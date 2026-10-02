export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: form ? undefined : body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(p: string) => req<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => req<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b?: unknown) => req<T>("PUT", p, b ?? {}),
  patch: <T,>(p: string, b?: unknown) => req<T>("PATCH", p, b ?? {}),
  del: <T,>(p: string) => req<T>("DELETE", p),
  form: <T,>(p: string, f: FormData) => req<T>("POST", p, undefined, f),
};

// ---------- shared types ----------
export type Channel = { name: string; render_rule: string };

export type Project = {
  id: number;
  name: string;
  description: string;
  channels: Channel[];
  business_facts: string;
  reviewer_name: string;
  settings: Record<string, any>;
  is_demo: boolean;
  review_round: number;
};

export type StageStatus = "locked" | "ready" | "in_progress" | "done";
export type Stage = { key: string; title: string; summary: string; term: string | null; status: StageStatus; unlock: string; next: string };

export type ProjectStatus = {
  stages: Stage[];
  next: Stage | null;
  counts: Record<string, number>;
  ai: { enabled: boolean; reviewed: number; threshold: number; unlocked: boolean; reason: string | null };
  saturation: { window: number; reviewed: number; new_in_window: number; suggest_stop: boolean; series: number[] };
};

export type TraceEvent = {
  id: number;
  seq: number;
  role: "user" | "assistant" | "tool_call" | "tool_result" | "system";
  content: string;
  tool_name: string;
  tool_args: Record<string, any>;
  tool_result: string;
  tool_call_id: string;
};

export type TraceView = {
  id: number;
  external_id: string;
  channel: string;
  meta: Record<string, any>;
  synthetic: boolean;
  synthetic_tuple?: Record<string, any>;
  prompt_version?: string | null;
  system_prompt: string;
  system_prompt_hash?: string;
  n_turns: number;
  n_tool_calls: number;
  events: TraceEvent[];
  raw?: any;
};

export type Facet =
  | { key: string; kind: "category"; values: { value: string; count: number }[] }
  | { key: string; kind: "number"; min: number; max: number; count: number };

export type BatchSummary = {
  id: number;
  name: string;
  method: string;
  params: Record<string, any>;
  size: number;
  reviewed: number;
  reasons: Record<string, number>;
  created_at: string;
};

export type Meta = { llm_mode: string; model: string; has_key: boolean; concurrency: number };
