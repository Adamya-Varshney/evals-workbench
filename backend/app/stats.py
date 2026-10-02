"""Judge validation statistics.

Positive class = the human says the failure is present.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict
from typing import Optional, Sequence

Z95 = 1.959963984540054


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[Optional[float], Optional[float]]:
    """95% Wilson score interval for a binomial proportion. Returns (None, None) when n == 0."""
    if n <= 0:
        return (None, None)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return (lo, hi)


@dataclass
class Confusion:
    tp: int = 0
    fn: int = 0
    tn: int = 0
    fp: int = 0

    @property
    def n_pos(self) -> int:
        return self.tp + self.fn

    @property
    def n_neg(self) -> int:
        return self.tn + self.fp

    @property
    def n(self) -> int:
        return self.n_pos + self.n_neg


def confusion(human: Sequence[bool], judge: Sequence[bool]) -> Confusion:
    if len(human) != len(judge):
        raise ValueError("human and judge label lists must be the same length")
    c = Confusion()
    for h, j in zip(human, judge):
        if h and j:
            c.tp += 1
        elif h and not j:
            c.fn += 1
        elif not h and not j:
            c.tn += 1
        else:
            c.fp += 1
    return c


def tpr(c: Confusion) -> Optional[float]:
    return c.tp / c.n_pos if c.n_pos else None


def tnr(c: Confusion) -> Optional[float]:
    return c.tn / c.n_neg if c.n_neg else None


def judge_metrics(human: Sequence[bool], judge: Sequence[bool], low_confidence_min: int = 30) -> dict:
    """Everything the validation screens show for one split."""
    c = confusion(human, judge)
    t, n = tpr(c), tnr(c)
    agreement = (c.tp + c.tn) / c.n if c.n else None
    # What a judge that always says "pass" (never flags a failure) would score.
    always_pass_agreement = c.n_neg / c.n if c.n else None
    return {
        "confusion": asdict(c),
        "n": c.n,
        "n_pos": c.n_pos,
        "n_neg": c.n_neg,
        "tpr": t,
        "tpr_ci": wilson_interval(c.tp, c.n_pos),
        "tnr": n,
        "tnr_ci": wilson_interval(c.tn, c.n_neg),
        "agreement": agreement,
        "always_pass_agreement": always_pass_agreement,
        "low_confidence": c.n_pos < low_confidence_min or c.n_neg < low_confidence_min,
    }


class NoBetterThanChance(ValueError):
    pass


def corrected_rate(p_obs: float, tpr_: float, tnr_: float) -> float:
    """theta = (p_obs + TNR - 1) / (TPR + TNR - 1), clipped to [0, 1]."""
    denom = tpr_ + tnr_ - 1
    if denom <= 0:
        raise NoBetterThanChance(
            "TPR + TNR <= 1: the judge is no better than chance, so a corrected rate cannot be computed."
        )
    return min(1.0, max(0.0, (p_obs + tnr_ - 1) / denom))


def corrected_rate_with_ci(
    unlabelled_preds: Sequence[bool],
    test_human: Sequence[bool],
    test_judge: Sequence[bool],
    iterations: int = 2000,
    seed: int = 7,
) -> dict:
    """Corrected failure rate on unlabelled data with a 95% bootstrap interval.

    Each iteration resamples the test-set (human, judge) pairs to re-estimate TPR and TNR,
    and resamples the judge's predictions on the unlabelled data to re-estimate p_obs.
    """
    preds = [bool(p) for p in unlabelled_preds]
    if not preds:
        raise ValueError("no judge predictions to correct")
    p_obs = sum(preds) / len(preds)
    c = confusion(test_human, test_judge)
    t, n = tpr(c), tnr(c)
    if t is None or n is None:
        raise NoBetterThanChance("The test split needs at least one positive and one negative label.")
    theta = corrected_rate(p_obs, t, n)

    rng = random.Random(seed)
    pairs = list(zip(test_human, test_judge))
    m, k = len(pairs), len(preds)
    samples: list[float] = []
    skipped = 0
    for _ in range(iterations):
        rs = [pairs[rng.randrange(m)] for _ in range(m)]
        bc = confusion([h for h, _ in rs], [j for _, j in rs])
        bt, bn = tpr(bc), tnr(bc)
        bp = sum(preds[rng.randrange(k)] for _ in range(k)) / k
        if bt is None or bn is None or bt + bn <= 1:
            skipped += 1
            continue
        samples.append(corrected_rate(bp, bt, bn))
    samples.sort()
    lo = hi = None
    if samples:
        lo = _percentile(samples, 0.025)
        hi = _percentile(samples, 0.975)
    return {
        "p_obs": p_obs,
        "n_unlabelled": k,
        "theta": theta,
        "ci": (lo, hi),
        "tpr": t,
        "tnr": n,
        "n_test": m,
        "n_test_pos": c.n_pos,
        "n_test_neg": c.n_neg,
        "iterations": iterations,
        "skipped_iterations": skipped,
    }


def _percentile(sorted_vals: list[float], q: float) -> float:
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def rate_with_ci(k: int, n: int) -> dict:
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": (k / n if n else None), "ci": (lo, hi)}
