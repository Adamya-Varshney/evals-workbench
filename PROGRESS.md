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

## Next: Phase 2 — Review screen
