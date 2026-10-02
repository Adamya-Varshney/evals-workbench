from tests.helpers import review_batch


def _bootstrap(demo, n=40):
    client, pid, _ = demo
    bid, q = review_batch(client, pid, n=n)
    return client, pid, bid


def test_propose_requires_unlock(demo):
    client, pid, bid = _bootstrap(demo, n=20)
    r = client.post(f"/api/projects/{pid}/group/propose")
    assert r.status_code == 403


def test_full_axial_coding_flow(demo):
    client, pid, bid = _bootstrap(demo, n=60)
    base = f"/api/projects/{pid}"
    st = client.get(f"{base}/status").json()
    assert st["stages"][3]["status"] == "ready"

    props = client.post(f"{base}/group/propose").json()
    assert 4 <= len(props) <= 7
    assert all(p["examples"] for p in props)
    vague = [p for p in props if p["warnings"]]
    assert vague, "mock includes a vague name like 'Temporal issues' to exercise the specificity check"

    # Accept every proposal, rewriting vague names into specific ones.
    rename = {"Temporal issues": "Wrong current date", "Formatting issues": "Markdown sent over SMS",
              "Scheduling problems": "Duplicate booking instead of reschedule", "Other quality issues": None}
    for p in props:
        new = rename.get(p["name"], p["name"])
        if new is None:
            client.post(f"{base}/group/proposals/{p['id']}/reject")
            continue
        m = client.post(f"{base}/group/proposals/{p['id']}/accept",
                        json={"name": new, "definition": p["definition"], "counts_as": "e.g. " + new.lower(), "does_not_count_as": "anything else"}).json()
        assert m["warnings"] == []
    modes = client.get(f"{base}/failure_modes").json()
    assert any(m["is_none_bucket"] for m in modes)
    names = {m["name"] for m in modes}
    assert "Markdown sent over SMS" in names and "Wrong current date" in names

    res = client.post(f"{base}/group/suggest", json={"scope": "unassigned"}).json()
    summary = client.get(f"{base}/group/summary").json()
    assert res["created"] == summary["failing_notes"] == summary["pending_suggestions"]
    assert summary["bulk_unlocked"] is False

    notes = [n for n in client.get(f"{base}/group/notes").json() if n["suggestion"]]
    # bulk accept refused before 10 individual confirmations
    assert client.post(f"{base}/group/suggestions/bulk_accept", json={"failure_mode_id": notes[0]["suggestion"]["failure_mode_ids"][0]}).status_code == 409
    for n in notes[:10]:
        assert client.post(f"{base}/group/suggestions/{n['suggestion']['id']}/accept", json={}).json()["ok"]
    summary = client.get(f"{base}/group/summary").json()
    assert summary["bulk_unlocked"] is True
    # change one suggestion: source becomes human
    other = notes[10]
    mode_ids = [m["id"] for m in modes if not m["is_none_bucket"]]
    r = client.post(f"{base}/group/suggestions/{other['suggestion']['id']}/accept", json={"failure_mode_ids": mode_ids[:1]}).json()
    assert r["status"] in ("changed", "accepted")
    for fid in mode_ids:
        client.post(f"{base}/group/suggestions/bulk_accept", json={"failure_mode_id": fid})
    for n in client.get(f"{base}/group/notes").json():
        if n["suggestion"]:
            client.post(f"{base}/group/suggestions/{n['suggestion']['id']}/accept", json={})
    summary = client.get(f"{base}/group/summary").json()
    assert summary["pending_suggestions"] == 0 and summary["unassigned"] == 0

    # Clear the None-of-the-above queue by creating a category from a note there (if any) or assigning.
    none_id = summary["none_id"]
    for n in client.get(f"{base}/group/notes").json():
        if any(lab["failure_mode_id"] == none_id for lab in n["labels"]):
            client.post(f"{base}/failure_modes", json={"name": "Problem seen once", "definition": "x", "from_review_id": n["review_id"]})
    assert client.get(f"{base}/group/summary").json()["in_none"] == 0
    st = client.get(f"{base}/status").json()
    assert st["stages"][3]["status"] == "done"
    assert st["stages"][4]["status"] == "in_progress"

    # Count: pivot by channel, drill into a cell.
    c = client.get(f"{base}/count", params={"facet": "channel"}).json()
    md = next(r for r in c["rows"] if r["name"] == "Markdown sent over SMS")
    assert md["count"] > 0 and set(md["by_facet"]) == {"sms"}
    assert c["n_reviewed"] == 60 and 0 < c["n_failing"] < 60
    assert 0 < md["share_reviewed"] < md["share_failing"] <= 1
    assert c["top3_share"] and len(c["top3_names"]) == 3
    drill = client.get(f"{base}/count/traces", params={"failure_mode_id": md["id"], "facet": "channel", "value": "sms"}).json()
    assert len(drill) == md["count"] and all(d["channel"] == "sms" for d in drill)

    # Severity, impact, manual order (no computed score)
    real = [m for m in client.get(f"{base}/failure_modes").json() if not m["is_none_bucket"]]
    for m in real:
        client.patch(f"{base}/failure_modes/{m['id']}", json={"severity": "high", "impact_note": "hurts trust"})
    order = [m["id"] for m in reversed(real)]
    client.post(f"{base}/failure_modes/reorder", json={"ids": order})
    after = [m["id"] for m in client.get(f"{base}/failure_modes").json() if not m["is_none_bucket"]]
    assert after == order
    assert client.patch(f"{base}/failure_modes/{real[0]['id']}", json={"severity": "medium"}).status_code == 400
    assert client.get(f"{base}/status").json()["stages"][4]["status"] == "done"


def test_definition_change_flags_recheck_and_history(demo):
    client, pid, bid = _bootstrap(demo, n=40)
    base = f"/api/projects/{pid}"
    m = client.post(f"{base}/failure_modes", json={"name": "Markdown sent over SMS", "definition": "v1"}).json()
    notes = [n for n in client.get(f"{base}/group/notes").json() if n["verdict"] == "fail"]
    client.put(f"{base}/group/labels/{notes[0]['review_id']}", json={"failure_mode_ids": [m["id"]]})
    client.patch(f"{base}/failure_modes/{m['id']}", json={"name": "Markdown over SMS"})
    assert client.get(f"{base}/group/summary").json()["recheck"] == 0  # rename does not invalidate labels
    r = client.patch(f"{base}/failure_modes/{m['id']}", json={"definition": "v2: any markdown syntax in an SMS reply"}).json()
    assert r["version"] == 2 and r["n_recheck"] == 1
    assert client.get(f"{base}/group/summary").json()["recheck"] == 1
    hist = client.get(f"{base}/failure_modes/{m['id']}/history").json()
    assert [h["action"] for h in hist] == ["edit", "edit", "create"]
    # re-confirming the label clears the flag
    client.put(f"{base}/group/labels/{notes[0]['review_id']}", json={"failure_mode_ids": [m["id"]]})
    assert client.get(f"{base}/group/summary").json()["recheck"] == 0


def test_merge_split_subcategories(demo):
    client, pid, bid = _bootstrap(demo, n=40)
    base = f"/api/projects/{pid}"
    a = client.post(f"{base}/failure_modes", json={"name": "Markdown in SMS"}).json()
    b = client.post(f"{base}/failure_modes", json={"name": "Bullets in texts"}).json()
    notes = [n for n in client.get(f"{base}/group/notes").json() if n["verdict"] == "fail"]
    client.put(f"{base}/group/labels/{notes[0]['review_id']}", json={"failure_mode_ids": [a["id"]]})
    client.put(f"{base}/group/labels/{notes[1]['review_id']}", json={"failure_mode_ids": [b["id"]]})
    client.post(f"{base}/failure_modes/merge", json={"source_ids": [b["id"]], "target_id": a["id"]})
    modes = {m["id"]: m for m in client.get(f"{base}/failure_modes").json()}
    assert b["id"] not in modes and modes[a["id"]]["n_labels"] == 2
    sp = client.post(f"{base}/failure_modes/{a['id']}/split", json={"parts": [{"name": "Bold markdown in SMS"}, {"name": "Bulleted lists in SMS"}], "as_children": True}).json()
    modes = {m["id"]: m for m in client.get(f"{base}/failure_modes").json()}
    assert all(modes[c]["parent_id"] == a["id"] for c in sp["created"])
    assert modes[a["id"]]["n_recheck"] == 2
    # only one level of sub-category
    r = client.post(f"{base}/failure_modes", json={"name": "Too deep", "parent_id": sp["created"][0]})
    assert r.status_code == 400
    # parent count rolls up children
    client.put(f"{base}/group/labels/{notes[2]['review_id']}", json={"failure_mode_ids": [sp["created"][0]]})
    rows = {r["id"]: r for r in client.get(f"{base}/count").json()["rows"]}
    assert rows[a["id"]]["count"] == 3 and rows[sp["created"][0]]["count"] == 1
    assert client.delete(f"{base}/failure_modes/{a['id']}").json()["ok"]
    modes = {m["id"]: m for m in client.get(f"{base}/failure_modes").json()}
    assert all(modes[c]["parent_id"] is None for c in sp["created"])
