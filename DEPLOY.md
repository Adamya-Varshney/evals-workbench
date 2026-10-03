# Deploying Evals Workbench

There are two setups:

| | Portfolio demo | Your own projects |
|---|---|---|
| Who uses it | Anyone with the link | Only you |
| AI | Simulated (never calls Claude, ignores any key) | Real Claude with your key |
| Data | Resets every 24 h | Kept |
| Where | Render (free) or Railway | Your PC + Tailscale (recommended), or a private hosted copy |

The app runs as **one container**: FastAPI serves both the API and the built React app on `$PORT`.

The `Dockerfile`, `render.yaml` and `/healthz` endpoint are included. These environment switches control behaviour:

| Variable | Effect |
|---|---|
| `DEMO_MODE=1` | Public demo. Forces simulated AI and ignores `ANTHROPIC_API_KEY`. Shows a banner. On startup, and every `DEMO_RESET_HOURS` (default 24), it wipes all data and rebuilds two projects: a blank **Larkspur Residences** project (traces imported, ready to review) and a **guided walkthrough** with every stage already completed. Visitors can also click *Reset now*. Uploads are capped at 5 MB. |
| `APP_PASSWORD=...` | Puts the whole app behind a browser password prompt (any username). Use it for any private hosted copy. |
| `EVALS_DB` | SQLite location. The image defaults to `/data/evals_workbench.db`; mount a volume at `/data` to keep data. |
| `LLM_MODE=live`, `ANTHROPIC_API_KEY`, `EVALS_MODEL` | Real AI, for private copies only. |

---

## 1. Put the code on GitHub (once)

1. Create an **empty** repository on github.com, e.g. `evals-workbench`, without a README.
2. Push the code:

```bash
git remote add origin https://github.com/<you>/evals-workbench.git
git branch -M main
git push -u origin main
```

`.env` (your API key) is in `.gitignore`, so it is never pushed. Check with `git status` before pushing if you're unsure.

---

## 2. Portfolio demo

### Option A — Render (free)

1. render.com → **New → Blueprint** → connect your GitHub repo. Render reads `render.yaml` (Docker, free plan, `DEMO_MODE=1`).
2. Click **Apply**. The first build takes about 5 minutes. Your URL looks like `https://evals-workbench-demo.onrender.com`.

On the free plan the service sleeps after about 15 minutes without visitors, so the first visit after that takes 30–60 seconds while it starts and rebuilds the demo. That's fine for a portfolio link. A fresh start also resets the data, which is what you want here.

### Option B — Railway (about $5/month, never sleeps)

1. railway.com → **New Project → Deploy from GitHub repo**. Railway detects the `Dockerfile`.
2. **Variables:** add `DEMO_MODE` = `1`.
3. **Settings → Networking → Generate Domain.**

### What visitors see

- A banner explaining that AI responses are simulated and that data resets.
- Two projects. They can open the walkthrough to see every stage filled in (reviews, failure taxonomy, counts, a validated judge with TPR/TNR, suite runs, the export bundle), or review the blank Larkspur project themselves using the keyboard.
- **Download bundle** works, so they can run `run_evals.py` locally.

The walkthrough's notes and labels are pre-written for the demo. The blank Larkspur project never sees them, so visitors still have to find the failures by reading.

### Portfolio tips

- Link straight to the walkthrough (`/p/2`), and to the review screen (`/p/1/review`) with a note saying "press ? for keyboard shortcuts".
- A 60–90 second screen recording of the review → group → validate loop is worth adding next to the link.

---

## 3. Your own projects

### Option A (recommended) — run it on your PC, reach it from anywhere with Tailscale

Your traces never leave your machine, there is nothing to pay for, and no login is needed because only devices you own can reach it.

1. Install Tailscale on your PC and your phone/laptop (tailscale.com, free personal plan) and sign in on both.
2. On the PC, from the `evals-workbench` folder:

```bash
python dev.py serve
```

This builds the UI and serves everything on port 8000.

3. In another terminal:

```bash
tailscale serve --bg 8000
```

4. Open the `https://<your-pc>.<tailnet>.ts.net` address it prints, from any of your devices.

Put your key in `.env` (`ANTHROPIC_API_KEY=...`, `LLM_MODE=live`) for real AI. Data lives in `%LOCALAPPDATA%\EvalsWorkbench\`.

### Option B — a private hosted copy (Railway)

Use this if you want it running when your PC is off.

1. In your Railway project, **New → GitHub repo** (the same repo; this becomes a second service).
2. **Variables:**
   - `APP_PASSWORD` = a long random password
   - `LLM_MODE` = `live`
   - `ANTHROPIC_API_KEY` = your key (Railway stores it as a secret)
   - optionally `EVALS_MODEL`
3. **Settings → Volumes → Add volume** mounted at `/data`. Without it, your data is lost on every deploy.
4. **Generate Domain.** The browser asks for the password on first visit.

Also set a **monthly spend limit** in the Anthropic Console for that key.

If you import real customer traces, tick the **redact emails / phone numbers** options on import.

---

## 4. Test the container locally (optional)

Docker Desktop must be running.

```bash
docker build -t evals-workbench .
docker run --rm -p 8000:8000 -e DEMO_MODE=1 evals-workbench
```

Open http://localhost:8000.

For a private copy with persistent data:

```bash
docker run --rm -p 8000:8000 -e APP_PASSWORD=change-me -e LLM_MODE=live -e ANTHROPIC_API_KEY=sk-ant-... -v evals-data:/data evals-workbench
```

## Updating

Push to `main`. Render and Railway rebuild and redeploy automatically. The demo rebuilds its data on every start; a private copy keeps its data on the `/data` volume, and schema changes are applied at startup.
