import json

from tests.helpers import review_batch


def test_synthetic_two_step_flow(client):
    p = client.post("/api/projects/demo").json()
    base = f"/api/projects/{p['id']}/synthetic"
    st = client.get(base).json()
    assert [d["name"] for d in st["dimensions"]] == ["feature", "scenario", "persona"]
    assert st["ai_unlocked"] is False
    client.put(base, json={"dimensions": st["dimensions"], "grounding": "Units: C-104 (1BR $1,385), R-101 (studio $1,050). No virtual tours."})
    assert client.post(f"{base}/propose", json={"count": 10}).status_code == 403  # fewer than 20 hand-written
    feats, scens, pers = (d["values"] for d in st["dimensions"])
    for i in range(20):
        client.post(f"{base}/tuples", json={"values": {"feature": feats[i % 5], "scenario": scens[(i // 5) % 5], "persona": pers[0]}})
    st = client.post(f"{base}/propose", json={"count": 15}).json()
    assert st["created"] == 15 and st["ai_unlocked"]
    pending = [t for t in st["tuples"] if t["status"] == "pending"]
    assert len(pending) == 15 and all(t["source"] == "ai" for t in pending)
    for t in pending[:10]:
        client.patch(f"{base}/tuples/{t['id']}", json={"status": "accepted"})
    for t in pending[10:]:
        client.patch(f"{base}/tuples/{t['id']}", json={"status": "rejected"})
    st = client.post(f"{base}/inputs").json()
    assert st["generated"] == 30
    msgs = [t["user_message"] for t in st["tuples"] if t["status"] == "accepted"]
    assert all(msgs) and len(set(msgs)) > 10
    lines = client.get(f"{base}/export").text.strip().splitlines()
    assert len(lines) == 30 and {"id", "input", "tuple"} <= set(json.loads(lines[0]))
    csv_text = client.get(f"{base}/export", params={"format": "csv"}).text
    assert csv_text.splitlines()[0].startswith("id,input")

    # import the resulting traces tagged as synthetic, keeping their tuple
    rows = [json.loads(x) for x in lines[:3]]
    traces = "\n".join(json.dumps({"id": r["id"], "tuple": r["tuple"], "channel": "sms",
                                   "messages": [{"role": "user", "content": r["input"]}, {"role": "assistant", "content": "ok"}]}) for r in rows)
    pid = p["id"]
    job = client.post(f"/api/projects/{pid}/imports", files={"file": ("syn.jsonl", traces, "application/json")}, data={"synthetic": "true"}).json()
    rep = client.post(f"/api/projects/{pid}/imports/{job['id']}/commit", json={"mapping": job["mapping"], "redaction": {}}).json()
    assert rep["imported"] == 3
    tr = client.get(f"/api/projects/{pid}/traces", params={"filters": json.dumps({"synthetic": ["true"]})}).json()
    assert tr["total"] == 3
    one = client.get(f"/api/projects/{pid}/traces/{tr['items'][0]['id']}").json()
    assert one["synthetic"] and one["synthetic_tuple"]["feature"]


def test_transition_matrix(demo):
    client, pid, _ = demo
    bid, q = review_batch(client, pid, n=60)
    base = f"/api/projects/{pid}"
    n = 0
    for item in q[:60]:
        d = client.get(f"{base}/review/trace/{item['id']}").json()
        if d["review"]["verdict"] != "fail":
            continue
        evs = d["trace"]["events"]
        if not any(e["role"] == "tool_call" for e in evs):
            continue
        last_asst = [e for e in evs if e["role"] == "assistant"][-1]
        client.put(f"{base}/reviews/{item['id']}", json={"first_failure_event_id": last_asst["id"], "fields": ["first_failure_event_id"]})
        n += 1
    m = client.get(f"{base}/count/transitions").json()
    assert m["n"] == n > 0
    assert "assistant reply" in m["cols"]
    assert sum(c["count"] for c in m["cells"]) == n
    assert all(c["from"] in m["rows"] and c["to"] in m["cols"] for c in m["cells"])
