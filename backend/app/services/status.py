"""Workflow stepper: status of each of the ten stages and the single next-best action."""
from __future__ import annotations

from sqlmodel import Session, func, select

from ..models import (
    AssignmentSuggestion, Batch, Evaluator, EvalRun, FailureMode, GroundTruth, Project, Review, ReviewLabel, Trace,
)

STAGES = [
    ("setup", "Set up the project", "Describe the product, channels and what you know that the model doesn't."),
    ("traces", "Get traces", "Import traces from your logs and build a review batch."),
    ("review", "Review traces", "Read each trace, mark pass or fail, write what you see.", "Also called open coding."),
    ("group", "Group failures", "Turn your notes into a short list of specific failure modes.", "Also called axial coding."),
    ("count", "Count and prioritise", "See which failures happen most and decide which matter most."),
    ("decide", "Decide what each failure needs", "Fix it now, write a code check, build an LLM judge, or park it."),
    ("build", "Build evaluators", "Write code checks and judge prompts for the failures you chose."),
    ("validate", "Validate judges", "Measure each judge against your own labels before trusting it."),
    ("run", "Run and measure", "Run the suite on new traces and compare versions."),
    ("export", "Export and operate", "Export the suite for CI and production monitoring."),
]


def reviewed_count(s: Session, project_id: int) -> int:
    return s.exec(select(func.count()).select_from(Review).where(Review.project_id == project_id, Review.verdict.is_not(None))).one()


def ai_state(s: Session, p: Project) -> dict:
    n = reviewed_count(s, p.id)
    thr = int(p.settings.get("ai_unlock_threshold", 30))
    enabled = bool(p.settings.get("ai_assist_enabled", True))
    return {"enabled": enabled, "reviewed": n, "threshold": thr, "unlocked": enabled and n >= thr,
            "reason": None if enabled and n >= thr else ("AI assist is switched off in settings." if not enabled
                                                         else f"Unlocks after {thr} traces reviewed by hand ({n} so far).")}


def project_status(s: Session, p: Project) -> dict:
    pid = p.id
    n_traces = s.exec(select(func.count()).select_from(Trace).where(Trace.project_id == pid)).one()
    n_batches = s.exec(select(func.count()).select_from(Batch).where(Batch.project_id == pid)).one()
    reviews = s.exec(select(Review).where(Review.project_id == pid)).all()
    saved = [r for r in reviews if r.verdict]
    n_fail = sum(1 for r in saved if r.verdict == "fail")
    modes = [m for m in s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.archived == False)).all()  # noqa: E712
             if not m.is_none_bucket]
    top_modes = [m for m in modes if m.parent_id is None]
    labels = s.exec(select(ReviewLabel).join(Review, ReviewLabel.review_id == Review.id).where(Review.project_id == pid)).all()
    labelled_reviews = {lab.review_id for lab in labels}
    none_ids = {m.id for m in s.exec(select(FailureMode).where(FailureMode.project_id == pid, FailureMode.is_none_bucket == True)).all()}  # noqa: E712
    in_none = {lab.review_id for lab in labels if lab.failure_mode_id in none_ids}
    pending_sugg = s.exec(select(func.count()).select_from(AssignmentSuggestion).where(
        AssignmentSuggestion.project_id == pid, AssignmentSuggestion.status == "pending")).one()
    unlabelled_fails = [r for r in saved if r.verdict == "fail" and r.id not in labelled_reviews]
    evals = s.exec(select(Evaluator).where(Evaluator.project_id == pid, Evaluator.status != "retired")).all()
    judges = [e for e in evals if e.type == "judge"]
    checks = [e for e in evals if e.type == "code"]
    batch_runs = s.exec(select(func.count()).select_from(EvalRun).where(EvalRun.project_id == pid, EvalRun.kind == "batch", EvalRun.status == "done")).one()
    n_gt = s.exec(select(func.count()).select_from(GroundTruth).join(FailureMode).where(FailureMode.project_id == pid)).one()

    st: dict[str, dict] = {}

    def put(key, status, unlock, next_):
        st[key] = {"status": status, "unlock": unlock, "next": next_}

    setup_ok = bool(p.name and p.description.strip() and p.reviewer_name.strip() and p.channels)
    missing = [w for w, ok in (("a description", p.description.strip()), ("your reviewer name", p.reviewer_name.strip()),
                               ("at least one channel", p.channels)) if not ok]
    put("setup", "done" if setup_ok else "in_progress", "Always open",
        "Setup complete — edit any time." if setup_ok else f"Add {', '.join(missing)}.")
    put("traces", "done" if n_batches else ("in_progress" if n_traces else "ready"), "Always open",
        "Import more traces or build another batch." if n_batches else ("Build a review batch of about 100 traces." if n_traces else "Import a file of traces (or load the demo traces)."))

    sat = saturation(s, pid, int(p.settings.get("saturation_window", 20)))
    if not n_batches:
        put("review", "locked", "Unlocks when a review batch exists.", "Build a batch first.")
    elif not saved:
        put("review", "ready", "", "Open the first trace and start reading.")
    else:
        done = sat["suggest_stop"]
        put("review", "done" if done else "in_progress", "",
            "Saturation reached: new kinds of problem have stopped appearing. Move on to grouping." if done
            else f"{len(saved)} reviewed. Keep going until new kinds of problem stop appearing (usually ~100).")

    if n_fail < 5:
        put("group", "locked", "Unlocks after at least 5 traces are marked Fail with notes.", "Review more traces first.")
    elif not top_modes:
        put("group", "ready", "", "Read your notes and draft failure categories (or ask AI to propose some).")
    else:
        todo = len(unlabelled_fails) + pending_sugg + len(in_none)
        put("group", "done" if todo == 0 else "in_progress", "",
            "Every failing note is assigned." if todo == 0 else
            f"{len(unlabelled_fails)} failing notes unassigned, {pending_sugg} suggestions to confirm, {len(in_none)} in 'None of the above'.")

    if not labels:
        put("count", "locked", "Unlocks once notes are assigned to failure modes.", "Assign notes to failure modes first.")
    else:
        unsev = [m for m in top_modes if not m.severity]
        put("count", "done" if not unsev else "in_progress", "",
            "Severity set for every failure mode." if not unsev else f"Set severity for {len(unsev)} failure mode(s) and order the list.")

    if st["count"]["status"] == "locked":
        put("decide", "locked", "Unlocks after counting.", "Count failures first.")
    else:
        undecided = [m for m in top_modes if not m.decision]
        put("decide", "done" if not undecided else ("in_progress" if len(undecided) < len(top_modes) else "ready"), "",
            "Every failure mode has a decision." if not undecided else f"Decide what {len(undecided)} failure mode(s) need.")

    wants_eval = [m for m in top_modes if m.decision in ("code_check", "llm_judge")]
    if not wants_eval:
        put("build", "locked", "Unlocks when a failure is marked 'Code check' or 'LLM judge'.", "Mark at least one failure for an evaluator.")
    else:
        have = {e.failure_mode_id for e in evals}
        missing_e = [m for m in wants_eval if m.id not in have]
        inactive_checks = [e for e in checks if e.status == "draft"]
        put("build", "done" if not missing_e and not inactive_checks else ("in_progress" if evals else "ready"), "",
            "Evaluators exist for every chosen failure." if not missing_e and not inactive_checks
            else (f"Build evaluators for: {', '.join(m.name for m in missing_e)}." if missing_e else "Activate your draft code checks."))

    if not judges:
        put("validate", "locked", "Unlocks when an LLM judge exists.", "Build an LLM judge first.")
    else:
        unval = [j for j in judges if j.status != "validated"]
        put("validate", "done" if not unval else ("in_progress" if n_gt else "ready"), "",
            "All judges validated." if not unval else f"Label traces and validate: {', '.join(j.name for j in unval)}.")

    active = [e for e in evals if e.status in ("active", "validated")]
    if not active:
        put("run", "locked", "Unlocks when an evaluator is active or validated.", "Activate a check or validate a judge.")
    else:
        put("run", "done" if batch_runs else "ready", "", "Run the suite on a fresh batch and compare." if batch_runs else "Run the active suite on a batch of traces.")

    if not batch_runs:
        put("export", "locked", "Unlocks after the suite has run on a batch.", "Run the suite first.")
    else:
        exported = bool(p.settings.get("last_export_at"))
        put("export", "done" if exported else "ready", "", "Re-export after changes." if exported else "Export the bundle for CI and monitoring.")

    stages = [{"key": k, "title": t, "summary": d, "term": (x[0] if x else None), **st[k]} for k, t, d, *x in STAGES]
    nxt = next((x for x in stages if x["status"] in ("ready", "in_progress")), None)
    return {
        "stages": stages,
        "next": nxt,
        "counts": {"traces": n_traces, "batches": n_batches, "reviewed": len(saved), "failed": n_fail,
                   "failure_modes": len(top_modes), "evaluators": len(evals), "ground_truth": n_gt},
        "ai": ai_state(s, p),
        "saturation": sat,
    }


def saturation(s: Session, project_id: int, window: int = 20) -> dict:
    """How many NEW kinds of problem appeared in the last `window` reviewed traces.

    Before a taxonomy exists, "kind" is approximated by the reviewer's own words: a failing note counts
    as new if it shares no distinctive keyword with any earlier failing note. Once notes are assigned to
    failure modes, a trace is new if it introduced a failure mode not seen earlier.
    """
    reviews = s.exec(select(Review).where(Review.project_id == project_id, Review.verdict.is_not(None))
                     .order_by(Review.reviewed_at, Review.id)).all()
    labels = s.exec(select(ReviewLabel).join(Review, ReviewLabel.review_id == Review.id).where(Review.project_id == project_id)).all()
    by_review: dict[int, set[int]] = {}
    for lab in labels:
        by_review.setdefault(lab.review_id, set()).add(lab.failure_mode_id)
    seen_modes: set[int] = set()
    seen_terms: set[str] = set()
    flags: list[bool] = []
    for r in reviews:
        new = False
        if r.id in by_review:
            if by_review[r.id] - seen_modes:
                new = True
            seen_modes |= by_review[r.id]
        elif r.verdict == "fail":
            terms = keywords(r.note)
            if terms and not (terms & seen_terms):
                new = True
            seen_terms |= terms
        flags.append(new)
    last = flags[-window:]
    n_new = sum(last)
    return {
        "window": window, "reviewed": len(flags), "new_in_window": n_new,
        "suggest_stop": len(flags) >= window and n_new == 0,
        "series": [int(x) for x in flags],
    }


_STOP = set("""a an the and or but if then than to of in on at for with without from by is are was were be been being it its this that
these those there their they them he she you your i me my we our us not no yes did does do doesnt didnt dont isnt wasnt cant
can could should would will just also only very too so as into about over under after before again still even when what which who
whom how why all any each some more most other such own same user users assistant bot agent model trace says said say asked asks
ask told tell gave give got get gets one two out up down off then said response reply replied message messages wrong bad good
fine ok okay instead really should've like seems seem though""".split())


def keywords(note: str) -> set[str]:
    import re

    words = re.findall(r"[a-z][a-z'-]{3,}", (note or "").lower())
    return {w.rstrip("s") for w in words if w not in _STOP}
