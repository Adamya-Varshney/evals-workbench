# Progress

## Phase 1 — Scaffold, data model, seed data, import with mapping, project setup ✅

**Built**
- FastAPI + SQLModel/SQLite backend with the full data model, so later phases need no migrations (`backend/app/models.py`).
- One LLM gateway (`backend/app/llm/client.py`): structured outputs via `output_config.format`, SDK retries, a concurrency limit, server-side refusal fallback, and every call logged to `llm_calls`. `LLM_MODE=mock` gives deterministic responses. Eight prompt templates are stored in the DB and editable in Settings.
- Statistics module (`backend/app/stats.py`): Wilson intervals, TPR/TNR, the raw-agreement trap, the corrected failure rate and a 2,000-iteration bootstrap. Plus split assignment (`backend/app/splits.py`): stratified by label and fixed when a trace is first labelled.
- Importer (`backend/app/importers/normalize.py`): reads JSONL, JSON and CSV in OpenAI, Anthropic content-block or LangChain-style formats, including nested paths and JSON-in-CSV columns. Auto-guesses the field mapping, redacts emails, phones and custom regexes, turns every unmapped field into a metadata facet, and writes an import report listing skipped rows with reasons.
- Sampling for review batches: random, stratified, outliers, negative feedback and evaluator-flagged, always keeping at least 20% random.
- Ten-stage stepper with a status and "what to do next" for each stage, plus one next-best-action card on the home screen.
- Seed project: 120 Larkspur traces, 58% clean, with 8 planted failure types. One line is malformed, one record is empty and one is a duplicate. The planted truth lives only in `backend/tests/fixtures/planted_truth.json`.
- UI: project picker, home, setup (including prompt versions), Get traces (upload, mapping screen with a live rendered preview of 3 traces, redaction, import report, facets, batch builder), AI activity drawer, settings with a template editor, and the AI-assist switch with a privacy notice. Trace rendering per channel: SMS bubbles, email thread, chat widget and voice transcript, plus tool cards and a collapsible system prompt.

**Tests**: 27 backend tests pass (stats, splits, importers, the seed import flow and the API). Frontend typechecks and builds.

**Try it**
1. `python dev.py dev` (or `make dev`), then open http://localhost:5173
2. Click **Open the demo project**. Home shows the next action: add your reviewer name.
3. **Set up the project**: add your name and save. Step 1 turns ✓.
4. **Get traces** → **Load the Larkspur demo traces**. Change the mapping, tick "Phone numbers" and watch the preview update. Click **Import**, then check the report (3 skipped, with reasons) and the facets.
5. Build a batch of 100 (try "Stratified by channel" too). Step 2 turns ✓ and step 3 unlocks.

## Phase 2 — Review screen + UI restyle ✅

**UI restyle (per feedback: "like Braintrust or LangSmith")**
- Neutral zinc design system built from CSS-variable tokens. Light is the default, with a dark toggle in the top bar that is remembered per browser. 13px dense type, table-first layouts.
- App shell: a top bar with breadcrumbs (project / page), a model/mock badge, AI activity, Settings and the theme toggle. A slim left workflow sidebar with step status icons (shape, not colour alone) that collapses to icons while reviewing.
- Overview is now a next-action card, four stat tiles and a stage table. Projects, batches and the AI activity log are tables.
- The trace viewer has LangSmith-style tabs: **Conversation** (as the end user saw it), **Steps** (an event tree with a detail pane) and **Raw JSON**.

**Review screen** (`frontend/src/pages/Review.tsx`, `backend/app/routers/review.py`)
- Three panes: queue (search, channel and status filters, verdict badges), the trace with its metadata strip, and the judgment panel.
- Pass/Fail with one key, a free-text note with autosave, a first-failure anchor (click a turn, or `[` `]` then `A`), come back later, and undo (server-side history; rapid note edits collapse into one undo step).
- Hotkeys: J/K and the arrow keys, P, F (focuses the note), N, S, T, D, R, B, Z, `/`, `?`, Esc, and Ctrl/⌘+Enter for save and next from anywhere. Neighbouring traces are prefetched.
- Progress ("12 of 100 reviewed"), pass/fail tally, session timer, median seconds per trace, and a nudge after 2 minutes on one trace (configurable).
- Saturation: new problem types in the last 20 reviews, with a sparkline and a suggestion to stop once it reaches zero.
- System prompt marked "same as / changed from previous trace". Business facts and channel rules open in a slide-over (B). In multi-turn fails you are prompted to mark the first upstream failure.
- No category picker in the first round. Quick-tag chips (1–9) appear only in later rounds, after the note.
- AI assist is locked until 30 hand reviews and respects the global switch. "Find similar traces" uses a keyword prefilter, then ranking by the LLM.
- Evaluator verdicts are hidden until you have saved your own judgment.
- Robustness: a unique review per trace, saves serialised per trace on the client, and a write lock on the server.

**Tests**: 32 backend tests pass (including review save, undo, defer, stats, saturation and the AI gate). The **Playwright keyboard-only review test passes** (`python dev.py e2e`).

**Try it**
1. `python dev.py dev`, then open http://localhost:5173 → Open demo project (the light theme is new; ☾ in the top bar switches to dark).
2. Add your reviewer name in Set up, then go to **Review traces**.
3. Press `?` for shortcuts. Then `P`, `J`, `F`, type a note, `Esc`, `]` `]` `A` to mark the first failure, and `Ctrl+Enter` to save and move on.
4. Watch the progress count, median s/trace and the "New problem types" indicator. Try the **Steps** tab and `R` for raw JSON.
5. After 30 reviews, "Find similar traces" unlocks in the right panel.

## Next: Phase 3 — Group failures and Count
