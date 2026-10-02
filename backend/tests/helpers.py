"""Test helpers: simulate a reviewer using the planted truth (tests only)."""
import json
from pathlib import Path

TRUTH = json.loads((Path(__file__).parent / "fixtures" / "planted_truth.json").read_text())

NOTE_FOR = {
    "markdown_sms": "Sent markdown bold and bullets over SMS, shows asterisks",
    "promise_no_followup": "Said it would check back and get back to them, never did",
    "ignores_constraint": "Showed a unit over the stated budget / ignored the pet or floor constraint",
    "virtual_vs_inperson": "Booked an in-person tour but told them it was a virtual tour",
    "duplicate_booking": "Created a duplicate booking instead of rescheduling the existing tour",
    "wrong_date": "Wrong date: said tomorrow but the day/date is off",
    "no_handoff": "User asked for a real person and the bot did not hand off",
    "robotic_dead_end": "Robotic dead-end reply, no alternatives offered to the lead",
}


def review_batch(client, pid, n=40, size=100, seed=5):
    client.patch(f"/api/projects/{pid}", json={"reviewer_name": "Pat"})
    b = client.post(f"/api/projects/{pid}/batches", json={"size": size, "seed": seed}).json()
    q = client.get(f"/api/projects/{pid}/review/queue", params={"batch_id": b["id"]}).json()
    for item in q[:n]:
        fails = TRUTH[item["external_id"]]["failures"]
        body = {"verdict": "fail" if fails else "pass", "batch_id": b["id"], "add_seconds": 40}
        if fails:
            body["note"] = "; ".join(NOTE_FOR[f] for f in fails)
        client.put(f"/api/projects/{pid}/reviews/{item['id']}", json=body)
    return b["id"], q


def wait_run(client, pid, run_id, suite=False, timeout=60):
    """Background jobs run after the request returns (as in production); poll until done."""
    import time

    url = f"/api/projects/{pid}/suite/runs/{run_id}/report" if suite else f"/api/projects/{pid}/runs/{run_id}"
    end = time.time() + timeout
    while time.time() < end:
        r = client.get(url).json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(0.1)
    raise AssertionError("run did not finish")
