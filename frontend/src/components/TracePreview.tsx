import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type TraceView } from "../api";
import { TraceRenderer } from "./TraceRenderer";
import { TraceSteps } from "./TraceSteps";
import { VerdictBadge } from "./ui";

type Payload = { trace: TraceView; review: { verdict: string | null; note: string; first_failure_event_id: number | null } | null };

/** Slide-over showing one trace plus the reviewer's note. */
export function TracePreview({ pid, traceId, product, onClose, children }: { pid: number; traceId: number; product?: string; onClose: () => void; children?: React.ReactNode }) {
  const q = useQuery({ queryKey: ["rtrace", pid, traceId, undefined], queryFn: () => api.get<Payload>(`/api/projects/${pid}/review/trace/${traceId}`) });
  const [tab, setTab] = useState<"conversation" | "steps">("conversation");
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);
  const t = q.data?.trace;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={onClose}>
      <div className="flex h-full w-[760px] max-w-[95vw] flex-col border-l border-ink-700 bg-ink-950 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-ink-700 px-4 py-3">
          <span className="font-mono text-[13px] font-medium text-mist-50">{t?.external_id ?? "…"}</span>
          {t && <span className="chip">{t.channel}</span>}
          {q.data?.review && <VerdictBadge verdict={q.data.review.verdict} />}
          <button className="btn-quiet btn-sm ml-auto" onClick={onClose}>Close <span className="kbd">Esc</span></button>
        </div>
        {q.data?.review?.note && (
          <div className="border-b border-ink-700 bg-ink-900 px-4 py-2.5 text-[13px]">
            <span className="label">Your note</span>
            <div className="text-mist-100">{q.data.review.note}</div>
          </div>
        )}
        {children}
        <div className="flex gap-4 border-b border-ink-700 px-4">
          {(["conversation", "steps"] as const).map((x) => (
            <button key={x} className={`tab ${tab === x ? "tab-active" : ""}`} onClick={() => setTab(x)}>{x === "conversation" ? "Conversation" : "Steps"}</button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto bg-ink-900 p-5">
          {t && (tab === "steps" ? <TraceSteps trace={t} anchorId={q.data?.review?.first_failure_event_id} /> : <TraceRenderer trace={t} product={product} anchorId={q.data?.review?.first_failure_event_id} />)}
        </div>
      </div>
    </div>
  );
}
