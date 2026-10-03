import { Fragment, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { DemoBanner, StatusIcon, Term, useMeta, usePid, useProject, useStatus, useTheme } from "./ui";

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

export function Logo() {
  return (
    <span className="grid h-6 w-6 place-items-center rounded-md bg-mist-50 text-ink-950">
      <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"><path d="M2 12l4-4 3 3 5-7" /></svg>
    </span>
  );
}

export function Layout() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus(pid);
  const meta = useMeta();
  const [theme, toggleTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  const seg = loc.pathname.split("/")[3] ?? "";
  const reviewing = seg === "review";
  const current = status.data?.stages.find((s) => STAGE_ROUTES[s.key] === seg);
  const pageName = current?.title ?? ({ settings: "Settings", glossary: "Glossary", synthetic: "Synthetic inputs" } as Record<string, string>)[seg] ?? "Overview";
  const ai = status.data?.ai;

  return (
    <div className="flex h-full flex-col">
      <DemoBanner />
      <header className="flex h-11 shrink-0 items-center gap-2.5 border-b border-ink-700 bg-ink-950 px-3">
        <Link to="/" className="flex items-center gap-2 text-[13px] font-semibold text-mist-50" title="All projects">
          <Logo /> <span className="hidden sm:inline">Evals Workbench</span>
        </Link>
        <span className="text-mist-500">/</span>
        <Link to={`/p/${pid}`} className="max-w-[260px] truncate text-[13px] text-mist-300 hover:text-mist-50">{project.data?.name ?? "…"}</Link>
        <span className="text-mist-500">/</span>
        <span className="text-[13px] font-medium text-mist-50">{pageName}</span>
        <div className="ml-auto flex items-center gap-1">
          {meta.data && ai && (
            <span className="chip mr-1" title="Where AI-assist calls go">
              <span className={`h-1.5 w-1.5 rounded-full ${!ai.enabled ? "bg-mist-500" : meta.data.llm_mode === "mock" ? "bg-warn-400" : "bg-pass-500"}`} />
              {!ai.enabled ? "AI off" : meta.data.llm_mode === "mock" ? "Mock LLM" : meta.data.model}
            </span>
          )}
          <button onClick={() => setDrawer(true)} className="btn-quiet btn-sm" title="Every prompt sent to the model">AI activity</button>
          <NavLink to={`/p/${pid}/glossary`} className="btn-quiet btn-sm">Glossary</NavLink>
          <NavLink to={`/p/${pid}/settings`} className="btn-quiet btn-sm">Settings</NavLink>
          <button onClick={toggleTheme} className="btn-quiet btn-sm w-7 justify-center px-0" title={`Switch to ${theme === "light" ? "dark" : "light"} theme`} aria-label="Toggle theme">
            {theme === "light" ? "☾" : "☀"}
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className={`flex shrink-0 flex-col border-r border-ink-700 bg-ink-900 ${reviewing ? "w-12" : "w-60"}`}>
          <nav className="flex-1 overflow-y-auto px-2 py-2">
            <NavLink
              end
              to={`/p/${pid}`}
              className={({ isActive }) => `mb-1 flex h-8 items-center gap-2 rounded-md px-2 text-[13px] ${isActive ? "bg-ink-800 font-medium text-mist-50" : "text-mist-300 hover:bg-ink-850"}`}
              title="Overview"
            >
              <span className="inline-flex w-[18px] justify-center text-mist-400">⌂</span>
              {!reviewing && "Overview"}
            </NavLink>
            {!reviewing && <div className="mb-1 mt-3 px-2 text-xxs font-medium uppercase tracking-wide text-mist-500">Workflow</div>}
            <ol className="space-y-px">
              {(status.data?.stages ?? []).map((s, i) => (
                <li key={s.key}>
                  <NavLink
                    to={`/p/${pid}/${STAGE_ROUTES[s.key]}`}
                    title={`${i + 1}. ${s.title} — ${s.status === "locked" ? s.unlock : s.next}`}
                    className={({ isActive }) =>
                      `flex items-start gap-2 rounded-md px-2 py-1.5 text-[13px] ${isActive ? "bg-ink-800 text-mist-50" : s.status === "locked" ? "text-mist-500 hover:bg-ink-850" : "text-mist-200 hover:bg-ink-850"}`
                    }
                  >
                    <span className="pt-px"><StatusIcon status={s.status} n={i + 1} /></span>
                    {!reviewing && (
                      <div className="min-w-0">
                        <div className="truncate leading-[18px]">{s.term ? <Term tip={s.term}>{s.title}</Term> : s.title}</div>
                        {s.status !== "done" && <div className="line-clamp-2 text-xxs text-mist-400">{s.status === "locked" ? s.unlock : s.next}</div>}
                      </div>
                    )}
                  </NavLink>
                </li>
              ))}
            </ol>
          </nav>
          {!reviewing && status.data && (
            <div className="space-y-0.5 border-t border-ink-700 px-3 py-2.5 text-xxs text-mist-400">
              <div className="flex justify-between"><span>Traces</span><span className="tabular-nums text-mist-200">{status.data.counts.traces}</span></div>
              <div className="flex justify-between"><span>Reviewed</span><span className="tabular-nums text-mist-200">{status.data.counts.reviewed}</span></div>
              <div className="flex justify-between"><span>AI assist</span><span className="text-mist-200">{status.data.ai.unlocked ? "unlocked" : status.data.ai.enabled ? `locked · ${status.data.ai.reviewed}/${status.data.ai.threshold}` : "off"}</span></div>
            </div>
          )}
        </aside>
        <main className="min-w-0 flex-1 overflow-y-auto bg-ink-950">
          <Outlet />
        </main>
      </div>
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
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-[600px] flex-col border-l border-ink-700 bg-ink-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <div>
            <div className="h2">AI activity</div>
            <div className="text-xs text-mist-400">Every prompt this project sent to the model, with the response, tokens and cost.</div>
          </div>
          <button className="btn-quiet btn-sm" onClick={onClose}>Close <span className="kbd">Esc</span></button>
        </div>
        {q.data && (
          <div className="grid grid-cols-3 gap-2 border-b border-ink-700 px-4 py-3">
            <div><div className="label">Calls</div><div className="tabular-nums">{q.data.totals.calls}</div></div>
            <div><div className="label">Tokens in / out</div><div className="tabular-nums">{q.data.totals.input_tokens.toLocaleString()} / {q.data.totals.output_tokens.toLocaleString()}</div></div>
            <div><div className="label">Cost</div><div className="tabular-nums">${Number(q.data.totals.cost_usd).toFixed(4)}</div></div>
          </div>
        )}
        <div className="flex-1 overflow-y-auto">
          {q.data?.calls.length === 0 && <div className="p-4 text-mist-400">No AI calls yet.</div>}
          <table className="tbl">
            <tbody>
              {q.data?.calls.map((c) => (
                <Fragment key={c.id}>
                  <tr className="cursor-pointer" onClick={() => setOpen(open === c.id ? null : c.id)}>
                    <td className="font-mono text-xs text-accent-300">{c.job}</td>
                    <td><span className="chip">{c.mode}</span>{c.error && <span className="chip ml-1 text-fail-400">error</span>}</td>
                    <td className="text-right text-xs tabular-nums text-mist-400">{c.input_tokens + c.output_tokens} tok · ${c.cost_usd.toFixed(4)} · {c.latency_ms}ms</td>
                  </tr>
                  {open === c.id && (
                    <tr>
                      <td colSpan={3} className="bg-ink-900">
                        <div className="mb-1 text-xs text-mist-400">{new Date(c.created_at).toLocaleString()} · {c.model}</div>
                        {c.error && <div className="mb-1 text-xs text-fail-400">{c.error}</div>}
                        <div className="label">Prompt</div>
                        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-ink-700 bg-ink-950 p-2 font-mono text-xs text-mist-200">{c.request?.prompt}</pre>
                        <div className="label mt-2">Response</div>
                        <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded border border-ink-700 bg-ink-950 p-2 font-mono text-xs text-mist-200">{c.response}</pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
