"""The single gateway for every Claude call the app makes.

- Structured outputs via `output_config.format` (JSON schema), parsed and returned as a dict.
- SDK retries (429/5xx/connection) plus a process-wide concurrency limit.
- Every call (prompt, response, tokens, cost) is logged to `llm_calls`.
- LLM_MODE=mock returns deterministic canned responses (see mock.py) so nothing needs a key.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional

from sqlmodel import Session

from ..config import price_for, settings
from ..db import get_engine
from ..models import LLMCall


class LLMError(RuntimeError):
    pass


class AIGateError(RuntimeError):
    """Raised when an AI-assist feature is locked or switched off."""


_sem_lock = threading.Lock()
_sem: Optional[threading.BoundedSemaphore] = None
_client = None


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    with _sem_lock:
        if _sem is None:
            _sem = threading.BoundedSemaphore(max(1, settings.llm_concurrency))
        return _sem


def _anthropic():
    global _client
    if _client is None:
        import anthropic

        if not settings.anthropic_api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set. Add it to .env or run with LLM_MODE=mock.")
        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=4, timeout=180.0)
    return _client


def estimate_cost(input_tokens: int, output_tokens: int, model: Optional[str] = None) -> float:
    pin, pout = price_for(model or settings.model)
    return input_tokens / 1e6 * pin + output_tokens / 1e6 * pout


def call_structured(
    job: str,
    prompt: str,
    schema: dict,
    *,
    project_id: Optional[int] = None,
    system: Optional[str] = None,
    max_tokens: int = 16000,
    model: Optional[str] = None,
    mock_ctx: Optional[dict] = None,
) -> dict:
    """Send one prompt, get back a dict that validates against `schema`.

    Returns {"data": ..., "call_id": int, "cost_usd": float}.
    """
    model = model or settings.model
    mode = settings.llm_mode
    req = {"system": system or "", "prompt": prompt, "schema": schema, "max_tokens": max_tokens}
    started = time.monotonic()
    log = LLMCall(project_id=project_id, job=job, model=model, mode=mode, request=req)
    try:
        with _semaphore():
            if mode == "mock":
                from .mock import respond

                data = respond(job, mock_ctx or {}, prompt)
                text = json.dumps(data)
                in_tok = max(1, len(prompt) // 4)
                out_tok = max(1, len(text) // 4)
            else:
                data, text, in_tok, out_tok = _live(prompt, schema, system, max_tokens, model)
        log.response = text
        log.input_tokens, log.output_tokens = in_tok, out_tok
        log.cost_usd = round(estimate_cost(in_tok, out_tok, model), 6) if mode != "mock" else 0.0
        return {"data": data, "call_id": _save(log, started), "cost_usd": log.cost_usd}
    except Exception as e:  # noqa: BLE001
        log.error = f"{type(e).__name__}: {e}"
        _save(log, started)
        if isinstance(e, LLMError):
            raise
        raise LLMError(log.error) from e


def _live(prompt: str, schema: dict, system: Optional[str], max_tokens: int, model: str):
    import anthropic

    client = _anthropic()
    kwargs: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if system:
        kwargs["system"] = system
    if settings.fallbacks_enabled:
        # Server-side refusal fallback: if a safety classifier declines, the API re-runs on a fallback model.
        kwargs["extra_headers"] = {"anthropic-beta": "server-side-fallback-2026-07-01"}
        kwargs["extra_body"] = {"fallbacks": "default"}
    try:
        resp = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        if settings.fallbacks_enabled and "fallback" in str(e).lower():
            kwargs.pop("extra_headers", None)
            kwargs.pop("extra_body", None)
            resp = client.messages.create(**kwargs)
        else:
            raise LLMError(f"Bad request: {e}") from e
    except anthropic.AuthenticationError as e:
        raise LLMError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Rate limited by the Anthropic API after retries. Try again shortly or lower EVALS_LLM_CONCURRENCY.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"API error {e.status_code}: {e}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Could not reach the Anthropic API.") from e

    if resp.stop_reason == "refusal":
        cat = getattr(getattr(resp, "stop_details", None), "category", None)
        raise LLMError(f"The model declined this request (category: {cat}).")
    if resp.stop_reason == "max_tokens":
        raise LLMError("The response hit max_tokens before finishing; try fewer items per call.")
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Model returned invalid JSON: {e}") from e
    u = resp.usage
    in_tok = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (getattr(u, "cache_creation_input_tokens", 0) or 0)
    return data, text, in_tok, u.output_tokens or 0


def _save(log: LLMCall, started: float) -> int:
    log.latency_ms = int((time.monotonic() - started) * 1000)
    with Session(get_engine()) as s:
        s.add(log)
        s.commit()
        s.refresh(log)
        return log.id  # type: ignore[return-value]
