"""Finite-sample and anytime-valid inference. Pure Python, no dependencies.

Three tools, each answering a question a small real experiment actually has:

`sequential_paired_test`
    "Does judge B make fewer false passes than judge A?" asked as episodes
    arrive, with the freedom to stop as soon as the evidence is strong. A betting
    e-process on the discordant pairs (episodes where exactly one judge falsely
    passes); by Ville's inequality the type-I error stays below `alpha` no matter
    when you look or stop. This is in the spirit of STEP (arXiv 2503.10966) and
    N-SCORE (arXiv 2603.13616) but is a simpler, self-contained test for paired
    binary outcomes, not a reimplementation of either.

`wsr_interval`
    A confidence interval for a mean in [a, b] that is valid at every sample
    size (no normal approximation), from the hedged betting construction of
    Waudby-Smith & Ramdas (arXiv 2010.09686). Conservative, but honest at n = 30.

`ppi_finite_sample`
    Prediction-powered inference (arXiv 2301.09633) with finite-sample bounds, as
    in SureSim (arXiv 2510.04354): a bound on the mean prediction over all
    episodes plus a bound on the mean rectifier (label - prediction) on the
    labeled subset, combined by a union bound.

`conformal_upper`
    Split-conformal upper quantile: a new known-good score exceeds it with
    probability at most `alpha`, under exchangeability.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

LAMBDAS = tuple(round(0.1 * k, 1) for k in range(1, 10))


def sequential_paired_test(outcomes: Sequence[int], alpha: float = 0.05) -> dict[str, Any]:
    """Anytime-valid test that outcome 1 is more likely than outcome 0.

    `outcomes` are the discordant pairs in a pre-specified order: 1 when judge A
    erred and B did not, 0 when B erred and A did not. Under H0 (equally likely)
    the product of (1 + lambda * (2x - 1)) is a nonnegative martingale for every
    fixed lambda in (0, 1); the average over a grid of lambdas is one too. The
    anytime p-value is 1 / max_k E_k, valid at any stopping time.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    if any(x not in (0, 1) for x in outcomes):
        raise ValueError("outcomes must be 0 or 1")
    log_wealth = [0.0] * len(LAMBDAS)
    best = 1.0
    stopped_at = None
    path = []
    for n, x in enumerate(outcomes, start=1):
        sign = 1.0 if x == 1 else -1.0
        log_wealth = [w + math.log1p(lam * sign) for w, lam in zip(log_wealth, LAMBDAS)]
        peak = max(log_wealth)
        e = math.exp(peak) * sum(math.exp(w - peak) for w in log_wealth) / len(LAMBDAS)
        best = max(best, e)
        path.append(e)
        if stopped_at is None and e >= 1 / alpha:
            stopped_at = n
    return {
        "discordant_pairs": len(outcomes),
        "a_only_errors": int(sum(outcomes)),
        "b_only_errors": len(outcomes) - int(sum(outcomes)),
        "e_value": round(path[-1], 6) if path else 1.0,
        "max_e_value": round(best, 6),
        "anytime_p": round(min(1.0, 1 / best), 6),
        "alpha": alpha,
        "rejected": stopped_at is not None,
        "stopped_at_pair": stopped_at,
    }


def _prpl_lambdas(xs: Sequence[float], alpha: float) -> list[float]:
    """Predictable plug-in bets (empirical-Bernstein style), computed before seeing each x_t."""
    out, total, total_sq_dev = [], 0.0, 0.0
    mu_hat, sigma_sq = 0.5, 0.25
    for t, x in enumerate(xs, start=1):
        out.append(min(math.sqrt(2 * math.log(2 / alpha) / (sigma_sq * t * math.log(1 + t))), 1.0))
        total += x
        mu_prev = mu_hat
        mu_hat = (0.5 + total) / (t + 1)
        total_sq_dev += (x - mu_prev) ** 2
        sigma_sq = (0.25 + total_sq_dev) / (t + 1)
    return out


def wsr_interval(xs: Sequence[float], alpha: float = 0.05, low: float = 0.0, high: float = 1.0, grid: int = 1000) -> list[float]:
    """Finite-sample (1 - alpha) confidence interval for the mean of values in [low, high]."""
    if not 0 < alpha < 1 or high <= low or grid < 10:
        raise ValueError("need 0 < alpha < 1, high > low and grid >= 10")
    if any(not low <= x <= high for x in xs):
        raise ValueError(f"values must lie in [{low}, {high}]")
    if len(xs) == 0:
        return [low, high]
    scaled = [(x - low) / (high - low) for x in xs]
    lams = _prpl_lambdas(scaled, alpha)
    threshold = math.log(2 / alpha)  # hedged capital with theta = 1/2 on each side
    c = 0.5
    accepted = []
    for i in range(grid + 1):
        m = i / grid
        up = down = 0.0
        for x, lam in zip(scaled, lams):
            up += math.log1p(min(lam, c / m if m > 0 else lam) * (x - m))
            down += math.log1p(-min(lam, c / (1 - m) if m < 1 else lam) * (x - m))
        if max(up, down) < threshold:
            accepted.append(m)
    if not accepted:  # cannot happen at the true mean except through grid error: fall back to no claim
        return [low, high]
    step = 1 / grid
    lo, hi = max(0.0, accepted[0] - step), min(1.0, accepted[-1] + step)
    return [round(low + lo * (high - low), 6), round(low + hi * (high - low), 6)]


def ppi_finite_sample(
    predictions_unlabeled: Sequence[float], predictions_labeled: Sequence[float], labels: Sequence[float], alpha: float = 0.05, grid: int = 400
) -> dict[str, Any]:
    """Finite-sample prediction-powered interval for a mean of [0, 1] outcomes.

    Valid when the labeled episodes are a uniformly random sample of all episodes.
    The alpha is split evenly between the two bounds (union bound), so this is
    wider than the asymptotic interval; that is the price of validity at small n.
    """
    n, big_n = len(labels), len(predictions_unlabeled)
    if n < 2 or big_n < 2 or len(predictions_labeled) != n:
        raise ValueError("need at least 2 labeled and 2 unlabeled episodes")
    pred_lo, pred_hi = wsr_interval(predictions_unlabeled, alpha / 2, 0.0, 1.0, grid)
    rect_lo, rect_hi = wsr_interval([y - f for y, f in zip(labels, predictions_labeled)], alpha / 2, -1.0, 1.0, grid)
    return {
        "ci": [round(max(0.0, pred_lo + rect_lo), 6), round(min(1.0, pred_hi + rect_hi), 6)],
        "prediction_mean_ci": [pred_lo, pred_hi],
        "rectifier_ci": [rect_lo, rect_hi],
        "labeled": n,
        "unlabeled": big_n,
        "alpha": alpha,
    }


def conformal_upper(scores: Sequence[float], alpha: float = 0.05) -> float | None:
    """Split-conformal upper bound: P(new score > bound) <= alpha if scores are exchangeable.

    Returns None when there are too few scores: at least 1/alpha - 1 are needed.
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    n = len(scores)
    k = math.ceil((n + 1) * (1 - alpha))
    if k > n:
        return None
    return sorted(scores)[k - 1]


def min_scores_needed(alpha: float) -> int:
    return math.ceil(1 / alpha) - 1
