from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import ROOT
from .db import init_db
from .routers import evaluators, group, projects, review, runs, synthetic, system, traces


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Evals Workbench", lifespan=lifespan)
app.include_router(system.router)
app.include_router(projects.router)
app.include_router(traces.router)
app.include_router(review.router)
app.include_router(group.router)
app.include_router(evaluators.router)
app.include_router(runs.router)
app.include_router(synthetic.router)

# Serve the built frontend when it exists (production-style `python dev.py serve`).
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            from fastapi import HTTPException

            raise HTTPException(404, "Not found")
        f = DIST / path
        if path and f.is_file() and Path(f).resolve().is_relative_to(DIST.resolve()):
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
