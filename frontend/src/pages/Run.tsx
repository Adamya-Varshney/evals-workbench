import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type BatchSummary, type Facet } from "../api";
import { Empty, Notice, PageHeader, Spinner, Stat, Term, pct, usePid, useStatus } from "../components/ui";
import { STATUS_CHIP } from "./Build";

type Rate = { k: number; n: number; rate: number | null; ci: [number | null, number | null] };
type Corrected = { theta: number; ci: [number | null, number | null]; p_obs: number; tpr: number; tnr: number; n_test: number; n_unlabelled: number };
type EvRow = { evaluator_id: number; name: string; type: string; status: string; n: number; errors: number; cached: number; raw: Rate; corrected: Corrected | null; corrected_note: string | null; by_facet?: Record<string, Rate> };
type Report = { status: string; progress?: number; total?: number; error?: string; n_traces: number; evaluators: EvRow[]; pass_all: Rate; pass_all_by_facet: Record<string, Rate> | null; facet: string | null; facet_values: string[] };
type RunRow = { id: number; status: string; progress: number; total: number; batch: string; batch_id: number; cost_estimate: number; cost_actual: number; created_at: string; error: string };
type Estimate = { llm_calls: number; cached: number; usd: number; model: string; mode: string; n_traces: number; evaluators: { id: number; name: string; type: string; status: string }[]; concurrency: number };

const R = (r?: Rate | null, digits = 1) => (r && r.n ? `${pct(r.rate, digits)}` : "—");
const CI = (c?: [number | null, number | null]) => (c && c[0] !== null ? `${pct(c[0])}–${pct(c[1])}` : "");

export function Run() {
  const pid = usePid();
  const qc = useQueryClient();
  const nav = useNavigate();
  const status = useStatus(pid);
  const batches = useQuery({ queryKey: ["batches", pid], queryFn: () => api.get<BatchSummary[]>(`/api/projects/${pid}/batches`) });
  const runs = useQuery({
    queryKey: ["suiteRuns", pid],
    queryFn: () => api.get<RunRow[]>(`/api/projects/${pid}/suite/runs`),
    refetchIntervalInBackground: true,
    refetchInterval: (q) => (q.state.data?.some((r) => ["queued", "running"].includes(r.status)) ? 1000 : false),
  });
  const [batch, setBatch] = useState<string>("");
  const [sel, setSel] = useState<number | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    if (!batch && batches.data?.length) setBatch(String(batches.data[batches.data.length - 1].id));
  }, [batches.data, batch]);
  useEffect(() => {
    if (sel === null && runs.data?.length) setSel(runs.data[0].id);
  }, [runs.data, sel]);
  const est = useQuery({ queryKey: ["estimate", pid, batch], queryFn: () => api.get<Estimate>(`/api/projects/${pid}/suite/estimate?batch_id=${batch}`), enabled: !!batch });
  const run = useMutation({
    mutationFn: () => api.post<{ run_id: number }>(`/api/projects/${pid}/suite/run`, { batch_id: Number(batch) }),
    onSuccess: (r) => {
      setSel(r.run_id);
      qc.invalidateQueries({ queryKey: ["suiteRuns", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
    },
    onError: (x: any) => setErr(x.message),
  });
  const stage = status.data?.stages.find((s) => s.key === "run");
  if (stage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader title="Run and measure" />
        <Notice>{stage.unlock}</Notice>
      </div>
    );
  const e = est.data;
  return (
    <div className="mx-auto max-w-[1300px] px-6 py-6">
      <PageHeader title="Run and measure" sub="Run the active suite on any batch of traces, compare versions, and log every experiment. The roadmap counts experiments, not features." />
      <div className="card flex flex-wrap items-end gap-4 p-4">
        <div>
          <label className="label">Batch</label>
          <select className="input h-8 w-60 py-0" value={batch} onChange={(x) => setBatch(x.target.value)}>
            {batches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
          </select>
        </div>
        <div className="min-w-0 flex-1 text-xs text-mist-300">
          {e ? (
            <>
              <div className="flex flex-wrap gap-1">{e.evaluators.map((x) => <span key={x.id} className={`chip ${STATUS_CHIP[x.status]}`}>{x.type === "code" ? "{ }" : "✦"} {x.name}</span>)}</div>
              <div className="mt-1">
                <b>Cost estimate:</b> {e.llm_calls} judge call{e.llm_calls === 1 ? "" : "s"} ({e.cached} cached) · ≈ ${e.usd.toFixed(3)} on {e.model}{e.mode === "mock" ? " (mock mode: free)" : ""} · up to {e.concurrency} at a time · code checks are free.
              </div>
            </>
          ) : <Spinner />}
        </div>
        <button className="btn-primary" disabled={!e?.evaluators.length || run.isPending} onClick={() => { setErr(""); run.mutate(); }}>Run suite on batch</button>
      </div>
      {err && <div className="mt-2"><Notice tone="danger">{err}</Notice></div>}

      <div className="mt-5 grid grid-cols-[300px_minmax(0,1fr)] gap-5">
        <div>
          <div className="label">Runs</div>
          {!runs.data?.length && <Empty>No runs yet.</Empty>}
          <div className="space-y-1.5">
            {runs.data?.map((r) => (
              <button key={r.id} onClick={() => setSel(r.id)} className={`block w-full rounded-md border px-3 py-2 text-left ${sel === r.id ? "border-accent-400 bg-ink-950" : "border-ink-700 hover:border-ink-500"}`}>
                <div className="flex items-center gap-2"><span className="font-mono text-xs">#{r.id}</span><span className="truncate text-[13px] font-medium text-mist-50">{r.batch}</span></div>
                <div className="text-xxs text-mist-500">
                  {r.status === "done" ? `done · $${r.cost_actual.toFixed(3)}` : r.status === "failed" ? `failed: ${r.error}` : `${r.status} ${r.progress}/${r.total}`} · {new Date(r.created_at).toLocaleString()}
                </div>
              </button>
            ))}
          </div>
        </div>
        <div className="min-w-0">{sel && <RunReport pid={pid} rid={sel} onFlagged={(bid) => nav(`/p/${pid}/review?batch=${bid}`)} />}</div>
      </div>

      {(runs.data?.filter((r) => r.status === "done").length ?? 0) >= 2 && <Compare pid={pid} runs={runs.data!.filter((r) => r.status === "done")} />}
      <Experiments pid={pid} />
    </div>
  );
}

function RunReport({ pid, rid, onFlagged }: { pid: number; rid: number; onFlagged: (bid: number) => void }) {
  const [facet, setFacet] = useState("");
  const facets = useQuery({ queryKey: ["facets", pid], queryFn: () => api.get<Facet[]>(`/api/projects/${pid}/facets`) });
  const q = useQuery({
    queryKey: ["report", pid, rid, facet],
    queryFn: () => api.get<Report>(`/api/projects/${pid}/suite/runs/${rid}/report${facet ? `?facet=${facet}` : ""}`),
    refetchIntervalInBackground: true,
    refetchInterval: (x) => (x.state.data && x.state.data.status !== "done" && x.state.data.status !== "failed" ? 1000 : false),
  });
  const flag = useMutation({ mutationFn: () => api.post<{ id: number }>(`/api/projects/${pid}/suite/flagged_to_review`, { run_id: rid, size: 30 }), onSuccess: (b) => onFlagged(b.id) });
  const r = q.data;
  if (!r) return <Spinner />;
  if (r.status !== "done")
    return r.status === "failed" ? <Notice tone="danger">{r.error}</Notice> : (
      <div className="panel flex items-center gap-3 p-4"><Spinner label={`Running… ${r.progress}/${r.total}`} /><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-800"><div className="h-full bg-accent-400" style={{ width: `${(100 * (r.progress ?? 0)) / Math.max(1, r.total ?? 1)}%` }} /></div></div>
    );
  const catFacets = (facets.data ?? []).filter((f) => f.kind === "category");
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Pass-all rate" value={R(r.pass_all)} sub={<>a trace passes only if it passes every evaluator · {r.pass_all.k}/{r.pass_all.n} · CI {CI(r.pass_all.ci)}</>} />
        <Stat label="Traces" value={r.n_traces} />
        <Stat label="Evaluators" value={r.evaluators.length} sub={`${r.evaluators.reduce((a, e) => a + e.cached, 0)} cached results`} />
      </div>
      <div className="flex items-center gap-2">
        <label className="text-xs text-mist-400">Group by</label>
        <select className="input h-8 w-44 py-0" value={facet} onChange={(x) => setFacet(x.target.value)}>
          <option value="">— none —</option>
          {catFacets.map((f) => <option key={f.key} value={f.key}>{f.key}</option>)}
        </select>
        <button className="btn-ghost btn-sm ml-auto" onClick={() => flag.mutate()} title="Builds a review batch from flagged traces (plus 20% random). Verdicts stay hidden until you save your own.">Send flagged traces to review →</button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-ink-700">
        <table className="tbl">
          <thead>
            <tr>
              <th>Evaluator</th>
              <th className="text-right">Raw failure rate</th>
              <th className="text-right"><Term tip="For judges: the raw rate corrected for the judge's own errors, theta = (p_obs + TNR − 1) / (TPR + TNR − 1), using TPR/TNR from the test split, with a 2,000-sample bootstrap interval.">Corrected rate</Term></th>
              {r.facet && r.facet_values.map((v) => <th key={v} className="text-right">{v}</th>)}
            </tr>
          </thead>
          <tbody>
            {r.evaluators.map((e) => (
              <tr key={e.evaluator_id}>
                <td>
                  <div className="font-medium text-mist-50">{e.type === "code" ? "{ }" : "✦"} {e.name}</div>
                  <div className="text-xxs text-mist-500">{e.status}{e.errors ? ` · ${e.errors} errors` : ""}</div>
                </td>
                <td className="text-right tabular-nums">{R(e.raw)}<div className="text-xxs text-mist-500">{e.raw.k}/{e.raw.n} · CI {CI(e.raw.ci)}</div></td>
                <td className="text-right tabular-nums">
                  {e.type === "code" ? <span className="text-xs text-mist-500">n/a (deterministic)</span> : e.corrected ? (
                    <>
                      <b>{pct(e.corrected.theta, 1)}</b>
                      <div className="text-xxs text-mist-500">CI {CI(e.corrected.ci)} · TPR {pct(e.corrected.tpr)} / TNR {pct(e.corrected.tnr)} on n={e.corrected.n_test}</div>
                    </>
                  ) : <span className="text-xs text-warn-400">{e.corrected_note}</span>}
                </td>
                {r.facet && r.facet_values.map((v) => <td key={v} className="text-right tabular-nums">{R(e.by_facet?.[v])}<div className="text-xxs text-mist-500">n={e.by_facet?.[v]?.n ?? 0}</div></td>)}
              </tr>
            ))}
            {r.facet && r.pass_all_by_facet && (
              <tr className="bg-ink-900">
                <td className="font-medium">Pass-all</td><td className="text-right">{R(r.pass_all)}</td><td />
                {r.facet_values.map((v) => <td key={v} className="text-right tabular-nums">{R(r.pass_all_by_facet![v])}</td>)}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type CompareData = { a: { run_id: number; batch: string; pass_all: Rate; n: number }; b: { run_id: number; batch: string; pass_all: Rate; n: number }; rows: { evaluator_id: number; name: string; type: string; a: EvRow; b: EvRow | null; delta: number | null }[] };

function Compare({ pid, runs }: { pid: number; runs: RunRow[] }) {
  const qc = useQueryClient();
  const [a, setA] = useState(String(runs[1]?.id ?? ""));
  const [b, setB] = useState(String(runs[0]?.id ?? ""));
  const q = useQuery({ queryKey: ["compare", pid, a, b], queryFn: () => api.get<CompareData>(`/api/projects/${pid}/suite/compare?a=${a}&b=${b}`), enabled: !!a && !!b && a !== b });
  const [x, setX] = useState({ hypothesis: "", change: "", result: "" });
  const log = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/experiments`, { ...x, run_a_id: Number(a), run_b_id: Number(b) }),
    onSuccess: () => {
      setX({ hypothesis: "", change: "", result: "" });
      qc.invalidateQueries({ queryKey: ["experiments", pid] });
    },
  });
  const rate = (e?: EvRow | null) => (e ? (e.corrected ? e.corrected.theta : e.raw.rate) : null);
  return (
    <div className="mt-8">
      <div className="h2 mb-2">Compare two runs</div>
      <div className="mb-3 flex items-center gap-2 text-xs">
        <span className="text-mist-400">Before</span>
        <select className="input h-8 w-64 py-0" value={a} onChange={(e) => setA(e.target.value)}>{runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.batch}</option>)}</select>
        <span className="text-mist-400">After</span>
        <select className="input h-8 w-64 py-0" value={b} onChange={(e) => setB(e.target.value)}>{runs.map((r) => <option key={r.id} value={r.id}>#{r.id} · {r.batch}</option>)}</select>
      </div>
      {q.data && (
        <div className="overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <thead><tr><th>Evaluator</th><th className="text-right">Before ({q.data.a.batch})</th><th className="text-right">After ({q.data.b.batch})</th><th className="text-right">Change</th></tr></thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={r.evaluator_id}>
                  <td className="font-medium text-mist-50">{r.name}</td>
                  <td className="text-right tabular-nums">{pct(rate(r.a), 1)}</td>
                  <td className="text-right tabular-nums">{pct(rate(r.b), 1)}</td>
                  <td className={`text-right tabular-nums ${r.delta === null ? "" : r.delta > 0.005 ? "text-fail-400" : r.delta < -0.005 ? "text-pass-400" : "text-mist-400"}`}>
                    {r.delta === null ? "—" : `${r.delta > 0 ? "▲ worse " : r.delta < 0 ? "▼ better " : ""}${pct(Math.abs(r.delta), 1)}`}
                  </td>
                </tr>
              ))}
              <tr className="bg-ink-900"><td className="font-medium">Pass-all</td><td className="text-right">{R(q.data.a.pass_all)}</td><td className="text-right">{R(q.data.b.pass_all)}</td><td /></tr>
            </tbody>
          </table>
        </div>
      )}
      <div className="card mt-3 grid grid-cols-[1fr_1fr_1fr_auto] items-end gap-2 p-3">
        <div><label className="label">Hypothesis</label><input className="input" value={x.hypothesis} onChange={(e) => setX({ ...x, hypothesis: e.target.value })} placeholder="Adding the SMS plain-text rule removes markdown" /></div>
        <div><label className="label">Change</label><input className="input" value={x.change} onChange={(e) => setX({ ...x, change: e.target.value })} placeholder="Prompt v1.4" /></div>
        <div><label className="label">Result</label><input className="input" value={x.result} onChange={(e) => setX({ ...x, result: e.target.value })} placeholder="Markdown 8% → 1%; no regressions" /></div>
        <button className="btn-primary" disabled={!x.hypothesis.trim() || !x.change.trim()} onClick={() => log.mutate()}>Log experiment</button>
      </div>
    </div>
  );
}

function Experiments({ pid }: { pid: number }) {
  const q = useQuery({ queryKey: ["experiments", pid], queryFn: () => api.get<{ count: number; items: any[] }>(`/api/projects/${pid}/experiments`) });
  return (
    <div className="mt-8">
      <div className="mb-2 flex items-baseline gap-3">
        <div className="h2">Experiment log</div>
        <span className="chip">{q.data?.count ?? 0} experiments run</span>
      </div>
      {!q.data?.items.length ? <Empty>Every comparison you log appears here with its hypothesis, change and result.</Empty> : (
        <div className="overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <thead><tr><th>#</th><th>Hypothesis</th><th>Change</th><th>Result</th><th>Measured</th><th>When</th></tr></thead>
            <tbody>
              {q.data.items.map((x: any, i: number) => (
                <tr key={x.id}>
                  <td className="text-mist-500">{q.data!.count - i}</td>
                  <td className="text-mist-100">{x.hypothesis}</td>
                  <td className="text-mist-300">{x.change}</td>
                  <td className="text-mist-300">{x.result}</td>
                  <td className="text-xs text-mist-400">{(x.snapshot?.deltas ?? []).map((d: any) => `${d.name}: ${d.delta === null ? "—" : `${d.delta > 0 ? "+" : ""}${(100 * d.delta).toFixed(1)}pt`}`).join("; ")}</td>
                  <td className="text-xs text-mist-400">{new Date(x.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

