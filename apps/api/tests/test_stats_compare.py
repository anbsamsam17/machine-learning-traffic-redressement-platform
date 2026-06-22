"""Tests for app.services.ml.stats_compare — McNemar's paired test.

Verifies the chi-square statistic / p-value against the closed-form formula
and scipy, the exact-binomial small-sample branch, contingency construction,
and the directional verdict. Deterministic, no GPU, no real data.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from app.services.ml.stats_compare import (
    compare_models,
    contingency,
    in_tolerance_mask,
    mcnemar,
)

# ---------------------------------------------------------------------------
# mcnemar — chi-square branch (disc >= 25)
# ---------------------------------------------------------------------------


class TestMcNemarChiSquare:
    def test_statistic_matches_closed_form(self):
        n01, n10 = 30, 10  # disc = 40 >= 25 -> chi2 with continuity correction
        result = mcnemar(n01, n10)

        expected_chi2 = (abs(n01 - n10) - 1) ** 2 / (n01 + n10)
        expected_p = float(stats.chi2.sf(expected_chi2, df=1))

        assert result["method"] == "chi2"
        assert result["chi2"] == pytest.approx(expected_chi2, abs=1e-6)
        assert result["p_value"] == pytest.approx(expected_p, rel=1e-9)

    def test_significant_flag(self):
        # Strongly discordant -> significant at 0.05.
        result = mcnemar(40, 5)
        assert result["significant_at_0.05"] is True
        assert result["p_value"] < 0.05

    def test_balanced_discordance_not_significant(self):
        # n01 == n10 -> statistic ~ 0 -> not significant.
        result = mcnemar(20, 20)  # disc=40
        assert result["method"] == "chi2"
        assert result["significant_at_0.05"] is False
        assert result["p_value"] > 0.05


# ---------------------------------------------------------------------------
# mcnemar — exact binomial branch (disc < 25)
# ---------------------------------------------------------------------------


class TestMcNemarBinomial:
    def test_matches_scipy_binomtest(self):
        n01, n10 = 8, 2  # disc=10 < 25 -> exact binomial
        result = mcnemar(n01, n10)

        expected_p = stats.binomtest(
            min(n01, n10), n=n01 + n10, p=0.5, alternative="two-sided"
        ).pvalue

        assert result["method"] == "binomial_exact"
        assert result["chi2"] is None
        assert result["p_value"] == pytest.approx(expected_p, rel=1e-9)

    def test_zero_discordance_is_pvalue_one(self):
        result = mcnemar(0, 0)
        assert result["p_value"] == 1.0
        assert result["significant_at_0.05"] is False
        assert result["chi2"] is None

    def test_negative_counts_raise(self):
        with pytest.raises(ValueError):
            mcnemar(-1, 3)


# ---------------------------------------------------------------------------
# in_tolerance_mask
# ---------------------------------------------------------------------------


class TestInToleranceMask:
    def test_relative_error_threshold(self):
        obs = np.array([100.0, 100.0, 100.0])
        pred = np.array([105.0, 120.0, 100.0])  # rel err 5%, 20%, 0%
        mask = in_tolerance_mask(obs, pred, tolerance_pct=10.0)
        np.testing.assert_array_equal(mask, [True, False, True])

    def test_zero_obs_is_out_of_tolerance(self):
        obs = np.array([0.0, 0.0])
        pred = np.array([0.0, 1.0])
        mask = in_tolerance_mask(obs, pred, tolerance_pct=10.0)
        # obs==0 -> undefined relative error -> treated as OUT.
        np.testing.assert_array_equal(mask, [False, False])


# ---------------------------------------------------------------------------
# contingency
# ---------------------------------------------------------------------------


class TestContingency:
    def test_cells_count_correctly(self):
        a = np.array([True, True, False, False])
        b = np.array([True, False, True, False])
        table = contingency(a, b)
        assert table == {"n11": 1, "n10": 1, "n01": 1, "n00": 1}

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            contingency(np.array([True, False]), np.array([True]))


# ---------------------------------------------------------------------------
# compare_models — high-level entry point
# ---------------------------------------------------------------------------


class TestCompareModels:
    def test_a_better_verdict_significant(self):
        # Construct obs/preds so A is in-tol on many sensors where B is not.
        n = 50
        obs = np.full(n, 100.0)
        # A: all within 5% (in tol at 10%).
        pred_a = np.full(n, 103.0)
        # B: first 40 wildly off (out of tol), last 10 in tol.
        pred_b = np.concatenate([np.full(40, 200.0), np.full(10, 101.0)])

        out = compare_models(obs, pred_a, pred_b, tolerance_pct=10.0, name_a="A", name_b="B")

        assert out["model_a"]["tol_in_n"] == 50
        assert out["model_b"]["tol_in_n"] == 10
        assert out["significant_at_0.05"] is True
        assert out["method"] == "chi2"
        assert "A" in out["verdict"] and "better" in out["verdict"]
        # Contingency total is consistent.
        t = out["table"]
        assert t["n00"] + t["n01"] + t["n10"] + t["n11"] == n

    def test_no_difference_verdict(self):
        obs = np.full(10, 100.0)
        pred_a = np.full(10, 101.0)
        pred_b = np.full(10, 101.0)  # identical -> no discordance
        out = compare_models(obs, pred_a, pred_b, tolerance_pct=10.0)
        assert out["significant_at_0.05"] is False
        assert out["verdict"] == "no significant difference"

    def test_invalid_tolerance_raises(self):
        obs = np.array([1.0, 2.0])
        with pytest.raises(ValueError):
            compare_models(obs, obs, obs, tolerance_pct=0.0)
        with pytest.raises(ValueError):
            compare_models(obs, obs, obs, tolerance_pct=150.0)

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError):
            compare_models(
                np.array([1.0, 2.0]),
                np.array([1.0]),
                np.array([1.0, 2.0]),
                tolerance_pct=10.0,
            )
