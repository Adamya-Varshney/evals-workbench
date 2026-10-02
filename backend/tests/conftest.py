import os
import sys
from pathlib import Path

import pytest

os.environ["LLM_MODE"] = "mock"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def client(tmp_path):
    from fastapi.testclient import TestClient

    from app import db

    db.set_engine(db.make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}"))
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def demo(client):
    """Demo project with the seed traces imported. Returns (client, project_id, import_report)."""
    p = client.post("/api/projects/demo").json()
    job = client.post(f"/api/projects/{p['id']}/imports", data={"demo": "true"}).json()
    rep = client.post(f"/api/projects/{p['id']}/imports/{job['id']}/commit", json={"mapping": job["mapping"], "redaction": {}}).json()
    return client, p["id"], rep
