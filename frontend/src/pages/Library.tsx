import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen, FileUp, Settings as SettingsIcon, Trash2, AlertTriangle, Folder as FolderIcon, FolderPlus, Inbox,
  Library as LibraryIcon, CalendarDays, Pencil, Search,
} from "lucide-react";
import { api } from "../api";
import type { Folder, Paper, Settings } from "../types";
import ReadingCalendar from "../components/ReadingCalendar";

type Filter = "all" | "unfiled" | number;

const lastReadText = (ts: number | null) => {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const days = Math.floor((Date.now() - ts * 1000) / 86400000);
  if (days <= 0) return "오늘 읽음";
  if (days === 1) return "어제 읽음";
  if (days < 7) return `${days}일 전 읽음`;
  return `${d.getMonth() + 1}월 ${d.getDate()}일 읽음`;
};

export default function Library({ settings, onOpenSettings }: { settings: Settings | null; onOpenSettings: () => void }) {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<"library" | "calendar">("library");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [drag, setDrag] = useState(false);
  const [dropFolder, setDropFolder] = useState<Filter | null>(null);
  const [newFolder, setNewFolder] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const nav = useNavigate();

  const refresh = () =>
    Promise.all([api.listPapers(), api.folders()])
      .then(([p, f]) => {
        setPapers(p);
        setFolders(f);
      })
      .catch((e) => setError(String(e.message || e)));
  useEffect(() => {
    refresh();
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return papers
      .filter((p) => (filter === "all" ? true : filter === "unfiled" ? p.folder_id == null : p.folder_id === filter))
      .filter((p) => !q || p.title.toLowerCase().includes(q) || p.filename.toLowerCase().includes(q))
      .sort((a, b) => (b.last_read || b.added_at) - (a.last_read || a.added_at));
  }, [papers, filter, query]);

  const unfiledCount = papers.filter((p) => p.folder_id == null).length;
  const folderName = (id: number | null) => folders.find((f) => f.id === id);

  const upload = async (files: FileList | File[]) => {
    setBusy(true);
    setError("");
    const target = typeof filter === "number" ? filter : null;
    try {
      let last: Paper | null = null;
      let n = 0;
      for (const f of Array.from(files)) {
        if (!f.name.toLowerCase().endsWith(".pdf")) continue;
        last = await api.uploadPaper(f, target);
        n++;
      }
      await refresh();
      if (last && n === 1) nav(`/paper/${last.id}`);
    } catch (e) {
      setError(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Paper) => {
    if (!confirm(`"${p.title}" 논문과 관련 노트·번역 캐시·읽기 기록을 삭제할까요?`)) return;
    await api.deletePaper(p.id);
    refresh();
  };

  const move = async (p: Paper, folderId: number | null) => {
    if (p.folder_id === folderId) return;
    await api.movePaper(p.id, folderId);
    refresh();
  };

  const addFolder = async () => {
    const name = (newFolder || "").trim();
    setNewFolder(null);
    if (!name) return;
    try {
      const r = await api.createFolder(name);
      await refresh();
      setFilter(r.id);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  };

  const renameFolder = async (f: Folder) => {
    const name = prompt("폴더 이름", f.name);
    if (!name || !name.trim() || name === f.name) return;
    await api.patchFolder(f.id, { name: name.trim() });
    refresh();
  };

  const removeFolder = async (f: Folder) => {
    if (!confirm(`폴더 "${f.name}"을 삭제할까요? 안의 논문 ${f.count}편은 삭제되지 않고 '미분류'로 이동합니다.`)) return;
    await api.deleteFolder(f.id);
    if (filter === f.id) setFilter("all");
    refresh();
  };

  const noKey = settings && !Object.values(settings.providers).some((p) => p.key_set && p.model);
  const title =
    filter === "all" ? "모든 논문" : filter === "unfiled" ? "미분류" : folderName(filter)?.name || "폴더";

  const dropHandlers = (target: Filter) => ({
    onDragOver: (e: React.DragEvent) => {
      if (e.dataTransfer.types.includes("text/paper-id")) {
        e.preventDefault();
        setDropFolder(target);
      }
    },
    onDragLeave: () => setDropFolder((t) => (t === target ? null : t)),
    onDrop: (e: React.DragEvent) => {
      const pid = e.dataTransfer.getData("text/paper-id");
      setDropFolder(null);
      if (!pid || target === "all") return;
      e.preventDefault();
      const p = papers.find((x) => x.id === pid);
      if (p) move(p, target === "unfiled" ? null : (target as number));
    },
  });

  return (
    <div className="library">
      <header className="lib-header">
        <div className="brand">
          <BookOpen size={22} />
          <span>Paper Reader</span>
        </div>
        <div className="seg">
          <button className={view === "library" ? "on" : ""} onClick={() => setView("library")}>
            <LibraryIcon size={14} style={{ verticalAlign: "-2px" }} /> 라이브러리
          </button>
          <button className={view === "calendar" ? "on" : ""} onClick={() => setView("calendar")}>
            <CalendarDays size={14} style={{ verticalAlign: "-2px" }} /> 읽기 캘린더
          </button>
        </div>
        <button className="btn ghost" onClick={onOpenSettings} title="설정">
          <SettingsIcon size={18} /> 설정
        </button>
      </header>

      {noKey && (
        <div className="notice">
          <AlertTriangle size={16} />
          AI 기능(번역·설명·요약·토론)을 쓰려면 설정에서 ChatGPT 계정으로 로그인하거나 API 키를 입력하세요.
          <button className="btn small" onClick={onOpenSettings}>설정 열기</button>
        </div>
      )}
      {error && <div className="error">{error}</div>}

      {view === "calendar" ? (
        <ReadingCalendar />
      ) : (
        <div className="lib-body">
          <aside className="folders">
            <button className={"folder-item" + (filter === "all" ? " on" : "")} onClick={() => setFilter("all")}>
              <LibraryIcon size={15} /> <span className="folder-name">모든 논문</span> <span className="folder-count">{papers.length}</span>
            </button>
            <button
              className={"folder-item" + (filter === "unfiled" ? " on" : "") + (dropFolder === "unfiled" ? " drop" : "")}
              onClick={() => setFilter("unfiled")}
              {...dropHandlers("unfiled")}
            >
              <Inbox size={15} /> <span className="folder-name">미분류</span> <span className="folder-count">{unfiledCount}</span>
            </button>
            <div className="folder-sep">주제 폴더</div>
            {folders.map((f) => (
              <div key={f.id} className="folder-row">
                <button
                  className={"folder-item" + (filter === f.id ? " on" : "") + (dropFolder === f.id ? " drop" : "")}
                  onClick={() => setFilter(f.id)}
                  {...dropHandlers(f.id)}
                >
                  <FolderIcon size={15} style={{ color: f.color }} fill={f.color} fillOpacity={0.25} />
                  <span className="folder-name">{f.name}</span>
                  <span className="folder-count">{f.count}</span>
                </button>
                <span className="folder-tools">
                  <button className="btn ghost small" title="이름 변경" onClick={() => renameFolder(f)}><Pencil size={12} /></button>
                  <button className="btn ghost small danger" title="폴더 삭제" onClick={() => removeFolder(f)}><Trash2 size={12} /></button>
                </span>
              </div>
            ))}
            {newFolder === null ? (
              <button className="folder-item add" onClick={() => setNewFolder("")}>
                <FolderPlus size={15} /> 새 폴더
              </button>
            ) : (
              <input
                className="folder-input"
                autoFocus
                placeholder="폴더 이름 (Enter)"
                value={newFolder}
                onChange={(e) => setNewFolder(e.target.value)}
                onBlur={addFolder}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.nativeEvent.isComposing) addFolder();
                  if (e.key === "Escape") setNewFolder(null);
                }}
              />
            )}
          </aside>

          <main className="lib-main">
            <div className="lib-toolbar">
              <h2>{title} <span className="muted small">{shown.length}편</span></h2>
              <div className="search">
                <Search size={14} />
                <input placeholder="제목 검색" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
            </div>

            <div
              className={"dropzone compact" + (drag ? " drag" : "")}
              onDragOver={(e) => {
                if (e.dataTransfer.types.includes("Files")) {
                  e.preventDefault();
                  setDrag(true);
                }
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => {
                if (!e.dataTransfer.files.length) return;
                e.preventDefault();
                setDrag(false);
                upload(e.dataTransfer.files);
              }}
              onClick={() => fileRef.current?.click()}
            >
              <FileUp size={22} />
              <div>
                <strong>PDF를 끌어다 놓거나 클릭해서 업로드</strong>
                <div className="muted small">
                  {typeof filter === "number" ? `"${folderName(filter)?.name}" 폴더에 추가됩니다.` : "업로드한 논문은 이 컴퓨터의 data/ 폴더에만 저장됩니다."}
                </div>
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

            <div className="paper-grid">
              {shown.map((p) => {
                const f = folderName(p.folder_id);
                return (
                  <div
                    key={p.id}
                    className="paper-card"
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/paper-id", p.id)}
                    onClick={() => nav(`/paper/${p.id}`)}
                  >
                    <div className="paper-title">{p.title}</div>
                    <div className="muted small">
                      {p.pages}쪽 · {new Date(p.added_at * 1000).toLocaleDateString()} 추가
                      {p.last_read ? ` · ${lastReadText(p.last_read)}` : ""}
                    </div>
                    {p.meta?.author && <div className="muted small">{p.meta.author}</div>}
                    <div className="card-actions" onClick={(e) => e.stopPropagation()}>
                      <select
                        className="folder-select"
                        value={p.folder_id ?? ""}
                        style={f ? { borderColor: f.color, color: f.color } : undefined}
                        onChange={(e) => move(p, e.target.value === "" ? null : Number(e.target.value))}
                        title="폴더 이동"
                      >
                        <option value="">미분류</option>
                        {folders.map((x) => (
                          <option key={x.id} value={x.id}>{x.name}</option>
                        ))}
                      </select>
                      <button className="btn ghost small danger" onClick={() => remove(p)}>
                        <Trash2 size={14} /> 삭제
                      </button>
                    </div>
                  </div>
                );
              })}
              {shown.length === 0 && (
                <div className="muted">
                  {papers.length === 0 ? "아직 논문이 없습니다. PDF를 올려 시작하세요." : "이 폴더에 논문이 없습니다. 논문 카드를 폴더로 끌어다 놓거나 카드의 폴더 선택으로 옮길 수 있습니다."}
                </div>
              )}
            </div>
          </main>
        </div>
      )}
    </div>
  );
}
