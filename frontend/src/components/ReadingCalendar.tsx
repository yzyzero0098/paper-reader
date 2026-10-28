import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, BookOpen } from "lucide-react";
import { api, localDay } from "../api";
import type { ReadingMonth } from "../types";

const DOW = ["일", "월", "화", "수", "목", "금", "토"];

export const fmtDuration = (sec: number) => {
  if (sec < 60) return sec > 0 ? "1분 미만" : "열람만";
  const m = Math.round(sec / 60);
  return m >= 60 ? `${Math.floor(m / 60)}시간 ${m % 60}분` : `${m}분`;
};

const ym = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;

export default function ReadingCalendar() {
  const nav = useNavigate();
  const [cursor, setCursor] = useState(() => {
    const n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), 1);
  });
  const [data, setData] = useState<ReadingMonth | null>(null);
  const [selected, setSelected] = useState(localDay());
  const [err, setErr] = useState("");

  useEffect(() => {
    setData(null);
    api.readingCalendar(ym(cursor)).then(setData).catch((e) => setErr(String(e.message || e)));
  }, [cursor]);

  const cells = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const start = first.getDay();
    const days = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0).getDate();
    const out: (string | null)[] = Array(start).fill(null);
    for (let d = 1; d <= days; d++) out.push(localDay(new Date(cursor.getFullYear(), cursor.getMonth(), d)));
    while (out.length % 7) out.push(null);
    return out;
  }, [cursor]);

  const today = localDay();
  const entries = data?.days[selected] || [];
  const maxSec = Math.max(1, ...Object.values(data?.days || {}).map((es) => es.reduce((a, e) => a + e.seconds, 0)));

  return (
    <div className="cal">
      <div className="cal-head">
        <button className="btn ghost" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}><ChevronLeft size={18} /></button>
        <h3>{cursor.getFullYear()}년 {cursor.getMonth() + 1}월</h3>
        <button className="btn ghost" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))}><ChevronRight size={18} /></button>
        <button className="btn small" onClick={() => { const n = new Date(); setCursor(new Date(n.getFullYear(), n.getMonth(), 1)); setSelected(localDay()); }}>오늘</button>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {!data ? "불러오는 중…" : data.papers === 0 ? "이달 읽은 논문 없음" : `이달 ${data.papers}편 · 총 ${fmtDuration(data.total_seconds)}`}
        </span>
      </div>
      {err && <div className="error">{err}</div>}

      <div className="cal-grid">
        {DOW.map((d, i) => (
          <div key={d} className={"cal-dow" + (i === 0 ? " sun" : i === 6 ? " sat" : "")}>{d}</div>
        ))}
        {cells.map((day, i) => {
          if (!day) return <div key={i} className="cal-cell empty" />;
          const es = data?.days[day] || [];
          const sec = es.reduce((a, e) => a + e.seconds, 0);
          const level = es.length ? 1 + Math.min(3, Math.floor((sec / maxSec) * 3.99)) : 0;
          const folders = Array.from(new Set(es.map((e) => e.folder_color).filter(Boolean))) as string[];
          return (
            <button
              key={day}
              className={`cal-cell lv${level}` + (day === selected ? " sel" : "") + (day === today ? " today" : "")}
              onClick={() => setSelected(day)}
            >
              <span className="cal-num">{Number(day.slice(8))}</span>
              {es.length > 0 && (
                <>
                  <span className="cal-count">{es.length}편</span>
                  <span className="cal-dots">
                    {folders.slice(0, 4).map((c) => (
                      <i key={c} style={{ background: c }} />
                    ))}
                  </span>
                </>
              )}
            </button>
          );
        })}
      </div>

      <div className="cal-day">
        <h4>{selected.replace(/-/g, ".")} {selected === today && <span className="tag ok">오늘</span>}</h4>
        {entries.length === 0 && <div className="muted">이 날 읽은 논문이 없습니다.</div>}
        {entries.map((e) => (
          <div key={e.paper_id} className="cal-entry" onClick={() => nav(`/paper/${e.paper_id}`)}>
            <BookOpen size={15} />
            <div className="cal-entry-main">
              <div className="cal-entry-title">{e.title}</div>
              <div className="muted small">
                {fmtDuration(e.seconds)}
                {e.folder_name && (
                  <span className="folder-chip" style={{ borderColor: e.folder_color || undefined, color: e.folder_color || undefined }}>
                    {e.folder_name}
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
