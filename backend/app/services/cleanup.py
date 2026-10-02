from __future__ import annotations

from sqlalchemy import delete
from sqlmodel import Session, select

from .. import models as M


def delete_project_cascade(s: Session, p: M.Project) -> None:
    pid = p.id
    trace_ids = list(s.exec(select(M.Trace.id).where(M.Trace.project_id == pid)).all())
    fm_ids = list(s.exec(select(M.FailureMode.id).where(M.FailureMode.project_id == pid)).all())
    ev_ids = list(s.exec(select(M.Evaluator.id).where(M.Evaluator.project_id == pid)).all())
    run_ids = list(s.exec(select(M.EvalRun.id).where(M.EvalRun.project_id == pid)).all())
    batch_ids = list(s.exec(select(M.Batch.id).where(M.Batch.project_id == pid)).all())
    review_ids = list(s.exec(select(M.Review.id).where(M.Review.project_id == pid)).all())
    stmts = [
        delete(M.EvalResult).where(M.EvalResult.run_id.in_(run_ids)),
        delete(M.EvalRun).where(M.EvalRun.project_id == pid),
        delete(M.EvaluatorVersion).where(M.EvaluatorVersion.evaluator_id.in_(ev_ids)),
        delete(M.Evaluator).where(M.Evaluator.project_id == pid),
        delete(M.GroundTruth).where(M.GroundTruth.failure_mode_id.in_(fm_ids)),
        delete(M.Fix).where(M.Fix.failure_mode_id.in_(fm_ids)),
        delete(M.ReviewLabel).where(M.ReviewLabel.review_id.in_(review_ids)),
        delete(M.AssignmentSuggestion).where(M.AssignmentSuggestion.project_id == pid),
        delete(M.CategoryProposal).where(M.CategoryProposal.project_id == pid),
        delete(M.FailureMode).where(M.FailureMode.project_id == pid, M.FailureMode.parent_id.is_not(None)),
        delete(M.FailureMode).where(M.FailureMode.project_id == pid),
        delete(M.Review).where(M.Review.project_id == pid),
        delete(M.BatchTrace).where(M.BatchTrace.batch_id.in_(batch_ids)),
        delete(M.Batch).where(M.Batch.project_id == pid),
        delete(M.Event).where(M.Event.trace_id.in_(trace_ids)),
        delete(M.Trace).where(M.Trace.project_id == pid),
        delete(M.ImportJob).where(M.ImportJob.project_id == pid),
        delete(M.PromptVersion).where(M.PromptVersion.project_id == pid),
        delete(M.Experiment).where(M.Experiment.project_id == pid),
        delete(M.SyntheticTuple).where(M.SyntheticTuple.project_id == pid),
        delete(M.SyntheticDimension).where(M.SyntheticDimension.project_id == pid),
        delete(M.LLMCall).where(M.LLMCall.project_id == pid),
    ]
    for st in stmts:
        s.exec(st)
    s.delete(p)
    s.commit()
