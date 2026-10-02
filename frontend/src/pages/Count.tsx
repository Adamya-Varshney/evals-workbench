import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, type BatchSummary, type Facet } from "../api";
import { TracePreview } from "../components/TracePreview";
import { Empty, Notice, PageHeader, pct, usePid, useProject, useStatus } from "../components/ui";
import { orderModes, useModes, type FM } from "./Group";

type Row = {
  id: number;
  name: string;
  parent_id: number | null;
  is_none_bucket: boolean;
  severity: string;
  impact_note: string;
  count: number;
  share_reviewed: number | null;
  share_failing: number | null;
  by_facet: Record<string, number>;
};
type CountData = {
  rows: Row[];
  n_reviewed: number;
  n_failing: number;
  facet: string | null;
  facet_values: string[];
  facet_reviewed: Record<string, number>;
  facet_failing: Record<string, number>;
  top3_share: number | null;
  top3_names: string[];
  n_label_instances: number;
};
type DrillRow = { review_id: number; trace_id: number; external_id: string; channel: string; verdict: string; note: string; modes: string[] };

export const SEVERITY: Record<string, { icon: string; label: string; cls: string }> = {
  low: { icon: "▽", label: "Low", cls: "text-mist-300" },
  high: { icon: "▲", label: "High", cls: "text-warn-400" },
  catastrophic: { icon: "✸", label: "Catastrophic", cls: "text-fail-400" },
};

export function Count() {
  const pid = usePid();
  const project = useProject(pid);
  const status = useStatus(pid);
  const [facet, setFacet] = useState("");
  const [batch, setBatch] = useState("");
  const facets = useQuery({ queryKey: ["facets", pid], queryFn: () => api.get<Facet[]>(`/api/projects/${pid}/facets`) });
  const batches = useQuery({ queryKey: ["batches", pid], queryFn: () => api.get<BatchSummary[]>(`/api/projects/${pid}/batches`) });
  const q = useQuery({
    queryKey: ["count", pid, facet, batch],
    queryFn: () => api.get<CountData>(`/api/projects/${pid}/count?${new URLSearchParams({ ...(facet ? { facet } : {}), ...(batch ? { batch_id: batch } : {}) })}`),
  });
  const [drill, setDrill] = useState<{ fid?: number; value?: string; title: string } | null>(null);
  const stage = status.data?.stages.find((s) => s.key === "count");
  if (stage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <PageHeader title="Count and prioritise" />
        <Notice>{stage.unlock} <Link to={`/p/${pid}/group`} className="underline">Go to Group failures →</Link></Notice>
      </div>
    );
  const d = q.data;
  const ordered = d ? orderRows(d.rows) : [];
  const tops = ordered.filter((r) => !r.parent_id && !r.is_none_bucket);
  const chart = [...tops].sort((a, b) => b.count - a.count);
  const catFacets = (facets.data ?? []).filter((f) => f.kind === "category").map((f) => f.key);

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      <PageHeader
        title="Count and prioritise"
        sub="The frequency table turns “there are errors somewhere” into “this is the biggest problem”. Then decide what matters most — that is your call, not a formula."
        right={
          <>
            <label className="text-xs text-mist-400">Pivot by</label>
            <select className="input h-8 w-44 py-0" value={facet} onChange={(e) => setFacet(e.target.value)}>
              <option value="">— none —</option>
              {catFacets.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <select className="input h-8 w-48 py-0" value={batch} onChange={(e) => setBatch(e.target.value)}>
              <option value="">All reviewed traces</option>
              {batches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </>
        }
      />
      {!d ? null : !tops.length ? (
        <Empty>No failure modes have labels yet.</Empty>
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_420px] gap-5">
            <div className="card p-4">
              <div className="flex items-baseline justify-between">
                <div className="h2">Failure modes by frequency</div>
                <div className="text-xs text-mist-400">traces with the failure · n = {d.n_reviewed} reviewed</div>
              </div>
              {d.top3_share !== null && (
                <p className="mt-1 text-[13px] text-mist-200" data-testid="top3">
                  The top three modes ({d.top3_names.join(", ")}) account for <b>{pct(d.top3_share)}</b> of the {d.n_label_instances} labelled failures.
                </p>
              )}
              <div style={{ height: Math.max(160, chart.length * 34 + 20) }} className="mt-3">
                <ResponsiveContainer>
                  <BarChart data={chart} layout="vertical" margin={{ left: 8, right: 48, top: 0, bottom: 0 }} barCategoryGap={6}>
                    <XAxis type="number" hide />
                    <YAxis type="category" dataKey="name" width={240} tickLine={false} axisLine={false} tick={{ fill: "rgb(var(--mist-300))", fontSize: 12 }} />
                    <Tooltip
                      cursor={{ fill: "rgb(var(--ink-800))" }}
                      content={({ active, payload }) =>
                        active && payload?.[0] ? (
                          <div className="rounded-md border border-ink-700 bg-ink-950 px-2.5 py-1.5 text-xs shadow-lg">
                            <div className="font-medium text-mist-50">{(payload[0].payload as Row).name}</div>
                            <div className="text-mist-300">{(payload[0].payload as Row).count} traces · {pct((payload[0].payload as Row).share_reviewed, 1)} of reviewed · {pct((payload[0].payload as Row).share_failing, 1)} of failing</div>
                          </div>
                        ) : null
                      }
                    />
                    <Bar dataKey="count" radius={[0, 4, 4, 0]} maxBarSize={22} onClick={(r: any) => setDrill({ fid: r.id, title: r.name })} className="cursor-pointer">
                      {chart.map((r) => <Cell key={r.id} fill="rgb(var(--accent-400))" />)}
                      <LabelList dataKey="count" position="right" style={{ fill: "rgb(var(--mist-300))", fontSize: 12 }} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <Prioritise pid={pid} counts={Object.fromEntries(d.rows.map((r) => [r.id, r.count]))} />
          </div>

          <div className="mt-5 overflow-x-auto rounded-lg border border-ink-700">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Failure mode</th>
                  <th className="text-right">Traces</th>
                  <th className="text-right" title="Denominator: all reviewed traces">% of reviewed <span className="normal-case text-mist-500">(n={d.n_reviewed})</span></th>
                  <th className="text-right" title="Denominator: traces you marked Fail">% of failing <span className="normal-case text-mist-500">(n={d.n_failing})</span></th>
                  {d.facet && d.facet_values.map((v) => (
                    <th key={v} className="text-right" title={`${d.facet} = ${v}`}>{v} <span className="normal-case text-mist-500">(n={d.facet_reviewed[v]})</span></th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ordered.map((r) => (
                  <tr key={r.id}>
                    <td className={r.parent_id ? "pl-8 text-mist-300" : r.is_none_bucket ? "text-mist-400" : "font-medium text-mist-50"}>
                      {r.parent_id ? "↳ " : ""}{r.name}
                      {r.severity && <span className={`ml-2 text-xs ${SEVERITY[r.severity].cls}`}>{SEVERITY[r.severity].icon} {SEVERITY[r.severity].label}</span>}
                    </td>
                    <Cell2 v={r.count} onClick={() => setDrill({ fid: r.id, title: r.name })} />
                    <td className="text-right tabular-nums text-mist-300">{pct(r.share_reviewed, 1)}</td>
                    <td className="text-right tabular-nums text-mist-300">{pct(r.share_failing, 1)}</td>
                    {d.facet && d.facet_values.map((v) => (
                      <Cell2 key={v} v={r.by_facet[v] ?? 0} sub={d.facet_reviewed[v] ? pct((r.by_facet[v] ?? 0) / d.facet_reviewed[v]) : ""} onClick={() => setDrill({ fid: r.id, value: v, title: `${r.name} · ${d.facet} = ${v}` })} />
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-mist-500">Counts are traces. A trace can carry several failure modes, so columns can sum to more than the number of failing traces. Click any number to see the traces behind it.</p>
        </>
      )}
      {drill && <Drill pid={pid} facet={d?.facet ?? undefined} drill={drill} product={project.data?.name} onClose={() => setDrill(null)} />}
    </div>
  );
}

function Cell2({ v, sub, onClick }: { v: number; sub?: string; onClick: () => void }) {
  return (
    <td className="text-right tabular-nums">
      {v ? (
        <button className="text-accent-400 hover:underline" onClick={onClick}>{v}{sub ? <span className="ml-1 text-xs text-mist-500">{sub}</span> : null}</button>
      ) : (
        <span className="text-mist-500">0</span>
      )}
    </td>
  );
}

function orderRows(rows: Row[]): Row[] {
  const tops = rows.filter((r) => !r.parent_id && !r.is_none_bucket);
  const out: Row[] = [];
  for (const t of tops) {
    out.push(t);
    out.push(...rows.filter((r) => r.parent_id === t.id));
  }
  out.push(...rows.filter((r) => r.is_none_bucket && r.count));
  return out;
}

function Drill({ pid, facet, drill, product, onClose }: { pid: number; facet?: string; drill: { fid?: number; value?: string; title: string }; product?: string; onClose: () => void }) {
  const params = new URLSearchParams({ ...(drill.fid ? { failure_mode_id: String(drill.fid) } : {}), ...(drill.value !== undefined && facet ? { facet, value: drill.value } : {}) });
  const q = useQuery({ queryKey: ["drill", pid, params.toString()], queryFn: () => api.get<DrillRow[]>(`/api/projects/${pid}/count/traces?${params}`) });
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && !open && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, open]);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-[640px] flex-col border-l border-ink-700 bg-ink-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
          <div>
            <div className="h2">{drill.title}</div>
            <div className="text-xs text-mist-400">{q.data?.length ?? "…"} traces</div>
          </div>
          <button className="btn-quiet btn-sm" onClick={onClose}>Close <span className="kbd">Esc</span></button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <table className="tbl">
            <tbody>
              {q.data?.map((r) => (
                <tr key={r.review_id} className="cursor-pointer" onClick={() => setOpen(r.trace_id)}>
                  <td className="w-32"><div className="font-mono text-xs text-accent-400">{r.external_id}</div><div className="text-xxs text-mist-500">{r.channel}</div></td>
                  <td className="text-mist-100">{r.note}<div className="mt-1 flex flex-wrap gap-1">{r.modes.map((m) => <span key={m} className="chip h-5 text-xxs">{m}</span>)}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {open && <TracePreview pid={pid} traceId={open} product={product} onClose={() => setOpen(null)} />}
    </div>
  );
}

function Prioritise({ pid, counts }: { pid: number; counts: Record<number, number> }) {
  const qc = useQueryClient();
  const modesQ = useModes(pid);
  const tops = useMemo(() => orderModes(modesQ.data ?? []).filter((m) => !m.parent_id && !m.is_none_bucket), [modesQ.data]);
  const [order, setOrder] = useState<FM[]>([]);
  useEffect(() => setOrder(tops), [tops]);
  const [dragging, setDragging] = useState<number | null>(null);
  const refresh = () => {
    for (const k of ["modes", "count", "status"]) qc.invalidateQueries({ queryKey: [k, pid] });
  };
  const reorder = useMutation({ mutationFn: (ids: number[]) => api.post(`/api/projects/${pid}/failure_modes/reorder`, { ids }), onSuccess: refresh });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: number; body: Record<string, string> }) => api.patch(`/api/projects/${pid}/failure_modes/${id}`, body), onSuccess: refresh });
  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= order.length) return;
    const next = [...order];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setOrder(next);
    reorder.mutate(next.map((m) => m.id));
  };
  return (
    <div className="card p-4">
      <div className="h2">Priority</div>
      <p className="mt-0.5 text-xs text-mist-400">Drag to order. Set severity and a one-line impact. No score is computed: a rare catastrophic failure can outrank a frequent cosmetic one.</p>
      <ol className="mt-3 space-y-1.5">
        {order.map((m, i) => (
          <li
            key={m.id}
            draggable
            onDragStart={() => setDragging(i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragging !== null) move(dragging, i);
              setDragging(null);
            }}
            className={`rounded-md border bg-ink-950 p-2 ${dragging === i ? "border-accent-400 opacity-60" : "border-ink-700"}`}
            data-testid="priority-row"
          >
            <div className="flex items-center gap-2">
              <span className="cursor-grab select-none text-mist-500" title="Drag to reorder">⠿</span>
              <span className="w-4 text-xs tabular-nums text-mist-500">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate font-medium text-mist-50">{m.name}</span>
              <span className="text-xs tabular-nums text-mist-400">{counts[m.id] ?? 0}</span>
              <span className="flex flex-col">
                <button className="text-[9px] leading-[9px] text-mist-500 hover:text-mist-100" onClick={() => move(i, i - 1)} aria-label="Move up">▲</button>
                <button className="text-[9px] leading-[9px] text-mist-500 hover:text-mist-100" onClick={() => move(i, i + 1)} aria-label="Move down">▼</button>
              </span>
            </div>
            <div className="mt-1.5 flex items-center gap-1 pl-10">
              {Object.entries(SEVERITY).map(([k, s]) => (
                <button
                  key={k}
                  onClick={() => patch.mutate({ id: m.id, body: { severity: m.severity === k ? "" : k } })}
                  className={`chip h-6 ${m.severity === k ? "border-mist-300 bg-ink-800 font-medium" : ""} ${s.cls}`}
                  aria-pressed={m.severity === k}
                >
                  {s.icon} {s.label}
                </button>
              ))}
            </div>
            <input
              className="input mt-1.5 h-7 py-0 pl-2 text-xs"
              placeholder="Impact, e.g. prospects see raw asterisks; looks broken"
              defaultValue={m.impact_note}
              onBlur={(e) => e.target.value !== m.impact_note && patch.mutate({ id: m.id, body: { impact_note: e.target.value } })}
            />
          </li>
        ))}
      </ol>
    </div>
  );
}
