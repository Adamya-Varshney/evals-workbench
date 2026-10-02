import json
from pathlib import Path

TRUTH = Path(__file__).parent / "fixtures" / "planted_truth.json"


def test_seed_import_report(demo):
    client, pid, rep = demo
    assert rep["imported"] == 120
    assert rep["skipped"] == 3
    reasons = " ".join(r["reason"] for r in rep["skipped_rows"])
    assert "invalid JSON" in reasons and "duplicate" in reasons and "no message array" in reasons
    assert set(rep["channels"]) == {"sms", "chat", "email", "voice"}


def test_seed_truth_matches_and_is_not_served(demo):
    client, pid, _ = demo
    truth = json.loads(TRUTH.read_text())
    traces = client.get(f"/api/projects/{pid}/traces?limit=500").json()
    ids = {t["external_id"] for t in traces["items"]}
    assert ids == set(truth)
    clean = sum(1 for v in truth.values() if not v["failures"])
    assert 0.55 <= clean / len(truth) <= 0.60
    # Planted labels must never reach the UI: no API payload mentions them.
    one = client.get(f"/api/projects/{pid}/traces/{traces['items'][0]['id']}?raw=true").text
    for word in ("planted", "failures", "markdown_sms", "no_handoff"):
        assert word not in one


def test_mapping_preview_renders_three(demo):
    client, pid, _ = demo
    job = client.post(f"/api/projects/{pid}/imports", data={"demo": "true"}).json()
    assert {"path": "messages"} .items() <= {"path": "messages"}.items()
    assert any(f["path"] == "user_feedback" for f in job["fields"])
    pv = client.post(f"/api/projects/{pid}/imports/{job['id']}/preview", json={"mapping": job["mapping"], "redaction": {"phones": True}}).json()
    assert len(pv["traces"]) == 3
    assert all(t["events"] for t in pv["traces"])
    assert not any("512-555" in json.dumps(t) for t in pv["traces"])
    # Re-importing the same file skips everything as duplicates.
    rep = client.post(f"/api/projects/{pid}/imports/{job['id']}/commit", json={"mapping": job["mapping"], "redaction": {}}).json()
    assert rep["imported"] == 0


def test_batch_of_100_with_facets_and_status(demo):
    client, pid, _ = demo
    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["stages"][0]["status"] == "in_progress"  # reviewer name missing on the demo
    assert st["stages"][1]["status"] == "in_progress"
    b = client.post(f"/api/projects/{pid}/batches", json={"size": 100, "method": "random", "seed": 1}).json()
    assert b["size"] == 100 and b["reasons"] == {"random": 100}
    strat = client.post(f"/api/projects/{pid}/batches", json={"size": 40, "method": "stratified", "params": {"facet": "channel"}, "seed": 2}).json()
    assert strat["size"] == 40 and strat["reasons"]["random"] >= 8
    neg = client.post(f"/api/projects/{pid}/batches", json={"size": 30, "method": "negative_feedback", "seed": 3}).json()
    assert neg["reasons"]["random"] >= 6 and neg["reasons"].get("negative_feedback", 0) > 0
    out = client.post(f"/api/projects/{pid}/batches", json={"size": 20, "method": "outliers", "params": {"by": "n_turns"}}).json()
    assert out["reasons"]["random"] == 4 and out["reasons"]["outlier"] == 16
    facets = client.get(f"/api/projects/{pid}/facets").json()
    keys = {f["key"] for f in facets}
    assert {"channel", "property", "prompt_version", "user_feedback", "latency_ms"} <= keys
    sms = client.get(f"/api/projects/{pid}/traces", params={"filters": json.dumps({"channel": ["sms"]})}).json()
    assert sms["total"] > 20 and all(i["channel"] == "sms" for i in sms["items"])
    q = client.get(f"/api/projects/{pid}/traces", params={"q": "virtual"}).json()
    assert q["total"] > 0
    client.patch(f"/api/projects/{pid}", json={"reviewer_name": "Adamya"})
    st = client.get(f"/api/projects/{pid}/status").json()
    assert st["stages"][0]["status"] == "done" and st["stages"][1]["status"] == "done"
    assert st["stages"][2]["status"] == "ready"
    assert st["next"]["key"] == "review"
    assert st["ai"]["unlocked"] is False


def test_prompt_versions_created_from_import(demo):
    client, pid, _ = demo
    vs = client.get(f"/api/projects/{pid}/prompt_versions").json()
    assert {v["label"] for v in vs} == {"v1.3", "v1.4"}
    assert "plain text only" in next(v for v in vs if v["label"] == "v1.4")["body"]


def test_templates_editable(client):
    ts = client.get("/api/templates").json()
    assert {"propose_categories", "suggest_assignments", "run_judge", "draft_judge"} <= {t["key"] for t in ts}
    client.put("/api/templates/run_judge", json={"body": "custom"})
    assert next(t for t in client.get("/api/templates").json() if t["key"] == "run_judge")["body"] == "custom"
    client.post("/api/templates/run_judge/reset")
    assert next(t for t in client.get("/api/templates").json() if t["key"] == "run_judge")["body"] != "custom"


def test_mock_llm_logs_calls(client):
    from app.llm.client import call_structured

    r = call_structured("ping", "hello there", {"type": "object"})
    assert r["data"]["ok"] is True
    calls = client.get("/api/llm_calls").json()
    assert calls["totals"]["calls"] == 1 and calls["calls"][0]["mode"] == "mock"
