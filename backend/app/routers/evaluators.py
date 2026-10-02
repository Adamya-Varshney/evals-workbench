"""Stages 6–8: decide, fix log, build evaluators (code checks + LLM judges), validate judges."""
from __future__ import annotations

import re
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, func, select

from .. import checks, stats
from ..config import settings
from ..db import get_session
from ..llm.client import LLMError, call_structured
from ..llm.templates import get_template, render
from ..models import (
    Batch, BatchTrace, EvalResult, EvalRun, Evaluator, EvaluatorVersion, FailureMode, Fix, GroundTruth, LLMCall, PromptVersion,
    Review, ReviewLabel, Trace, now,
)
from ..services import evals as E
from ..services.gate import require_ai
from ..services.taxonomy import descendants
from ..services.traceview import trace_view
from ..splits import assign_split
from .projects import get_project

router = APIRouter(prefix="/api/projects/{pid}", tags=["evaluators"])

SUITE_GUIDE = {"code": 3, "judge": 2}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:48] or "evaluator"


def _ev(s: Session, pid: int, eid: int) -> Evaluator:
    ev = s.get(Evaluator, eid)
    if not ev or ev.project_id != pid:
        raise HTTPException(404, "Evaluator not found")
    return ev


def _fm(s: Session, pid: int, fid: int) -> FailureMode:
    m = s.get(FailureMode, fid)
    if not m or m.project_id != pid:
        raise HTTPException(404, "Failure mode not found")
    return m


# ================================================================== stage 6: decisions + fix log
@router.get("/decide")
def decide_board(pid: int, s: Session = Depends(get_session)):
    from ..services.taxonomy import count_table

    c = count_table(s, pid)
    rows = {r["id"]: r for r in c["rows"]}
    modes = s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.archived == False,  # noqa: E712
                                             FailureMode.parent_id == None, FailureMode.is_none_bucket == False)  # noqa: E711,E712
                   .order_by(FailureMode.rank, FailureMode.id)).all()
    evs = s.exec(select(Evaluator).where(Evaluator.project_id == pid, Evaluator.status != "retired")).all()
    n_code = sum(1 for e in evs if e.type == "code")
    n_judge = sum(1 for e in evs if e.type == "judge")
    planned = Counter(m.decision for m in modes)
    warnings = []
    if planned["code_check"] + 0 > SUITE_GUIDE["code"] + 1 or n_code > SUITE_GUIDE["code"] + 1:
        warnings.append(f"{max(planned['code_check'], n_code)} code checks planned. A healthy suite is usually 2–3; make sure each one earns its maintenance.")
    if planned["llm_judge"] > SUITE_GUIDE["judge"] + 1 or n_judge > SUITE_GUIDE["judge"] + 1:
        warnings.append(f"{max(planned['llm_judge'], n_judge)} LLM judges planned. Each needs ~100+ human labels and ongoing upkeep; 1–2 is typical.")
    return {
        "modes": [{"id": m.id, "name": m.name, "definition": m.definition, "severity": m.severity, "impact_note": m.impact_note,
                   "decision": m.decision, "decision_note": m.decision_note, "count": rows.get(m.id, {}).get("count", 0),
                   "share_reviewed": rows.get(m.id, {}).get("share_reviewed"),
                   "evaluators": [{"id": e.id, "type": e.type, "name": e.name, "status": e.status} for e in evs if e.failure_mode_id == m.id]}
                  for m in modes],
        "n_reviewed": c["n_reviewed"], "suite": {"code": n_code, "judge": n_judge, "planned": dict(planned)}, "warnings": warnings,
    }


class FixIn(BaseModel):
    failure_mode_id: int
    description: str
    prompt_version_id: Optional[int] = None
    before_batch_id: Optional[int] = None
    after_batch_id: Optional[int] = None


def _rate(s: Session, pid: int, fm_id: int, trace_ids: set[int]) -> dict:
    truth = E.human_truth(s, pid, fm_id)
    vals = [truth[t] for t in trace_ids if t in truth]
    return stats.rate_with_ci(sum(vals), len(vals))


def _batch_traces(s: Session, bid: int) -> set[int]:
    return set(s.exec(select(BatchTrace.trace_id).where(BatchTrace.batch_id == bid)).all())


@router.get("/fixes")
def list_fixes(pid: int, s: Session = Depends(get_session)):
    out = []
    fixes = s.exec(select(Fix).join(FailureMode).where(FailureMode.project_id == pid).order_by(Fix.id.desc())).all()
    batches = s.exec(select(Batch).where(Batch.project_id == pid).order_by(Batch.id)).all()
    for f in fixes:
        m = s.get(FailureMode, f.failure_mode_id)
        pv = s.get(PromptVersion, f.prompt_version_id) if f.prompt_version_id else None
        before_ids = _batch_traces(s, f.before_batch_id) if f.before_batch_id else set().union(*[_batch_traces(s, b.id) for b in batches if b.created_at <= f.created_at]) if batches else set()
        after_b = f.after_batch_id or next((b.id for b in batches if b.created_at > f.created_at), None)
        after_ids = _batch_traces(s, after_b) if after_b else set()
        before, after = _rate(s, pid, f.failure_mode_id, before_ids), _rate(s, pid, f.failure_mode_id, after_ids)
        out.append({"id": f.id, "failure_mode_id": f.failure_mode_id, "failure_mode": m.name if m else "?", "description": f.description,
                    "prompt_version": pv.label if pv else None, "created_at": f.created_at, "before": before, "after": after,
                    "after_batch_id": after_b, "awaiting": after["n"] == 0})
    return out


@router.post("/fixes")
def add_fix(pid: int, body: FixIn, s: Session = Depends(get_session)):
    _fm(s, pid, body.failure_mode_id)
    f = Fix(**body.model_dump())
    s.add(f)
    s.commit()
    return {"id": f.id}


# ================================================================== evaluators
class EvaluatorIn(BaseModel):
    type: str
    failure_mode_id: Optional[int] = None
    name: Optional[str] = None


def evaluator_view(s: Session, ev: Evaluator) -> dict:
    v = latest_v = E.latest_version(s, ev)
    mode = s.get(FailureMode, ev.failure_mode_id) if ev.failure_mode_id else None
    last_dev = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "dev").order_by(EvalRun.id.desc())).first()
    last_final = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "final").order_by(EvalRun.id.desc())).first()
    last_prev = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "check_preview").order_by(EvalRun.id.desc())).first()
    return {"id": ev.id, "type": ev.type, "name": ev.name, "slug": ev.slug, "status": ev.status, "failure_mode_id": ev.failure_mode_id,
            "failure_mode": mode.name if mode else None, "owner": ev.owner, "where_to_run": ev.where_to_run, "threshold": ev.threshold,
            "target": ev.target, "active_version_id": ev.active_version_id, "latest_version": latest_v.version if latest_v else None,
            "latest_version_id": v.id if v else None,
            "last_dev": {"id": last_dev.id, "status": last_dev.status, "metrics": last_dev.metrics, "version_id": last_dev.evaluator_version_id} if last_dev else None,
            "last_final": {"id": last_final.id, "status": last_final.status, "metrics": last_final.metrics, "version_id": last_final.evaluator_version_id} if last_final else None,
            "last_preview": {"id": last_prev.id, "metrics": last_prev.metrics, "version_id": last_prev.evaluator_version_id} if last_prev else None}


@router.get("/evaluators")
def list_evaluators(pid: int, s: Session = Depends(get_session)):
    return [evaluator_view(s, e) for e in s.exec(select(Evaluator).where(Evaluator.project_id == pid).order_by(Evaluator.id)).all()]


@router.post("/evaluators")
def create_evaluator(pid: int, body: EvaluatorIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    if body.type not in ("code", "judge"):
        raise HTTPException(400, "type must be code or judge")
    mode = _fm(s, pid, body.failure_mode_id) if body.failure_mode_id else None
    if body.type == "judge":
        if not mode:
            raise HTTPException(400, "A judge must target exactly one failure mode")
        if s.exec(select(Evaluator).where(Evaluator.failure_mode_id == mode.id, Evaluator.type == "judge", Evaluator.status != "retired")).first():
            raise HTTPException(409, "This failure mode already has a judge. One judge per failure mode.")
    name = body.name or (f"{mode.name} — {'check' if body.type == 'code' else 'judge'}" if mode else "Code check")
    ev = Evaluator(project_id=pid, failure_mode_id=mode.id if mode else None, type=body.type, name=name, slug=_slug(name), owner=p.reviewer_name)
    s.add(ev)
    s.commit()
    s.refresh(ev)
    defn = {"kind": "rules", "rules": []} if body.type == "code" else {"failure_when": [], "not_failure_when": []}
    s.add(EvaluatorVersion(evaluator_id=ev.id, version=1, definition=defn, context_scope=[] if body.type == "code" else ["last_assistant"],
                           model=settings.model if body.type == "judge" else "", note="created"))
    s.commit()
    return evaluator_view(s, ev)


class EvaluatorPatch(BaseModel):
    name: Optional[str] = None
    owner: Optional[str] = None
    where_to_run: Optional[str] = None
    threshold: Optional[float] = None
    target: Optional[float] = None
    retire: Optional[bool] = None


@router.patch("/evaluators/{eid}")
def patch_evaluator(pid: int, eid: int, body: EvaluatorPatch, s: Session = Depends(get_session)):
    ev = _ev(s, pid, eid)
    data = body.model_dump(exclude_unset=True)
    if data.pop("retire", None):
        ev.status = "retired"
    for k, v in data.items():
        setattr(ev, k, v)
    if "name" in data:
        ev.slug = _slug(ev.name)
    s.add(ev)
    s.commit()
    return evaluator_view(s, ev)


@router.get("/evaluators/{eid}")
def get_evaluator(pid: int, eid: int, s: Session = Depends(get_session)):
    ev = _ev(s, pid, eid)
    versions = s.exec(select(EvaluatorVersion).where(EvaluatorVersion.evaluator_id == eid).order_by(EvaluatorVersion.version.desc())).all()
    runs = s.exec(select(EvalRun).where(EvalRun.evaluator_id == eid).order_by(EvalRun.id.desc())).all()
    vmap = {v.id: v.version for v in versions}
    table = {}
    for r in runs:
        if r.kind in ("dev", "final") and r.status == "done":
            row = table.setdefault(r.evaluator_version_id, {"version": vmap.get(r.evaluator_version_id), "dev": None, "test": None, "n_final_runs": 0})
            if r.kind == "dev" and row["dev"] is None:
                row["dev"] = r.metrics
            if r.kind == "final":
                row["n_final_runs"] += 1
                if row["test"] is None:
                    row["test"] = r.metrics
    return {**evaluator_view(s, ev), "versions": [v.model_dump() for v in versions],
            "runs": [{"id": r.id, "kind": r.kind, "status": r.status, "progress": r.progress, "total": r.total, "metrics": r.metrics,
                      "version": vmap.get(r.evaluator_version_id), "created_at": r.created_at, "error": r.error} for r in runs[:50]],
            "version_table": sorted(table.values(), key=lambda x: -(x["version"] or 0))}


class VersionIn(BaseModel):
    definition: dict
    context_scope: Optional[list[str]] = None
    model: Optional[str] = None
    few_shot_ids: list[int] = []
    note: str = ""


@router.post("/evaluators/{eid}/versions")
def new_version(pid: int, eid: int, body: VersionIn, s: Session = Depends(get_session)):
    ev = _ev(s, pid, eid)
    prev = E.latest_version(s, ev)
    if ev.type == "code":
        errs = checks.validate_definition(body.definition)
        if errs:
            raise HTTPException(400, "; ".join(errs))
        scope: list[str] = []
    else:
        d = body.definition
        if not isinstance(d.get("failure_when"), list) or not [x for x in d["failure_when"] if x.strip()]:
            raise HTTPException(400, "List at least one concrete condition under 'The failure occurs when'")
        scope = body.context_scope if body.context_scope is not None else (prev.context_scope if prev else ["last_assistant"])
        bad = [c for c in scope if c not in E.CONTEXT_OPTIONS]
        if bad or not scope:
            raise HTTPException(400, f"context scope must be a non-empty subset of {E.CONTEXT_OPTIONS}")
        for gid in body.few_shot_ids:
            g = s.get(GroundTruth, gid)
            if not g or g.failure_mode_id != ev.failure_mode_id or g.split != "train":
                raise HTTPException(400, "Few-shot examples must come from this failure mode's train split")
    v = EvaluatorVersion(evaluator_id=ev.id, version=(prev.version + 1) if prev else 1, definition=body.definition, context_scope=scope,
                         model=(body.model or (prev.model if prev else settings.model)) if ev.type == "judge" else "",
                         few_shot_ids=body.few_shot_ids, note=body.note)
    s.add(v)
    if ev.type == "code" and ev.status == "active":
        ev.status = "draft"  # a changed check must be re-verified before it runs again
        s.add(ev)
    s.commit()
    s.refresh(v)
    return v


@router.post("/evaluators/{eid}/judge_prompt")
def preview_judge_prompt(pid: int, eid: int, body: VersionIn, s: Session = Depends(get_session)):
    """Shows exactly what the judge will receive for one sample trace."""
    p = get_project(s, pid)
    ev = _ev(s, pid, eid)
    mode = _fm(s, pid, ev.failure_mode_id)
    v = EvaluatorVersion(evaluator_id=ev.id, definition=body.definition, context_scope=body.context_scope or ["last_assistant"],
                         few_shot_ids=body.few_shot_ids)
    g = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == mode.id, GroundTruth.split == "dev")).first()
    t = s.get(Trace, g.trace_id) if g else s.exec(select(Trace).where(Trace.project_id == pid)).first()
    return {"prompt": E.build_judge_prompt(s, p, mode, v, trace_view(s, t)), "sample_trace": t.external_id, "schema": E.JUDGE_SCHEMA}


# ------------------------------------------------------------------ code checks: preview + activate
@router.post("/evaluators/{eid}/preview")
def preview_check(pid: int, eid: int, s: Session = Depends(get_session)):
    ev = _ev(s, pid, eid)
    if ev.type != "code":
        raise HTTPException(400, "Preview is for code checks; judges use dev runs")
    v = E.latest_version(s, ev)
    errs = checks.validate_definition(v.definition)
    if errs:
        raise HTTPException(400, "; ".join(errs))
    truth = E.human_truth(s, pid, ev.failure_mode_id) if ev.failure_mode_id else {}
    traces = s.exec(select(Trace).where(Trace.id.in_(list(truth)))).all() if truth else []
    res = E.check_results(s, v, traces)
    run = EvalRun(project_id=pid, kind="check_preview", evaluator_id=ev.id, evaluator_version_id=v.id, status="done", total=len(traces), progress=len(traces))
    s.add(run)
    s.commit()
    rows = []
    for t in traces:
        failed, why = res[t.id]
        s.add(EvalResult(run_id=run.id, evaluator_id=ev.id, evaluator_version_id=v.id, trace_id=t.id, trace_hash=t.content_hash, failure=failed, critique=why))
        h = truth.get(t.id)
        rows.append({"trace_id": t.id, "external_id": t.external_id, "channel": t.channel, "human_failure": h, "check_failure": failed, "reason": why,
                     "outcome": "correct fail" if h and failed else "correct pass" if (h is False and not failed) else "missed failure" if h else "false alarm"})
    m = stats.judge_metrics([r["human_failure"] for r in rows], [r["check_failure"] for r in rows])
    m["correct_fail"] = m["confusion"]["tp"]
    m["correct_pass"] = m["confusion"]["tn"]
    run.metrics = m
    s.add(run)
    s.commit()
    return {"run_id": run.id, "version": v.version, "metrics": m, "rows": sorted(rows, key=lambda r: ["missed failure", "false alarm", "correct fail", "correct pass"].index(r["outcome"])),
            "can_activate": m["correct_fail"] >= 1 and m["correct_pass"] >= 1}


@router.post("/evaluators/{eid}/activate")
def activate_check(pid: int, eid: int, s: Session = Depends(get_session)):
    ev = _ev(s, pid, eid)
    if ev.type != "code":
        raise HTTPException(400, "Judges become active by passing final validation")
    v = E.latest_version(s, ev)
    prev = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "check_preview", EvalRun.evaluator_version_id == v.id)
                  .order_by(EvalRun.id.desc())).first()
    if not prev or prev.metrics.get("correct_fail", 0) < 1 or prev.metrics.get("correct_pass", 0) < 1:
        raise HTTPException(409, "Run the check against your reviewed traces first. It must produce at least one correct fail and one correct pass.")
    ev.status, ev.active_version_id = "active", v.id
    s.add(ev)
    s.commit()
    return evaluator_view(s, ev)


# ------------------------------------------------------------------ AI drafting
RULE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["type"], "properties": {
    "type": {"type": "string", "enum": ["regex", "markdown", "tool_called", "tool_count_max", "tool_args_required", "length"]},
    "pattern": {"type": "string"}, "mode": {"type": "string", "enum": ["present", "absent"]}, "flags": {"type": "string"},
    "tool": {"type": "string"}, "expect": {"type": "string", "enum": ["called", "not_called"]}, "max": {"type": "integer"},
    "args": {"type": "array", "items": {"type": "string"}}, "min": {"type": "integer"},
    "scope": {"type": "object", "additionalProperties": False, "required": ["facet", "values"],
              "properties": {"facet": {"type": "string"}, "values": {"type": "array", "items": {"type": "string"}}}}}}
DRAFT_CHECK_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["explanation", "rules"],
                      "properties": {"explanation": {"type": "string"}, "rules": {"type": "array", "items": RULE_SCHEMA}}}
DRAFT_JUDGE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["failure_when", "not_failure_when"], "properties": {
    "failure_when": {"type": "array", "items": {"type": "string"}}, "not_failure_when": {"type": "array", "items": {"type": "string"}}}}


def _examples(s: Session, pid: int, fm_id: int, limit: int = 12) -> list[str]:
    modes = s.exec(select(FailureMode).where(FailureMode.project_id == pid)).all()
    ids = descendants(list(modes)).get(fm_id, {fm_id})
    rids = [lab.review_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id.in_(ids))).all()]
    return [r.note for r in s.exec(select(Review).where(Review.id.in_(rids))).all() if r.note.strip()][:limit] if rids else []


class DraftIn(BaseModel):
    failure_mode_id: int


@router.post("/evaluators/draft_check")
def draft_check(pid: int, body: DraftIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    require_ai(s, p)
    m = _fm(s, pid, body.failure_mode_id)
    ex = _examples(s, pid, m.id)
    from ..models import Event

    tools = sorted({n for n in s.exec(select(Event.tool_name).join(Trace, Event.trace_id == Trace.id)
                                      .where(Trace.project_id == pid, Event.role == "tool_call")).all() if n})
    prompt = render(get_template(s, "draft_code_check"), name=m.name, definition=m.definition, counts_as=m.counts_as,
                    does_not_count_as=m.does_not_count_as, examples="\n".join(f"- {x}" for x in ex) or "(none)")
    channels = ", ".join(c["name"] for c in p.channels) or "(unknown)"
    prompt += f"\n\nTools that appear in this product's traces: {', '.join(tools) or '(none)'}\nChannels: {channels}"
    try:
        out = call_structured("draft_code_check", prompt, DRAFT_CHECK_SCHEMA, project_id=pid,
                              mock_ctx={"name": m.name, "definition": m.definition, "examples": ex, "tools": tools})
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"definition": {"kind": "rules", "rules": out["data"]["rules"]}, "explanation": out["data"]["explanation"],
            "note": "AI draft — review every rule, then save it as a new version."}


@router.post("/evaluators/draft_judge")
def draft_judge(pid: int, body: DraftIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    require_ai(s, p)
    m = _fm(s, pid, body.failure_mode_id)
    ex = _examples(s, pid, m.id)
    gts = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == m.id, GroundTruth.split == "train")).all()
    ex += [g.critique for g in gts if g.critique.strip()][:8]
    prompt = render(get_template(s, "draft_judge"), product_name=p.name, product_description=p.description, business_facts=p.business_facts or "(none)",
                    name=m.name, definition=m.definition, counts_as=m.counts_as, does_not_count_as=m.does_not_count_as,
                    examples="\n".join(f"- {x}" for x in ex) or "(none)")
    try:
        out = call_structured("draft_judge", prompt, DRAFT_JUDGE_SCHEMA, project_id=pid,
                              mock_ctx={"name": m.name, "definition": m.definition, "counts_as": m.counts_as, "does_not_count_as": m.does_not_count_as})
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"definition": out["data"], "note": "AI draft — edit it, then save it as a new version. Nothing runs until you do."}


# ================================================================== ground truth (stage 8)
def _gt_view(s: Session, g: GroundTruth) -> dict:
    t = s.get(Trace, g.trace_id)
    return {"id": g.id, "trace_id": g.trace_id, "external_id": t.external_id if t else "", "channel": t.channel if t else "",
            "label": g.label, "critique": g.critique, "split": g.split, "source": g.source, "history_len": len(g.history or [])}


def _split_counts(s: Session, fm_id: int) -> dict:
    out = {sp: {"pos": 0, "neg": 0} for sp in ("train", "dev", "test")}
    for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fm_id)).all():
        out[g.split]["pos" if g.label else "neg"] += 1
    return out


def upsert_gt(s: Session, fm_id: int, trace_id: int, label: bool, critique: str, source: str, by: str = "") -> GroundTruth:
    g = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fm_id, GroundTruth.trace_id == trace_id)).first()
    if g is None:
        counts = {sp: 0 for sp in ("train", "dev", "test")}
        for x in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fm_id, GroundTruth.label == label)).all():
            counts[x.split] += 1
        g = GroundTruth(failure_mode_id=fm_id, trace_id=trace_id, label=label, critique=critique, source=source,
                        split=assign_split(trace_id, fm_id, label, counts))
    else:
        if g.label != label or g.critique != critique:
            g.history = list(g.history or []) + [{"at": now().isoformat(), "label": g.label, "critique": g.critique, "by": by, "action": "corrected"}]
        g.label, g.critique = label, critique  # split never changes
    s.add(g)
    s.commit()
    s.refresh(g)
    return g


@router.get("/ground_truth/{fid}")
def list_gt(pid: int, fid: int, s: Session = Depends(get_session)):
    _fm(s, pid, fid)
    rows = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fid).order_by(GroundTruth.id)).all()
    counts = _split_counts(s, fid)
    low = any(counts[sp]["pos"] < 30 or counts[sp]["neg"] < 30 for sp in ("dev", "test"))
    total = sum(c["pos"] + c["neg"] for c in counts.values())
    return {"rows": [_gt_view(s, g) for g in rows], "counts": counts, "total": total, "low_confidence": low, "target": [100, 200]}


@router.post("/ground_truth/{fid}/seed")
def seed_gt(pid: int, fid: int, s: Session = Depends(get_session)):
    """Seed ground truth from error analysis: each reviewed trace says whether this failure mode was present."""
    p = get_project(s, pid)
    _fm(s, pid, fid)
    truth = E.human_truth(s, pid, fid)
    reviews = {r.trace_id: r for r in s.exec(select(Review).where(Review.project_id == pid)).all()}
    have = {g.trace_id for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fid)).all()}
    n = 0
    for tid, present in truth.items():
        if tid in have:
            continue
        r = reviews.get(tid)
        crit = (r.note.strip() if r and r.note.strip() else ("Reviewed: passed." if r and r.verdict == "pass" else "Reviewed: failed for other reasons."))
        upsert_gt(s, fid, tid, present, crit, "seeded_from_review", p.reviewer_name)
        n += 1
    return {"seeded": n, **list_gt(pid, fid, s)}


@router.get("/ground_truth/{fid}/queue")
def gt_queue(pid: int, fid: int, limit: int = 30, s: Session = Depends(get_session)):
    """Unlabelled traces for this failure mode, most likely positives first (by similarity to known positives).
    Judge output is never included here."""
    _fm(s, pid, fid)
    have = {g.trace_id for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fid)).all()}
    pos_ids = [g.trace_id for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fid, GroundTruth.label == True)).all()]  # noqa: E712
    traces = [t for t in s.exec(select(Trace).where(Trace.project_id == pid)).all() if t.id not in have]
    terms = Counter()
    for t in s.exec(select(Trace).where(Trace.id.in_(pos_ids))).all() if pos_ids else []:
        terms.update(set(re.findall(r"[a-z]{5,}", t.search_text)))
    common = {w for w, c in terms.items() if c >= max(2, len(pos_ids) // 3)}

    def score(t: Trace) -> float:
        words = set(re.findall(r"[a-z]{5,}", t.search_text))
        return len(words & common) / (len(common) or 1)

    traces.sort(key=lambda t: (-score(t), t.id))
    return {"remaining": len(traces), "items": [{"trace_id": t.id, "external_id": t.external_id, "channel": t.channel} for t in traces[:limit]]}


class GTIn(BaseModel):
    label: bool
    critique: str = ""


@router.put("/ground_truth/{fid}/{tid}")
def put_gt(pid: int, fid: int, tid: int, body: GTIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    _fm(s, pid, fid)
    t = s.get(Trace, tid)
    if not t or t.project_id != pid:
        raise HTTPException(404)
    if body.label and not body.critique.strip():
        raise HTTPException(400, "Add a short critique saying what you saw")
    g = upsert_gt(s, fid, tid, body.label, body.critique, "human", p.reviewer_name)
    return _gt_view(s, g)


@router.get("/ground_truth/{fid}/{tid}/history")
def gt_history(pid: int, fid: int, tid: int, s: Session = Depends(get_session)):
    g = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == fid, GroundTruth.trace_id == tid)).first()
    return list(reversed(g.history or [])) if g else []


# ------------------------------------------------------------------ judge runs: dev + final
class RunIn(BaseModel):
    split: str = "dev"


@router.post("/evaluators/{eid}/run")
def run_judge_split(pid: int, eid: int, body: RunIn, s: Session = Depends(get_session)):
    p = get_project(s, pid)
    ev = _ev(s, pid, eid)
    if ev.type != "judge":
        raise HTTPException(400, "Only judges run on dev/test splits")
    if not settings.llm_mode == "mock":
        if not p.settings.get("ai_assist_enabled", True):
            raise HTTPException(403, "AI assist is switched off in settings.")
    if body.split not in ("dev", "test"):
        raise HTTPException(400, "split must be dev or test")
    v = E.latest_version(s, ev)
    if not (v.definition or {}).get("failure_when"):
        raise HTTPException(400, "Write the judge prompt first")
    gts = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == ev.failure_mode_id, GroundTruth.split == body.split)).all()
    if not gts or not any(g.label for g in gts) or all(g.label for g in gts):
        raise HTTPException(400, f"The {body.split} split needs at least one trace with the failure and one without. Label more traces first.")
    kind = "dev" if body.split == "dev" else "final"
    prior_finals = s.exec(select(func.count()).select_from(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "final")).one()
    traces = s.exec(select(Trace).where(Trace.id.in_([g.trace_id for g in gts]))).all()
    run = EvalRun(project_id=pid, kind=kind, evaluator_id=ev.id, evaluator_version_id=v.id, total=len(traces),
                  cost_estimate=E.estimate_cost(s, p, [ev], list(traces))["usd"])
    s.add(run)
    s.commit()
    s.refresh(run)
    started = now()

    # The job runs after this request's session is closed: hand it plain ids only.
    ev_id, v_id, t_ids = ev.id, v.id, [t.id for t in traces]

    def work(s2: Session, r: EvalRun):
        ev2, v2 = s2.get(Evaluator, ev_id), s2.get(EvaluatorVersion, v_id)
        ts = s2.exec(select(Trace).where(Trace.id.in_(t_ids))).all()
        E.execute(s2, r, [(ev2, v2, t) for t in ts])
        m = E.split_metrics(s2, r, ev2.failure_mode_id)
        if kind == "final":
            dev = s2.exec(select(EvalRun).where(EvalRun.evaluator_id == ev2.id, EvalRun.kind == "dev", EvalRun.evaluator_version_id == v2.id,
                                                EvalRun.status == "done").order_by(EvalRun.id.desc())).first()
            m["run_number"] = prior_finals + 1
            m["repeat_warning"] = prior_finals >= 2
            m["overfit_warning"] = False
            if dev and dev.metrics.get("tpr") is not None and m.get("tpr") is not None and m.get("tnr") is not None:
                gap = max((dev.metrics["tpr"] or 0) - m["tpr"], (dev.metrics.get("tnr") or 0) - m["tnr"])
                m["dev_gap"] = gap
                m["overfit_warning"] = gap > 0.10
            m["threshold"] = ev2.threshold
            m["passed"] = (m.get("tpr") or 0) >= ev2.threshold and (m.get("tnr") or 0) >= ev2.threshold and m["errors"] == 0
            if m["passed"]:
                ev2.status, ev2.active_version_id = "validated", v2.id
            elif ev2.status == "validated" and ev2.active_version_id == v2.id:
                ev2.status = "draft"
            s2.add(ev2)
        cost = s2.exec(select(func.coalesce(func.sum(LLMCall.cost_usd), 0)).where(LLMCall.project_id == pid, LLMCall.job == "run_judge",
                                                                                   LLMCall.created_at >= started)).one()
        r.metrics, r.cost_actual = m, float(cost or 0)
        s2.add(r)
        s2.commit()

    E.submit(run.id, work)
    return {"run_id": run.id}


@router.get("/runs/{rid}")
def get_run(pid: int, rid: int, s: Session = Depends(get_session)):
    r = s.get(EvalRun, rid)
    if not r or r.project_id != pid:
        raise HTTPException(404)
    out = {"id": r.id, "kind": r.kind, "status": r.status, "progress": r.progress, "total": r.total, "metrics": r.metrics,
           "evaluator_id": r.evaluator_id, "evaluator_version_id": r.evaluator_version_id, "batch_id": r.batch_id,
           "evaluator_ids": r.evaluator_ids, "cost_estimate": r.cost_estimate, "cost_actual": r.cost_actual, "error": r.error,
           "created_at": r.created_at, "finished_at": r.finished_at}
    if r.kind in ("dev", "final") and r.status == "done":
        ev = s.get(Evaluator, r.evaluator_id)
        gts = {g.trace_id: g for g in s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == ev.failure_mode_id)).all()}
        rows = []
        for res in E.run_rows(s, r):
            g = gts.get(res.trace_id)
            t = s.get(Trace, res.trace_id)
            if not g:
                continue
            outcome = "error" if res.failure is None else ("agree" if g.label == res.failure else ("missed failure" if g.label else "false alarm"))
            rows.append({"trace_id": t.id, "external_id": t.external_id, "channel": t.channel, "human_label": g.label, "human_critique": g.critique,
                         "judge_failure": res.failure, "judge_critique": res.critique, "error": res.error, "split": g.split, "outcome": outcome,
                         "gt_id": g.id})
        out["rows"] = sorted(rows, key=lambda x: ["missed failure", "false alarm", "error", "agree"].index(x["outcome"]))
    return out
