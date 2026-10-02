import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type BatchSummary, type Facet, type TraceView } from "../api";
import { TraceRenderer } from "../components/TraceRenderer";
import { Empty, Notice, PageHeader, Spinner, Term, usePid, useProject, useStatus } from "../components/ui";

type Job = {
  id: number;
  filename: string;
  fmt: string;
  mapping: Record<string, any>;
  redaction: Record<string, any>;
  report: Record<string, any>;
  status: string;
  tags: Record<string, any>;
  fields: { path: string; sample: string }[];
};

export function Traces() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const status = useStatus(pid);
  const [job, setJob] = useState<Job | null>(null);
  const [report, setReport] = useState<any>(null);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["status", pid] });
    qc.invalidateQueries({ queryKey: ["batches", pid] });
    qc.invalidateQueries({ queryKey: ["facets", pid] });
    qc.invalidateQueries({ queryKey: ["pvs", pid] });
  };
  const n = status.data?.counts.traces ?? 0;
  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      <PageHeader
        title="Get traces"
        sub="A trace is the full record of one interaction: system prompt, user messages, tool calls and results, assistant replies, and metadata."
      />
      <AiNotice pid={pid} enabled={project.data?.settings.ai_assist_enabled !== false} />

      {job ? (
        <MappingScreen
          pid={pid}
          product={project.data?.name ?? "Assistant"}
          job={job}
          onCancel={() => setJob(null)}
          onDone={(r) => {
            setJob(null);
            setReport(r);
            refresh();
          }}
        />
      ) : (
        <>
          <ImportBox pid={pid} isDemo={!!project.data?.is_demo} onStaged={(j) => { setReport(null); setJob(j); }} />
          {report && <ImportReport report={report} />}
          <div className="mt-10">
            <div className="mb-3 flex items-baseline justify-between">
              <div className="h2">Traces in this project</div>
              <div className="text-sm text-mist-400">{n} imported</div>
            </div>
            {n === 0 ? <Empty>No traces yet. Import a file above.</Empty> : <FacetSummary pid={pid} />}
          </div>
          {n > 0 && <Batches pid={pid} total={n} />}
          <SyntheticTeaser />
        </>
      )}
    </div>
  );
}

function AiNotice({ pid, enabled }: { pid: number; enabled: boolean }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: () => api.patch(`/api/projects/${pid}`, { settings: { ai_assist_enabled: !enabled } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["project", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
    },
  });
  return (
    <div className="mb-5 flex items-center justify-between gap-4 rounded-lg border border-ink-700 bg-ink-900 px-4 py-2.5 text-[13px]">
      <div className="text-mist-300">
        <span className="font-semibold text-mist-100">Privacy:</span> trace content is sent to the Anthropic API whenever an AI-assist feature runs (proposing categories, suggesting assignments, drafting, judging, finding similar traces). Nothing is sent while you import or review.
      </div>
      <label className="flex shrink-0 cursor-pointer items-center gap-2">
        <span className="text-mist-300">AI assist</span>
        <button
          role="switch"
          aria-checked={enabled}
          onClick={() => toggle.mutate()}
          className={`relative h-5 w-9 rounded-full transition ${enabled ? "bg-accent-400" : "bg-ink-600"}`}
        >
          <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${enabled ? "left-[18px]" : "left-0.5"}`} />
        </button>
        <span className="w-7 text-xs text-mist-400">{enabled ? "on" : "off"}</span>
      </label>
    </div>
  );
}

function ImportBox({ pid, isDemo, onStaged }: { pid: number; isDemo: boolean; onStaged: (j: Job) => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [synthetic, setSynthetic] = useState(false);
  const [drag, setDrag] = useState(false);
  const [err, setErr] = useState("");
  const stage = useMutation({
    mutationFn: (fd: FormData) => api.form<Job>(`/api/projects/${pid}/imports`, fd),
    onSuccess: onStaged,
    onError: (e: any) => setErr(e.message),
  });
  const send = (file?: File) => {
    const fd = new FormData();
    if (file) fd.append("file", file);
    else fd.append("demo", "true");
    if (synthetic) fd.append("synthetic", "true");
    setErr("");
    stage.mutate(fd);
  };
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        const f = e.dataTransfer.files[0];
        if (f) send(f);
      }}
      className={`card flex flex-col items-center gap-3 border-dashed p-6 text-center ${drag ? "border-accent-400 bg-ink-850" : ""}`}
    >
      <div className="h2">Import traces</div>
      <p className="max-w-xl text-sm text-mist-300">
        JSONL, JSON or CSV. OpenAI-style message arrays, Anthropic content blocks, or flat input/output columns all work — exports from Braintrust, LangSmith, Phoenix or your own logs. Missing fields won't block the import.
      </p>
      <div className="flex items-center gap-2">
        <button className="btn-primary" onClick={() => fileRef.current?.click()} disabled={stage.isPending}>
          Choose a file
        </button>
        {isDemo && (
          <button className="btn-ghost" onClick={() => send()} disabled={stage.isPending}>
            Load the Larkspur demo traces
          </button>
        )}
      </div>
      <label className="flex items-center gap-2 text-xs text-mist-400">
        <input type="checkbox" checked={synthetic} onChange={(e) => setSynthetic(e.target.checked)} /> These traces came from synthetic inputs (tag them as synthetic)
      </label>
      <input ref={fileRef} type="file" accept=".jsonl,.json,.csv,.txt" hidden onChange={(e) => e.target.files?.[0] && send(e.target.files[0])} />
      {stage.isPending && <Spinner label="Reading file…" />}
      {err && <Notice tone="danger">{err}</Notice>}
    </div>
  );
}

const MAP_FIELDS: { key: string; label: string; help: string; modes: string[] }[] = [
  { key: "messages", label: "Message array", help: "List of {role, content} messages (OpenAI or Anthropic style).", modes: ["messages"] },
  { key: "input", label: "Input", help: "User input (text, or a message array).", modes: ["input_output"] },
  { key: "output", label: "Output", help: "Assistant output (text, or a message array).", modes: ["input_output"] },
  { key: "system", label: "System prompt", help: "Optional. Otherwise taken from a system message.", modes: ["messages", "input_output"] },
  { key: "id", label: "Trace ID", help: "Optional. Used for de-duplication.", modes: ["messages", "input_output"] },
  { key: "channel", label: "Channel", help: "sms, email, chat, voice…", modes: ["messages", "input_output"] },
  { key: "prompt_version", label: "Prompt version", help: "Optional. Links traces to a system prompt version.", modes: ["messages", "input_output"] },
];

function MappingScreen({ pid, product, job, onCancel, onDone }: { pid: number; product: string; job: Job; onCancel: () => void; onDone: (r: any) => void }) {
  const [mapping, setMapping] = useState<Record<string, any>>(job.mapping);
  const [red, setRed] = useState<{ emails: boolean; phones: boolean; custom: string[] }>({ emails: false, phones: false, custom: [] });
  const [customText, setCustomText] = useState("");
  const [preview, setPreview] = useState<{ traces: TraceView[]; skipped_in_preview: any[]; total_records: number; parse_errors: any[] } | null>(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const redaction = useMemo(() => ({ ...red, custom: customText.split("\n").map((s) => s.trim()).filter(Boolean) }), [red, customText]);

  useEffect(() => {
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        setPreview(await api.post(`/api/projects/${pid}/imports/${job.id}/preview`, { mapping, redaction }));
        setErr("");
      } catch (e: any) {
        setErr(e.message);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(t);
  }, [mapping, redaction, pid, job.id]);

  const commit = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/imports/${job.id}/commit`, { mapping, redaction }),
    onSuccess: onDone,
    onError: (e: any) => setErr(e.message),
  });
  const mode = mapping.mode ?? "messages";
  const mapped = new Set(MAP_FIELDS.map((f) => mapping[f.key]).filter(Boolean));
  const roots = new Set([...mapped].map((p: string) => p.split(".")[0]));
  const facets = job.fields.filter((f) => !mapped.has(f.path) && !roots.has(f.path) && !f.path.includes(".")).map((f) => f.path);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <div className="h2">Map fields — {job.filename}</div>
          <div className="text-sm text-mist-400">
            Detected {job.fmt.toUpperCase()}, {preview?.total_records ?? job.report.parsed} records{(preview?.parse_errors?.length ?? 0) > 0 && `, ${preview?.parse_errors.length} unreadable lines (will be skipped)`}. We guessed a mapping; check the preview on the right.
          </div>
        </div>
        <div className="flex gap-2">
          <button className="btn-quiet" onClick={onCancel}>Cancel</button>
          <button className="btn-primary" onClick={() => commit.mutate()} disabled={commit.isPending || !preview?.traces.length}>
            {commit.isPending ? "Importing…" : `Import ${preview?.total_records ?? ""} records`}
          </button>
        </div>
      </div>
      {err && <div className="mb-3"><Notice tone="danger">{err}</Notice></div>}
      <div className="grid grid-cols-[360px_1fr] gap-6">
        <div className="space-y-5">
          <div className="card space-y-3 p-4">
            <div className="label">Conversation shape</div>
            <div className="flex gap-2">
              {[["messages", "Message array"], ["input_output", "Input + output"]].map(([v, l]) => (
                <button key={v} className={mode === v ? "btn-primary" : "btn-ghost"} onClick={() => setMapping({ ...mapping, mode: v })}>{l}</button>
              ))}
            </div>
            {MAP_FIELDS.filter((f) => f.modes.includes(mode)).map((f) => (
              <div key={f.key}>
                <label className="label" title={f.help}>{f.label}</label>
                <select className="input" value={mapping[f.key] ?? ""} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value || undefined })}>
                  <option value="">— none —</option>
                  {job.fields.map((x) => (
                    <option key={x.path} value={x.path}>{x.path}  ·  {x.sample.slice(0, 40)}</option>
                  ))}
                </select>
              </div>
            ))}
            <div>
              <label className="label">Default channel (when none is mapped or a value is empty)</label>
              <select className="input" value={mapping.channel_default ?? "chat"} onChange={(e) => setMapping({ ...mapping, channel_default: e.target.value })}>
                {["chat", "sms", "email", "voice"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div className="card p-4">
            <div className="label">Becomes filterable metadata</div>
            <div className="flex flex-wrap gap-1.5">
              {facets.length ? facets.map((f) => <span key={f} className="chip">{f}</span>) : <span className="text-sm text-mist-400">No other fields.</span>}
            </div>
          </div>
          <div className="card space-y-2 p-4">
            <div className="label">Redact on import (optional)</div>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={red.emails} onChange={(e) => setRed({ ...red, emails: e.target.checked })} /> Email addresses → [EMAIL]</label>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={red.phones} onChange={(e) => setRed({ ...red, phones: e.target.checked })} /> Phone numbers → [PHONE]</label>
            <textarea className="input font-mono text-xs" rows={2} placeholder="Custom regex, one per line" value={customText} onChange={(e) => setCustomText(e.target.value)} />
          </div>
        </div>
        <div>
          <div className="mb-2 flex items-center gap-3">
            <div className="label mb-0">Live preview — first 3 traces, exactly as the review screen will show them</div>
            {loading && <Spinner />}
          </div>
          {preview?.skipped_in_preview?.length ? (
            <div className="mb-3"><Notice tone="warn">{preview.skipped_in_preview.length} of the first records would be skipped: {preview.skipped_in_preview[0].reason}</Notice></div>
          ) : null}
          <div className="space-y-6">
            {preview?.traces.map((t, i) => (
              <div key={i} className="card p-4">
                <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
                  <span className="chip border-accent-500/40 text-accent-300">{t.channel}</span>
                  <span className="chip">{t.external_id}</span>
                  {Object.entries(t.meta).filter(([k]) => k !== "channel").slice(0, 6).map(([k, v]) => <span key={k} className="chip">{k}: {String(v)}</span>)}
                </div>
                <TraceRenderer trace={t} product={product} />
              </div>
            ))}
            {preview && !preview.traces.length && <Empty>No records could be read with this mapping. Pick the field that holds the conversation.</Empty>}
          </div>
        </div>
      </div>
    </div>
  );
}

function ImportReport({ report }: { report: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="card mt-6 p-5">
      <div className="h2">Import report</div>
      <div className="mt-3 grid grid-cols-3 gap-4 text-sm">
        <div><div className="label">Imported</div><div className="text-2xl font-semibold text-pass-400">{report.imported}</div></div>
        <div><div className="label">Skipped</div><div className="text-2xl font-semibold text-accent-300">{report.skipped}</div></div>
        <div><div className="label">By channel</div>{Object.entries(report.channels ?? {}).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}</div>
      </div>
      {report.skipped > 0 && (
        <div className="mt-4">
          <div className="text-sm text-mist-300">Why: {Object.entries(report.skip_reasons ?? {}).map(([k, v]) => `${k} (${v})`).join("; ")}</div>
          <button className="btn-quiet mt-1 px-0" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} skipped rows</button>
          {open && (
            <table className="mt-2 w-full text-left text-sm">
              <thead className="text-xs text-mist-400"><tr><th className="py-1">Line</th><th>ID</th><th>Reason</th></tr></thead>
              <tbody>
                {report.skipped_rows.map((r: any, i: number) => (
                  <tr key={i} className="border-t border-ink-800"><td className="py-1">{r.line}</td><td className="font-mono text-xs">{r.id ?? ""}</td><td>{r.reason}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function FacetSummary({ pid }: { pid: number }) {
  const q = useQuery({ queryKey: ["facets", pid], queryFn: () => api.get<Facet[]>(`/api/projects/${pid}/facets`) });
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
      {q.data?.map((f) => (
        <div key={f.key} className="card p-3">
          <div className="label">{f.key}</div>
          {f.kind === "category" ? (
            <div className="flex flex-wrap gap-1">
              {f.values.slice(0, 8).map((v) => <span key={v.value} className="chip">{v.value} <span className="text-mist-500">{v.count}</span></span>)}
              {f.values.length > 8 && <span className="text-xs text-mist-500">+{f.values.length - 8} more</span>}
            </div>
          ) : (
            <div className="text-sm text-mist-300">{f.min.toLocaleString()} – {f.max.toLocaleString()} <span className="text-mist-500">({f.count} values)</span></div>
          )}
        </div>
      ))}
    </div>
  );
}

const METHOD_HELP: Record<string, string> = {
  random: "A plain random sample. The best default for a first round.",
  stratified: "Spread the batch evenly across the values of one facet (e.g. channel).",
  outliers: "The longest conversations, most turns or most tool calls.",
  negative_feedback: "Traces where the user gave negative feedback.",
  evaluator_flag: "Traces an active evaluator flagged as failing (available after you run evaluators).",
};

function Batches({ pid, total }: { pid: number; total: number }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const batches = useQuery({ queryKey: ["batches", pid], queryFn: () => api.get<BatchSummary[]>(`/api/projects/${pid}/batches`) });
  const facets = useQuery({ queryKey: ["facets", pid], queryFn: () => api.get<Facet[]>(`/api/projects/${pid}/facets`) });
  const [size, setSize] = useState(100);
  const [method, setMethod] = useState("random");
  const [facet, setFacet] = useState("channel");
  const [by, setBy] = useState("n_turns");
  const [fbField, setFbField] = useState("user_feedback");
  const [excl, setExcl] = useState(false);
  const [err, setErr] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.post<BatchSummary>(`/api/projects/${pid}/batches`, {
        size,
        method,
        params: { ...(method === "stratified" ? { facet } : {}), ...(method === "outliers" ? { by } : {}), ...(method === "negative_feedback" ? { field: fbField } : {}), exclude_reviewed: excl },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["batches", pid] });
      qc.invalidateQueries({ queryKey: ["status", pid] });
      setErr("");
    },
    onError: (e: any) => setErr(e.message),
  });
  const catFacets = (facets.data ?? []).filter((f) => f.kind === "category").map((f) => f.key);
  return (
    <div className="mt-10">
      <div className="h2">Review batches</div>
      <p className="mb-4 mt-1 text-sm text-mist-400">
        A batch is the set of traces you will read in one round. Around 100 is typical. Whatever method you choose, at least 20% of the batch stays random so failures you don't know about yet can still show up.
      </p>
      <div className="card grid grid-cols-[120px_220px_1fr_auto] items-end gap-3 p-4">
        <div>
          <label className="label">Size</label>
          <input className="input" type="number" min={1} max={total} value={size} onChange={(e) => setSize(Number(e.target.value))} />
        </div>
        <div>
          <label className="label">Method</label>
          <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="random">Random</option>
            <option value="stratified">Stratified by a facet</option>
            <option value="outliers">Outliers</option>
            <option value="negative_feedback">Negative user feedback</option>
            <option value="evaluator_flag">Flagged by an evaluator</option>
          </select>
        </div>
        <div className="space-y-1">
          {method === "stratified" && (
            <select className="input" value={facet} onChange={(e) => setFacet(e.target.value)}>{catFacets.map((k) => <option key={k}>{k}</option>)}</select>
          )}
          {method === "outliers" && (
            <select className="input" value={by} onChange={(e) => setBy(e.target.value)}>
              <option value="n_turns">Most turns</option><option value="n_chars">Longest conversations</option><option value="n_tool_calls">Most tool calls</option>
            </select>
          )}
          {method === "negative_feedback" && (
            <select className="input" value={fbField} onChange={(e) => setFbField(e.target.value)}>{catFacets.map((k) => <option key={k}>{k}</option>)}</select>
          )}
          <div className="text-xs text-mist-400">{METHOD_HELP[method]}</div>
          <label className="flex items-center gap-2 text-xs text-mist-400"><input type="checkbox" checked={excl} onChange={(e) => setExcl(e.target.checked)} /> Skip traces already reviewed</label>
        </div>
        <button className="btn-primary" onClick={() => create.mutate()} disabled={create.isPending}>Build batch</button>
      </div>
      {err && <div className="mt-2"><Notice tone="danger">{err}</Notice></div>}
      {!!batches.data?.length && (
        <div className="mt-4 overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <thead>
              <tr><th>Batch</th><th>Sample</th><th className="w-56">Progress</th><th className="w-28" /></tr>
            </thead>
            <tbody>
              {batches.data.map((b) => (
                <tr key={b.id}>
                  <td><div className="font-medium text-mist-50">{b.name}</div><div className="text-xxs text-mist-500">{new Date(b.created_at).toLocaleString()}</div></td>
                  <td className="text-xs text-mist-400">{Object.entries(b.reasons).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(" · ")}</td>
                  <td>
                    <div className="mb-1 text-xs tabular-nums text-mist-300">{b.reviewed} of {b.size} reviewed</div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-ink-800"><div className="h-full bg-accent-400" style={{ width: `${(100 * b.reviewed) / Math.max(1, b.size)}%` }} /></div>
                  </td>
                  <td className="text-right"><button className="btn-ghost btn-sm" onClick={() => nav(`/p/${pid}/review?batch=${b.id}`)}>Review →</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SyntheticTeaser() {
  const pid = usePid();
  return (
    <div className="mt-10 rounded-lg border border-ink-700 bg-ink-900 p-4 text-[13px] text-mist-300">
      <span className="font-semibold text-mist-100">No real traces yet?</span> Use the{" "}
      <Term tip="Generates varied user inputs from dimensions you define (feature, scenario, persona). You run them through your real system and import the results.">synthetic input generator</Term>{" "}
      to create realistic inputs, run them through your system, and import the traces. <Link className="text-accent-400 underline" to={`/p/${pid}/synthetic`}>Open it →</Link>
    </div>
  );
}
