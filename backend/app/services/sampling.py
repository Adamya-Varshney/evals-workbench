"""Build review batches. Whatever the method, at least 20% of the batch is a plain random sample
so unknown failure types can still surface."""
from __future__ import annotations

import random
from collections import defaultdict

from sqlmodel import Session, select

from ..models import Batch, BatchTrace, EvalResult, EvalRun, Review, Trace

MIN_RANDOM_SHARE = 0.20
METHODS = ("random", "stratified", "outliers", "negative_feedback", "evaluator_flag")


def build_batch(s: Session, project_id: int, size: int = 100, method: str = "random", params: dict | None = None,
                name: str | None = None, seed: int | None = None) -> Batch:
    params = dict(params or {})
    if method not in METHODS:
        raise ValueError(f"unknown sampling method '{method}'")
    rng = random.Random(seed if seed is not None else random.randrange(1 << 30))
    q = select(Trace).where(Trace.project_id == project_id)
    if params.get("exclude_reviewed"):
        reviewed = set(s.exec(select(Review.trace_id).where(Review.project_id == project_id, Review.verdict.is_not(None))).all())
    else:
        reviewed = set()
    if params.get("only_import_id"):
        q = q.where(Trace.import_id == params["only_import_id"])
    pool = [t for t in s.exec(q).all() if t.id not in reviewed]
    size = max(1, min(size, len(pool)))
    n_random_min = int(round(size * MIN_RANDOM_SHARE)) if method != "random" else size
    targeted: list[tuple[Trace, str]] = []
    if method == "stratified":
        facet = params.get("facet", "channel")
        groups: dict[str, list[Trace]] = defaultdict(list)
        for t in pool:
            groups[str(facet_value(t, facet))].append(t)
        quota = size - n_random_min
        keys = sorted(groups)
        for g in groups.values():
            rng.shuffle(g)
        i = 0
        while len(targeted) < quota and any(groups[k] for k in keys):
            k = keys[i % len(keys)]
            if groups[k]:
                targeted.append((groups[k].pop(), "stratified"))
            i += 1
    elif method == "outliers":
        by = params.get("by", "n_turns")  # n_turns | n_tool_calls | n_chars
        ordered = sorted(pool, key=lambda t: getattr(t, by, 0), reverse=True)
        targeted = [(t, "outlier") for t in ordered[: size - n_random_min]]
    elif method == "negative_feedback":
        field = params.get("field", "user_feedback")
        neg = {str(v).lower() for v in params.get("values", ["thumbs_down", "negative", "-1", "0", "bad", "false"])}
        hits = [t for t in pool if str(t.meta.get(field, "")).lower() in neg]
        rng.shuffle(hits)
        targeted = [(t, "negative_feedback") for t in hits[: size - n_random_min]]
    elif method == "evaluator_flag":
        flagged = flagged_trace_ids(s, project_id, params.get("evaluator_ids"), params.get("run_id"))
        hits = [t for t in pool if t.id in flagged]
        rng.shuffle(hits)
        targeted = [(t, "evaluator_flag") for t in hits[: size - n_random_min]]
    chosen_ids = {t.id for t, _ in targeted}
    rest = [t for t in pool if t.id not in chosen_ids]
    rng.shuffle(rest)
    picks = targeted + [(t, "random") for t in rest[: size - len(targeted)]]
    rng.shuffle(picks)
    batch = Batch(project_id=project_id, name=name or f"{method.replace('_', ' ').title()} batch ({len(picks)})",
                  method=method, params={**params, "size": size})
    s.add(batch)
    s.flush()
    for pos, (t, reason) in enumerate(picks):
        s.add(BatchTrace(batch_id=batch.id, trace_id=t.id, position=pos, reason=reason))
    s.commit()
    s.refresh(batch)
    return batch


def facet_value(t: Trace, facet: str):
    if facet == "channel":
        return t.channel
    if facet == "synthetic":
        return t.synthetic
    return t.meta.get(facet, "(none)")


def flagged_trace_ids(s: Session, project_id: int, evaluator_ids: list[int] | None = None, run_id: int | None = None) -> set[int]:
    runs = [run_id] if run_id else s.exec(select(EvalRun.id).where(EvalRun.project_id == project_id, EvalRun.kind == "batch")).all()
    if not runs:
        return set()
    q = select(EvalResult.trace_id).where(EvalResult.run_id.in_(runs), EvalResult.failure == True)  # noqa: E712
    if evaluator_ids:
        q = q.where(EvalResult.evaluator_id.in_(evaluator_ids))
    return set(s.exec(q).all())
