"""Shared trace serialisation, facet discovery and filtering."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable, Optional

from sqlmodel import Session, select

from ..models import Event, PromptVersion, Trace

HIDDEN_META = {"timestamp", "id", "trace_id"}


def events_of(s: Session, trace_id: int) -> list[Event]:
    return list(s.exec(select(Event).where(Event.trace_id == trace_id).order_by(Event.seq)).all())


def trace_view(s: Session, t: Trace, include_raw: bool = False) -> dict:
    pv = s.get(PromptVersion, t.prompt_version_id) if t.prompt_version_id else None
    d = {
        "id": t.id, "external_id": t.external_id, "channel": t.channel, "meta": t.meta, "synthetic": t.synthetic,
        "synthetic_tuple": t.synthetic_tuple, "prompt_version": pv.label if pv else t.meta.get("prompt_version"),
        "system_prompt": t.system_prompt, "system_prompt_hash": t.system_prompt_hash,
        "n_turns": t.n_turns, "n_tool_calls": t.n_tool_calls, "n_chars": t.n_chars,
        "events": [
            {"id": e.id, "seq": e.seq, "role": e.role, "content": e.content, "tool_name": e.tool_name,
             "tool_args": e.tool_args, "tool_result": e.tool_result, "tool_call_id": e.tool_call_id}
            for e in events_of(s, t.id)
        ],
    }
    if include_raw:
        d["raw"] = t.raw
    return d


def trace_text(view: dict, scope: Optional[Iterable[str]] = None) -> str:
    """Plain-text rendering of a trace used in prompts. `scope` limits what is included:
    last_assistant | conversation | tool_calls | system_prompt | metadata."""
    scope = set(scope or ["conversation", "tool_calls"])
    out: list[str] = []
    if "system_prompt" in scope and view.get("system_prompt"):
        out.append(f"[system prompt]\n{view['system_prompt']}\n")
    if "metadata" in scope:
        out.append("[metadata] " + ", ".join(f"{k}={v}" for k, v in view.get("meta", {}).items()))
    out.append(f"[channel] {view.get('channel')}")
    evs = view["events"]
    if "conversation" in scope:
        for e in evs:
            if e["role"] in ("user", "assistant") and e["content"]:
                out.append(f"{e['role'].upper()}: {e['content']}")
            elif e["role"] == "tool_call" and "tool_calls" in scope:
                out.append(f"TOOL CALL {e['tool_name']}({_short(e['tool_args'])})")
            elif e["role"] == "tool_result" and "tool_calls" in scope:
                out.append(f"TOOL RESULT {e['tool_name']}: {e['tool_result'][:1500]}")
    else:
        if "tool_calls" in scope:
            for e in evs:
                if e["role"] == "tool_call":
                    out.append(f"TOOL CALL {e['tool_name']}({_short(e['tool_args'])})")
        if "last_assistant" in scope:
            last = next((e for e in reversed(evs) if e["role"] == "assistant" and e["content"]), None)
            last_user = None
            if last:
                last_user = next((e for e in reversed(evs[: evs.index(last)]) if e["role"] == "user"), None)
            if last_user:
                out.append(f"USER: {last_user['content']}")
            if last:
                out.append(f"ASSISTANT: {last['content']}")
    return "\n".join(out)


def _short(args: Any) -> str:
    import json

    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) < 600 else s[:600] + "…"


def facets(traces: list[Trace]) -> list[dict]:
    values: dict[str, Counter] = defaultdict(Counter)
    numeric: dict[str, list[float]] = defaultdict(list)
    for t in traces:
        values["channel"][t.channel] += 1
        for k, v in t.meta.items():
            if k in HIDDEN_META or k == "channel":
                continue
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                values[k][str(v)] += 1
            else:
                numeric[k].append(float(v))
        if t.synthetic:
            values["synthetic"]["true"] += 1
    out = []
    for k, c in values.items():
        if len(c) <= 40:
            present = sum(c.values())
            if present < len(traces):
                c["(none)"] += len(traces) - present
            out.append({"key": k, "kind": "category", "values": [{"value": v, "count": n} for v, n in c.most_common()]})
    for k, xs in numeric.items():
        out.append({"key": k, "kind": "number", "min": min(xs), "max": max(xs), "count": len(xs)})
    out.sort(key=lambda f: (f["key"] != "channel", f["kind"] != "category", f["key"]))
    return out


def matches(t: Trace, q: str = "", filters: Optional[dict] = None) -> bool:
    if q:
        terms = q.lower().split()
        hay = t.search_text + " " + t.external_id.lower()
        if not all(term in hay for term in terms):
            return False
    for k, cond in (filters or {}).items():
        v = t.channel if k == "channel" else (str(t.synthetic).lower() if k == "synthetic" else t.meta.get(k))
        if isinstance(cond, dict):
            if v is None or not isinstance(v, (int, float)):
                return False
            if cond.get("min") is not None and v < cond["min"]:
                return False
            if cond.get("max") is not None and v > cond["max"]:
                return False
        elif isinstance(cond, list) and cond:
            sv = "(none)" if v is None else str(v)
            if sv not in [str(c) for c in cond]:
                return False
    return True
