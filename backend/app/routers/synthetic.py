"""Synthetic inputs for when there are no real traces yet.

Two separate LLM calls: (1) propose more tuples from the dimensions and the user's hand-written tuples,
(2) turn each accepted tuple into a natural user message. The split avoids repetitive phrasing.
Only user inputs are generated, never expected outputs.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..llm.client import LLMError, call_structured
from ..llm.templates import get_template, render
from ..models import SyntheticDimension, SyntheticTuple
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}/synthetic", tags=["synthetic"])

MIN_HAND_TUPLES = 20
DEFAULT_DIMS = [
    ("feature", ["availability search", "tour booking", "reschedule", "maintenance request", "policy question"]),
    ("scenario", ["happy path", "nothing matches", "ambiguous request", "asks for a human", "changes their mind"]),
    ("persona", ["first-time renter", "busy professional, terse", "non-native English speaker", "frustrated current resident"]),
]


def _dims(s: Session, pid: int) -> list[SyntheticDimension]:
    dims = list(s.exec(select(SyntheticDimension).where(SyntheticDimension.project_id == pid).order_by(SyntheticDimension.position)).all())
    if not dims:
        p = get_project(s, pid)
        for i, (name, vals) in enumerate(DEFAULT_DIMS):
            s.add(SyntheticDimension(project_id=pid, name=name, values=vals if p.is_demo else [], position=i))
        s.commit()
        dims = list(s.exec(select(SyntheticDimension).where(SyntheticDimension.project_id == pid).order_by(SyntheticDimension.position)).all())
    return dims


def _ai_ok(s: Session, pid: int) -> None:
    p = get_project(s, pid)
    if not p.settings.get("ai_assist_enabled", True):
        raise HTTPException(403, "AI assist is switched off in settings.")


@router.get("")
def state(pid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    tuples = s.exec(select(SyntheticTuple).where(SyntheticTuple.project_id == pid).order_by(SyntheticTuple.id)).all()
    human = sum(1 for t in tuples if t.source == "human")
    return {"dimensions": [{"id": d.id, "name": d.name, "values": d.values} for d in _dims(s, pid)],
            "tuples": [t.model_dump() for t in tuples], "grounding": p.settings.get("synthetic_grounding", ""),
            "hand_written": human, "min_hand_written": MIN_HAND_TUPLES, "ai_unlocked": human >= MIN_HAND_TUPLES}


class DimsIn(BaseModel):
    dimensions: list[dict]  # [{name, values}]
    grounding: Optional[str] = None


@router.put("")
def save_dims(pid: int, body: DimsIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    for d in _dims(s, pid):
        s.delete(d)
    s.commit()
    for i, d in enumerate(body.dimensions):
        if (d.get("name") or "").strip():
            s.add(SyntheticDimension(project_id=pid, name=d["name"].strip(), values=[v.strip() for v in d.get("values", []) if v.strip()], position=i))
    if body.grounding is not None:
        p.settings = {**p.settings, "synthetic_grounding": body.grounding}
        s.add(p)
    s.commit()
    return state(pid, s)


class TupleIn(BaseModel):
    values: dict
    user_message: str = ""


@router.post("/tuples")
def add_tuple(pid: int, body: TupleIn, s: Session = Depends(get_session)):
    if not any(str(v).strip() for v in body.values.values()):
        raise HTTPException(400, "Fill in at least one dimension")
    t = SyntheticTuple(project_id=pid, values=body.values, source="human", status="accepted", user_message=body.user_message)
    s.add(t)
    s.commit()
    s.refresh(t)
    return t


class TuplePatch(BaseModel):
    status: Optional[str] = None
    user_message: Optional[str] = None
    values: Optional[dict] = None


@router.patch("/tuples/{tid}")
def edit_tuple(pid: int, tid: int, body: TuplePatch, s: Session = Depends(get_session)):
    t = s.get(SyntheticTuple, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    s.add(t)
    s.commit()
    return t


@router.delete("/tuples/{tid}")
def delete_tuple(pid: int, tid: int, s: Session = Depends(get_session)):
    t = s.get(SyntheticTuple, tid)
    if t and t.project_id == pid:
        s.delete(t)
        s.commit()
    return {"ok": True}


TUPLES_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["tuples"], "properties": {"tuples": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["values"], "properties": {"values": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["dimension", "value"],
        "properties": {"dimension": {"type": "string"}, "value": {"type": "string"}}}}}}}}}
INPUTS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["messages"], "properties": {"messages": {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["tuple_id", "message"],
    "properties": {"tuple_id": {"type": "integer"}, "message": {"type": "string"}}}}}}


class ProposeIn(BaseModel):
    count: int = 20


@router.post("/propose")
def propose(pid: int, body: ProposeIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    _ai_ok(s, pid)
    st = state(pid, s)
    if not st["ai_unlocked"]:
        raise HTTPException(403, f"Write at least {MIN_HAND_TUPLES} tuples by hand first ({st['hand_written']} so far).")
    dims = st["dimensions"]
    tuples = [t for t in st["tuples"] if t["status"] == "accepted"]
    prompt = render(get_template(s, "synthetic_tuples"), product_name=p.name, product_description=p.description,
                    grounding=st["grounding"] or "(none)", count=body.count,
                    dimensions="\n".join(f"- {d['name']}: {', '.join(d['values']) or '(open)'}" for d in dims),
                    tuples="\n".join("- " + ", ".join(f"{k}={v}" for k, v in t["values"].items()) for t in tuples))
    try:
        out = call_structured("synthetic_tuples", prompt, TUPLES_SCHEMA, project_id=pid,
                              mock_ctx={"dimensions": dims, "existing": [t["values"] for t in tuples], "count": body.count})
    except LLMError as e:
        raise HTTPException(502, str(e))
    existing = {json.dumps(t["values"], sort_keys=True) for t in st["tuples"]}
    n = 0
    for tp in out["data"]["tuples"]:
        vals = {x["dimension"]: x["value"] for x in tp["values"]}
        key = json.dumps(vals, sort_keys=True)
        if key in existing:
            continue
        existing.add(key)
        s.add(SyntheticTuple(project_id=pid, values=vals, source="ai", status="pending"))
        n += 1
    s.commit()
    return {"created": n, **state(pid, s)}


@router.post("/inputs")
def generate_inputs(pid: int, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    _ai_ok(s, pid)
    st = state(pid, s)
    if not st["ai_unlocked"]:
        raise HTTPException(403, f"Write at least {MIN_HAND_TUPLES} tuples by hand first.")
    todo = [t for t in s.exec(select(SyntheticTuple).where(SyntheticTuple.project_id == pid, SyntheticTuple.status == "accepted")).all()
            if not t.user_message.strip()]
    n = 0
    for i in range(0, len(todo), 25):
        chunk = todo[i:i + 25]
        prompt = render(get_template(s, "synthetic_inputs"), product_name=p.name, product_description=p.description,
                        channels="; ".join(f"{c['name']}: {c['render_rule']}" for c in p.channels) or "(none)",
                        grounding=st["grounding"] or "(none)",
                        tuples="\n".join(f"[{t.id}] " + ", ".join(f"{k}={v}" for k, v in t.values.items()) for t in chunk))
        try:
            out = call_structured("synthetic_inputs", prompt, INPUTS_SCHEMA, project_id=pid,
                                  mock_ctx={"tuples": [{"id": t.id, "values": t.values} for t in chunk], "grounding": st["grounding"]})
        except LLMError as e:
            raise HTTPException(502, str(e))
        by_id = {t.id: t for t in chunk}
        for m in out["data"]["messages"]:
            t = by_id.get(m["tuple_id"])
            if t and m["message"].strip():
                t.user_message = m["message"].strip()
                s.add(t)
                n += 1
        s.commit()
    return {"generated": n, **state(pid, s)}


@router.get("/export")
def export_inputs(pid: int, format: str = "jsonl", s: Session = Depends(get_session)):
    rows = [t for t in s.exec(select(SyntheticTuple).where(SyntheticTuple.project_id == pid, SyntheticTuple.status == "accepted")).all() if t.user_message.strip()]
    if format == "csv":
        out = io.StringIO()
        dims = sorted({k for t in rows for k in t.values})
        w = csv.writer(out)
        w.writerow(["id", "input", *dims])
        for t in rows:
            w.writerow([f"syn-{t.id}", t.user_message, *[t.values.get(d, "") for d in dims]])
        return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="synthetic_inputs.csv"'})
    body = "\n".join(json.dumps({"id": f"syn-{t.id}", "input": t.user_message, "tuple": t.values}) for t in rows) + "\n"
    return Response(body, media_type="application/x-ndjson", headers={"Content-Disposition": 'attachment; filename="synthetic_inputs.jsonl"'})
