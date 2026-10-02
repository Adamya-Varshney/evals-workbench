import { useState } from "react";
import type { TraceEvent, TraceView } from "../api";

/**
 * Renders a trace the way the end user experienced it.
 * SMS: phone bubbles, plain text exactly as sent (markdown shows literally).
 * Email: an email thread. Chat: widget bubbles. Voice: speaker-turn transcript.
 * Tool calls are compact cards that expand to JSON; tool results are collapsed by default.
 */
export function TraceRenderer({
  trace,
  raw = false,
  showSystem = false,
  onToggleSystem,
  toolsExpanded = false,
  systemSameAsPrevious,
  anchorId,
  onAnchor,
  focusEventId,
  product = "Assistant",
}: {
  product?: string;
  trace: TraceView;
  raw?: boolean;
  showSystem?: boolean;
  onToggleSystem?: () => void;
  toolsExpanded?: boolean;
  systemSameAsPrevious?: boolean | null;
  anchorId?: number | null;
  onAnchor?: (eventId: number | null) => void;
  focusEventId?: number | null;
}) {
  if (raw) {
    return (
      <pre className="whitespace-pre-wrap break-words rounded-lg border border-ink-700 bg-ink-950 p-4 font-mono text-[12.5px] leading-relaxed text-mist-200">
        {JSON.stringify(trace.raw ?? { system_prompt: trace.system_prompt, events: trace.events, meta: trace.meta }, null, 2)}
      </pre>
    );
  }
  const ch = (trace.channel || "chat").toLowerCase();
  return (
    <div className="space-y-4">
      <SystemPrompt
        text={trace.system_prompt}
        open={showSystem}
        onToggle={onToggleSystem}
        same={systemSameAsPrevious}
        version={trace.prompt_version}
      />
      <Body ch={ch} product={product} events={trace.events} toolsExpanded={toolsExpanded} anchorId={anchorId} onAnchor={onAnchor} focusEventId={focusEventId} meta={trace.meta} />
    </div>
  );
}

function SystemPrompt({ text, open, onToggle, same, version }: { text: string; open: boolean; onToggle?: () => void; same?: boolean | null; version?: string | null }) {
  const [localOpen, setLocalOpen] = useState(false);
  const isOpen = onToggle ? open : localOpen;
  const toggle = onToggle ?? (() => setLocalOpen((v) => !v));
  if (!text) return <div className="text-xs text-mist-500">No system prompt recorded.</div>;
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900/60">
      <button onClick={toggle} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-mist-300 hover:text-mist-50">
        <span className="font-mono">{isOpen ? "▾" : "▸"}</span>
        <span className="font-semibold uppercase tracking-wider">System prompt</span>
        {version && <span className="chip">{version}</span>}
        {same === true && <span className="chip border-pass-500/40 text-pass-400">= same as previous trace</span>}
        {same === false && <span className="chip border-gold-500/50 text-gold-300">≠ changed from previous trace</span>}
        <span className="ml-auto text-mist-500">
          <span className="kbd">S</span>
        </span>
      </button>
      {isOpen && <pre className="max-h-80 overflow-auto whitespace-pre-wrap border-t border-ink-700 px-4 py-3 font-mono text-[12.5px] leading-relaxed text-mist-200">{text}</pre>}
    </div>
  );
}

type BodyProps = {
  ch: string;
  product: string;
  events: TraceEvent[];
  toolsExpanded: boolean;
  anchorId?: number | null;
  onAnchor?: (id: number | null) => void;
  focusEventId?: number | null;
  meta: Record<string, any>;
};

function Body(p: BodyProps) {
  if (p.ch === "sms") return <SmsBody {...p} />;
  if (p.ch === "email") return <EmailBody {...p} />;
  if (p.ch === "voice") return <VoiceBody {...p} />;
  return <ChatBody {...p} />;
}

function Anchorable({
  ev,
  anchorId,
  onAnchor,
  focus,
  children,
  className = "",
}: {
  ev: TraceEvent;
  anchorId?: number | null;
  onAnchor?: (id: number | null) => void;
  focus?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  const active = anchorId === ev.id;
  return (
    <div
      data-event-id={ev.id}
      onClick={onAnchor ? () => onAnchor(active ? null : ev.id) : undefined}
      title={onAnchor ? (active ? "Click to clear the first-failure marker" : "Click to mark this turn as the first failure") : undefined}
      className={`relative ${onAnchor ? "cursor-pointer" : ""} ${active ? "rounded-xl ring-2 ring-gold-400 ring-offset-2 ring-offset-ink-950" : ""} ${focus ? "rounded-xl ring-1 ring-mist-400/60" : ""} ${className}`}
    >
      {active && (
        <span className="absolute -top-3 right-2 z-10 rounded-full bg-gold-400 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-ink-950">⚑ first failure</span>
      )}
      {children}
    </div>
  );
}

function ToolCard({ ev, result, expanded }: { ev: TraceEvent; result?: TraceEvent; expanded: boolean }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const [resOpen, setResOpen] = useState(false);
  const isOpen = open ?? expanded;
  const args = Object.entries(ev.tool_args || {});
  const keyArgs = args.slice(0, 4).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`);
  const resText = result?.tool_result ?? "";
  const isErr = /"error"|error:|timeout|exception/i.test(resText.slice(0, 200));
  return (
    <div className="mx-auto w-full max-w-read rounded-lg border border-dashed border-ink-500 bg-ink-900/70 text-[12.5px]" onClick={(e) => e.stopPropagation()}>
      <button className="flex w-full items-start gap-2 px-3 py-1.5 text-left" onClick={() => setOpen(!isOpen)}>
        <span className="mt-[1px] font-mono text-gold-400">⚙</span>
        <span className="font-mono font-medium text-mist-100">{ev.tool_name || "tool"}</span>
        <span className="truncate font-mono text-mist-400">{keyArgs.join(" · ")}{args.length > 4 ? " …" : ""}</span>
        <span className="ml-auto font-mono text-mist-500">{isOpen ? "▾" : "▸"}</span>
      </button>
      {isOpen && (
        <pre className="overflow-auto whitespace-pre-wrap border-t border-ink-700 px-3 py-2 font-mono text-[12px] text-mist-200">{JSON.stringify(ev.tool_args, null, 2)}</pre>
      )}
      {result && (
        <div className="border-t border-ink-700">
          <button className="flex w-full items-center gap-2 px-3 py-1 text-left text-mist-400 hover:text-mist-200" onClick={() => setResOpen(!resOpen)}>
            <span className="font-mono">↳</span>
            <span>result</span>
            {isErr && <span className="chip border-fail-500/50 text-fail-400">error</span>}
            <span className="text-mist-500">{resText.length} chars</span>
            <span className="ml-auto font-mono text-mist-500">{resOpen ? "▾" : "▸"}</span>
          </button>
          {resOpen && <pre className="max-h-72 overflow-auto whitespace-pre-wrap px-3 pb-2 font-mono text-[12px] text-mist-300">{pretty(resText)}</pre>}
        </div>
      )}
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

/** Pairs tool_call events with their tool_result; returns display items in order. */
function items(events: TraceEvent[]) {
  const results = new Map<string, TraceEvent>();
  const used = new Set<number>();
  events.forEach((e, i) => {
    if (e.role === "tool_result") {
      const key = e.tool_call_id || `idx-${i}`;
      results.set(key, e);
    }
  });
  const out: { ev: TraceEvent; result?: TraceEvent }[] = [];
  events.forEach((e, i) => {
    if (e.role === "tool_call") {
      let r = e.tool_call_id ? results.get(e.tool_call_id) : undefined;
      if (!r) {
        const next = events[i + 1];
        if (next && next.role === "tool_result" && !next.tool_call_id) r = next;
      }
      if (r) used.add(r.id);
      out.push({ ev: e, result: r });
    } else if (e.role === "tool_result") {
      if (!used.has(e.id)) out.push({ ev: { ...e, role: "tool_call", tool_name: e.tool_name || "tool result", tool_args: {} }, result: e });
    } else if (e.content?.trim()) {
      out.push({ ev: e });
    }
  });
  return out;
}

function SmsBody({ product, events, toolsExpanded, anchorId, onAnchor, focusEventId }: BodyProps) {
  return (
    <div className="mx-auto w-full max-w-[420px] rounded-[2rem] border border-ink-600 bg-[#0d1220] p-3 shadow-2xl">
      <div className="mb-2 flex items-center justify-center gap-2 pt-1 text-[11px] text-mist-400">
        <span className="h-1.5 w-12 rounded-full bg-ink-600" />
      </div>
      <div className="mb-3 text-center text-xs text-mist-400">Text Message · {product}</div>
      <div className="space-y-2 px-1 pb-2">
        {items(events).map(({ ev, result }) =>
          ev.role === "tool_call" ? (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <div className="py-1 opacity-90"><ToolCard ev={ev} result={result} expanded={toolsExpanded} /></div>
            </Anchorable>
          ) : (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <div className={`flex ${ev.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3.5 py-2 text-[15px] leading-snug ${
                    ev.role === "user" ? "rounded-br-md bg-[#2f7cf6] text-white" : "rounded-bl-md bg-[#2a2f3a] text-[#f2f4f8]"
                  }`}
                  style={{ fontFamily: "-apple-system, 'Segoe UI', Roboto, sans-serif" }}
                >
                  {ev.content}
                </div>
              </div>
              {ev.role === "assistant" && <div className="mt-0.5 pl-2 text-[10px] text-mist-500">{ev.content.length} chars · {Math.ceil(ev.content.length / 153) || 1} SMS segment{ev.content.length > 160 ? "s" : ""}</div>}
            </Anchorable>
          ),
        )}
      </div>
    </div>
  );
}

function ChatBody({ product, events, toolsExpanded, anchorId, onAnchor, focusEventId }: BodyProps) {
  return (
    <div className="mx-auto w-full max-w-[640px] overflow-hidden rounded-2xl border border-ink-600 bg-[#f7f8fb] text-[#1b2333] shadow-2xl">
      <div className="flex items-center gap-2 bg-[#21324f] px-4 py-2.5 text-sm font-medium text-white">
        <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" /> Chat · {product}
      </div>
      <div className="space-y-3 p-4">
        {items(events).map(({ ev, result }) =>
          ev.role === "tool_call" ? (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <div className="text-mist-100"><ToolCard ev={ev} result={result} expanded={toolsExpanded} /></div>
            </Anchorable>
          ) : (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <div className={`flex ${ev.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[82%] whitespace-pre-wrap break-words rounded-xl px-3.5 py-2.5 text-[15px] leading-relaxed ${ev.role === "user" ? "bg-[#21324f] text-white" : "border border-[#dfe3ec] bg-white"}`}>
                  {ev.content}
                </div>
              </div>
            </Anchorable>
          ),
        )}
      </div>
    </div>
  );
}

function EmailBody({ product, events, toolsExpanded, anchorId, onAnchor, focusEventId, meta }: BodyProps) {
  let n = 0;
  return (
    <div className="mx-auto w-full max-w-[720px] space-y-3">
      {items(events).map(({ ev, result }) => {
        if (ev.role === "tool_call")
          return (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <ToolCard ev={ev} result={result} expanded={toolsExpanded} />
            </Anchorable>
          );
        n += 1;
        const fromUser = ev.role === "user";
        return (
          <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
            <div className="overflow-hidden rounded-lg border border-[#d9dde6] bg-white text-[#1d2433] shadow-lg">
              <div className="border-b border-[#e6e9f0] bg-[#f6f7fa] px-4 py-2 text-[12.5px] leading-6 text-[#4a5468]">
                <div><span className="inline-block w-12 text-[#8a93a6]">From</span>{fromUser ? "Customer" : `${product} (assistant)`}</div>
                <div><span className="inline-block w-12 text-[#8a93a6]">To</span>{fromUser ? product : "Customer"}</div>
                <div><span className="inline-block w-12 text-[#8a93a6]">Subject</span>{n > 1 ? "Re: " : ""}{String(meta.subject ?? `Inquiry${meta.property ? ` about ${meta.property}` : ""}`)}</div>
              </div>
              <div className="whitespace-pre-wrap px-5 py-4 font-[Georgia,serif] text-[15.5px] leading-relaxed">{ev.content}</div>
            </div>
          </Anchorable>
        );
      })}
    </div>
  );
}

function VoiceBody({ product, events, toolsExpanded, anchorId, onAnchor, focusEventId }: BodyProps) {
  return (
    <div className="mx-auto w-full max-w-read rounded-xl border border-ink-600 bg-ink-900 p-5">
      <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-wider text-mist-400">
        <span>☎</span> Call transcript
      </div>
      <div className="space-y-3">
        {items(events).map(({ ev, result }) =>
          ev.role === "tool_call" ? (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <ToolCard ev={ev} result={result} expanded={toolsExpanded} />
            </Anchorable>
          ) : (
            <Anchorable key={ev.id} ev={ev} anchorId={anchorId} onAnchor={onAnchor} focus={focusEventId === ev.id}>
              <div className="grid grid-cols-[72px_1fr] gap-3">
                <div className={`pt-0.5 text-right text-xs font-semibold uppercase tracking-wider ${ev.role === "user" ? "text-sky-300" : "text-gold-300"}`}>
                  {ev.role === "user" ? "Caller" : "Agent"}
                </div>
                <div className="whitespace-pre-wrap text-[15.5px] leading-relaxed text-mist-50">{ev.content}</div>
              </div>
            </Anchorable>
          ),
        )}
      </div>
    </div>
  );
}
