import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Facet } from "../api";
import { MetricsPanel, type Metrics } from "../components/metrics";
import { TracePreview } from "../components/TracePreview";
import { Empty, Notice, PageHeader, Spinner, Term, usePid, useProject, useStatus } from "../components/ui";
import { useModes } from "./Group";

export type EvalView = {
  id: number;
  type: "code" | "judge";
  name: string;
  slug: string;
  status: string;
  failure_mode_id: number | null;
  failure_mode: string | null;
  owner: string;
  where_to_run: string;
  threshold: number;
  target: number;
  active_version_id: number | null;
  latest_version: number | null;
  latest_version_id: number | null;
  last_dev: { id: number; status: string; metrics: Metrics; version_id: number } | null;
  last_final: { id: number; status: string; metrics: Metrics; version_id: number } | null;
};
export type Version = { id: number; version: number; definition: any; context_scope: string[]; model: string; few_shot_ids: number[]; note: string; created_at: string };
export type EvalDetail = EvalView & {
  versions: Version[];
  runs: { id: number; kind: string; status: string; progress: number; total: number; metrics: any; version: number; created_at: string; error: string }[];
  version_table: { version: number; dev: Metrics | null; test: Metrics | null; n_final_runs: number }[];
};

export const STATUS_CHIP: Record<string, string> = {
  draft: "border-ink-600 text-mist-300",
  active: "border-pass-500/50 text-pass-400",
  validated: "border-pass-500/50 text-pass-400",
  retired: "border-ink-600 text-mist-500",
};

export function useEvaluators(pid: number) {
  return useQuery({ queryKey: ["evaluators", pid], queryFn: () => api.get<EvalView[]>(`/api/projects/${pid}/evaluators`) });
}

export function Build() {
  const pid = usePid();
  const qc = useQueryClient();
  const status = useStatus(pid);
  const [params, setParams] = useSearchParams();
  const evs = useEvaluators(pid);
  const modes = useModes(pid);
  const sel = Number(params.get("e")) || null;
  const [err, setErr] = useState("");
  const create = useMutation({
    mutationFn: (b: { type: string; failure_mode_id: number }) => api.post<EvalView>(`/api/projects/${pid}/evaluators`, b),
    onSuccess: (ev) => {
      qc.invalidateQueries({ queryKey: ["evaluators", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
      setParams({ e: String(ev.id) });
    },
    onError: (e: any) => setErr(e.message),
  });
  useEffect(() => {
    const n = params.get("new");
    const fm = Number(params.get("fm"));
    if (n && fm && evs.data && !create.isPending) {
      const existing = evs.data.find((e) => e.failure_mode_id === fm && e.type === n && e.status !== "retired");
      if (existing) setParams({ e: String(existing.id) });
      else create.mutate({ type: n, failure_mode_id: fm });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, evs.data]);

  const stage = status.data?.stages.find((s) => s.key === "build");
  if (stage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader title="Build evaluators" />
        <Notice>{stage.unlock} <Link className="underline" to={`/p/${pid}/decide`}>Go to Decide →</Link></Notice>
      </div>
    );
  const wanted = (modes.data ?? []).filter((m) => (m.decision === "code_check" || m.decision === "llm_judge") && !(evs.data ?? []).some((e) => e.failure_mode_id === m.id && e.type === (m.decision === "code_check" ? "code" : "judge") && e.status !== "retired"));
  return (
    <div className="grid h-full grid-cols-[300px_minmax(0,1fr)]">
      <aside className="overflow-y-auto border-r border-ink-700 bg-ink-900 p-3">
        <div className="mb-2 h2">Evaluators</div>
        {err && <div className="mb-2"><Notice tone="danger">{err}</Notice></div>}
        <div className="space-y-1.5">
          {evs.data?.map((e) => (
            <button key={e.id} onClick={() => setParams({ e: String(e.id) })} className={`block w-full rounded-md border px-3 py-2 text-left ${sel === e.id ? "border-accent-400 bg-ink-950" : "border-ink-700 bg-ink-950 hover:border-ink-500"}`}>
              <div className="flex items-center gap-2">
                <span className="chip h-5 text-xxs">{e.type === "code" ? "{ } code" : "✦ judge"}</span>
                <span className={`chip h-5 text-xxs ${STATUS_CHIP[e.status]}`}>{e.status}</span>
              </div>
              <div className="mt-1 truncate font-medium text-mist-50">{e.name}</div>
              <div className="text-xxs text-mist-500">v{e.latest_version} · {e.failure_mode ?? "no failure mode"}</div>
            </button>
          ))}
        </div>
        {!!wanted.length && (
          <div className="mt-5">
            <div className="label">Still to build</div>
            {wanted.map((m) => (
              <button key={m.id} className="btn-ghost btn-sm mb-1 w-full justify-start" onClick={() => create.mutate({ type: m.decision === "code_check" ? "code" : "judge", failure_mode_id: m.id })}>
                + {m.decision === "code_check" ? "Code check" : "Judge"}: <span className="truncate">{m.name}</span>
              </button>
            ))}
          </div>
        )}
      </aside>
      <div className="min-w-0 overflow-y-auto">
        {sel ? <EvaluatorEditor key={sel} pid={pid} id={sel} /> : (
          <div className="p-6">
            <PageHeader title="Build evaluators" sub="Code checks for anything that is an if/else on the trace; one LLM judge per failure mode that needs judgement." />
            <Empty>Pick an evaluator on the left, or create one from a failure mode marked "Code check" or "LLM judge".</Empty>
          </div>
        )}
      </div>
    </div>
  );
}

function EvaluatorEditor({ pid, id }: { pid: number; id: number }) {
  const q = useQuery({ queryKey: ["evaluator", pid, id], queryFn: () => api.get<EvalDetail>(`/api/projects/${pid}/evaluators/${id}`) });
  const e = q.data;
  if (!e) return <div className="p-6"><Spinner /></div>;
  return (
    <div className="p-6">
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="h1">{e.name}</h1>
            <span className={`chip ${STATUS_CHIP[e.status]}`}>{e.status}</span>
          </div>
          <div className="text-xs text-mist-400">{e.type === "code" ? "Code check" : "LLM judge"} for <b>{e.failure_mode}</b> · latest v{e.latest_version}{e.active_version_id ? ` · runs v${e.versions.find((v) => v.id === e.active_version_id)?.version}` : ""}</div>
        </div>
        <EvalSettings pid={pid} e={e} />
      </div>
      {e.type === "code" ? <CodeCheckEditor pid={pid} e={e} /> : <JudgeEditor pid={pid} e={e} />}
      <div className="mt-8">
        <div className="label">Versions</div>
        <div className="overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <tbody>
              {e.versions.map((v) => (
                <tr key={v.id}>
                  <td className="w-14 font-mono">v{v.version}</td>
                  <td className="text-xs text-mist-400">{new Date(v.created_at).toLocaleString()}</td>
                  <td className="text-xs text-mist-300">{v.note}</td>
                  <td className="text-right text-xs">{v.id === e.active_version_id && <span className="chip border-pass-500/50 text-pass-400">in use</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function EvalSettings({ pid, e }: { pid: number; e: EvalDetail }) {
  const qc = useQueryClient();
  const patch = useMutation({
    mutationFn: (b: Record<string, any>) => api.patch(`/api/projects/${pid}/evaluators/${e.id}`, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["evaluator", pid, e.id] });
      qc.invalidateQueries({ queryKey: ["evaluators", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
    },
  });
  return (
    <div className="flex items-end gap-2">
      <div>
        <label className="label">Owner</label>
        <input className="input h-8 w-32" defaultValue={e.owner} onBlur={(x) => x.target.value !== e.owner && patch.mutate({ owner: x.target.value })} />
      </div>
      <div>
        <label className="label">Where it runs</label>
        <select className="input h-8 w-36 py-0" defaultValue={e.where_to_run} onChange={(x) => patch.mutate({ where_to_run: x.target.value })}>
          <option value="">—</option>
          <option value="ci">CI</option>
          <option value="production">Production monitoring</option>
          <option value="ci+production">CI + production</option>
          <option value="guardrail">Inline guardrail</option>
        </select>
      </div>
      {e.status !== "retired" && <button className="btn-quiet btn-sm" onClick={() => confirm("Retire this evaluator? It stops running but its history is kept.") && patch.mutate({ retire: true })}>Retire</button>}
    </div>
  );
}

// ------------------------------------------------------------------ code checks
type Rule = { type: string; pattern?: string; mode?: string; flags?: string; tool?: string; expect?: string; max?: number | null; min?: number | null; args?: string[]; schema?: any; scope?: { facet: string; values: string[] } };
const RULE_LABEL: Record<string, string> = {
  regex: "Regex in assistant messages",
  markdown: "Markdown syntax present",
  tool_called: "Tool called / not called",
  tool_count_max: "Tool called more than N times",
  tool_args_required: "Required tool arguments",
  length: "Response length limits",
  json_schema: "Valid JSON against a schema",
};
type PreviewRow = { trace_id: number; external_id: string; channel: string; human_failure: boolean; check_failure: boolean; reason: string; outcome: string };

function CodeCheckEditor({ pid, e }: { pid: number; e: EvalDetail }) {
  const qc = useQueryClient();
  const project = useProject(pid);
  const latest = e.versions[0];
  const [defn, setDefn] = useState<any>(latest?.definition ?? { kind: "rules", rules: [] });
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [aiNote, setAiNote] = useState("");
  const [preview, setPreview] = useState<{ metrics: Metrics; rows: PreviewRow[]; can_activate: boolean; version: number } | null>(null);
  const [filter, setFilter] = useState("problems");
  const [open, setOpen] = useState<number | null>(null);
  const facets = useQuery({ queryKey: ["facets", pid], queryFn: () => api.get<Facet[]>(`/api/projects/${pid}/facets`) });
  const dirty = JSON.stringify(defn) !== JSON.stringify(latest?.definition);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["evaluator", pid, e.id] });
    qc.invalidateQueries({ queryKey: ["evaluators", pid] });
    qc.invalidateQueries({ queryKey: ["status", pid] });
  };
  const save = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/evaluators/${e.id}/versions`, { definition: defn, note: note || "edited" }),
    onSuccess: () => {
      setNote("");
      setErr("");
      setPreview(null);
      refresh();
    },
    onError: (x: any) => setErr(x.message),
  });
  const run = useMutation({ mutationFn: () => api.post<any>(`/api/projects/${pid}/evaluators/${e.id}/preview`), onSuccess: (r) => { setPreview(r); refresh(); }, onError: (x: any) => setErr(x.message) });
  const activate = useMutation({ mutationFn: () => api.post(`/api/projects/${pid}/evaluators/${e.id}/activate`), onSuccess: refresh, onError: (x: any) => setErr(x.message) });
  const draft = useMutation({
    mutationFn: () => api.post<any>(`/api/projects/${pid}/evaluators/draft_check`, { failure_mode_id: e.failure_mode_id }),
    onSuccess: (r) => {
      if (r.definition.rules.length) setDefn(r.definition);
      setAiNote(r.explanation);
      setNote("AI draft, reviewed");
    },
    onError: (x: any) => setErr(x.message),
  });
  const rules: Rule[] = defn.rules ?? [];
  const setRule = (i: number, r: Rule) => setDefn({ ...defn, rules: rules.map((x, j) => (j === i ? r : x)) });
  const catFacets = (facets.data ?? []).filter((f) => f.kind === "category");
  const rows = (preview?.rows ?? []).filter((r) => filter === "all" || (filter === "problems" ? r.outcome === "missed failure" || r.outcome === "false alarm" : r.outcome === filter));

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <div className="flex rounded-md border border-ink-600 p-0.5">
          {(["rules", "python"] as const).map((k) => (
            <button key={k} onClick={() => setDefn(k === "rules" ? { kind: "rules", rules: rules.length ? rules : [] } : { kind: "python", code: defn.code ?? PY_TEMPLATE })} className={`rounded px-3 py-1 text-xs ${defn.kind === k ? "bg-ink-800 font-medium text-mist-50" : "text-mist-400"}`}>
              {k === "rules" ? "Rule builder" : "Custom Python"}
            </button>
          ))}
        </div>
        <button className="btn-ghost btn-sm" onClick={() => draft.mutate()} disabled={draft.isPending}>{draft.isPending ? "Drafting…" : "✦ Draft with AI"}</button>
        <span className="text-xs text-mist-400">Every rule describes a <b>failure</b>; a trace fails the check if any rule fires.</span>
      </div>
      {aiNote && <Notice>✦ {aiNote} <span className="text-mist-500">— review it, then save as a new version to approve.</span></Notice>}

      {defn.kind === "python" ? (
        <div>
          <label className="label">check(trace) → True when the trace PASSES. Runs in a sandboxed subprocess with a timeout.</label>
          <textarea className="input min-h-[240px] font-mono text-[12.5px]" value={defn.code} onChange={(x) => setDefn({ ...defn, code: x.target.value })} spellCheck={false} />
          <p className="mt-1 text-xs text-mist-400">trace = {"{"}id, channel, meta, system_prompt, events: [{"{"}role, content, tool_name, tool_args, tool_result{"}"}]{"}"}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {rules.map((r, i) => (
            <div key={i} className="card space-y-2 p-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-mist-500">Fail if</span>
                <select className="input h-8 w-64 py-0" value={r.type} onChange={(x) => setRule(i, { type: x.target.value, scope: r.scope })}>
                  {Object.entries(RULE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                <RuleFields r={r} set={(nr) => setRule(i, nr)} />
                <button className="btn-quiet btn-sm ml-auto" onClick={() => setDefn({ ...defn, rules: rules.filter((_, j) => j !== i) })}>✕</button>
              </div>
              <div className="flex items-center gap-2 text-xs text-mist-400">
                <span>Only for</span>
                <select className="input h-7 w-40 py-0 text-xs" value={r.scope?.facet ?? ""} onChange={(x) => setRule(i, { ...r, scope: x.target.value ? { facet: x.target.value, values: [] } : undefined })}>
                  <option value="">all traces</option>
                  {catFacets.map((f) => <option key={f.key} value={f.key}>{f.key}</option>)}
                </select>
                {r.scope?.facet && (
                  <div className="flex flex-wrap gap-1">
                    {(catFacets.find((f) => f.key === r.scope!.facet) as any)?.values.map((v: any) => {
                      const on = r.scope!.values.includes(v.value);
                      return <button key={v.value} onClick={() => setRule(i, { ...r, scope: { facet: r.scope!.facet, values: on ? r.scope!.values.filter((x) => x !== v.value) : [...r.scope!.values, v.value] } })} className={`chip h-6 ${on ? "border-accent-400 text-accent-400" : ""}`}>{v.value}</button>;
                    })}
                  </div>
                )}
              </div>
            </div>
          ))}
          <button className="btn-ghost btn-sm" onClick={() => setDefn({ ...defn, kind: "rules", rules: [...rules, { type: "markdown" }] })}>+ Add rule</button>
        </div>
      )}

      {err && <Notice tone="danger">{err}</Notice>}
      <div className="flex items-center gap-2">
        <input className="input h-8 w-72" placeholder="Version note" value={note} onChange={(x) => setNote(x.target.value)} />
        <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save as v{(e.latest_version ?? 0) + 1}</button>
        <button className="btn-ghost" disabled={dirty || run.isPending} onClick={() => run.mutate()} title={dirty ? "Save first" : ""}>{run.isPending ? "Running…" : `Run v${e.latest_version} on reviewed traces`}</button>
        <button
          className="btn-ghost"
          disabled={!preview?.can_activate || dirty || e.status === "active"}
          onClick={() => activate.mutate()}
          title="Activation requires seeing at least one correct fail and one correct pass"
        >
          {e.status === "active" ? "✓ Active" : "Activate"}
        </button>
      </div>
      {!preview && e.status !== "active" && <p className="text-xs text-mist-400">A check can be activated only after you have seen it produce at least one correct pass and one correct fail against your own labels.</p>}

      {preview && (
        <div className="space-y-3">
          <MetricsPanel m={preview.metrics} title={`v${preview.version} vs your labels`} />
          {!preview.can_activate && <Notice tone="warn">Not yet: the check needs at least one correct fail and one correct pass on your reviewed traces.</Notice>}
          <div className="flex gap-4 border-b border-ink-700">
            {[["problems", "Disagreements"], ["correct fail", "Correct fails"], ["correct pass", "Correct passes"], ["all", "All"]].map(([k, l]) => (
              <button key={k} className={`tab ${filter === k ? "tab-active" : ""}`} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
          <div className="max-h-[420px] overflow-y-auto rounded-lg border border-ink-700">
            <table className="tbl">
              <thead><tr><th>Trace</th><th>You</th><th>Check</th><th>Why</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.trace_id} className="cursor-pointer" onClick={() => setOpen(r.trace_id)}>
                    <td className="font-mono text-xs text-accent-400">{r.external_id}<div className="text-xxs text-mist-500">{r.channel}</div></td>
                    <td className="text-xs">{r.human_failure ? "✕ failure" : "✓ no failure"}</td>
                    <td className="text-xs">{r.check_failure ? "✕ failure" : "✓ pass"} {r.outcome !== "correct fail" && r.outcome !== "correct pass" && <span className="chip ml-1 h-5 border-warn-400/40 text-warn-400">{r.outcome}</span>}</td>
                    <td className="text-xs text-mist-400">{r.reason}</td>
                  </tr>
                ))}
                {!rows.length && <tr><td colSpan={4} className="text-mist-400">None.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {open && <TracePreview pid={pid} traceId={open} product={project.data?.name} onClose={() => setOpen(null)} />}
    </div>
  );
}

const PY_TEMPLATE = `def check(trace):
    """Return True when the trace PASSES, False when the failure is present."""
    names = [e.get("tool_name") for e in trace["events"] if e["role"] == "tool_call"]
    # Example: an existing booking was looked up, then a new one was created instead of rescheduling.
    if "lookup_tours" in names and "schedule_tour" in names and "reschedule_tour" not in names:
        return False
    return True
`;

function RuleFields({ r, set }: { r: Rule; set: (r: Rule) => void }) {
  if (r.type === "regex")
    return (
      <>
        <input className="input h-8 font-mono text-xs" placeholder="pattern" value={r.pattern ?? ""} onChange={(x) => set({ ...r, pattern: x.target.value })} />
        <select className="input h-8 w-28 py-0" value={r.mode ?? "present"} onChange={(x) => set({ ...r, mode: x.target.value })}><option value="present">is present</option><option value="absent">is absent</option></select>
        <label className="flex items-center gap-1 text-xs text-mist-400"><input type="checkbox" checked={(r.flags ?? "").includes("i")} onChange={(x) => set({ ...r, flags: x.target.checked ? "i" : "" })} /> ignore case</label>
      </>
    );
  if (r.type === "tool_called")
    return (
      <>
        <input className="input h-8 w-48 font-mono text-xs" placeholder="tool name" value={r.tool ?? ""} onChange={(x) => set({ ...r, tool: x.target.value })} />
        <select className="input h-8 w-40 py-0" value={r.expect ?? "called"} onChange={(x) => set({ ...r, expect: x.target.value })}><option value="called">is never called</option><option value="not_called">is called</option></select>
      </>
    );
  if (r.type === "tool_count_max")
    return (
      <>
        <input className="input h-8 w-48 font-mono text-xs" placeholder="tool name" value={r.tool ?? ""} onChange={(x) => set({ ...r, tool: x.target.value })} />
        <span className="text-xs text-mist-400">more than</span>
        <input className="input h-8 w-20" type="number" value={r.max ?? 1} onChange={(x) => set({ ...r, max: Number(x.target.value) })} />
      </>
    );
  if (r.type === "tool_args_required")
    return (
      <>
        <input className="input h-8 w-48 font-mono text-xs" placeholder="tool name" value={r.tool ?? ""} onChange={(x) => set({ ...r, tool: x.target.value })} />
        <input className="input h-8 font-mono text-xs" placeholder="args, comma separated" value={(r.args ?? []).join(", ")} onChange={(x) => set({ ...r, args: x.target.value.split(",").map((a) => a.trim()).filter(Boolean) })} />
      </>
    );
  if (r.type === "length")
    return (
      <>
        <span className="text-xs text-mist-400">min</span>
        <input className="input h-8 w-20" type="number" value={r.min ?? ""} onChange={(x) => set({ ...r, min: x.target.value ? Number(x.target.value) : null })} />
        <span className="text-xs text-mist-400">max chars</span>
        <input className="input h-8 w-24" type="number" value={r.max ?? ""} onChange={(x) => set({ ...r, max: x.target.value ? Number(x.target.value) : null })} />
      </>
    );
  if (r.type === "json_schema")
    return <JsonField value={r.schema ?? { type: "object" }} onChange={(schema) => set({ ...r, schema })} />;
  return <span className="text-xs text-mist-400">bold, italics, headings, bullet or numbered lists, links, inline code, quotes</span>;
}

function JsonField({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const [txt, setTxt] = useState(JSON.stringify(value));
  const [bad, setBad] = useState(false);
  return (
    <input
      className={`input h-8 font-mono text-xs ${bad ? "border-fail-500" : ""}`}
      value={txt}
      onChange={(x) => {
        setTxt(x.target.value);
        try {
          onChange(JSON.parse(x.target.value));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}

// ------------------------------------------------------------------ judges
const CONTEXT: [string, string][] = [
  ["last_assistant", "Last assistant turn (+ the user turn before it)"],
  ["conversation", "Full conversation"],
  ["tool_calls", "Tool calls and results"],
  ["system_prompt", "System prompt"],
  ["business_facts", "Business facts"],
];
type GTRow = { id: number; trace_id: number; external_id: string; label: boolean; critique: string; split: string };

function JudgeEditor({ pid, e }: { pid: number; e: EvalDetail }) {
  const qc = useQueryClient();
  const latest = e.versions[0];
  const [fw, setFw] = useState<string>((latest?.definition?.failure_when ?? []).join("\n"));
  const [nf, setNf] = useState<string>((latest?.definition?.not_failure_when ?? []).join("\n"));
  const [scope, setScope] = useState<string[]>(latest?.context_scope ?? ["last_assistant"]);
  const [shots, setShots] = useState<number[]>(latest?.few_shot_ids ?? []);
  const [model, setModel] = useState(latest?.model ?? "");
  const [note, setNote] = useState("");
  const [err, setErr] = useState("");
  const [prompt, setPrompt] = useState<string | null>(null);
  const gt = useQuery({ queryKey: ["gt", pid, e.failure_mode_id], queryFn: () => api.get<{ rows: GTRow[] }>(`/api/projects/${pid}/ground_truth/${e.failure_mode_id}`) });
  const train = (gt.data?.rows ?? []).filter((g) => g.split === "train");
  const definition = { failure_when: fw.split("\n").map((x) => x.trim()).filter(Boolean), not_failure_when: nf.split("\n").map((x) => x.trim()).filter(Boolean) };
  const dirty =
    JSON.stringify(definition) !== JSON.stringify({ failure_when: latest?.definition?.failure_when ?? [], not_failure_when: latest?.definition?.not_failure_when ?? [] }) ||
    JSON.stringify(scope) !== JSON.stringify(latest?.context_scope) ||
    JSON.stringify(shots) !== JSON.stringify(latest?.few_shot_ids ?? []) ||
    model !== (latest?.model ?? "");
  const save = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/evaluators/${e.id}/versions`, { definition, context_scope: scope, few_shot_ids: shots, model, note: note || "edited" }),
    onSuccess: () => {
      setNote("");
      setErr("");
      qc.invalidateQueries({ queryKey: ["evaluator", pid, e.id] });
      qc.invalidateQueries({ queryKey: ["evaluators", pid] });
    },
    onError: (x: any) => setErr(x.message),
  });
  const draft = useMutation({
    mutationFn: () => api.post<any>(`/api/projects/${pid}/evaluators/draft_judge`, { failure_mode_id: e.failure_mode_id }),
    onSuccess: (r) => {
      setFw(r.definition.failure_when.join("\n"));
      setNf(r.definition.not_failure_when.join("\n"));
      setNote("AI draft, edited");
    },
    onError: (x: any) => setErr(x.message),
  });
  const view = useMutation({
    mutationFn: () => api.post<{ prompt: string; sample_trace: string }>(`/api/projects/${pid}/evaluators/${e.id}/judge_prompt`, { definition, context_scope: scope, few_shot_ids: shots }),
    onSuccess: (r) => setPrompt(`# Sample trace: ${r.sample_trace}\n\n${r.prompt}`),
  });
  return (
    <div className="space-y-5">
      <Notice>
        A judge prompt copied from someone else's product will not work for yours. The value comes from iterating against <b>your own labels</b> in <Link className="underline" to={`/p/${pid}/validate?e=${e.id}`}>Validate judges</Link>.
      </Notice>
      <div className="flex items-center gap-2">
        <button className="btn-ghost btn-sm" onClick={() => draft.mutate()} disabled={draft.isPending}>{draft.isPending ? "Drafting…" : "✦ Draft with AI"}</button>
        <span className="text-xs text-mist-400">Uses the failure-mode definition, your notes and business facts. You edit before anything runs.</span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">1 · The failure occurs when… (one condition per line)</label>
          <textarea className="input min-h-[170px] text-[13px]" value={fw} onChange={(x) => setFw(x.target.value)} />
        </div>
        <div>
          <label className="label">2 · It is NOT a failure when… (prevents false alarms)</label>
          <textarea className="input min-h-[170px] text-[13px]" value={nf} onChange={(x) => setNf(x.target.value)} />
        </div>
      </div>
      <div className="panel p-3 text-xs text-mist-300">
        <b>3 · Output:</b> a short critique first, then the verdict — structured as <code className="font-mono">{"{critique: string, failure: boolean}"}</code>.
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="label">What the judge sees</label>
          <div className="space-y-1">
            {CONTEXT.map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={scope.includes(k)} onChange={(x) => setScope(x.target.checked ? [...scope, k] : scope.filter((y) => y !== k))} /> {l}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-mist-400">Default to the minimum needed. Extra context makes judges worse.</p>
          <label className="label mt-3">Model</label>
          <input className="input h-8 w-60 font-mono text-xs" value={model} onChange={(x) => setModel(x.target.value)} />
        </div>
        <div>
          <label className="label"><Term tip="Few-shot examples, each with your critique. Only the train split may appear in the prompt, so dev and test stay honest.">Few-shot examples (train split only)</Term></label>
          {!train.length ? (
            <p className="text-xs text-mist-400">No train-split labels yet. Label traces in Validate judges first.</p>
          ) : (
            <div className="max-h-48 space-y-1 overflow-y-auto">
              {train.map((g) => (
                <label key={g.id} className="flex items-start gap-2 text-xs">
                  <input type="checkbox" className="mt-0.5" checked={shots.includes(g.id)} onChange={(x) => setShots(x.target.checked ? [...shots, g.id] : shots.filter((y) => y !== g.id))} />
                  <span><span className="font-mono text-mist-400">{g.external_id}</span> {g.label ? <span className="text-fail-400">failure</span> : <span className="text-pass-400">no failure</span>} — <span className="text-mist-300">{g.critique}</span></span>
                </label>
              ))}
            </div>
          )}
        </div>
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      <div className="flex items-center gap-2">
        <input className="input h-8 w-72" placeholder="Version note" value={note} onChange={(x) => setNote(x.target.value)} />
        <button className="btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>Save as v{(e.latest_version ?? 0) + 1}</button>
        <button className="btn-ghost" onClick={() => view.mutate()}>View exact prompt</button>
        <Link className="btn-ghost" to={`/p/${pid}/validate?e=${e.id}`}>Validate →</Link>
      </div>
      {prompt && (
        <div>
          <div className="label">Exactly what the judge receives (the prompt template is editable in Settings)</div>
          <pre className="max-h-[480px] overflow-auto whitespace-pre-wrap rounded-md border border-ink-700 bg-ink-900 p-3 font-mono text-[12px] text-mist-200">{prompt}</pre>
        </div>
      )}
    </div>
  );
}
