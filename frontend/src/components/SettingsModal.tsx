import { useEffect, useState } from "react";
import { X, KeyRound, CheckCircle2, XCircle, RefreshCw, LogIn, LogOut } from "lucide-react";
import { api } from "../api";
import type { ProviderInfo, Settings } from "../types";

type Draft = Record<string, { api_key?: string; model?: string; base_url?: string }>;

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [s, setS] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [lang, setLang] = useState("ko");
  const [def, setDef] = useState("anthropic");
  const [vision, setVision] = useState("");
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [test, setTest] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [login, setLogin] = useState<"idle" | "waiting" | "error">("idle");
  const [loginErr, setLoginErr] = useState("");

  const load = () =>
    api.settings().then((x) => {
      setS(x);
      setLang(x.target_lang);
      setDef(x.default_provider);
      setVision(x.vision_provider);
      setDraft({});
    });
  useEffect(() => {
    load().catch((e) => setErr(String(e.message || e)));
  }, []);

  const field = (name: string, key: "api_key" | "model" | "base_url", fallback: string) =>
    draft[name]?.[key] ?? fallback;
  const setField = (name: string, key: "api_key" | "model" | "base_url", v: string) =>
    setDraft((d) => ({ ...d, [name]: { ...d[name], [key]: v } }));

  const save = async () => {
    setSaving(true);
    setErr("");
    try {
      await api.saveSettings({ target_lang: lang, default_provider: def, vision_provider: vision, providers: draft });
      await load();
    } catch (e) {
      setErr(String((e as Error).message || e));
    } finally {
      setSaving(false);
    }
  };

  const fetchModels = async (name: string) => {
    setErr("");
    try {
      if (Object.keys(draft).length) await save();
      const r = await api.listModels(name);
      setModels((m) => ({ ...m, [name]: r.models }));
    } catch (e) {
      setErr(String((e as Error).message || e));
    }
  };

  const runTest = async (name: string) => {
    setTest((t) => ({ ...t, [name]: "…" }));
    try {
      if (Object.keys(draft).length) await save();
      const r = await api.testProvider(name);
      setTest((t) => ({ ...t, [name]: "ok:" + r.reply }));
    } catch (e) {
      setTest((t) => ({ ...t, [name]: "err:" + String((e as Error).message || e) }));
    }
  };

  const chatgptLogin = async () => {
    setLoginErr("");
    setLogin("waiting");
    try {
      const { url } = await api.chatgptStart();
      window.open(url, "_blank", "noopener");
      const started = Date.now();
      const poll = async () => {
        const st = await api.chatgptStatus();
        if (st.logged_in && st.sharing) {
          setLogin("idle");
          await load();
          try {
            const r = await api.listModels("chatgpt");
            setModels((m) => ({ ...m, chatgpt: r.models }));
          } catch {
            /* ignore */
          }
          return;
        }
        if (st.last_error) {
          setLogin("error");
          setLoginErr(st.last_error);
          return;
        }
        if (Date.now() - started > 10 * 60 * 1000) {
          setLogin("error");
          setLoginErr("로그인 대기 시간이 지났습니다. 다시 시도하세요.");
          return;
        }
        setTimeout(poll, 2000);
      };
      setTimeout(poll, 2000);
    } catch (e) {
      setLogin("error");
      setLoginErr(String((e as Error).message || e));
    }
  };

  const chatgptLogout = async () => {
    await api.chatgptLogout();
    await load();
  };

  const renderChatGPT = (name: string, p: ProviderInfo) => {
    const auth = p.auth;
    const loggedIn = !!auth?.logged_in;
    return (
      <div key={name} className="provider">
        <div className="provider-head">
          <strong>{p.label}</strong>
          {loggedIn && auth?.sharing ? (
            <span className="tag ok"><CheckCircle2 size={12} /> {auth.email || "연결됨"}</span>
          ) : loggedIn ? (
            <span className="tag">로그인됨 · 플랜 사용 미허용</span>
          ) : (
            <span className="tag">연결 안 됨</span>
          )}
        </div>
        <p className="muted small" style={{ margin: "4px 0 8px" }}>
          ChatGPT Plus/Pro 구독의 사용량으로 동작합니다(OpenAI Sign in with ChatGPT). API 키가 필요 없고, 토큰은 이 컴퓨터의 <code>data/</code>에만 저장됩니다.
          앱별 사용 한도는 ChatGPT 설정 → 사용량에서 조정할 수 있습니다.
        </p>
        <div className="row">
          {!loggedIn || !auth?.sharing ? (
            <button className="btn primary small" onClick={chatgptLogin} disabled={login === "waiting"}>
              <LogIn size={14} /> {login === "waiting" ? "브라우저에서 로그인 중…" : "ChatGPT 계정으로 로그인"}
            </button>
          ) : (
            <>
              <button className="btn small" onClick={chatgptLogin}><RefreshCw size={12} /> 다시 로그인</button>
              <button className="btn small ghost danger" onClick={chatgptLogout}><LogOut size={12} /> 연결 해제</button>
            </>
          )}
        </div>
        {login === "waiting" && (
          <div className="muted small">새 탭에서 OpenAI 로그인 화면이 열렸습니다. 로그인하고 "ChatGPT 플랜 사용"에 동의하면 자동으로 연결됩니다.</div>
        )}
        {loginErr && <div className="error">{loginErr}</div>}
        {loggedIn && auth?.sharing && (
          <div className="row">
            <label>모델</label>
            <input
              list={`models-${name}`}
              value={field(name, "model", p.model)}
              onChange={(e) => setField(name, "model", e.target.value)}
              placeholder="모델 ID (목록 불러오기)"
            />
            <datalist id={`models-${name}`}>
              {(models[name] || []).map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
            <button className="btn small ghost" onClick={() => fetchModels(name)} title="모델 목록 불러오기"><RefreshCw size={14} /></button>
            <button className="btn small" onClick={() => runTest(name)}>테스트</button>
          </div>
        )}
        {test[name] && (
          <div className={"small " + (test[name].startsWith("ok") ? "ok-text" : test[name] === "…" ? "muted" : "error")}>
            {test[name].startsWith("ok") ? (
              <><CheckCircle2 size={14} /> 연결 성공 ({test[name].slice(3)})</>
            ) : test[name] === "…" ? "테스트 중…" : (
              <><XCircle size={14} /> {test[name].slice(4)}</>
            )}
          </div>
        )}
      </div>
    );
  };

  if (!s) return null;

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>설정</h2>
          <button className="btn ghost" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <section>
            <h3>일반</h3>
            <div className="row">
              <label>번역 언어</label>
              <select value={lang} onChange={(e) => setLang(e.target.value)}>
                {Object.entries(s.languages).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </div>
            <div className="row">
              <label>기본 AI</label>
              <select value={def} onChange={(e) => setDef(e.target.value)}>
                {Object.entries(s.providers).map(([k, p]) => (
                  <option key={k} value={k}>{p.label}</option>
                ))}
              </select>
            </div>
            <div className="row">
              <label>그림 설명용 AI</label>
              <select value={vision} onChange={(e) => setVision(e.target.value)}>
                <option value="">기본 AI와 동일 (비전 미지원이면 자동 선택)</option>
                {Object.entries(s.providers)
                  .filter(([, p]) => p.vision)
                  .map(([k, p]) => (
                    <option key={k} value={k}>{p.label}</option>
                  ))}
              </select>
            </div>
          </section>

          <section>
            <h3>AI 프로바이더</h3>
            <p className="muted small">
              ChatGPT 계정 로그인은 구독 사용량으로, 나머지는 API 키(종량제)로 동작합니다. 키는 이 컴퓨터의 <code>data/settings.json</code>에만 저장되며, 환경변수(ANTHROPIC_API_KEY 등)가 있으면 자동으로 사용합니다.
            </p>
            {Object.entries(s.providers).map(([name, p]) => p.oauth ? renderChatGPT(name, p) : (
              <div key={name} className="provider">
                <div className="provider-head">
                  <strong>{p.label}</strong>
                  {p.key_set ? (
                    <span className="tag ok">
                      <KeyRound size={12} /> {p.key_from_env ? "환경변수" : p.key_hint || "설정됨"}
                    </span>
                  ) : (
                    <span className="tag">키 없음</span>
                  )}
                  {!p.vision && <span className="tag">텍스트 전용</span>}
                </div>
                {name !== "custom" && (
                  <div className="row">
                    <label>API 키</label>
                    <input
                      type="password"
                      placeholder={p.key_set ? "(변경하려면 새 키 입력)" : "sk-…"}
                      value={field(name, "api_key", "")}
                      onChange={(e) => setField(name, "api_key", e.target.value)}
                      autoComplete="off"
                    />
                  </div>
                )}
                {(name === "custom" || name === "deepseek" || name === "openai") && (
                  <div className="row">
                    <label>Base URL</label>
                    <input
                      value={field(name, "base_url", p.base_url)}
                      onChange={(e) => setField(name, "base_url", e.target.value)}
                    />
                  </div>
                )}
                {name === "custom" && (
                  <div className="row">
                    <label>API 키 (선택)</label>
                    <input
                      type="password"
                      placeholder="Ollama는 비워 두세요"
                      value={field(name, "api_key", "")}
                      onChange={(e) => setField(name, "api_key", e.target.value)}
                    />
                  </div>
                )}
                <div className="row">
                  <label>모델</label>
                  <input
                    list={`models-${name}`}
                    value={field(name, "model", p.model)}
                    onChange={(e) => setField(name, "model", e.target.value)}
                    placeholder="모델 ID"
                  />
                  <datalist id={`models-${name}`}>
                    {(models[name] || p.models).map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <button className="btn small ghost" onClick={() => fetchModels(name)} title="모델 목록 불러오기">
                    <RefreshCw size={14} />
                  </button>
                  <button className="btn small" onClick={() => runTest(name)}>테스트</button>
                </div>
                {test[name] && (
                  <div className={"small " + (test[name].startsWith("ok") ? "ok-text" : test[name] === "…" ? "muted" : "error")}>
                    {test[name].startsWith("ok") ? (
                      <><CheckCircle2 size={14} /> 연결 성공 ({test[name].slice(3)})</>
                    ) : test[name] === "…" ? (
                      "테스트 중…"
                    ) : (
                      <><XCircle size={14} /> {test[name].slice(4)}</>
                    )}
                  </div>
                )}
              </div>
            ))}
          </section>
          {err && <div className="error">{err}</div>}
        </div>

        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>닫기</button>
          <button className="btn primary" onClick={save} disabled={saving}>
            {saving ? "저장 중…" : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}
