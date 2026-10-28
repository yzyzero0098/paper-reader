import { useEffect, useRef, useState } from "react";
import { Gauge, ExternalLink, X } from "lucide-react";
import { api } from "../api";
import type { Settings, UsageAgg, UsageSummary } from "../types";

export const fmtTok = (n: number) =>
  n >= 1_000_000 ? (n / 1_000_000).toFixed(2) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);

const tot = (a?: UsageAgg) => (a ? a.input + a.output : 0);
const USAGE_URL = "https://chatgpt.com/settings/usage";

function Bar({ label, used, budget, sub }: { label: string; used: number; budget: number; sub?: string }) {
  const pct = budget > 0 ? Math.min(100, (used / budget) * 100) : 0;
  const level = pct >= 90 ? "danger" : pct >= 70 ? "warn" : "";
  return (
    <div className="ubar-row">
      <div className="ubar-head">
        <span>{label}</span>
        <span className="num">
          {fmtTok(used)}
          {budget > 0 && <> / {fmtTok(budget)} · <b>{pct.toFixed(0)}%</b></>}
        </span>
      </div>
      <div className="ubar">
        <div className={"ubar-fill " + level} style={{ width: budget > 0 ? `${Math.max(pct, used > 0 ? 1.5 : 0)}%` : "0%" }} />
      </div>
      {sub && <div className="muted ubar-sub">{sub}</div>}
    </div>
  );
}

export default function UsagePanel({ usage, settings, onSettingsChanged, onRefresh }: {
  usage: UsageSummary | null;
  settings: Settings | null;
  onSettingsChanged: (s: Settings) => void;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [b5, setB5] = useState("");
  const [b7, setB7] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!settings) return;
    setB5(settings.usage_budget_5h ? String(Math.round(settings.usage_budget_5h / 1000)) : "");
    setB7(settings.usage_budget_7d ? String(Math.round(settings.usage_budget_7d / 1000)) : "");
  }, [settings]);

  useEffect(() => {
    if (!open) return;
    onRefresh();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!usage) return null;
  const budget5 = settings?.usage_budget_5h || 0;
  const budget7 = settings?.usage_budget_7d || 0;
  const used5 = tot(usage.window_5h);
  const pct5 = budget5 > 0 ? Math.min(100, (used5 / budget5) * 100) : null;
  const cg5 = tot(usage.chatgpt_5h);
  const cg7 = tot(usage.chatgpt_7d);
  const share = (part: number, whole: number) => (whole > 0 ? ` (앱 사용량의 ${Math.round((part / whole) * 100)}%)` : "");

  const saveBudgets = async () => {
    const k = (v: string) => Math.max(0, Math.round(Number(v || 0) * 1000)) || 0;
    try {
      const s = await api.saveSettings({ usage_budget_5h: k(b5), usage_budget_7d: k(b7) });
      onSettingsChanged(s);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="usage-wrap" ref={ref}>
      <button className="usage-pill" onClick={() => setOpen((v) => !v)} title="사용량 보기">
        <Gauge size={13} />
        5시간 <b>{fmtTok(used5)}</b>
        {pct5 !== null && (
          <span className="mini-bar"><span className={pct5 >= 90 ? "danger" : pct5 >= 70 ? "warn" : ""} style={{ width: `${pct5}%` }} /></span>
        )}
        {usage.paper && <>· 이 논문 <b>{fmtTok(tot(usage.paper))}</b></>}
      </button>

      {open && (
        <div className="usage-panel">
          <div className="usage-panel-head">
            <strong>사용량</strong>
            <button className="btn ghost small" onClick={() => setOpen(false)}><X size={14} /></button>
          </div>

          <div className="usage-sec">Paper Reader가 쓴 양</div>
          <Bar label="최근 5시간" used={used5} budget={budget5} sub={`${usage.window_5h.calls}회 호출`} />
          <Bar label="최근 7일" used={tot(usage.window_7d)} budget={budget7} sub={`${usage.window_7d.calls}회 호출`} />
          <table className="usage-table">
            <tbody>
              <tr><td>오늘</td><td className="num">{fmtTok(tot(usage.today))} · {usage.today.calls}회</td></tr>
              {usage.paper && <tr><td>이 논문 (누적)</td><td className="num">{fmtTok(tot(usage.paper))} · {usage.paper.calls}회</td></tr>}
              <tr><td>전체 누적</td><td className="num">{fmtTok(tot(usage.total))}</td></tr>
              {usage.by_kind_today.map((k) => (
                <tr key={k.kind}><td className="muted">· 오늘 {k.kind}</td><td className="num muted">{fmtTok(k.input + k.output)}</td></tr>
              ))}
            </tbody>
          </table>

          <div className="usage-sec">ChatGPT 구독</div>
          <div className="usage-note">
            ChatGPT 계정으로 이 앱이 쓴 양: 5시간 <b>{fmtTok(cg5)}</b>{share(cg5, used5)} · 7일 <b>{fmtTok(cg7)}</b>{share(cg7, tot(usage.window_7d))}
          </div>
          <div className="usage-note muted">
            플랜 전체 사용률(5시간·주간 %)은 OpenAI가 외부 앱에 제공하지 않아 여기서 읽을 수 없습니다.
            앱별 사용량과 한도는 ChatGPT 사용량 페이지에서 확인·조정하세요.
          </div>
          <a className="btn small" href={USAGE_URL} target="_blank" rel="noreferrer">
            <ExternalLink size={12} /> ChatGPT 사용량 페이지 열기
          </a>
          {usage.limit_hit_at && (
            <div className="usage-note warn-text">
              최근 플랜 한도 도달: {new Date(usage.limit_hit_at * 1000).toLocaleString()}
            </div>
          )}

          <div className="usage-sec">내 사용 예산 (선택)</div>
          <div className="usage-note muted">정해 두면 위 막대가 예산 대비 %로 표시됩니다. 단위는 천 토큰(k)입니다.</div>
          <div className="budget-row">
            <label>5시간</label>
            <input inputMode="numeric" value={b5} placeholder="예: 300" onChange={(e) => setB5(e.target.value.replace(/[^\d]/g, ""))} />
            <span>k</span>
            <label>7일</label>
            <input inputMode="numeric" value={b7} placeholder="예: 3000" onChange={(e) => setB7(e.target.value.replace(/[^\d]/g, ""))} />
            <span>k</span>
            <button className="btn small primary" onClick={saveBudgets}>저장</button>
          </div>
        </div>
      )}
    </div>
  );
}
