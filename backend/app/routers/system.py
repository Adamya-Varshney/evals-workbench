from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from ..config import settings
from ..db import get_session
from ..models import LLMCall, PromptTemplate, now

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/meta")
def meta():
    return {"llm_mode": settings.llm_mode, "model": settings.model, "has_key": bool(settings.anthropic_api_key),
            "concurrency": settings.llm_concurrency, "demo_mode": settings.demo_mode, "demo_reset_hours": settings.demo_reset_hours}


@router.get("/llm_calls")
def llm_calls(project_id: Optional[int] = None, limit: int = 100, s: Session = Depends(get_session)):
    q = select(LLMCall).order_by(LLMCall.id.desc()).limit(limit)
    if project_id:
        q = q.where(LLMCall.project_id == project_id)
    calls = s.exec(q).all()
    tq = select(func.count(), func.coalesce(func.sum(LLMCall.cost_usd), 0), func.coalesce(func.sum(LLMCall.input_tokens), 0),
                func.coalesce(func.sum(LLMCall.output_tokens), 0))
    if project_id:
        tq = tq.where(LLMCall.project_id == project_id)
    n, cost, tin, tout = s.exec(tq).one()
    return {"totals": {"calls": n, "cost_usd": cost, "input_tokens": tin, "output_tokens": tout}, "calls": calls}


@router.get("/templates")
def templates(s: Session = Depends(get_session)):
    return s.exec(select(PromptTemplate).order_by(PromptTemplate.id)).all()


class TemplateIn(BaseModel):
    body: str


@router.put("/templates/{key}")
def save_template(key: str, body: TemplateIn, s: Session = Depends(get_session)):
    t = s.exec(select(PromptTemplate).where(PromptTemplate.key == key)).first()
    if not t:
        raise HTTPException(404)
    t.body, t.updated_at = body.body, now()
    s.add(t)
    s.commit()
    return t


@router.post("/templates/{key}/reset")
def reset_template(key: str, s: Session = Depends(get_session)):
    t = s.exec(select(PromptTemplate).where(PromptTemplate.key == key)).first()
    if not t:
        raise HTTPException(404)
    t.body, t.updated_at = t.default_body, now()
    s.add(t)
    s.commit()
    return t
