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

## Phase 3 — Group failures and Count ✅

**Group failures** (`frontend/src/pages/Group.tsx`, `backend/app/routers/group.py`, `backend/app/services/taxonomy.py`)
- Every note in one table, with tabs: All, Unassigned, AI suggestions to confirm, None of the above, Needs re-check.
- **✦ Propose categories** (locked until 30 reviews): sends the failing notes to the model using the terms "open codes" and "axial codes" and returns 5–6 proposals, each with a definition and example notes. Proposals are editable cards; nothing is created until you accept.
- **Taxonomy editor**: add, rename, merge, split (as siblings or sub-categories, with affected labels flagged for re-check), delete, one level of sub-category, and a full edit history. Every mode has a definition, "counts as" and "does not count as".
- **Specificity check**: warnings for vague names (quality, temporal, general, issues…), one-word names and missing definition fields. The colleague test is shown in the panel and the editor.
- **None of the above** always exists. Notes landing there sit in their own queue with a "+ Create category from this note" action.
- **✦ Suggest assignments**: every suggestion needs your confirmation. Keyboard: J/K move, Enter accepts, 1–9 change modes, 0 sends to None of the above, X rejects, O opens the trace, E edits the note. Bulk accept within a category unlocks only after 10 one-by-one confirmations. A trace can carry several modes, and each label records its source (human, or AI-suggested and confirmed).
- **Criteria drift**: changing a definition bumps the version and flags that category's labels for re-check. "✓ Still correct" (Enter) clears the flag.

**Count and prioritise** (`frontend/src/pages/Count.tsx`)
- Pivot table of failure mode and sub-mode by traces, % of reviewed (n=…) and % of failing (n=…), with both denominators labelled. Pivot by any facet (channel, prompt version, property, feedback…) and filter by batch.
- Every number opens the traces behind it, and each of those opens the full trace with your note.
- Bar chart sorted by frequency (single series), plus a line stating what share of failures the top three modes account for.
- Priority list: drag to reorder (or use ▲▼), severity Low/High/Catastrophic shown with icon and text, and a one-line impact note. No computed score.

**Also fixed**: the dev runner now binds to 127.0.0.1 (on Windows `localhost` added ~200ms per request) and only watches `backend/app` for reloads. A stale `frontend/dist` that hid a stuck reload is gone.

**Tests**: 36 backend tests pass, including the full grouping flow (propose → rename vague → suggest → 10 confirmations → bulk → clear None queue → count → drill → severity/order), definition-change re-check with history, and merge/split/sub-categories/delete. The Playwright review test still passes.

**Try it** (on the demo, after reviewing at least 30 traces with notes)
1. **Group failures** → **✦ Propose categories**. Rewrite any proposal with a warning (e.g. "Temporal issues" → "Wrong current date") and Accept. Reject the vague ones.
2. **✦ Suggest assignments**, then confirm with the keyboard: Enter, J, change one with a number key, Enter… After 10, "Accept all suggested here" appears on each mode.
3. Open the **None of the above** tab and create a category from one of its notes.
4. Edit a mode's definition and watch its labels move into **Needs re-check**.
5. **Count and prioritise** → pivot by channel → click a number to see the traces. Set severities, drag to reorder.

## Phase 4 — Decide, fix log, code checks ✅
- One decision card per failure mode: Fix now / Code check / LLM judge / Park, with the helper questions. The judge option shows its cost honestly (~100+ labels plus upkeep). Soft warnings appear once the suite grows past 2–3 checks or 1–2 judges.
- Fix log: what changed, when, and which prompt version. The before rate is measured on earlier batches and the after rate on the next batch reviewed.
- Code-check engine (`backend/app/checks.py`): regex present/absent, markdown preset, tool called / not called, tool called more than N times, required tool arguments, length limits, JSON against a schema. Every rule can be scoped by any facet (e.g. SMS only). Custom Python `check(trace) -> bool` runs in an isolated subprocess with a timeout.
- "✦ Draft with AI" for checks. It says plainly when a failure needs a judge or Python instead of rules. You approve a draft by saving it as a version.
- "Run on reviewed traces" shows the check next to your labels (disagreements first). **Activate** stays disabled until you have seen at least one correct fail and one correct pass. Editing an active check puts it back to draft.
- Later review rounds: building a batch after a taxonomy exists starts round 2+, where quick-tag chips appear under the note.

## Phase 5 — LLM judges and validation ✅
- One judge per failure mode, enforced. Three-part prompt: (1) "the failure occurs when", (2) "it is NOT a failure when", (3) a critique first, then `{critique, failure}` as structured output.
- Context selector (last assistant turn, full conversation, tool calls, system prompt, business facts), defaulting to the minimum. Few-shot examples come from the train split only. "View exact prompt" shows precisely what the judge receives. Every version is kept.
- Ground truth: seed from error analysis, then label in a focused, keyboard-driven queue (Y/N, critique, Ctrl+Enter). Judge output is never shown there. Splits are 15/42.5/42.5, stratified by label and fixed when a trace is first labelled. A low-confidence badge appears when dev or test has fewer than 30 of either class.
- Dev loop: confusion matrix, TPR and TNR with Wilson intervals, raw agreement shown small with its trap-metric tooltip next to the always-pass score. The disagreement queue offers: add to failure criteria / add to not-a-failure (each makes a new version), promote to few-shot (train only, explained), correct my label (logged), edit the definition. Plus a version table (dev and test TPR/TNR per version).
- Final validation on the locked test split: every run is logged, repeat runs trigger a warning, and a dev-to-test gap over 10 points is flagged as likely overfitting. Status becomes **Validated** only when test TPR and TNR both meet the threshold (default 0.80, target 0.90, configurable per judge).

## Phase 6 — Run and measure, experiments, export ✅
- Run the active suite on any batch as a background job: a cost estimate first, a concurrency limit, and caching keyed on evaluator version × trace content hash.
- Report: failure rate per evaluator with a Wilson CI. For judges, the **corrected rate** θ = (p_obs + TNR − 1)/(TPR + TNR − 1) with a 2,000-iteration bootstrap CI using test-split TPR/TNR; it refuses when TPR + TNR ≤ 1. Also the pass-all rate and a breakdown by any facet.
- Compare two runs with per-evaluator deltas (▲ worse / ▼ better). Log an experiment with its hypothesis, change and result; the running count is shown.
- "Send flagged traces to review" builds a prioritised batch. Verdicts stay hidden until you save your own.
- Export zip: `EVAL_SPEC.md` (with the operating guidance), `failure_taxonomy.json`, `error_analysis.csv`, `judges/<slug>.md` (DRAFT banner if not validated), `checks/code_checks.py` (pytest), `datasets/<slug>_{train,dev,test}.jsonl`, `golden_regression.jsonl`, and a self-contained `run_evals.py` + `suite.json` + `evals_lib.py`.

## Phase 7 — Synthetic inputs, transition matrix, glossary, README ✅
- Synthetic generator: editable dimensions (feature/scenario/persona), a grounding field, and at least 20 hand-written tuples before AI unlocks. LLM call 1 proposes tuples (accept/reject); separate LLM call 2 writes the user messages. Export as JSONL/CSV, then import the resulting traces tagged synthetic with their tuple. A caution banner covers specialised domains.
- Transition failure matrix on Count: last successful tool step → first failing step, from first-failure marks, with clickable cells.
- Glossary page (top bar), plus tooltips on technical terms throughout.
- README covering setup, configuration, the workflow, importing your own traces, the bundle, and development.

## Hardening found during the build
- Background jobs pass plain ids to worker threads. This fixed a crash where judge runs touched objects from a closed request session. Tests now run jobs truly in the background and poll, so this class of bug is caught.
- SQLite busy timeout raised to 30s. Run progress keeps polling in background tabs.
- The database now lives in local app data (`%LOCALAPPDATA%\EvalsWorkbench`), not inside OneDrive, which slowed writes and risks corrupting a live SQLite file. The old file was migrated automatically.
- The e2e test's database lives in the system temp folder for the same reason. It passed 3 of 3 runs after the move.

**Final state:** 50 backend tests pass, the frontend typechecks and builds, and the Playwright keyboard-only review test passes.

**Definition-of-done coverage (mock mode):** steps 1–9 are exercised end to end by `test_runs_export.py` plus `test_evaluators.py`, ending with extracting the bundle and running `run_evals.py` successfully. Live-key runs have not been executed in this environment because there is no `ANTHROPIC_API_KEY`.
