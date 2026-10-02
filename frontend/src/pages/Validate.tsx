import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type TraceView } from "../api";
import { LowConfidence, MetricsPanel, type Metrics } from "../components/metrics";
import { TracePreview } from "../components/TracePreview";
import { TraceRenderer } from "../components/TraceRenderer";
import { Empty, Notice, PageHeader, Spinner, pct, usePid, useProject, useStatus } from "../components/ui";
import { STATUS_CHIP, useEvaluators, type EvalDetail } from "./Build";

type GT = { rows: { id: number; trace_id: number; external_id: string; label: boolean; critique: string; split: string }[]; counts: Record<string, { pos: number; neg: number }>; total: number; low_confidence: boolean };
type RunRow = { trace_id: number; external_id: string; channel: string; human_label: boolean; human_critique: string; judge_failure: boolean | null; judge_critique: string; error: string; split: string; outcome: string; gt_id: number };
type Run = { id: number; kind: string; status: string; progress: number; total: number; metrics: Metrics; error: string; cost_estimate: number; cost_actual: number; rows?: RunRow[] };

function useRun(pid: number, rid: number | null) {
  return useQuery({
    queryKey: ["run", pid, rid],
    queryFn: () => api.get<Run>(`/api/projects/${pid}/runs/${rid}`),
    enabled: !!rid,
    refetchIntervalInBackground: true,
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 800 : false),
  });
}

export function Validate() {
  const pid = usePid();
  const status = useStatus(pid);
  const [params, setParams] = useSearchParams();
  const evs = useEvaluators(pid);
  const judges = (evs.data ?? []).filter((e) => e.type === "judge" && e.status !== "retired");
  const sel = Number(params.get("e")) || judges[0]?.id;
  const stage = status.data?.stages.find((s) => s.key === "validate");
  if (stage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader title="Validate judges" />
        <Notice>{stage.unlock} <Link className="underline" to={`/p/${pid}/build`}>Go to Build →</Link></Notice>
      </div>
    );
  return (
    <div className="mx-auto max-w-[1300px] px-6 py-6">
      <PageHeader
        title="Validate judges"
        sub="A judge is untrusted until it agrees with your labels. Measure true positive rate and true negative rate separately — raw agreement is a trap."
        right={
          <select className="input h-8 w-72 py-0" value={sel ?? ""} onChange={(e) => setParams({ e: e.target.value })}>
            {judges.map((j) => <option key={j.id} value={j.id}>{j.name} ({j.status})</option>)}
          </select>
        }
      />
      {!judges.length ? <Empty>No judges yet.</Empty> : sel ? <JudgeValidation key={sel} pid={pid} eid={sel} /> : null}
    </div>
  );
}

function JudgeValidation({ pid, eid }: { pid: number; eid: number }) {
  const qc = useQueryClient();
  const project = useProject(pid);
  const evq = useQuery({ queryKey: ["evaluator", pid, eid], queryFn: () => api.get<EvalDetail>(`/api/projects/${pid}/evaluators/${eid}`) });
  const e = evq.data;
  const fm = e?.failure_mode_id;
  const gt = useQuery({ queryKey: ["gt", pid, fm], queryFn: () => api.get<GT>(`/api/projects/${pid}/ground_truth/${fm}`), enabled: !!fm });
  const [labelling, setLabelling] = useState(false);
  const [devRun, setDevRun] = useState<number | null>(null);
  const [finalRun, setFinalRun] = useState<number | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (e?.last_dev && devRun === null) setDevRun(e.last_dev.id);
    if (e?.last_final && finalRun === null) setFinalRun(e.last_final.id);
  }, [e, devRun, finalRun]);
  const dev = useRun(pid, devRun);
  const fin = useRun(pid, finalRun);
  const refresh = () => {
    ["evaluator", "evaluators", "gt", "status"].forEach((k) => qc.invalidateQueries({ queryKey: [k, pid] }));
  };
  useEffect(() => {
    if (dev.data?.status === "done" || fin.data?.status === "done") refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dev.data?.status, fin.data?.status]);
  const seed = useMutation({ mutationFn: () => api.post(`/api/projects/${pid}/ground_truth/${fm}/seed`), onSuccess: refresh });
  const run = useMutation({
    mutationFn: (split: string) => api.post<{ run_id: number }>(`/api/projects/${pid}/evaluators/${eid}/run`, { split }),
    onSuccess: (r, split) => (split === "dev" ? setDevRun(r.run_id) : setFinalRun(r.run_id)),
    onError: (x: any) => setErr(x.message),
  });
  const patch = useMutation({ mutationFn: (b: Record<string, any>) => api.patch(`/api/projects/${pid}/evaluators/${eid}`, b), onSuccess: refresh });
  if (!e || !gt.data) return <Spinner />;
  const c = gt.data.counts;
  const finals = e.runs.filter((r) => r.kind === "final").length;
  const devFresh = dev.data && dev.data.status === "done" && e.last_dev?.version_id === e.latest_version_id;

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-2 text-xs">
        <span className={`chip ${STATUS_CHIP[e.status]}`}>{e.status}</span>
        <span className="text-mist-400">Failure mode: <b className="text-mist-200">{e.failure_mode}</b> · editing v{e.latest_version} in <Link className="underline" to={`/p/${pid}/build?e=${eid}`}>Build</Link></span>
      </div>

      {/* ---------------------------------------------------------------- labels */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <div className="h2">1 · Your labels (ground truth)</div>
          <div className="flex gap-2">
            <button className="btn-ghost btn-sm" onClick={() => seed.mutate()} disabled={seed.isPending}>Seed from error analysis</button>
            <button className="btn-primary btn-sm" onClick={() => setLabelling(true)}>Open labelling queue</button>
          </div>
        </div>
        <p className="mb-3 text-xs text-mist-400">
          Is the failure present or absent? Target 100–200 labelled traces. Each trace is assigned to a split the first time you label it and never moves: train 10–20% (may appear in the prompt), dev 40–45% (iterate here), test 40–45% (held out).
        </p>
        <div className="grid grid-cols-4 gap-3">
          <div className="panel p-3"><div className="label">Total labelled</div><div className="text-xl font-semibold tabular-nums">{gt.data.total}</div><div className="text-xs text-mist-400">target 100–200</div></div>
          {(["train", "dev", "test"] as const).map((sp) => (
            <div key={sp} className="panel p-3">
              <div className="label flex items-center justify-between">{sp}{sp === "test" && <span className="normal-case">🔒 locked</span>}</div>
              <div className="text-xl font-semibold tabular-nums">{c[sp].pos + c[sp].neg}</div>
              <div className="text-xs text-mist-400"><span className="text-fail-400">{c[sp].pos} with failure</span> · <span className="text-pass-400">{c[sp].neg} without</span></div>
              {sp !== "train" && (c[sp].pos < 30 || c[sp].neg < 30) && <div className="mt-1"><LowConfidence /></div>}
            </div>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------------- dev loop */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <div className="h2">2 · Iterate on the dev split</div>
          <button className="btn-primary btn-sm" disabled={run.isPending || dev.data?.status === "running"} onClick={() => { setErr(""); run.mutate("dev"); }}>
            Run v{e.latest_version} on dev ({c.dev.pos + c.dev.neg})
          </button>
        </div>
        {err && <div className="mb-2"><Notice tone="danger">{err}</Notice></div>}
        {dev.data && ["queued", "running"].includes(dev.data.status) && <Progress r={dev.data} />}
        {dev.data?.status === "failed" && <Notice tone="danger">Run failed: {dev.data.error.split("\n")[0]}</Notice>}
        {dev.data?.status === "done" && (
          <>
            {!devFresh && <div className="mb-2"><Notice tone="warn">These results are for an older version. Run the latest version on dev.</Notice></div>}
            <MetricsPanel m={dev.data.metrics} title="dev" />
            <Disagreements pid={pid} e={e} rows={dev.data.rows ?? []} product={project.data?.name} onChanged={refresh} />
          </>
        )}
      </section>

      {/* ---------------------------------------------------------------- versions */}
      {!!e.version_table.length && (
        <section>
          <div className="h2 mb-2">Versions</div>
          <div className="overflow-hidden rounded-lg border border-ink-700">
            <table className="tbl">
              <thead><tr><th>Version</th><th className="text-right">Dev TPR</th><th className="text-right">Dev TNR</th><th className="text-right">Test TPR</th><th className="text-right">Test TNR</th><th className="text-right">Final runs</th></tr></thead>
              <tbody>
                {e.version_table.map((r) => (
                  <tr key={r.version}>
                    <td className="font-mono">v{r.version}</td>
                    <td className="text-right tabular-nums">{r.dev ? `${pct(r.dev.tpr)} (n=${r.dev.n_pos})` : "—"}</td>
                    <td className="text-right tabular-nums">{r.dev ? `${pct(r.dev.tnr)} (n=${r.dev.n_neg})` : "—"}</td>
                    <td className="text-right tabular-nums">{r.test ? pct(r.test.tpr) : "—"}</td>
                    <td className="text-right tabular-nums">{r.test ? pct(r.test.tnr) : "—"}</td>
                    <td className="text-right tabular-nums">{r.n_final_runs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ---------------------------------------------------------------- final */}
      <section>
        <div className="mb-2 flex items-center justify-between">
          <div className="h2">3 · Final validation on the locked test split</div>
          <div className="flex items-end gap-2">
            <div>
              <label className="label">Threshold (TPR and TNR)</label>
              <input className="input h-8 w-20" type="number" step="0.05" min="0.5" max="1" defaultValue={e.threshold} onBlur={(x) => Number(x.target.value) !== e.threshold && patch.mutate({ threshold: Number(x.target.value) })} />
            </div>
            <div>
              <label className="label">Target</label>
              <input className="input h-8 w-20" type="number" step="0.05" min="0.5" max="1" defaultValue={e.target} onBlur={(x) => Number(x.target.value) !== e.target && patch.mutate({ target: Number(x.target.value) })} />
            </div>
            <button
              className="btn-primary"
              disabled={run.isPending || fin.data?.status === "running"}
              onClick={() => {
                if (finals >= 2 && !confirm(`The test split has been run ${finals} times. Re-running it to tune the prompt turns it into a dev set and overstates accuracy. Run anyway?`)) return;
                setErr("");
                run.mutate("test");
              }}
            >
              Run final validation ({c.test.pos + c.test.neg})
            </button>
          </div>
        </div>
        <p className="mb-3 text-xs text-mist-400">Status moves from Draft to Validated only when test TPR and TNR both meet the threshold. Every run is logged. Run it once you are done iterating on dev.</p>
        {fin.data && ["queued", "running"].includes(fin.data.status) && <Progress r={fin.data} />}
        {fin.data?.status === "done" && (
          <div className="space-y-3">
            <div className={`rounded-md border px-3 py-2 text-[13px] ${fin.data.metrics.passed ? "border-pass-500/40 bg-pass-900/60 text-pass-400" : "border-fail-500/40 bg-fail-900/60 text-fail-400"}`}>
              {fin.data.metrics.passed ? "✓ Validated" : "✕ Not validated"} — run #{fin.data.metrics.run_number}: TPR {pct(fin.data.metrics.tpr)} and TNR {pct(fin.data.metrics.tnr)} against a threshold of {pct(fin.data.metrics.threshold)} (target {pct(e.target)}).
            </div>
            {fin.data.metrics.passed && fin.data.metrics.low_confidence && (
              <Notice tone="warn">
                Validated, but on only {fin.data.metrics.n_pos} trace(s) with the failure and {fin.data.metrics.n_neg} without. The intervals are wide; label more traces (100–200 total, 30+ of each class per split) before relying on this judge.
              </Notice>
            )}
            {fin.data.metrics.overfit_warning && <Notice tone="warn">Likely overfitting: test results are materially worse than dev (gap {pct(fin.data.metrics.dev_gap)}). Revisit the criteria with fresh dev labels rather than tuning on test.</Notice>}
            {fin.data.metrics.repeat_warning && <Notice tone="warn">The test split has been run several times. Repeated final runs used for tuning make this number optimistic.</Notice>}
            <MetricsPanel m={fin.data.metrics} threshold={e.threshold} title="test" />
          </div>
        )}
      </section>

      {labelling && fm && <LabelQueue pid={pid} fm={fm} name={e.failure_mode ?? ""} product={project.data?.name} onClose={() => { setLabelling(false); refresh(); }} />}
    </div>
  );
}

function Progress({ r }: { r: Run }) {
  return (
    <div className="panel flex items-center gap-3 p-3 text-xs text-mist-300">
      <Spinner />
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-800"><div className="h-full bg-accent-400 transition-all" style={{ width: `${(100 * r.progress) / Math.max(1, r.total)}%` }} /></div>
      <span className="tabular-nums">{r.progress}/{r.total}</span>
      {r.cost_estimate > 0 && <span>est. ${r.cost_estimate.toFixed(3)}</span>}
    </div>
  );
}

function Disagreements({ pid, e, rows, product, onChanged }: { pid: number; e: EvalDetail; rows: RunRow[]; product?: string; onChanged: () => void }) {
  const qc = useQueryClient();
  const dis = rows.filter((r) => r.outcome === "missed failure" || r.outcome === "false alarm" || r.outcome === "error");
  const [open, setOpen] = useState<number | null>(null);
  const [text, setText] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const latest = e.versions[0];
  const addCriterion = useMutation({
    mutationFn: ({ which, line }: { which: "failure_when" | "not_failure_when"; line: string }) => {
      const d = { failure_when: [...(latest.definition.failure_when ?? [])], not_failure_when: [...(latest.definition.not_failure_when ?? [])] };
      d[which].push(line);
      return api.post(`/api/projects/${pid}/evaluators/${e.id}/versions`, {
        definition: d, context_scope: latest.context_scope, few_shot_ids: latest.few_shot_ids, model: latest.model,
        note: which === "failure_when" ? "added failure criterion from disagreement" : "added not-a-failure case from disagreement",
      });
    },
    onSuccess: () => {
      setMsg("Saved as a new version. Re-run on dev to see the effect.");
      qc.invalidateQueries({ queryKey: ["evaluator", pid, e.id] });
    },
  });
  const correct = useMutation({
    mutationFn: (r: RunRow) => api.put(`/api/projects/${pid}/ground_truth/${e.failure_mode_id}/${r.trace_id}`, { label: !r.human_label, critique: (text[r.trace_id] || r.human_critique) + " [label corrected after review]" }),
    onSuccess: () => {
      setMsg("Label corrected and logged. Re-run on dev to update the numbers.");
      onChanged();
    },
  });
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-baseline gap-3">
        <div className="text-[13px] font-semibold text-mist-50">Disagreement queue</div>
        <span className="text-xs text-mist-400">{dis.filter((d) => d.outcome === "missed failure").length} missed failures · {dis.filter((d) => d.outcome === "false alarm").length} false alarms</span>
      </div>
      {msg && <div className="mb-2"><Notice tone="ok">{msg}</Notice></div>}
      {!dis.length ? (
        <Empty>The judge agrees with you on every dev trace.</Empty>
      ) : (
        <div className="space-y-2">
          {dis.map((r) => (
            <div key={r.trace_id} className="card p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className={`chip ${r.outcome === "missed failure" ? "border-fail-500/40 text-fail-400" : "border-warn-400/40 text-warn-400"}`}>{r.outcome}</span>
                <button className="font-mono text-xs text-accent-400 hover:underline" onClick={() => setOpen(r.trace_id)}>{r.external_id}</button>
                <span className="text-xxs text-mist-500">{r.channel} · {r.split}</span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-[13px]">
                <div className="panel p-2.5"><div className="label">You — {r.human_label ? "failure present" : "no failure"}</div>{r.human_critique}</div>
                <div className="panel p-2.5"><div className="label">Judge — {r.judge_failure === null ? "error" : r.judge_failure ? "failure present" : "no failure"}</div>{r.judge_critique || r.error}</div>
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <input className="input h-7 w-96 text-xs" placeholder="Describe the scenario in one line…" value={text[r.trace_id] ?? ""} onChange={(x) => setText({ ...text, [r.trace_id]: x.target.value })} />
                <button className="btn-ghost btn-sm" disabled={!text[r.trace_id]} onClick={() => addCriterion.mutate({ which: "failure_when", line: text[r.trace_id] })}>+ Add to failure criteria</button>
                <button className="btn-ghost btn-sm" disabled={!text[r.trace_id]} onClick={() => addCriterion.mutate({ which: "not_failure_when", line: text[r.trace_id] })}>+ Add to "not a failure"</button>
                <button className="btn-ghost btn-sm" disabled title="Only train-split traces can be few-shot examples. This trace is in dev, so it stays an honest measurement. Pick train examples in Build.">Promote to few-shot (train only)</button>
                <button className="btn-ghost btn-sm" onClick={() => confirm(`Change your label to "${r.human_label ? "no failure" : "failure present"}"? The correction is logged.`) && correct.mutate(r)}>Correct my label</button>
                <Link className="btn-quiet btn-sm" to={`/p/${pid}/group`}>Edit failure-mode definition</Link>
              </div>
            </div>
          ))}
        </div>
      )}
      {open && <TracePreview pid={pid} traceId={open} product={product} onClose={() => setOpen(null)} />}
    </div>
  );
}

// ---------------------------------------------------------------- focused labelling queue
type QueueItem = { trace_id: number; external_id: string; channel: string };

function LabelQueue({ pid, fm, name, product, onClose }: { pid: number; fm: number; name: string; product?: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["gtq", pid, fm], queryFn: () => api.get<{ remaining: number; items: QueueItem[] }>(`/api/projects/${pid}/ground_truth/${fm}/queue?limit=50`) });
  const [i, setI] = useState(0);
  const [label, setLabel] = useState<boolean | null>(null);
  const [crit, setCrit] = useState("");
  const [done, setDone] = useState(0);
  const [err, setErr] = useState("");
  const critRef = useRef<HTMLTextAreaElement>(null);
  const item = q.data?.items[i];
  const t = useQuery({ queryKey: ["trace", pid, item?.trace_id], queryFn: () => api.get<TraceView>(`/api/projects/${pid}/traces/${item!.trace_id}`), enabled: !!item });
  const save = async () => {
    if (!item || label === null) return;
    try {
      await api.put(`/api/projects/${pid}/ground_truth/${fm}/${item.trace_id}`, { label, critique: crit });
      setDone((d) => d + 1);
      setI((x) => x + 1);
      setLabel(null);
      setCrit("");
      setErr("");
    } catch (x: any) {
      setErr(x.message);
      critRef.current?.focus();
    }
  };
  useEffect(() => {
    const h = (ev: KeyboardEvent) => {
      const typing = ev.target instanceof HTMLTextAreaElement;
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
        ev.preventDefault();
        save();
        return;
      }
      if (typing) {
        if (ev.key === "Escape") (ev.target as HTMLElement).blur();
        return;
      }
      if (ev.key === "Escape") onClose();
      else if (ev.key === "y") {
        ev.preventDefault();
        setLabel(true);
        critRef.current?.focus();
      } else if (ev.key === "n") {
        ev.preventDefault();
        setLabel(false);
      } else if (ev.key === "j") setI((x) => x + 1);
      else if (ev.key === "k") setI((x) => Math.max(0, x - 1));
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-ink-950">
      <div className="flex h-12 items-center gap-4 border-b border-ink-700 px-4">
        <div className="font-semibold text-mist-50">Labelling: {name}</div>
        <span className="text-xs text-mist-400">{done} labelled this session · {Math.max(0, (q.data?.remaining ?? 0) - done)} unlabelled left</span>
        <span className="text-xs text-mist-500">Judge output is never shown here.</span>
        <button className="btn-quiet btn-sm ml-auto" onClick={onClose}>Done <span className="kbd">Esc</span></button>
      </div>
      {!item ? (
        <div className="p-8"><Empty>No more unlabelled traces in this queue.</Empty></div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_380px]">
          <div className="overflow-y-auto bg-ink-900 p-6">
            <div className="mb-3 flex gap-2"><span className="font-mono text-[13px] text-mist-50">{item.external_id}</span><span className="chip">{item.channel}</span></div>
            {t.data ? <TraceRenderer trace={t.data} product={product} toolsExpanded /> : <Spinner />}
          </div>
          <div className="space-y-4 border-l border-ink-700 p-4">
            <div className="h2">Is "{name}" present in this trace?</div>
            <div className="grid grid-cols-2 gap-2">
              <button onClick={() => { setLabel(true); critRef.current?.focus(); }} className={`h-12 rounded-md border font-semibold ${label === true ? "border-fail-500 bg-fail-500 text-white" : "border-ink-600 text-mist-200"}`}>✕ Present <span className="kbd">Y</span></button>
              <button onClick={() => setLabel(false)} className={`h-12 rounded-md border font-semibold ${label === false ? "border-pass-500 bg-pass-500 text-white" : "border-ink-600 text-mist-200"}`}>✓ Absent <span className="kbd">N</span></button>
            </div>
            <div>
              <label className="label">Critique {label ? "(required)" : "(optional)"}</label>
              <textarea ref={critRef} className="input min-h-[110px]" value={crit} onChange={(x) => setCrit(x.target.value)} placeholder="What did you see?" />
            </div>
            {err && <Notice tone="danger">{err}</Notice>}
            <button className="btn-primary w-full justify-center" disabled={label === null} onClick={save}>Save &amp; next <span className="kbd border-white/30 bg-transparent text-white">Ctrl ↵</span></button>
            <div className="text-xs text-mist-400"><span className="kbd">J</span>/<span className="kbd">K</span> skip / back · traces most likely to show the failure come first</div>
          </div>
        </div>
      )}
    </div>
  );
}

