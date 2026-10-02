"""Definition of done, steps 5–9, in mock mode: build + validate, run on a second batch, export, run run_evals.py."""
import io
import json
import subprocess
import sys
import zipfile

from tests.helpers import TRUTH, wait_run
from tests.test_evaluators import setup_taxonomy


def _validated_suite(client, pid):
    base = f"/api/projects/{pid}"
    bid, q, ids = setup_taxonomy(client, pid, n=80)
    # code check: markdown in SMS
    ck = client.post(f"{base}/evaluators", json={"type": "code", "failure_mode_id": ids["markdown_sms"]}).json()
    client.post(f"{base}/evaluators/{ck['id']}/versions", json={"definition": {"kind": "rules", "rules": [{"type": "markdown", "scope": {"facet": "channel", "values": ["sms"]}}]}})
    client.post(f"{base}/evaluators/{ck['id']}/preview")
    assert client.post(f"{base}/evaluators/{ck['id']}/activate").json()["status"] == "active"
    # judge: missed handoff
    jd = client.post(f"{base}/evaluators", json={"type": "judge", "failure_mode_id": ids["no_handoff"]}).json()
    d = client.post(f"{base}/evaluators/draft_judge", json={"failure_mode_id": ids["no_handoff"]}).json()["definition"]
    client.post(f"{base}/evaluators/{jd['id']}/versions", json={"definition": d, "context_scope": ["conversation", "tool_calls"]})
    client.post(f"{base}/ground_truth/{ids['no_handoff']}/seed")
    qq = client.get(f"{base}/ground_truth/{ids['no_handoff']}/queue", params={"limit": 200}).json()
    for it in qq["items"]:
        present = "no_handoff" in TRUTH[it["external_id"]]["failures"]
        client.put(f"{base}/ground_truth/{ids['no_handoff']}/{it['trace_id']}", json={"label": present, "critique": "asked for a person" if present else "ok"})
    wait_run(client, pid, client.post(f"{base}/evaluators/{jd['id']}/run", json={"split": "dev"}).json()["run_id"])
    fin = client.post(f"{base}/evaluators/{jd['id']}/run", json={"split": "test"}).json()
    assert wait_run(client, pid, fin["run_id"])["metrics"]["passed"]
    return bid, ids, ck, jd


def test_run_compare_experiment_export(demo, tmp_path):
    client, pid, _ = demo
    base = f"/api/projects/{pid}"
    bid, ids, ck, jd = _validated_suite(client, pid)
    # second batch (fresh sample of all 120 traces)
    b2 = client.post(f"{base}/batches", json={"size": 60, "seed": 21}).json()
    est = client.get(f"{base}/suite/estimate", params={"batch_id": b2["id"]}).json()
    assert {e["id"] for e in est["evaluators"]} == {ck["id"], jd["id"]}
    assert est["llm_calls"] + est["cached"] == 60 and est["cached"] > 0  # traces judged during validation are cached
    run2 = client.post(f"{base}/suite/run", json={"batch_id": b2["id"]}).json()["run_id"]
    wait_run(client, pid, run2, suite=True)
    rep = client.get(f"{base}/suite/runs/{run2}/report", params={"facet": "channel"}).json()
    assert rep["status"] == "done" and rep["n_traces"] == 60
    judge = next(e for e in rep["evaluators"] if e["type"] == "judge")
    check = next(e for e in rep["evaluators"] if e["type"] == "code")
    assert judge["raw"]["n"] == 60 and judge["raw"]["ci"][0] is not None
    assert judge["corrected"] is not None, judge["corrected_note"]
    lo, hi = judge["corrected"]["ci"]
    assert 0 <= lo <= judge["corrected"]["theta"] <= hi <= 1
    assert check["corrected"] is None and set(check["by_facet"]) <= {"sms", "chat", "email", "voice"}
    assert rep["pass_all"]["n"] == 60 and rep["pass_all_by_facet"]

    run1 = client.post(f"{base}/suite/run", json={"batch_id": bid}).json()["run_id"]
    wait_run(client, pid, run1, suite=True)
    cmp_ = client.get(f"{base}/suite/compare", params={"a": run1, "b": run2}).json()
    assert len(cmp_["rows"]) == 2 and all(r["delta"] is not None for r in cmp_["rows"])
    x = client.post(f"{base}/experiments", json={"hypothesis": "v1.4 SMS rule reduces markdown", "change": "prompt v1.4", "result": "markdown down",
                                                 "run_a_id": run1, "run_b_id": run2}).json()
    assert x["snapshot"]["deltas"]
    assert client.get(f"{base}/experiments").json()["count"] == 1

    flagged = client.post(f"{base}/suite/flagged_to_review", json={"run_id": run2, "size": 10}).json()
    assert flagged["reasons"].get("evaluator_flag", 0) >= 1 and flagged["reasons"].get("random", 0) >= 2
    # verdict hidden until the human saves
    q = client.get(f"{base}/review/queue", params={"batch_id": flagged["id"]}).json()
    one = q[0]["id"]
    assert client.get(f"{base}/review/trace/{one}").json()["evaluator_results"] == []
    client.put(f"{base}/reviews/{one}", json={"verdict": "pass"})
    assert client.get(f"{base}/review/trace/{one}").json()["evaluator_results"]

    st = client.get(f"{base}/status").json()
    assert st["stages"][8]["status"] == "done" and st["stages"][9]["status"] == "ready"

    # export and run the bundle on its own
    r = client.get(f"{base}/export")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    root = names[0].split("/")[0]
    for needed in ("EVAL_SPEC.md", "failure_taxonomy.json", "error_analysis.csv", "checks/code_checks.py", "run_evals.py",
                   "golden_regression.jsonl", "suite.json", "evals_lib.py", f"judges/{jd['slug']}.md",
                   f"datasets/{jd['slug']}_train.jsonl", f"datasets/{jd['slug']}_dev.jsonl", f"datasets/{jd['slug']}_test.jsonl"):
        assert f"{root}/{needed}" in names, needed
    spec = zf.read(f"{root}/EVAL_SPEC.md").decode()
    assert "Operating guidance" in spec and "TPR" in spec and "Motivated by" in spec
    assert "DRAFT" not in zf.read(f"{root}/judges/{jd['slug']}.md").decode()
    zf.extractall(tmp_path)
    out = subprocess.run([sys.executable, "run_evals.py", "--json", "res.json"], cwd=tmp_path / root, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "Pass-all (code checks)" in out.stdout and "skipped (use --judges)" in out.stdout
    res = json.loads((tmp_path / root / "res.json").read_text())
    assert any(v.get(ck["slug"], {}).get("failure") for v in res.values())  # golden set contains past markdown failures
    assert client.get(base).json()["settings"]["last_export_at"]


def test_draft_judge_exports_with_banner(demo):
    client, pid, _ = demo
    base = f"/api/projects/{pid}"
    bid, q, ids = setup_taxonomy(client, pid, n=30)
    jd = client.post(f"{base}/evaluators", json={"type": "judge", "failure_mode_id": ids["robotic_dead_end"]}).json()
    client.post(f"{base}/evaluators/{jd['id']}/versions", json={"definition": {"failure_when": ["dead end"], "not_failure_when": []}})
    zf = zipfile.ZipFile(io.BytesIO(client.get(f"{base}/export").content))
    root = zf.namelist()[0].split("/")[0]
    assert "DRAFT" in zf.read(f"{root}/judges/{jd['slug']}.md").decode()
