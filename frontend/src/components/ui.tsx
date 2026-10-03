import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type Meta, type Project, type ProjectStatus, type StageStatus } from "../api";

export function usePid(): number {
  const { pid } = useParams();
  return Number(pid);
}

export function useProject(pid: number) {
  return useQuery({ queryKey: ["project", pid], queryFn: () => api.get<Project>(`/api/projects/${pid}`), enabled: !!pid });
}

export function useStatus(pid: number) {
  return useQuery({ queryKey: ["status", pid], queryFn: () => api.get<ProjectStatus>(`/api/projects/${pid}/status`), enabled: !!pid });
}

export function useMeta() {
  return useQuery({ queryKey: ["meta"], queryFn: () => api.get<Meta>("/api/meta"), staleTime: 60_000 });
}

type Theme = "light" | "dark";
function readTheme(): Theme {
  try {
    return (localStorage.getItem("ew-theme") as Theme) || "light";
  } catch {
    return "light";
  }
}
export function useTheme(): [Theme, () => void] {
  const [t, setT] = useState<Theme>(readTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = t;
    try {
      localStorage.setItem("ew-theme", t);
    } catch {
      /* private mode */
    }
  }, [t]);
  return [t, () => setT((x) => (x === "light" ? "dark" : "light"))];
}

/** Plain-language label with the technical term in a tooltip. */
export function Term({ tip, children }: { tip: string; children: React.ReactNode }) {
  return (
    <span className="term" data-tip={tip} tabIndex={0}>
      {children}
    </span>
  );
}

export function StatusIcon({ status, n }: { status: StageStatus; n?: number }) {
  // Shape + label, never colour alone.
  const label = { locked: "Locked", ready: "Ready", in_progress: "In progress", done: "Done" }[status];
  const base = "inline-flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-semibold";
  if (status === "done")
    return (
      <span className={`${base} bg-pass-500 text-white`} aria-label={label} title={label}>
        ✓
      </span>
    );
  if (status === "locked")
    return (
      <span className={`${base} border border-dashed border-ink-500 text-mist-500`} aria-label={label} title={label}>
        <svg width="8" height="9" viewBox="0 0 8 9" fill="currentColor"><rect x="0.5" y="4" width="7" height="5" rx="1" /><path d="M2 4V2.8a2 2 0 0 1 4 0V4" stroke="currentColor" fill="none" strokeWidth="1" /></svg>
      </span>
    );
  if (status === "in_progress")
    return (
      <span className={`${base} border-[1.5px] border-accent-400 text-accent-400`} aria-label={label} title={label} style={{ background: "conic-gradient(rgb(var(--accent-400)) 0 50%, transparent 50% 100%)" }}>
        <span className="h-[11px] w-[11px] rounded-full bg-ink-950" />
      </span>
    );
  return (
    <span className={`${base} border-[1.5px] border-mist-400 text-mist-300`} aria-label={label} title={label}>
      {n ?? ""}
    </span>
  );
}

export function PageHeader({ title, sub, right, term }: { title: string; sub?: React.ReactNode; right?: React.ReactNode; term?: string | null }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-6">
      <div className="min-w-0">
        <h1 className="h1">{term ? <Term tip={term}>{title}</Term> : title}</h1>
        {sub && <p className="mt-1 max-w-3xl text-[13px] text-mist-400">{sub}</p>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={`mx-auto px-6 py-6 ${wide ? "max-w-[1400px]" : "max-w-5xl"}`}>{children}</div>;
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger" | "ok"; children: React.ReactNode }) {
  const cls = {
    info: "border-ink-700 bg-ink-900 text-mist-300",
    warn: "border-warn-400/30 bg-warn-900/60 text-warn-400",
    danger: "border-fail-500/30 bg-fail-900/60 text-fail-400",
    ok: "border-pass-500/30 bg-pass-900/60 text-pass-400",
  }[tone];
  const icon = { info: "ℹ", warn: "!", danger: "✕", ok: "✓" }[tone];
  return (
    <div className={`flex gap-2 rounded-md border px-3 py-2 text-[13px] ${cls}`}>
      <span className="font-bold">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-ink-600 p-8 text-center text-[13px] text-mist-400">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-[13px] text-mist-400">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-ink-600 border-t-accent-400" />
      {label}
    </div>
  );
}

export function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div className="panel px-3 py-2.5">
      <div className="label mb-0.5">{label}</div>
      <div className="text-lg font-semibold tabular-nums text-mist-50">{value}</div>
      {sub && <div className="text-xs text-mist-400">{sub}</div>}
    </div>
  );
}

export function VerdictBadge({ verdict, deferred }: { verdict?: string | null; deferred?: boolean }) {
  if (verdict === "pass") return <span className="inline-flex items-center gap-1 rounded bg-pass-900 px-1.5 text-xs font-medium text-pass-400">✓ Pass</span>;
  if (verdict === "fail") return <span className="inline-flex items-center gap-1 rounded bg-fail-900 px-1.5 text-xs font-medium text-fail-400">✕ Fail</span>;
  if (deferred) return <span className="inline-flex items-center gap-1 rounded bg-warn-900 px-1.5 text-xs font-medium text-warn-400">↻ Later</span>;
  return <span className="inline-flex items-center gap-1 rounded bg-ink-800 px-1.5 text-xs text-mist-400">· Open</span>;
}

export function pct(x: number | null | undefined, digits = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

/** Shown on hosted public demos: AI is simulated and data resets on a schedule. */
export function DemoBanner() {
  const meta = useMeta();
  const [msg, setMsg] = useState("");
  if (!meta.data?.demo_mode) return null;
  const reset = async () => {
    if (!confirm("Reset the demo to its starting state? Everyone's changes are cleared.")) return;
    try {
      await api.post("/api/demo/reset");
      setMsg("Resetting… reload in about 30 seconds.");
    } catch (e: any) {
      setMsg(e.message);
    }
  };
  return (
    <div className="flex h-8 shrink-0 items-center justify-center gap-3 border-b border-warn-400/30 bg-warn-900/60 px-3 text-xs text-warn-400">
      <span>
        <b>Public demo.</b> AI responses are simulated (no real model calls), and data resets every {meta.data.demo_reset_hours ?? 24}h. Start with the pre-filled walkthrough, or try the blank Larkspur project yourself.
      </span>
      <button className="underline hover:text-mist-50" onClick={reset}>Reset now</button>
      {msg && <span className="text-mist-300">{msg}</span>}
    </div>
  );
}
