"""Stage 10: export the suite as a zip that runs on its own (CI, monitoring)."""
from __future__ import annotations

import csv
import inspect
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from .. import checks
from ..models import (
    Evaluator, EvaluatorVersion, EvalRun, FailureMode, GroundTruth, Project, Review, ReviewLabel, Trace,
)
from . import evals as E
from .taxonomy import count_table, specificity_warnings
from .traceview import _short, trace_text, trace_view

OPERATING_GUIDANCE = """\
- **CI:** run the code checks and the golden set on every change. Use LLM judges sparingly there because of cost.
- **Production monitoring:** sample live traces regularly, run judges asynchronously, and investigate when the confidence interval for a failure rate crosses the agreed threshold.
- **New failures:** any new failure found in production gets added to the golden set.
- **Re-run error analysis** on 100 or more fresh traces after significant changes (new features, prompt or model changes), and review 10–20 traces weekly in between.
- **Re-check judges** against fresh human labels periodically. Retire evaluators that always pass.
- **Guardrails:** fast, objective code checks may also be used inline as guardrails. Judges are for measurement after the fact.
"""


def _trace_record(s: Session, t: Trace) -> dict:
    v = trace_view(s, t)
    return {"id": t.external_id, "channel": v["channel"], "meta": v["meta"], "system_prompt": v["system_prompt"],
            "events": [{k: e[k] for k in ("role", "content", "tool_name", "tool_args", "tool_result")} for e in v["events"]]}


def _pct(x):
    return "—" if x is None else f"{100 * x:.0f}%"


def build_bundle(s: Session, p: Project) -> tuple[bytes, str]:
    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
    root = f"evals_{_slug(p.name)}_{stamp}/"

    def w(name: str, data: str) -> None:
        z.writestr(root + name, data)

    modes = s.exec(select(FailureMode).where(FailureMode.project_id == p.id, FailureMode.archived == False)  # noqa: E712
                   .order_by(FailureMode.rank, FailureMode.id)).all()
    counts = count_table(s, p.id)
    crow = {r["id"]: r for r in counts["rows"]}
    evaluators = s.exec(select(Evaluator).where(Evaluator.project_id == p.id, Evaluator.status != "retired")).all()

    # ---- taxonomy + error analysis
    w("failure_taxonomy.json", json.dumps({"project": p.name, "exported": stamp, "n_reviewed": counts["n_reviewed"], "n_failing": counts["n_failing"],
                                           "failure_modes": [{"id": m.id, "name": m.name, "parent_id": m.parent_id, "definition": m.definition,
                                                              "counts_as": m.counts_as, "does_not_count_as": m.does_not_count_as, "severity": m.severity,
                                                              "impact": m.impact_note, "decision": m.decision, "rank": m.rank, "version": m.version,
                                                              "is_none_bucket": m.is_none_bucket, "traces": crow.get(m.id, {}).get("count", 0),
                                                              "share_of_reviewed": crow.get(m.id, {}).get("share_reviewed"),
                                                              "share_of_failing": crow.get(m.id, {}).get("share_failing")} for m in modes]}, indent=2))
    names = {m.id: m.name for m in modes}
    out = io.StringIO()
    cw = csv.writer(out)
    cw.writerow(["trace_id", "channel", "verdict", "note", "failure_modes", "first_failure_event", "reviewer", "seconds_spent", "reviewed_at"])
    for r in s.exec(select(Review).where(Review.project_id == p.id, Review.verdict.is_not(None))).all():
        t = s.get(Trace, r.trace_id)
        labs = [names.get(lab.failure_mode_id, "?") for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == r.id)).all()]
        cw.writerow([t.external_id, t.channel, r.verdict, r.note, "; ".join(labs), r.first_failure_event_id or "", r.reviewer, round(r.seconds_spent), r.reviewed_at])
    cw.writerow([])
    cw.writerow(["# counts", "failure_mode", "traces", "share_of_reviewed", "share_of_failing"])
    for row in counts["rows"]:
        cw.writerow(["", row["name"], row["count"], row["share_reviewed"], row["share_failing"]])
    w("error_analysis.csv", out.getvalue())

    # ---- evaluators
    suite = {"project": p.name, "exported": stamp, "checks": [], "judges": []}
    spec_rows = []
    for ev in evaluators:
        v = E.run_version(s, ev)
        mode = s.get(FailureMode, ev.failure_mode_id) if ev.failure_mode_id else None
        motivated = f"{mode.name}: {crow.get(mode.id, {}).get('count', 0)} of {counts['n_reviewed']} reviewed traces ({_pct(crow.get(mode.id, {}).get('share_reviewed'))})" if mode else "—"
        if ev.type == "code":
            suite["checks"].append({"slug": ev.slug, "name": ev.name, "failure_mode": mode.name if mode else None, "version": v.version,
                                    "status": ev.status, "definition": v.definition})
            prev = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "check_preview", EvalRun.evaluator_version_id == v.id)
                          .order_by(EvalRun.id.desc())).first()
            m = prev.metrics if prev else None
            validation = (f"Checked against {m['n']} human-reviewed traces: TPR {_pct(m['tpr'])} (n={m['n_pos']}), TNR {_pct(m['tnr'])} (n={m['n_neg']}), "
                          f"{prev.created_at:%Y-%m-%d}.") if m else "Not yet checked against human labels."
        else:
            template = E.build_judge_prompt(s, p, mode, v, None, trace_placeholder="{{TRACE}}")
            final = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "final", EvalRun.evaluator_version_id == v.id,
                                                 EvalRun.status == "done").order_by(EvalRun.id.desc())).first()
            dev = s.exec(select(EvalRun).where(EvalRun.evaluator_id == ev.id, EvalRun.kind == "dev", EvalRun.evaluator_version_id == v.id,
                                               EvalRun.status == "done").order_by(EvalRun.id.desc())).first()
            fm_ = final.metrics if final else None
            validation = (f"Test split: TPR {_pct(fm_['tpr'])} (n={fm_['n_pos']}), TNR {_pct(fm_['tnr'])} (n={fm_['n_neg']}), run {final.created_at:%Y-%m-%d}; "
                          f"threshold {ev.threshold:.2f}." + (" Low confidence: fewer than 30 examples of a class." if fm_.get("low_confidence") else "")) if fm_ else "Not validated."
            suite["judges"].append({"slug": ev.slug, "name": ev.name, "failure_mode": mode.name, "version": v.version, "status": ev.status,
                                    "model": v.model, "context_scope": v.context_scope, "prompt_template": template,
                                    "output_schema": E.JUDGE_SCHEMA, "validated": ev.status == "validated",
                                    "test_metrics": {k: fm_.get(k) for k in ("tpr", "tnr", "n_pos", "n_neg")} if fm_ else None})
            banner = "" if ev.status == "validated" else "> **DRAFT — this judge has not passed final validation. Do not trust its numbers yet.**\n\n"
            md = [f"# {ev.name}\n", banner, f"- Failure mode: **{mode.name}** — {mode.definition}", f"- Model: `{v.model}`", f"- Version: v{v.version}",
                  f"- Context scope: {', '.join(v.context_scope)}", f"- Status: {ev.status}", f"- Owner: {ev.owner or '—'}",
                  f"- Validation: {validation}"]
            if dev:
                md.append(f"- Dev split: TPR {_pct(dev.metrics.get('tpr'))}, TNR {_pct(dev.metrics.get('tnr'))} (n={dev.metrics.get('n')})")
            md += ["", "## Prompt", "", "The trace (rendered for the context scope above) replaces `{{TRACE}}`. Output is structured as `{critique: string, failure: boolean}`, critique first.", "",
                   "```text", template, "```", ""]
            w(f"judges/{ev.slug}.md", "\n".join(md))
        spec_rows.append((ev, mode, motivated, validation))

    # ---- datasets
    golden_ids: set[int] = set()
    for ev in evaluators:
        if ev.type != "judge":
            continue
        rows = s.exec(select(GroundTruth).where(GroundTruth.failure_mode_id == ev.failure_mode_id)).all()
        for split in ("train", "dev", "test"):
            lines = []
            for g in rows:
                if g.split == split:
                    t = s.get(Trace, g.trace_id)
                    lines.append(json.dumps({"trace": _trace_record(s, t), "failure": g.label, "critique": g.critique, "split": split}))
            w(f"datasets/{ev.slug}_{split}.jsonl", "\n".join(lines) + ("\n" if lines else ""))
    # golden regression: past failures (up to 5 per failure mode) + one passing trace per channel
    for m in modes:
        if m.is_none_bucket:
            continue
        tids = [lab.trace_id for lab in s.exec(select(ReviewLabel).where(ReviewLabel.failure_mode_id == m.id)).all()][:5]
        golden_ids.update(tids)
    seen_ch = set()
    for r in s.exec(select(Review).where(Review.project_id == p.id, Review.verdict == "pass")).all():
        t = s.get(Trace, r.trace_id)
        if t.channel not in seen_ch:
            seen_ch.add(t.channel)
            golden_ids.add(t.id)
    golden = []
    for tid in sorted(golden_ids):
        t = s.get(Trace, tid)
        rv = s.exec(select(Review).where(Review.trace_id == tid)).first()
        labs = [names.get(lab.failure_mode_id) for lab in s.exec(select(ReviewLabel).where(ReviewLabel.review_id == rv.id)).all()] if rv else []
        golden.append(json.dumps({**_trace_record(s, t), "expected": {"verdict": rv.verdict if rv else None, "failure_modes": labs, "note": rv.note if rv else ""}}))
    w("datasets/golden_regression.jsonl", "\n".join(golden) + "\n")
    w("golden_regression.jsonl", "\n".join(golden) + "\n")

    # ---- runnable code
    w("suite.json", json.dumps(suite, indent=2))
    w("evals_lib.py", _lib_source())
    w("run_evals.py", RUN_EVALS)
    w("checks/__init__.py", "")
    w("checks/code_checks.py", CODE_CHECKS_PY)
    w("checks/conftest.py", "import sys, os\nsys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))\n")

    # ---- spec
    spec = [f"# Evaluation spec — {p.name}", "", f"Exported {stamp}. Built with error-analysis-first evals: every evaluator below exists because the failure was observed in real traces.", "",
            f"**Product:** {p.description}", "", f"**Error analysis:** {counts['n_reviewed']} traces reviewed, {counts['n_failing']} failing. "
            + (f"The top three failure modes ({', '.join(counts['top3_names'])}) account for {_pct(counts['top3_share'])} of labelled failures." if counts["top3_share"] else ""), "",
            "## Failure taxonomy", "", "| Rank | Failure mode | Traces | % of reviewed | Severity | Decision |", "|---|---|---|---|---|---|"]
    for m in [m for m in modes if not m.is_none_bucket and not m.parent_id]:
        r = crow.get(m.id, {})
        spec.append(f"| {m.rank} | {m.name} | {r.get('count', 0)} | {_pct(r.get('share_reviewed'))} | {m.severity or '—'} | {m.decision or '—'} |")
    spec += ["", "## Evaluators", ""]
    if not spec_rows:
        spec.append("_No evaluators yet._")
    for ev, mode, motivated, validation in spec_rows:
        warn = specificity_warnings(mode) if mode else []
        spec += [f"### {ev.name}" + ("" if ev.type == "code" or ev.status == "validated" else " (DRAFT)"), "",
                 f"- **Type:** {'code check' if ev.type == 'code' else 'LLM judge'} · status **{ev.status}**",
                 f"- **Measures:** {mode.name if mode else '—'} — {mode.definition if mode else ''}",
                 f"- **Motivated by:** {motivated}", f"- **Validation:** {validation}", f"- **Owner:** {ev.owner or '—'}",
                 f"- **Where it runs:** {ev.where_to_run or ('CI and production' if ev.type == 'code' else 'production monitoring (sampled)')}"]
        if warn:
            spec.append(f"- _Taxonomy note: {'; '.join(warn)}_")
        spec.append("")
    spec += ["## Fixed without an evaluator", ""]
    fixed = [m for m in modes if m.decision == "fix_now"]
    spec += [f"- {m.name}: {m.decision_note or 'fixed in the prompt'}" for m in fixed] or ["_None._"]
    spec += ["", "## Running", "", "```bash", "python run_evals.py                      # golden_regression.jsonl, code checks only",
             "python run_evals.py my_traces.jsonl --judges   # also run LLM judges (needs ANTHROPIC_API_KEY)",
             "EVAL_TRACES=my_traces.jsonl pytest checks/      # code checks as pytest assertions", "```", "",
             "Traces use the normalised format: `{id, channel, meta, system_prompt, events: [{role, content, tool_name, tool_args, tool_result}]}`.", "",
             "## Operating guidance", "", OPERATING_GUIDANCE]
    w("EVAL_SPEC.md", "\n".join(spec))
    z.close()
    return buf.getvalue(), root.rstrip("/") + ".zip"


def _slug(x: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", x.lower()).strip("_")[:40] or "project"


def _lib_source() -> str:
    head = ('"""Self-contained evaluator library exported by Evals Workbench. Do not edit by hand; re-export instead.\n'
            'Requires Python 3.10+. Code checks use only the standard library (jsonschema optional); judges need `anthropic`."""\n'
            "from typing import Iterable, Optional  # noqa: E402\n")
    checks_src = Path(checks.__file__).read_text(encoding="utf-8").replace("from __future__ import annotations\n", "")
    tt = inspect.getsource(_short) + "\n\n" + inspect.getsource(trace_text)
    return head + checks_src + "\n\n# ---- trace rendering for judges\n" + tt + "\n\n" + JUDGE_LIB


JUDGE_LIB = '''
# ---- LLM judge runner
def run_judge(judge: dict, trace: dict, business_facts: str = "") -> dict:
    """Returns {"critique": str, "failure": bool}. Needs the `anthropic` package and ANTHROPIC_API_KEY."""
    import anthropic

    scope = judge.get("context_scope") or ["last_assistant"]
    text = trace_text(trace, scope)
    prompt = judge["prompt_template"].replace("{{TRACE}}", text)
    client = anthropic.Anthropic(max_retries=4)
    resp = client.messages.create(
        model=judge.get("model") or "claude-sonnet-5-5",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": judge["output_schema"]}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined the request")
    out = next(b.text for b in resp.content if b.type == "text")
    return json.loads(out)
'''

RUN_EVALS = '''#!/usr/bin/env python
"""Run the exported eval suite against a JSONL of traces.

    python run_evals.py [traces.jsonl] [--judges] [--json results.json]

Defaults to golden_regression.jsonl. Code checks always run. LLM judges run only with --judges
(and need ANTHROPIC_API_KEY plus `pip install anthropic`). Exit code is 0 unless the suite itself errors;
use the printed rates (or --json) to gate CI.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evals_lib  # noqa: E402


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("traces", nargs="?", default=os.path.join(HERE, "golden_regression.jsonl"))
    ap.add_argument("--judges", action="store_true", help="also run LLM judges")
    ap.add_argument("--json", help="write per-trace results here")
    a = ap.parse_args()
    suite = json.load(open(os.path.join(HERE, "suite.json"), encoding="utf-8"))
    traces = load(a.traces)
    print(f"Suite: {suite['project']} (exported {suite['exported']}) - {len(traces)} traces from {os.path.basename(a.traces)}\\n")
    results = {t.get("id"): {} for t in traces}
    rows = []
    for c in suite["checks"]:
        res = evals_lib.run_definition(c["definition"], traces)
        fails = [tid for tid, (failed, _) in res.items() if failed]
        for tid, (failed, why) in res.items():
            results[tid][c["slug"]] = {"failure": failed, "reason": why}
        rows.append((c["name"], "code", len(fails), len(traces), c.get("status", "")))
    for j in suite["judges"]:
        label = j["name"] + ("" if j.get("validated") else " [DRAFT]")
        if not a.judges:
            rows.append((label, "judge", None, len(traces), "skipped (use --judges)"))
            continue
        if not os.environ.get("ANTHROPIC_API_KEY"):
            rows.append((label, "judge", None, len(traces), "skipped (no ANTHROPIC_API_KEY)"))
            continue
        k = 0
        for t in traces:
            try:
                out = evals_lib.run_judge(j, t)
                results[t.get("id")][j["slug"]] = out
                k += bool(out["failure"])
            except Exception as e:  # noqa: BLE001
                results[t.get("id")][j["slug"]] = {"error": str(e)}
        rows.append((label, "judge", k, len(traces), "raw rate - correct it with TPR/TNR in EVAL_SPEC.md"))
    w = max([len(r[0]) for r in rows] + [10])
    print(f"{'evaluator'.ljust(w)}  type   failures   rate    note")
    for name, kind, k, n, note in rows:
        rate = "   -  " if k is None else f"{100 * k / max(1, n):5.1f}%"
        print(f"{name.ljust(w)}  {kind:<5}  {('-' if k is None else str(k)).rjust(4)}/{n:<4}  {rate}  {note}")
    ran = [s for s in (c["slug"] for c in suite["checks"])]
    passing = sum(1 for tid, r in results.items() if all(not r.get(sl, {}).get("failure") for sl in ran))
    print(f"\\nPass-all (code checks): {passing}/{len(traces)} traces")
    if a.json:
        json.dump(results, open(a.json, "w", encoding="utf-8"), indent=2)
        print(f"Wrote {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

CODE_CHECKS_PY = '''"""Code checks as pytest assertions.

    EVAL_TRACES=path/to/outputs.jsonl pytest checks/

Each check asserts that no trace in EVAL_TRACES shows its failure. The default file is the golden
regression set, which contains past failures on purpose; run it against fresh outputs of your
system for those inputs.
"""
import json
import os

import pytest

import evals_lib

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUITE = json.load(open(os.path.join(HERE, "suite.json"), encoding="utf-8"))
TRACES_FILE = os.environ.get("EVAL_TRACES", os.path.join(HERE, "golden_regression.jsonl"))
TRACES = [json.loads(line) for line in open(TRACES_FILE, encoding="utf-8") if line.strip()]


@pytest.mark.parametrize("check", SUITE["checks"], ids=[c["slug"] for c in SUITE["checks"]] or None)
def test_check(check):
    res = evals_lib.run_definition(check["definition"], TRACES)
    failures = {tid: why for tid, (failed, why) in res.items() if failed}
    assert not failures, f"{check['name']}: {len(failures)} failing trace(s): " + "; ".join(f"{k}: {v}" for k, v in list(failures.items())[:5])
'''
