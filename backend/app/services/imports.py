"""Stage → preview → commit pipeline for trace imports."""
from __future__ import annotations

import hashlib
from collections import Counter

from sqlmodel import Session, select

from ..importers.normalize import (
    NormTrace, SkipRecord, apply_redaction, guess_mapping, normalize_record, parse_file,
)
from ..models import Event, ImportJob, PromptVersion, Trace, now


def stage_import(s: Session, project_id: int, filename: str, text: str, tags: dict | None = None) -> ImportJob:
    records, fmt, errors = parse_file(text, filename)
    job = ImportJob(project_id=project_id, filename=filename, fmt=fmt, raw_text=text,
                    mapping=guess_mapping(records), tags=tags or {},
                    report={"parsed": len(records), "parse_errors": errors})
    s.add(job)
    s.commit()
    s.refresh(job)
    return job


def records_of(job: ImportJob) -> tuple[list[dict], list[dict]]:
    recs, _, errors = parse_file(job.raw_text, job.filename)
    return recs, errors


def source_fields(job: ImportJob) -> list[dict]:
    """Field paths found in the first records, with a sample value, for the mapping screen."""
    from ..importers.normalize import _candidate_paths  # noqa: PLC0415

    recs, _ = records_of(job)
    seen: dict[str, str] = {}
    for r in recs[:20]:
        for p, v in _candidate_paths(r):
            if p not in seen:
                sv = v if isinstance(v, str) else repr(v)
                seen[p] = sv[:80]
    return [{"path": p, "sample": v} for p, v in seen.items()]


def preview(job: ImportJob, mapping: dict, redaction: dict, n: int = 3) -> dict:
    recs, errors = records_of(job)
    out, skipped = [], []
    for i, r in enumerate(recs):
        if len(out) >= n:
            break
        try:
            t = apply_redaction(normalize_record(r, mapping, i), redaction)
            out.append(norm_to_view(t))
        except SkipRecord as e:
            skipped.append({"index": i + 1, "reason": str(e)})
    return {"traces": out, "skipped_in_preview": skipped, "total_records": len(recs), "parse_errors": errors}


def norm_to_view(t: NormTrace) -> dict:
    return {
        "external_id": t.external_id, "channel": t.channel, "meta": t.meta, "system_prompt": t.system_prompt,
        "events": [{**e, "id": e["seq"]} for e in t.events], "n_turns": t.n_turns, "n_tool_calls": t.n_tool_calls,
    }


def commit_import(s: Session, job: ImportJob, mapping: dict, redaction: dict) -> dict:
    recs, errors = records_of(job)
    # Duplicate = same trace id when the source has ids, otherwise identical content.
    has_ids = bool(mapping.get("id"))
    key_col = Trace.external_id if has_ids else Trace.content_hash
    existing_keys = set(s.exec(select(key_col).where(Trace.project_id == job.project_id)).all())
    versions = {pv.label: pv for pv in s.exec(select(PromptVersion).where(PromptVersion.project_id == job.project_id)).all()}
    imported, skipped = 0, list(errors)
    reasons: Counter = Counter()
    channels: Counter = Counter()
    for i, r in enumerate(recs):
        try:
            t = apply_redaction(normalize_record(r, mapping, i), redaction)
        except SkipRecord as e:
            skipped.append({"line": i + 1, "id": str(r.get("id", "")), "reason": str(e)})
            continue
        h = t.content_hash()
        key = t.external_id if has_ids else h
        if key in existing_keys:
            skipped.append({"line": i + 1, "id": t.external_id, "reason": "duplicate of a trace already imported"})
            continue
        existing_keys.add(key)
        pv_id = None
        if t.prompt_version:
            pv = versions.get(t.prompt_version)
            if pv is None and t.system_prompt:
                pv = PromptVersion(project_id=job.project_id, label=t.prompt_version, body=t.system_prompt)
                s.add(pv)
                s.flush()
                versions[pv.label] = pv
            pv_id = pv.id if pv else None
        trace = Trace(
            project_id=job.project_id, import_id=job.id, external_id=t.external_id, raw=t.raw, channel=t.channel,
            meta=t.meta, synthetic=bool(job.tags.get("synthetic")), synthetic_tuple=_tuple_of(r, job.tags),
            prompt_version_id=pv_id, system_prompt=t.system_prompt,
            system_prompt_hash=hashlib.sha256(t.system_prompt.encode()).hexdigest()[:16] if t.system_prompt else "",
            content_hash=h, n_turns=t.n_turns, n_tool_calls=t.n_tool_calls, n_chars=t.n_chars, search_text=t.search_text(),
        )
        if trace.synthetic:
            trace.meta = {**trace.meta, "synthetic": True}
        s.add(trace)
        s.flush()
        for e in t.events:
            s.add(Event(trace_id=trace.id, seq=e["seq"], role=e["role"], content=e["content"], tool_name=e["tool_name"],
                        tool_args=e["tool_args"], tool_result=e["tool_result"], tool_call_id=e["tool_call_id"]))
        imported += 1
        channels[t.channel] += 1
    for sk in skipped:
        reasons[sk["reason"].split(" (")[0]] += 1
    job.mapping, job.redaction, job.status = mapping, redaction, "committed"
    job.report = {"parsed": len(recs), "imported": imported, "skipped": len(skipped), "skipped_rows": skipped[:200],
                  "skip_reasons": dict(reasons), "channels": dict(channels), "committed_at": now().isoformat()}
    job.raw_text = ""  # the raw record is kept per trace; no need to hold the file
    s.add(job)
    s.commit()
    return job.report


def _tuple_of(rec: dict, tags: dict) -> dict:
    if not tags.get("synthetic"):
        return {}
    t = rec.get("tuple") or rec.get("synthetic_tuple") or {}
    return t if isinstance(t, dict) else {}
