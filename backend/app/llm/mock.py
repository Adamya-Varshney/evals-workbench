"""Deterministic canned responses for LLM_MODE=mock.

Each responder receives `ctx`, the structured data the caller already holds (notes, failure modes,
trace text...), so it can return plausible, schema-valid output without parsing prompts.
Responders are registered per job name.
"""
from __future__ import annotations

from typing import Callable

_RESPONDERS: dict[str, Callable[[dict, str], dict]] = {}


def responder(job: str):
    def deco(fn):
        _RESPONDERS[job] = fn
        return fn

    return deco


def respond(job: str, ctx: dict, prompt: str) -> dict:
    from . import mock_evals  # noqa: F401  (registers more responders)

    fn = _RESPONDERS.get(job)
    if fn is None:
        raise RuntimeError(f"No mock responder for job '{job}'")
    return fn(ctx, prompt)


@responder("ping")
def _ping(ctx: dict, prompt: str) -> dict:
    return {"ok": True, "echo": prompt[:40]}


@responder("find_similar")
def _find_similar(ctx: dict, prompt: str) -> dict:
    cands = sorted(ctx.get("candidates", []), key=lambda c: -c["score"])[: ctx.get("k", 5)]
    return {"matches": [{"id": c["id"], "why": f"Shares much of the same wording and intent (overlap {c['score']:.0%})."} for c in cands]}


# --- keyword groups used by the axial-coding mocks -------------------------------------------
import re as _re  # noqa: E402

_GROUPS = [
    ("formatting", r"markdown|bold|bullet|asterisk|\*\*|format|heading|link syntax|symbols",
     "Formatting issues", "Replies contain formatting the channel cannot display."),
    ("followup", r"check (back|on|with)|get back|follow[ -]?up|never (did|came|followed)|promis|said (it|they|he|she) would|will look into",
     "Broken follow-through", "The assistant says it will do something later and the conversation shows it never does."),
    ("constraint", r"budget|over (my|the|their)|price|constraint|pet|dog|ground floor|floor|ignor|didn't filter|filter",
     "Search results ignore what the user asked for", "Units shown do not respect a constraint the user stated."),
    ("tour_type", r"virtual|in[ -]person|video",
     "Tour type mix-up", "The tour type the assistant describes differs from what was booked."),
    ("duplicate", r"duplicate|double|twice|second booking|two bookings|instead of (moving|resched)|new booking",
     "Scheduling problems", "Tour changes create extra bookings or otherwise go wrong."),
    ("date", r"\bdate\b|wrong day|today|weekday|calendar|\bday\b|in the past",
     "Temporal issues", "Problems with dates and days."),
    ("handoff", r"\bhuman\b|\bperson\b|\bagent\b|representative|hand ?off|transfer|escalat|speak to",
     "Ignores requests for a human", "The user explicitly asks for a person and is not handed off."),
    ("deadend", r"dead[ -]?end|robotic|no alternative|alternatives|nurtur|lead|gave up|unhelpful|generic|anything else",
     "Unhelpful dead-end replies", "When nothing matches, the assistant ends the conversation instead of offering alternatives."),
]


def _groups_of(text: str) -> list[str]:
    t = (text or "").lower()
    return [g for g, rx, *_ in _GROUPS if _re.search(rx, t)]


@responder("propose_categories")
def _propose(ctx: dict, prompt: str) -> dict:
    buckets: dict[str, list[int]] = {}
    for n in ctx.get("notes", []):
        for g in _groups_of(n["note"]) or ["_other"]:
            buckets.setdefault(g, []).append(n["id"])
    meta = {g: (name, d) for g, _, name, d in _GROUPS}
    ranked = sorted((g for g in buckets if g != "_other"), key=lambda g: -len(buckets[g]))[:6]
    props = [{"name": meta[g][0], "definition": meta[g][1], "example_note_ids": buckets[g][:5]} for g in ranked]
    if len(props) < 6 and buckets.get("_other"):
        props.append({"name": "Other quality issues", "definition": "Assorted problems that did not fit elsewhere.", "example_note_ids": buckets["_other"][:5]})
    return {"proposals": props}


@responder("suggest_assignments")
def _suggest(ctx: dict, prompt: str) -> dict:
    def best_group(text: str) -> set:
        hits = {g: len(_re.findall(rx, text.lower())) for g, rx, *_ in _GROUPS}
        top = max(hits.values()) if hits else 0
        return {g for g, h in hits.items() if h == top and h > 0}

    mode_groups = {m["id"]: best_group(" ".join([m["name"], m.get("definition", ""), m.get("counts_as", "")])) for m in ctx.get("modes", [])}
    out = []
    for n in ctx.get("notes", []):
        ng = set(_groups_of(n["note"]))
        ids = [mid for mid, gs in mode_groups.items() if ng & gs]
        if not ids:
            words = set(_re.findall(r"[a-z]{5,}", n["note"].lower()))
            ids = [m["id"] for m in ctx.get("modes", []) if len(words & set(_re.findall(r"[a-z]{5,}", (m["name"] + " " + m.get("definition", "")).lower()))) >= 2]
        out.append({"note_id": n["id"], "failure_mode_ids": ids or [ctx["none_id"]],
                    "rationale": "Matches the definition of the selected mode(s)." if ids else "No existing failure mode covers this note."})
    return {"assignments": out}
