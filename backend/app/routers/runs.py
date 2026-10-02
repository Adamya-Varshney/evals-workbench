"""Stages 9–10: run the suite on batches, compare, experiment log, export."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models import Batch, BatchTrace, EvalRun, Evaluator, Experiment, Trace, now
from ..services import evals as E
from ..services.export import OPERATING_GUIDANCE, build_bundle
from ..services.report import run_report
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}", tags=["runs"])


def _suite(s: Session, pid: int, ids: Optional[list[int]]) -> list[Evaluator]:
    evs = s.exec(select(Evaluator).where(Evaluator.project_id == pid, Evaluator.status.in_(["active", "validated", "draft"]))).all()
    if ids:
        return [e for e in evs if e.id in ids]
    return [e for e in evs if e.status in ("active", "validated")]


def _batch_traces(s: Session, pid: int, bid: int) -> list[Trace]:
    b = s.get(Batch, bid)
    if not b or b.project_id != pid:
        raise HTTPException(404, "Batch not found")
    ids = s.exec(select(BatchTrace.trace_id).where(BatchTrace.batch_id == bid)).all()
    return list(s.exec(select(Trace).where(Trace.id.in_(ids))).all())


@router.get("/suite/estimate")
def estimate(pid: int, batch_id: int, evaluator_ids: str = "", s: Session = Depends(get_session)):
    p = get_project(s, pid)
    evs = _suite(s, pid, [int(x) for x in evaluator_ids.split(",") if x])
    traces = _batch_traces(s, pid, batch_id)
    est = E.estimate_cost(s, p, evs, traces)
    return {**est, "n_traces": len(traces), "evaluators": [{"id": e.id, "name": e.name, "type": e.type, "status": e.status} for e in evs],
            "concurrency": settings.llm_concurrency}


class SuiteRunIn(BaseModel):
    batch_id: int
    evaluator_ids: list[int] = []
    note: str = ""


@router.post("/suite/run")
def run_suite(pid: int, body: SuiteRunIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    evs = _suite(s, pid, body.evaluator_ids or None)
    if not evs:
        raise HTTPException(400, "No active or validated evaluators to run")
    if any(e.type == "judge" for e in evs) and not p.settings.get("ai_assist_enabled", True) and settings.llm_mode != "mock":
        raise HTTPException(403, "AI assist is switched off, so judges cannot run.")
    traces = _batch_traces(s, pid, body.batch_id)
    est = E.estimate_cost(s, p, evs, traces)
    run = EvalRun(project_id=pid, kind="batch", batch_id=body.batch_id, evaluator_ids=[e.id for e in evs], total=len(traces) * len(evs),
                  cost_estimate=est["usd"])
    s.add(run)
    s.commit()
    s.refresh(run)
    ev_ids, t_ids = [e.id for e in evs], [t.id for t in traces]
    started = now()

    def work(s2: Session, r: EvalRun):
        from sqlmodel import func

        from ..models import LLMCall

        items = []
        for eid in ev_ids:
            ev = s2.get(Evaluator, eid)
            v = E.run_version(s2, ev)
            for t in s2.exec(select(Trace).where(Trace.id.in_(t_ids))).all():
                items.append((ev, v, t))
        E.execute(s2, r, items)
        r.cost_actual = float(s2.exec(select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.project_id == pid, LLMCall.created_at >= started)).one() or 0)
        s2.add(r)
        s2.commit()

    E.submit(run.id, work)
    return {"run_id": run.id, "estimate": est}


@router.get("/suite/runs")
def list_runs(pid: int, s: Session = Depends(get_session)):
    runs = s.exec(select(EvalRun).where(EvalRun.project_id == pid, EvalRun.kind == "batch").order_by(EvalRun.id.desc())).all()
    out = []
    for r in runs:
        b = s.get(Batch, r.batch_id) if r.batch_id else None
        out.append({"id": r.id, "status": r.status, "progress": r.progress, "total": r.total, "batch_id": r.batch_id, "batch": b.name if b else "?",
                    "evaluator_ids": r.evaluator_ids, "cost_estimate": r.cost_estimate, "cost_actual": r.cost_actual, "created_at": r.created_at,
                    "error": r.error.split("\n")[0] if r.error else ""})
    return out


@router.get("/suite/runs/{rid}/report")
def report(pid: int, rid: int, facet: Optional[str] = None, s: Session = Depends(get_session)):
    r = s.get(EvalRun, rid)
    if not r or r.project_id != pid or r.kind != "batch":
        raise HTTPException(404)
    if r.status != "done":
        return {"status": r.status, "progress": r.progress, "total": r.total, "error": r.error}
    return {"status": "done", **run_report(s, r, facet or None)}


@router.get("/suite/compare")
def compare(pid: int, a: int, b: int, s: Session = Depends(get_session)):
    ra, rb = s.get(EvalRun, a), s.get(EvalRun, b)
    if not ra or not rb or ra.project_id != pid or rb.project_id != pid:
        raise HTTPException(404)
    A, B = run_report(s, ra), run_report(s, rb)
    bmap = {e["evaluator_id"]: e for e in B["evaluators"]}
    rows = []
    for e in A["evaluators"]:
        o = bmap.get(e["evaluator_id"])

        def rate(x):
            if not x:
                return None
            if x.get("corrected"):
                return x["corrected"]["theta"]
            return x["raw"]["rate"]

        ra_, rb_ = rate(e), rate(o)
        rows.append({"evaluator_id": e["evaluator_id"], "name": e["name"], "type": e["type"], "a": e, "b": o,
                     "delta": (rb_ - ra_) if ra_ is not None and rb_ is not None else None})
    return {"a": {"run_id": a, "batch": _batch_name(s, ra), "pass_all": A["pass_all"], "n": A["n_traces"]},
            "b": {"run_id": b, "batch": _batch_name(s, rb), "pass_all": B["pass_all"], "n": B["n_traces"]}, "rows": rows}


def _batch_name(s: Session, r: EvalRun) -> str:
    b = s.get(Batch, r.batch_id) if r.batch_id else None
    return b.name if b else "?"


class FlagIn(BaseModel):
    run_id: int
    size: int = 30


@router.post("/suite/flagged_to_review")
def flagged_to_review(pid: int, body: FlagIn, s: Session = Depends(get_session)):
    """Send evaluator-flagged traces back to human review (verdicts stay hidden until the human saves)."""
    from ..services.sampling import build_batch

    r = s.get(EvalRun, body.run_id)
    if not r or r.project_id != pid:
        raise HTTPException(404)
    b = build_batch(s, pid, body.size, "evaluator_flag", {"run_id": body.run_id, "exclude_reviewed": True},
                    name=f"Flagged by run #{body.run_id}")
    from .traces import batch_summary

    return batch_summary(s, b)


# ------------------------------------------------------------------ experiments
class ExperimentIn(BaseModel):
    hypothesis: str
    change: str
    result: str = ""
    batch_a_id: Optional[int] = None
    batch_b_id: Optional[int] = None
    run_a_id: Optional[int] = None
    run_b_id: Optional[int] = None


@router.get("/experiments")
def experiments(pid: int, s: Session = Depends(get_session)):
    rows = s.exec(select(Experiment).where(Experiment.project_id == pid).order_by(Experiment.id.desc())).all()
    return {"count": len(rows), "items": rows}


@router.post("/experiments")
def add_experiment(pid: int, body: ExperimentIn, s: Session = Depends(get_session)):
    get_project(s, pid)
    snap = {}
    if body.run_a_id and body.run_b_id:
        c = compare(pid, body.run_a_id, body.run_b_id, s)
        snap = {"pass_all_a": c["a"]["pass_all"], "pass_all_b": c["b"]["pass_all"],
                "deltas": [{"name": r["name"], "delta": r["delta"]} for r in c["rows"]], "runs": [body.run_a_id, body.run_b_id]}
    e = Experiment(project_id=pid, hypothesis=body.hypothesis, change=body.change, result=body.result, batch_a_id=body.batch_a_id,
                   batch_b_id=body.batch_b_id, snapshot=snap)
    s.add(e)
    s.commit()
    s.refresh(e)
    return e


@router.patch("/experiments/{xid}")
def edit_experiment(pid: int, xid: int, body: dict, s: Session = Depends(get_session)):
    e = s.get(Experiment, xid)
    if not e or e.project_id != pid:
        raise HTTPException(404)
    for k in ("hypothesis", "change", "result"):
        if k in body:
            setattr(e, k, body[k])
    s.add(e)
    s.commit()
    return e


# ------------------------------------------------------------------ export
@router.get("/export")
def export(pid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    data, name = build_bundle(s, p)
    p.settings = {**p.settings, "last_export_at": now().isoformat()}
    s.add(p)
    s.commit()
    return Response(content=data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/export/guidance")
def guidance(pid: int):
    return {"markdown": OPERATING_GUIDANCE}
