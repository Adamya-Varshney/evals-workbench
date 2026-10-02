"""Default prompt templates. Every one is stored in the DB and editable in Settings.

Placeholders use {{name}} and are filled by `render`.
"""
from __future__ import annotations

import re

from sqlmodel import Session, select

DEFAULTS: dict[str, tuple[str, str]] = {
    "propose_categories": (
        "Propose failure categories (axial coding)",
        """You are helping a product manager do error analysis on traces from an AI product.

Product: {{product_name}}
What it does: {{product_description}}

Below are the reviewer's open codes: free-text notes written while reading individual traces that FAILED.
Each note has an id.

<open_codes>
{{notes}}
</open_codes>

Group these open codes into axial codes: 5 to 6 failure modes that together cover the notes.
Rules:
- Each failure mode must be specific and actionable. A colleague should be able to label new traces using only its name and definition. Avoid vague names like "quality issues", "temporal issues", "capability", "general", "misc".
- Name the observable behaviour, not a guessed root cause.
- The definition is one sentence.
- List the ids of notes that are good examples of each mode.
- A note may describe several problems; it may appear under more than one mode.
- Do not invent failure modes that no note describes.""",
    ),
    "suggest_assignments": (
        "Suggest failure-mode assignments",
        """You are mapping a reviewer's free-text notes (open codes) onto an agreed failure taxonomy (axial codes).

<failure_modes>
{{failure_modes}}
</failure_modes>

<notes>
{{notes}}
</notes>

For each note, return the ids of every failure mode it describes. A note can describe several modes.
If a note describes a problem that no mode covers, return the id of "None of the above" ({{none_id}}).
Respect each mode's "counts as" and "does not count as" guidance. Give a short rationale per note.""",
    ),
    "draft_code_check": (
        "Draft a code check",
        """You are drafting a deterministic code check for one failure mode in an AI product.

Failure mode: {{name}}
Definition: {{definition}}
Counts as: {{counts_as}}
Does not count as: {{does_not_count_as}}

Example reviewer notes for this failure:
{{examples}}

Available rule types (JSON):
- {"type": "regex", "pattern": "...", "mode": "present"|"absent", "flags": "i"}   applied to assistant messages; "present" means a match is a FAILURE
- {"type": "markdown"}   failure if assistant messages contain markdown syntax
- {"type": "tool_called", "tool": "name", "expect": "called"|"not_called"}   failure when the expectation is violated
- {"type": "tool_count_max", "tool": "name", "max": N}   failure if the tool is called more than N times
- {"type": "tool_args_required", "tool": "name", "args": ["a", "b"]}   failure if a call to the tool lacks any of the args
- {"type": "length", "min": N|null, "max": N|null}   failure if any assistant message length is outside the limits
- {"type": "json_schema", "schema": {...}}   failure if the last assistant message is not valid JSON for the schema
Each rule may have "scope": {"facet": "channel", "values": ["sms"]} to apply only to some traces.

Propose the smallest set of rules that catches this failure. If the failure cannot be caught with an if/else on the trace, say so in the explanation and return no rules.""",
    ),
    "draft_judge": (
        "Draft an LLM judge prompt",
        """You are drafting an LLM-as-judge prompt that detects exactly ONE failure mode in an AI product.

Product: {{product_name}} — {{product_description}}
Things the business knows that the model may not:
{{business_facts}}

Failure mode: {{name}}
Definition: {{definition}}
Counts as: {{counts_as}}
Does not count as: {{does_not_count_as}}

Reviewer notes (human critiques) for traces with this failure:
{{examples}}

Write:
1. failure_when: an enumerated list of concrete, observable conditions under which the failure occurs.
2. not_failure_when: an enumerated list of situations that look similar but are NOT this failure, to prevent false alarms.
Keep each item to one line. Be concrete about the trace evidence a judge should look for.""",
    ),
    "run_judge": (
        "Judge prompt wrapper",
        """You are evaluating one trace from an AI product for exactly one failure mode.

Failure mode: {{name}}

The failure occurs when:
{{failure_when}}

It is NOT a failure when:
{{not_failure_when}}
{{few_shot}}
<trace>
{{trace}}
</trace>

First write a short critique explaining what the trace shows with respect to this failure mode. Then give the verdict: failure = true if the failure is present, false otherwise.""",
    ),
    "synthetic_tuples": (
        "Propose synthetic tuples",
        """You are helping create varied test inputs for an AI product.

Product: {{product_name}} — {{product_description}}
Grounding (real constraints and sample records):
{{grounding}}

Dimensions and example values:
{{dimensions}}

Here are tuples the product manager wrote by hand:
{{tuples}}

Propose {{count}} NEW tuples. Each tuple picks one value per dimension. Cover combinations the hand-written tuples miss, especially ones likely to stress the system. You may introduce new values for a dimension when it improves coverage. Do not repeat existing tuples.""",
    ),
    "synthetic_inputs": (
        "Turn tuples into user messages",
        """You write realistic first messages that a real user would send to this product.

Product: {{product_name}} — {{product_description}}
Channel conventions: {{channels}}
Grounding (use these real IDs, dates and rules so the message triggers the intended scenario):
{{grounding}}

For each tuple below, write one natural user message that fits the tuple. Vary length, tone and polish the way real users do: some terse, some with typos, some long. Write only the user's message, never an expected answer.

{{tuples}}""",
    ),
    "find_similar": (
        "Find similar traces",
        """You help a reviewer find traces similar to one they are looking at.

<reference_trace>
{{reference}}
</reference_trace>

<candidates>
{{candidates}}
</candidates>

Return the ids of up to {{k}} candidates most similar to the reference in what the user wanted and how the assistant behaved, most similar first, with a few words on why.""",
    ),
}


def ensure_templates(s: Session) -> None:
    from ..models import PromptTemplate

    existing = {t.key: t for t in s.exec(select(PromptTemplate)).all()}
    for key, (title, body) in DEFAULTS.items():
        if key not in existing:
            s.add(PromptTemplate(key=key, title=title, body=body, default_body=body))
        else:
            t = existing[key]
            if t.default_body != body:
                # Keep the user's edits; refresh the stored default so "reset" uses the latest.
                if t.body == t.default_body:
                    t.body = body
                t.default_body = body
                s.add(t)
    s.commit()


def get_template(s: Session, key: str) -> str:
    from ..models import PromptTemplate

    t = s.exec(select(PromptTemplate).where(PromptTemplate.key == key)).first()
    return t.body if t else DEFAULTS[key][1]


_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render(body: str, **vars: object) -> str:
    return _VAR.sub(lambda m: str(vars.get(m.group(1), "")), body)
