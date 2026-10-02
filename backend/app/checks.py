"""Code-check engine. Pure functions over a normalised trace dict, so the exported bundle can reuse this file verbatim.

A trace dict looks like:
    {"id": ..., "channel": "sms", "meta": {...}, "system_prompt": "...",
     "events": [{"role": "user"|"assistant"|"tool_call"|"tool_result", "content": str,
                 "tool_name": str, "tool_args": dict, "tool_result": str}, ...]}

A check definition is either
    {"kind": "rules", "rules": [rule, ...]}      every rule is a FAILURE condition; any hit fails the trace
    {"kind": "python", "code": "def check(trace):\\n    return True"}   check() returns True when the trace PASSES
Rule types:
    regex              {"pattern", "mode": "present"|"absent", "flags": "i"}   on assistant messages
    markdown           {}                                                      markdown syntax in assistant messages
    tool_called        {"tool", "expect": "called"|"not_called"}
    tool_count_max     {"tool", "max": N}
    tool_args_required {"tool", "args": [..]}
    length             {"min": N|null, "max": N|null}                          per assistant message, in characters
    json_schema        {"schema": {...}}                                       last assistant message must be valid JSON for the schema
Any rule may carry "scope": {"facet": "channel", "values": ["sms"]}; out-of-scope traces pass that rule.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from typing import Any

RULE_TYPES = ("regex", "markdown", "tool_called", "tool_count_max", "tool_args_required", "length", "json_schema")

MARKDOWN_PATTERNS = [
    (r"\*\*[^*\n]+\*\*", "bold (**text**)"),
    (r"(?<![\w*])\*[^*\s][^*\n]*\*(?!\w)", "italic (*text*)"),
    (r"(?m)^\s{0,3}#{1,6}\s", "heading (#)"),
    (r"(?m)^\s*[-*+]\s+\S", "bullet list"),
    (r"(?m)^\s*\d+\.\s+\S", "numbered list"),
    (r"\[[^\]]+\]\([^)]+\)", "link [text](url)"),
    (r"`[^`\n]+`", "inline code"),
    (r"(?m)^\s*>\s", "block quote"),
    (r"(?<!\w)_[^_\s][^_\n]*_(?!\w)", "italic (_text_)"),
]


def _assistant_texts(trace: dict) -> list[str]:
    return [e.get("content") or "" for e in trace.get("events", []) if e.get("role") == "assistant" and (e.get("content") or "").strip()]


def _tool_calls(trace: dict, tool: str | None = None) -> list[dict]:
    return [e for e in trace.get("events", []) if e.get("role") == "tool_call" and (tool is None or e.get("tool_name") == tool)]


def facet_value(trace: dict, facet: str) -> Any:
    if facet == "channel":
        return trace.get("channel")
    return (trace.get("meta") or {}).get(facet)


def in_scope(trace: dict, scope: dict | None) -> bool:
    if not scope or not scope.get("facet") or not scope.get("values"):
        return True
    v = facet_value(trace, scope["facet"])
    return str(v).lower() in {str(x).lower() for x in scope["values"]}


def run_rule(rule: dict, trace: dict) -> tuple[bool, str]:
    """Returns (failed, reason)."""
    if not in_scope(trace, rule.get("scope")):
        return False, ""
    t = rule.get("type")
    if t == "regex":
        flags = re.I if "i" in (rule.get("flags") or "") else 0
        try:
            rx = re.compile(rule.get("pattern") or "", flags)
        except re.error as e:
            return True, f"invalid regex: {e}"
        hits = [m.group(0) for txt in _assistant_texts(trace) for m in [rx.search(txt)] if m]
        if (rule.get("mode") or "present") == "present":
            return (bool(hits), f"assistant message matches /{rx.pattern}/: {hits[0][:60]!r}" if hits else "")
        return (not hits, "" if hits else f"no assistant message matches /{rx.pattern}/")
    if t == "markdown":
        for txt in _assistant_texts(trace):
            for pat, label in MARKDOWN_PATTERNS:
                m = re.search(pat, txt)
                if m:
                    return True, f"markdown {label}: {m.group(0)[:50]!r}"
        return False, ""
    if t == "tool_called":
        called = bool(_tool_calls(trace, rule.get("tool")))
        if (rule.get("expect") or "called") == "called":
            return (not called, "" if called else f"{rule.get('tool')} was never called")
        return (called, f"{rule.get('tool')} was called" if called else "")
    if t == "tool_count_max":
        n = len(_tool_calls(trace, rule.get("tool")))
        mx = int(rule.get("max") or 0)
        return (n > mx, f"{rule.get('tool')} called {n} times (max {mx})" if n > mx else "")
    if t == "tool_args_required":
        for c in _tool_calls(trace, rule.get("tool")):
            missing = [a for a in rule.get("args") or [] if (c.get("tool_args") or {}).get(a) in (None, "")]
            if missing:
                return True, f"{rule.get('tool')} call missing {', '.join(missing)}"
        return False, ""
    if t == "length":
        lo, hi = rule.get("min"), rule.get("max")
        for txt in _assistant_texts(trace):
            if lo is not None and len(txt) < int(lo):
                return True, f"assistant message is {len(txt)} chars (< {lo})"
            if hi is not None and len(txt) > int(hi):
                return True, f"assistant message is {len(txt)} chars (> {hi})"
        return False, ""
    if t == "json_schema":
        texts = _assistant_texts(trace)
        if not texts:
            return True, "no assistant message"
        try:
            obj = json.loads(texts[-1])
        except json.JSONDecodeError as e:
            return True, f"last assistant message is not JSON ({e.msg})"
        try:
            import jsonschema

            jsonschema.validate(obj, rule.get("schema") or {})
        except ImportError:
            return False, ""
        except Exception as e:  # noqa: BLE001
            return True, f"JSON does not match schema: {str(e).splitlines()[0][:120]}"
        return False, ""
    return True, f"unknown rule type {t!r}"


def run_rules(rules: list[dict], trace: dict) -> tuple[bool, str]:
    reasons = []
    for r in rules:
        failed, why = run_rule(r, trace)
        if failed:
            reasons.append(why)
    return (bool(reasons), "; ".join(reasons) if reasons else "all rules passed")


_RUNNER = textwrap.dedent(
    """
    import json, sys
    src = sys.stdin.readline()
    traces = [json.loads(l) for l in sys.stdin if l.strip()]
    ns = {}
    try:
        exec(compile(json.loads(src), "<check>", "exec"), ns)
        fn = ns["check"]
    except Exception as e:
        print(json.dumps({"error": "could not load check(): %s: %s" % (type(e).__name__, e)}))
        sys.exit(0)
    for t in traces:
        try:
            ok = fn(t)
            print(json.dumps({"id": t.get("id"), "pass": bool(ok)}))
        except Exception as e:
            print(json.dumps({"id": t.get("id"), "error": "%s: %s" % (type(e).__name__, e)}))
    """
)


def run_python(code: str, traces: list[dict], timeout: float = 20.0) -> dict[Any, tuple[bool, str]]:
    """Run a user-supplied `check(trace) -> bool` in an isolated subprocess with a timeout.
    Returns {trace_id: (failed, reason)}."""
    payload = json.dumps(code) + "\n" + "\n".join(json.dumps(t, default=str) for t in traces) + "\n"
    try:
        proc = subprocess.run([sys.executable, "-I", "-c", _RUNNER], input=payload, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {t.get("id"): (True, f"check() timed out after {timeout:.0f}s") for t in traces}
    out: dict[Any, tuple[bool, str]] = {}
    for line in proc.stdout.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "error" in r and "id" not in r:
            return {t.get("id"): (True, r["error"]) for t in traces}
        if "error" in r:
            out[r["id"]] = (True, f"check() raised {r['error']}")
        else:
            out[r["id"]] = (not r["pass"], "check() returned False" if not r["pass"] else "check() returned True")
    for t in traces:
        out.setdefault(t.get("id"), (True, "no result from check() " + (proc.stderr.strip().splitlines() or [""])[-1][:120]))
    return out


def run_definition(defn: dict, traces: list[dict]) -> dict[Any, tuple[bool, str]]:
    if defn.get("kind") == "python":
        return run_python(defn.get("code") or "", traces)
    rules = defn.get("rules") or []
    return {t.get("id"): run_rules(rules, t) for t in traces}


def validate_definition(defn: dict) -> list[str]:
    errs = []
    if defn.get("kind") == "python":
        code = defn.get("code") or ""
        if "def check" not in code:
            errs.append("Python checks must define check(trace) -> bool")
        try:
            compile(code, "<check>", "exec")
        except SyntaxError as e:
            errs.append(f"Syntax error: {e}")
        return errs
    rules = defn.get("rules") or []
    if not rules:
        errs.append("Add at least one rule")
    for i, r in enumerate(rules):
        if r.get("type") not in RULE_TYPES:
            errs.append(f"Rule {i + 1}: unknown type {r.get('type')!r}")
        if r.get("type") == "regex":
            try:
                re.compile(r.get("pattern") or "")
            except re.error as e:
                errs.append(f"Rule {i + 1}: invalid regex ({e})")
            if not r.get("pattern"):
                errs.append(f"Rule {i + 1}: regex pattern is empty")
        if r.get("type") in ("tool_called", "tool_count_max", "tool_args_required") and not r.get("tool"):
            errs.append(f"Rule {i + 1}: choose a tool")
    return errs
