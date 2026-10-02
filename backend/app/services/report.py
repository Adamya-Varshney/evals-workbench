"""Suite results on a batch: per-evaluator rates, corrected judge rates, pass-all, facet breakdown."""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlmodel import Session, select

from .. import stats
from ..models import EvalResult, EvalRun, Evaluator, GroundTruth, Trace


def test_pairs(s: Session, ev: Evaluator, version_id: int) -> Optional[tuple[list[bool], list[bool], int]]:
    """Human labels and judge verdicts on the test split from the latest final run of this version."""
    fr = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "final", EvalRun.status == "done",
                                      EvalRun.evaluator_version_id == version_id).order_by(EvalRun.id.desc())).first()
    if not fr:
        return None
    gt = {g.trace_id: g.label for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == ev.failure_mode_id)).all()}
    pairs = [(gt[r.trace_id], bool(r.failure)) for r in s.exec(select(EvalResult).where(EvalResult.run_id == fr.id)).all()
             if r.trace_id in gt and r.failure is not None]
    return [h for h, _ in pairs], [j for _, j in pairs], fr.id


def facet_of(t: Trace, facet: str) -> str:
    if facet == "channel":
        return t.channel
    v = t.meta.get(facet)
    return "(none)" if v is None else str(v)


def run_report(s: Session, run: EvalRun, facet: Optional[str] = None) -> dict:
    results = list(s.exec(select(EvalResult).where(EvalResult.run_id == run.id)).all())
    traces = {t.id: t for t in s.exec(select(Trace).where(Trace.id.in_({r.trace_id for r in results}))).all()} if results else {}
    by_ev: dict[int, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_ev[r.evaluator_id].append(r)
    evaluators = []
    for eid, rs in by_ev.items():
        ev = s.get(Evaluator, eid)
        valid = [r for r in rs if r.failure is not None]
        k = sum(1 for r in valid if r.failure)
        row = {"evaluator_id": eid, "name": ev.name, "type": ev.type, "status": ev.status, "version_id": rs[0].evaluator_version_id,
               "n": len(valid), "errors": len(rs) - len(valid), "cached": sum(1 for r in rs if r.cached),
               "raw": stats.rate_with_ci(k, len(valid)), "corrected": None, "corrected_note": None}
        if ev.type == "judge" and valid:
            tp = test_pairs(s, ev, rs[0].evaluator_version_id)
            if not tp:
                row["corrected_note"] = "No final validation for this judge version, so the rate cannot be corrected for judge error."
            else:
                human, judge, _ = tp
                try:
                    row["corrected"] = stats.corrected_rate_with_ci([bool(r.failure) for r in valid], human, judge, iterations=2000)
                except stats.NoBetterThanChance as e:
                    row["corrected_note"] = str(e)
        if facet:
            groups: dict[str, list[bool]] = defaultdict(list)
            for r in valid:
                groups[facet_of(traces[r.trace_id], facet)].append(bool(r.failure))
            row["by_facet"] = {g: stats.rate_with_ci(sum(v), len(v)) for g, v in groups.items()}
        evaluators.append(row)
    # pass-all: a trace passes only if it passes every evaluator in the run
    per_trace: dict[int, list[Optional[bool]]] = defaultdict(list)
    for r in results:
        per_trace[r.trace_id].append(r.failure)
    complete = {tid: v for tid, v in per_trace.items() if len(v) == len(by_ev) and all(x is not None for x in v)}
    passed = [tid for tid, v in complete.items() if not any(v)]
    pass_all = stats.rate_with_ci(len(passed), len(complete))
    pass_all_facet = None
    if facet:
        g: dict[str, list[bool]] = defaultdict(list)
        for tid, v in complete.items():
            g[facet_of(traces[tid], facet)].append(not any(v))
        pass_all_facet = {k: stats.rate_with_ci(sum(v), len(v)) for k, v in g.items()}
    return {"run_id": run.id, "batch_id": run.batch_id, "n_traces": len(per_trace), "evaluators": sorted(evaluators, key=lambda e: e["name"]),
            "pass_all": pass_all, "pass_all_by_facet": pass_all_facet, "facet": facet,
            "facet_values": sorted(pass_all_facet) if pass_all_facet else []}
