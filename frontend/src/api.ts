import type {
  ChatGPTAuthStatus, ChatMessage, ExplainKind, Highlight, Layout, Paper, Reference, Settings, TranslatedBlock, UsageSummary,
} from "./types";

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return res.json();
}

const post = (url: string, body: unknown, method = "POST") =>
  fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  // papers
  listPapers: () => fetch("/api/papers").then((r) => json<Paper[]>(r)),
  getPaper: (id: string) => fetch(`/api/papers/${id}`).then((r) => json<Paper>(r)),
  uploadPaper: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/papers", { method: "POST", body: fd }).then((r) => json<Paper>(r));
  },
  deletePaper: (id: string) => fetch(`/api/papers/${id}`, { method: "DELETE" }).then((r) => json(r)),
  renamePaper: (id: string, title: string) => post(`/api/papers/${id}`, { title }, "PATCH").then((r) => json<Paper>(r)),
  fileUrl: (id: string) => `/api/papers/${id}/file`,
  figureUrl: (id: string, fid: string, caption = 1) => `/api/papers/${id}/figures/${fid}/image?caption=${caption}`,

  layout: (id: string, page: number) => fetch(`/api/papers/${id}/pages/${page}/layout`).then((r) => json<Layout>(r)),
  translatePage: (id: string, page: number, lang: string, force = false) =>
    fetch(`/api/papers/${id}/pages/${page}/translate?lang=${lang}${force ? "&force=1" : ""}`).then((r) =>
      json<TranslatedBlock[]>(r),
    ),
  translateText: (id: string, text: string, lang: string, model?: string) =>
    post(`/api/papers/${id}/translate-text`, { text, lang, model: model || null }).then((r) => json<{ t: string }>(r)),

  references: (id: string) => fetch(`/api/papers/${id}/references`).then((r) => json<Reference[]>(r)),
  lookupReference: (id: string, n: number) =>
    fetch(`/api/papers/${id}/references/${n}/lookup`).then((r) => json<Reference>(r)),
  resolveCitation: (id: string, c: { text: string; style: string; refs: number[]; authors?: string }) =>
    post(`/api/papers/${id}/citations/resolve`, c).then((r) => json<Reference[]>(r)),

  summary: (id: string, lang: string) =>
    fetch(`/api/papers/${id}/summary?lang=${lang}`).then((r) => json<{ summary: string | null }>(r)),

  chat: (id: string) => fetch(`/api/papers/${id}/chat`).then((r) => json<{ messages: ChatMessage[] }>(r)),
  saveChat: (id: string, messages: ChatMessage[]) => post(`/api/papers/${id}/chat`, { messages }, "PUT"),

  highlights: (id: string) => fetch(`/api/papers/${id}/highlights`).then((r) => json<Highlight[]>(r)),
  addHighlight: (id: string, h: Omit<Highlight, "id" | "paper_id" | "created_at">) =>
    post(`/api/papers/${id}/highlights`, h).then((r) => json<{ id: number }>(r)),
  patchHighlight: (id: string, hid: number, patch: { note?: string; color?: string }) =>
    post(`/api/papers/${id}/highlights/${hid}`, patch, "PATCH"),
  deleteHighlight: (id: string, hid: number) => fetch(`/api/papers/${id}/highlights/${hid}`, { method: "DELETE" }),

  // settings
  settings: () => fetch("/api/settings").then((r) => json<Settings>(r)),
  saveSettings: (patch: unknown) => post("/api/settings", patch, "PUT").then((r) => json<Settings>(r)),
  listModels: (provider: string) =>
    fetch(`/api/settings/models?provider=${provider}`).then((r) => json<{ models: string[] }>(r)),
  testProvider: (provider: string) => post("/api/settings/test", { provider }).then((r) => json<{ ok: boolean; reply: string }>(r)),

  usage: (paperId?: string) =>
    fetch(`/api/usage${paperId ? `?paper_id=${paperId}` : ""}`).then((r) => json<UsageSummary>(r)),

  // Sign in with ChatGPT
  chatgptStart: () => post("/api/auth/chatgpt/start", {}).then((r) => json<{ url: string }>(r)),
  chatgptStatus: () => fetch("/api/auth/chatgpt/status").then((r) => json<ChatGPTAuthStatus>(r)),
  chatgptLogout: () => post("/api/auth/chatgpt/logout", {}).then((r) => json(r)),
};

/** Consume a server-sent-event stream of {t: "..."} chunks. */
export async function streamSSE(
  url: string,
  body: unknown,
  onChunk: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const evt = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of evt.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const d = JSON.parse(line.slice(6));
        if (d.error) throw new Error(d.error);
        if (d.t) onChunk(d.t);
      }
    }
  }
}

export function explainStream(
  paperId: string,
  body: {
    kind: ExplainKind; page: number; text?: string; figure_id?: string; refs?: unknown[]; question?: string; lang: string;
    model?: string | null; effort?: string;
  },
  onChunk: (t: string) => void,
  signal?: AbortSignal,
) {
  return streamSSE(`/api/papers/${paperId}/explain`, body, onChunk, signal);
}
