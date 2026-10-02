import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { StatusIcon, Term, useMeta, usePid, useProject, useStatus } from "./ui";

export const STAGE_ROUTES: Record<string, string> = {
  setup: "setup",
  traces: "traces",
  review: "review",
  group: "group",
  count: "count",
  decide: "decide",
  build: "build",
  validate: "validate",
  run: "run",
  export: "export",
};

export function Layout() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus(pid);
  const meta = useMeta();
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  const reviewing = loc.pathname.endsWith("/review");

  return (
    <div className="flex h-full">
      <aside className={`flex shrink-0 flex-col border-r border-ink-800 bg-ink-900 ${reviewing ? "w-[64px]" : "w-[272px]"}`}>
        <Link to="/" className="flex items-center gap-2 border-b border-ink-800 px-4 py-3.5" title="All projects">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-gold-400 font-bold text-ink-950">E</span>
          {!reviewing && (
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-mist-50">{project.data?.name ?? "…"}</div>
              <div className="text-[11px] text-mist-400">Evals Workbench</div>
            </div>
          )}
        </Link>
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          <NavLink
            end
            to={`/p/${pid}`}
            className={({ isActive }) => `mb-2 flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${isActive ? "bg-ink-800 text-mist-50" : "text-mist-300 hover:bg-ink-850"}`}
            title="Home"
          >
            <span className="inline-flex w-5 justify-center">⌂</span>
            {!reviewing && "Home"}
          </NavLink>
          {!reviewing && <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-mist-500">Workflow</div>}
          <ol className="space-y-0.5">
            {(status.data?.stages ?? []).map((s, i) => (
              <li key={s.key}>
                <NavLink
                  to={`/p/${pid}/${STAGE_ROUTES[s.key]}`}
                  title={`${s.title} — ${s.status === "locked" ? s.unlock : s.next}`}
                  className={({ isActive }) =>
                    `group flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${isActive ? "bg-ink-800 text-mist-50 ring-1 ring-gold-400/30" : s.status === "locked" ? "text-mist-500 hover:bg-ink-850" : "text-mist-200 hover:bg-ink-850"}`
                  }
                >
                  <StatusIcon status={s.status} />
                  {!reviewing && (
                    <div className="min-w-0">
                      <div className="leading-5">
                        <span className="mr-1 text-mist-500">{i + 1}.</span>
                        {s.term ? <Term tip={s.term}>{s.title}</Term> : s.title}
                      </div>
                      <div className="line-clamp-2 text-[11.5px] leading-4 text-mist-400">{s.status === "locked" ? s.unlock : s.next}</div>
                    </div>
                  )}
                </NavLink>
              </li>
            ))}
          </ol>
        </nav>
        <div className="space-y-1 border-t border-ink-800 p-2 text-sm">
          <button onClick={() => setDrawer(true)} className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-mist-300 hover:bg-ink-850" title="AI activity">
            <span className="inline-flex w-5 justify-center">✦</span>
            {!reviewing && "AI activity"}
          </button>
          <NavLink to={`/p/${pid}/settings`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-mist-300 hover:bg-ink-850" title="Settings">
            <span className="inline-flex w-5 justify-center">⚙</span>
            {!reviewing && "Settings"}
          </NavLink>
          {!reviewing && meta.data && (
            <div className="px-2 pt-1 text-[11px] text-mist-500">
              AI: {status.data?.ai.enabled === false ? "switched off" : meta.data.llm_mode === "mock" ? "mock mode (no API calls)" : meta.data.model}
            </div>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
      {drawer && <AIDrawer pid={pid} onClose={() => setDrawer(false)} />}
    </div>
  );
}

type Call = { id: number; job: string; model: string; mode: string; request: any; response: string; input_tokens: number; output_tokens: number; cost_usd: number; latency_ms: number; error: string; created_at: string };

function AIDrawer({ pid, onClose }: { pid: number; onClose: () => void }) {
  const q = useQuery({ queryKey: ["llm_calls", pid], queryFn: () => api.get<{ totals: any; calls: Call[] }>(`/api/llm_calls?project_id=${pid}`), refetchInterval: 4000 });
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <div className="flex h-full w-[560px] flex-col border-l border-ink-700 bg-ink-900" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <div>
            <div className="h2">AI activity</div>
            <div className="text-xs text-mist-400">Every prompt this project sent to the model, with the full response, tokens and cost.</div>
          </div>
          <button className="btn-quiet" onClick={onClose}>
            Close <span className="kbd">Esc</span>
          </button>
        </div>
        {q.data && (
          <div className="grid grid-cols-3 gap-3 border-b border-ink-800 px-5 py-3 text-sm">
            <div><div className="label">Calls</div>{q.data.totals.calls}</div>
            <div><div className="label">Tokens in / out</div>{q.data.totals.input_tokens.toLocaleString()} / {q.data.totals.output_tokens.toLocaleString()}</div>
            <div><div className="label">Cost</div>${Number(q.data.totals.cost_usd).toFixed(4)}</div>
          </div>
        )}
        <div className="flex-1 space-y-2 overflow-y-auto p-4">
          {q.data?.calls.length === 0 && <div className="text-sm text-mist-400">No AI calls yet.</div>}
          {q.data?.calls.map((c) => (
            <div key={c.id} className="rounded-lg border border-ink-700 bg-ink-950">
              <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" onClick={() => setOpen(open === c.id ? null : c.id)}>
                <span className="font-mono text-gold-300">{c.job}</span>
                <span className="chip">{c.mode}</span>
                {c.error && <span className="chip border-fail-500/50 text-fail-400">error</span>}
                <span className="ml-auto text-xs text-mist-400">
                  {c.input_tokens + c.output_tokens} tok · ${c.cost_usd.toFixed(4)} · {c.latency_ms}ms
                </span>
              </button>
              {open === c.id && (
                <div className="space-y-2 border-t border-ink-800 p-3 text-xs">
                  <div className="text-mist-400">{new Date(c.created_at).toLocaleString()} · {c.model}</div>
                  {c.error && <div className="text-fail-400">{c.error}</div>}
                  <div className="label">Prompt</div>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-ink-900 p-2 font-mono text-mist-200">{c.request?.prompt}</pre>
                  <div className="label">Response</div>
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-ink-900 p-2 font-mono text-mist-200">{c.response}</pre>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
