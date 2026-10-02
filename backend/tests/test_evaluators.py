from tests.helpers import TRUTH, review_batch, wait_run

MODES = {
    "markdown_sms": "Markdown sent over SMS",
    "no_handoff": "Missed human handoff",
    "promise_no_followup": "Promised follow-up never happens",
    "ignores_constraint": "Results ignore stated constraint",
    "virtual_vs_inperson": "In-person tour called virtual",
    "duplicate_booking": "Duplicate booking instead of reschedule",
    "wrong_date": "Wrong current date",
    "robotic_dead_end": "Dead-end reply with no alternative",
}


def setup_taxonomy(client, pid, n=120):
    """Review n traces and label notes with the planted truth (stands in for a human doing axial coding)."""
    bid, q = review_batch(client, pid, n=n, size=120)
    base = f"/api/projects/{pid}"
    ids = {}
    for key, name in MODES.items():
        ids[key] = client.post(f"{base}/failure_modes", json={"name": name, "definition": f"{name}.", "counts_as": "x", "does_not_count_as": "y"}).json()["id"]
    by_trace = {i["id"]: i["external_id"] for i in q}
    for n_ in client.get(f"{base}/group/notes").json():
        fails = TRUTH[by_trace[n_["trace_id"]]]["failures"]
        if fails:
            client.put(f"{base}/group/labels/{n_['review_id']}", json={"failure_mode_ids": [ids[f] for f in fails]})
    return bid, q, ids


def test_decide_and_fix_log(demo):
    client, pid, _ = demo
    base = f"/api/projects/{pid}"
    bid, q, ids = setup_taxonomy(client, pid, n=60)
    client.patch(f"{base}/failure_modes/{ids['wrong_date']}", json={"decision": "fix_now", "decision_note": "add today's date to the prompt"})
    client.patch(f"{base}/failure_modes/{ids['markdown_sms']}", json={"decision": "code_check"})
    client.patch(f"{base}/failure_modes/{ids['no_handoff']}", json={"decision": "llm_judge"})
    for k in ("ignores_constraint", "promise_no_followup", "robotic_dead_end"):
        client.patch(f"{base}/failure_modes/{ids[k]}", json={"decision": "llm_judge"})
    board = client.get(f"{base}/decide").json()
    assert {m["decision"] for m in board["modes"]} >= {"fix_now", "code_check", "llm_judge"}
    assert any("judges" in w for w in board["warnings"])  # 4 judges planned > soft guidance
    pv = client.post(f"{base}/prompt_versions", json={"label": "v1.5", "body": "...Today's date is {date}."}).json()
    client.post(f"{base}/fixes", json={"failure_mode_id": ids["wrong_date"], "description": "Inject current date", "prompt_version_id": pv["id"], "before_batch_id": bid})
    fx = client.get(f"{base}/fixes").json()[0]
    assert fx["awaiting"] is True and fx["before"]["n"] == 60 and fx["prompt_version"] == "v1.5"
    # next batch reviewed -> after rate appears; a later round shows quick tags
    b2 = client.post(f"{base}/batches", json={"size": 20, "seed": 9, "params": {"exclude_reviewed": True}}).json()
    assert client.get(base).json()["review_round"] == 2
    q2 = client.get(f"{base}/review/queue", params={"batch_id": b2["id"]}).json()
    d = client.get(f"{base}/review/trace/{q2[0]['id']}").json()
    assert len(d["quick_tags"]) == len(MODES)
    for it in q2:
        client.put(f"{base}/reviews/{it['id']}", json={"verdict": "pass", "batch_id": b2["id"]})
    fx = client.get(f"{base}/fixes").json()[0]
    assert fx["awaiting"] is False and fx["after"]["n"] == 20 and fx["after_batch_id"] == b2["id"]


def test_markdown_code_check_flow(demo):
    client, pid, _ = demo
    base = f"/api/projects/{pid}"
    setup_taxonomy(client, pid)
    fm = [m for m in client.get(f"{base}/failure_modes").json() if m["name"] == MODES["markdown_sms"]][0]
    ev = client.post(f"{base}/evaluators", json={"type": "code", "failure_mode_id": fm["id"]}).json()
    assert client.post(f"{base}/evaluators/{ev['id']}/activate").status_code == 409
    draft = client.post(f"{base}/evaluators/draft_check", json={"failure_mode_id": fm["id"]}).json()
    assert draft["definition"]["rules"][0]["type"] == "markdown"
    assert client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": {"kind": "rules", "rules": [{"type": "regex", "pattern": "("}]}}).status_code == 400
    v = client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": draft["definition"], "note": "AI draft, approved"}).json()
    assert v["version"] == 2
    prev = client.post(f"{base}/evaluators/{ev['id']}/preview").json()
    m = prev["metrics"]
    assert prev["can_activate"] and m["tpr"] == 1.0 and m["tnr"] >= 0.97, m
    act = client.post(f"{base}/evaluators/{ev['id']}/activate").json()
    assert act["status"] == "active" and act["active_version_id"] == v["id"]
    # editing the check demotes it until re-verified
    client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": {"kind": "rules", "rules": [{"type": "markdown"}]}})
    assert client.get(f"{base}/evaluators/{ev['id']}").json()["status"] == "draft"


def test_handoff_judge_validation(demo):
    client, pid, _ = demo
    base = f"/api/projects/{pid}"
    bid, q, ids = setup_taxonomy(client, pid, n=80)
    fid = ids["no_handoff"]
    ev = client.post(f"{base}/evaluators", json={"type": "judge", "failure_mode_id": fid}).json()
    assert client.post(f"{base}/evaluators", json={"type": "judge", "failure_mode_id": fid}).status_code == 409
    draft = client.post(f"{base}/evaluators/draft_judge", json={"failure_mode_id": fid}).json()["definition"]
    assert any("handoff_to_human" in x for x in draft["failure_when"])
    v = client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": draft, "context_scope": ["conversation", "tool_calls"]}).json()
    pr = client.post(f"{base}/evaluators/{ev['id']}/judge_prompt", json={"definition": draft, "context_scope": ["conversation", "tool_calls"]}).json()
    assert "It is NOT a failure when" in pr["prompt"] and "<trace>" in pr["prompt"]

    seeded = client.post(f"{base}/ground_truth/{fid}/seed").json()
    assert seeded["seeded"] == 80
    # focused queue: label the remaining 40 traces using the truth (the human, in the real app)
    while True:
        qq = client.get(f"{base}/ground_truth/{fid}/queue", params={"limit": 50}).json()
        if not qq["items"]:
            break
        for it in qq["items"]:
            present = "no_handoff" in TRUTH[it["external_id"]]["failures"]
            client.put(f"{base}/ground_truth/{fid}/{it['trace_id']}", json={"label": present, "critique": "asked for a person, no handoff" if present else "fine"})
    gt = client.get(f"{base}/ground_truth/{fid}").json()
    assert gt["total"] == 120 and gt["low_confidence"] is True
    c = gt["counts"]
    assert c["dev"]["pos"] >= 2 and c["test"]["pos"] >= 2 and c["train"]["pos"] >= 1
    assert 0.10 <= sum(c["train"].values()) / 120 <= 0.20

    # positives must carry a critique; split never changes on correction
    one = gt["rows"][0]
    assert client.put(f"{base}/ground_truth/{fid}/{one['trace_id']}", json={"label": True, "critique": ""}).status_code == 400

    run = client.post(f"{base}/evaluators/{ev['id']}/run", json={"split": "dev"}).json()
    r = wait_run(client, pid, run["run_id"])
    assert r["status"] == "done", r["error"]
    m = r["metrics"]
    assert m["tpr"] is not None and m["tnr"] > 0.8 and m["n"] == c["dev"]["pos"] + c["dev"]["neg"]
    assert m["always_pass_agreement"] is not None
    assert all(row["outcome"] in ("agree", "missed failure", "false alarm") for row in r["rows"])
    # cached second run: no new LLM calls
    calls_before = client.get("/api/llm_calls").json()["totals"]["calls"]
    wait_run(client, pid, client.post(f"{base}/evaluators/{ev['id']}/run", json={"split": "dev"}).json()["run_id"])
    assert client.get("/api/llm_calls").json()["totals"]["calls"] == calls_before

    # few-shot from train only
    train = [g for g in gt["rows"] if g["split"] == "train"]
    dev = [g for g in gt["rows"] if g["split"] == "dev"]
    assert client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": draft, "few_shot_ids": [dev[0]["id"]]}).status_code == 400
    v3 = client.post(f"{base}/evaluators/{ev['id']}/versions", json={"definition": draft, "context_scope": ["conversation", "tool_calls"], "few_shot_ids": [train[0]["id"]]}).json()
    assert v3["version"] == 3

    fin = client.post(f"{base}/evaluators/{ev['id']}/run", json={"split": "test"}).json()
    f = wait_run(client, pid, fin["run_id"])
    assert f["status"] == "done" and f["metrics"]["passed"] is True, f["metrics"]
    e = client.get(f"{base}/evaluators/{ev['id']}").json()
    assert e["status"] == "validated" and e["active_version_id"] == v3["id"]
    assert e["version_table"][0]["test"]["tpr"] >= 0.8
