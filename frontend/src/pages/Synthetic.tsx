import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Notice, PageHeader, Term, usePid, useProject } from "../components/ui";

type Dim = { id?: number; name: string; values: string[] };
type Tup = { id: number; values: Record<string, string>; source: string; status: string; user_message: string };
type State = { dimensions: Dim[]; tuples: Tup[]; grounding: string; hand_written: number; min_hand_written: number; ai_unlocked: boolean };

export function Synthetic() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const q = useQuery({ queryKey: ["synthetic", pid], queryFn: () => api.get<State>(`/api/projects/${pid}/synthetic`) });
  const [dims, setDims] = useState<Dim[]>([]);
  const [grounding, setGrounding] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const [count, setCount] = useState(20);
  useEffect(() => {
    if (q.data) {
      setDims(q.data.dimensions);
      setGrounding(q.data.grounding);
    }
  }, [q.data]);
  const set = (d: State) => qc.setQueryData(["synthetic", pid], d);
  const onErr = (e: any) => setErr(e.message);
  const saveDims = useMutation({ mutationFn: () => api.put<State>(`/api/projects/${pid}/synthetic`, { dimensions: dims, grounding }), onSuccess: set, onError: onErr });
  const add = useMutation({
    mutationFn: () => api.post(`/api/projects/${pid}/synthetic/tuples`, { values: draft }),
    onSuccess: () => {
      setDraft({});
      qc.invalidateQueries({ queryKey: ["synthetic", pid] });
    },
    onError: onErr,
  });
  const patch = useMutation({ mutationFn: ({ id, b }: { id: number; b: any }) => api.patch(`/api/projects/${pid}/synthetic/tuples/${id}`, b), onSuccess: () => qc.invalidateQueries({ queryKey: ["synthetic", pid] }) });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/projects/${pid}/synthetic/tuples/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["synthetic", pid] }) });
  const propose = useMutation({ mutationFn: () => api.post<State>(`/api/projects/${pid}/synthetic/propose`, { count }), onSuccess: set, onError: onErr });
  const inputs = useMutation({ mutationFn: () => api.post<State>(`/api/projects/${pid}/synthetic/inputs`), onSuccess: set, onError: onErr });
  const s = q.data;
  if (!s) return null;
  const pending = s.tuples.filter((t) => t.status === "pending");
  const accepted = s.tuples.filter((t) => t.status === "accepted");
  const withMsg = accepted.filter((t) => t.user_message.trim()).length;

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-6">
      <PageHeader
        title="Synthetic inputs"
        sub="No real traces yet? Define dimensions, write at least 20 combinations by hand, and let AI propose more. A second, separate step turns each combination into a natural user message. Only inputs are generated — never expected outputs."
        right={<Link to={`/p/${pid}/traces`} className="btn-ghost">← Get traces</Link>}
      />
      <Notice tone="warn">
        Synthetic data is unreliable for specialised or high-stakes domains. Compare what you find here with real traces as soon as you have them.
      </Notice>
      {err && <div className="mt-2"><Notice tone="danger">{err}</Notice></div>}

      <div className="mt-5 grid grid-cols-2 gap-5">
        <div className="card p-4">
          <div className="h2 mb-2"><Term tip="Each dimension is one axis of variation. A tuple picks one value per dimension, e.g. (tour booking, asks for a human, terse).">Dimensions</Term></div>
          <div className="space-y-2">
            {dims.map((d, i) => (
              <div key={i} className="flex gap-2">
                <input className="input w-32" value={d.name} onChange={(e) => setDims(dims.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <input className="input" value={d.values.join(", ")} placeholder="values, comma separated" onChange={(e) => setDims(dims.map((x, j) => (j === i ? { ...x, values: e.target.value.split(",").map((v) => v.trimStart()) } : x)))} />
                <button className="btn-quiet btn-sm" onClick={() => setDims(dims.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <button className="btn-ghost btn-sm" onClick={() => setDims([...dims, { name: "", values: [] }])}>+ Dimension</button>
          </div>
        </div>
        <div className="card p-4">
          <div className="h2 mb-2">Grounding</div>
          <textarea className="input min-h-[120px] font-mono text-xs" value={grounding} onChange={(e) => setGrounding(e.target.value)}
            placeholder="Paste real constraints and sample records — real unit IDs, availability windows, business rules — so generated inputs trigger the intended scenario." />
          <button className="btn-primary btn-sm mt-2" onClick={() => saveDims.mutate()}>Save dimensions and grounding</button>
        </div>
      </div>

      <div className="mt-6">
        <div className="mb-2 flex items-center gap-3">
          <div className="h2">Tuples</div>
          <span className={`chip ${s.ai_unlocked ? "border-pass-500/40 text-pass-400" : ""}`}>{s.hand_written}/{s.min_hand_written} written by hand</span>
          <span className="text-xs text-mist-400">{accepted.length} accepted · {pending.length} AI proposals to review · {withMsg} with a message</span>
        </div>
        <div className="card flex flex-wrap items-end gap-2 p-3">
          {(q.data?.dimensions ?? []).map((d) => (
            <div key={d.name}>
              <label className="label">{d.name}</label>
              <input className="input h-8 w-52" list={`dl-${d.name}`} value={draft[d.name] ?? ""} onChange={(e) => setDraft({ ...draft, [d.name]: e.target.value })} />
              <datalist id={`dl-${d.name}`}>{d.values.map((v) => <option key={v} value={v} />)}</datalist>
            </div>
          ))}
          <button className="btn-primary" disabled={!Object.values(draft).some((v) => v.trim())} onClick={() => add.mutate()}>Add tuple</button>
          <div className="ml-auto flex items-end gap-2">
            <input className="input h-8 w-16" type="number" min={1} max={100} value={count} onChange={(e) => setCount(Number(e.target.value))} />
            <button className="btn-ghost" disabled={!s.ai_unlocked || propose.isPending} onClick={() => { setErr(""); propose.mutate(); }} title={s.ai_unlocked ? "" : `Write ${s.min_hand_written} by hand first`}>
              {propose.isPending ? "Proposing…" : "✦ Step 1: propose more tuples"}
            </button>
            <button className="btn-ghost" disabled={!s.ai_unlocked || inputs.isPending || withMsg === accepted.length} onClick={() => { setErr(""); inputs.mutate(); }}>
              {inputs.isPending ? "Writing…" : "✦ Step 2: write user messages"}
            </button>
          </div>
        </div>
        <div className="mt-3 overflow-hidden rounded-lg border border-ink-700">
          <table className="tbl">
            <thead>
              <tr>{(q.data?.dimensions ?? []).map((d) => <th key={d.name}>{d.name}</th>)}<th>User message</th><th className="w-40" /></tr>
            </thead>
            <tbody>
              {[...pending, ...accepted, ...s.tuples.filter((t) => t.status === "rejected")].map((t) => (
                <tr key={t.id} className={t.status === "rejected" ? "opacity-40" : ""}>
                  {(q.data?.dimensions ?? []).map((d) => <td key={d.name} className="text-xs text-mist-300">{t.values[d.name] ?? "—"}</td>)}
                  <td>
                    <textarea
                      className="input min-h-[34px] text-xs"
                      defaultValue={t.user_message}
                      placeholder={t.status === "accepted" ? "Write it yourself, or use step 2" : ""}
                      onBlur={(e) => e.target.value !== t.user_message && patch.mutate({ id: t.id, b: { user_message: e.target.value } })}
                    />
                  </td>
                  <td className="text-right">
                    {t.status === "pending" ? (
                      <>
                        <button className="btn-primary btn-sm" onClick={() => patch.mutate({ id: t.id, b: { status: "accepted" } })}>Accept</button>
                        <button className="btn-quiet btn-sm" onClick={() => patch.mutate({ id: t.id, b: { status: "rejected" } })}>Reject</button>
                      </>
                    ) : (
                      <span className="text-xxs text-mist-500">{t.source === "ai" ? "✦ AI" : "by hand"} · {t.status} <button className="ml-1 text-mist-400 hover:text-fail-400" onClick={() => del.mutate(t.id)}>✕</button></span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card mt-6 p-4">
        <div className="h2">Run them through your real system</div>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-[13px] text-mist-300">
          <li>Export the {withMsg} inputs: <a className="text-accent-400 underline" href={`/api/projects/${pid}/synthetic/export?format=jsonl`}>JSONL</a> or <a className="text-accent-400 underline" href={`/api/projects/${pid}/synthetic/export?format=csv`}>CSV</a>. Each row keeps its id and tuple.</li>
          <li>Send each input to {project.data?.name ?? "your product"} and log the full traces. Keep the <code className="font-mono">tuple</code> field on each record.</li>
          <li>Import the traces on <Link className="text-accent-400 underline" to={`/p/${pid}/traces`}>Get traces</Link> with "tag them as synthetic" ticked. They stay filterable as synthetic everywhere.</li>
        </ol>
      </div>
    </div>
  );
}
