from __future__ import annotations

import base64
import hmac
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import ROOT, settings
from .db import init_db
from .routers import evaluators, group, projects, review, runs, synthetic, system, traces


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if settings.demo_mode:
        from .services.showcase import start_demo_scheduler

        start_demo_scheduler()
    yield


app = FastAPI(title="Evals Workbench", lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    # Optional shared password for hosted copies (APP_PASSWORD). Any username works.
    pw = settings.app_password
    if pw and request.url.path != "/healthz":
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                _, _, given = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
                ok = hmac.compare_digest(given.encode(), pw.encode())
            except Exception:  # noqa: BLE001
                ok = False
        if not ok:
            return Response("Password required", status_code=401, headers={"WWW-Authenticate": 'Basic realm="Evals Workbench"'})
    # Upload size cap (smaller in demo mode).
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > settings.max_upload_mb * 1024 * 1024:
        return Response(f"Upload too large (limit {settings.max_upload_mb:g} MB)", status_code=413)
    return await call_next(request)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


@app.get("/api/demo")
def demo_state():
    from .services.showcase import state

    return {"demo_mode": settings.demo_mode, "building": state["building"], "last_reset": state["last_reset"],
            "reset_hours": settings.demo_reset_hours, "error": state["error"]}


_last_manual_reset = {"t": 0.0}


@app.post("/api/demo/reset")
def demo_reset():
    from .services.showcase import reset_demo, state

    if not settings.demo_mode:
        raise HTTPException(404)
    if state["building"] or time.time() - _last_manual_reset["t"] < 120:
        raise HTTPException(429, "A reset ran recently; try again in a couple of minutes.")
    _last_manual_reset["t"] = time.time()
    threading.Thread(target=reset_demo, daemon=True).start()
    return {"ok": True}


app.include_router(system.router)
app.include_router(projects.router)
app.include_router(traces.router)
app.include_router(review.router)
app.include_router(group.router)
app.include_router(evaluators.router)
app.include_router(runs.router)
app.include_router(synthetic.router)

# Serve the built frontend when it exists (Docker / `python dev.py serve`).
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = DIST / path
        if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
