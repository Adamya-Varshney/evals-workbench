"""All tables. JSON columns hold lists/dicts; `history` columns hold append-only edit logs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


def JSONField(default: Any = None):  # noqa: N802
    factory = (lambda: list(default)) if isinstance(default, list) else (lambda: dict(default or {}))
    return Field(default_factory=factory, sa_column=Column(JSON))


def TextField(default: str = ""):  # noqa: N802
    return Field(default=default, sa_column=Column(Text))


DEFAULT_PROJECT_SETTINGS = {
    "ai_unlock_threshold": 30,
    "ai_assist_enabled": True,
    "review_nudge_seconds": 120,
    "saturation_window": 20,
}


# ---------- Stage 1: project ----------
class Project(SQLModel, table=True):
    __tablename__ = "projects"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = TextField()
    channels: list = JSONField([])  # [{name, render_rule}]
    business_facts: str = TextField()
    reviewer_name: str = ""
    settings: dict = JSONField(DEFAULT_PROJECT_SETTINGS)
    is_demo: bool = False
    review_round: int = 1  # bumped when a new round of review starts after a taxonomy exists
    created_at: datetime = Field(default_factory=now)


class PromptVersion(SQLModel, table=True):
    __tablename__ = "prompt_versions"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    label: str
    body: str = TextField()
    created_at: datetime = Field(default_factory=now)


# ---------- Stage 2: traces ----------
class ImportJob(SQLModel, table=True):
    __tablename__ = "imports"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    filename: str = ""
    fmt: str = ""
    raw_text: str = TextField()  # staged file content until committed
    mapping: dict = JSONField({})
    redaction: dict = JSONField({})
    report: dict = JSONField({})
    tags: dict = JSONField({})  # e.g. {"synthetic": true}
    status: str = "staged"  # staged | committed
    created_at: datetime = Field(default_factory=now)


class Trace(SQLModel, table=True):
    __tablename__ = "traces"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    import_id: Optional[int] = Field(default=None, foreign_key="imports.id")
    external_id: str = ""
    raw: dict = JSONField({})
    channel: str = "chat"
    meta: dict = JSONField({})
    synthetic: bool = False
    synthetic_tuple: dict = JSONField({})
    prompt_version_id: Optional[int] = Field(default=None, foreign_key="prompt_versions.id")
    system_prompt: str = TextField()
    system_prompt_hash: str = ""
    content_hash: str = Field(default="", index=True)
    n_turns: int = 0
    n_tool_calls: int = 0
    n_chars: int = 0
    search_text: str = TextField()
    created_at: datetime = Field(default_factory=now)


class Event(SQLModel, table=True):
    __tablename__ = "events"
    id: Optional[int] = Field(default=None, primary_key=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    seq: int
    role: str  # system | user | assistant | tool_call | tool_result
    content: str = TextField()
    tool_name: str = ""
    tool_args: dict = JSONField({})
    tool_result: str = TextField()
    tool_call_id: str = ""


class Batch(SQLModel, table=True):
    __tablename__ = "batches"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    name: str
    method: str = "random"
    params: dict = JSONField({})
    created_at: datetime = Field(default_factory=now)


class BatchTrace(SQLModel, table=True):
    __tablename__ = "batch_traces"
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: int = Field(foreign_key="batches.id", index=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    position: int = 0
    reason: str = "random"  # random | stratified | outlier | negative_feedback | evaluator_flag


# ---------- Stage 3: review ----------
class Review(SQLModel, table=True):
    __tablename__ = "reviews"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    batch_id: Optional[int] = Field(default=None, foreign_key="batches.id")
    verdict: Optional[str] = None  # pass | fail | None (deferred / unsaved)
    note: str = TextField()
    first_failure_event_id: Optional[int] = None
    deferred: bool = False
    reviewer: str = ""
    seconds_spent: float = 0
    round: int = 1
    history: list = JSONField([])
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


# ---------- Stage 4: taxonomy ----------
class FailureMode(SQLModel, table=True):
    __tablename__ = "failure_modes"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    parent_id: Optional[int] = Field(default=None, foreign_key="failure_modes.id")
    name: str
    definition: str = TextField()
    counts_as: str = TextField()
    does_not_count_as: str = TextField()
    severity: str = ""  # low | high | catastrophic
    impact_note: str = ""
    decision: str = ""  # fix_now | code_check | llm_judge | park
    decision_note: str = TextField()
    rank: int = 0
    is_none_bucket: bool = False
    archived: bool = False
    version: int = 1
    history: list = JSONField([])
    created_at: datetime = Field(default_factory=now)


class ReviewLabel(SQLModel, table=True):
    __tablename__ = "review_labels"
    id: Optional[int] = Field(default=None, primary_key=True)
    review_id: int = Field(foreign_key="reviews.id", index=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    failure_mode_id: int = Field(foreign_key="failure_modes.id", index=True)
    source: str = "human"  # human | ai_confirmed
    needs_recheck: bool = False
    created_at: datetime = Field(default_factory=now)


class AssignmentSuggestion(SQLModel, table=True):
    __tablename__ = "assignment_suggestions"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    review_id: int = Field(foreign_key="reviews.id", index=True)
    failure_mode_ids: list = JSONField([])
    rationale: str = TextField()
    status: str = "pending"  # pending | accepted | changed | rejected
    created_at: datetime = Field(default_factory=now)


class CategoryProposal(SQLModel, table=True):
    __tablename__ = "category_proposals"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    name: str
    definition: str = TextField()
    example_review_ids: list = JSONField([])
    status: str = "pending"  # pending | accepted | rejected
    created_at: datetime = Field(default_factory=now)


# ---------- Stage 6/7/8: evaluators ----------
class GroundTruth(SQLModel, table=True):
    __tablename__ = "ground_truth"
    id: Optional[int] = Field(default=None, primary_key=True)
    failure_mode_id: int = Field(foreign_key="failure_modes.id", index=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    label: bool  # True = failure present (positive class)
    critique: str = TextField()
    split: str = "dev"  # train | dev | test — fixed at first labelling
    source: str = "human"  # human | seeded_from_review
    history: list = JSONField([])
    created_at: datetime = Field(default_factory=now)


class Evaluator(SQLModel, table=True):
    __tablename__ = "evaluators"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    failure_mode_id: Optional[int] = Field(default=None, foreign_key="failure_modes.id")
    type: str  # code | judge
    name: str
    slug: str
    status: str = "draft"  # draft | active | validated | retired
    active_version_id: Optional[int] = None
    owner: str = ""
    where_to_run: str = ""
    threshold: float = 0.80
    target: float = 0.90
    created_at: datetime = Field(default_factory=now)


class EvaluatorVersion(SQLModel, table=True):
    __tablename__ = "evaluator_versions"
    id: Optional[int] = Field(default=None, primary_key=True)
    evaluator_id: int = Field(foreign_key="evaluators.id", index=True)
    version: int = 1
    definition: dict = JSONField({})  # code: {rules|python}; judge: {failure_when, not_failure_when, ...}
    context_scope: list = JSONField([])
    model: str = ""
    few_shot_ids: list = JSONField([])  # ground_truth ids (train split only)
    note: str = TextField()
    approved: bool = False
    created_at: datetime = Field(default_factory=now)


class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    kind: str  # check_preview | dev | final | batch
    evaluator_id: Optional[int] = None
    evaluator_version_id: Optional[int] = None
    batch_id: Optional[int] = None
    evaluator_ids: list = JSONField([])
    status: str = "queued"  # queued | running | done | failed
    progress: int = 0
    total: int = 0
    cost_estimate: float = 0
    cost_actual: float = 0
    metrics: dict = JSONField({})
    error: str = TextField()
    created_at: datetime = Field(default_factory=now)
    finished_at: Optional[datetime] = None


class EvalResult(SQLModel, table=True):
    __tablename__ = "eval_results"
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="eval_runs.id", index=True)
    evaluator_id: int = Field(index=True)
    evaluator_version_id: int = Field(index=True)
    trace_id: int = Field(foreign_key="traces.id", index=True)
    trace_hash: str = ""
    failure: Optional[bool] = None
    critique: str = TextField()
    cached: bool = False
    error: str = TextField()
    created_at: datetime = Field(default_factory=now)


class Fix(SQLModel, table=True):
    __tablename__ = "fixes"
    id: Optional[int] = Field(default=None, primary_key=True)
    failure_mode_id: int = Field(foreign_key="failure_modes.id", index=True)
    description: str = TextField()
    prompt_version_id: Optional[int] = None
    before_batch_id: Optional[int] = None
    after_batch_id: Optional[int] = None
    created_at: datetime = Field(default_factory=now)


class Experiment(SQLModel, table=True):
    __tablename__ = "experiments"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    hypothesis: str = TextField()
    change: str = TextField()
    result: str = TextField()
    batch_a_id: Optional[int] = None
    batch_b_id: Optional[int] = None
    snapshot: dict = JSONField({})
    created_at: datetime = Field(default_factory=now)


# ---------- Synthetic inputs ----------
class SyntheticDimension(SQLModel, table=True):
    __tablename__ = "synthetic_dimensions"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    name: str
    values: list = JSONField([])
    position: int = 0


class SyntheticTuple(SQLModel, table=True):
    __tablename__ = "synthetic_tuples"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="projects.id", index=True)
    values: dict = JSONField({})
    source: str = "human"  # human | ai
    status: str = "accepted"  # pending | accepted | rejected
    user_message: str = TextField()
    created_at: datetime = Field(default_factory=now)


# ---------- LLM plumbing ----------
class LLMCall(SQLModel, table=True):
    __tablename__ = "llm_calls"
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: Optional[int] = Field(default=None, index=True)
    job: str
    model: str
    mode: str  # live | mock
    request: dict = JSONField({})
    response: str = TextField()
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0
    latency_ms: int = 0
    error: str = TextField()
    created_at: datetime = Field(default_factory=now)


class PromptTemplate(SQLModel, table=True):
    __tablename__ = "prompt_templates"
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    title: str
    body: str = TextField()
    default_body: str = TextField()
    updated_at: datetime = Field(default_factory=now)
