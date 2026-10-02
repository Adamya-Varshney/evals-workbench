import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type BatchSummary, type TraceView } from "../api";
import { TraceRenderer } from "../components/TraceRenderer";
import { TraceSteps } from "../components/TraceSteps";
import { Empty, Term, VerdictBadge, usePid, useProject } from "../components/ui";

type QItem = {
  id: number;
  pos: number;
  external_id: string;
  channel: string;
  n_turns: number;
  snippet: string;
  meta: Record<string, any>;
  reason: string;
  verdict: "pass" | "fail" | null;
  deferred: boolean;
  has_note: boolean;
  search: string;
};
type ReviewRec = { id: number; verdict: "pass" | "fail" | null; note: string; first_failure_event_id: number | null; deferred: boolean; seconds_spent: number; history_len: number };
type TracePayload = {
  trace: TraceView;
  review: ReviewRec | null;
  system_same_as_previous: boolean | null;
  evaluator_results: { evaluator_id: number; failure: boolean | null; critique: string }[];
  quick_tags: { id: number; name: string }[];
  tags: number[];
};
type Stats = {
  total: number | null;
  reviewed: number;
  passed: number;
  failed: number;
  deferred: number;
  median_seconds: number | null;
  saturation: { window: number; reviewed: number; new_in_window: number; suggest_stop: boolean; series: number[] };
  ai: { enabled: boolean; reviewed: number; threshold: number; unlocked: boolean; reason: string | null };
  first_round: boolean;
};
type Draft = { verdict: "pass" | "fail" | null; note: string; anchor: number | null; deferred: boolean; tags: number[] };
const EMPTY: Draft = { verdict: null, note: "", anchor: null, deferred: false, tags: [] };

const isTyping = (el: EventTarget | null) => el instanceof HTMLElement && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.tagName === "SELECT" || el.isContentEditable);
const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

export function Review() {
  const pid = usePid();
  const qc = useQueryClient();
  const project = useProject(pid);
  const [params, setParams] = useSearchParams();
  const batches = useQuery({ queryKey: ["batches", pid], queryFn: () => api.get<BatchSummary[]>(`/api/projects/${pid}/batches`) });
  const bid = Number(params.get("batch")) || batches.data?.[batches.data.length - 1]?.id;

  const queue = useQuery({ queryKey: ["queue", pid, bid], queryFn: () => api.get<QItem[]>(`/api/projects/${pid}/review/queue?batch_id=${bid}`), enabled: !!bid });
  const stats = useQuery({ queryKey: ["rstats", pid, bid], queryFn: () => api.get<Stats>(`/api/projects/${pid}/review/stats?batch_id=${bid}`), enabled: !!bid });

  // ---- filters
  const [q, setQ] = useState("");
  const [chan, setChan] = useState("all");
  const [vf, setVf] = useState("all");
  const items = useMemo(() => {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (queue.data ?? []).filter((i) => {
      if (chan !== "all" && i.channel !== chan) return false;
      if (vf === "open" && (i.verdict || i.deferred)) return false;
      if (vf === "pass" && i.verdict !== "pass") return false;
      if (vf === "fail" && i.verdict !== "fail") return false;
      if (vf === "later" && !(i.deferred && !i.verdict)) return false;
      const hay = i.search + " " + i.external_id.toLowerCase();
      return terms.every((t) => hay.includes(t));
    });
  }, [queue.data, q, chan, vf]);
  const channels = useMemo(() => [...new Set((queue.data ?? []).map((i) => i.channel))], [queue.data]);

  // ---- current trace
  const tParam = Number(params.get("t"));
  const tid = tParam && queue.data?.some((i) => i.id === tParam) ? tParam : (queue.data?.find((i) => !i.verdict && !i.deferred) ?? queue.data?.[0])?.id;
  const idx = items.findIndex((i) => i.id === tid);
  // Pin the current trace in the URL so saving a verdict never moves the view.
  useEffect(() => {
    if (tid && tid !== tParam) {
      const next = new URLSearchParams(params);
      next.set("t", String(tid));
      if (bid) next.set("batch", String(bid));
      setParams(next, { replace: true });
    }
  }, [tid, tParam, bid, params, setParams]);
  const detail = useQuery({
    queryKey: ["rtrace", pid, tid, bid],
    queryFn: () => api.get<TracePayload>(`/api/projects/${pid}/review/trace/${tid}?batch_id=${bid}`),
    enabled: !!tid,
  });

  // Prefetch neighbours so J/K feel instant.
  useEffect(() => {
    if (!detail.data || idx < 0) return;
    for (const n of [items[idx + 1], items[idx + 2], items[idx - 1]]) {
      if (n) qc.prefetchQuery({ queryKey: ["rtrace", pid, n.id, bid], queryFn: () => api.get<TracePayload>(`/api/projects/${pid}/review/trace/${n.id}?batch_id=${bid}`), staleTime: 30_000 });
    }
  }, [detail.data, idx, items, pid, bid, qc]);

  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [loadedFor, setLoadedFor] = useState<number | null>(null);
  useEffect(() => {
    if (detail.data && detail.data.trace.id === tid && loadedFor !== tid) {
      const r = detail.data.review;
      setDraft(r ? { verdict: r.verdict, note: r.note, anchor: r.first_failure_event_id, deferred: r.deferred, tags: detail.data.tags } : { ...EMPTY, tags: detail.data.tags });
      setLoadedFor(tid);
    }
  }, [detail.data, tid, loadedFor]);

  // ---- view toggles
  const [showSystem, setShowSystem] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [tab, setTab] = useState<"conversation" | "steps" | "raw">("conversation");
  const [help, setHelp] = useState(false);
  const [facts, setFacts] = useState(false);
  const [cursor, setCursor] = useState<number>(-1);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  // ---- timing
  const sessionStart = useRef(Date.now());
  const enteredAt = useRef(Date.now());
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    enteredAt.current = Date.now();
    setCursor(-1);
  }, [tid]);
  const onTrace = (now - enteredAt.current) / 1000;
  const nudgeAt = Number(project.data?.settings.review_nudge_seconds ?? 120);

  // ---- saving
  const patchQueue = useCallback(
    (id: number, patch: Partial<QItem>) => qc.setQueryData<QItem[]>(["queue", pid, bid], (old) => old?.map((i) => (i.id === id ? { ...i, ...patch } : i))),
    [qc, pid, bid],
  );
  const pendingNote = useRef<{ id: number; note: string } | null>(null);
  const noteTimer = useRef<number | undefined>(undefined);

  // Saves for the same trace are chained so they reach the server in order.
  const chain = useRef<Record<number, Promise<unknown>>>({});
  const put = useCallback(
    (id: number, body: Record<string, any>) => {
      const run = chain.current[id] ?? Promise.resolve();
      const next = run.then(() => doPut(id, body));
      chain.current[id] = next.catch(() => undefined);
      return next;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [pid, bid],
  );
  const doPut = useCallback(
    async (id: number, body: Record<string, any>) => {
      setSaveState("saving");
      try {
        const r = await api.put<ReviewRec>(`/api/projects/${pid}/reviews/${id}`, { batch_id: bid, ...body });
        patchQueue(id, { verdict: r.verdict, deferred: r.deferred, has_note: !!r.note.trim() });
        qc.setQueryData<TracePayload>(["rtrace", pid, id, bid], (old) => (old ? { ...old, review: r } : old));
        setSaveState("saved");
        qc.invalidateQueries({ queryKey: ["rstats", pid, bid] });
        return r;
      } catch {
        setSaveState("error");
      }
    },
    [pid, bid, patchQueue, qc],
  );

  const flushNote = useCallback(async () => {
    window.clearTimeout(noteTimer.current);
    const p = pendingNote.current;
    pendingNote.current = null;
    if (p) await put(p.id, { note: p.note, fields: ["note"] });
  }, [put]);

  const navTarget = useRef<number | null>(null);
  const go = (target: number | undefined) => {
    if (target === undefined || target === (navTarget.current ?? tid)) return;
    navTarget.current = target;
    // Save the trace we are leaving in the background; navigation itself is instant.
    if (tid) {
      void flushNote();
      const secs = Math.min(600, (Date.now() - enteredAt.current) / 1000);
      if (secs > 1 && (draft.verdict || draft.note || draft.deferred)) void put(tid, { add_seconds: secs, fields: [] });
    }
    setLoadedFor(null);
    const next = new URLSearchParams(params);
    next.set("t", String(target));
    if (bid) next.set("batch", String(bid));
    setParams(next, { replace: true });
    document.getElementById("trace-scroll")?.scrollTo({ top: 0 });
  };
  if (navTarget.current !== null && navTarget.current === tid) navTarget.current = null;
  const step = (d: number) => {
    const cur = items.findIndex((i) => i.id === (navTarget.current ?? tid));
    const j = cur < 0 ? 0 : Math.max(0, Math.min(items.length - 1, cur + d));
    go(items[j]?.id);
  };

  const setVerdict = (v: "pass" | "fail") => {
    if (!tid) return;
    const nv = draft.verdict === v ? null : v;
    setDraft((d) => ({ ...d, verdict: nv, deferred: nv ? false : d.deferred }));
    put(tid, { verdict: nv, fields: ["verdict"] });
  };
  const toggleDefer = () => {
    if (!tid) return;
    const nd = !draft.deferred;
    setDraft((d) => ({ ...d, deferred: nd }));
    put(tid, { deferred: nd, fields: ["deferred"] });
  };
  const setAnchor = (eid: number | null) => {
    if (!tid) return;
    setDraft((d) => ({ ...d, anchor: eid }));
    put(tid, { first_failure_event_id: eid, fields: ["first_failure_event_id"] });
  };
  const toggleTag = (fm: number) => {
    if (!tid) return;
    const tags = draft.tags.includes(fm) ? draft.tags.filter((x) => x !== fm) : [...draft.tags, fm];
    setDraft((d) => ({ ...d, tags }));
    put(tid, { tags, fields: [] });
  };
  const onNote = (v: string) => {
    if (!tid) return;
    setDraft((d) => ({ ...d, note: v }));
    pendingNote.current = { id: tid, note: v };
    setSaveState("saving");
    window.clearTimeout(noteTimer.current);
    noteTimer.current = window.setTimeout(flushNote, 600);
  };
  const undo = useMutation({
    mutationFn: async () => {
      await flushNote();
      await chain.current[tid!];
      return api.post<ReviewRec>(`/api/projects/${pid}/reviews/${tid}/undo`);
    },
    onSuccess: (r) => {
      setDraft((d) => ({ ...d, verdict: r.verdict, note: r.note, anchor: r.first_failure_event_id, deferred: r.deferred }));
      patchQueue(tid!, { verdict: r.verdict, deferred: r.deferred, has_note: !!r.note.trim() });
      qc.invalidateQueries({ queryKey: ["rstats", pid, bid] });
    },
  });
  const saveAndNext = async () => {
    noteRef.current?.blur();
    step(1);
  };

  // anchorable events for the keyboard turn cursor
  const turnIds = useMemo(() => (detail.data?.trace.events ?? []).filter((e) => (e.role !== "tool_result" && e.content?.trim()) || e.role === "tool_call").map((e) => e.id), [detail.data]);
  const cursorId = cursor >= 0 ? turnIds[cursor] : null;
  useEffect(() => {
    if (cursorId) document.querySelector(`[data-event-id="${cursorId}"]`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [cursorId]);

  // ---- keyboard
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key === "Enter") {
        e.preventDefault();
        saveAndNext();
        return;
      }
      if (isTyping(e.target)) {
        if (e.key === "Escape") (e.target as HTMLElement).blur();
        return;
      }
      if (help && e.key !== "?" && e.key !== "Escape") return;
      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        undo.mutate();
        return;
      }
      if (mod || e.altKey) return;
      const k = e.key;
      const quick = detail.data?.quick_tags ?? [];
      if (/^[1-9]$/.test(k) && quick[Number(k) - 1]) {
        toggleTag(quick[Number(k) - 1].id);
        return;
      }
      const act: Record<string, () => void> = {
        j: () => step(1),
        ArrowDown: () => step(1),
        ArrowRight: () => step(1),
        k: () => step(-1),
        ArrowUp: () => step(-1),
        ArrowLeft: () => step(-1),
        p: () => setVerdict("pass"),
        f: () => {
          if (draft.verdict !== "fail") setVerdict("fail");
          noteRef.current?.focus();
        },
        n: () => noteRef.current?.focus(),
        s: () => setShowSystem((v) => !v),
        t: () => setToolsOpen((v) => !v),
        d: () => toggleDefer(),
        r: () => setTab((t) => (t === "raw" ? "conversation" : "raw")),
        b: () => setFacts((v) => !v),
        z: () => undo.mutate(),
        "[": () => setCursor((c) => Math.max(0, (c < 0 ? turnIds.length : c) - 1)),
        "]": () => setCursor((c) => Math.min(turnIds.length - 1, c + 1)),
        a: () => cursorId && setAnchor(draft.anchor === cursorId ? null : cursorId),
        "?": () => setHelp((v) => !v),
        "/": () => searchRef.current?.focus(),
        Escape: () => {
          setHelp(false);
          setFacts(false);
          setCursor(-1);
        },
      };
      const fn = act[k] ?? act[k.toLowerCase()];
      if (fn) {
        e.preventDefault();
        fn();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  });

  // flush on unmount / tab close
  const flushRef = useRef(flushNote);
  flushRef.current = flushNote;
  useEffect(() => () => void flushRef.current(), []);

  if (batches.data && !batches.data.length)
    return (
      <div className="p-8">
        <Empty>
          No review batch yet. <Link className="text-accent-400 underline" to={`/p/${pid}/traces`}>Build one on Get traces</Link>.
        </Empty>
      </div>
    );

  const st = stats.data;
  const tr = detail.data?.trace;
  const multiTurn = (tr?.n_turns ?? 0) > 2;
  const reviewedNow = st?.reviewed ?? 0;

  return (
    <div className="flex h-full flex-col">
      {/* toolbar */}
      <div className="flex h-12 shrink-0 items-center gap-4 border-b border-ink-700 bg-ink-950 px-4">
        <select
          className="input h-8 w-56 py-0"
          value={bid ?? ""}
          onChange={(e) => {
            setLoadedFor(null);
            setParams({ batch: e.target.value });
          }}
          aria-label="Batch"
        >
          {batches.data?.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
        </select>
        <div className="flex items-center gap-2">
          <div className="w-40">
            <div className="h-1.5 overflow-hidden rounded-full bg-ink-800"><div className="h-full bg-accent-400 transition-all" style={{ width: `${(100 * reviewedNow) / Math.max(1, st?.total ?? 1)}%` }} /></div>
          </div>
          <span className="text-[13px] tabular-nums text-mist-200" data-testid="progress"><b className="text-mist-50">{reviewedNow}</b> of {st?.total ?? "…"} reviewed</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-mist-400">
          <span title="Pass / fail so far"><span className="text-pass-400">✓ {st?.passed ?? 0}</span> · <span className="text-fail-400">✕ {st?.failed ?? 0}</span>{st?.deferred ? <> · <span className="text-warn-400">↻ {st.deferred}</span></> : null}</span>
          <span title="Session time">⏱ {fmt((now - sessionStart.current) / 1000)}</span>
          <span title="Median seconds per reviewed trace">median {st?.median_seconds ? `${Math.round(st.median_seconds)}s` : "—"}/trace</span>
        </div>
        <Saturation st={st} />
        <button className="btn-quiet btn-sm ml-auto" onClick={() => setFacts(true)}>Business facts <span className="kbd">B</span></button>
        <button className="btn-quiet btn-sm" onClick={() => setHelp(true)}>Shortcuts <span className="kbd">?</span></button>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_360px]">
        {/* queue */}
        <div className="flex min-h-0 flex-col border-r border-ink-700 bg-ink-900">
          <div className="space-y-2 border-b border-ink-700 p-2">
            <div className="relative">
              <input ref={searchRef} className="input pr-8" placeholder="Search traces…" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLElement).blur()} />
              <span className="kbd absolute right-2 top-1.5">/</span>
            </div>
            <div className="flex gap-1.5">
              <select className="input h-7 py-0 text-xs" value={chan} onChange={(e) => setChan(e.target.value)} aria-label="Channel filter">
                <option value="all">All channels</option>
                {channels.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <select className="input h-7 py-0 text-xs" value={vf} onChange={(e) => setVf(e.target.value)} aria-label="Status filter">
                <option value="all">All statuses</option>
                <option value="open">Open</option>
                <option value="pass">Pass</option>
                <option value="fail">Fail</option>
                <option value="later">Come back later</option>
              </select>
            </div>
            <div className="text-xxs text-mist-500">{items.length} of {queue.data?.length ?? 0} traces</div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto" data-testid="queue">
            {items.map((i) => (
              <button
                key={i.id}
                onClick={() => go(i.id)}
                className={`block w-full border-b border-ink-700 px-3 py-2 text-left ${i.id === tid ? "bg-ink-950 shadow-[inset_2px_0_0_rgb(var(--accent-400))]" : "hover:bg-ink-850"}`}
              >
                <div className="flex items-center gap-2">
                  <VerdictBadge verdict={i.verdict} deferred={i.deferred} />
                  <span className="truncate font-mono text-xxs text-mist-400">{i.external_id}</span>
                  <span className="ml-auto text-xxs text-mist-500">{i.channel}</span>
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-mist-300">{i.snippet || "—"}</div>
              </button>
            ))}
            {queue.data && !items.length && <div className="p-4 text-xs text-mist-400">No traces match.</div>}
          </div>
        </div>

        {/* trace */}
        <div className="flex min-h-0 flex-col">
          {tr && (
            <div className="shrink-0 border-b border-ink-700 bg-ink-950 px-5 pt-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[13px] font-medium text-mist-50">{tr.external_id}</span>
                <span className="text-xs text-mist-500">#{idx + 1} in view</span>
                {tr.synthetic && <span className="chip">synthetic</span>}
                <span className="ml-auto text-xs text-mist-400">{onTrace > 3 ? `${fmt(onTrace)} on this trace` : ""}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5" data-testid="meta-strip">
                <span className="chip border-accent-400/40 text-accent-400">{tr.channel}</span>
                {tr.prompt_version && <span className="chip">prompt {tr.prompt_version}</span>}
                <span className="chip">{tr.n_turns} turns</span>
                <span className="chip">{tr.n_tool_calls} tool calls</span>
                {Object.entries(tr.meta)
                  .filter(([k]) => !["channel", "prompt_version"].includes(k))
                  .map(([k, v]) => (
                    <span key={k} className="chip"><span className="text-mist-500">{k}</span> {String(v)}</span>
                  ))}
              </div>
              <div className="mt-2 flex gap-4">
                {(["conversation", "steps", "raw"] as const).map((t) => (
                  <button key={t} className={`tab ${tab === t ? "tab-active" : ""}`} onClick={() => setTab(t)}>
                    {t === "conversation" ? "Conversation" : t === "steps" ? "Steps" : "Raw JSON"}
                    {t === "raw" && <span className="kbd">R</span>}
                  </button>
                ))}
                <div className="ml-auto flex items-center gap-1 pb-1 text-xs text-mist-400">
                  <button className="btn-quiet btn-sm" onClick={() => setShowSystem((v) => !v)}>System prompt <span className="kbd">S</span></button>
                  <button className="btn-quiet btn-sm" onClick={() => setToolsOpen((v) => !v)}>{toolsOpen ? "Collapse" : "Expand"} tools <span className="kbd">T</span></button>
                </div>
              </div>
            </div>
          )}
          <div id="trace-scroll" className="min-h-0 flex-1 overflow-y-auto bg-ink-900 px-6 py-5">
            {!tr ? (
              <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-16 animate-pulse rounded-lg bg-ink-800" />)}</div>
            ) : tab === "steps" ? (
              <TraceSteps key={tr.id} trace={tr} anchorId={draft.anchor} />
            ) : (
              <TraceRenderer
                trace={tr}
                product={project.data?.name}
                raw={tab === "raw"}
                showSystem={showSystem}
                onToggleSystem={() => setShowSystem((v) => !v)}
                toolsExpanded={toolsOpen}
                systemSameAsPrevious={detail.data?.system_same_as_previous}
                anchorId={draft.anchor}
                onAnchor={setAnchor}
                focusEventId={cursorId}
              />
            )}
          </div>
        </div>

        {/* annotation */}
        <div className="flex min-h-0 flex-col overflow-y-auto border-l border-ink-700 bg-ink-950">
          <div className="border-b border-ink-700 px-4 py-3">
            <div className="flex items-center justify-between">
              <div className="h2">Your judgment</div>
              <SaveIndicator s={saveState} />
            </div>
            <p className="mt-1 text-xs text-mist-400">Write what you see going wrong. Do not diagnose the cause. Capture the most important problems and move on.</p>
          </div>
          <div className="space-y-4 p-4">
            <div className="grid grid-cols-2 gap-2">
              <button
                onClick={() => setVerdict("pass")}
                data-testid="pass-btn"
                aria-pressed={draft.verdict === "pass"}
                className={`flex h-12 items-center justify-center gap-2 rounded-md border text-[14px] font-semibold transition ${draft.verdict === "pass" ? "border-pass-500 bg-pass-500 text-white" : "border-ink-600 text-mist-200 hover:border-pass-500 hover:text-pass-400"}`}
              >
                <span className="text-base">✓</span> Pass <span className={`kbd ${draft.verdict === "pass" ? "border-white/40 bg-transparent text-white" : ""}`}>P</span>
              </button>
              <button
                onClick={() => {
                  if (draft.verdict !== "fail") setVerdict("fail");
                  setTimeout(() => noteRef.current?.focus(), 0);
                }}
                data-testid="fail-btn"
                aria-pressed={draft.verdict === "fail"}
                className={`flex h-12 items-center justify-center gap-2 rounded-md border text-[14px] font-semibold transition ${draft.verdict === "fail" ? "border-fail-500 bg-fail-500 text-white" : "border-ink-600 text-mist-200 hover:border-fail-500 hover:text-fail-400"}`}
              >
                <span className="text-base">✕</span> Fail <span className={`kbd ${draft.verdict === "fail" ? "border-white/40 bg-transparent text-white" : ""}`}>F</span>
              </button>
            </div>

            <div>
              <label className="label flex items-center justify-between" htmlFor="note">
                <span>Note <span className="normal-case tracking-normal text-mist-500">— <Term tip="Free-text notes like this are called open codes. Later you'll group them into failure modes (axial coding).">what went wrong, in your words</Term></span></span>
                <span className="kbd">N</span>
              </label>
              <textarea
                id="note"
                ref={noteRef}
                data-testid="note"
                className="input min-h-[120px] resize-y text-[13.5px] leading-relaxed"
                placeholder={draft.verdict === "pass" ? "Optional. Anything worth remembering?" : "e.g. Sent markdown bullets over SMS; booked in-person tour but called it virtual"}
                value={draft.note}
                onChange={(e) => onNote(e.target.value)}
              />
              <div className="mt-1 flex justify-between text-xxs text-mist-500">
                <span><span className="kbd">Esc</span> leave note · <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span> save &amp; next</span>
              </div>
            </div>

            {!!detail.data?.quick_tags.length && (
              <div>
                <div className="label">Quick tags <span className="normal-case tracking-normal text-mist-500">(after the note)</span></div>
                <div className="flex flex-wrap gap-1.5">
                  {detail.data.quick_tags.map((m, i) => (
                    <button key={m.id} onClick={() => toggleTag(m.id)} className={`chip ${draft.tags.includes(m.id) ? "border-accent-400 bg-accent-400/10 text-accent-400" : ""}`}>
                      {i < 9 && <span className="kbd">{i + 1}</span>} {m.name}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="panel space-y-1.5 p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-medium text-mist-200">⚑ First failure</span>
                {draft.anchor ? (
                  <button className="text-mist-400 underline hover:text-mist-100" onClick={() => setAnchor(null)}>clear</button>
                ) : (
                  <span className="text-mist-500">not set</span>
                )}
              </div>
              {draft.anchor ? (
                <div className="text-mist-300">Marked on turn #{(tr?.events.findIndex((e) => e.id === draft.anchor) ?? 0) + 1}.</div>
              ) : (
                <div className={draft.verdict === "fail" && multiTurn ? "text-warn-400" : "text-mist-400"}>
                  {draft.verdict === "fail" && multiTurn ? "Multi-turn trace: mark the first upstream failure — later problems are often consequences of it. " : ""}
                  Click a turn, or use <span className="kbd">[</span> <span className="kbd">]</span> then <span className="kbd">A</span>.
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button className={`btn-ghost btn-sm ${draft.deferred ? "border-warn-400 text-warn-400" : ""}`} onClick={toggleDefer} data-testid="defer-btn">
                ↻ {draft.deferred ? "Marked: come back later" : "Come back later"} <span className="kbd">D</span>
              </button>
              <button className="btn-quiet btn-sm" onClick={() => undo.mutate()} disabled={!detail.data?.review?.history_len}>
                Undo <span className="kbd">Z</span>
              </button>
            </div>

            <button className="btn-primary w-full justify-center" onClick={saveAndNext} data-testid="save-next">
              Save &amp; next <span className="kbd border-white/30 bg-transparent text-white">Ctrl ↵</span>
            </button>

            {onTrace > nudgeAt && (
              <div className="rounded-md border border-warn-400/30 bg-warn-900/60 px-3 py-2 text-xs text-warn-400">
                You've spent {Math.floor(onTrace / 60)} min on this trace. Note what you see and move on.
              </div>
            )}

            {!!detail.data?.evaluator_results.length && (
              <div className="panel p-3 text-xs">
                <div className="label">Evaluator verdicts (shown after your judgment)</div>
                {detail.data.evaluator_results.map((r) => (
                  <div key={r.evaluator_id} className="mt-1"><VerdictBadge verdict={r.failure ? "fail" : "pass"} /> <span className="text-mist-300">{r.critique}</span></div>
                ))}
              </div>
            )}

            <Similar pid={pid} tid={tid} ai={st?.ai} onOpen={(id) => go(id)} inQueue={(id) => !!queue.data?.some((i) => i.id === id)} />
          </div>
        </div>
      </div>

      {help && <Shortcuts onClose={() => setHelp(false)} />}
      {facts && <Facts text={project.data?.business_facts ?? ""} channels={project.data?.channels ?? []} onClose={() => setFacts(false)} />}
    </div>
  );
}

function SaveIndicator({ s }: { s: string }) {
  if (s === "saving") return <span className="text-xxs text-mist-400">Saving…</span>;
  if (s === "saved") return <span className="text-xxs text-pass-400">✓ Saved</span>;
  if (s === "error") return <span className="text-xxs text-fail-400">Not saved — retrying on next change</span>;
  return <span className="text-xxs text-mist-500">Autosaves</span>;
}

function Saturation({ st }: { st?: Stats }) {
  if (!st) return null;
  const sat = st.saturation;
  const last = sat.series.slice(-sat.window);
  return (
    <div
      className={`flex items-center gap-2 rounded-md border px-2 py-1 text-xs ${sat.suggest_stop ? "border-pass-500/40 bg-pass-900/50 text-pass-400" : "border-ink-700 text-mist-300"}`}
      title="How many new kinds of problem appeared in the most recent reviewed traces. When no new kinds appear, you have probably seen the main failure types."
      data-testid="saturation"
    >
      <div className="flex h-4 items-end gap-px">
        {Array.from({ length: sat.window }).map((_, i) => (
          <span key={i} className={`w-[3px] rounded-sm ${last[i] ? "h-4 bg-accent-400" : last[i] === 0 ? "h-1.5 bg-ink-600" : "h-1 bg-ink-800"}`} />
        ))}
      </div>
      {sat.reviewed < sat.window ? (
        <span><Term tip="Saturation: when new kinds of problem stop appearing, more review has diminishing returns. ~100 traces is typical, but it is a heuristic, not a quota.">New problem types</Term>: {sat.new_in_window} so far</span>
      ) : sat.suggest_stop ? (
        <span>No new problem types in the last {sat.window}. Consider moving on to grouping.</span>
      ) : (
        <span><Term tip="Saturation: when new kinds of problem stop appearing, more review has diminishing returns. ~100 traces is typical, but it is a heuristic, not a quota.">New problem types</Term> in last {sat.window}: <b>{sat.new_in_window}</b></span>
      )}
    </div>
  );
}

function Similar({ pid, tid, ai, onOpen, inQueue }: { pid: number; tid?: number; ai?: Stats["ai"]; onOpen: (id: number) => void; inQueue: (id: number) => boolean }) {
  const [res, setRes] = useState<{ id: number; external_id: string; channel: string; why: string; snippet: string }[] | null>(null);
  const [err, setErr] = useState("");
  const m = useMutation({
    mutationFn: () => api.post<typeof res>(`/api/projects/${pid}/traces/${tid}/similar`),
    onSuccess: (r) => {
      setRes(r);
      setErr("");
    },
    onError: (e: any) => setErr(e.message),
  });
  useEffect(() => setRes(null), [tid]);
  if (!ai) return null;
  return (
    <div className="border-t border-ink-700 pt-4">
      <div className="label">AI assist</div>
      {!ai.unlocked ? (
        <div className="text-xs text-mist-400">
          🔒 {ai.reason}
          {ai.enabled && (
            <div className="mt-2 h-1 overflow-hidden rounded-full bg-ink-800"><div className="h-full bg-accent-400" style={{ width: `${Math.min(100, (100 * ai.reviewed) / Math.max(1, ai.threshold))}%` }} /></div>
          )}
        </div>
      ) : (
        <>
          <button className="btn-ghost btn-sm" onClick={() => m.mutate()} disabled={m.isPending}>{m.isPending ? "Finding…" : "Find similar traces"}</button>
          {err && <div className="mt-1 text-xs text-fail-400">{err}</div>}
          {res && (
            <div className="mt-2 space-y-1">
              {res.map((r) => (
                <button key={r.id} disabled={!inQueue(r.id)} onClick={() => onOpen(r.id)} className="block w-full rounded border border-ink-700 px-2 py-1.5 text-left text-xs hover:bg-ink-850 disabled:opacity-60">
                  <div className="flex gap-2"><span className="font-mono text-mist-300">{r.external_id}</span><span className="text-mist-500">{r.channel}</span>{!inQueue(r.id) && <span className="text-mist-500">(not in this batch)</span>}</div>
                  <div className="line-clamp-1 text-mist-400">{r.snippet}</div>
                  <div className="text-mist-500">{r.why}</div>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

const KEYS: [string, string][] = [
  ["J / ↓ / →", "Next trace"],
  ["K / ↑ / ←", "Previous trace"],
  ["P", "Pass"],
  ["F", "Fail (and focus the note)"],
  ["N", "Focus the note"],
  ["Esc", "Leave the note field"],
  ["Ctrl/⌘ + Enter", "Save and go to next (works anywhere)"],
  ["D", "Come back later"],
  ["[ / ]", "Move between turns"],
  ["A", "Mark the selected turn as the first failure"],
  ["S", "Show / hide the system prompt"],
  ["T", "Expand / collapse tool calls"],
  ["R", "Raw JSON view"],
  ["B", "Business facts"],
  ["Z / Ctrl+Z", "Undo the last change to this trace"],
  ["/", "Search traces"],
  ["1–9", "Quick tags (later review rounds)"],
  ["?", "This help"],
];

function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40" onClick={onClose}>
      <div className="w-[520px] rounded-lg border border-ink-700 bg-ink-950 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="shortcuts">
        <div className="mb-3 flex items-center justify-between">
          <div className="h2">Keyboard shortcuts</div>
          <span className="kbd">Esc</span>
        </div>
        <div className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1.5 text-[13px]">
          {KEYS.map(([k, v]) => (
            <div key={k} className="contents">
              <span className="font-mono text-xs text-mist-200">{k}</span>
              <span className="text-mist-300">{v}</span>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-mist-400">Shortcuts are active whenever the note field is not focused.</p>
      </div>
    </div>
  );
}

function Facts({ text, channels, onClose }: { text: string; channels: { name: string; render_rule: string }[]; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <div className="h-full w-[420px] overflow-y-auto border-l border-ink-700 bg-ink-950 p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <div className="h2">Things you know that the model doesn't</div>
          <span className="kbd">B</span>
        </div>
        <pre className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-mist-100">{text || "No business facts yet — add them in Set up the project."}</pre>
        <div className="label mt-6">Channel render rules</div>
        <ul className="space-y-1.5 text-[13px]">
          {channels.map((c) => (
            <li key={c.name}><span className="chip mr-1">{c.name}</span><span className="text-mist-300">{c.render_rule}</span></li>
          ))}
        </ul>
      </div>
    </div>
  );
}
