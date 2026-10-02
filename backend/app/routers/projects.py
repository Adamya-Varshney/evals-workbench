from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import DEFAULT_PROJECT_SETTINGS, Project, PromptVersion
from ..services.status import project_status

router = APIRouter(prefix="/api/projects", tags=["projects"])

DEMO = dict(
    name="Larkspur Residences",
    description=(
        "Lark is the leasing assistant for Larkspur Residences, three apartment communities around Austin. "
        "It answers prospects and current residents, searches available units, books and moves tours, "
        "files maintenance requests and hands conversations to the leasing team."
    ),
    channels=[
        {"name": "sms", "render_rule": "SMS is plain text exactly as a phone shows it. Markdown symbols appear literally. Keep it short."},
        {"name": "email", "render_rule": "Email renders as an email: greeting, body, sign-off. Plain text."},
        {"name": "chat", "render_rule": "The website chat widget shows plain text with line breaks; it does not render markdown."},
        {"name": "voice", "render_rule": "Voice replies are read aloud by text-to-speech. No lists, links or symbols."},
    ],
    business_facts=(
        "- We do not offer virtual tours. Tours are in person or self-guided (via the Larkspur app).\n"
        "- Same-day tour requests must go to a human leasing agent.\n"
        "- If someone asks for a person, the leasing team takes over (handoff_to_human). Office hours Mon–Sat 9–6, Sun 12–5.\n"
        "- Every prospect who can't find a match should get an alternative: sister property, notify list, or the current special.\n"
        "- Current special: one month free on a 13-month lease at Riverside.\n"
        "- Pets: up to 2 per home, $300 deposit and $25/mo each. Unit C-112 and R-207 are in pet-free buildings."
    ),
)


class ProjectIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    channels: Optional[list[dict]] = None
    business_facts: Optional[str] = None
    reviewer_name: Optional[str] = None
    settings: Optional[dict[str, Any]] = None


def get_project(s: Session, pid: int) -> Project:
    p = s.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


@router.get("")
def list_projects(s: Session = Depends(get_session)):
    return s.exec(select(Project).order_by(Project.id)).all()


@router.post("")
def create_project(body: ProjectIn, s: Session = Depends(get_session)):
    p = Project(name=body.name or "Untitled project", description=body.description or "",
                channels=body.channels or [], business_facts=body.business_facts or "",
                reviewer_name=body.reviewer_name or "", settings={**DEFAULT_PROJECT_SETTINGS, **(body.settings or {})})
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


@router.post("/demo")
def create_demo(s: Session = Depends(get_session)):
    existing = s.exec(select(Project).where(Project.is_demo == True)).first()  # noqa: E712
    if existing:
        return existing
    p = Project(**DEMO, is_demo=True, settings=dict(DEFAULT_PROJECT_SETTINGS))
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


@router.get("/{pid}")
def read_project(pid: int, s: Session = Depends(get_session)):
    return get_project(s, pid)


@router.patch("/{pid}")
def update_project(pid: int, body: ProjectIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    data = body.model_dump(exclude_unset=True)
    if "settings" in data:
        data["settings"] = {**p.settings, **(data["settings"] or {})}
    for k, v in data.items():
        setattr(p, k, v)
    s.add(p)
    s.commit()
    s.refresh(p)
    return p


@router.delete("/{pid}")
def delete_project(pid: int, s: Session = Depends(get_session)):
    from ..services.cleanup import delete_project_cascade

    delete_project_cascade(s, get_project(s, pid))
    return {"ok": True}


@router.get("/{pid}/status")
def status(pid: int, s: Session = Depends(get_session)):
    return project_status(s, get_project(s, pid))


class PromptVersionIn(BaseModel):
    label: str
    body: str = ""


@router.get("/{pid}/prompt_versions")
def list_versions(pid: int, s: Session = Depends(get_session)):
    return s.exec(select(PromptVersion).where(PromptVersion.project_id == pid).order_by(PromptVersion.id)).all()


@router.post("/{pid}/prompt_versions")
def add_version(pid: int, body: PromptVersionIn, s: Session = Depends(get_session)):
    get_project(s, pid)
    if s.exec(select(PromptVersion).where(PromptVersion.project_id == pid, PromptVersion.label == body.label)).first():
        raise HTTPException(409, f"Version '{body.label}' already exists")
    pv = PromptVersion(project_id=pid, label=body.label, body=body.body)
    s.add(pv)
    s.commit()
    s.refresh(pv)
    return pv


@router.patch("/{pid}/prompt_versions/{vid}")
def edit_version(pid: int, vid: int, body: PromptVersionIn, s: Session = Depends(get_session)):
    pv = s.get(PromptVersion, vid)
    if not pv or pv.project_id != pid:
        raise HTTPException(404)
    pv.label, pv.body = body.label, body.body
    s.add(pv)
    s.commit()
    return pv
