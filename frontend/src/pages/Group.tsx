import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { TracePreview } from "../components/TracePreview";
import { Empty, Notice, Spinner, Term, usePid, useProject, useStatus } from "../components/ui";

export type FM = {
  id: number;
  name: string;
  definition: string;
  counts_as: string;
  does_not_count_as: string;
  parent_id: number | null;
  severity: string;
  impact_note: string;
  decision: string;
  decision_note: string;
  rank: number;
  is_none_bucket: boolean;
  version: number;
  n_labels: number;
  n_recheck: number;
  warnings: string[];
  history_len: number;
};
type Label = { failure_mode_id: number; source: string; needs_recheck: boolean };
type NoteRow = {
  review_id: number;
  trace_id: number;
  external_id: string;
  channel: string;
  verdict: string;
  note: string;
  labels: Label[];
  suggestion: { id: number; failure_mode_ids: number[]; rationale: string } | null;
};
type Summary = {
  notes: number;
  failing_notes: number;
  unassigned: number;
  pending_suggestions: number;
  in_none: number;
  recheck: number;
  confirmed_individually: number;
  bulk_unlocked: boolean;
  none_id: number | null;
  ai: { enabled: boolean; reviewed: number; threshold: number; unlocked: boolean; reason: string | null };
  colleague_test: string;
};
type Proposal = { id: number; name: string; definition: string; examples: { review_id: number; note: string }[]; warnings: string[] };

const isTyping = (el: EventTarget | null) => el instanceof HTMLElement && (["TEXTAREA", "INPUT", "SELECT"].includes(el.tagName) || el.isContentEditable);

/** Modes in display order: each top-level mode followed by its sub-categories; None last. */
export function orderModes(modes: FM[]): FM[] {
  const tops = modes.filter((m) => !m.parent_id && !m.is_none_bucket);
  const out: FM[] = [];
  for (const t of tops) {
    out.push(t);
    out.push(...modes.filter((m) => m.parent_id === t.id));
  }
  out.push(...modes.filter((m) => m.parent_id && !tops.some((t) => t.id === m.parent_id)));
  out.push(...modes.filter((m) => m.is_none_bucket));
  return out;
}

export function useModes(pid: number) {
  return useQuery({ queryKey: ["modes", pid], queryFn: () => api.get<FM[]>(`/api/projects/${pid}/failure_modes`) });
}

export function Group() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const status = useStatus(pid);
  const modesQ = useModes(pid);
  const notesQ = useQuery({ queryKey: ["notes", pid], queryFn: () => api.get<NoteRow[]>(`/api/projects/${pid}/group/notes`) });
  const sumQ = useQuery({ queryKey: ["gsum", pid], queryFn: () => api.get<Summary>(`/api/projects/${pid}/group/summary`) });
  const propQ = useQuery({ queryKey: ["proposals", pid], queryFn: () => api.get<Proposal[]>(`/api/projects/${pid}/group/proposals`) });
  const refresh = () => {
    for (const k of ["modes", "notes", "gsum", "proposals", "status", "count"]) qc.invalidateQueries({ queryKey: [k, pid] });
  };
  const [err, setErr] = useState("");
  const propose = useMutation({ mutationFn: () => api.post(`/api/projects/${pid}/group/propose`), onSuccess: refresh, onError: (e: any) => setErr(e.message) });
  const suggest = useMutation({
    mutationFn: (scope: string) => api.post(`/api/projects/${pid}/group/suggest`, { scope }),
    onSuccess: () => {
      refresh();
      setFilter("suggested");
    },
    onError: (e: any) => setErr(e.message),
  });

  const modes = useMemo(() => orderModes(modesQ.data ?? []), [modesQ.data]);
  const realModes = modes.filter((m) => !m.is_none_bucket);
  const keyModes = realModes.slice(0, 9);
  const byId = useMemo(() => Object.fromEntries(modes.map((m) => [m.id, m])), [modes]);
  const sum = sumQ.data;

  const [filter, setFilter] = useState<"all" | "unassigned" | "suggested" | "none" | "recheck">("all");
  const rows = useMemo(() => {
    const all = notesQ.data ?? [];
    return all.filter((r) => {
      if (filter === "unassigned") return r.verdict === "fail" && !r.labels.length && !r.suggestion;
      if (filter === "suggested") return !!r.suggestion;
      if (filter === "none") return r.labels.some((l) => l.failure_mode_id === sum?.none_id);
      if (filter === "recheck") return r.labels.some((l) => l.needs_recheck);
      return true;
    });
  }, [notesQ.data, filter, sum?.none_id]);

  const [sel, setSel] = useState(0);
  const [override, setOverride] = useState<Record<number, number[]>>({});
  const [preview, setPreview] = useState<number | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const [openMode, setOpenMode] = useState<number | "new" | null>(null);
  useEffect(() => setSel((s) => Math.min(s, Math.max(0, rows.length - 1))), [rows.length]);

  const accept = useMutation({
    mutationFn: ({ sid, ids }: { sid: number; ids?: number[] }) => api.post(`/api/projects/${pid}/group/suggestions/${sid}/accept`, ids ? { failure_mode_ids: ids } : {}),
    onSuccess: refresh,
    onError: (e: any) => setErr(e.message),
  });
  const reject = useMutation({ mutationFn: (sid: number) => api.post(`/api/projects/${pid}/group/suggestions/${sid}/reject`), onSuccess: refresh });
  const setLabels = useMutation({
    mutationFn: ({ rid, ids }: { rid: number; ids: number[] }) => api.put(`/api/projects/${pid}/group/labels/${rid}`, { failure_mode_ids: ids }),
    onSuccess: refresh,
  });
  const bulk = useMutation({
    mutationFn: (fid: number) => api.post<{ accepted: number }>(`/api/projects/${pid}/group/suggestions/bulk_accept`, { failure_mode_id: fid }),
    onSuccess: refresh,
    onError: (e: any) => setErr(e.message),
  });

  const toggleIn = (ids: number[], id: number) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids.filter((x) => x !== sum?.none_id), id]);
  const actOnDigit = (row: NoteRow, fid: number) => {
    if (row.suggestion) {
      const cur = override[row.review_id] ?? row.suggestion.failure_mode_ids;
      setOverride({ ...override, [row.review_id]: toggleIn(cur, fid) });
    } else {
      setLabels.mutate({ rid: row.review_id, ids: toggleIn(row.labels.map((l) => l.failure_mode_id), fid) });
    }
  };
  const acceptRow = (row: NoteRow) => {
    if (row.suggestion) accept.mutate({ sid: row.suggestion.id, ids: override[row.review_id] });
    else if (row.labels.some((l) => l.needs_recheck)) setLabels.mutate({ rid: row.review_id, ids: row.labels.map((l) => l.failure_mode_id) });
  };

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (isTyping(e.target) || preview || openMode || e.ctrlKey || e.metaKey || e.altKey) return;
      const row = rows[sel];
      const k = e.key;
      if (k === "j" || k === "ArrowDown") setSel((s) => Math.min(rows.length - 1, s + 1));
      else if (k === "k" || k === "ArrowUp") setSel((s) => Math.max(0, s - 1));
      else if (k === "Enter" && row) acceptRow(row);
      else if (/^[1-9]$/.test(k) && row && keyModes[Number(k) - 1]) actOnDigit(row, keyModes[Number(k) - 1].id);
      else if (k === "0" && row && sum?.none_id) actOnDigit(row, sum.none_id);
      else if (k === "x" && row?.suggestion) reject.mutate(row.suggestion.id);
      else if (k === "o" && row) setPreview(row.trace_id);
      else if (k === "e" && row) setEditing(row.review_id);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });
  useEffect(() => {
    document.querySelector(`[data-row="${sel}"]`)?.scrollIntoView({ block: "nearest" });
  }, [sel]);

  const groupStage = status.data?.stages.find((s) => s.key === "group");
  if (groupStage?.status === "locked")
    return (
      <div className="mx-auto max-w-5xl px-6 py-6">
        <h1 className="h1">Group failures</h1>
        <div className="mt-4"><Notice>{groupStage.unlock} <Link to={`/p/${pid}/review`} className="underline">Go to Review traces →</Link></Notice></div>
      </div>
    );

  const ai = sum?.ai;
  const tabs: [typeof filter, string, number | undefined][] = [
    ["all", "All notes", sum?.notes],
    ["unassigned", "Unassigned", sum?.unassigned],
    ["suggested", "AI suggestions to confirm", sum?.pending_suggestions],
    ["none", "None of the above", sum?.in_none],
    ["recheck", "Needs re-check", sum?.recheck],
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink-700 px-6 pb-0 pt-5">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="h1"><Term tip="Also called axial coding: grouping your open codes (notes) into a small set of failure modes.">Group failures</Term></h1>
            <p className="mt-1 max-w-3xl text-mist-400">Turn your notes into a short list of specific failure modes. Each needs a definition a colleague could use to label traces on their own.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {ai && !ai.unlocked && <span className="text-xs text-mist-400">🔒 {ai.reason}</span>}
            <button className="btn-ghost" disabled={!ai?.unlocked || propose.isPending} onClick={() => { setErr(""); propose.mutate(); }} title="Sends your failing notes to the model; nothing is created until you accept">
              {propose.isPending ? "Proposing…" : "✦ Propose categories"}
            </button>
            <button className="btn-primary" disabled={!ai?.unlocked || !realModes.length || suggest.isPending} onClick={() => { setErr(""); suggest.mutate("unassigned"); }}>
              {suggest.isPending ? "Suggesting…" : "✦ Suggest assignments"}
            </button>
          </div>
        </div>
        {err && <div className="mt-3"><Notice tone="danger">{err}</Notice></div>}
        <div className="mt-3 flex gap-5">
          {tabs.map(([k, label, n]) => (
            <button key={k} className={`tab ${filter === k ? "tab-active" : ""}`} onClick={() => { setFilter(k); setSel(0); }}>
              {label} {n !== undefined && <span className={`rounded px-1 text-xxs ${n && k !== "all" ? "bg-accent-400/15 text-accent-400" : "bg-ink-800 text-mist-400"}`}>{n}</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-h-0 overflow-y-auto">
          {filter === "suggested" && sum && (
            <div className="flex items-center gap-3 border-b border-ink-700 bg-ink-900 px-6 py-2 text-xs text-mist-300">
              <span><span className="kbd">J</span>/<span className="kbd">K</span> move · <span className="kbd">Enter</span> accept · <span className="kbd">1</span>–<span className="kbd">9</span> change modes · <span className="kbd">0</span> None of the above · <span className="kbd">X</span> reject · <span className="kbd">O</span> open trace</span>
              <span className="ml-auto">Confirmed one by one: <b>{sum.confirmed_individually}</b>/10 {sum.bulk_unlocked ? "· bulk accept unlocked" : "before bulk accept"}</span>
            </div>
          )}
          {filter === "none" && !!sum?.in_none && (
            <div className="border-b border-ink-700 bg-warn-900/40 px-6 py-2 text-xs text-warn-400">
              These notes don't fit any failure mode yet. For each, consider a new category ("Create category") or move it into an existing one with number keys.
            </div>
          )}
          {!notesQ.data ? (
            <div className="p-6"><Spinner label="Loading notes…" /></div>
          ) : !rows.length ? (
            <div className="p-6"><Empty>Nothing here.</Empty></div>
          ) : (
            <table className="tbl">
              <thead>
                <tr><th className="w-36">Trace</th><th>Note (your open code)</th><th className="w-[38%]">Failure modes</th></tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <NoteRowView
                    key={r.review_id}
                    pid={pid}
                    i={i}
                    r={r}
                    active={i === sel}
                    byId={byId}
                    keyModes={keyModes}
                    noneId={sum?.none_id ?? null}
                    override={override[r.review_id]}
                    editing={editing === r.review_id}
                    onSelect={() => setSel(i)}
                    onOpen={() => setPreview(r.trace_id)}
                    onEditDone={() => { setEditing(null); refresh(); }}
                    onAccept={() => acceptRow(r)}
                    onReject={() => r.suggestion && reject.mutate(r.suggestion.id)}
                    onToggle={(fid) => actOnDigit(r, fid)}
                    onCreateFrom={() => setOpenMode("new")}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        <aside className="min-h-0 overflow-y-auto border-l border-ink-700 bg-ink-900">
          {!!propQ.data?.length && <Proposals pid={pid} proposals={propQ.data} onDone={refresh} />}
          <div className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="h2">Failure modes</div>
              <button className="btn-ghost btn-sm" onClick={() => setOpenMode("new")}>+ Add</button>
            </div>
            <p className="mb-3 text-xs text-mist-400">{sum?.colleague_test ?? "Could a colleague label traces using only the name and its definition?"}</p>
            {!realModes.length && <Empty>No failure modes yet. Draft some from your notes, or click ✦ Propose categories.</Empty>}
            <div className="space-y-1.5">
              {modes.map((m) => {
                const k = keyModes.findIndex((x) => x.id === m.id);
                return (
                  <button key={m.id} onClick={() => setOpenMode(m.id)} className={`block w-full rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-left hover:border-ink-500 ${m.parent_id ? "ml-5 w-[calc(100%-1.25rem)]" : ""}`}>
                    <div className="flex items-center gap-2">
                      {m.is_none_bucket ? <span className="kbd">0</span> : k >= 0 ? <span className="kbd">{k + 1}</span> : <span className="w-[18px]" />}
                      <span className={`truncate font-medium ${m.is_none_bucket ? "text-mist-400" : "text-mist-50"}`}>{m.name}</span>
                      <span className="ml-auto tabular-nums text-xs text-mist-400">{m.n_labels}</span>
                    </div>
                    {m.definition && <div className="mt-0.5 line-clamp-2 pl-[26px] text-xs text-mist-400">{m.definition}</div>}
                    <div className="mt-1 flex flex-wrap gap-1 pl-[26px]">
                      {m.warnings.length > 0 && <span className="chip h-5 border-warn-400/40 text-warn-400" title={m.warnings.join("\n")}>! {m.warnings.length} to fix</span>}
                      {m.n_recheck > 0 && <span className="chip h-5 border-accent-400/40 text-accent-400">↻ {m.n_recheck} to re-check</span>}
                      {sum?.bulk_unlocked && !m.is_none_bucket && (notesQ.data ?? []).some((r) => r.suggestion && r.suggestion.failure_mode_ids.length === 1 && r.suggestion.failure_mode_ids[0] === m.id) && (
                        <span
                          role="button"
                          className="chip h-5 hover:border-accent-400"
                          onClick={(e) => {
                            e.stopPropagation();
                            bulk.mutate(m.id);
                          }}
                        >
                          ✓ Accept all suggested here
                        </span>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </aside>
      </div>

      {preview && <TracePreview pid={pid} traceId={preview} product={project.data?.name} onClose={() => setPreview(null)} />}
      {openMode !== null && (
        <ModeEditor
          pid={pid}
          mode={openMode === "new" ? null : byId[openMode] ?? null}
          modes={modes}
          fromReviewId={openMode === "new" && filter === "none" ? rows[sel]?.review_id : undefined}
          fromNote={openMode === "new" && filter === "none" ? rows[sel]?.note : undefined}
          onClose={() => setOpenMode(null)}
          onSaved={refresh}
        />
      )}
    </div>
  );
}

function NoteRowView(p: {
  pid: number;
  i: number;
  r: NoteRow;
  active: boolean;
  byId: Record<number, FM>;
  keyModes: FM[];
  noneId: number | null;
  override?: number[];
  editing: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onEditDone: () => void;
  onAccept: () => void;
  onReject: () => void;
  onToggle: (fid: number) => void;
  onCreateFrom: () => void;
}) {
  const { r } = p;
  const [draft, setDraft] = useState(r.note);
  useEffect(() => setDraft(r.note), [r.note, p.editing]);
  const save = async () => {
    await api.put(`/api/projects/${p.pid}/reviews/${r.trace_id}`, { note: draft, fields: ["note"] });
    p.onEditDone();
  };
  const sugIds = r.suggestion ? p.override ?? r.suggestion.failure_mode_ids : null;
  const inNone = r.labels.some((l) => l.failure_mode_id === p.noneId);
  return (
    <tr data-row={p.i} onClick={p.onSelect} className={p.active ? "bg-accent-400/5 shadow-[inset_2px_0_0_rgb(var(--accent-400))]" : ""}>
      <td>
        <button className="font-mono text-xs text-accent-400 hover:underline" onClick={p.onOpen}>{r.external_id}</button>
        <div className="mt-0.5 flex gap-1 text-xxs text-mist-500"><span>{r.channel}</span>·<span className={r.verdict === "fail" ? "text-fail-400" : "text-pass-400"}>{r.verdict}</span></div>
      </td>
      <td className="text-[13px] text-mist-100">
        {p.editing ? (
          <div>
            <textarea autoFocus className="input min-h-[70px]" value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={(e) => {
              if (e.key === "Escape") p.onEditDone();
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) save();
            }} />
            <div className="mt-1 flex gap-2"><button className="btn-primary btn-sm" onClick={save}>Save</button><button className="btn-quiet btn-sm" onClick={p.onEditDone}>Cancel</button></div>
          </div>
        ) : (
          <span onDoubleClick={() => p.onSelect()} title="Press E to edit">{r.note || <span className="italic text-mist-500">no note</span>}</span>
        )}
      </td>
      <td>
        <div className="flex flex-wrap gap-1">
          {r.labels.map((l) => {
            const m = p.byId[l.failure_mode_id];
            return (
              <span key={l.failure_mode_id} className={`chip ${l.needs_recheck ? "border-accent-400/50" : ""} ${m?.is_none_bucket ? "text-mist-400" : "text-mist-100"}`} title={l.source === "ai_confirmed" ? "AI-suggested, confirmed by you" : "Assigned by you"}>
                {l.needs_recheck && "↻"} {m?.name ?? "?"} {l.source === "ai_confirmed" && <span className="text-mist-500">✦</span>}
              </span>
            );
          })}
        </div>
        {sugIds && (
          <div className="mt-1 rounded-md border border-dashed border-accent-400/50 bg-accent-400/5 p-2">
            <div className="mb-1 text-xxs font-medium uppercase tracking-wide text-accent-400">AI suggestion — confirm or change</div>
            <div className="flex flex-wrap gap-1">
              {sugIds.map((id) => <span key={id} className="chip border-accent-400/40 text-mist-100">{p.byId[id]?.name ?? "?"}</span>)}
            </div>
            <div className="mt-1 text-xs text-mist-400">{r.suggestion?.rationale}</div>
            <div className="mt-1.5 flex gap-1.5">
              <button className="btn-primary btn-sm" onClick={p.onAccept}>Accept <span className="kbd border-white/30 bg-transparent text-white">↵</span></button>
              <button className="btn-quiet btn-sm" onClick={p.onReject}>Reject <span className="kbd">X</span></button>
            </div>
          </div>
        )}
        {p.active && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {p.keyModes.map((m, i) => {
              const on = (sugIds ?? r.labels.map((l) => l.failure_mode_id)).includes(m.id);
              return (
                <button key={m.id} onClick={() => p.onToggle(m.id)} className={`chip h-5 text-xxs ${on ? "border-accent-400 text-accent-400" : ""}`}>
                  <span className="font-mono">{i + 1}</span> {m.name}
                </button>
              );
            })}
            {p.noneId && <button onClick={() => p.onToggle(p.noneId!)} className="chip h-5 text-xxs"><span className="font-mono">0</span> None of the above</button>}
            {inNone && <button onClick={p.onCreateFrom} className="chip h-5 border-warn-400/50 text-xxs text-warn-400">+ Create category from this note</button>}
            {r.labels.some((l) => l.needs_recheck) && !sugIds && <button onClick={p.onAccept} className="chip h-5 text-xxs">✓ Still correct <span className="kbd">↵</span></button>}
          </div>
        )}
      </td>
    </tr>
  );
}

function Proposals({ pid, proposals, onDone }: { pid: number; proposals: Proposal[]; onDone: () => void }) {
  return (
    <div className="border-b border-ink-700 bg-accent-400/5 p-4">
      <div className="h2">✦ Proposed categories</div>
      <p className="mb-3 mt-0.5 text-xs text-mist-400">A starting point only. Rewrite each into something specific and actionable before accepting.</p>
      <div className="space-y-2">
        {proposals.map((p) => <ProposalCard key={p.id} pid={pid} p={p} onDone={onDone} />)}
      </div>
    </div>
  );
}

function ProposalCard({ pid, p, onDone }: { pid: number; p: Proposal; onDone: () => void }) {
  const [name, setName] = useState(p.name);
  const [def, setDef] = useState(p.definition);
  const [open, setOpen] = useState(false);
  const accept = useMutation({ mutationFn: () => api.post(`/api/projects/${pid}/group/proposals/${p.id}/accept`, { name, definition: def }), onSuccess: onDone });
  const reject = useMutation({ mutationFn: () => api.post(`/api/projects/${pid}/group/proposals/${p.id}/reject`), onSuccess: onDone });
  return (
    <div className="rounded-md border border-ink-700 bg-ink-950 p-2.5">
      <input className="input mb-1 font-medium" value={name} onChange={(e) => setName(e.target.value)} />
      <textarea className="input min-h-[48px] text-xs" value={def} onChange={(e) => setDef(e.target.value)} />
      {p.warnings.length > 0 && name === p.name && <div className="mt-1 text-xs text-warn-400">! {p.warnings[0]}</div>}
      <button className="mt-1 text-xs text-mist-400 underline" onClick={() => setOpen(!open)}>{p.examples.length} example notes</button>
      {open && <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-mist-300">{p.examples.map((e) => <li key={e.review_id}>{e.note}</li>)}</ul>}
      <div className="mt-2 flex gap-1.5">
        <button className="btn-primary btn-sm" onClick={() => accept.mutate()}>Accept</button>
        <button className="btn-quiet btn-sm" onClick={() => reject.mutate()}>Reject</button>
      </div>
    </div>
  );
}

type Hist = { at: string; action: string; changes: Record<string, any>; by: string; version: number };

function ModeEditor({ pid, mode, modes, fromReviewId, fromNote, onClose, onSaved }: { pid: number; mode: FM | null; modes: FM[]; fromReviewId?: number; fromNote?: string; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    name: mode?.name ?? "",
    definition: mode?.definition ?? (fromNote ? `Seen in: "${fromNote}"` : ""),
    counts_as: mode?.counts_as ?? "",
    does_not_count_as: mode?.does_not_count_as ?? "",
    parent_id: mode?.parent_id ?? null,
  });
  const [err, setErr] = useState("");
  const [mergeTo, setMergeTo] = useState<number | "">("");
  const [splitText, setSplitText] = useState("");
  const [splitChildren, setSplitChildren] = useState(true);
  const hist = useQuery({ queryKey: ["mhist", mode?.id], queryFn: () => api.get<Hist[]>(`/api/projects/${pid}/failure_modes/${mode!.id}/history`), enabled: !!mode });
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const done = () => {
    onSaved();
    onClose();
  };
  const run = async (fn: () => Promise<unknown>) => {
    try {
      setErr("");
      await fn();
      done();
    } catch (e: any) {
      setErr(e.message);
    }
  };
  const save = () => run(() => (mode ? api.patch(`/api/projects/${pid}/failure_modes/${mode.id}`, f) : api.post(`/api/projects/${pid}/failure_modes`, { ...f, from_review_id: fromReviewId })));
  const parents = modes.filter((m) => !m.parent_id && !m.is_none_bucket && m.id !== mode?.id);
  const isNone = !!mode?.is_none_bucket;
  const defChanged = mode && (f.definition !== mode.definition || f.counts_as !== mode.counts_as || f.does_not_count_as !== mode.does_not_count_as);
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <div className="h-full w-[520px] overflow-y-auto border-l border-ink-700 bg-ink-950 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <div className="h2">{mode ? (isNone ? "None of the above" : "Edit failure mode") : "New failure mode"}</div>
          <span className="kbd">Esc</span>
        </div>
        {mode && mode.warnings.length > 0 && (
          <div className="mb-3"><Notice tone="warn"><ul className="list-disc pl-4">{mode.warnings.map((w) => <li key={w}>{w}</li>)}</ul></Notice></div>
        )}
        {!isNone && (
          <div className="space-y-3">
            <div>
              <label className="label">Name — the observable behaviour</label>
              <input className="input" autoFocus value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="e.g. Markdown sent over SMS" />
            </div>
            <div>
              <label className="label">Definition (one sentence)</label>
              <textarea className="input min-h-[60px]" value={f.definition} onChange={(e) => setF({ ...f, definition: e.target.value })} />
            </div>
            <div>
              <label className="label">Counts as</label>
              <textarea className="input min-h-[60px]" value={f.counts_as} onChange={(e) => setF({ ...f, counts_as: e.target.value })} placeholder="Concrete examples that belong here" />
            </div>
            <div>
              <label className="label">Does not count as</label>
              <textarea className="input min-h-[60px]" value={f.does_not_count_as} onChange={(e) => setF({ ...f, does_not_count_as: e.target.value })} placeholder="Near-misses that belong elsewhere" />
            </div>
            <div>
              <label className="label">Sub-category of (one level only)</label>
              <select className="input" value={f.parent_id ?? ""} onChange={(e) => setF({ ...f, parent_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">— top level —</option>
                {parents.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            </div>
            <div className="rounded-md border border-ink-700 bg-ink-900 p-2.5 text-xs text-mist-300">
              <b>Colleague test:</b> could someone who has never seen your notes label traces using only the name and definition above?
            </div>
            {defChanged && !!mode?.n_labels && <Notice tone="warn">Changing the definition flags this mode's {mode.n_labels} existing label(s) for re-check.</Notice>}
            {err && <Notice tone="danger">{err}</Notice>}
            <div className="flex gap-2">
              <button className="btn-primary" disabled={!f.name.trim()} onClick={save}>{mode ? "Save" : "Create"}</button>
              <button className="btn-quiet" onClick={onClose}>Cancel</button>
            </div>
          </div>
        )}
        {isNone && <p className="text-mist-300">{mode?.definition}</p>}

        {mode && !isNone && (
          <div className="mt-8 space-y-5 border-t border-ink-700 pt-5">
            <div>
              <div className="label">Merge into another mode</div>
              <div className="flex gap-2">
                <select className="input" value={mergeTo} onChange={(e) => setMergeTo(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Choose…</option>
                  {modes.filter((m) => m.id !== mode.id && !m.is_none_bucket).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                </select>
                <button className="btn-ghost" disabled={!mergeTo} onClick={() => run(() => api.post(`/api/projects/${pid}/failure_modes/merge`, { source_ids: [mode.id], target_id: mergeTo }))}>Merge</button>
              </div>
            </div>
            <div>
              <div className="label">Split into (one name per line)</div>
              <textarea className="input min-h-[60px]" value={splitText} onChange={(e) => setSplitText(e.target.value)} placeholder={"Bold markdown in SMS\nBulleted lists in SMS"} />
              <div className="mt-1 flex items-center gap-3">
                {!mode.parent_id && <label className="flex items-center gap-1.5 text-xs text-mist-300"><input type="checkbox" checked={splitChildren} onChange={(e) => setSplitChildren(e.target.checked)} /> as sub-categories</label>}
                <button className="btn-ghost btn-sm" disabled={splitText.split("\n").filter((x) => x.trim()).length < 2} onClick={() => run(() => api.post(`/api/projects/${pid}/failure_modes/${mode.id}/split`, { parts: splitText.split("\n").filter((x) => x.trim()).map((name) => ({ name })), as_children: splitChildren && !mode.parent_id }))}>Split</button>
              </div>
              <p className="mt-1 text-xs text-mist-400">Existing labels are flagged for re-check so you can move each note to the right part.</p>
            </div>
            <div>
              <button className="btn-ghost btn-sm text-fail-400" onClick={() => confirm(`Delete "${mode.name}"? Its ${mode.n_labels} label(s) are removed and those notes become unassigned.`) && run(() => api.del(`/api/projects/${pid}/failure_modes/${mode.id}`))}>Delete failure mode</button>
            </div>
            <div>
              <div className="label">History</div>
              <ol className="space-y-1.5 text-xs">
                {hist.data?.map((h, i) => (
                  <li key={i} className="border-l-2 border-ink-600 pl-2">
                    <div className="text-mist-400">{new Date(h.at).toLocaleString()} · {h.action} · v{h.version}{h.by ? ` · ${h.by}` : ""}</div>
                    {Object.entries(h.changes).map(([k, v]) => (
                      <div key={k} className="text-mist-300"><span className="text-mist-500">{k}:</span> {Array.isArray(v) ? <><s className="text-mist-500">{String(v[0] ?? "")}</s> → {String(v[1] ?? "")}</> : String(v)}</div>
                    ))}
                  </li>
                ))}
              </ol>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
