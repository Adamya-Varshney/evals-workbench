"""Mock responders for evaluator drafting and judging (LLM_MODE=mock)."""
from __future__ import annotations

import hashlib
import re

from .mock import _GROUPS, responder


@responder("draft_code_check")
def _draft_check(ctx: dict, prompt: str) -> dict:
    text = (ctx.get("name", "") + " " + ctx.get("definition", "") + " " + " ".join(ctx.get("examples", []))).lower()
    tools = ctx.get("tools", [])
    if re.search(r"markdown|bold|bullet|asterisk|format", text):
        return {"explanation": "Markdown syntax is detectable with patterns, and the failure only matters on SMS, so the rule is scoped to the sms channel.",
                "rules": [{"type": "markdown", "scope": {"facet": "channel", "values": ["sms"]}}]}
    if re.search(r"duplicate|double|instead of resched", text) and "schedule_tour" in tools:
        return {"explanation": "This is an if/else on the trace, but a conditional one: if lookup_tours found an existing booking, schedule_tour "
                               "should not be called. The rule builder cannot express 'after', so use a custom Python check, e.g. "
                               "fail when 'lookup_tours' and 'schedule_tour' are both called and 'reschedule_tour' is not.",
                "rules": []}
    if re.search(r"human|person|hand ?off|agent", text) and "handoff_to_human" in tools:
        return {"explanation": "Whether the user explicitly asked for a person depends on wording and context; a code check can only see whether "
                               "handoff_to_human was called, not whether it should have been. This is better as an LLM judge.",
                "rules": []}
    return {"explanation": "This failure needs judgement about context, so it cannot be written as a reliable if/else on the trace. Consider an LLM judge.",
            "rules": []}


_JUDGE_LIBRARY = {
    "handoff": (["The user explicitly asks to speak with a person, human, agent, representative or the office, and the assistant does not call handoff_to_human.",
                 "The user repeats a request for a human after an unhelpful reply, and the assistant keeps answering itself.",
                 "The assistant says it will connect the user to someone but no handoff_to_human call follows."],
                ["The user is frustrated but never asks for a person.",
                 "handoff_to_human is called after the request, even if the reply text is brief.",
                 "The assistant hands off proactively for a policy reason without being asked."]),
    "markdown": (["An assistant message on SMS contains markdown syntax: **bold**, bullet lines starting with - or *, # headings, [text](url) links or backticks."],
                 ["Plain-text lists written as sentences or separated by semicolons.", "Email or chat messages (not SMS)."]),
}


def _judge_kind(name: str, defn: dict) -> str:
    t = (name + " " + " ".join(defn.get("failure_when", []))).lower()
    best, hits = "generic", 0
    for g, rx, *_ in _GROUPS:
        n = len(re.findall(rx, t))
        if n > hits:
            best, hits = g, n
    return {"formatting": "markdown"}.get(best, best)


@responder("draft_judge")
def _draft_judge(ctx: dict, prompt: str) -> dict:
    kind = _judge_kind(ctx.get("name", ""), {"failure_when": [ctx.get("definition", ""), ctx.get("counts_as", "")]})
    if kind in _JUDGE_LIBRARY:
        fw, nf = _JUDGE_LIBRARY[kind]
        return {"failure_when": fw, "not_failure_when": nf}
    fw = [x.strip() for x in [ctx.get("definition", ""), ctx.get("counts_as", "")] if x.strip()] or [f"The trace shows: {ctx.get('name')}"]
    nf = [x.strip() for x in [ctx.get("does_not_count_as", "")] if x.strip()] or ["The trace does not clearly show the behaviour described above."]
    return {"failure_when": fw, "not_failure_when": nf}


ASK_HUMAN = (r"real person|\bperson\b|human|representative|speak (with|to) |talk to someone|\bagent\b"
             r"|connect me|transfer me|someone call me")


def heuristic(kind: str, tr: dict) -> tuple[bool, str]:
    ev = tr.get("events", [])
    users = " ".join(e["content"] for e in ev if e["role"] == "user").lower()
    asst = [e["content"] for e in ev if e["role"] == "assistant" and e["content"]]
    tools = [e for e in ev if e["role"] == "tool_call"]
    names = [t["tool_name"] for t in tools]
    if kind == "handoff":
        if not re.search(ASK_HUMAN, users):
            return False, "The user never asks for a person, so a missed handoff is not possible here."
        if "handoff_to_human" in names:
            return False, "The user asks for a person and the assistant calls handoff_to_human."
        return True, "The user explicitly asks for a person, but the assistant keeps replying itself and never calls handoff_to_human."
    if kind == "markdown":
        if tr.get("channel") != "sms":
            return False, "Not an SMS conversation."
        for a in asst:
            if re.search(r"\*\*|(?m)^\s*[-*]\s|(?m)^#|\[[^\]]+\]\(", a):
                return True, "An SMS reply contains markdown syntax that a phone would show literally."
        return False, "SMS replies are plain text."
    if kind == "followup":
        last = asst[-1].lower() if asst else ""
        if re.search(r"get back to you|follow up|check (on|with)|look into|as soon as i hear", last):
            return True, "The assistant promises to check and get back, and the conversation ends without any follow-up action."
        return False, "No unfulfilled promise to follow up."
    if kind == "tour_type":
        said_virtual = any("virtual tour" in a.lower() and "don't offer virtual" not in a.lower() for a in asst)
        booked = [t for t in tools if t["tool_name"] == "schedule_tour"]
        if said_virtual and booked and all(t["tool_args"].get("tour_type") == "in_person" for t in booked):
            return True, "The tour booked is in person, but the assistant calls it virtual."
        return False, "Tour type described matches the booking."
    if kind == "duplicate":
        if "lookup_tours" in names and "schedule_tour" in names and "reschedule_tour" not in names:
            return True, "An existing booking was found, but the assistant created a new one instead of rescheduling."
        return False, "No duplicate booking."
    if kind == "deadend":
        last = asst[-1].lower() if asst else ""
        joined = " ".join(asst).lower()
        if re.search(r"anything else|check back later|have a (nice|great) day|no units|0 results|no availability", last) and not re.search(r"notify|waitlist|sister|special|tour", joined):
            return True, "The assistant ends with a generic dead-end reply and offers no alternative."
        return False, "The assistant offers a way forward."
    return False, "No clear evidence of the failure in this trace."


@responder("run_judge")
def _run_judge(ctx: dict, prompt: str) -> dict:
    kind = _judge_kind(ctx.get("mode", ""), ctx.get("definition") or {})
    failure, critique = heuristic(kind, ctx.get("trace", {}))
    # A little deterministic disagreement, so validation numbers look like a real judge's.
    h = int(hashlib.sha256((ctx.get("trace", {}).get("external_id", "") + kind).encode()).hexdigest(), 16) % 100
    if h < 3 and not failure:
        failure = True
        critique += " (Uncertain reading of this trace.)"
    return {"critique": critique, "failure": failure}
