from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..config import SEED_FILE
from ..db import get_session
from ..importers.normalize import validate_regexes
from ..models import Batch, BatchTrace, Event, FailureMode, ImportJob, Review, Trace
from ..services import imports as imp
from ..services.sampling import METHODS, build_batch
from ..services.traceview import facets, matches, trace_view
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}", tags=["traces"])


# ------------------------------------------------------------------ imports
@router.post("/imports")
async def upload(pid: int, file: Optional[UploadFile] = File(None), demo: bool = Form(False),
                 synthetic: bool = Form(False), s: Session = Depends(get_session)):
    get_project(s, pid)
    if demo:
        text, name = SEED_FILE.read_text(encoding="utf-8"), SEED_FILE.name
    elif file is not None:
        raw = await file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        name = file.filename or "upload"
    else:
        raise HTTPException(400, "Send a file or demo=true")
    job = imp.stage_import(s, pid, name, text, tags={"synthetic": True} if synthetic else {})
    return _job_view(job)


def _job_view(job: ImportJob) -> dict:
    return {"id": job.id, "filename": job.filename, "fmt": job.fmt, "mapping": job.mapping, "redaction": job.redaction,
            "report": job.report, "status": job.status, "tags": job.tags, "created_at": job.created_at,
            "fields": imp.source_fields(job) if job.status == "staged" else []}


def _job(s: Session, pid: int, iid: int) -> ImportJob:
    job = s.get(ImportJob, iid)
    if not job or job.project_id != pid:
        raise HTTPException(404, "Import not found")
    return job


@router.get("/imports")
def list_imports(pid: int, s: Session = Depends(get_session)):
    jobs = s.exec(select(ImportJob).where(ImportJob.project_id == pid).order_by(ImportJob.id.desc())).all()
    return [{"id": j.id, "filename": j.filename, "fmt": j.fmt, "status": j.status, "report": j.report, "created_at": j.created_at} for j in jobs]


@router.get("/imports/{iid}")
def get_import(pid: int, iid: int, s: Session = Depends(get_session)):
    return _job_view(_job(s, pid, iid))


class MappingIn(BaseModel):
    mapping: dict
    redaction: dict = {}


@router.post("/imports/{iid}/preview")
def preview(pid: int, iid: int, body: MappingIn, s: Session = Depends(get_session)):
    job = _job(s, pid, iid)
    if job.status != "staged":
        raise HTTPException(409, "This import is already committed")
    bad = validate_regexes(body.redaction.get("custom", []))
    if bad:
        raise HTTPException(400, "Invalid regex: " + "; ".join(bad))
    return imp.preview(job, body.mapping, body.redaction)


@router.post("/imports/{iid}/commit")
def commit(pid: int, iid: int, body: MappingIn, s: Session = Depends(get_session)):
    job = _job(s, pid, iid)
    if job.status != "staged":
        raise HTTPException(409, "This import is already committed")
    bad = validate_regexes(body.redaction.get("custom", []))
    if bad:
        raise HTTPException(400, "Invalid regex: " + "; ".join(bad))
    return imp.commit_import(s, job, body.mapping, body.redaction)


# ------------------------------------------------------------------ traces
def _filtered(s: Session, pid: int, batch_id: Optional[int], q: str, filters: Optional[str]) -> list[Trace]:
    f = json.loads(filters) if filters else {}
    if batch_id:
        ids = [bt.trace_id for bt in s.exec(select(BatchTrace).where(BatchTrace.batch_id == batch_id).order_by(BatchTrace.position)).all()]
        tmap = {t.id: t for t in s.exec(select(Trace).where(Trace.id.in_(ids))).all()}
        traces = [tmap[i] for i in ids if i in tmap]
    else:
        traces = list(s.exec(select(Trace).where(Trace.project_id == pid).order_by(Trace.id)).all())
    return [t for t in traces if matches(t, q, f)]


@router.get("/traces")
def list_traces(pid: int, batch_id: Optional[int] = None, q: str = "", filters: Optional[str] = None,
                offset: int = 0, limit: int = 200, s: Session = Depends(get_session)):
    traces = _filtered(s, pid, batch_id, q, filters)
    reviews = {r.trace_id: r for r in s.exec(select(Review).where(Review.project_id == pid)).all()}
    page = traces[offset: offset + limit]
    firsts: dict[int, str] = {}
    for e in s.exec(select(Event).where(Event.trace_id.in_([t.id for t in page]), Event.role == "user").order_by(Event.seq)).all():
        firsts.setdefault(e.trace_id, e.content)
    items = []
    for t in page:
        r = reviews.get(t.id)
        first_user = " ".join((firsts.get(t.id) or "").split())
        items.append({
            "id": t.id, "external_id": t.external_id, "channel": t.channel, "n_turns": t.n_turns,
            "n_tool_calls": t.n_tool_calls, "snippet": first_user[:120], "synthetic": t.synthetic,
            "verdict": r.verdict if r else None, "deferred": bool(r and r.deferred), "has_note": bool(r and r.note.strip()),
        })
    return {"total": len(traces), "items": items}


@router.get("/facets")
def get_facets(pid: int, batch_id: Optional[int] = None, s: Session = Depends(get_session)):
    return facets(_filtered(s, pid, batch_id, "", None))


@router.get("/traces/{tid}")
def get_trace(pid: int, tid: int, raw: bool = False, s: Session = Depends(get_session)):
    t = s.get(Trace, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404, "Trace not found")
    return trace_view(s, t, include_raw=raw)


# ------------------------------------------------------------------ batches
class BatchIn(BaseModel):
    size: int = 100
    method: str = "random"
    params: dict = {}
    name: Optional[str] = None
    seed: Optional[int] = None


@router.post("/batches")
def create_batch(pid: int, body: BatchIn, s: Session = Depends(get_session)):
    get_project(s, pid)
    if body.method not in METHODS:
        raise HTTPException(400, f"method must be one of {METHODS}")
    n = s.exec(select(func.count()).select_from(Trace).where(Trace.project_id == pid)).one()
    if n == 0:
        raise HTTPException(400, "Import traces before building a batch")
    p = get_project(s, pid)
    has_taxonomy = s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.is_none_bucket == False,  # noqa: E712
                                                    FailureMode.archived == False)).first() is not None  # noqa: E712
    b = build_batch(s, pid, body.size, body.method, body.params, body.name, body.seed)
    if has_taxonomy:
        # A new round of review once a taxonomy exists: quick-tag chips may appear (after the note).
        p.review_round += 1
        s.add(p)
        s.commit()
    return batch_summary(s, b)


def batch_summary(s: Session, b: Batch) -> dict:
    bts = s.exec(select(BatchTrace).where(BatchTrace.batch_id == b.id)).all()
    ids = [bt.trace_id for bt in bts]
    reviewed = s.exec(select(func.count()).select_from(Review).where(Review.trace_id.in_(ids), Review.verdict.is_not(None))).one() if ids else 0
    reasons: dict[str, int] = {}
    for bt in bts:
        reasons[bt.reason] = reasons.get(bt.reason, 0) + 1
    return {"id": b.id, "name": b.name, "method": b.method, "params": b.params, "created_at": b.created_at,
            "size": len(ids), "reviewed": reviewed, "reasons": reasons}


@router.get("/batches")
def list_batches(pid: int, s: Session = Depends(get_session)):
    return [batch_summary(s, b) for b in s.exec(select(Batch).where(Batch.project_id == pid).order_by(Batch.id)).all()]


@router.patch("/batches/{bid}")
def rename_batch(pid: int, bid: int, body: dict, s: Session = Depends(get_session)):
    b = s.get(Batch, bid)
    if not b or b.project_id != pid:
        raise HTTPException(404)
    b.name = body.get("name", b.name)
    s.add(b)
    s.commit()
    return batch_summary(s, b)
