import { useEffect, useRef, useState } from "react";
import {
  FileText, MessageSquare, Sparkles, Languages, Quote, StickyNote, Send, RefreshCw, Square, Trash2, ExternalLink,
} from "lucide-react";
import { api, streamSSE } from "../api";
import Markdown from "./Markdown";
import type { ActiveSentence, ChatMessage, Effort, ExplainKind, Highlight, Reference, TranslatedBlock } from "../types";

export interface AiPrefs {
  model: string;                 // "" = provider default
  effort: Effort;
  setModel: (m: string) => void;
  setEffort: (e: Effort) => void;
  modelOptions: string[];
  providerLabel: string;
}

export function AiPrefsBar({ prefs, compact }: { prefs: AiPrefs; compact?: boolean }) {
  return (
    <div className="ai-prefs">
      {!compact && <span>{prefs.providerLabel}</span>}
      <select value={prefs.model} onChange={(e) => prefs.setModel(e.target.value)} title="모델">
        <option value="">기본 모델</option>
        {prefs.modelOptions.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
      <select value={prefs.effort} onChange={(e) => prefs.setEffort(e.target.value as Effort)} title="추론 노력(생각하는 양)">
        <option value="low">빠르게</option>
        <option value="medium">보통</option>
        <option value="high">깊게</option>
      </select>
    </div>
  );
}

export type Tab = "summary" | "chat" | "explain" | "translation" | "citations" | "notes";

export interface ExplainState {
  status: "idle" | "streaming" | "done" | "error";
  kind: ExplainKind | "translate";
  title: string;
  quote?: string;
  figureUrl?: string;
  content: string;
  error?: string;
  payload?: Record<string, unknown>;
}

interface Props {
  paperId: string;
  lang: string;
  tab: Tab;
  setTab: (t: Tab) => void;
  currentPage: number;
  explain: ExplainState;
  onFollowUp: (question: string) => void;
  onStopExplain: () => void;
  numPages: number;
  trans: Record<string, TranslatedBlock[]>;
  translating: Record<number, boolean>;
  active: ActiveSentence | null;
  onHoverSentence: (page: number, sid: string | null) => void;
  onClickSentence: (page: number, sid: string) => void;
  registerEl: (key: string, el: HTMLElement | null) => void;
  onTranslatePage: (page: number, force: boolean) => void;
  panelRef: React.RefObject<HTMLDivElement>;
  highlights: Highlight[];
  onHighlightsChanged: () => void;
  onGoToPage: (page: number) => void;
  chatDraft: string;
  setChatDraft: (s: string) => void;
  prefs: AiPrefs;
  onUsageChanged: () => void;
}

export default function SidePanel(p: Props) {
  const tabs: [Tab, string, JSX.Element][] = [
    ["summary", "요약", <FileText size={14} />],
    ["chat", "토론", <MessageSquare size={14} />],
    ["explain", "설명", <Sparkles size={14} />],
    ["translation", "번역", <Languages size={14} />],
    ["citations", "인용", <Quote size={14} />],
    ["notes", "노트", <StickyNote size={14} />],
  ];
  return (
    <>
      <div className="tabs">
        {tabs.map(([k, label, icon]) => (
          <button key={k} className={p.tab === k ? "on" : ""} onClick={() => p.setTab(k)}>
            {icon} {label}
          </button>
        ))}
      </div>
      <div className="panel" ref={p.panelRef}>
        {p.tab === "summary" && <SummaryTab paperId={p.paperId} lang={p.lang} prefs={p.prefs} onUsageChanged={p.onUsageChanged} />}
        {p.tab === "chat" && (
          <ChatTab paperId={p.paperId} lang={p.lang} draft={p.chatDraft} setDraft={p.setChatDraft} prefs={p.prefs} onUsageChanged={p.onUsageChanged} />
        )}
        {p.tab === "explain" && <ExplainTab state={p.explain} onFollowUp={p.onFollowUp} onStop={p.onStopExplain} />}
        {p.tab === "translation" && (
          <TranslationPane
            numPages={p.numPages}
            lang={p.lang}
            trans={p.trans}
            translating={p.translating}
            active={p.active}
            currentPage={p.currentPage}
            onHover={p.onHoverSentence}
            onClick={p.onClickSentence}
            registerEl={p.registerEl}
            onTranslatePage={p.onTranslatePage}
          />
        )}
        {p.tab === "citations" && <CitationsTab paperId={p.paperId} />}
        {p.tab === "notes" && (
          <NotesTab paperId={p.paperId} highlights={p.highlights} onChanged={p.onHighlightsChanged} onGoToPage={p.onGoToPage} />
        )}
      </div>
    </>
  );
}

/* ------------------------------------------------------------ summary */
function SummaryTab({ paperId, lang, prefs, onUsageChanged }: { paperId: string; lang: string; prefs: AiPrefs; onUsageChanged: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "streaming" | "error">("loading");
  const [err, setErr] = useState("");
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    setStatus("loading");
    api.summary(paperId, lang).then((r) => {
      setText(r.summary);
      setStatus("idle");
    });
    return () => abort.current?.abort();
  }, [paperId, lang]);

  const generate = async () => {
    abort.current?.abort();
    const ac = new AbortController();
    abort.current = ac;
    setText("");
    setStatus("streaming");
    setErr("");
    try {
      await streamSSE(`/api/papers/${paperId}/summary`, { lang, model: prefs.model || null, effort: prefs.effort }, (t) => setText((s) => (s || "") + t), ac.signal);
      setStatus("idle");
      onUsageChanged();
    } catch (e) {
      if (ac.signal.aborted) return;
      setErr(String((e as Error).message || e));
      setStatus("error");
    }
  };

  return (
    <div>
      <AiPrefsBar prefs={prefs} />
      <div className="panel-actions">
        <button className="btn small primary" onClick={generate} disabled={status === "streaming"}>
          <Sparkles size={14} /> {text ? "다시 요약" : "논문 요약 생성"}
        </button>
        {status === "streaming" && (
          <button className="btn small" onClick={() => abort.current?.abort()}>
            <Square size={12} /> 중지
          </button>
        )}
      </div>
      {err && <div className="error">{err}</div>}
      {status === "loading" && <div className="muted">불러오는 중…</div>}
      {text ? (
        <div className={status === "streaming" ? "cursor" : ""}>
          <Markdown>{text}</Markdown>
        </div>
      ) : (
        status === "idle" && <div className="muted">아직 요약이 없습니다. 버튼을 눌러 논문 전체를 요약하세요.</div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ chat */
function ChatTab({ paperId, lang, draft, setDraft, prefs, onUsageChanged }: {
  paperId: string; lang: string; draft: string; setDraft: (s: string) => void; prefs: AiPrefs; onUsageChanged: () => void;
}) {
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.chat(paperId).then((r) => setMsgs(r.messages));
    return () => abort.current?.abort();
  }, [paperId]);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [msgs]);
  useEffect(() => {
    if (draft) taRef.current?.focus();
  }, [draft]);

  const send = async () => {
    const q = draft.trim();
    if (!q || busy) return;
    setDraft("");
    setErr("");
    const next: ChatMessage[] = [...msgs, { role: "user", content: q }, { role: "assistant", content: "" }];
    setMsgs(next);
    setBusy(true);
    const ac = new AbortController();
    abort.current = ac;
    let answer = "";
    try {
      await streamSSE(
        `/api/papers/${paperId}/chat`,
        { messages: next.slice(0, -1), lang, model: prefs.model || null, effort: prefs.effort },
        (t) => {
          answer += t;
          setMsgs((m) => [...m.slice(0, -1), { role: "assistant", content: answer }]);
        },
        ac.signal,
      );
      const final: ChatMessage[] = [...next.slice(0, -1), { role: "assistant", content: answer }];
      setMsgs(final);
      api.saveChat(paperId, final);
      onUsageChanged();
    } catch (e) {
      if (!ac.signal.aborted) setErr(String((e as Error).message || e));
      setMsgs((m) => (m[m.length - 1]?.content ? m : m.slice(0, -1)));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    if (!confirm("대화 기록을 지울까요?")) return;
    setMsgs([]);
    api.saveChat(paperId, []);
  };

  return (
    <div className="chat">
      <div className="chat-list" ref={listRef}>
        {msgs.length === 0 && (
          <div className="muted">
            논문 전체 내용을 바탕으로 질문하고 토론하세요. 예: “이 연구의 핵심 가정은 무엇인가요?”, “Table 2의 결과가 가설을 뒷받침하나요?”
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === "user" ? m.content : <div className={busy && i === msgs.length - 1 ? "cursor" : ""}><Markdown>{m.content || " "}</Markdown></div>}
          </div>
        ))}
        {err && <div className="error">{err}</div>}
      </div>
      <div style={{ paddingTop: 6 }}><AiPrefsBar prefs={prefs} /></div>
      <div className="chat-input" style={{ paddingTop: 0, borderTop: 0 }}>
        <textarea
          ref={taRef}
          value={draft}
          placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
        />
        {busy ? (
          <button className="btn" onClick={() => abort.current?.abort()} title="중지"><Square size={14} /></button>
        ) : (
          <button className="btn primary" onClick={send} title="전송"><Send size={14} /></button>
        )}
        <button className="btn ghost" onClick={clear} title="대화 지우기"><Trash2 size={14} /></button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------ explain */
function ExplainTab({ state, onFollowUp, onStop }: { state: ExplainState; onFollowUp: (q: string) => void; onStop: () => void }) {
  const [q, setQ] = useState("");
  if (state.status === "idle") {
    return (
      <div className="muted">
        본문에서 문장을 드래그하면 <b>설명·번역·수식 풀이</b> 버튼이 나타납니다. 그림이나 표 위에 마우스를 올리면 <b>그림 설명</b> 버튼이, 인용 번호를 클릭하면 참고문헌 정보가 표시됩니다.
      </div>
    );
  }
  return (
    <div>
      <h4>{state.title}</h4>
      {state.figureUrl && <img className="fig-preview" src={state.figureUrl} alt="figure" />}
      {state.quote && <div className="quote">{state.quote}</div>}
      {state.error && <div className="error">{state.error}</div>}
      <div className={state.status === "streaming" ? "cursor" : ""}>
        <Markdown>{state.content}</Markdown>
      </div>
      <div className="panel-actions" style={{ marginTop: 10 }}>
        {state.status === "streaming" && (
          <button className="btn small" onClick={onStop}><Square size={12} /> 중지</button>
        )}
      </div>
      {state.kind !== "translate" && state.status !== "streaming" && (
        <div className="chat-input">
          <textarea
            value={q}
            placeholder="이 내용에 대해 더 질문하기"
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (q.trim()) {
                  onFollowUp(q.trim());
                  setQ("");
                }
              }
            }}
          />
          <button
            className="btn primary"
            onClick={() => {
              if (q.trim()) {
                onFollowUp(q.trim());
                setQ("");
              }
            }}
          >
            <Send size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ translation (side-by-side, scroll-synced) */
function TranslationPane({ numPages, lang, trans, translating, active, currentPage, onHover, onClick, registerEl, onTranslatePage }: {
  numPages: number;
  lang: string;
  trans: Record<string, TranslatedBlock[]>;
  translating: Record<number, boolean>;
  active: ActiveSentence | null;
  currentPage: number;
  onHover: (page: number, sid: string | null) => void;
  onClick: (page: number, sid: string) => void;
  registerEl: (key: string, el: HTMLElement | null) => void;
  onTranslatePage: (page: number, force: boolean) => void;
}) {
  const [showOrig, setShowOrig] = useState(false);
  const cur = trans[`${currentPage}:${lang}`];
  return (
    <div className="tr-pane">
      <div className="tr-tools">
        <span className="muted small" style={{ alignSelf: "center" }}>{currentPage + 1}쪽 보는 중</span>
        {!cur && (
          <button className="btn small primary" onClick={() => onTranslatePage(currentPage, false)} disabled={!!translating[currentPage]}>
            <Languages size={14} /> {translating[currentPage] ? "번역 중…" : "이 페이지 번역"}
          </button>
        )}
        {cur && (
          <button className="btn small" onClick={() => onTranslatePage(currentPage, true)} disabled={!!translating[currentPage]} title="이 페이지 다시 번역">
            <RefreshCw size={12} /> 다시 번역
          </button>
        )}
        <button className={"btn small" + (showOrig ? " active" : "")} onClick={() => setShowOrig((v) => !v)}>원문 함께</button>
      </div>
      <div className="muted small" style={{ marginBottom: 8 }}>
        원문과 함께 스크롤됩니다. 번역 문장에 마우스를 올리면 원문 위치가, 원문 위에 올리면 번역 문장이 표시됩니다. 클릭하면 원문으로 이동합니다.
      </div>
      {Array.from({ length: numPages }, (_, i) => {
        const blocks = trans[`${i}:${lang}`];
        return (
          <div key={i}>
            <div className="tr-page" ref={(el) => registerEl(`p${i}`, el)} data-key={`p${i}`} data-page={i} data-top="0">
              p.{i + 1}
              {translating[i] && <span className="tag"> 번역 중…</span>}
            </div>
            {!blocks && !translating[i] && (
              <div className="muted small" style={{ margin: "4px 0 10px" }}>
                아직 번역되지 않은 페이지입니다. 스크롤해서 보이면 자동으로 번역됩니다.{" "}
                <a href="#" onClick={(e) => { e.preventDefault(); onTranslatePage(i, false); }}>지금 번역</a>
              </div>
            )}
            {blocks?.map((b) => (
              <div key={b.id}>
                <p
                  className={`tr-par ${b.kind}`}
                  ref={(el) => registerEl(`${i}:${b.id}`, el)}
                  data-key={`${i}:${b.id}`}
                  data-page={i}
                  data-top={b.bbox[1]}
                >
                  {b.sentences.map((s, k) => {
                    const tp = s.ref ? s.ref.page : i;
                    const tsid = s.ref ? s.ref.sid : s.id;
                    const isActive = !!active && active.page === tp && active.sid === tsid;
                    return (
                      <span key={s.id}>
                        <span
                          className={(s.ref ? "sent-ref" : "sent") + (isActive ? " active" : "")}
                          ref={(el) => registerEl(`${i}:${s.id}`, el)}
                          onMouseEnter={() => onHover(tp, tsid)}
                          onMouseLeave={() => onHover(tp, null)}
                          onClick={() => onClick(tp, tsid)}
                          title={s.ref ? `원문: ${s.text}` : s.text}
                        >
                          {s.ref
                            ? `↑ p.${s.ref.page + 1}에서 이어지는 문장`
                            : s.t || <span className="muted">{s.text}</span>}
                        </span>
                        {s.cont && <span className="cont-badge" title="이 문장은 다음 쪽까지 이어집니다">→ p.{s.cont.page + 1}</span>}
                        {k < b.sentences.length - 1 ? " " : ""}
                      </span>
                    );
                  })}
                </p>
                {showOrig && <div className="tr-orig">{b.text}</div>}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------ citations */
function CitationsTab({ paperId }: { paperId: string }) {
  const [refs, setRefs] = useState<Reference[]>([]);
  const [open, setOpen] = useState<number | null>(null);
  const [meta, setMeta] = useState<Record<number, Reference>>({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.references(paperId).then((r) => {
      setRefs(r);
      setLoading(false);
    });
  }, [paperId]);

  const toggle = async (n: number) => {
    if (open === n) {
      setOpen(null);
      return;
    }
    setOpen(n);
    if (!meta[n]) {
      const r = await api.lookupReference(paperId, n);
      setMeta((m) => ({ ...m, [n]: r }));
    }
  };

  if (loading) return <div className="muted">참고문헌을 추출하는 중…</div>;
  if (!refs.length) return <div className="muted">참고문헌 목록을 찾지 못했습니다. (References 섹션이 없거나 형식이 특이한 논문)</div>;
  return (
    <div className="ref-list">
      <div className="muted small" style={{ marginBottom: 8 }}>{refs.length}개 참고문헌 · 항목을 클릭하면 CrossRef에서 서지정보를 가져옵니다.</div>
      {refs.map((r) => (
        <div key={r.n} className="ref-item" onClick={() => toggle(r.n)} style={{ cursor: "pointer" }}>
          <span className="ref-n">[{r.n}]</span>
          {r.raw}
          {open === r.n && <RefMeta r={meta[r.n]} />}
        </div>
      ))}
    </div>
  );
}

export function RefMeta({ r }: { r?: Reference }) {
  if (!r) return <div className="muted small">서지정보 조회 중…</div>;
  const m = r.meta;
  if (!m || !m.title) return <div className="muted small">CrossRef에서 찾지 못했습니다.</div>;
  return (
    <div className="ref-meta" onClick={(e) => e.stopPropagation()}>
      <div className="ref-title">{m.title}</div>
      <div className="muted small">
        {(m.authors || []).slice(0, 4).join(", ")}{(m.authors || []).length > 4 ? " 외" : ""} · {m.journal} {m.year}
        {m.cited_by != null && ` · 피인용 ${m.cited_by}`}
      </div>
      {m.url && (
        <a href={m.url} target="_blank" rel="noreferrer" className="small">
          <ExternalLink size={12} style={{ verticalAlign: "-2px" }} /> {m.doi || m.url}
        </a>
      )}
      {m.abstract && <div className="small" style={{ marginTop: 4 }}>{m.abstract.slice(0, 500)}{m.abstract.length > 500 ? "…" : ""}</div>}
    </div>
  );
}

/* ------------------------------------------------------------ notes */
function NotesTab({ paperId, highlights, onChanged, onGoToPage }: {
  paperId: string; highlights: Highlight[]; onChanged: () => void; onGoToPage: (p: number) => void;
}) {
  if (!highlights.length) {
    return <div className="muted">본문을 드래그한 뒤 형광펜 색을 고르면 여기에 모입니다. 각 하이라이트에 메모를 남길 수 있습니다.</div>;
  }
  return (
    <div>
      {highlights.map((h) => (
        <div key={h.id} className={`hl-item hl-${h.color}`}>
          <div className="muted small" style={{ display: "flex", justifyContent: "space-between" }}>
            <a href="#" onClick={(e) => { e.preventDefault(); onGoToPage(h.page); }}>{h.page + 1}쪽</a>
            <button
              className="btn ghost small danger"
              onClick={async () => {
                await api.deleteHighlight(paperId, h.id);
                onChanged();
              }}
            >
              <Trash2 size={12} />
            </button>
          </div>
          <div className="hl-text">{h.text.slice(0, 300)}{h.text.length > 300 ? "…" : ""}</div>
          <textarea
            defaultValue={h.note}
            placeholder="메모"
            rows={2}
            onBlur={async (e) => {
              if (e.target.value !== h.note) {
                await api.patchHighlight(paperId, h.id, { note: e.target.value });
                onChanged();
              }
            }}
          />
        </div>
      ))}
    </div>
  );
}
