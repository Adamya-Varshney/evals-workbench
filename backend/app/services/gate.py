from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session

from ..models import Project
from .status import ai_state


def require_ai(s: Session, p: Project) -> None:
    """AI-assist features stay locked until enough traces are reviewed by hand, and obey the global switch."""
    st = ai_state(s, p)
    if not st["unlocked"]:
        raise HTTPException(403, st["reason"])
