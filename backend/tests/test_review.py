def _setup(demo):
    client, pid, _ = demo
    client.patch(f"/api/projects/{pid}", json={"reviewer_name": "Pat"})
    b = client.post(f"/api/projects/{pid}/batches", json={"size": 100, "seed": 5}).json()
    q = client.get(f"/api/projects/{pid}/review/queue", params={"batch_id": b["id"]}).json()
    return client, pid, b["id"], q


def test_queue_and_trace_payload(demo):
    client, pid, bid, q = _setup(demo)
    assert len(q) == 100 and all(i["verdict"] is None for i in q)
    d = client.get(f"/api/projects/{pid}/review/trace/{q[1]['id']}", params={"batch_id": bid}).json()
    assert d["trace"]["events"] and d["review"] is None
    assert d["system_same_as_previous"] in (True, False)
    assert d["quick_tags"] == []  # first round: no category picker


def test_save_undo_and_history(demo):
    client, pid, bid, q = _setup(demo)
    tid = q[0]["id"]
    url = f"/api/projects/{pid}/reviews/{tid}"
    r = client.put(url, json={"verdict": "fail", "add_seconds": 12, "batch_id": bid}).json()
    assert r["verdict"] == "fail" and r["reviewer"] == "Pat" and r["reviewed_at"]
    client.put(url, json={"note": "used ** in sms", "fields": ["note"], "add_seconds": 5})
    client.put(url, json={"note": "used **bold** in an SMS", "fields": ["note"], "add_seconds": 5})
    r = client.put(url, json={"first_failure_event_id": 3, "fields": ["first_failure_event_id"]}).json()
    assert r["seconds_spent"] == 22
    # undo anchor, then the (collapsed) note edits
    r = client.post(url + "/undo").json()
    assert r["first_failure_event_id"] is None and r["note"] == "used **bold** in an SMS"
    r = client.post(url + "/undo").json()
    assert r["note"] == "" and r["verdict"] == "fail"
    r = client.post(url + "/undo").json()
    assert r["verdict"] is None and r["reviewed_at"] is None
    assert client.post(url + "/undo").status_code == 409


def test_defer_then_verdict_clears_defer(demo):
    client, pid, bid, q = _setup(demo)
    url = f"/api/projects/{pid}/reviews/{q[2]['id']}"
    assert client.put(url, json={"deferred": True}).json()["deferred"] is True
    assert client.put(url, json={"verdict": "pass"}).json()["deferred"] is False


def test_stats_saturation_and_ai_unlock(demo):
    client, pid, bid, q = _setup(demo)
    for i, item in enumerate(q[:30]):
        v = "fail" if i % 3 == 0 else "pass"
        body = {"verdict": v, "add_seconds": 30 + i, "batch_id": bid}
        if v == "fail":
            body["note"] = ["markdown bullets in sms", "said will check back and never did", "ignored budget constraint"][i % 9 // 3]
        client.put(f"/api/projects/{pid}/reviews/{item['id']}", json=body)
    st = client.get(f"/api/projects/{pid}/review/stats", params={"batch_id": bid}).json()
    assert st["reviewed"] == 30 and st["total"] == 100 and st["failed"] == 10
    assert st["median_seconds"] == 44.5
    sat = st["saturation"]
    assert sat["reviewed"] == 30 and sat["new_in_window"] == 0 and sat["suggest_stop"] is True
    assert st["ai"]["unlocked"] is True
    sim = client.post(f"/api/projects/{pid}/traces/{q[0]['id']}/similar").json()
    assert len(sim) == 5 and all(s["id"] != q[0]["id"] for s in sim)


def test_ai_locked_before_threshold_and_when_off(demo):
    client, pid, bid, q = _setup(demo)
    r = client.post(f"/api/projects/{pid}/traces/{q[0]['id']}/similar")
    assert r.status_code == 403 and "30" in r.json()["detail"]
    client.patch(f"/api/projects/{pid}", json={"settings": {"ai_unlock_threshold": 0, "ai_assist_enabled": False}})
    r = client.post(f"/api/projects/{pid}/traces/{q[0]['id']}/similar")
    assert r.status_code == 403 and "off" in r.json()["detail"]
