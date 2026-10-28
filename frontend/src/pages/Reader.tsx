import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Document } from "react-pdf";
import {
  ArrowLeft, ZoomIn, ZoomOut, Maximize2, Settings as SettingsIcon, PanelRightClose, PanelRightOpen,
  Sparkles, Languages, Sigma, MessageSquare, Highlighter, X,
} from "lucide-react";
import { api, explainStream } from "../api";
import type {
  ActiveSentence, Citation, Effort, ExplainKind, Figure, Highlight, Layout, Paper, Reference, Settings, TranslatedBlock, UsageSummary,
} from "../types";
import PageView, { type SelectionInfo, type ViewMode } from "../components/PageView";
import SidePanel, { RefMeta, type AiPrefs, type ExplainState, type Tab } from "../components/SidePanel";

const fmtTok = (n: number) => (n >= 1_000_000 ? (n / 1_000_000).toFixed(2) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n));

interface CitePopup {
  cite: Citation;
  page: number;
  x: number;
  y: number;
  refs: Reference[] | null;
  meta: Record<number, Reference>;
}

const HL_COLORS: [string, string][] = [["yellow", "#fde68a"], ["green", "#a7f3d0"], ["blue", "#bfdbfe"], ["pink", "#fbcfe8"]];

export default function Reader({ settings, onOpenSettings, onSettingsChanged }: {
  settings: Settings | null; onOpenSettings: () => void; onSettingsChanged: (s: Settings) => void;
}) {
  const { id = "" } = useParams();
  const nav = useNavigate();
  const [paper, setPaper] = useState<Paper | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [pageSize, setPageSize] = useState({ w: 612, h: 792 });
  const [scale, setScale] = useState(1.3);
  const [mode, setMode] = useState<ViewMode>("original");
  const [lang, setLang] = useState("ko");
  const [layouts, setLayouts] = useState<Record<number, Layout>>({});
  const [trans, setTrans] = useState<Record<string, TranslatedBlock[]>>({});
  const [translating, setTranslating] = useState<Record<number, boolean>>({});
  const [visible, setVisible] = useState<Set<number>>(new Set());
  const [current, setCurrent] = useState(0);
  const [pageInput, setPageInput] = useState("1");
  const [panelOpen, setPanelOpen] = useState(true);
  const [tab, setTab] = useState<Tab>("summary");
  const [highlights, setHighlights] = useState<Highlight[]>([]);
  const [selection, setSelection] = useState<SelectionInfo | null>(null);
  const [cite, setCite] = useState<CitePopup | null>(null);
  const [active, setActive] = useState<ActiveSentence | null>(null);
  const [explain, setExplain] = useState<ExplainState>({ status: "idle", kind: "text", title: "", content: "" });
  const [chatDraft, setChatDraft] = useState("");
  const [error, setError] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState<Effort>("medium");
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [ctx, setCtx] = useState<{ sel: SelectionInfo | null; x: number; y: number; q: string } | null>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const els = useRef<Map<string, HTMLElement>>(new Map());
  const inflight = useRef<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const citeCache = useRef<Map<string, Reference[]>>(new Map());
  const syncLock = useRef<{ source: "pdf" | "pane"; until: number }>({ source: "pdf", until: 0 });
  // latest values for use inside scroll handlers
  const live = useRef({ mode, trans, lang, scale, tab, panelOpen });
  live.current = { mode, trans, lang, scale, tab, panelOpen };

  useEffect(() => {
    if (!settings) return;
    setLang(settings.target_lang);
    const prov = settings.providers[settings.default_provider];
    setModel(prov?.model || "");
    const listed = prov?.models || [];
    if (listed.length) setModelOptions(listed);
    if (prov?.key_set) {
      api.listModels(settings.default_provider).then((r) => setModelOptions(r.models)).catch(() => {});
    }
  }, [settings]);

  const refreshUsage = useCallback(() => api.usage(id).then(setUsage).catch(() => {}), [id]);

  useEffect(() => {
    api.getPaper(id).then(setPaper).catch(() => nav("/"));
    refreshHighlights();
    refreshUsage();
    const t = setInterval(refreshUsage, 20000);
    return () => clearInterval(t);
  }, [id]);

  const refreshHighlights = () => api.highlights(id).then(setHighlights).catch(() => {});

  const changeModel = async (m: string) => {
    setModel(m);
    if (!settings) return;
    try {
      const s = await api.saveSettings({ providers: { [settings.default_provider]: { model: m || settings.providers[settings.default_provider].model } } });
      onSettingsChanged(s);
    } catch {
      /* ignore */
    }
  };
  const prefs: AiPrefs = {
    model, effort, setModel: changeModel, setEffort, modelOptions,
    providerLabel: settings?.providers[settings.default_provider]?.label || "",
  };
  const registerEl = useCallback((key: string, el: HTMLElement | null) => {
    if (el) els.current.set(key, el);
    else els.current.delete(key);
  }, []);

  // ---------- layouts / translations for visible pages
  const onVisible = useCallback((p: number, v: boolean) => {
    setVisible((s) => {
      if (s.has(p) === v) return s;
      const n = new Set(s);
      v ? n.add(p) : n.delete(p);
      return n;
    });
  }, []);

  useEffect(() => {
    visible.forEach((p) => {
      const lk = `layout:${p}`;
      if (!layouts[p] && !inflight.current.has(lk)) {
        inflight.current.add(lk);
        api.layout(id, p).then((l) => setLayouts((s) => ({ ...s, [p]: l }))).catch(() => {}).finally(() => inflight.current.delete(lk));
      }
      if (mode !== "original") ensureTranslation(p, false);
    });
  }, [visible, mode, lang, id]);

  const ensureTranslation = (p: number, force: boolean) => {
    const key = `${p}:${lang}`;
    const ik = `tr:${key}`;
    if ((trans[key] && !force) || inflight.current.has(ik)) return;
    inflight.current.add(ik);
    setTranslating((s) => ({ ...s, [p]: true }));
    api
      .translatePage(id, p, lang, force)
      .then((t) => {
        setTrans((s) => ({ ...s, [key]: t }));
        refreshUsage();
      })
      .catch((e) => setError(String(e.message || e)))
      .finally(() => {
        inflight.current.delete(ik);
        setTranslating((s) => ({ ...s, [p]: false }));
      });
  };

  // ---------- scroll tracking: current page, visibility fallback, pane sync
  const pageAt = (y: number): { page: number; yPdf: number } => {
    let page = 0;
    pageRefs.current.forEach((el, i) => {
      if (el && el.offsetTop <= y) page = i;
    });
    const el = pageRefs.current[page];
    const yPdf = el ? Math.max(0, (y - el.offsetTop) / live.current.scale) : 0;
    return { page, yPdf };
  };

  const syncPaneToPdf = () => {
    const v = viewerRef.current;
    const pane = panelRef.current;
    const { mode: m, trans: tr, lang: lg, tab: tb, panelOpen: po } = live.current;
    if (!v || !pane || m !== "side" || tb !== "translation" || !po) return;
    const now = Date.now();
    if (syncLock.current.source === "pane" && now < syncLock.current.until) return;
    const { page, yPdf } = pageAt(v.scrollTop + 8);
    const blocks = tr[`${page}:${lg}`];
    let target: HTMLElement | undefined;
    if (blocks) {
      const b = blocks.find((x) => x.bbox[3] >= yPdf);
      target = b ? els.current.get(`${page}:${b.id}`) : els.current.get(`p${page + 1}`);
    }
    if (!target) target = els.current.get(`p${page}`);
    if (!target) return;
    syncLock.current = { source: "pdf", until: now + 300 };
    pane.scrollTop += target.getBoundingClientRect().top - pane.getBoundingClientRect().top - 8;
  };

  const syncFromScroll = useCallback(() => {
    const v = viewerRef.current;
    if (!v) return;
    const top = v.scrollTop + v.clientHeight * 0.3;
    const lo = v.scrollTop - 600;
    const hi = v.scrollTop + v.clientHeight + 600;
    let best = 0;
    const vis = new Set<number>();
    pageRefs.current.forEach((el, i) => {
      if (!el) return;
      if (el.offsetTop <= top) best = i;
      if (el.offsetTop + el.offsetHeight >= lo && el.offsetTop <= hi) vis.add(i);
    });
    setCurrent(best);
    setPageInput(String(best + 1));
    setVisible((s) => {
      let changed = false;
      const n = new Set(s);
      vis.forEach((p) => {
        if (!n.has(p)) {
          n.add(p);
          changed = true;
        }
      });
      return changed ? n : s;
    });
  }, []);

  useEffect(() => {
    const v = viewerRef.current;
    if (!v || !numPages) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        syncFromScroll();
        syncPaneToPdf();
        setSelection(null);
        setCite(null);
      }, 30);
    };
    v.addEventListener("scroll", onScroll, { passive: true });
    const t = setTimeout(syncFromScroll, 300);
    return () => {
      v.removeEventListener("scroll", onScroll);
      clearTimeout(timer);
      clearTimeout(t);
    };
  }, [numPages, syncFromScroll]);

  // pane → pdf
  useEffect(() => {
    const pane = panelRef.current;
    if (!pane || mode !== "side" || tab !== "translation" || !panelOpen) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const now = Date.now();
        if (syncLock.current.source === "pdf" && now < syncLock.current.until) return;
        const v = viewerRef.current;
        if (!v) return;
        const paneTop = pane.getBoundingClientRect().top + 8;
        const items = Array.from(pane.querySelectorAll<HTMLElement>("[data-key]"));
        const first = items.find((el) => el.getBoundingClientRect().bottom >= paneTop);
        if (!first) return;
        const page = Number(first.dataset.page);
        const topPdf = Number(first.dataset.top || 0);
        const pageEl = pageRefs.current[page];
        if (!pageEl) return;
        syncLock.current = { source: "pane", until: now + 300 };
        v.scrollTo({ top: pageEl.offsetTop + topPdf * live.current.scale - 12 });
      }, 30);
    };
    pane.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      pane.removeEventListener("scroll", onScroll);
      clearTimeout(timer);
    };
  }, [mode, tab, panelOpen]);

  const changeMode = (m: ViewMode) => {
    setMode(m);
    setActive(null);
    if (m === "side") {
      setPanelOpen(true);
      setTab("translation");
      setTimeout(() => {
        syncFromScroll();
        syncPaneToPdf();
      }, 50);
    }
  };

  const goToPage = (p: number) => {
    const el = pageRefs.current[p];
    if (el && viewerRef.current) viewerRef.current.scrollTo({ top: el.offsetTop - 12, behavior: "smooth" });
  };

  const fitWidth = () => {
    const v = viewerRef.current;
    if (!v) return;
    setScale(Math.max(0.5, Math.min(3, (v.clientWidth - 48) / pageSize.w)));
  };

  // ---------- sentence linking
  const findSentence = (page: number, sid: string) => {
    const blocks = trans[`${page}:${lang}`];
    if (!blocks) return null;
    for (const b of blocks) {
      const s = b.sentences?.find((x) => x.id === sid);
      if (s) return s;
    }
    return null;
  };

  const hoverFromPdf = useCallback((page: number, sid: string | null) => {
    if (!sid) {
      setActive(null);
      return;
    }
    const s = findSentenceRef.current(page, sid);
    if (!s) return;
    setActive({ page, sid, rects: s.rects });
    const pane = panelRef.current;
    const el = els.current.get(`${page}:${sid}`);
    if (pane && el) {
      const pr = pane.getBoundingClientRect();
      const er = el.getBoundingClientRect();
      if (er.top < pr.top + 40 || er.bottom > pr.bottom - 40) {
        syncLock.current = { source: "pdf", until: Date.now() + 400 };
        pane.scrollTop += er.top - pr.top - pane.clientHeight / 2;
      }
    }
  }, []);
  const findSentenceRef = useRef(findSentence);
  findSentenceRef.current = findSentence;

  const hoverFromPane = (page: number, sid: string | null) => {
    if (!sid) {
      setActive(null);
      return;
    }
    const s = findSentence(page, sid);
    if (s) setActive({ page, sid, rects: s.rects });
  };

  const clickFromPane = (page: number, sid: string) => {
    const s = findSentence(page, sid);
    const pageEl = pageRefs.current[page];
    const v = viewerRef.current;
    if (!s || !pageEl || !v) return;
    setActive({ page, sid, rects: s.rects });
    const top = s.rects.length ? s.rects[0][1] : 0;
    syncLock.current = { source: "pane", until: Date.now() + 600 };
    v.scrollTo({ top: pageEl.offsetTop + top * scale - 140, behavior: "smooth" });
  };

  // ---------- explain
  const runExplain = async (
    kind: ExplainKind,
    payload: { page: number; text?: string; figure_id?: string; refs?: unknown[]; question?: string },
    title: string,
    extras: { quote?: string; figureUrl?: string } = {},
  ) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setPanelOpen(true);
    setTab("explain");
    setExplain({ status: "streaming", kind, title, content: "", payload, ...extras });
    try {
      await explainStream(id, { ...payload, kind, lang, model: model || null, effort }, (t) => setExplain((s) => ({ ...s, content: s.content + t })), ac.signal);
      setExplain((s) => ({ ...s, status: "done" }));
      refreshUsage();
    } catch (e) {
      if (ac.signal.aborted) {
        setExplain((s) => ({ ...s, status: "done" }));
        return;
      }
      setExplain((s) => ({ ...s, status: "error", error: String((e as Error).message || e) }));
    }
  };

  const followUp = (question: string) => {
    const p = explain.payload as { page: number; text?: string; figure_id?: string; refs?: unknown[] } | undefined;
    if (!p) return;
    runExplain(explain.kind as ExplainKind, { ...p, question }, `${explain.title} · ${question}`, { quote: explain.quote, figureUrl: explain.figureUrl });
  };

  const onFigure = (fig: Figure, page: number) => {
    const label = fig.kind === "table" ? "표" : "그림";
    runExplain(fig.kind, { page, figure_id: fig.id }, `${label} 설명 — ${fig.caption ? fig.caption.slice(0, 80) : `${page + 1}쪽`}`, {
      figureUrl: api.figureUrl(id, fig.id),
    });
  };

  // ---------- selection toolbar actions
  const clearSelection = () => {
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  };
  const selExplain = (kind: ExplainKind) => {
    if (!selection) return;
    const titles: Record<string, string> = { text: "선택 구절 설명", equation: "수식 풀이", term: "용어 설명" };
    runExplain(kind, { page: selection.page, text: selection.text }, titles[kind] || "설명", { quote: selection.text });
    clearSelection();
  };
  const selTranslate = async () => {
    if (!selection) return;
    const sel = selection;
    clearSelection();
    setPanelOpen(true);
    setTab("explain");
    setExplain({ status: "streaming", kind: "translate", title: "선택 구절 번역", quote: sel.text, content: "" });
    try {
      const r = await api.translateText(id, sel.text, lang, model);
      setExplain((s) => ({ ...s, status: "done", content: r.t }));
      refreshUsage();
    } catch (e) {
      setExplain((s) => ({ ...s, status: "error", error: String((e as Error).message || e) }));
    }
  };
  const selAsk = () => {
    if (!selection) return;
    setChatDraft(`> ${selection.text.slice(0, 600)}\n\n`);
    setPanelOpen(true);
    setTab("chat");
    clearSelection();
  };
  const selHighlight = async (color: string) => {
    if (!selection) return;
    await api.addHighlight(id, { page: selection.page, rects: selection.rects, color, text: selection.text, note: "" });
    clearSelection();
    refreshHighlights();
  };

  // ---------- right-click menu
  const openCtx = (sel: SelectionInfo | null, x: number, y: number) => {
    setCite(null);
    setSelection(null);
    setCtx({ sel, x: Math.min(x, window.innerWidth - 320), y: Math.min(y, window.innerHeight - 320), q: "" });
  };
  const ctxRun = (fn: () => void) => {
    fn();
    setCtx(null);
    window.getSelection()?.removeAllRanges();
  };
  const ctxAsk = () => {
    if (!ctx) return;
    const q = ctx.q.trim();
    if (!q) return;
    if (ctx.sel) {
      runExplain("text", { page: ctx.sel.page, text: ctx.sel.text, question: q }, `질문: ${q.slice(0, 60)}`, { quote: ctx.sel.text });
    } else {
      setChatDraft(q);
      setPanelOpen(true);
      setTab("chat");
    }
    ctxRun(() => {});
  };

  // ---------- citations
  const onCitation = async (c: Citation, page: number, anchor: DOMRect) => {
    const x = Math.min(anchor.left, window.innerWidth - 400);
    const y = anchor.bottom + 6;
    const cached = citeCache.current.get(c.text);
    setCite({ cite: c, page, x, y, refs: cached ?? null, meta: {} });
    let refs = cached;
    if (!refs) {
      try {
        refs = await api.resolveCitation(id, { text: c.text, style: c.style, refs: c.refs, authors: c.authors });
      } catch {
        refs = [];
      }
      citeCache.current.set(c.text, refs);
      setCite((s) => (s && s.cite.text === c.text ? { ...s, refs: refs! } : s));
    }
    for (const r of refs.slice(0, 3)) {
      api.lookupReference(id, r.n).then((m) => setCite((s) => (s && s.cite.text === c.text ? { ...s, meta: { ...s.meta, [r.n]: m } } : s))).catch(() => {});
    }
  };

  const explainCitation = () => {
    if (!cite) return;
    const lay = layouts[cite.page];
    const block = lay?.blocks.find((b) => b.text.includes(cite.cite.text));
    let sentence = block?.text || cite.cite.text;
    if (sentence.length > 700) {
      const i = sentence.indexOf(cite.cite.text);
      sentence = sentence.slice(Math.max(0, i - 350), i + 350);
    }
    runExplain("citation", { page: cite.page, text: sentence, refs: cite.refs || [] }, `인용 ${cite.cite.text} 맥락 설명`, { quote: sentence });
    setCite(null);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setCite(null);
        setCtx(null);
        clearSelection();
      }
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (!t.closest(".cite-popup") && !t.closest(".cite-hit")) setCite(null);
      if (!t.closest(".sel-toolbar") && !t.closest(".page-wrap")) setSelection(null);
      if (!t.closest(".ctx-menu")) setCtx(null);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, []);

  const changeLang = async (l: string) => {
    setLang(l);
    try {
      const s = await api.saveSettings({ target_lang: l });
      onSettingsChanged(s);
    } catch {
      /* ignore */
    }
  };

  const fileUrl = useMemo(() => api.fileUrl(id), [id]);
  const hlByPage = useMemo(() => {
    const m: Record<number, Highlight[]> = {};
    highlights.forEach((h) => (m[h.page] ||= []).push(h));
    return m;
  }, [highlights]);

  const noKey = settings && !Object.values(settings.providers).some((p) => p.key_set && p.model);

  return (
    <div className="reader">
      <div className="toolbar">
        <button className="btn ghost" onClick={() => nav("/")} title="라이브러리"><ArrowLeft size={18} /></button>
        <div className="title" title={paper?.title}>{paper?.title || "…"}</div>
        <div className="sep" />
        <input
          className="page-input"
          value={pageInput}
          onChange={(e) => setPageInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              const p = parseInt(pageInput, 10);
              if (p >= 1 && p <= numPages) goToPage(p - 1);
            }
          }}
        />
        <span className="muted">/ {numPages}</span>
        <div className="sep" />
        <button className="btn ghost" onClick={() => setScale((s) => Math.max(0.5, s - 0.15))} title="축소"><ZoomOut size={16} /></button>
        <span className="muted small" style={{ width: 40, textAlign: "center" }}>{Math.round(scale * 100)}%</span>
        <button className="btn ghost" onClick={() => setScale((s) => Math.min(3, s + 0.15))} title="확대"><ZoomIn size={16} /></button>
        <button className="btn ghost" onClick={fitWidth} title="너비 맞춤"><Maximize2 size={16} /></button>
        <div className="sep" />
        <div className="seg" title="원문 / 나란히 번역(오른쪽 패널, 스크롤 동기화) / 덮어쓰기(원문 위치에 번역)">
          <button className={mode === "original" ? "on" : ""} onClick={() => changeMode("original")}>원문</button>
          <button className={mode === "side" ? "on" : ""} onClick={() => changeMode("side")}>나란히 번역</button>
          <button className={mode === "overlay" ? "on" : ""} onClick={() => changeMode("overlay")}>덮어쓰기</button>
        </div>
        <select value={lang} onChange={(e) => changeLang(e.target.value)} title="번역 언어">
          {Object.entries(settings?.languages || { ko: "한국어" }).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
        <div className="sep" />
        <select value={model} onChange={(e) => changeModel(e.target.value)} title={`모델 (${prefs.providerLabel})`} style={{ maxWidth: 150 }}>
          <option value="">기본 모델</option>
          {modelOptions.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        {usage && (
          <div className="usage-pill" title="토큰 사용량">
            오늘 <b>{fmtTok(usage.today.input + usage.today.output)}</b>
            {usage.paper && <>· 이 논문 <b>{fmtTok(usage.paper.input + usage.paper.output)}</b></>}
            <div className="usage-pop">
              <table>
                <tbody>
                  <tr><td>오늘 입력 / 출력</td><td className="num">{fmtTok(usage.today.input)} / {fmtTok(usage.today.output)} · {usage.today.calls}회</td></tr>
                  {usage.paper && <tr><td>이 논문 입력 / 출력</td><td className="num">{fmtTok(usage.paper.input)} / {fmtTok(usage.paper.output)} · {usage.paper.calls}회</td></tr>}
                  <tr><td>전체 누적</td><td className="num">{fmtTok(usage.total.input + usage.total.output)}</td></tr>
                  {usage.by_kind_today.map((k) => (
                    <tr key={k.kind}><td className="muted">· {k.kind}</td><td className="num muted">{fmtTok(k.input + k.output)}</td></tr>
                  ))}
                  {usage.by_provider_today.map((p) => (
                    <tr key={p.provider + p.model}><td className="muted">· {p.provider} {p.model}</td><td className="num muted">{fmtTok(p.input + p.output)}</td></tr>
                  ))}
                </tbody>
              </table>
              <div className="muted" style={{ marginTop: 6 }}>입력 토큰은 논문 본문 길이에 비례합니다. ChatGPT 구독은 토큰이 아닌 앱별 사용 한도로 집계됩니다.</div>
            </div>
          </div>
        )}
        <button className="btn ghost" onClick={onOpenSettings} title="설정"><SettingsIcon size={18} /></button>
        <button className="btn ghost" onClick={() => setPanelOpen((v) => !v)} title="패널 접기/펴기">
          {panelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
        </button>
      </div>

      {(error || noKey) && (
        <div className="notice" style={{ margin: 0, borderRadius: 0 }}>
          {noKey ? "AI 기능을 쓰려면 설정에서 ChatGPT 계정으로 로그인하거나 API 키를 입력하세요." : error}
          <button className="btn small ghost" onClick={() => setError("")}><X size={14} /></button>
        </div>
      )}

      <div className="reader-body">
        <div className="viewer" ref={viewerRef}>
          <Document
            file={fileUrl}
            onLoadSuccess={async (pdf) => {
              setNumPages(pdf.numPages);
              const p1 = await pdf.getPage(1);
              const vp = p1.getViewport({ scale: 1 });
              setPageSize({ w: vp.width, h: vp.height });
              const v = viewerRef.current;
              if (v) setScale(Math.max(0.6, Math.min(2, (v.clientWidth - 48) / vp.width)));
            }}
            onLoadError={(e) => setError("PDF를 열 수 없습니다: " + e.message)}
            loading={<div className="muted" style={{ padding: 40 }}>PDF 불러오는 중…</div>}
          >
            <div className="pages">
              {Array.from({ length: numPages }, (_, i) => {
                const lay = layouts[i];
                return (
                  <PageView
                    key={i}
                    pageIndex={i}
                    scale={scale}
                    pageWidth={lay?.width || pageSize.w}
                    pageHeight={lay?.height || pageSize.h}
                    layout={lay}
                    translation={trans[`${i}:${lang}`]}
                    translating={!!translating[i]}
                    mode={mode}
                    highlights={hlByPage[i] || []}
                    activeSid={active && active.page === i ? active.sid : null}
                    onVisible={onVisible}
                    onSelection={setSelection}
                    onFigure={onFigure}
                    onCitation={onCitation}
                    onHighlightClick={(h) => {
                      setPanelOpen(true);
                      setTab("notes");
                      void h;
                    }}
                    onHoverSentence={hoverFromPdf}
                    onContextMenu={openCtx}
                    registerRef={(el) => (pageRefs.current[i] = el)}
                  />
                );
              })}
            </div>
          </Document>
        </div>

        <div className={"side" + (panelOpen ? "" : " collapsed")}>
          {panelOpen && (
            <SidePanel
              paperId={id}
              lang={lang}
              tab={tab}
              setTab={setTab}
              currentPage={current}
              explain={explain}
              onFollowUp={followUp}
              onStopExplain={() => abortRef.current?.abort()}
              numPages={numPages}
              trans={trans}
              translating={translating}
              active={active}
              onHoverSentence={hoverFromPane}
              onClickSentence={clickFromPane}
              registerEl={registerEl}
              onTranslatePage={(p, force) => ensureTranslation(p, force)}
              panelRef={panelRef}
              highlights={highlights}
              onHighlightsChanged={refreshHighlights}
              onGoToPage={goToPage}
              chatDraft={chatDraft}
              setChatDraft={setChatDraft}
              prefs={prefs}
              onUsageChanged={refreshUsage}
            />
          )}
        </div>
      </div>

      {ctx && (
        <div className="ctx-menu" style={{ left: ctx.x, top: ctx.y }} onMouseDown={(e) => e.stopPropagation()}>
          {ctx.sel ? (
            <>
              <div className="ctx-quote">“{ctx.sel.text.slice(0, 140)}{ctx.sel.text.length > 140 ? "…" : ""}”</div>
              <button className="ctx-item" onClick={() => ctxRun(() => runExplain("text", { page: ctx.sel!.page, text: ctx.sel!.text }, "선택 구절 설명", { quote: ctx.sel!.text }))}><Sparkles size={14} /> 설명</button>
              <button className="ctx-item" onClick={() => ctxRun(() => { setSelection(ctx.sel); setTimeout(selTranslate, 0); })}><Languages size={14} /> 번역</button>
              <button className="ctx-item" onClick={() => ctxRun(() => runExplain("equation", { page: ctx.sel!.page, text: ctx.sel!.text }, "수식 풀이", { quote: ctx.sel!.text }))}><Sigma size={14} /> 수식 풀이</button>
              <button className="ctx-item" onClick={() => ctxRun(() => { setChatDraft(`> ${ctx.sel!.text.slice(0, 600)}\n\n`); setPanelOpen(true); setTab("chat"); })}><MessageSquare size={14} /> 토론으로 보내기</button>
              <div className="ctx-row">
                <Highlighter size={14} /> 형광펜
                {HL_COLORS.map(([name, hex]) => (
                  <span key={name} className="swatch" style={{ background: hex }} title={name}
                    onClick={() => ctxRun(async () => { await api.addHighlight(id, { page: ctx.sel!.page, rects: ctx.sel!.rects, color: name, text: ctx.sel!.text, note: "" }); refreshHighlights(); })} />
                ))}
              </div>
            </>
          ) : (
            <div className="ctx-quote">선택된 텍스트가 없습니다. 아래에 질문을 입력하면 토론 탭으로 보냅니다.</div>
          )}
          <div className="ctx-ask">
            <input
              autoFocus
              value={ctx.q}
              placeholder={ctx.sel ? "이 부분에 대해 질문…" : "논문에 대해 질문…"}
              onChange={(e) => setCtx((c) => (c ? { ...c, q: e.target.value } : c))}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) ctxAsk();
              }}
            />
            <button className="btn primary small" onClick={ctxAsk}>질문</button>
          </div>
        </div>
      )}

      {selection && (
        <div
          className="sel-toolbar"
          style={{ left: Math.min(selection.anchor.left, window.innerWidth - 420), top: selection.anchor.bottom + 8 }}
          onMouseDown={(e) => e.preventDefault()}
        >
          <button onClick={() => selExplain("text")}><Sparkles size={14} /> 설명</button>
          <button onClick={selTranslate}><Languages size={14} /> 번역</button>
          <button onClick={() => selExplain("equation")}><Sigma size={14} /> 수식</button>
          <button onClick={selAsk}><MessageSquare size={14} /> 질문</button>
          <span style={{ width: 1, background: "rgba(255,255,255,0.25)", margin: "4px 2px" }} />
          {HL_COLORS.map(([name, hex]) => (
            <button key={name} onClick={() => selHighlight(name)} title={`형광펜 (${name})`}>
              <Highlighter size={13} /><span className="swatch" style={{ background: hex }} />
            </button>
          ))}
        </div>
      )}

      {cite && (
        <div className="cite-popup" style={{ left: cite.x, top: Math.min(cite.y, window.innerHeight - 380) }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <strong>인용 {cite.cite.text}</strong>
            <button className="btn ghost small" onClick={() => setCite(null)}><X size={14} /></button>
          </div>
          {cite.refs === null && <div className="muted small">참고문헌 찾는 중…</div>}
          {cite.refs && cite.refs.length === 0 && <div className="muted small">참고문헌 목록에서 해당 항목을 찾지 못했습니다.</div>}
          {cite.refs?.map((r) => (
            <div key={r.n} className="ref">
              <span className="ref-n">[{r.n}]</span>
              <span className="ref-raw">{r.raw.slice(0, 220)}{r.raw.length > 220 ? "…" : ""}</span>
              <RefMeta r={cite.meta[r.n]} />
            </div>
          ))}
          <div className="panel-actions" style={{ marginTop: 6, marginBottom: 0 }}>
            <button className="btn small primary" onClick={explainCitation} disabled={!cite.refs}>
              <Sparkles size={13} /> 왜 인용했는지 설명
            </button>
            <button className="btn small" onClick={() => { setPanelOpen(true); setTab("citations"); setCite(null); }}>전체 목록</button>
          </div>
        </div>
      )}
    </div>
  );
}
