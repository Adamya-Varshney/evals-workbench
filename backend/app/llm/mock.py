"""Deterministic canned responses for LLM_MODE=mock.

Each responder receives `ctx`, the structured data the caller already holds (notes, failure modes,
trace text...), so it can return plausible, schema-valid output without parsing prompts.
Responders are registered per job name.
"""
from __future__ import annotations

from typing import Callable

_RESPONDERS: dict[str, Callable[[dict, str], dict]] = {}


def responder(job: str):
    def deco(fn):
        _RESPONDERS[job] = fn
        return fn

    return deco


def respond(job: str, ctx: dict, prompt: str) -> dict:
    fn = _RESPONDERS.get(job)
    if fn is None:
        raise RuntimeError(f"No mock responder for job '{job}'")
    return fn(ctx, prompt)


@responder("ping")
def _ping(ctx: dict, prompt: str) -> dict:
    return {"ok": True, "echo": prompt[:40]}
