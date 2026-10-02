import { useState } from "react";
import type { TraceView } from "../api";

const ROLE: Record<string, { icon: string; label: string; cls: string }> = {
  system: { icon: "⚙", label: "System", cls: "bg-ink-800 text-mist-300" },
  user: { icon: "U", label: "User", cls: "bg-accent-400/15 text-accent-400" },
  assistant: { icon: "A", label: "Assistant", cls: "bg-pass-900 text-pass-400" },
  tool_call: { icon: "ƒ", label: "Tool call", cls: "bg-warn-900 text-warn-400" },
  tool_result: { icon: "↳", label: "Tool result", cls: "bg-ink-800 text-mist-300" },
};

/** Step-by-step view: every event as a row in a tree on the left, full detail on the right. */
export function TraceSteps({ trace, anchorId }: { trace: TraceView; anchorId?: number | null }) {
  const steps = [
    ...(trace.system_prompt ? [{ id: -1, seq: -1, role: "system", content: trace.system_prompt, tool_name: "", tool_args: {}, tool_result: "", tool_call_id: "" }] : []),
    ...trace.events,
  ];
  const [sel, setSel] = useState<number>(steps[0]?.id ?? 0);
  const cur = steps.find((s) => s.id === sel) ?? steps[0];
  return (
    <div className="grid min-h-[420px] grid-cols-[280px_1fr] overflow-hidden rounded-lg border border-ink-700">
      <div className="overflow-y-auto border-r border-ink-700 bg-ink-900">
        {steps.map((s, i) => {
          const r = ROLE[s.role] ?? ROLE.user;
          const title = s.role === "tool_call" ? s.tool_name : s.role === "tool_result" ? `${s.tool_name || "result"}` : r.label;
          const preview = s.role === "tool_call" ? Object.keys(s.tool_args || {}).join(", ") : (s.content || s.tool_result || "").slice(0, 60);
          return (
            <button
              key={s.id}
              onClick={() => setSel(s.id)}
              className={`flex w-full items-start gap-2 border-b border-ink-700 px-2.5 py-2 text-left ${sel === s.id ? "bg-ink-800" : "hover:bg-ink-850"} ${s.role === "tool_result" ? "pl-7" : ""}`}
            >
              <span className={`mt-px grid h-[18px] w-[18px] shrink-0 place-items-center rounded font-mono text-[10px] font-semibold ${r.cls}`}>{r.icon}</span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span className="font-medium text-mist-100">{title}</span>
                  {anchorId === s.id && <span className="rounded bg-accent-400 px-1 text-[9px] font-bold uppercase text-white">first failure</span>}
                  <span className="ml-auto font-mono text-[10px] text-mist-500">#{i}</span>
                </span>
                <span className="block truncate text-xs text-mist-400">{preview}</span>
              </span>
            </button>
          );
        })}
      </div>
      <div className="overflow-y-auto p-4">
        {cur && (
          <>
            <div className="mb-3 flex items-center gap-2">
              <span className="chip">{ROLE[cur.role]?.label}</span>
              {cur.tool_name && <span className="font-mono text-[13px] text-mist-100">{cur.tool_name}</span>}
              {cur.tool_call_id && <span className="font-mono text-xs text-mist-500">{cur.tool_call_id}</span>}
            </div>
            {cur.role === "tool_call" ? (
              <Block title="Arguments" text={JSON.stringify(cur.tool_args, null, 2)} mono />
            ) : cur.role === "tool_result" ? (
              <Block title="Output" text={pretty(cur.tool_result)} mono />
            ) : (
              <Block title={cur.role === "system" ? "Prompt" : "Content"} text={cur.content} mono={cur.role === "system"} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Block({ title, text, mono }: { title: string; text: string; mono?: boolean }) {
  return (
    <div>
      <div className="label">{title}</div>
      <pre className={`whitespace-pre-wrap break-words rounded-md border border-ink-700 bg-ink-900 p-3 text-[13px] leading-relaxed text-mist-100 ${mono ? "font-mono text-[12.5px]" : "font-sans"}`}>{text}</pre>
    </div>
  );
}

function pretty(s: string) {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}
