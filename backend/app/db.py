from __future__ import annotations

from typing import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine(settings.db_url)
    return _engine


def make_engine(url: str):
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return eng


def set_engine(eng) -> None:
    """Used by tests to point the app at a throwaway database."""
    global _engine
    _engine = eng


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(get_engine())
    from .llm.templates import ensure_templates

    with Session(get_engine()) as s:
        ensure_templates(s)


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as s:
        yield s
