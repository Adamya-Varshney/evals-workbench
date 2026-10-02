"""Failure taxonomy helpers: specificity checks, history, label bookkeeping, counting."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Optional

from sqlmodel import Session, select

from ..models import FailureMode, Review, ReviewLabel, Trace, now

VAGUE_WORDS = {"quality", "temporal", "general", "capability", "capabilities", "misc", "miscellaneous", "other", "others",
               "issue", "issues", "problem", "problems", "error", "errors", "bad", "various", "stuff", "accuracy", "performance"}
COLLEAGUE_TEST = "Could a colleague label traces using only this name and its definition?"
NONE_NAME = "None of the above"


def specificity_warnings(m: FailureMode) -> list[str]:
    if m.is_none_bucket:
        return []
    out = []
    words = set(re.findall(r"[a-z]+", m.name.lower()))
    vague = sorted(words & VAGUE_WORDS)
    if vague and len(words - VAGUE_WORDS) <= 1:
        out.append(f"Vague name ({', '.join(vague)}). Name the observable behaviour, e.g. 'date formatting error'.")
    elif vague:
        out.append(f"Name contains a vague word ({', '.join(vague)}). Make sure it is specific.")
    if len(m.name.split()) < 2:
        out.append("One-word names are rarely specific enough.")
    if not m.definition.strip():
        out.append("Missing definition.")
    if not m.counts_as.strip():
        out.append("Missing 'counts as' examples.")
    if not m.does_not_count_as.strip():
        out.append("Missing 'does not count as' boundary.")
    return out


def none_bucket(s: Session, project_id: int) -> FailureMode:
    m = s.exec(select(FailureMode).where(FailureMode.project_id == project_id, FailureMode.is_none_bucket == True)).first()  # noqa: E712
    if not m:
        m = FailureMode(project_id=project_id, name=NONE_NAME, is_none_bucket=True, rank=9999,
                        definition="Notes describing a problem that no current failure mode covers. Each one is a prompt to consider a new category.")
        s.add(m)
        s.commit()
        s.refresh(m)
    return m


def add_history(m: FailureMode, action: str, changes: Optional[dict] = None, by: str = "") -> None:
    hist = list(m.history or [])
    hist.append({"at": now().isoformat(), "action": action, "changes": changes or {}, "by": by, "version": m.version})
    m.history = hist


DEFINITION_FIELDS = ("definition", "counts_as", "does_not_count_as")


def apply_edit(s: Session, m: FailureMode, data: dict, by: str = "") -> FailureMode:
    changes = {}
    for k, v in data.items():
        if v is not None and getattr(m, k) != v:
            changes[k] = [getattr(m, k), v]
            setattr(m, k, v)
    if not changes:
        return m
    if any(k in DEFINITION_FIELDS for k in changes):
        m.version += 1
        # Criteria drift: existing labels in this category must be re-checked against the new definition.
        for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == m.id)).all():
            lab.needs_recheck = True
            s.add(lab)
    add_history(m, "edit", changes, by)
    s.add(m)
    s.commit()
    s.refresh(m)
    return m


def set_labels(s: Session, review: Review, mode_ids: list[int], source: str = "human") -> None:
    existing = {lab.failure_mode_id: lab for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == review.id)).all()}
    want = set(mode_ids)
    for fm in want - set(existing):
        s.add(ReviewLabel(review_id=review.id, trace_id=review.trace_id, failure_mode_id=fm, source=source))
    for fm, lab in existing.items():
        if fm not in want:
            s.delete(lab)
        elif lab.needs_recheck:
            lab.needs_recheck = False  # re-confirmed by the human
            s.add(lab)
    s.commit()


def descendants(modes: list[FailureMode]) -> dict[int, set[int]]:
    """mode id -> ids that roll up into it (itself plus children)."""
    out: dict[int, set[int]] = {m.id: {m.id} for m in modes}
    for m in modes:
        if m.parent_id and m.parent_id in out:
            out[m.parent_id].add(m.id)
    return out


def count_table(s: Session, project_id: int, facet: Optional[str] = None, batch_id: Optional[int] = None) -> dict:
    from ..models import BatchTrace

    modes = s.exec(select(FailureMode).where(FailureMode.project_id == project_id, FailureMode.archived == False)).all()  # noqa: E712
    reviews = s.exec(select(Review).where(Review.project_id == project_id, Review.verdict.is_not(None))).all()
    if batch_id:
        ids = set(s.exec(select(BatchTrace.trace_id).where(BatchTrace.batch_id == batch_id)).all())
        reviews = [r for r in reviews if r.trace_id in ids]
    rev_ids = {r.id for r in reviews}
    traces = {t.id: t for t in s.exec(select(Trace).where(Trace.id.in_([r.trace_id for r in reviews]))).all()} if reviews else {}
    labels = [lab for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id.in_(rev_ids))).all()] if rev_ids else []

    def fval(tid: int) -> str:
        t = traces.get(tid)
        if not t or not facet:
            return "all"
        if facet == "channel":
            return t.channel
        if facet == "synthetic":
            return str(t.synthetic).lower()
        v = t.meta.get(facet)
        return "(none)" if v is None else str(v)

    n_reviewed = len(reviews)
    failing = {r.trace_id for r in reviews if r.verdict == "fail"}
    by_facet_reviewed: dict[str, int] = defaultdict(int)
    by_facet_failing: dict[str, int] = defaultdict(int)
    for r in reviews:
        by_facet_reviewed[fval(r.trace_id)] += 1
        if r.verdict == "fail":
            by_facet_failing[fval(r.trace_id)] += 1
    roll = descendants(modes)
    traces_by_mode: dict[int, set[int]] = defaultdict(set)
    for lab in labels:
        traces_by_mode[lab.failure_mode_id].add(lab.trace_id)
    rows = []
    for m in sorted(modes, key=lambda x: (x.rank, x.id)):
        tids: set[int] = set()
        for mid in roll.get(m.id, {m.id}):
            tids |= traces_by_mode.get(mid, set())
        cells: dict[str, int] = defaultdict(int)
        for tid in tids:
            cells[fval(tid)] += 1
        rows.append({
            "id": m.id, "name": m.name, "parent_id": m.parent_id, "is_none_bucket": m.is_none_bucket,
            "severity": m.severity, "impact_note": m.impact_note, "decision": m.decision, "rank": m.rank,
            "count": len(tids),
            "share_reviewed": len(tids) / n_reviewed if n_reviewed else None,
            "share_failing": len(tids & failing) / len(failing) if failing else None,
            "by_facet": dict(cells),
        })
    top = sorted([r for r in rows if not r["parent_id"] and not r["is_none_bucket"]], key=lambda r: -r["count"])
    total_instances = sum(r["count"] for r in top)
    top3 = sum(r["count"] for r in top[:3])
    facet_values = sorted(by_facet_reviewed, key=lambda v: -by_facet_reviewed[v])
    return {
        "rows": rows, "n_reviewed": n_reviewed, "n_failing": len(failing),
        "facet": facet, "facet_values": facet_values,
        "facet_reviewed": dict(by_facet_reviewed), "facet_failing": dict(by_facet_failing),
        "top3_share": (top3 / total_instances) if total_instances else None,
        "top3_names": [r["name"] for r in top[:3]],
        "n_label_instances": total_instances,
    }
