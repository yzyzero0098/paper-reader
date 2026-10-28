import { memo, useEffect, useLayoutEffect, useRef, useState } from "react";
// (useState is still used by TrBlock)
import { Page } from "react-pdf";
import { Sparkles } from "lucide-react";
import type { Citation, Figure, Highlight, Layout, Sentence, TranslatedBlock } from "../types";

export type ViewMode = "original" | "side" | "overlay";

export interface SelectionInfo {
  text: string;
  page: number;
  rects: [number, number, number, number][];
  anchor: { left: number; top: number; right: number; bottom: number };
}

interface Props {
  pageIndex: number;
  scale: number;
  pageWidth: number;
  pageHeight: number;
  layout?: Layout;
  translation?: TranslatedBlock[];
  translating?: boolean;
  mode: ViewMode;
  highlights: Highlight[];
  activeSid?: string | null;
  onVisible: (page: number, visible: boolean) => void;
  onSelection: (sel: SelectionInfo | null) => void;
  onFigure: (fig: Figure, page: number) => void;
  onCitation: (cite: Citation, page: number, anchor: DOMRect) => void;
  onHighlightClick: (h: Highlight) => void;
  onHoverSentence?: (page: number, sid: string | null) => void;
  onContextMenu?: (sel: SelectionInfo | null, x: number, y: number) => void;
  registerRef: (el: HTMLDivElement | null) => void;
}

/** A translated block drawn over the original text; the font shrinks until the text fits the box. */
function TrBlock({ b, scale }: { b: TranslatedBlock; scale: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const base = Math.max(6, b.size * scale * 0.96);
  const [fs, setFs] = useState(base);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let f = base;
    el.style.fontSize = f + "px";
    let guard = 0;
    while (el.scrollHeight > el.clientHeight + 1 && f > base * 0.45 && guard++ < 60) {
      f -= Math.max(0.2, f * 0.04);
      el.style.fontSize = f + "px";
    }
    setFs(f);
  }, [b.t, scale, base]);
  const [x0, y0, x1, y1] = b.bbox;
  return (
    <div
      ref={ref}
      className={`tr-block ${b.kind}`}
      style={{
        left: x0 * scale - 1,
        top: y0 * scale - 1,
        width: (x1 - x0) * scale + 3,
        height: (y1 - y0) * scale + 3,
        fontSize: fs,
      }}
      title={b.text}
    >
      {b.t}
    </div>
  );
}

function PageView({
  pageIndex, scale, pageWidth, pageHeight, layout, translation, translating, mode, highlights, activeSid,
  onVisible, onSelection, onFigure, onCitation, onHighlightClick, onHoverSentence, onContextMenu, registerRef,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const lastHover = useRef<string | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => onVisible(pageIndex, e.isIntersecting)),
      { rootMargin: "600px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [pageIndex, onVisible]);

  const sentences: Sentence[] = translation ? translation.flatMap((b) => b.sentences || []) : [];

  const currentSelection = (): SelectionInfo | null => {
    const sel = window.getSelection();
    const wr = wrapRef.current?.getBoundingClientRect();
    if (!sel || sel.isCollapsed || !wr) return null;
    const text = sel.toString().replace(/\s+/g, " ").trim();
    if (!text) return null;
    const range = sel.getRangeAt(0);
    if (!wrapRef.current?.contains(range.commonAncestorContainer)) return null;
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 1 && r.height > 1);
    if (!rects.length) return null;
    const pdfRects = rects.map(
      (r) =>
        [
          (r.left - wr.left) / scale,
          (r.top - wr.top) / scale,
          (r.right - wr.left) / scale,
          (r.bottom - wr.top) / scale,
        ] as [number, number, number, number],
    );
    const last = rects[rects.length - 1];
    return { text, page: pageIndex, rects: pdfRects, anchor: { left: last.left, top: last.top, right: last.right, bottom: last.bottom } };
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    if (e.button === 2) return;           // right button: handled by the context menu
    onSelection(currentSelection());
  };

  const handleContextMenu = (e: React.MouseEvent) => {
    if (!onContextMenu) return;
    const sel = currentSelection();
    e.preventDefault();
    onContextMenu(sel, e.clientX, e.clientY);
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (mode !== "side" || !onHoverSentence || !sentences.length) return;
    const wr = wrapRef.current?.getBoundingClientRect();
    if (!wr) return;
    const x = (e.clientX - wr.left) / scale;
    const y = (e.clientY - wr.top) / scale;
    let hit: string | null = null;
    for (const s of sentences) {
      if (s.rects.some((r) => x >= r[0] - 1 && x <= r[2] + 1 && y >= r[1] - 1 && y <= r[3] + 1)) {
        hit = s.id;
        break;
      }
    }
    if (hit !== lastHover.current) {
      lastHover.current = hit;
      onHoverSentence(pageIndex, hit);
    }
  };

  const handleMouseLeave = () => {
    if (lastHover.current !== null) {
      lastHover.current = null;
      onHoverSentence?.(pageIndex, null);
    }
  };

  const W = pageWidth * scale;
  const H = pageHeight * scale;
  const showOverlay = mode === "overlay" && translation && translation.length > 0;
  const activeRects = activeSid ? sentences.find((s) => s.id === activeSid)?.rects : undefined;

  return (
    <div
      ref={(el) => {
        (wrapRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
        registerRef(el);
      }}
      className="page-wrap"
      style={{ width: W, height: H }}
      onMouseUp={handleMouseUp}
      onContextMenu={handleContextMenu}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      data-page={pageIndex}
    >
      <Page
        pageNumber={pageIndex + 1}
        scale={scale}
        renderTextLayer
        renderAnnotationLayer={false}
        loading=""
      />

      {mode === "overlay" && translating && <div className="page-badge loading">번역 중…</div>}
      {mode === "overlay" && !translating && !translation && <div className="page-badge">번역 대기</div>}

      {(layout || translation || highlights.length > 0) && (
        <div className="overlay">
          {showOverlay &&
            translation!.map((b) =>
              b.t ? (
                <TrBlock key={b.id} b={b} scale={scale} />
              ) : (
                <div
                  key={b.id}
                  className="tr-missing"
                  style={{ left: b.bbox[0] * scale, top: b.bbox[1] * scale, width: (b.bbox[2] - b.bbox[0]) * scale, height: (b.bbox[3] - b.bbox[1]) * scale }}
                  title="번역되지 않은 블록"
                />
              ),
            )}

          {highlights.map((h) =>
            h.rects.map((r, i) => (
              <div
                key={`${h.id}-${i}`}
                className={`hl-rect hl-${h.color}`}
                style={{ left: r[0] * scale, top: r[1] * scale, width: (r[2] - r[0]) * scale, height: (r[3] - r[1]) * scale }}
                onClick={() => onHighlightClick(h)}
                title={h.note || h.text}
              />
            )),
          )}

          {mode === "side" &&
            activeRects?.map((r, i) => (
              <div
                key={`act-${i}`}
                className="sent-active"
                style={{ left: r[0] * scale - 1, top: r[1] * scale - 1, width: (r[2] - r[0]) * scale + 2, height: (r[3] - r[1]) * scale + 2 }}
              />
            ))}

          {layout?.figures.map((f) => {
            const [x0, y0, x1, y1] = f.bbox;
            return (
              <div
                key={f.id}
                className="fig-hit"
                style={{ left: x0 * scale, top: y0 * scale, width: (x1 - x0) * scale, height: (y1 - y0) * scale }}
                title={f.caption}
              >
                <button
                  className="fig-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onFigure(f, pageIndex);
                  }}
                >
                  <Sparkles size={12} /> {f.kind === "table" ? "표 설명" : "그림 설명"}
                </button>
              </div>
            );
          })}

          {mode !== "overlay" &&
            layout?.citations.map((c) =>
              c.rects.map((r, i) => (
                <div
                  key={`${c.text}-${i}`}
                  className="cite-hit"
                  style={{ left: r[0] * scale, top: r[1] * scale, width: (r[2] - r[0]) * scale, height: (r[3] - r[1]) * scale }}
                  onClick={(e) => {
                    e.stopPropagation();
                    onCitation(c, pageIndex, (e.currentTarget as HTMLElement).getBoundingClientRect());
                  }}
                  title={c.text}
                />
              )),
            )}
        </div>
      )}
    </div>
  );
}

export default memo(PageView);
