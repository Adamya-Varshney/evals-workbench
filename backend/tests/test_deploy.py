import base64
import importlib


def test_password_gate(client, monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    assert client.get("/api/meta").status_code == 401
    assert client.get("/healthz").status_code == 200
    bad = base64.b64encode(b"me:nope").decode()
    assert client.get("/api/meta", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"anyone:s3cret").decode()
    assert client.get("/api/meta", headers={"Authorization": f"Basic {good}"}).status_code == 200
    monkeypatch.delenv("APP_PASSWORD")
    assert client.get("/api/meta").status_code == 200


def test_demo_mode_never_uses_a_key(monkeypatch):
    from app.config import settings

    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("LLM_MODE", "live")
    assert settings.llm_mode == "mock" and settings.anthropic_api_key == "" and settings.max_upload_mb == 5


def test_upload_limit(client, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")
    p = client.post("/api/projects/demo").json()
    r = client.post(f"/api/projects/{p['id']}/imports", files={"file": ("x.jsonl", "x" * 5000, "application/json")})
    assert r.status_code == 413


def test_demo_reset_builds_walkthrough(client):
    from app.services import showcase

    showcase.reset_demo()
    assert showcase.state["error"] is None, showcase.state["error"]
    projects = client.get("/api/projects").json()
    names = [p["name"] for p in projects]
    assert names == ["Larkspur Residences", showcase.WALKTHROUGH_NAME]
    demo = projects[0]
    assert client.get(f"/api/projects/{demo['id']}/status").json()["counts"]["traces"] == 120
    w = projects[1]["id"]
    st = client.get(f"/api/projects/{w}/status").json()
    by = {s["key"]: s["status"] for s in st["stages"]}
    assert st["counts"]["reviewed"] == 100 and st["counts"]["failure_modes"] >= 6
    assert all(by[k] == "done" for k in ("setup", "traces", "review", "group", "count", "decide", "build", "validate", "run")), by
    assert by["export"] == "ready"
    evs = {e["type"]: e for e in client.get(f"/api/projects/{w}/evaluators").json()}
    assert evs["code"]["status"] == "active" and evs["judge"]["status"] == "validated"
    assert client.get(f"/api/projects/{w}/experiments").json()["count"] == 1
    assert client.get(f"/api/projects/{w}/count/transitions").json()["n"] > 0
    # resetting again wipes visitor changes and rebuilds the same thing
    client.patch(f"/api/projects/{demo['id']}", json={"name": "vandalised"})
    showcase.reset_demo()
    assert [p["name"] for p in client.get("/api/projects").json()] == names
