"""Public-demo content: a blank demo project to try, plus a pre-filled walkthrough project.

The walkthrough is built by driving the app's own API in-process (simulated AI), so every screen shows
real data produced by the real code paths. Its review notes come from seed/showcase_notes.json, which the
seed generator writes alongside the traces. The blank demo project never sees those notes.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from pathlib import Path

from sqlmodel import Session, select

from ..config import BACKEND, settings
from ..db import get_engine
from ..models import LLMCall, Project
from .cleanup import delete_project_cascade

log = logging.getLogger("evals.showcase")
NOTES_FILE = BACKEND / "seed" / "showcase_notes.json"
WALKTHROUGH_NAME = "Larkspur — guided walkthrough (pre-filled)"
_lock = threading.Lock()
state = {"building": False, "last_reset": None, "error": None}

RENAME = {
    "Formatting issues": "Markdown sent over SMS",
    "Temporal issues": "Wrong current date",
    "Scheduling problems": "Duplicate booking instead of reschedule",
    "Broken follow-through": "Promised follow-up never happens",
    "Search results ignore what the user asked for": "Results ignore a stated constraint",
}
SEVERITY = {
    "Markdown sent over SMS": ("high", "Prospects see raw asterisks and bullets; the brand looks broken on the main channel."),
    "Ignores requests for a human": ("catastrophic", "Angry residents get stuck in a loop; complaints and churn risk."),
    "Wrong current date": ("high", "Tours booked on the wrong day; no-shows."),
    "Duplicate booking instead of reschedule": ("high", "Double bookings clog agents' calendars."),
    "Results ignore a stated constraint": ("high", "Prospects are shown units they can't rent; trust drops."),
    "Promised follow-up never happens": ("high", "Leads silently drop."),
    "Unhelpful dead-end replies": ("low", "Missed nurturing opportunities."),
}
DECISION = {
    "Wrong current date": ("fix_now", "Inject today's date into the system prompt."),
    "Markdown sent over SMS": ("code_check", "Detectable with patterns on SMS replies."),
    "Ignores requests for a human": ("llm_judge", "Needs judgement about what counts as asking for a person."),
    "Duplicate booking instead of reschedule": ("park", "Rare so far; revisit after the next round."),
    "Results ignore a stated constraint": ("fix_now", "Pass every stated constraint (budget, pets, floor) into check_availability."),
    "Promised follow-up never happens": ("fix_now", "Tell the model it cannot follow up later; it must act now or hand off."),
    "Unhelpful dead-end replies": ("fix_now", "Add nurture instructions: sister property, notify list, current special."),
    "In-person tour described as virtual": ("fix_now", "State in the prompt that virtual tours are not offered."),
}
# Modes a reviewer adds by hand when the AI proposals miss them (name, definition, keyword in notes).
HAND_ADDED = [
    ("In-person tour described as virtual", "The assistant books an in-person tour but tells the user it is virtual.", r"virtual"),
    ("Duplicate booking instead of reschedule", "Asked to move a tour, the assistant creates a second booking instead of rescheduling.", r"booking|resched"),
    ("Wrong current date", "The assistant states or uses a date that doesn't match the conversation's actual date.", r"date"),
    ("Promised follow-up never happens", "The assistant says it will check or follow up later, and nothing follows.", r"get back|follow up|follow-up"),
    ("Results ignore a stated constraint", "Units shown break a constraint the user stated (budget, pets, floor).", r"constraint|budget"),
    ("Unhelpful dead-end replies", "When nothing matches, the assistant ends without offering any alternative.", r"dead end|gives up|no alternatives"),
    ("Markdown sent over SMS", "An SMS reply contains markdown syntax that a phone shows literally.", r"markdown|\*\*|bullet"),
    ("Ignores requests for a human", "The user explicitly asks for a person and is not handed off.", r"real person|human"),
]


def _client():
    from fastapi.testclient import TestClient

    from ..main import app

    return TestClient(app)  # no context manager: lifespan is not re-run


def _wait(c, url: str, timeout: float = 120) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        r = c.get(url).json()
        if r.get("status") in ("done", "failed"):
            return r
        time.sleep(0.2)
    raise RuntimeError(f"timed out waiting for {url}")


def build_walkthrough() -> int:
    from ..routers.projects import DEMO

    c = _client()
    notes = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    rng = random.Random(7)
    p = c.post("/api/projects", json={**DEMO, "name": WALKTHROUGH_NAME, "reviewer_name": "Demo reviewer"}).json()
    pid = p["id"]
    B = f"/api/projects/{pid}"
    c.patch(B, json={"settings": {"walkthrough": True}})
    job = c.post(f"{B}/imports", data={"demo": "true"}).json()
    c.post(f"{B}/imports/{job['id']}/commit", json={"mapping": job["mapping"], "redaction": {}})
    b1 = c.post(f"{B}/batches", json={"size": 100, "seed": 7, "name": "Round 1 — random 100"}).json()
    q = c.get(f"{B}/review/queue", params={"batch_id": b1["id"]}).json()

    # Stage 3: 80 reviews, with first-failure marks on failing traces that used tools.
    for it in q[:80]:
        note = notes.get(it["external_id"])
        body = {"verdict": "fail" if note else "pass", "batch_id": b1["id"], "add_seconds": rng.randint(22, 75)}
        if note:
            body["note"] = note
            d = c.get(f"{B}/review/trace/{it['id']}").json()
            evs = d["trace"]["events"]
            if any(e["role"] == "tool_call" for e in evs):
                asst = [e for e in evs if e["role"] == "assistant" and e["content"]]
                if asst:
                    body["first_failure_event_id"] = asst[0]["id"] if len(asst) == 1 else asst[-1]["id"]
        c.put(f"{B}/reviews/{it['id']}", json=body)

    # Stage 4: AI proposals rewritten into specific modes, AI assignments confirmed.
    for pr in c.post(f"{B}/group/propose").json():
        new = RENAME.get(pr["name"], pr["name"])
        if pr["name"].startswith("Other"):
            c.post(f"{B}/group/proposals/{pr['id']}/reject")
            continue
        c.post(f"{B}/group/proposals/{pr['id']}/accept", json={"name": new, "definition": pr["definition"],
                                                             "counts_as": f"Any trace showing: {new.lower()}.",
                                                             "does_not_count_as": "Similar wording where the behaviour did not actually happen."})
    have = {m["name"] for m in c.get(f"{B}/failure_modes").json()}
    for name, definition, _ in HAND_ADDED:
        if name not in have:
            c.post(f"{B}/failure_modes", json={"name": name, "definition": definition, "counts_as": f"Any trace showing: {name.lower()}.",
                                                "does_not_count_as": "Similar wording where the behaviour did not actually happen."})
    _assign_all(c, B)

    # Stage 5: severity, impact, order (most severe first, then by count).
    modes = [m for m in c.get(f"{B}/failure_modes").json() if not m["is_none_bucket"]]
    for m in modes:
        sev, impact = SEVERITY.get(m["name"], ("high", "Hurts the experience."))
        c.patch(f"{B}/failure_modes/{m['id']}", json={"severity": sev, "impact_note": impact})
    rank = {"catastrophic": 0, "high": 1, "low": 2}
    modes = sorted(c.get(f"{B}/failure_modes").json(), key=lambda m: (rank.get(m["severity"], 3), -m["n_labels"]))
    c.post(f"{B}/failure_modes/reorder", json={"ids": [m["id"] for m in modes if not m["is_none_bucket"]]})
    ids = {m["name"]: m["id"] for m in modes}

    # Stage 6: decisions + a fix log entry.
    for name, (dec, note) in DECISION.items():
        if name in ids:
            c.patch(f"{B}/failure_modes/{ids[name]}", json={"decision": dec, "decision_note": note})
    if "Wrong current date" in ids:
        pv = c.post(f"{B}/prompt_versions", json={"label": "v1.5", "body": "…plus: Today's date is {current_date}."}).json()
        c.post(f"{B}/fixes", json={"failure_mode_id": ids["Wrong current date"], "description": "Inject today's date into the system prompt",
                                   "prompt_version_id": pv.get("id"), "before_batch_id": b1["id"]})

    # Stage 7: code check (drafted, approved, verified, activated) and a judge (drafted, edited).
    check_id = judge_id = None
    if "Markdown sent over SMS" in ids:
        ck = c.post(f"{B}/evaluators", json={"type": "code", "failure_mode_id": ids["Markdown sent over SMS"]}).json()
        d = c.post(f"{B}/evaluators/draft_check", json={"failure_mode_id": ids["Markdown sent over SMS"]}).json()
        c.post(f"{B}/evaluators/{ck['id']}/versions", json={"definition": d["definition"], "note": "AI draft, reviewed and approved"})
        c.post(f"{B}/evaluators/{ck['id']}/preview")
        c.post(f"{B}/evaluators/{ck['id']}/activate")
        c.patch(f"{B}/evaluators/{ck['id']}", json={"where_to_run": "ci+production"})
        check_id = ck["id"]
    if "Ignores requests for a human" in ids:
        fid = ids["Ignores requests for a human"]
        jd = c.post(f"{B}/evaluators", json={"type": "judge", "failure_mode_id": fid}).json()
        d = c.post(f"{B}/evaluators/draft_judge", json={"failure_mode_id": fid}).json()["definition"]
        c.post(f"{B}/evaluators/{jd['id']}/versions", json={"definition": d, "context_scope": ["conversation", "tool_calls"], "note": "AI draft, edited"})
        c.patch(f"{B}/evaluators/{jd['id']}", json={"where_to_run": "production"})
        # Stage 8: ground truth from error analysis, dev loop, final validation.
        c.post(f"{B}/ground_truth/{fid}/seed")
        qq = c.get(f"{B}/ground_truth/{fid}/queue", params={"limit": 200}).json()
        for it in qq["items"]:
            note = (notes.get(it["external_id"]) or "").lower()
            present = "real person" in note or "for a human" in note
            c.put(f"{B}/ground_truth/{fid}/{it['trace_id']}",
                  json={"label": present, "critique": "Asked for a person; no handoff." if present else "No request for a person, or handed off."})
        r = c.post(f"{B}/evaluators/{jd['id']}/run", json={"split": "dev"})
        if r.status_code == 200:
            _wait(c, f"{B}/runs/{r.json()['run_id']}")
            r = c.post(f"{B}/evaluators/{jd['id']}/run", json={"split": "test"})
            if r.status_code == 200:
                _wait(c, f"{B}/runs/{r.json()['run_id']}")
        judge_id = jd["id"]

    # Stage 9: a second round, suite runs on both batches, comparison and an experiment.
    b2 = c.post(f"{B}/batches", json={"size": 40, "seed": 11, "name": "Round 2 — after prompt v1.5", "params": {"exclude_reviewed": True}}).json()
    q2 = c.get(f"{B}/review/queue", params={"batch_id": b2["id"]}).json()
    for it in q2[:20]:
        note = notes.get(it["external_id"])
        c.put(f"{B}/reviews/{it['id']}", json={"verdict": "fail" if note else "pass", "note": note or "", "batch_id": b2["id"],
                                               "add_seconds": rng.randint(20, 60)})
    _assign_all(c, B)
    runs = []
    for bid in (b1["id"], b2["id"]):
        rr = c.post(f"{B}/suite/run", json={"batch_id": bid})
        if rr.status_code == 200:
            _wait(c, f"{B}/suite/runs/{rr.json()['run_id']}/report")
            runs.append(rr.json()["run_id"])
    if len(runs) == 2:
        c.post(f"{B}/experiments", json={"hypothesis": "Adding the plain-text SMS rule (prompt v1.4) reduces markdown on SMS",
                                         "change": "Prompt v1.4 for new traffic", "result": "See deltas; no regression in handoffs",
                                         "run_a_id": runs[0], "run_b_id": runs[1]})
    log.info("walkthrough built: project %s (check %s, judge %s)", pid, check_id, judge_id)
    return pid


def _assign_all(c, B: str) -> None:
    """AI suggestions for every unassigned failing note, confirmed; leftovers matched to hand-added modes by keyword."""
    c.post(f"{B}/group/suggest", json={"scope": "unassigned"})
    for n in c.get(f"{B}/group/notes").json():
        if n["suggestion"]:
            c.post(f"{B}/group/suggestions/{n['suggestion']['id']}/accept", json={})
    none_id = c.get(f"{B}/group/summary").json()["none_id"]
    modes = {m["name"]: m["id"] for m in c.get(f"{B}/failure_modes").json()}
    for n in c.get(f"{B}/group/notes").json():
        labels = [lab["failure_mode_id"] for lab in n["labels"]]
        if n["verdict"] != "fail" or (labels and none_id not in labels):
            continue
        hits = [modes[name] for name, _, kw in HAND_ADDED if re.search(kw, n["note"].lower()) and name in modes]
        if hits:
            c.put(f"{B}/group/labels/{n['review_id']}", json={"failure_mode_ids": hits})


def reset_demo() -> None:
    """Wipe everything and rebuild the blank demo project + the walkthrough."""
    with _lock:
        state["building"] = True
        state["error"] = None
        try:
            with Session(get_engine()) as s:
                for p in s.exec(select(Project)).all():
                    delete_project_cascade(s, p)
                for call in s.exec(select(LLMCall)).all():
                    s.delete(call)
                s.commit()
            c = _client()
            demo = c.post("/api/projects/demo").json()
            job = c.post(f"/api/projects/{demo['id']}/imports", data={"demo": "true"}).json()
            c.post(f"/api/projects/{demo['id']}/imports/{job['id']}/commit", json={"mapping": job["mapping"], "redaction": {}})
            build_walkthrough()
            state["last_reset"] = time.time()
        except Exception as e:  # noqa: BLE001
            log.exception("demo reset failed")
            state["error"] = f"{type(e).__name__}: {e}"
        finally:
            state["building"] = False


def start_demo_scheduler() -> None:
    def loop():
        reset_demo()
        while True:
            time.sleep(max(0.1, settings.demo_reset_hours) * 3600)
            reset_demo()

    threading.Thread(target=loop, name="demo-reset", daemon=True).start()


def exists() -> bool:
    return Path(NOTES_FILE).exists()
