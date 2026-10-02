import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type BatchSummary } from "../api";
import { Empty, Notice, PageHeader, Term, pct, usePid, useStatus } from "../components/ui";
import { SEVERITY } from "./Count";

type Board = {
  modes: {
    id: number;
    name: string;
    definition: string;
    severity: string;
    impact_note: string;
    decision: string;
    decision_note: string;
    count: number;
    share_reviewed: number | null;
    evaluators: { id: number; type: string; name: string; status: string }[];
  }[];
  n_reviewed: number;
  suite: { code: number; judge: number; planned: Record<string, number> };
  warnings: string[];
};
type Rate = { k: number; n: number; rate: number | null; ci: [number | null, number | null] };
type FixRow = { id: number; failure_mode: string; description: string; prompt_version: string | null; created_at: string; before: Rate; after: Rate; awaiting: boolean };

const OPTIONS: { key: string; title: string; when: string; cost?: string }[] = [
  { key: "fix_now", title: "Fix now", when: "Is there an obvious cause, such as a missing instruction or a missing tool? Fix it — no evaluator needed." },
  { key: "code_check", title: "Code check", when: "Can the check be written as an if/else on the trace? Cheapest and most reliable." },
  { key: "llm_judge", title: "LLM judge", when: "Does it need judgement about context, policy or tone, and will you iterate on it repeatedly?", cost: "Costs ~100+ human labels and ongoing maintenance." },
  { key: "park", title: "Park", when: "Is it rare and low severity? Note it and move on." },
];

export function Decide() {
  const pid = usePid();
  const qc = useQueryClient();
  const status = useStatus(pid);
  const board = useQuery({ queryKey: ["decide", pid], queryFn: () => api.get<Board>(`/api/projects/${pid}/decide`) });
  const refresh = () => ["decide", "status", "modes", "fixes"].forEach((k) => qc.invalidateQueries({ queryKey: [k, pid] }));
  const patch = useMutation({ mutationFn: ({ id, body }: { id: number; body: Record<string, string> }) => api.patch(`/api/projects/${pid}/failure_modes/${id}`, body), onSuccess: refresh });
  const stage = status.data?.stages.find((s) => s.key === "decide");
  if (stage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader title="Decide what each failure needs" />
        <Notice>{stage.unlock}</Notice>
      </div>
    );
  const b = board.data;
  return (
    <div className="mx-auto max-w-[1200px] px-6 py-6">
      <PageHeader
        title="Decide what each failure needs"
        sub="Not every failure needs an evaluator — many are fixed by a one-line prompt change. Build evaluators only for failures you expect to iterate against, and use the cheapest one that works."
        right={b && <span className="chip">Suite: {b.suite.code} code check{b.suite.code === 1 ? "" : "s"} · {b.suite.judge} judge{b.suite.judge === 1 ? "" : "s"}</span>}
      />
      <div className="mb-4 text-xs text-mist-400">A healthy end state is typically <b>2–3 code checks and 1–2 LLM judges</b>.</div>
      {b?.warnings.map((w) => <div key={w} className="mb-3"><Notice tone="warn">{w}</Notice></div>)}
      {b && !b.modes.length && <Empty>No failure modes yet.</Empty>}
      <div className="space-y-3">
        {b?.modes.map((m) => (
          <div key={m.id} className="card p-4" data-testid="decision-card">
            <div className="flex items-start gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <div className="h2">{m.name}</div>
                  {m.severity && <span className={`text-xs ${SEVERITY[m.severity].cls}`}>{SEVERITY[m.severity].icon} {SEVERITY[m.severity].label}</span>}
                </div>
                <div className="text-xs text-mist-400">{m.count} traces · {pct(m.share_reviewed, 1)} of {b.n_reviewed} reviewed{m.impact_note ? ` · ${m.impact_note}` : ""}</div>
                {m.definition && <div className="mt-1 text-[13px] text-mist-300">{m.definition}</div>}
              </div>
              {m.evaluators.length > 0 && (
                <div className="text-right text-xs">
                  {m.evaluators.map((e) => <div key={e.id}><Link className="text-accent-400 hover:underline" to={`/p/${pid}/build?e=${e.id}`}>{e.name}</Link> <span className="text-mist-500">({e.status})</span></div>)}
                </div>
              )}
            </div>
            <div className="mt-3 grid grid-cols-4 gap-2" role="radiogroup" aria-label={`Decision for ${m.name}`}>
              {OPTIONS.map((o) => {
                const on = m.decision === o.key;
                return (
                  <button
                    key={o.key}
                    role="radio"
                    aria-checked={on}
                    onClick={() => patch.mutate({ id: m.id, body: { decision: on ? "" : o.key } })}
                    className={`rounded-md border p-2.5 text-left transition ${on ? "border-accent-400 bg-accent-400/5 ring-1 ring-accent-400" : "border-ink-700 hover:border-ink-500"}`}
                  >
                    <div className="flex items-center gap-1.5 font-medium text-mist-50">
                      <span className={`grid h-4 w-4 place-items-center rounded-full border ${on ? "border-accent-400 bg-accent-400 text-[9px] text-white" : "border-ink-500"}`}>{on ? "✓" : ""}</span>
                      {o.title}
                    </div>
                    <div className="mt-1 text-xs text-mist-400">{o.when}</div>
                    {o.cost && <div className="mt-1 text-xs font-medium text-warn-400">{o.cost}</div>}
                  </button>
                );
              })}
            </div>
            <input
              className="input mt-2 h-8 text-xs"
              placeholder={m.decision === "fix_now" ? "What will you change? (log it below once done)" : "Why this decision? (optional)"}
              defaultValue={m.decision_note}
              onBlur={(e) => e.target.value !== m.decision_note && patch.mutate({ id: m.id, body: { decision_note: e.target.value } })}
            />
            {(m.decision === "code_check" || m.decision === "llm_judge") && !m.evaluators.some((e) => e.type === (m.decision === "code_check" ? "code" : "judge")) && (
              <Link to={`/p/${pid}/build?new=${m.decision === "code_check" ? "code" : "judge"}&fm=${m.id}`} className="btn-ghost btn-sm mt-2">
                Build the {m.decision === "code_check" ? "code check" : "judge"} →
              </Link>
            )}
          </div>
        ))}
      </div>
      {b && <FixLog pid={pid} modes={b.modes.filter((m) => m.decision === "fix_now")} />}
    </div>
  );
}

function FixLog({ pid, modes }: { pid: number; modes: { id: number; name: string }[] }) {
  const qc = useQueryClient();
  const fixes = useQuery({ queryKey: ["fixes", pid], queryFn: () => api.get<FixRow[]>(`/api/projects/${pid}/fixes`) });
  const pvs = useQuery({ queryKey: ["pvs", pid], queryFn: () => api.get<{ id: number; label: string }[]>(`/api/projects/${pid}/prompt_versions`) });
  const batches = useQuery({ queryKey: ["batches", pid], queryFn: () => api.get<BatchSummary[]>(`/api/projects/${pid}/batches`) });
  const [f, setF] = useState({ failure_mode_id: "", description: "", prompt_version_id: "", before_batch_id: "" });
  const add = useMutation({
    mutationFn: () =>
      api.post(`/api/projects/${pid}/fixes`, {
        failure_mode_id: Number(f.failure_mode_id),
        description: f.description,
        prompt_version_id: f.prompt_version_id ? Number(f.prompt_version_id) : null,
        before_batch_id: f.before_batch_id ? Number(f.before_batch_id) : null,
      }),
    onSuccess: () => {
      setF({ failure_mode_id: "", description: "", prompt_version_id: "", before_batch_id: "" });
      qc.invalidateQueries({ queryKey: ["fixes", pid] });
    },
  });
  const R = (r: Rate) => (r.n ? <span className="tabular-nums">{pct(r.rate, 1)} <span className="text-mist-500">({r.k}/{r.n})</span></span> : <span className="text-mist-500">—</span>);
  return (
    <div className="mt-10">
      <div className="h2">Fix log</div>
      <p className="mb-3 mt-0.5 text-xs text-mist-400">
        Record what you changed for each "Fix now" failure. After the next batch is reviewed, the before and after rates appear here. New prompt versions are added in <Link className="underline" to={`/p/${pid}/setup`}>Set up the project</Link>.
      </p>
      <div className="card grid grid-cols-[200px_1fr_140px_180px_auto] items-end gap-2 p-3">
        <div>
          <label className="label">Failure mode</label>
          <select className="input" value={f.failure_mode_id} onChange={(e) => setF({ ...f, failure_mode_id: e.target.value })}>
            <option value="">Choose…</option>
            {modes.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">What changed</label>
          <input className="input" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} placeholder="e.g. Inject today's date into the system prompt" />
        </div>
        <div>
          <label className="label">Prompt version</label>
          <select className="input" value={f.prompt_version_id} onChange={(e) => setF({ ...f, prompt_version_id: e.target.value })}>
            <option value="">—</option>
            {pvs.data?.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label"><Term tip="The rate before the fix is measured on this batch. Leave empty to use all batches created before the fix.">Before = batch</Term></label>
          <select className="input" value={f.before_batch_id} onChange={(e) => setF({ ...f, before_batch_id: e.target.value })}>
            <option value="">All earlier batches</option>
            {batches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <button className="btn-primary" disabled={!f.failure_mode_id || !f.description.trim()} onClick={() => add.mutate()}>Log fix</button>
      </div>
      {!!fixes.data?.length && (
        <div className="mt-3 overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <thead><tr><th>Failure mode</th><th>Change</th><th>Prompt</th><th>Logged</th><th className="text-right">Before</th><th className="text-right">After</th></tr></thead>
            <tbody>
              {fixes.data.map((x) => (
                <tr key={x.id}>
                  <td className="font-medium text-mist-50">{x.failure_mode}</td>
                  <td className="text-mist-300">{x.description}</td>
                  <td>{x.prompt_version ? <span className="chip">{x.prompt_version}</span> : "—"}</td>
                  <td className="text-xs text-mist-400">{new Date(x.created_at).toLocaleDateString()}</td>
                  <td className="text-right">{R(x.before)}</td>
                  <td className="text-right">{x.awaiting ? <span className="text-xs text-mist-500">awaiting next reviewed batch</span> : R(x.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
