"""Stage 3: review traces (open coding)."""
from __future__ import annotations

import re
import statistics
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..llm.client import LLMError, call_structured
from ..llm.templates import get_template, render
from ..models import BatchTrace, EvalResult, Event, FailureMode, Review, ReviewLabel, Trace, now
from ..services.gate import require_ai
from ..services.status import ai_state, saturation
from ..services.traceview import trace_text, trace_view
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}", tags=["review"])

REVIEW_FIELDS = ("verdict", "note", "first_failure_event_id", "deferred")
_save_lock = threading.Lock()  # one writer at a time: autosave sends overlapping requests


def _review_dict(r: Optional[Review]) -> Optional[dict]:
    if not r:
        return None
    return {"id": r.id, "trace_id": r.trace_id, "verdict": r.verdict, "note": r.note, "first_failure_event_id": r.first_failure_event_id,
            "deferred": r.deferred, "reviewer": r.reviewer, "seconds_spent": r.seconds_spent, "round": r.round,
            "reviewed_at": r.reviewed_at, "updated_at": r.updated_at, "history_len": len(r.history or [])}


def _batch_ids(s: Session, batch_id: int) -> list[int]:
    return [bt.trace_id for bt in s.exec(select(BatchTrace).where(BatchTrace.batch_id == batch_id).order_by(BatchTrace.position)).all()]


@router.get("/review/queue")
def queue(pid: int, batch_id: int, s: Session = Depends(get_session)):
    ids = _batch_ids(s, batch_id)
    if not ids:
        raise HTTPException(404, "Batch not found or empty")
    traces = {t.id: t for t in s.exec(select(Trace).where(Trace.id.in_(ids))).all()}
    reviews = {r.trace_id: r for r in s.exec(select(Review).where(Review.project_id == pid, Review.trace_id.in_(ids))).all()}
    firsts: dict[int, str] = {}
    for e in s.exec(select(Event).where(Event.trace_id.in_(ids), Event.role == "user").order_by(Event.seq)).all():
        firsts.setdefault(e.trace_id, e.content)
    reasons = {bt.trace_id: bt.reason for bt in s.exec(select(BatchTrace).where(BatchTrace.batch_id == batch_id)).all()}
    items = []
    for i, tid in enumerate(ids):
        t, r = traces[tid], reviews.get(tid)
        items.append({"id": tid, "pos": i, "external_id": t.external_id, "channel": t.channel, "n_turns": t.n_turns,
                      "snippet": " ".join((firsts.get(tid) or "").split())[:140], "meta": t.meta, "reason": reasons.get(tid),
                      "verdict": r.verdict if r else None, "deferred": bool(r and r.deferred), "has_note": bool(r and r.note.strip()),
                      "search": t.search_text})
    return items


@router.get("/review/trace/{tid}")
def review_trace(pid: int, tid: int, batch_id: Optional[int] = None, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    t = s.get(Trace, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404, "Trace not found")
    view = trace_view(s, t, include_raw=True)
    review = s.exec(select(Review).where(Review.project_id == pid, Review.trace_id == tid)).first()
    same_as_prev = None
    if batch_id:
        ids = _batch_ids(s, batch_id)
        if tid in ids and ids.index(tid) > 0:
            prev = s.get(Trace, ids[ids.index(tid) - 1])
            same_as_prev = bool(prev and prev.system_prompt_hash == t.system_prompt_hash)
    # Evaluator verdicts on this trace stay hidden until the human has saved their own judgment.
    flags = []
    if review and review.verdict:
        rs = s.exec(select(EvalResult).where(EvalResult.trace_id == tid).order_by(EvalResult.id.desc())).all()
        seen = set()
        for r in rs:
            if r.evaluator_id in seen:
                continue
            seen.add(r.evaluator_id)
            flags.append({"evaluator_id": r.evaluator_id, "failure": r.failure, "critique": r.critique})
    modes = []
    if p.review_round > 1:
        modes = [{"id": m.id, "name": m.name} for m in s.exec(select(FailureMode).where(
            FailureMode.project_id == pid, FailureMode.archived == False, FailureMode.parent_id == None)).all()]  # noqa: E711,E712
    tags = []
    if review:
        tags = [lab.failure_mode_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == review.id)).all()]
    return {"trace": view, "review": _review_dict(review), "system_same_as_previous": same_as_prev,
            "evaluator_results": flags, "quick_tags": modes, "tags": tags}


class ReviewIn(BaseModel):
    verdict: Optional[str] = None
    note: Optional[str] = None
    first_failure_event_id: Optional[int] = None
    deferred: Optional[bool] = None
    add_seconds: float = 0
    batch_id: Optional[int] = None
    fields: list[str] = []  # which of verdict/note/first_failure_event_id/deferred to apply (allows explicit nulls)
    tags: Optional[list[int]] = None  # quick-tag chips (later rounds only)


@router.put("/reviews/{tid}")
def save_review(pid: int, tid: int, body: ReviewIn, s: Session = Depends(get_session)):
    with _save_lock:
        return _save_review(pid, tid, body, s)


def _save_review(pid: int, tid: int, body: ReviewIn, s: Session):
    p = get_project(s, pid)
    t = s.get(Trace, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404, "Trace not found")
    if body.verdict not in (None, "pass", "fail"):
        raise HTTPException(400, "verdict must be pass or fail")
    r = s.exec(select(Review).where(Review.project_id == pid, Review.trace_id == tid)).first()
    if r is None:
        r = Review(project_id=pid, trace_id=tid, batch_id=body.batch_id, reviewer=p.reviewer_name, round=p.review_round)
    fields = body.fields or [f for f in REVIEW_FIELDS if getattr(body, f) is not None]
    snapshot = {f: getattr(r, f) for f in REVIEW_FIELDS}
    changed = any(getattr(body, f) != snapshot[f] for f in fields if f in REVIEW_FIELDS)
    if changed:
        # Collapse rapid note edits into one undo step.
        hist = list(r.history or [])
        last = hist[-1] if hist else None
        only_note = fields == ["note"]
        if not (only_note and last and last.get("_kind") == "note" and last.get("verdict") == r.verdict):
            hist.append({**snapshot, "_kind": "note" if only_note else "edit", "at": now().isoformat(), "reviewer": r.reviewer})
        r.history = hist[-200:]
    for f in fields:
        if f in REVIEW_FIELDS:
            setattr(r, f, getattr(body, f))
    if r.verdict and r.deferred and "deferred" not in fields:
        r.deferred = False
    if r.verdict and not r.reviewed_at:
        r.reviewed_at = now()
    if body.batch_id and not r.batch_id:
        r.batch_id = body.batch_id
    r.seconds_spent = (r.seconds_spent or 0) + max(0.0, min(body.add_seconds, 3600))
    r.reviewer = p.reviewer_name or r.reviewer
    r.updated_at = now()
    s.add(r)
    s.commit()
    s.refresh(r)
    if body.tags is not None:
        existing = {lab.failure_mode_id: lab for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == r.id)).all()}
        for fm_id in set(body.tags) - set(existing):
            s.add(ReviewLabel(review_id=r.id, trace_id=tid, failure_mode_id=fm_id, source="human"))
        for fm_id in set(existing) - set(body.tags):
            s.delete(existing[fm_id])
        s.commit()
    return _review_dict(r)


@router.post("/reviews/{tid}/undo")
def undo_review(pid: int, tid: int, s: Session = Depends(get_session)):
    with _save_lock:
        return _undo(pid, tid, s)


def _undo(pid: int, tid: int, s: Session):
    r = s.exec(select(Review).where(Review.project_id == pid, Review.trace_id == tid)).first()
    if not r or not r.history:
        raise HTTPException(409, "Nothing to undo")
    hist = list(r.history)
    prev = hist.pop()
    for f in REVIEW_FIELDS:
        setattr(r, f, prev.get(f))
    if not r.verdict:
        r.reviewed_at = None
    r.history = hist
    r.updated_at = now()
    s.add(r)
    s.commit()
    s.refresh(r)
    return _review_dict(r)


@router.get("/review/stats")
def review_stats(pid: int, batch_id: Optional[int] = None, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    q = select(Review).where(Review.project_id == pid)
    reviews = s.exec(q).all()
    ids = set(_batch_ids(s, batch_id)) if batch_id else None
    in_batch = [r for r in reviews if ids is None or r.trace_id in ids]
    done = [r for r in in_batch if r.verdict]
    secs = [r.seconds_spent for r in done if r.seconds_spent and r.seconds_spent > 0]
    return {
        "total": len(ids) if ids is not None else None,
        "reviewed": len(done),
        "passed": sum(1 for r in done if r.verdict == "pass"),
        "failed": sum(1 for r in done if r.verdict == "fail"),
        "deferred": sum(1 for r in in_batch if r.deferred and not r.verdict),
        "median_seconds": statistics.median(secs) if secs else None,
        "saturation": saturation(s, pid, int(p.settings.get("saturation_window", 20))),
        "ai": ai_state(s, p),
        "first_round": p.review_round == 1,
    }


@router.post("/traces/{tid}/similar")
def similar(pid: int, tid: int, k: int = 5, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    require_ai(s, p)
    t = s.get(Trace, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404)
    others = [o for o in s.exec(select(Trace).where(Trace.project_id == pid, Trace.id != tid)).all()]
    ref_terms = _terms(t.search_text)
    scored = sorted(others, key=lambda o: _jaccard(ref_terms, _terms(o.search_text)), reverse=True)[:25]
    ref_view = trace_view(s, t)
    cands = "\n\n".join(f'<candidate id="{o.id}">\n{trace_text(trace_view(s, o))[:1500]}\n</candidate>' for o in scored)
    prompt = render(get_template(s, "find_similar"), reference=trace_text(ref_view)[:3000], candidates=cands, k=k)
    schema = {"type": "object", "additionalProperties": False, "required": ["matches"], "properties": {"matches": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "why"], "properties": {"id": {"type": "integer"}, "why": {"type": "string"}}}}}}
    try:
        out = call_structured("find_similar", prompt, schema, project_id=pid,
                              mock_ctx={"candidates": [{"id": o.id, "score": _jaccard(ref_terms, _terms(o.search_text))} for o in scored], "k": k})
    except LLMError as e:
        raise HTTPException(502, str(e))
    valid = {o.id: o for o in scored}
    res = []
    for m in out["data"]["matches"][:k]:
        o = valid.get(m["id"])
        if o:
            first = next((e.content for e in s.exec(select(Event).where(Event.trace_id == o.id, Event.role == "user").order_by(Event.seq)).all()), "")
            res.append({"id": o.id, "external_id": o.external_id, "channel": o.channel, "why": m["why"], "snippet": first[:140]})
    return res


def _terms(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", text.lower())}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0
