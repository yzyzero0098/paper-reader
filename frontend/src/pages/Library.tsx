import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, FileUp, Settings as SettingsIcon, Trash2, AlertTriangle } from "lucide-react";
import { api } from "../api";
import type { Paper, Settings } from "../types";

export default function Library({ settings, onOpenSettings }: { settings: Settings | null; onOpenSettings: () => void }) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const refresh = () => api.listPapers().then(setPapers).catch((e) => setError(String(e.message || e)));
  useEffect(() => {
    refresh();
  }, []);

  const upload = async (files: FileList | File[]) => {
    setBusy(true);
    setError("");
    try {
      let last: Paper | null = null;
      for (const f of Array.from(files)) {
        if (!f.name.toLowerCase().endsWith(".pdf")) continue;
        last = await api.uploadPaper(f);
      }
      await refresh();
      if (last && files.length === 1) nav(`/paper/${last.id}`);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Paper) => {
    if (!confirm(`"${p.title}" 논문과 관련 노트·번역 캐시를 삭제할까요?`)) return;
    await api.deletePaper(p.id);
    refresh();
  };

  const noKey =
    settings && !Object.values(settings.providers).some((p) => p.key_set && p.model);

  return (
    <div className="library">
      <header className="lib-header">
        <div className="brand">
          <BookOpen size={22} />
          <span>Paper Reader</span>
        </div>
        <button className="btn ghost" onClick={onOpenSettings} title="설정">
          <SettingsIcon size={18} /> 설정
        </button>
      </header>

      {noKey && (
        <div className="notice">
          <AlertTriangle size={16} />
          AI 기능(번역·설명·요약·토론)을 쓰려면 설정에서 API 키를 하나 이상 입력하세요.
          <button className="btn small" onClick={onOpenSettings}>설정 열기</button>
        </div>
      )}

      <div
        className={"dropzone" + (drag ? " drag" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          upload(e.dataTransfer.files);
        }}
        onClick={() => fileRef.current?.click()}
      >
        <FileUp size={28} />
        <div>
          <strong>PDF를 끌어다 놓거나 클릭해서 업로드</strong>
          <div className="muted">업로드한 논문은 이 컴퓨터의 data/ 폴더에만 저장됩니다.</div>
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => e.target.files && upload(e.target.files)}
        />
        {busy && <div className="muted">업로드 중…</div>}
      </div>
      {error && <div className="error">{error}</div>}

      <div className="paper-grid">
        {papers.map((p) => (
          <div key={p.id} className="paper-card" onClick={() => nav(`/paper/${p.id}`)}>
            <div className="paper-title">{p.title}</div>
            <div className="muted small">
              {p.filename} · {p.pages}쪽 · {new Date(p.added_at * 1000).toLocaleDateString()}
            </div>
            {p.meta?.author && <div className="muted small">{p.meta.author}</div>}
            <div className="card-actions">
              <button
                className="btn ghost small danger"
                onClick={(e) => {
                  e.stopPropagation();
                  remove(p);
                }}
              >
                <Trash2 size={14} /> 삭제
              </button>
            </div>
          </div>
        ))}
        {papers.length === 0 && <div className="muted">아직 논문이 없습니다. PDF를 올려 시작하세요.</div>}
      </div>
    </div>
  );
}
