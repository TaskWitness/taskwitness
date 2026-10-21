import random

import pytest

from taskwitness.evaluate import (
    Row,
    expected_calibration_error,
    judge_audit,
    mcnemar_exact,
    ppi_mean,
    roc_auc,
    success_rate_estimate,
    summarize,
    wilson,
)


def test_wilson_known_values():
    # Reference values from the closed-form Wilson interval at z = 1.959964.
    assert wilson(0, 10) == pytest.approx([0.0, 0.277533], abs=1e-6)
    assert wilson(5, 10) == pytest.approx([0.236593, 0.763407], abs=1e-6)
    assert wilson(10, 10) == pytest.approx([0.722467, 1.0], abs=1e-6)
    assert wilson(0, 0) is None


def test_mcnemar_exact():
    assert mcnemar_exact(4, 0)["p_one_sided"] == pytest.approx(1 / 16)
    assert mcnemar_exact(4, 0)["p_two_sided"] == pytest.approx(1 / 8)
    assert mcnemar_exact(10, 1)["p_one_sided"] == pytest.approx(12 / 2048)
    assert mcnemar_exact(0, 0)["p_two_sided"] == 1.0
    assert mcnemar_exact(3, 3)["p_two_sided"] == 1.0


def rows_for(pairs):
    return [Row(f"e{i}", label, {"a": a, "b": b}) for i, (label, a, b) in enumerate(pairs)]


def test_summarize_rates_and_pairing():
    rows = rows_for(
        [("FAIL", "PASS", "FAIL")] * 3
        + [("FAIL", "FAIL", "FAIL")] * 2
        + [("PASS", "PASS", "UNKNOWN")] * 4
        + [("PASS", "FAIL", "PASS")]
        + [(None, "PASS", "PASS")] * 2
    )
    report = summarize(rows, ["a", "b"], compare=("a", "b"))
    a, b = report["judges"]["a"], report["judges"]["b"]
    assert report["audit_coverage"]["count"] == 10 and report["audit_coverage"]["of"] == 12
    assert a["conditional_miss"]["count"] == 3 and a["conditional_miss"]["of"] == 5
    assert a["absolute_miss"]["of"] == 10
    assert a["false_fail"]["count"] == 1
    assert b["unknown"]["count"] == 4
    assert b["accuracy_on_decided"]["count"] == 6 and b["accuracy_on_decided"]["of"] == 6
    assert report["paired_false_pass"]["a_only"] == 3 and report["paired_false_pass"]["b_only"] == 0


def test_strata_report_conditional_misses_separately():
    rows = [Row("x1", "FAIL", {"a": "PASS"}, "below_rim"), Row("x2", "FAIL", {"a": "FAIL"}, "above_rim"),
            Row("x3", "PASS", {"a": "PASS"}, "above_rim")]
    report = summarize(rows, ["a"])
    assert report["by_stratum"]["below_rim"]["a"]["conditional_miss"]["rate"] == 1.0
    assert report["by_stratum"]["above_rim"]["a"]["conditional_miss"]["rate"] == 0.0


def test_roc_auc_and_ece():
    assert roc_auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert roc_auc([0.5, 0.5], [True, False]) == 0.5
    assert roc_auc([0.1], [True]) is None
    assert expected_calibration_error([0.95, 0.95, 0.05, 0.05], [True, True, False, False]) == pytest.approx(0.05)
    assert expected_calibration_error([0.9] * 10, [True] * 5 + [False] * 5) == pytest.approx(0.4)


def test_judge_audit_detects_success_bias():
    reference = {f"e{i}": ("PASS" if i < 5 else "FAIL") for i in range(10)}
    judgements = {f"e{i}": (0.9 if i < 8 else 0.2) for i in range(10)}  # says success on 3 failures
    judgements["extra"] = 0.5
    report = judge_audit(judgements, reference)
    assert report["matched_episodes"] == 10 and report["judge_only"] == 1
    assert report["pass_rate_bias"] == pytest.approx(0.3)
    assert report["judges"]["judge"]["conditional_miss"]["count"] == 3
    assert report["balanced_accuracy"] == pytest.approx(1 - (0.6 + 0.0) / 2)
    assert report["roc_auc"] == pytest.approx(0.7)
    verdicts = judge_audit({"e0": "PASS", "e5": "PASS"}, reference)
    assert verdicts["roc_auc"] is None and verdicts["judges"]["judge"]["conditional_miss"]["count"] == 1


def test_ppi_is_unbiased_where_judge_alone_is_not():
    # The judge says PASS on 20% of true failures. PPI should land near the truth,
    # the uncorrected judge rate should not.
    rng = random.Random(7)
    truth = [rng.random() < 0.6 for _ in range(2000)]
    verdict = ["PASS" if t or rng.random() < 0.2 else "FAIL" for t in truth]
    labeled = set(rng.sample(range(2000), 200))
    rows = [Row(f"e{i}", ("PASS" if truth[i] else "FAIL") if i in labeled else None, {"tw": verdict[i]}) for i in range(2000)]
    out = success_rate_estimate(rows, "tw")
    true_rate = sum(truth) / len(truth)
    lo, hi = out["prediction_powered"]["ci"]
    assert lo <= true_rate <= hi
    assert abs(out["judge_only_uncorrected"] - true_rate) > 0.05
    label_lo, label_hi = out["labels_only"]["ci95"]
    assert (hi - lo) < (label_hi - label_lo)  # verdicts on unlabeled episodes tighten the interval


def test_ppi_requires_enough_data():
    with pytest.raises(ValueError):
        ppi_mean([1.0], [1.0, 0.0], [1.0, 0.0])
    rows = [Row("a", "PASS", {"tw": "PASS"})]
    assert "error" in success_rate_estimate(rows, "tw")["prediction_powered"]
