import math

import pytest

from app import stats


def test_wilson_known_values():
    # Reference: 8/10 -> (0.4902, 0.9433) for the 95% Wilson interval.
    lo, hi = stats.wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3)
    assert hi == pytest.approx(0.9433, abs=1e-3)
    lo, hi = stats.wilson_interval(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    lo, hi = stats.wilson_interval(10, 10)
    assert hi == 1.0 and lo == pytest.approx(0.7225, abs=1e-3)
    assert stats.wilson_interval(0, 0) == (None, None)


def test_confusion_and_rates():
    human = [True, True, True, False, False, False, False]
    judge = [True, False, True, False, True, False, False]
    c = stats.confusion(human, judge)
    assert (c.tp, c.fn, c.tn, c.fp) == (2, 1, 3, 1)
    assert stats.tpr(c) == pytest.approx(2 / 3)
    assert stats.tnr(c) == pytest.approx(3 / 4)
    with pytest.raises(ValueError):
        stats.confusion([True], [True, False])


def test_raw_agreement_trap():
    # Failure occurs 10% of the time; a judge that always says "pass" scores 90% agreement but 0 TPR.
    human = [True] * 10 + [False] * 90
    judge = [False] * 100
    m = stats.judge_metrics(human, judge)
    assert m["agreement"] == pytest.approx(0.9)
    assert m["always_pass_agreement"] == pytest.approx(0.9)
    assert m["tpr"] == 0.0
    assert m["tnr"] == 1.0
    assert m["low_confidence"] is True  # only 10 positives


def test_low_confidence_flag():
    m = stats.judge_metrics([True] * 30 + [False] * 30, [True] * 30 + [False] * 30)
    assert m["low_confidence"] is False
    m = stats.judge_metrics([True] * 29 + [False] * 40, [True] * 29 + [False] * 40)
    assert m["low_confidence"] is True


def test_corrected_rate_formula_and_clipping():
    # theta = (p_obs + TNR - 1) / (TPR + TNR - 1)
    assert stats.corrected_rate(0.3, 0.9, 0.8) == pytest.approx((0.3 + 0.8 - 1) / (0.9 + 0.8 - 1))
    assert stats.corrected_rate(0.0, 0.9, 0.8) == 0.0  # would be negative -> clipped
    assert stats.corrected_rate(1.0, 0.6, 0.6) == 1.0  # would exceed 1 -> clipped
    with pytest.raises(stats.NoBetterThanChance):
        stats.corrected_rate(0.3, 0.5, 0.5)
    with pytest.raises(stats.NoBetterThanChance):
        stats.corrected_rate(0.3, 0.4, 0.5)


def test_perfect_judge_is_unchanged():
    human = [True] * 20 + [False] * 30
    r = stats.corrected_rate_with_ci([True] * 25 + [False] * 75, human, human, iterations=300)
    assert r["theta"] == pytest.approx(0.25)
    lo, hi = r["ci"]
    assert lo <= 0.25 <= hi


def test_bootstrap_ci_contains_estimate_and_is_deterministic():
    human = [True] * 30 + [False] * 70
    judge = [True] * 26 + [False] * 4 + [True] * 7 + [False] * 63  # TPR .867, TNR .9
    preds = [True] * 40 + [False] * 160
    r1 = stats.corrected_rate_with_ci(preds, human, judge, iterations=2000)
    r2 = stats.corrected_rate_with_ci(preds, human, judge, iterations=2000)
    assert r1 == r2
    expected = (0.2 + 0.9 - 1) / (26 / 30 + 0.9 - 1)
    assert r1["theta"] == pytest.approx(expected)
    lo, hi = r1["ci"]
    assert lo < r1["theta"] < hi
    assert 0 <= lo and hi <= 1
    assert r1["iterations"] == 2000


def test_bootstrap_refuses_chance_judge():
    human = [True] * 10 + [False] * 10
    judge = [True] * 5 + [False] * 5 + [True] * 5 + [False] * 5  # TPR .5, TNR .5
    with pytest.raises(stats.NoBetterThanChance):
        stats.corrected_rate_with_ci([True, False], human, judge)


def test_rate_with_ci():
    r = stats.rate_with_ci(5, 50)
    assert r["rate"] == 0.1 and r["n"] == 50
    assert not math.isnan(r["ci"][0])
