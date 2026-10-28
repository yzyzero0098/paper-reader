export interface Paper {
  id: string;
  title: string;
  filename: string;
  pages: number;
  added_at: number;
  meta: Record<string, string>;
  folder_id: number | null;
  last_page: number | null;
  last_read: number | null;
}

export interface Folder {
  id: number;
  name: string;
  color: string;
  count: number;
}

export interface ReadingEntry {
  paper_id: string;
  title: string;
  seconds: number;
  folder_id: number | null;
  folder_name: string | null;
  folder_color: string | null;
}

export interface ReadingMonth {
  month: string;
  days: Record<string, ReadingEntry[]>;
  total_seconds: number;
  papers: number;
}

export type BlockKind = "text" | "heading" | "caption" | "small" | "reference";

export interface Block {
  id: string;
  bbox: [number, number, number, number];
  text: string;
  kind: BlockKind;
  size: number;
  lines: number;
  bold: boolean;
}

export interface Figure {
  id: string;
  kind: "figure" | "table";
  bbox: [number, number, number, number];
  caption: string;
  caption_bbox: [number, number, number, number] | null;
}

export interface Citation {
  text: string;
  style: "numeric" | "author-year";
  refs: number[];
  authors?: string;
  rects: [number, number, number, number][];
}

export interface Layout {
  page: number;
  width: number;
  height: number;
  body_size: number;
  blocks: Block[];
  figures: Figure[];
  citations: Citation[];
}

export type Rect = [number, number, number, number];

export interface Sentence {
  id: string;
  text: string;
  t: string;
  rects: Rect[];
  /** this sentence continues on a later page: the part on that page */
  cont?: { page: number; rects: Rect[] };
  /** this fragment ends a sentence that starts on an earlier page (translated there) */
  ref?: { page: number; sid: string };
}

export interface TranslatedBlock {
  id: string;
  kind: BlockKind;
  bbox: Rect;
  size: number;
  lines: number;
  text: string;
  t: string;
  sentences: Sentence[];
  /** overlay mode: one box per column run; the main box carries the translation */
  boxes?: { bbox: Rect; main: boolean }[];
}

export interface ActiveSentence {
  page: number;
  sid: string;
  rects: Rect[];
  cont?: { page: number; rects: Rect[] };
}

export interface Reference {
  n: number;
  raw: string;
  doi: string;
  year: string;
  first_author: string;
  meta?: ReferenceMeta;
}

export interface ReferenceMeta {
  title?: string;
  authors?: string[];
  year?: string;
  journal?: string;
  doi?: string;
  url?: string;
  abstract?: string;
  cited_by?: number;
}

export interface Highlight {
  id: number;
  paper_id: string;
  page: number;
  rects: [number, number, number, number][];
  color: string;
  text: string;
  note: string;
  created_at: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatGPTAuthStatus {
  logged_in: boolean;
  email?: string;
  sharing?: boolean;
  scopes?: string[];
  expires_at?: number;
  pending?: boolean;
  last_error?: string;
}

export interface ProviderInfo {
  label: string;
  model: string;
  models: string[];
  base_url: string;
  vision: boolean;
  oauth?: boolean;
  auth?: ChatGPTAuthStatus;
  key_set: boolean;
  key_hint: string;
  key_from_env: boolean;
}

export interface Settings {
  target_lang: string;
  default_provider: string;
  vision_provider: string;
  languages: Record<string, string>;
  providers: Record<string, ProviderInfo>;
}

export interface UsageAgg {
  input: number;
  output: number;
  calls: number;
}

export interface UsageSummary {
  today: UsageAgg;
  total: UsageAgg;
  paper?: UsageAgg;
  window_5h: UsageAgg;
  window_7d: UsageAgg;
  chatgpt_5h: UsageAgg;
  chatgpt_7d: UsageAgg;
  limit_hit_at: number | null;
  by_provider_today: { provider: string; model: string; input: number; output: number; calls: number }[];
  by_kind_today: { kind: string; input: number; output: number; calls: number }[];
}

export type Effort = "low" | "medium" | "high";

export type ExplainKind = "text" | "equation" | "term" | "figure" | "table" | "citation";
