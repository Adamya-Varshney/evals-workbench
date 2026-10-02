"""Trace import: parse files, guess a field mapping, normalise records into events.

Supported inputs
- JSONL (one record per line) and JSON (a list of records, or {"data"|"traces"|"records"|"rows": [...]}).
- CSV with either input/output columns or a column holding a JSON message array.
- Message arrays in OpenAI style (role, content, tool_calls, role=tool) and Anthropic style
  (content blocks: text, tool_use, tool_result), plus LangChain-ish roles (human/ai).

A mapping is a dict of dotted paths into the source record:
  {"mode": "messages"|"input_output", "messages": "...", "input": "...", "output": "...",
   "system": "...", "id": "...", "channel": "...", "channel_default": "chat",
   "prompt_version": "...", "ignore": [...]}
Everything not mapped becomes metadata (flattened one level).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

CHANNEL_SYNONYMS = {
    "sms": "sms", "text": "sms", "txt": "sms", "text message": "sms", "mms": "sms",
    "email": "email", "e-mail": "email", "mail": "email",
    "chat": "chat", "web": "chat", "webchat": "chat", "chat widget": "chat", "widget": "chat",
    "voice": "voice", "phone": "voice", "call": "voice", "ivr": "voice",
}
ROLE_SYNONYMS = {
    "human": "user", "user": "user", "customer": "user", "prospect": "user",
    "ai": "assistant", "assistant": "assistant", "bot": "assistant", "model": "assistant", "agent": "assistant",
    "system": "system", "developer": "system",
    "tool": "tool", "function": "tool", "ipython": "tool",
}
LIST_KEYS = ("data", "traces", "records", "rows", "items", "examples", "runs", "spans")


class SkipRecord(Exception):
    pass


# ---------------------------------------------------------------- parsing
def parse_file(text: str, filename: str = "") -> tuple[list[dict], str, list[dict]]:
    """Return (records, format, parse_errors). Never raises on bad lines."""
    name = filename.lower()
    text = text.lstrip("﻿")
    errors: list[dict] = []
    if name.endswith(".csv") or (not name.endswith((".json", ".jsonl")) and _looks_csv(text)):
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
        return rows, "csv", errors
    stripped = text.strip()
    if name.endswith(".json") or (stripped.startswith("[") and not name.endswith(".jsonl")):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict):
                for k in LIST_KEYS:
                    if isinstance(data.get(k), list):
                        data = data[k]
                        break
                else:
                    data = [data]
            recs = [r for r in data if isinstance(r, dict)]
            for i, r in enumerate(data):
                if not isinstance(r, dict):
                    errors.append({"line": i + 1, "reason": "record is not a JSON object"})
            return recs, "json", errors
        except json.JSONDecodeError:
            pass  # fall through to JSONL
    recs = []
    for i, line in enumerate(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append({"line": i + 1, "reason": f"invalid JSON ({e.msg})"})
            continue
        if not isinstance(obj, dict):
            errors.append({"line": i + 1, "reason": "record is not a JSON object"})
            continue
        recs.append(obj)
    return recs, "jsonl", errors


def _looks_csv(text: str) -> bool:
    first = text.strip().splitlines()[0] if text.strip() else ""
    return bool(first) and not first.startswith(("{", "[")) and "," in first


# ---------------------------------------------------------------- path helpers
def get_path(rec: Any, path: Optional[str]) -> Any:
    if not path:
        return None
    cur = rec
    for part in path.split("."):
        if isinstance(cur, str) and cur[:1] in "[{":
            cur = _maybe_json(cur)
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.lstrip("-").isdigit():
            idx = int(part)
            cur = cur[idx] if -len(cur) <= idx < len(cur) else None
        else:
            return None
        if cur is None:
            return None
    return cur


def _maybe_json(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return v
    return v


def _is_message_list(v: Any) -> bool:
    v = _maybe_json(v)
    return (
        isinstance(v, list)
        and len(v) > 0
        and all(isinstance(m, dict) for m in v)
        and sum(1 for m in v if ("role" in m or "type" in m) and ("content" in m or "tool_calls" in m)) >= max(1, len(v) // 2)
    )


def _candidate_paths(rec: dict, prefix: str = "", depth: int = 0) -> list[tuple[str, Any]]:
    out = []
    for k, v in rec.items():
        p = f"{prefix}{k}"
        out.append((p, v))
        vv = _maybe_json(v)
        if isinstance(vv, dict) and depth < 2:
            out.extend(_candidate_paths(vv, p + ".", depth + 1))
    return out


# ---------------------------------------------------------------- mapping
def guess_mapping(records: list[dict]) -> dict:
    sample = records[0] if records else {}
    paths = _candidate_paths(sample)
    m: dict[str, Any] = {"mode": "messages", "channel_default": "chat"}
    msg_paths = [p for p, v in paths if _is_message_list(v)]
    if msg_paths:
        m["messages"] = sorted(msg_paths, key=lambda p: (p.count("."), -_score_msg_key(p)))[0]
    else:
        m["mode"] = "input_output"
        lower = {p.lower(): p for p, _ in paths}
        for want, opts in (
            ("input", ["input", "inputs.input", "inputs.question", "question", "prompt", "user_message", "query", "inputs"]),
            ("output", ["output", "outputs.output", "outputs.answer", "answer", "response", "completion", "assistant_message", "outputs"]),
        ):
            for o in opts:
                if o in lower:
                    m[want] = lower[o]
                    break
    lower = {p.lower(): p for p, _ in paths}
    for key, opts in (
        ("id", ["id", "trace_id", "run_id", "span_id", "uuid", "conversation_id"]),
        ("system", ["system", "system_prompt", "inputs.system"]),
        ("channel", ["channel", "metadata.channel", "meta.channel", "medium", "source_channel"]),
        ("prompt_version", ["prompt_version", "metadata.prompt_version", "meta.prompt_version", "version"]),
    ):
        for o in opts:
            if o in lower:
                m[key] = lower[o]
                break
    return m


def _score_msg_key(p: str) -> int:
    leaf = p.split(".")[-1].lower()
    return {"messages": 3, "conversation": 2, "turns": 1}.get(leaf, 0)


# ---------------------------------------------------------------- normalisation
@dataclass
class NormTrace:
    external_id: str
    channel: str
    system_prompt: str
    events: list[dict]
    meta: dict
    prompt_version: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def n_turns(self) -> int:
        return sum(1 for e in self.events if e["role"] in ("user", "assistant") and e["content"].strip())

    @property
    def n_tool_calls(self) -> int:
        return sum(1 for e in self.events if e["role"] == "tool_call")

    @property
    def n_chars(self) -> int:
        return sum(len(e.get("content") or "") for e in self.events)

    def content_hash(self) -> str:
        body = json.dumps([(e["role"], e["content"], e.get("tool_name"), e.get("tool_args")) for e in self.events], sort_keys=True)
        return hashlib.sha256(body.encode()).hexdigest()[:24]

    def search_text(self) -> str:
        parts = [e.get("content") or "" for e in self.events]
        parts += [e.get("tool_name") or "" for e in self.events]
        return "\n".join(p for p in parts if p).lower()


def _text_of(content: Any) -> str:
    content = _maybe_json(content) if isinstance(content, str) and content.strip()[:1] == "[" and '"type"' in content else content
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, str):
                parts.append(b)
            elif isinstance(b, dict):
                if b.get("type") in ("text", "input_text", "output_text") or "text" in b:
                    parts.append(str(b.get("text", "")))
                elif b.get("type") == "image" or b.get("type") == "image_url":
                    parts.append("[image]")
        return "\n".join(parts)
    if isinstance(content, dict):
        return str(content.get("text") or json.dumps(content))
    return str(content)


def _args(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v) if v.strip() else {}
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            return {"_raw": v}
    if v is None:
        return {}
    return {"value": v}


def messages_to_events(messages: list[dict]) -> tuple[list[dict], str]:
    events: list[dict] = []
    system_parts: list[str] = []
    tool_names: dict[str, str] = {}

    def add(role, content="", **kw):
        events.append({"role": role, "content": content or "", "tool_name": kw.get("tool_name", ""),
                       "tool_args": kw.get("tool_args", {}), "tool_result": kw.get("tool_result", ""),
                       "tool_call_id": kw.get("tool_call_id", "")})

    for m in messages:
        if not isinstance(m, dict):
            continue
        role = ROLE_SYNONYMS.get(str(m.get("role") or m.get("type") or "").lower(), str(m.get("role") or "user").lower())
        content = m.get("content")
        if role == "system":
            t = _text_of(content)
            system_parts.append(t)
            continue
        if role == "tool":
            cid = str(m.get("tool_call_id") or m.get("id") or "")
            add("tool_result", tool_result=_text_of(content), tool_call_id=cid,
                tool_name=m.get("name") or tool_names.get(cid, ""))
            continue
        # Anthropic content blocks (order preserved)
        blocks = _maybe_json(content) if isinstance(content, str) and content.strip().startswith("[{") else content
        if isinstance(blocks, list) and any(isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result") for b in blocks):
            buf: list[str] = []
            for b in blocks:
                if not isinstance(b, dict):
                    buf.append(str(b))
                    continue
                t = b.get("type")
                if t == "text":
                    buf.append(b.get("text", ""))
                elif t == "tool_use":
                    if buf:
                        add(role, "\n".join(buf))
                        buf = []
                    cid = str(b.get("id", ""))
                    tool_names[cid] = b.get("name", "")
                    add("tool_call", tool_name=b.get("name", ""), tool_args=_args(b.get("input")), tool_call_id=cid)
                elif t == "tool_result":
                    if buf:
                        add(role, "\n".join(buf))
                        buf = []
                    cid = str(b.get("tool_use_id", ""))
                    add("tool_result", tool_result=_text_of(b.get("content")), tool_call_id=cid, tool_name=tool_names.get(cid, ""))
            if buf and "\n".join(buf).strip():
                add(role, "\n".join(buf))
            continue
        text = _text_of(content)
        if text.strip() or not m.get("tool_calls"):
            add(role if role in ("user", "assistant") else "user", text)
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or tc.get("name", "")
            cid = str(tc.get("id", ""))
            tool_names[cid] = name
            add("tool_call", tool_name=name, tool_args=_args(fn.get("arguments", tc.get("arguments", tc.get("input")))), tool_call_id=cid)
        if m.get("function_call"):
            fc = m["function_call"]
            add("tool_call", tool_name=fc.get("name", ""), tool_args=_args(fc.get("arguments")))
    return events, "\n\n".join(p for p in system_parts if p)


def normalize_channel(v: Any, default: str = "chat") -> str:
    if v is None or str(v).strip() == "":
        return default
    s = str(v).strip().lower()
    return CHANNEL_SYNONYMS.get(s, CHANNEL_SYNONYMS.get(s.replace("_", " ").replace("-", " "), s))


def _flatten_meta(rec: dict, used_roots: set[str], used_paths: set[str]) -> dict:
    meta: dict[str, Any] = {}
    for k, v in rec.items():
        if k in used_paths:
            continue
        vv = _maybe_json(v)
        if isinstance(vv, dict):
            for k2, v2 in vv.items():
                if f"{k}.{k2}" in used_paths:
                    continue
                if _is_scalar(v2):
                    meta[k2 if k in ("metadata", "meta", "extra", "tags") else f"{k}.{k2}"] = v2
            continue
        if k in used_roots and not _is_scalar(vv):
            continue
        if _is_scalar(vv):
            meta[k] = vv
    return meta


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def normalize_record(rec: dict, mapping: dict, index: int = 0) -> NormTrace:
    mode = mapping.get("mode", "messages")
    events: list[dict]
    system = ""
    used = set()
    if mode == "messages":
        path = mapping.get("messages")
        raw_msgs = _maybe_json(get_path(rec, path))
        if not isinstance(raw_msgs, list) or not raw_msgs:
            raise SkipRecord(f"no message array at '{path}'")
        events, system = messages_to_events(raw_msgs)
        used.add(path or "")
    else:
        inp = get_path(rec, mapping.get("input"))
        out = get_path(rec, mapping.get("output"))
        if inp in (None, "") and out in (None, ""):
            raise SkipRecord("both input and output are empty")
        events = []
        # An input column may itself hold a message array.
        if _is_message_list(inp):
            ev, system = messages_to_events(_maybe_json(inp))
            events.extend(ev)
        elif inp not in (None, ""):
            events.append(_ev("user", _text_of(_maybe_json(inp)) if not isinstance(inp, str) else inp))
        if _is_message_list(out):
            ev, _ = messages_to_events(_maybe_json(out))
            events.extend(ev)
        elif out not in (None, ""):
            events.append(_ev("assistant", _text_of(_maybe_json(out)) if not isinstance(out, str) else out))
        used.update({mapping.get("input") or "", mapping.get("output") or ""})
    if not any(e["role"] in ("user", "assistant") and e["content"].strip() for e in events) and not any(e["role"] == "tool_call" for e in events):
        raise SkipRecord("conversation has no user or assistant text")
    sys_override = get_path(rec, mapping.get("system"))
    if sys_override:
        system = _text_of(sys_override)
    for k in ("system", "id", "channel", "prompt_version"):
        if mapping.get(k):
            used.add(mapping[k])
    for p in mapping.get("ignore") or []:
        used.add(p)
    ext_id = get_path(rec, mapping.get("id"))
    channel = normalize_channel(get_path(rec, mapping.get("channel")), mapping.get("channel_default") or "chat")
    pv = get_path(rec, mapping.get("prompt_version"))
    roots = {p.split(".")[0] for p in used if p}
    meta = _flatten_meta(rec, roots, used)
    meta.pop("channel", None)
    meta["channel"] = channel
    if pv not in (None, ""):
        meta["prompt_version"] = str(pv)
    for i, e in enumerate(events):
        e["seq"] = i
    return NormTrace(
        external_id=str(ext_id) if ext_id not in (None, "") else f"row-{index + 1}",
        channel=channel,
        system_prompt=system,
        events=events,
        meta=meta,
        prompt_version=str(pv) if pv not in (None, "") else "",
        raw=rec,
    )


def _ev(role: str, content: str) -> dict:
    return {"role": role, "content": content or "", "tool_name": "", "tool_args": {}, "tool_result": "", "tool_call_id": ""}


# ---------------------------------------------------------------- redaction
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)")


def make_redactor(opts: dict):
    pats: list[tuple[re.Pattern, str]] = []
    if opts.get("emails"):
        pats.append((EMAIL_RE, "[EMAIL]"))
    if opts.get("phones"):
        pats.append((PHONE_RE, "[PHONE]"))
    for c in opts.get("custom") or []:
        if c:
            try:
                pats.append((re.compile(c), "[REDACTED]"))
            except re.error:
                pass
    if not pats:
        return None

    def red(v: Any) -> Any:
        if isinstance(v, str):
            for p, rep in pats:
                v = p.sub(rep, v)
            return v
        if isinstance(v, list):
            return [red(x) for x in v]
        if isinstance(v, dict):
            return {k: red(x) for k, x in v.items()}
        return v

    return red


def apply_redaction(t: NormTrace, opts: dict) -> NormTrace:
    red = make_redactor(opts or {})
    if not red:
        return t
    t.system_prompt = red(t.system_prompt)
    t.events = red(t.events)
    t.meta = red(t.meta)
    t.raw = red(t.raw)
    return t


def validate_regexes(custom: list[str]) -> list[str]:
    bad = []
    for c in custom or []:
        try:
            re.compile(c)
        except re.error as e:
            bad.append(f"{c}: {e}")
    return bad
