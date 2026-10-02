"""Train/dev/test split assignment for judge ground truth.

Assignment is made once, when a trace is first labelled for a failure mode, and never changes.
Stratified by label: each new label goes to whichever split is furthest below its target share
for that label class, with a deterministic tie-break, so the splits stay balanced as labels arrive.
"""
from __future__ import annotations

import hashlib

TARGETS = {"train": 0.15, "dev": 0.425, "test": 0.425}
ORDER = ("dev", "test", "train")


def assign_split(trace_id: int, failure_mode_id: int, label: bool, current_counts: dict[str, int]) -> str:
    """Pick the split for a newly labelled trace.

    `current_counts` holds how many labels of the *same class* (same failure mode, same label)
    already sit in each split.
    """
    total = sum(current_counts.get(s, 0) for s in TARGETS) + 1
    deficits = {s: TARGETS[s] * total - current_counts.get(s, 0) for s in TARGETS}
    best = max(deficits.values())
    candidates = [s for s in ORDER if abs(deficits[s] - best) < 1e-9]
    if len(candidates) == 1:
        return candidates[0]
    # Deterministic tie-break from the ids so re-running gives the same answer.
    h = int(hashlib.sha256(f"{trace_id}:{failure_mode_id}:{label}".encode()).hexdigest(), 16)
    return candidates[h % len(candidates)]
