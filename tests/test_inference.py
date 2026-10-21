import math
import random

import pytest

from taskwitness.inference import (
    conformal_upper,
    min_scores_needed,
    ppi_finite_sample,
    sequential_paired_test,
    wsr_interval,
)


# ----------------------------------------------------------------------------- sequential test


def test_sequential_rejects_a_clear_difference_early():
    result = sequential_paired_test([1] * 12)
    assert result["rejected"] and result["stopped_at_pair"] <= 10
    assert result["anytime_p"] < 0.05


def test_sequential_does_not_reject_a_few_one_sided_pairs():
    # Four discordant pairs, all favouring B: a fixed-sample exact test gives p = 0.0625.
    result = sequential_paired_test([1, 1, 1, 1])
    assert not result["rejected"]
    assert result["anytime_p"] > 0.0625  # the anytime-valid p-value is more conservative


def test_sequential_stays_flat_when_nothing_happens():
    result = sequential_paired_test([])
    assert result["e_value"] == 1.0 and result["anytime_p"] == 1.0 and not result["rejected"]
    mixed = sequential_paired_test([1, 0] * 20)
    assert not mixed["rejected"]


def test_sequential_type_one_error_holds_under_optional_stopping():
    """Under H0, peeking after every pair and stopping at the first rejection must still be rare."""
    rng = random.Random(2026)
    sims, rejections = 3000, 0
    for _ in range(sims):
        outcomes = [rng.random() < 0.5 for _ in range(100)]
        rejections += sequential_paired_test([int(x) for x in outcomes], alpha=0.05)["rejected"]
    # Guarantee: <= 5%. Allow 3 standard errors of simulation noise on top.
    assert rejections / sims <= 0.05 + 3 * math.sqrt(0.05 * 0.95 / sims)


def test_sequential_has_power_against_a_real_effect():
    rng = random.Random(7)
    stops = []
    for _ in range(200):
        outcomes = [int(rng.random() < 0.85) for _ in range(60)]
        result = sequential_paired_test(outcomes)
        stops.append(result["stopped_at_pair"])
    assert sum(s is not None for s in stops) / len(stops) > 0.95
    assert sorted(s for s in stops if s)[len(stops) // 2] <= 15  # typically decides within ~15 discordant pairs


def test_sequential_rejects_bad_input():
    with pytest.raises(ValueError):
        sequential_paired_test([0, 2])
    with pytest.raises(ValueError):
        sequential_paired_test([1], alpha=1.5)


# ----------------------------------------------------------------------------- WSR interval


@pytest.mark.parametrize("p", [0.05, 0.5, 0.9])
def test_wsr_interval_covers_at_small_n(p):
    rng = random.Random(int(p * 100))
    sims, misses = 250, 0
    for _ in range(sims):
        xs = [float(rng.random() < p) for _ in range(40)]
        lo, hi = wsr_interval(xs, alpha=0.05, grid=200)
        misses += not (lo <= p <= hi)
    assert misses / sims <= 0.05 + 3 * math.sqrt(0.05 * 0.95 / sims)


def test_wsr_interval_is_informative_and_shrinks():
    rng = random.Random(3)
    xs = [float(rng.random() < 0.5) for _ in range(400)]
    small = wsr_interval(xs[:50], grid=200)
    large = wsr_interval(xs, grid=200)
    assert large[1] - large[0] < small[1] - small[0] < 1.0
    assert large[1] - large[0] < 0.25
    assert large[0] < 0.5 < large[1]


def test_wsr_interval_edge_cases():
    assert wsr_interval([]) == [0.0, 1.0]
    lo, hi = wsr_interval([0.0] * 60, grid=200)
    assert lo == 0.0 and hi < 0.2  # all zeros: the upper end shrinks, the lower stays at 0
    lo, hi = wsr_interval([1.0] * 60, grid=200)
    assert hi == 1.0 and lo > 0.8
    lo, hi = wsr_interval([-1.0, 1.0, 0.0, 1.0] * 20, low=-1.0, high=1.0, grid=200)
    assert -1.0 <= lo < 0.5 < hi <= 1.0
    with pytest.raises(ValueError):
        wsr_interval([1.5])


# ----------------------------------------------------------------------------- finite-sample PPI


def _ppi_trial(rng, total, labeled_n, false_pass, rate=0.6, grid=200):
    truth = [rng.random() < rate for _ in range(total)]
    pred = [1.0 if t or rng.random() < false_pass else 0.0 for t in truth]
    labeled = sorted(rng.sample(range(total), labeled_n))
    chosen = set(labeled)
    ppi = ppi_finite_sample(
        [pred[i] for i in range(total) if i not in chosen],
        [pred[i] for i in labeled],
        [float(truth[i]) for i in labeled],
        grid=grid,
    )["ci"]
    only = wsr_interval([float(truth[i]) for i in labeled], grid=grid)
    return sum(truth) / total, ppi, only


def test_ppi_finite_sample_covers():
    rng = random.Random(11)
    sims, misses = 80, 0
    for _ in range(sims):
        true_mean, (lo, hi), _ = _ppi_trial(rng, 400, 40, false_pass=0.1)
        misses += not (lo <= true_mean <= hi)
    assert misses / sims <= 0.05 + 3 * math.sqrt(0.05 * 0.95 / sims)


def test_ppi_finite_sample_helps_only_with_an_accurate_judge_and_many_episodes():
    rng = random.Random(21)
    # Favourable: thousands of episodes and a judge that is almost always right.
    widths = [_ppi_trial(rng, 4000, 150, false_pass=0.01) for _ in range(4)]
    assert sum(p[1] - p[0] for _, p, _ in widths) < sum(o[1] - o[0] for _, _, o in widths)
    # Documented limitation: at the size of a small lab experiment with a noisy judge,
    # the labels alone give the narrower valid interval.
    small = [_ppi_trial(rng, 400, 40, false_pass=0.1) for _ in range(4)]
    assert sum(p[1] - p[0] for _, p, _ in small) > sum(o[1] - o[0] for _, _, o in small)


def test_ppi_finite_sample_needs_data():
    with pytest.raises(ValueError):
        ppi_finite_sample([0.5], [0.5, 0.5], [1.0, 0.0])


# ----------------------------------------------------------------------------- conformal


def test_conformal_upper_order_statistic_and_minimum_size():
    assert conformal_upper(list(range(1, 20)), 0.05) == 19  # n = 19: k = ceil(20 * 0.95) = 19
    assert conformal_upper(list(range(1, 19)), 0.05) is None  # n = 18: not enough scores for alpha = 0.05
    assert min_scores_needed(0.05) == 19
    assert conformal_upper([5.0, 1.0, 3.0], 0.5) == 3.0
    with pytest.raises(ValueError):
        conformal_upper([1.0], 0.0)


def test_conformal_upper_has_marginal_coverage():
    rng = random.Random(5)
    reps, covered = 4000, 0
    for _ in range(reps):
        calibration = [abs(rng.gauss(0, 1)) for _ in range(39)]  # k = ceil(40 * 0.95) = 38 of 39
        bound = conformal_upper(calibration, 0.05)
        covered += abs(rng.gauss(0, 1)) <= bound
    assert covered / reps == pytest.approx(0.95, abs=0.012)
