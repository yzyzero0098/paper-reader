import { FileText, Monitor, Moon, Sun } from "lucide-react";
import { setPdfDark, setThemePref, useTheme, type ThemePref } from "../theme";

const NEXT: Record<ThemePref, ThemePref> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<ThemePref, string> = { system: "시스템 설정", light: "라이트", dark: "다크" };

/** Cycles system → light → dark. With `pdfOption`, also offers dark PDF pages while dark. */
export default function ThemeToggle({ pdfOption = false, withLabel = false }: { pdfOption?: boolean; withLabel?: boolean }) {
  const { pref, resolved, pdfDark } = useTheme();
  const Icon = pref === "system" ? Monitor : pref === "dark" ? Moon : Sun;
  return (
    <>
      {/* Theme button first so it doesn't move when the PDF button appears or disappears. */}
      <button
        className="btn ghost"
        onClick={() => setThemePref(NEXT[pref])}
        title={`화면 테마: ${LABEL[pref]} (누르면 ${LABEL[NEXT[pref]]})`}
      >
        <Icon size={18} />
        {withLabel && <span>{LABEL[pref]}</span>}
      </button>
      {pdfOption && resolved === "dark" && (
        <button
          className={"btn ghost" + (pdfDark ? " active" : "")}
          onClick={() => setPdfDark(!pdfDark)}
          title={pdfDark ? "PDF 원래 색으로 보기" : "PDF도 어둡게 보기 (색 반전)"}
        >
          <FileText size={16} />
        </button>
      )}
    </>
  );
}
