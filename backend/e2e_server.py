"""Start the API on a throwaway database for the Playwright test."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
db = HERE / "e2e.db"
for suffix in ("", "-wal", "-shm"):
    p = Path(str(db) + suffix)
    if p.exists():
        p.unlink()
os.environ["EVALS_DB"] = f"sqlite:///{db.as_posix()}"
os.environ["LLM_MODE"] = "mock"
sys.path.insert(0, str(HERE))
import uvicorn  # noqa: E402

uvicorn.run("app.main:app", host="127.0.0.1", port=int(sys.argv[1] if len(sys.argv) > 1 else 8011))
