# Evals Workbench

A local, single-user web app that walks a product manager through **error-analysis-first evals**. It starts from raw traces of an AI system and ends with a small, validated eval suite you can export to CI and production monitoring.

The method follows Hamel Husain and Shreya Shankar's approach. Look at real traces, write down what goes wrong, count it, and build evaluators **only** for the failures you actually observed. Each evaluator is the cheapest one that works, and it is validated against your own labels before anyone trusts it.

> There are no ready-made "helpfulness" or "coherence" metrics in this tool, on purpose. They don't catch product-specific failures like markdown in a text message or an in-person tour booked as "virtual".

---

## Setup

Requirements: **Python 3.11+** and **Node 20+**.

```bash
python dev.py setup     # creates backend/.venv, installs Python + npm deps, writes .env (mock mode)
python dev.py dev       # API on :8000, UI on http://127.0.0.1:5173
```

If you have `make`, `make setup` and `make dev` do the same thing.

### Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | empty | Needed for live AI assist (proposals, suggestions, drafting, judges, similar traces, synthetic inputs). |
| `LLM_MODE` | `mock` | `mock` returns deterministic canned responses, so the app and tests run without a key. Use `live` to call Claude. |
| `EVALS_MODEL` | `claude-sonnet-5-5` | The model for every AI call. Judges store their own model per version. |
| `EVALS_LLM_CONCURRENCY` | `4` | Maximum number of simultaneous Claude calls. |
| `EVALS_FALLBACKS` | `1` | Claude API server-side refusal fallback (on by default). |
| `EVALS_DB` | `%LOCALAPPDATA%\EvalsWorkbench\evals_workbench.db` (Windows) or `~/.local/share/evals-workbench/` | SQLite location. Kept out of synced folders like OneDrive on purpose. |

**Privacy:** trace content is sent to the Anthropic API only when an AI-assist feature runs. Nothing is sent while you import or review. You can turn AI assist off globally (Get traces → AI assist switch, or Settings). Every call is logged in the **AI activity** drawer with its prompt, response, tokens and cost, and every prompt template can be edited in **Settings**.

---

## The workflow

The left sidebar shows ten stages, each with its status and what to do next. The Overview page shows the single next-best action.

1. **Set up the project.** Describe the product, its channels (each with a render rule such as "SMS is plain text"), the system prompt versions under test, your reviewer name, and the *things you know that the model does not*.
2. **Get traces.** Import JSONL, JSON or CSV, map fields with a live preview, optionally redact, read the import report, then build a review batch (random, stratified, outliers, negative feedback, or evaluator-flagged; always at least 20% random). No traces yet? Use the **synthetic input generator**.
3. **Review traces** *(open coding)*. Each trace is shown the way the user saw it: SMS as phone bubbles, email as an email, voice as a transcript. Mark Pass or Fail with one key, write what you see, mark the first failing turn, and move on. Everything works from the keyboard (press `?`). A saturation indicator tells you when new kinds of problem stop appearing.
4. **Group failures** *(axial coding)*. Turn your notes into 5–8 specific failure modes, each with a definition plus "counts as" and "does not count as". AI can propose categories and suggest assignments (it unlocks after 30 hand reviews), but you confirm every suggestion yourself.
5. **Count and prioritise.** A pivot table by failure mode and any facet, showing both denominators, with drill-down into every cell, a frequency chart, and a transition matrix for agentic traces. You set severity and order. There is no computed priority score.
6. **Decide what each failure needs**: Fix now, Code check, LLM judge, or Park. The fix log shows before and after rates once the next batch is reviewed.
7. **Build evaluators.** Code checks come from a rule builder (or a sandboxed `check(trace)` in Python). LLM judges get a three-part prompt, a context selector and train-only few-shot examples. AI can draft either; you approve every version.
8. **Validate judges.** Label in a focused queue, with train/dev/test splits fixed at the moment a trace is first labelled. Iterate on dev using TPR, TNR, Wilson intervals and a disagreement queue, then run final validation once on the locked test split.
9. **Run and measure.** Run the active suite on any batch, with a cost estimate first and cached results. You get raw and **corrected** judge failure rates with bootstrap intervals, the pass-all rate, facet breakdowns, batch comparisons, and an experiment log.
10. **Export and operate.** Download a zip containing `EVAL_SPEC.md`, the taxonomy, the error-analysis CSV, judge cards, pytest code checks, datasets, a golden regression set and `run_evals.py`.

A **Glossary** (top bar) maps every plain-language label to its technical term.

### Try it on the demo

Click **Open demo project** to load Larkspur Residences, an invented apartment-leasing assistant on SMS, email, chat and voice. It has 120 messy traces, about 58% of them clean. Several failure types are planted in the rest, and the point is that you find them by reading. The answer key exists only in the test fixtures.

---

## Importing your own traces

Get traces → **Choose a file**. The importer reads:

- **JSONL**: one record per line.
- **JSON**: a list, or an object holding a list under `data`, `traces`, `records`, `rows` or `items`.
- **CSV**: either `input` / `output` columns, or a column whose value is a JSON message array.

Message formats:

- **OpenAI style:** `{"role": "user"|"assistant"|"system"|"tool", "content": ..., "tool_calls": [...]}`
- **Anthropic style:** content blocks `text`, `tool_use`, `tool_result`
- **LangChain-ish roles:** `human` / `ai`, including nested paths such as `inputs.messages`

The mapping screen guesses which field is the conversation, the ID, the system prompt, the channel and the prompt version. Override anything with the dropdowns (dotted paths into nested objects work) and watch three traces render exactly as the review screen will show them. Every field you don't map becomes a filterable **metadata facet** (channel, property, user feedback, latency…).

Missing fields never block an import. Bad lines, empty conversations and duplicates are skipped and listed with reasons in the import report.

Exports from Braintrust, LangSmith, Arize Phoenix and hand-rolled logs generally fit one of these shapes. If yours doesn't, flatten it to JSONL with a `messages` array per record.

### Synthetic inputs

Get traces → *synthetic input generator*:

1. Define dimensions (feature, scenario, persona) and write at least 20 tuples by hand.
2. AI proposes more tuples. You accept or reject each one.
3. A separate AI call writes a natural user message per tuple. Inputs only, never expected outputs.
4. Export the inputs as JSONL or CSV, run them through your real system, then import the resulting traces with "tag them as synthetic". Keep the `tuple` field on each record.

---

## The export bundle

```bash
python run_evals.py                          # golden set, code checks
python run_evals.py outputs.jsonl --judges   # + LLM judges (needs ANTHROPIC_API_KEY and `pip install anthropic`)
EVAL_TRACES=outputs.jsonl pytest checks/     # code checks as CI assertions
```

Traces in the bundle use a normalised format:

```
{id, channel, meta, system_prompt, events: [{role, content, tool_name, tool_args, tool_result}]}
```

Judges that have not passed final validation are exported with a **DRAFT** banner.

---

## Development

```bash
python dev.py test     # backend pytest + frontend typecheck
python dev.py e2e      # Playwright: a full review session using only the keyboard
python dev.py seed     # regenerate the demo traces (deterministic)
python dev.py serve    # build the UI and serve everything from FastAPI on :8000
```

- **Backend** (`backend/app`): FastAPI, SQLite via SQLModel, in-process background jobs.
  - `stats.py`: Wilson intervals, TPR/TNR, corrected rate, bootstrap.
  - `splits.py`: stratified, fixed split assignment.
  - `checks.py`: the code-check engine, shipped verbatim in the export.
  - `llm/client.py`: the single Claude gateway (structured outputs, retries, concurrency, logging, mock mode).
- **Frontend** (`frontend/src`): React, TypeScript, Vite, Tailwind, TanStack Query, Recharts. The light theme is the default; ☾ in the top bar switches to dark.
- **Tests:** statistics, splits, importers, the check engine, review, grouping and counting, evaluators and validation, suite runs and export (including running the exported `run_evals.py`), synthetic inputs, and the transition matrix. All of them run in mock mode.

Not included, by design: calling the AI system under test, live vendor integrations, automated prompt optimisation, multi-user accounts, and generic or RAG metrics. Retrieval metrics would plug in as a new evaluator `type` next to `code` and `judge`.
