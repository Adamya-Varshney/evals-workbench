from collections import Counter

from app.splits import assign_split


def simulate(n_pos: int, n_neg: int, fm: int = 1) -> dict[bool, Counter]:
    counts: dict[bool, Counter] = {True: Counter(), False: Counter()}
    tid = 0
    order = [True] * n_pos + [False] * n_neg
    # interleave like real labelling
    order.sort(key=lambda x: hash((x, len(order))) % 7)
    for label in order:
        tid += 1
        sp = assign_split(tid, fm, label, dict(counts[label]))
        counts[label][sp] += 1
    return counts


def test_split_proportions_are_stratified():
    c = simulate(100, 200)
    for label, total in ((True, 100), (False, 200)):
        assert sum(c[label].values()) == total
        assert 0.10 <= c[label]["train"] / total <= 0.20
        assert 0.40 <= c[label]["dev"] / total <= 0.45
        assert 0.40 <= c[label]["test"] / total <= 0.45


def test_split_small_counts_spread_across_dev_and_test():
    c = simulate(4, 4)
    assert c[True]["dev"] >= 1 and c[True]["test"] >= 1
    assert c[False]["dev"] >= 1 and c[False]["test"] >= 1


def test_split_is_deterministic():
    a = [assign_split(i, 3, i % 2 == 0, {}) for i in range(20)]
    b = [assign_split(i, 3, i % 2 == 0, {}) for i in range(20)]
    assert a == b
