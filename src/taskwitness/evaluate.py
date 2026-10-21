"""Statistics for judging the judges. Pure Python.

`evaluate`  Compare TaskWitness and a vision-only judge against human labels:
            false-pass / false-fail rates with Wilson intervals, an exact McNemar
            test on paired false passes, and - following "When Better Policies
            Leave Harder Failures" (arXiv 2610.24801) - absolute misses,
            conditional misses and audit coverage, optionally per stratum.
`audit`     The same questions for any external judge (a VLM, Robometer,
            TOPReward, ...) given per-episode scores or verdicts, plus success
            bias, ROC-AUC and calibration error. FailBench (arXiv 2609.03611)
            reports a systematic bias toward "success" under ambiguous evidence;
            `pass_rate_bias` measures exactly that.
`estimate`  Prediction-powered inference (Angelopoulos et al., arXiv 2301.09633):
            combine cheap TaskWitness verdicts on every episode with human labels
            on a random subset to estimate the true success rate with a valid
            confidence interval.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from taskwitness.core import FAIL, PASS, UNKNOWN

DECISIVE = (PASS, FAIL)


def wilson(k: int, n: int, confidence: float = 0.95) -> list[float] | None:
    """Wilson score interval for a binomial proportion k/n."""
    if n == 0:
        return None
    z = statistics.NormalDist().inv_cdf(0.5 + confidence / 2)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 6), round(min(1.0, centre + half), 6)]


def _binom_tail_ge(k: int, n: int) -> float:
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2**n


def mcnemar_exact(b: int, c: int) -> dict[str, Any]:
    """Exact McNemar test on discordant pairs.

    b: cases where judge A erred and judge B did not; c: the reverse.
    `p_one_sided` tests "B errs less often than A".
    """
    n = b + c
    if n == 0:
        return {"a_only": b, "b_only": c, "p_one_sided": 1.0, "p_two_sided": 1.0}
    p_one = _binom_tail_ge(b, n)
    p_two = min(1.0, 2 * min(p_one, _binom_tail_ge(c, n)))
    # Significant figures, not decimals: rounding would turn tiny p-values into 0.
    return {"a_only": b, "b_only": c, "p_one_sided": float(f"{p_one:.6g}"), "p_two_sided": float(f"{p_two:.6g}")}


def _rate(k: int, n: int) -> dict[str, Any]:
    return {"count": k, "of": n, "rate": round(k / n, 6) if n else None, "ci95": wilson(k, n)}


@dataclass
class Row:
    episode_id: str
    label: str | None
    verdicts: dict[str, str]  # judge name -> PASS/FAIL/UNKNOWN
    stratum: str = "(all)"


def judge_metrics(rows: list[Row], judge: str) -> dict[str, Any]:
    labeled = [r for r in rows if r.label in DECISIVE and judge in r.verdicts]
    true_fail = [r for r in labeled if r.label == FAIL]
    true_pass = [r for r in labeled if r.label == PASS]
    false_pass = sum(r.verdicts[judge] == PASS for r in true_fail)
    false_fail = sum(r.verdicts[judge] == FAIL for r in true_pass)
    unknown = sum(r.verdicts[judge] == UNKNOWN for r in labeled)
    decided = [r for r in labeled if r.verdicts[judge] in DECISIVE]
    correct = sum(r.verdicts[judge] == r.label for r in decided)
    said_pass = [r for r in labeled if r.verdicts[judge] == PASS]
    return {
        "labeled_episodes": len(labeled),
        "absolute_miss": _rate(false_pass, len(labeled)),
        "conditional_miss": _rate(false_pass, len(true_fail)),
        "false_fail": _rate(false_fail, len(true_pass)),
        "unknown": _rate(unknown, len(labeled)),
        "accuracy_on_decided": _rate(correct, len(decided)),
        "pass_precision": _rate(sum(r.label == PASS for r in said_pass), len(said_pass)),
    }


def paired_false_pass(rows: list[Row], a: str, b: str) -> dict[str, Any]:
    """McNemar on false passes among label-FAIL episodes judged by both a and b."""
    fails = [r for r in rows if r.label == FAIL and a in r.verdicts and b in r.verdicts]
    a_only = sum(r.verdicts[a] == PASS and r.verdicts[b] != PASS for r in fails)
    b_only = sum(r.verdicts[b] == PASS and r.verdicts[a] != PASS for r in fails)
    result = mcnemar_exact(a_only, b_only)
    result = {f"{a}_only": result.pop("a_only"), f"{b}_only": result.pop("b_only"), **result}
    result["hypothesis"] = f"{b} has fewer false passes than {a}"
    return result


def summarize(rows: list[Row], judges: list[str], compare: tuple[str, str] | None = None) -> dict[str, Any]:
    labels = [r.label for r in rows]
    report: dict[str, Any] = {
        "episodes": len(rows),
        "audit_coverage": _rate(sum(lab in DECISIVE for lab in labels), len(rows)),
        "labeled_unknown": sum(lab == UNKNOWN for lab in labels),
        "judges": {j: judge_metrics(rows, j) for j in judges},
    }
    if compare:
        report["paired_false_pass"] = paired_false_pass(rows, *compare)
    strata: dict[str, list[Row]] = defaultdict(list)
    for r in rows:
        strata[r.stratum].append(r)
    if len(strata) > 1 or "(all)" not in strata:
        report["by_stratum"] = {
            name: {
                "episodes": len(group),
                "audit_coverage": _rate(sum(r.label in DECISIVE for r in group), len(group)),
                **{j: {k: judge_metrics(group, j)[k] for k in ("absolute_miss", "conditional_miss", "unknown")} for j in judges},
            }
            for name, group in sorted(strata.items())
        }
    return report


# ----------------------------------------------------------------------------- external judges


def roc_auc(scores: list[float], positives: list[bool]) -> float | None:
    """Probability a random positive outscores a random negative (ties count half)."""
    pos = [s for s, p in zip(scores, positives) if p]
    neg = [s for s, p in zip(scores, positives) if not p]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 6)


def expected_calibration_error(scores: list[float], positives: list[bool], bins: int = 10) -> float | None:
    if not scores:
        return None
    buckets: dict[int, list[tuple[float, bool]]] = defaultdict(list)
    for s, p in zip(scores, positives):
        buckets[min(int(s * bins), bins - 1)].append((s, p))
    ece = sum(len(b) / len(scores) * abs(statistics.fmean(s for s, _ in b) - statistics.fmean(p for _, p in b)) for b in buckets.values())
    return round(ece, 6)


def judge_audit(
    judgements: dict[str, Any], reference: dict[str, str], threshold: float = 0.5, strata: dict[str, str] | None = None
) -> dict[str, Any]:
    """Audit an external judge against reference outcomes (PASS/FAIL per episode).

    `judgements` maps episode id to a score in [0, 1] or a PASS/FAIL/UNKNOWN verdict.
    """
    matched = sorted(set(judgements) & set(reference))
    numeric = [e for e in matched if not isinstance(judgements[e], str)]
    rows, scores, positives = [], [], []
    for e in matched:
        j = judgements[e]
        if isinstance(j, str):
            verdict = j
        else:
            verdict = PASS if j >= threshold else FAIL
            scores.append(float(j))
            positives.append(reference[e] == PASS)
        rows.append(Row(e, reference[e], {"judge": verdict}, (strata or {}).get(e, "(all)")))

    metrics = summarize(rows, ["judge"])
    m = metrics["judges"]["judge"]
    fpr = m["conditional_miss"]["rate"]
    fnr = m["false_fail"]["rate"]
    predicted_pass = sum(r.verdicts["judge"] == PASS for r in rows)
    actual_pass = sum(r.label == PASS for r in rows)
    return {
        "matched_episodes": len(matched),
        "judge_only": len(set(judgements) - set(reference)),
        "reference_only": len(set(reference) - set(judgements)),
        "threshold": threshold if numeric else None,
        "balanced_accuracy": round(1 - (fpr + fnr) / 2, 6) if fpr is not None and fnr is not None else None,
        "pass_rate_bias": round((predicted_pass - actual_pass) / len(rows), 6) if rows else None,
        "roc_auc": roc_auc(scores, positives) if len(scores) == len(matched) else None,
        "expected_calibration_error": expected_calibration_error(scores, positives) if len(scores) == len(matched) else None,
        **{k: v for k, v in metrics.items() if k != "episodes"},
    }


# ----------------------------------------------------------------------------- PPI


def ppi_mean(
    predictions_unlabeled: list[float],
    predictions_labeled: list[float],
    labels: list[float],
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Prediction-powered estimate of a mean with a CLT confidence interval.

    theta = mean(f(unlabeled)) + mean(y - f(labeled)). Valid for any predictor f,
    provided the labeled episodes are a uniformly random sample of all episodes.
    """
    n, big_n = len(labels), len(predictions_unlabeled)
    if n < 2 or big_n < 2 or len(predictions_labeled) != n:
        raise ValueError("need at least 2 labeled and 2 unlabeled episodes")
    rectifier = [y - f for y, f in zip(labels, predictions_labeled)]
    theta = statistics.fmean(predictions_unlabeled) + statistics.fmean(rectifier)
    se = math.sqrt(statistics.variance(predictions_unlabeled) / big_n + statistics.variance(rectifier) / n)
    z = statistics.NormalDist().inv_cdf(0.5 + confidence / 2)
    return {
        "estimate": round(theta, 6),
        "ci": [round(max(0.0, theta - z * se), 6), round(min(1.0, theta + z * se), 6)],
        "rectifier_mean": round(statistics.fmean(rectifier), 6),
        "labeled": n,
        "unlabeled": big_n,
    }


def success_rate_estimate(rows: list[Row], judge: str, unknown_as: float = 0.5, confidence: float = 0.95) -> dict[str, Any]:
    def f(r: Row) -> float:
        return {PASS: 1.0, FAIL: 0.0}.get(r.verdicts[judge], unknown_as)

    labeled = [r for r in rows if r.label in DECISIVE]
    unlabeled = [r for r in rows if r.label is None]
    y = [1.0 if r.label == PASS else 0.0 for r in labeled]
    out: dict[str, Any] = {
        "judge": judge,
        "unknown_counts_as": unknown_as,
        "labels_only": {**_rate(int(sum(y)), len(y)), "ci95": wilson(int(sum(y)), len(y), confidence)},
        "judge_only_uncorrected": round(statistics.fmean(f(r) for r in rows), 6) if rows else None,
        "assumption": "labeled episodes must be a uniformly random sample of all episodes",
    }
    try:
        out["prediction_powered"] = ppi_mean([f(r) for r in unlabeled], [f(r) for r in labeled], y, confidence)
    except ValueError as exc:
        out["prediction_powered"] = {"error": str(exc)}
    return out
