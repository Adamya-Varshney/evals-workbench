"""Evaluators: code checks and LLM judges, their runs, caching and metrics."""
from __future__ import annotations

import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from sqlmodel import Session, select

from .. import checks, stats
from ..config import price_for, settings
from ..db import get_engine
from ..llm.client import LLMError, call_structured
from ..llm.templates import get_template, render
from ..models import (
    EvalResult, EvalRun, Evaluator, EvaluatorVersion, FailureMode, GroundTruth, Project, Review, ReviewLabel, Trace, now,
)
from .taxonomy import descendants
from .traceview import trace_text, trace_view

CONTEXT_OPTIONS = ("last_assistant", "conversation", "tool_calls", "system_prompt", "business_facts")
JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["critique", "failure"],
    "properties": {"critique": {"type": "string"}, "failure": {"type": "boolean"}},
}


# ------------------------------------------------------------------ basics
def latest_version(s: Session, ev: Evaluator) -> Optional[EvaluatorVersion]:
    return s.exec(select(EvaluatorVersion).where(EvaluatorVersion.evaluator_id == ev.id).order_by(EvaluatorVersion.version.desc())).first()


def run_version(s: Session, ev: Evaluator) -> Optional[EvaluatorVersion]:
    """The version used when the suite runs: the approved one if any, else the latest."""
    if ev.active_version_id:
        v = s.get(EvaluatorVersion, ev.active_version_id)
        if v:
            return v
    return latest_version(s, ev)


def human_truth(s: Session, project_id: int, fm_id: int) -> dict[int, bool]:
    """From error analysis: reviewed trace -> failure mode (or a sub-mode) present?"""
    modes = s.exec(select(FailureMode).where(FailureMode.project_id == project_id)).all()
    ids = descendants(list(modes)).get(fm_id, {fm_id})
    reviewed = s.exec(select(Review).where(Review.project_id == project_id, Review.verdict.is_not(None))).all()
    pos = {lab.trace_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id.in_(ids))).all()}
    return {r.trace_id: r.trace_id in pos for r in reviewed}


def trace_dict(s: Session, t: Trace) -> dict:
    return trace_view(s, t)


# ------------------------------------------------------------------ judge prompt
def numbered(items: list[str]) -> str:
    items = [i for i in (items or []) if i.strip()]
    return "\n".join(f"{i + 1}. {x.strip()}" for i, x in enumerate(items)) or "(none listed)"


def build_judge_prompt(s: Session, p: Project, mode: FailureMode, v: EvaluatorVersion, view: Optional[dict], template: Optional[str] = None,
                       trace_placeholder: Optional[str] = None) -> str:
    scope = v.context_scope or ["last_assistant"]
    d = v.definition or {}
    shots = ""
    if v.few_shot_ids:
        exs = []
        for gid in v.few_shot_ids:
            g = s.get(GroundTruth, gid)
            if not g or g.split != "train":
                continue  # only the train split may appear in the prompt
            t = s.get(Trace, g.trace_id)
            exs.append(f"<example>\n<trace>\n{trace_text(trace_view(s, t), scope)[:2500]}\n</trace>\nCritique: {g.critique}\nFailure: {'true' if g.label else 'false'}\n</example>")
        if exs:
            shots = "\nExamples judged by the product owner:\n" + "\n".join(exs) + "\n"
    ttext = trace_placeholder if trace_placeholder is not None else trace_text(view, scope)
    if "business_facts" in scope and p.business_facts.strip():
        ttext = f"[business facts]\n{p.business_facts}\n\n" + ttext
    return render(template or get_template(s, "run_judge"), name=mode.name, failure_when=numbered(d.get("failure_when", [])),
                  not_failure_when=numbered(d.get("not_failure_when", [])), few_shot=shots, trace=ttext)


def judge_one(s: Session, p: Project, ev: Evaluator, v: EvaluatorVersion, t: Trace, mode: FailureMode) -> tuple[Optional[bool], str, bool, str]:
    """Returns (failure, critique, cached, error). Cached on (evaluator version, trace content hash)."""
    hit = s.exec(select(EvalResult).where(EvalResult.evaluator_version_id == v.id, EvalResult.trace_hash == t.content_hash,
                                          EvalResult.error == "", EvalResult.failure.is_not(None))).first()
    if hit:
        return hit.failure, hit.critique, True, ""
    view = trace_view(s, t)
    prompt = build_judge_prompt(s, p, mode, v, view)
    try:
        out = call_structured("run_judge", prompt, JUDGE_SCHEMA, project_id=p.id, model=v.model or None, max_tokens=4000,
                              mock_ctx={"mode": mode.name, "definition": v.definition, "trace": view})
        return bool(out["data"]["failure"]), out["data"]["critique"], False, ""
    except LLMError as e:
        return None, "", False, str(e)


def check_results(s: Session, v: EvaluatorVersion, traces: list[Trace]) -> dict[int, tuple[bool, str]]:
    dicts = [trace_dict(s, t) for t in traces]
    res = checks.run_definition(v.definition or {}, dicts)
    return {t.id: res.get(t.id, (True, "no result")) for t in traces}


# ------------------------------------------------------------------ cost
def estimate_cost(s: Session, p: Project, evaluators: list[Evaluator], traces: list[Trace]) -> dict:
    pin, pout = price_for(settings.model)
    calls = cached = 0
    in_tok = 0
    for ev in evaluators:
        if ev.type != "judge":
            continue
        v = run_version(s, ev)
        mode = s.get(FailureMode, ev.failure_mode_id)
        if not v or not mode:
            continue
        done = set(s.exec(select(EvalResult.trace_hash).where(EvalResult.evaluator_version_id == v.id, EvalResult.error == "")).all())
        sample = None
        for t in traces:
            if t.content_hash in done:
                cached += 1
                continue
            if sample is None:
                sample = len(build_judge_prompt(s, p, mode, v, trace_view(s, t))) // 4 + 50
            calls += 1
            in_tok += sample
    out_tok = calls * 250
    return {"llm_calls": calls, "cached": cached, "input_tokens": in_tok, "output_tokens": out_tok,
            "usd": round(in_tok / 1e6 * pin + out_tok / 1e6 * pout, 4), "model": settings.model, "mode": settings.llm_mode}


# ------------------------------------------------------------------ background jobs
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="evaljob")
_jobs_lock = threading.Lock()


def submit(run_id: int, fn: Callable[[Session, EvalRun], None], sync: bool = False) -> None:
    def work():
        with Session(get_engine()) as s:
            run = s.get(EvalRun, run_id)
            run.status = "running"
            s.add(run)
            s.commit()
            try:
                fn(s, run)
                run = s.get(EvalRun, run_id)
                run.status = "done"
            except Exception as e:  # noqa: BLE001
                run = s.get(EvalRun, run_id)
                run.status = "failed"
                run.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
            run.finished_at = now()
            s.add(run)
            s.commit()

    if sync or settings.llm_mode == "mock" and _is_test():
        work()
    else:
        _pool.submit(work)


def _is_test() -> bool:
    import sys

    return "pytest" in sys.modules


def execute(s: Session, run: EvalRun, items: list[tuple[Evaluator, EvaluatorVersion, Trace]]) -> None:
    """Run (evaluator, version, trace) items, writing EvalResults and progress. LLM calls run concurrently."""
    p = s.get(Project, run.project_id)
    run.total = len(items)
    s.add(run)
    s.commit()
    # code checks: batched per evaluator, synchronous and fast
    by_ev: dict[int, list[tuple[Evaluator, EvaluatorVersion, Trace]]] = {}
    for it in items:
        by_ev.setdefault(it[0].id, []).append(it)
    progress = 0
    cost = 0.0
    for ev_id, its in by_ev.items():
        ev, v = its[0][0], its[0][1]
        if ev.type == "code":
            res = check_results(s, v, [t for _, _, t in its])
            for _, _, t in its:
                failed, why = res[t.id]
                s.add(EvalResult(run_id=run.id, evaluator_id=ev.id, evaluator_version_id=v.id, trace_id=t.id, trace_hash=t.content_hash,
                                 failure=failed, critique=why))
            progress += len(its)
            run.progress = progress
            s.add(run)
            s.commit()
    # Worker threads get plain ids and use their own sessions; ORM objects never cross threads.
    judge_ids = [(ev.id, v.id, t.id, t.content_hash, ev.failure_mode_id) for ev, v, t in items if ev.type == "judge"]
    if judge_ids:
        pid = p.id

        def one(ids):
            ev_id, v_id, t_id, _, fm_id = ids
            with Session(get_engine()) as s2:
                return ids, judge_one(s2, s2.get(Project, pid), s2.get(Evaluator, ev_id), s2.get(EvaluatorVersion, v_id),
                                      s2.get(Trace, t_id), s2.get(FailureMode, fm_id))

        with ThreadPoolExecutor(max_workers=max(1, settings.llm_concurrency)) as ex:
            for (ev_id, v_id, t_id, t_hash, _), (failure, critique, cached, err) in ex.map(one, judge_ids):
                s.add(EvalResult(run_id=run.id, evaluator_id=ev_id, evaluator_version_id=v_id, trace_id=t_id, trace_hash=t_hash,
                                 failure=failure, critique=critique, cached=cached, error=err))
                progress += 1
                run.progress = progress
                s.add(run)
                s.commit()
    run.cost_actual = cost


# ------------------------------------------------------------------ metrics
def run_rows(s: Session, run: EvalRun) -> list[EvalResult]:
    return list(s.exec(select(EvalResult).where(EvalResult.run_id == run.id)).all())


def split_metrics(s: Session, run: EvalRun, fm_id: int) -> dict:
    """Judge vs ground truth on the run's traces (dev or test)."""
    gt = {g.trace_id: g for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fm_id)).all()}
    pairs = [(gt[r.trace_id].label, bool(r.failure)) for r in run_rows(s, run) if r.trace_id in gt and r.failure is not None]
    m = stats.judge_metrics([h for h, _ in pairs], [j for _, j in pairs])
    m["errors"] = sum(1 for r in run_rows(s, run) if r.error)
    return m
