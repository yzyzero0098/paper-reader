import { useEffect, useRef, useState } from "react";
import { Gauge, ExternalLink, X } from "lucide-react";
import type { UsageAgg, UsageSummary } from "../types";

export const fmtTok = (n: number) =>
  n >= 1_000_000 ? (n / 1_000_000).toFixed(2) + "M" : n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);

const tot = (a?: UsageAgg) => (a ? a.input + a.output : 0);
const USAGE_URL = "https://chatgpt.com/settings/usage";

/** Token usage counted by this app, plus a link to ChatGPT's own usage page for plan limits. */
export default function UsagePanel({ usage, onRefresh }: { usage: UsageSummary | null; onRefresh: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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
  const used5 = tot(usage.window_5h);
  const used7 = tot(usage.window_7d);
  const cg5 = tot(usage.chatgpt_5h);
  const cg7 = tot(usage.chatgpt_7d);

  return (
    <div className="usage-wrap" ref={ref}>
      <button className="usage-pill" onClick={() => setOpen((v) => !v)} title="이 앱의 토큰 사용량">
        <Gauge size={13} />
        5시간 <b>{fmtTok(used5)}</b>
        {usage.paper && <>· 이 논문 <b>{fmtTok(tot(usage.paper))}</b></>}
      </button>

      {open && (
        <div className="usage-panel">
          <div className="usage-panel-head">
            <strong>Paper Reader 사용량</strong>
            <button className="btn ghost small" onClick={() => setOpen(false)}><X size={14} /></button>
          </div>
          <table className="usage-table">
            <tbody>
              <tr><td>최근 5시간</td><td className="num">{fmtTok(used5)} · {usage.window_5h.calls}회</td></tr>
              <tr><td>최근 7일</td><td className="num">{fmtTok(used7)} · {usage.window_7d.calls}회</td></tr>
              <tr><td>오늘</td><td className="num">{fmtTok(tot(usage.today))} · {usage.today.calls}회</td></tr>
              {usage.paper && <tr><td>이 논문 (누적)</td><td className="num">{fmtTok(tot(usage.paper))} · {usage.paper.calls}회</td></tr>}
              <tr><td>전체 누적</td><td className="num">{fmtTok(tot(usage.total))}</td></tr>
              {usage.by_kind_today.map((k) => (
                <tr key={k.kind}><td className="muted">· 오늘 {k.kind}</td><td className="num muted">{fmtTok(k.input + k.output)}</td></tr>
              ))}
            </tbody>
          </table>
          {(cg5 > 0 || cg7 > 0) && (cg5 !== used5 || cg7 !== used7) && (
            <div className="usage-note muted">ChatGPT 계정으로 쓴 양: 5시간 {fmtTok(cg5)} · 7일 {fmtTok(cg7)}</div>
          )}
          {usage.limit_hit_at && (
            <div className="usage-note warn-text">최근 플랜 한도 도달: {new Date(usage.limit_hit_at * 1000).toLocaleString()}</div>
          )}
          <div className="usage-note muted">
            토큰은 이 앱이 보낸 요청만 센 값입니다. ChatGPT 플랜의 5시간·주간 한도는 사용량 페이지에서 확인하세요.
          </div>
          <a className="btn small" href={USAGE_URL} target="_blank" rel="noreferrer">
            <ExternalLink size={12} /> ChatGPT 사용량 페이지 열기
          </a>
        </div>
      )}
    </div>
  );
}
