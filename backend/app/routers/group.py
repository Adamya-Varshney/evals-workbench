"""Stage 4 (group failures / axial coding) and stage 5 (count and prioritise)."""
from __future__ import annotations

from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..llm.client import LLMError, call_structured
from ..llm.templates import get_template, render
from ..models import AssignmentSuggestion, CategoryProposal, FailureMode, Review, ReviewLabel, Trace
from ..services import taxonomy as tx
from ..services.gate import require_ai
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}", tags=["group"])


# ------------------------------------------------------------------ helpers
def _mode(s: Session, pid: int, fid: int) -> FailureMode:
    m = s.get(FailureMode, fid)
    if not m or m.project_id != pid:
        raise HTTPException(404, "Failure mode not found")
    return m


def _modes(s: Session, pid: int) -> list[FailureMode]:
    return list(s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.archived == False)  # noqa: E712
                       .order_by(FailureMode.rank, FailureMode.id)).all())


def _note_reviews(s: Session, pid: int) -> list[Review]:
    rs = s.exec(select(Review).where(Review.project_id == pid, Review.verdict.is_not(None)).order_by(Review.reviewed_at, Review.id)).all()
    return [r for r in rs if r.verdict == "fail" or r.note.strip()]


def mode_view(m: FailureMode, counts: Counter, recheck: Counter) -> dict:
    return {
        "id": m.id, "name": m.name, "definition": m.definition, "counts_as": m.counts_as, "does_not_count_as": m.does_not_count_as,
        "parent_id": m.parent_id, "severity": m.severity, "impact_note": m.impact_note, "decision": m.decision,
        "decision_note": m.decision_note, "rank": m.rank, "is_none_bucket": m.is_none_bucket, "version": m.version,
        "n_labels": counts.get(m.id, 0), "n_recheck": recheck.get(m.id, 0),
        "warnings": tx.specificity_warnings(m), "history_len": len(m.history or []),
    }


def _label_counts(s: Session, pid: int) -> tuple[Counter, Counter]:
    labs = s.exec(select(ReviewLabel).join(Review, ReviewLabel.review_id == Review.id).where(Review.project_id == pid)).all()
    return Counter(lab.failure_mode_id for lab in labs), Counter(lab.failure_mode_id for lab in labs if lab.needs_recheck)


# ------------------------------------------------------------------ notes
@router.get("/group/notes")
def notes(pid: int, s: Session = Depends(get_session)):
    reviews = _note_reviews(s, pid)
    rids = [r.id for r in reviews]
    traces = {t.id: t for t in s.exec(select(Trace).where(Trace.id.in_([r.trace_id for r in reviews]))).all()} if reviews else {}
    labs: dict[int, list] = {}
    for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id.in_(rids))).all() if rids else []:
        labs.setdefault(lab.review_id, []).append({"failure_mode_id": lab.failure_mode_id, "source": lab.source, "needs_recheck": lab.needs_recheck})
    sugg = {}
    for sg in s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.project_id == pid, AssignmentSuggestion.status == "pending")).all():
        sugg[sg.review_id] = {"id": sg.id, "failure_mode_ids": sg.failure_mode_ids, "rationale": sg.rationale}
    out = []
    for r in reviews:
        t = traces.get(r.trace_id)
        out.append({"review_id": r.id, "trace_id": r.trace_id, "external_id": t.external_id if t else "", "channel": t.channel if t else "",
                    "verdict": r.verdict, "note": r.note, "labels": labs.get(r.id, []), "suggestion": sugg.get(r.id)})
    return out


@router.get("/group/summary")
def summary(pid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    rows = notes(pid, s)
    none = s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.is_none_bucket == True)).first()  # noqa: E712
    confirmed = s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.project_id == pid,
                                                          AssignmentSuggestion.status.in_(["accepted", "changed"]))).all()
    from ..services.status import ai_state

    return {
        "notes": len(rows),
        "failing_notes": sum(1 for r in rows if r["verdict"] == "fail"),
        "unassigned": sum(1 for r in rows if r["verdict"] == "fail" and not r["labels"]),
        "pending_suggestions": sum(1 for r in rows if r["suggestion"]),
        "in_none": sum(1 for r in rows if none and any(lab["failure_mode_id"] == none.id for lab in r["labels"])),
        "recheck": sum(1 for r in rows if any(lab["needs_recheck"] for lab in r["labels"])),
        "confirmed_individually": len(confirmed),
        "bulk_unlocked": len(confirmed) >= 10,
        "none_id": none.id if none else None,
        "ai": ai_state(s, p),
        "colleague_test": tx.COLLEAGUE_TEST,
    }


class LabelsIn(BaseModel):
    failure_mode_ids: list[int]


@router.put("/group/labels/{rid}")
def put_labels(pid: int, rid: int, body: LabelsIn, s: Session = Depends(get_session)):
    r = s.get(Review, rid)
    if not r or r.project_id != pid:
        raise HTTPException(404, "Review not found")
    for fid in body.failure_mode_ids:
        _mode(s, pid, fid)
    tx.set_labels(s, r, body.failure_mode_ids, "human")
    for sg in s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.review_id == rid, AssignmentSuggestion.status == "pending")).all():
        sg.status = "changed" if sorted(sg.failure_mode_ids) != sorted(body.failure_mode_ids) else "accepted"
        s.add(sg)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ taxonomy
class ModeIn(BaseModel):
    name: Optional[str] = None
    definition: Optional[str] = None
    counts_as: Optional[str] = None
    does_not_count_as: Optional[str] = None
    parent_id: Optional[int] = None
    severity: Optional[str] = None
    impact_note: Optional[str] = None
    decision: Optional[str] = None
    decision_note: Optional[str] = None
    from_review_id: Optional[int] = None


def _check_parent(s: Session, pid: int, parent_id: Optional[int], self_id: Optional[int] = None) -> None:
    if parent_id is None:
        return
    parent = _mode(s, pid, parent_id)
    if parent.parent_id is not None:
        raise HTTPException(400, "Only one level of sub-category is allowed")
    if parent.is_none_bucket:
        raise HTTPException(400, "'None of the above' cannot have sub-categories")
    if self_id is not None:
        if parent_id == self_id:
            raise HTTPException(400, "A failure mode cannot be its own parent")
        if s.exec(select(FailureMode).where(FailureMode.parent_id == self_id, FailureMode.archived == False)).first():  # noqa: E712
            raise HTTPException(400, "This failure mode has sub-categories, so it cannot become one")


@router.get("/failure_modes")
def list_modes(pid: int, s: Session = Depends(get_session)):
    counts, recheck = _label_counts(s, pid)
    return [mode_view(m, counts, recheck) for m in _modes(s, pid)]


@router.post("/failure_modes")
def create_mode(pid: int, body: ModeIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    if not (body.name or "").strip():
        raise HTTPException(400, "Name is required")
    _check_parent(s, pid, body.parent_id)
    none = tx.none_bucket(s, pid)
    rank = max([m.rank for m in _modes(s, pid) if not m.is_none_bucket] or [0]) + 1
    m = FailureMode(project_id=pid, name=body.name.strip(), definition=body.definition or "", counts_as=body.counts_as or "",
                    does_not_count_as=body.does_not_count_as or "", parent_id=body.parent_id, rank=rank)
    tx.add_history(m, "create", {"name": [None, m.name]}, p.reviewer_name)
    s.add(m)
    s.commit()
    s.refresh(m)
    if body.from_review_id:
        r = s.get(Review, body.from_review_id)
        if r and r.project_id == pid:
            current = [lab.failure_mode_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == r.id)).all()]
            tx.set_labels(s, r, [x for x in current if x != none.id] + [m.id], "human")
    return mode_view(m, Counter(), Counter())


@router.patch("/failure_modes/{fid}")
def edit_mode(pid: int, fid: int, body: ModeIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    m = _mode(s, pid, fid)
    data = body.model_dump(exclude_unset=True, exclude={"from_review_id"})
    if "parent_id" in data:
        _check_parent(s, pid, data["parent_id"], fid)
        if m.parent_id != data["parent_id"]:
            tx.add_history(m, "move", {"parent_id": [m.parent_id, data["parent_id"]]}, p.reviewer_name)
            m.parent_id = data.pop("parent_id")
        else:
            data.pop("parent_id")
    if m.is_none_bucket and "name" in data:
        raise HTTPException(400, "'None of the above' cannot be renamed")
    if data.get("severity") not in (None, "", "low", "high", "catastrophic"):
        raise HTTPException(400, "severity must be low, high or catastrophic")
    if data.get("decision") not in (None, "", "fix_now", "code_check", "llm_judge", "park"):
        raise HTTPException(400, "decision must be fix_now, code_check, llm_judge or park")
    tx.apply_edit(s, m, data, p.reviewer_name)
    counts, recheck = _label_counts(s, pid)
    return mode_view(m, counts, recheck)


@router.get("/failure_modes/{fid}/history")
def mode_history(pid: int, fid: int, s: Session = Depends(get_session)):
    return list(reversed(_mode(s, pid, fid).history or []))


@router.delete("/failure_modes/{fid}")
def delete_mode(pid: int, fid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    m = _mode(s, pid, fid)
    if m.is_none_bucket:
        raise HTTPException(400, "'None of the above' always exists")
    for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == fid)).all():
        s.delete(lab)
    for child in s.exec(select(FailureMode).where(FailureMode.parent_id == fid)).all():
        child.parent_id = None
        s.add(child)
    m.archived = True
    tx.add_history(m, "delete", {}, p.reviewer_name)
    s.add(m)
    s.commit()
    return {"ok": True}


class MergeIn(BaseModel):
    source_ids: list[int]
    target_id: int


@router.post("/failure_modes/merge")
def merge(pid: int, body: MergeIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    target = _mode(s, pid, body.target_id)
    for sid in body.source_ids:
        if sid == target.id:
            continue
        src = _mode(s, pid, sid)
        if src.is_none_bucket:
            raise HTTPException(400, "Cannot merge 'None of the above'")
        have = {lab.review_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == target.id)).all()}
        for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == sid)).all():
            if lab.review_id in have:
                s.delete(lab)
            else:
                lab.failure_mode_id = target.id
                lab.needs_recheck = True
                s.add(lab)
                have.add(lab.review_id)
        for child in s.exec(select(FailureMode).where(FailureMode.parent_id == sid)).all():
            child.parent_id = target.id if target.parent_id is None else None
            s.add(child)
        src.archived = True
        tx.add_history(src, "merged_into", {"target": [None, target.name]}, p.reviewer_name)
        tx.add_history(target, "merged_from", {"source": [None, src.name]}, p.reviewer_name)
        s.add(src)
        s.add(target)
    s.commit()
    return {"ok": True}


class SplitIn(BaseModel):
    parts: list[dict]  # [{name, definition}]
    as_children: bool = False


@router.post("/failure_modes/{fid}/split")
def split(pid: int, fid: int, body: SplitIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    m = _mode(s, pid, fid)
    if m.is_none_bucket:
        raise HTTPException(400, "Cannot split 'None of the above'")
    if len(body.parts) < 2:
        raise HTTPException(400, "Split into at least two parts")
    if body.as_children and m.parent_id is not None:
        raise HTTPException(400, "Only one level of sub-category is allowed")
    created = []
    rank = max([x.rank for x in _modes(s, pid) if not x.is_none_bucket] or [0])
    for i, part in enumerate(body.parts):
        nm = FailureMode(project_id=pid, name=part.get("name", "").strip() or f"{m.name} ({i + 1})", definition=part.get("definition", ""),
                         parent_id=m.id if body.as_children else m.parent_id, rank=rank + i + 1)
        tx.add_history(nm, "split_from", {"source": [None, m.name]}, p.reviewer_name)
        s.add(nm)
        created.append(nm)
    for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == fid)).all():
        lab.needs_recheck = True  # the reviewer moves each note into the right part
        s.add(lab)
    tx.add_history(m, "split", {"into": [None, [c.name for c in created]]}, p.reviewer_name)
    s.add(m)
    s.commit()
    return {"created": [c.id for c in created]}


class ReorderIn(BaseModel):
    ids: list[int]


@router.post("/failure_modes/reorder")
def reorder(pid: int, body: ReorderIn, s: Session = Depends(get_session)):
    for i, fid in enumerate(body.ids):
        m = _mode(s, pid, fid)
        if not m.is_none_bucket:
            m.rank = i + 1
            s.add(m)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ AI: propose categories
PROPOSE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["proposals"], "properties": {"proposals": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["name", "definition", "example_note_ids"],
                               "properties": {"name": {"type": "string"}, "definition": {"type": "string"},
                                              "example_note_ids": {"type": "array", "items": {"type": "integer"}}}}}}}


@router.post("/group/propose")
def propose(pid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    require_ai(s, p)
    reviews = [r for r in _note_reviews(s, pid) if r.verdict == "fail" and r.note.strip()]
    if len(reviews) < 3:
        raise HTTPException(400, "Write notes on at least 3 failing traces first")
    notes_txt = "\n".join(f"[{r.id}] {r.note.strip()}" for r in reviews)
    prompt = render(get_template(s, "propose_categories"), product_name=p.name, product_description=p.description, notes=notes_txt)
    try:
        out = call_structured("propose_categories", prompt, PROPOSE_SCHEMA, project_id=pid,
                              mock_ctx={"notes": [{"id": r.id, "note": r.note} for r in reviews]})
    except LLMError as e:
        raise HTTPException(502, str(e))
    valid = {r.id for r in reviews}
    for old in s.exec(select(CategoryProposal).where(CategoryProposal.project_id == pid, CategoryProposal.status == "pending")).all():
        s.delete(old)
    for pr in out["data"]["proposals"][:8]:
        s.add(CategoryProposal(project_id=pid, name=pr["name"], definition=pr["definition"],
                               example_review_ids=[i for i in pr["example_note_ids"] if i in valid]))
    s.commit()
    return proposals(pid, s)


@router.get("/group/proposals")
def proposals(pid: int, s: Session = Depends(get_session)):
    rows = s.exec(select(CategoryProposal).where(CategoryProposal.project_id == pid, CategoryProposal.status == "pending")).all()
    notes_by = {r.id: r.note for r in _note_reviews(s, pid)}
    return [{"id": c.id, "name": c.name, "definition": c.definition, "examples": [{"review_id": i, "note": notes_by.get(i, "")} for i in c.example_review_ids],
             "warnings": tx.specificity_warnings(FailureMode(project_id=pid, name=c.name, definition=c.definition, counts_as="x", does_not_count_as="x"))}
            for c in rows]


@router.post("/group/proposals/{cid}/accept")
def accept_proposal(pid: int, cid: int, body: ModeIn, s: Session = Depends(get_session)):
    c = s.get(CategoryProposal, cid)
    if not c or c.project_id != pid:
        raise HTTPException(404)
    m = create_mode(pid, ModeIn(name=body.name or c.name, definition=body.definition if body.definition is not None else c.definition,
                                counts_as=body.counts_as, does_not_count_as=body.does_not_count_as), s)
    c.status = "accepted"
    s.add(c)
    s.commit()
    return m


@router.post("/group/proposals/{cid}/reject")
def reject_proposal(pid: int, cid: int, s: Session = Depends(get_session)):
    c = s.get(CategoryProposal, cid)
    if not c or c.project_id != pid:
        raise HTTPException(404)
    c.status = "rejected"
    s.add(c)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ AI: suggest assignments
SUGGEST_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["assignments"], "properties": {"assignments": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["note_id", "failure_mode_ids", "rationale"],
                               "properties": {"note_id": {"type": "integer"}, "failure_mode_ids": {"type": "array", "items": {"type": "integer"}},
                                              "rationale": {"type": "string"}}}}}}


class SuggestIn(BaseModel):
    scope: str = "unassigned"  # unassigned | recheck


@router.post("/group/suggest")
def suggest(pid: int, body: SuggestIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    require_ai(s, p)
    none = tx.none_bucket(s, pid)
    modes = [m for m in _modes(s, pid)]
    real = [m for m in modes if not m.is_none_bucket]
    if not real:
        raise HTTPException(400, "Create at least one failure mode first")
    labelled = {lab.review_id: lab for lab in s.exec(select(ReviewLabel).join(Review, ReviewLabel.review_id == Review.id).where(Review.project_id == pid)).all()}
    recheck = {lab.review_id for lab in labelled.values() if lab.needs_recheck}
    if body.scope == "recheck":
        targets = [r for r in _note_reviews(s, pid) if r.id in recheck]
    else:
        targets = [r for r in _note_reviews(s, pid) if r.verdict == "fail" and r.id not in labelled and r.note.strip()]
    if not targets:
        return {"created": 0}
    modes_txt = "\n".join(
        f"[{m.id}] {m.name}{' (sub-category of ' + str(m.parent_id) + ')' if m.parent_id else ''} — {m.definition}"
        + (f"\n    Counts as: {m.counts_as}" if m.counts_as else "") + (f"\n    Does not count as: {m.does_not_count_as}" if m.does_not_count_as else "")
        for m in modes)
    valid_ids = {m.id for m in modes}
    target_ids = {r.id for r in targets}
    created = 0
    for i in range(0, len(targets), 40):
        chunk = targets[i:i + 40]
        prompt = render(get_template(s, "suggest_assignments"), failure_modes=modes_txt, none_id=none.id,
                        notes="\n".join(f"[{r.id}] {r.note.strip()}" for r in chunk))
        try:
            out = call_structured("suggest_assignments", prompt, SUGGEST_SCHEMA, project_id=pid, mock_ctx={
                "notes": [{"id": r.id, "note": r.note} for r in chunk], "none_id": none.id,
                "modes": [{"id": m.id, "name": m.name, "definition": m.definition, "counts_as": m.counts_as} for m in real]})
        except LLMError as e:
            raise HTTPException(502, str(e))
        for a in out["data"]["assignments"]:
            if a["note_id"] not in target_ids:
                continue
            ids = [x for x in a["failure_mode_ids"] if x in valid_ids] or [none.id]
            if none.id in ids and len(ids) > 1:
                ids = [x for x in ids if x != none.id]
            for old in s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.review_id == a["note_id"], AssignmentSuggestion.status == "pending")).all():
                s.delete(old)
            s.add(AssignmentSuggestion(project_id=pid, review_id=a["note_id"], failure_mode_ids=ids, rationale=a["rationale"]))
            created += 1
        s.commit()
    return {"created": created}


class AcceptIn(BaseModel):
    failure_mode_ids: Optional[list[int]] = None


@router.post("/group/suggestions/{sid}/accept")
def accept_suggestion(pid: int, sid: int, body: AcceptIn, s: Session = Depends(get_session)):
    sg = s.get(AssignmentSuggestion, sid)
    if not sg or sg.project_id != pid or sg.status != "pending":
        raise HTTPException(404, "Suggestion not found or already handled")
    ids = body.failure_mode_ids if body.failure_mode_ids is not None else sg.failure_mode_ids
    for fid in ids:
        _mode(s, pid, fid)
    changed = sorted(ids) != sorted(sg.failure_mode_ids)
    r = s.get(Review, sg.review_id)
    tx.set_labels(s, r, ids, "human" if changed else "ai_confirmed")
    sg.status = "changed" if changed else "accepted"
    s.add(sg)
    s.commit()
    return {"ok": True, "status": sg.status}


@router.post("/group/suggestions/{sid}/reject")
def reject_suggestion(pid: int, sid: int, s: Session = Depends(get_session)):
    sg = s.get(AssignmentSuggestion, sid)
    if not sg or sg.project_id != pid:
        raise HTTPException(404)
    sg.status = "rejected"
    s.add(sg)
    s.commit()
    return {"ok": True}


class BulkIn(BaseModel):
    failure_mode_id: int


@router.post("/group/suggestions/bulk_accept")
def bulk_accept(pid: int, body: BulkIn, s: Session = Depends(get_session)):
    confirmed = len(s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.project_id == pid,
                                                              AssignmentSuggestion.status.in_(["accepted", "changed"]))).all())
    if confirmed < 10:
        raise HTTPException(409, f"Confirm at least 10 suggestions one by one before bulk-accepting ({confirmed} so far).")
    n = 0
    for sg in s.exec(select(AssignmentSuggestion).where(AssignmentSuggestion.project_id == pid, AssignmentSuggestion.status == "pending")).all():
        if sg.failure_mode_ids == [body.failure_mode_id]:
            tx.set_labels(s, s.get(Review, sg.review_id), sg.failure_mode_ids, "ai_confirmed")
            sg.status = "accepted"
            s.add(sg)
            n += 1
    s.commit()
    return {"accepted": n}


# ------------------------------------------------------------------ count
@router.get("/count")
def count(pid: int, facet: Optional[str] = None, batch_id: Optional[int] = None, s: Session = Depends(get_session)):
    get_project(s, pid)
    return tx.count_table(s, pid, facet or None, batch_id)


def _step_label(e) -> str:
    if e.role == "tool_call":
        return e.tool_name or "tool call"
    if e.role == "tool_result":
        return f"{e.tool_name or 'tool'} result"
    return "assistant reply" if e.role == "assistant" else "user turn"


@router.get("/count/transitions")
def transitions(pid: int, s: Session = Depends(get_session)):
    """Transition failure matrix: last successful step (rows) → first failing step (columns),
    from first-failure anchors on failing traces that contain tool steps."""
    from ..models import Event

    reviews = s.exec(select(Review).where(Review.project_id == pid, Review.verdict == "fail", Review.first_failure_event_id.is_not(None))).all()
    cells: Counter = Counter()
    examples: dict[str, list[int]] = {}
    used = 0
    for r in reviews:
        evs = list(s.exec(select(Event).where(Event.trace_id == r.trace_id).order_by(Event.seq)).all())
        if not any(e.role == "tool_call" for e in evs):
            continue
        idx = next((i for i, e in enumerate(evs) if e.id == r.first_failure_event_id), None)
        if idx is None:
            continue
        before = [e for e in evs[:idx] if e.role == "tool_call"]
        last_ok = before[-1].tool_name if before else "conversation start"
        first_bad = _step_label(evs[idx])
        cells[(last_ok, first_bad)] += 1
        examples.setdefault(f"{last_ok}→{first_bad}", []).append(r.trace_id)
        used += 1
    rows = sorted({a for a, _ in cells}, key=lambda x: (x != "conversation start", x))
    cols = sorted({b for _, b in cells})
    return {"rows": rows, "cols": cols, "cells": [{"from": a, "to": b, "count": n, "trace_ids": examples[f"{a}→{b}"]} for (a, b), n in cells.items()],
            "n": used}


@router.get("/count/traces")
def count_traces(pid: int, failure_mode_id: Optional[int] = None, facet: Optional[str] = None, value: Optional[str] = None,
                 s: Session = Depends(get_session)):
    modes = _modes(s, pid)
    roll = tx.descendants(modes)
    reviews = {r.id: r for r in s.exec(select(Review).where(Review.project_id == pid, Review.verdict.is_not(None))).all()}
    if failure_mode_id:
        ids = roll.get(failure_mode_id, {failure_mode_id})
        rids = {lab.review_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id.in_(ids))).all()}
    else:
        rids = set(reviews)
    out = []
    names = {m.id: m.name for m in modes}
    labs_by: dict[int, list[str]] = {}
    for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id.in_(rids))).all() if rids else []:
        labs_by.setdefault(lab.review_id, []).append(names.get(lab.failure_mode_id, "?"))
    for rid in rids:
        r = reviews.get(rid)
        if not r:
            continue
        t = s.get(Trace, r.trace_id)
        if facet and value is not None:
            v = t.channel if facet == "channel" else (str(t.synthetic).lower() if facet == "synthetic" else t.meta.get(facet))
            if ("(none)" if v is None else str(v)) != value:
                continue
        out.append({"review_id": r.id, "trace_id": t.id, "external_id": t.external_id, "channel": t.channel, "verdict": r.verdict,
                    "note": r.note, "modes": labs_by.get(r.id, [])})
    return sorted(out, key=lambda x: x["external_id"])
