import { useQuery } from "@tanstack/react-query";
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

/** Plain-language label with the technical term in a tooltip. */
export function Term({ tip, children }: { tip: string; children: React.ReactNode }) {
  return (
    <span className="term" data-tip={tip} tabIndex={0}>
      {children}
    </span>
  );
}

export function StatusIcon({ status }: { status: StageStatus }) {
  // Shape + text, never colour alone.
  const map: Record<StageStatus, { icon: string; cls: string; label: string }> = {
    locked: { icon: "🔒", cls: "text-mist-500", label: "Locked" },
    ready: { icon: "○", cls: "text-gold-300", label: "Ready" },
    in_progress: { icon: "◐", cls: "text-gold-400", label: "In progress" },
    done: { icon: "✓", cls: "text-pass-400", label: "Done" },
  };
  const m = map[status];
  return (
    <span className={`inline-flex w-5 justify-center text-sm ${m.cls}`} aria-label={m.label} title={m.label}>
      {m.icon}
    </span>
  );
}

export function PageHeader({ title, sub, right, term }: { title: string; sub?: React.ReactNode; right?: React.ReactNode; term?: string | null }) {
  return (
    <div className="mb-6 flex items-start justify-between gap-6">
      <div>
        <h1 className="h1">{term ? <Term tip={term}>{title}</Term> : title}</h1>
        {sub && <p className="mt-1 max-w-3xl text-sm text-mist-300">{sub}</p>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger" | "ok"; children: React.ReactNode }) {
  const cls = {
    info: "border-ink-600 bg-ink-850 text-mist-200",
    warn: "border-gold-500/40 bg-gold-500/10 text-gold-300",
    danger: "border-fail-500/40 bg-fail-900/40 text-fail-400",
    ok: "border-pass-500/40 bg-pass-900/40 text-pass-400",
  }[tone];
  const icon = { info: "ℹ", warn: "!", danger: "✕", ok: "✓" }[tone];
  return (
    <div className={`flex gap-2 rounded-lg border px-3 py-2 text-sm ${cls}`}>
      <span className="font-bold">{icon}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-ink-600 p-8 text-center text-sm text-mist-400">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-mist-400">
      <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-mist-500 border-t-gold-400" />
      {label}
    </div>
  );
}

export function pct(x: number | null | undefined, digits = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}
