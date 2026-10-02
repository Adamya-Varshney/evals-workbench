"""One entry point for local development (works with or without `make`).

    python dev.py setup   # create backend/.venv, install Python + npm deps, write .env if missing
    python dev.py dev     # run FastAPI (port 8000) and Vite (port 5173) together
    python dev.py test    # backend pytest + frontend typecheck
    python dev.py e2e     # Playwright keyboard-only review test (starts its own servers)
    python dev.py seed    # regenerate the demo traces
    python dev.py serve   # build the frontend and serve everything from FastAPI on :8000
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
WIN = os.name == "nt"
VENV_PY = BACKEND / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")
NPM = "npm.cmd" if WIN else "npm"
NPX = "npx.cmd" if WIN else "npx"


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> int:
    print(f"$ {' '.join(map(str, cmd))}  (in {cwd.name})", flush=True)
    return subprocess.call(cmd, cwd=cwd, env={**os.environ, **(env or {})})


def py() -> str:
    return str(VENV_PY) if VENV_PY.exists() else sys.executable


def setup() -> int:
    if not VENV_PY.exists():
        if run([sys.executable, "-m", "venv", ".venv"], BACKEND):
            return 1
    if run([str(VENV_PY), "-m", "pip", "install", "-q", "-r", "requirements.txt"], BACKEND):
        return 1
    if run([NPM, "install"], FRONTEND):
        return 1
    env = ROOT / ".env"
    if not env.exists():
        shutil.copy(ROOT / ".env.example", env)
        print("Wrote .env from .env.example (LLM_MODE=mock). Add ANTHROPIC_API_KEY to use the real model.")
    return 0


def dev() -> int:
    if not VENV_PY.exists() or not (FRONTEND / "node_modules").exists():
        if setup():
            return 1
    procs = [
        subprocess.Popen([py(), "-m", "uvicorn", "app.main:app", "--reload", "--reload-dir", "app", "--host", "127.0.0.1", "--port", "8000"], cwd=BACKEND),
        subprocess.Popen([NPM, "run", "dev", "--", "--host", "127.0.0.1"], cwd=FRONTEND),
    ]
    print("\n  Evals Workbench -> http://127.0.0.1:5173  (API on :8000)\n  Ctrl+C to stop.\n", flush=True)
    try:
        while all(p.poll() is None for p in procs):
            try:
                procs[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                if WIN:
                    subprocess.call(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    p.send_signal(signal.SIGINT)
    return 0


def test() -> int:
    rc = run([py(), "-m", "pytest", "-q"], BACKEND, {"LLM_MODE": "mock"})
    rc |= run([NPX, "tsc", "-p", "tsconfig.json"], FRONTEND)
    return rc


def e2e() -> int:
    return run([NPX, "playwright", "test"], FRONTEND)


def seed() -> int:
    return run([py(), "seed/generate_seed.py"], BACKEND)


def serve() -> int:
    if run([NPM, "run", "build"], FRONTEND):
        return 1
    return run([py(), "-m", "uvicorn", "app.main:app", "--port", "8000"], BACKEND)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dev"
    fn = {"setup": setup, "dev": dev, "test": test, "e2e": e2e, "seed": seed, "serve": serve}.get(cmd)
    if not fn:
        print(__doc__)
        sys.exit(2)
    sys.exit(fn())
