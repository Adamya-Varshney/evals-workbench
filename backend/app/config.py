"""Runtime configuration, read from environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


class Settings:
    @property
    def anthropic_api_key(self) -> str:
        return _env("ANTHROPIC_API_KEY", "")

    @property
    def model(self) -> str:
        return _env("EVALS_MODEL", "claude-sonnet-5-5")

    @property
    def llm_mode(self) -> str:
        # "mock" returns deterministic canned responses; "live" calls the API.
        mode = _env("LLM_MODE", "")
        if mode:
            return mode.lower()
        return "live" if self.anthropic_api_key else "mock"

    @property
    def db_url(self) -> str:
        return _env("EVALS_DB", f"sqlite:///{(BACKEND / 'evals_workbench.db').as_posix()}")

    @property
    def llm_concurrency(self) -> int:
        return int(_env("EVALS_LLM_CONCURRENCY", "4"))

    @property
    def fallbacks_enabled(self) -> bool:
        # Server-side refusal fallback (Claude API only). Set EVALS_FALLBACKS=0 to turn off.
        return _env("EVALS_FALLBACKS", "1") not in ("0", "false", "no")


settings = Settings()

SEED_FILE = BACKEND / "seed" / "larkspur_traces.jsonl"

# USD per million tokens (input, output). Used for cost estimates and the AI activity log.
PRICING = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-fable-5-1": (10.00, 50.00),
}


def price_for(model: str) -> tuple[float, float]:
    return PRICING.get(model, (2.00, 10.00))
