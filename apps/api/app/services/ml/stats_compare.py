"""Statistical comparison utilities for paired model evaluations.

This module implements McNemar's test (P1.4) — a paired non-parametric test that
answers the question "do two classifiers disagree in a statistically significant
way on the same set of items?". We apply it on the binary `in_tolerance`
outcome of each sensor (|pred - obs|/obs <= tol), so it directly tests whether
swapping model A for model B changes the count of sensors that fall inside the
user's tolerance band.

The test is run on the two DISCORDANT cells of the 2x2 contingency table:
- n01 : A out-of-tolerance AND B in-tolerance      ("B beats A")
- n10 : A in-tolerance      AND B out-of-tolerance ("A beats B")

We pick the variant of the test that matches the sample size:
- n01 + n10 >= 25  -> chi-square approximation with continuity correction
                      (Edwards 1948), 1 d.o.f.
- otherwise        -> exact two-sided binomial test, p = 0.5

The chi-square statistic is `(|n01 - n10| - 1)^2 / (n01 + n10)` and the
p-value is the upper-tail survival function of chi2(1).

The verdict is purely directional: A wins iff its in-tolerance count is
strictly higher AND the test is significant at alpha = 0.05.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy import stats


def _to_float_array(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {arr.shape}")
    return arr


def in_tolerance_mask(
    obs: np.ndarray,
    pred: np.ndarray,
    tolerance_pct: float,
) -> np.ndarray:
    """Return a boolean array: True iff |pred - obs| / |obs| <= tol/100.

    Sensors where ``obs == 0`` (or non-finite) are treated as OUT of tolerance
    — the relative error is undefined, and any non-zero prediction is
    definitionally infinite-error against a true zero. This keeps the
    contingency table dimensions consistent across both models without
    silently dropping sensors.
    """
    obs = np.asarray(obs, dtype=np.float64)
    pred = np.asarray(pred, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        rel = np.abs(pred - obs) / np.abs(obs)
    rel = np.where(np.isfinite(rel), rel, np.inf)
    return rel <= (tolerance_pct / 100.0)


def contingency(
    in_tol_a: np.ndarray,
    in_tol_b: np.ndarray,
) -> dict[str, int]:
    """Build the 2x2 paired contingency table.

    Cells follow the convention from the task spec:
    - n00 : both A and B FAIL
    - n01 : A FAIL, B OK
    - n10 : A OK,   B FAIL
    - n11 : both OK
    """
    if in_tol_a.shape != in_tol_b.shape:
        raise ValueError(f"in_tol_a {in_tol_a.shape} and in_tol_b {in_tol_b.shape} must match")
    a_ok = in_tol_a.astype(bool)
    b_ok = in_tol_b.astype(bool)
    n00 = int(np.sum(~a_ok & ~b_ok))
    n01 = int(np.sum(~a_ok & b_ok))
    n10 = int(np.sum(a_ok & ~b_ok))
    n11 = int(np.sum(a_ok & b_ok))
    return {"n00": n00, "n01": n01, "n10": n10, "n11": n11}


def mcnemar(n01: int, n10: int) -> dict:
    """Run McNemar's test on a single pair of discordant counts.

    Returns a dict with keys: ``chi2`` (None for the exact binomial branch),
    ``p_value``, ``method`` ("chi2" or "binomial_exact"), and
    ``significant_at_0.05`` (bool).
    """
    n01 = int(n01)
    n10 = int(n10)
    if n01 < 0 or n10 < 0:
        raise ValueError(f"n01 and n10 must be non-negative, got {n01}, {n10}")

    disc = n01 + n10
    if disc == 0:
        # No discordance at all -> the two models are indistinguishable on
        # this set. p-value is 1.0 by convention; no statistic to report.
        return {
            "chi2": None,
            "p_value": 1.0,
            "method": "binomial_exact",
            "significant_at_0.05": False,
        }

    if disc >= 25:
        chi2 = float(((abs(n01 - n10) - 1) ** 2) / disc)
        p = float(stats.chi2.sf(chi2, df=1))
        return {
            "chi2": round(chi2, 6),
            "p_value": float(p),
            "method": "chi2",
            "significant_at_0.05": bool(p < 0.05),
        }

    # Exact two-sided binomial test on min(n01, n10) successes out of disc
    # trials with p=0.5. scipy.stats.binomtest is the modern API; it returns
    # a BinomTestResult with .pvalue.
    k = min(n01, n10)
    result = stats.binomtest(k, n=disc, p=0.5, alternative="two-sided")
    p = float(result.pvalue)
    return {
        "chi2": None,
        "p_value": p,
        "method": "binomial_exact",
        "significant_at_0.05": bool(p < 0.05),
    }


def compare_models(
    obs: Sequence[float] | np.ndarray,
    pred_a: Sequence[float] | np.ndarray,
    pred_b: Sequence[float] | np.ndarray,
    tolerance_pct: float,
    name_a: str = "A",
    name_b: str = "B",
) -> dict:
    """High-level entry point used by the FastAPI router.

    Coerces inputs, validates equal length, derives the in-tolerance masks
    for both models, builds the contingency table, runs McNemar, and emits
    the directional verdict.
    """
    if not (0.0 < tolerance_pct <= 100.0):
        raise ValueError(f"tolerance_pct must be in (0, 100], got {tolerance_pct}")

    obs_arr = _to_float_array(obs, "obs")
    pa = _to_float_array(pred_a, "pred_a")
    pb = _to_float_array(pred_b, "pred_b")
    if not (obs_arr.shape == pa.shape == pb.shape):
        raise ValueError(
            f"shape mismatch: obs={obs_arr.shape}, pred_a={pa.shape}, pred_b={pb.shape}"
        )

    in_tol_a = in_tolerance_mask(obs_arr, pa, tolerance_pct)
    in_tol_b = in_tolerance_mask(obs_arr, pb, tolerance_pct)
    table = contingency(in_tol_a, in_tol_b)
    n_total = int(obs_arr.size)
    test = mcnemar(table["n01"], table["n10"])

    a_in_n = int(in_tol_a.sum())
    b_in_n = int(in_tol_b.sum())
    a_in_pct = round(100.0 * a_in_n / n_total, 2) if n_total else 0.0
    b_in_pct = round(100.0 * b_in_n / n_total, 2) if n_total else 0.0

    # Directional verdict: significance + which side has more in-tol sensors.
    if test["significant_at_0.05"]:
        if a_in_n > b_in_n:
            verdict = f"{name_a} meaningfully better than {name_b}"
        elif b_in_n > a_in_n:
            verdict = f"{name_b} meaningfully better than {name_a}"
        else:
            # Significant test but equal in-tol counts — algebraically
            # impossible when chi2 path is taken (disc > 0 and n01 != n10
            # implies a_in_n != b_in_n) but we cover it defensively.
            verdict = "no significant difference"
    else:
        verdict = "no significant difference"

    return {
        "table": table,
        "n_total": n_total,
        "chi2": test["chi2"],
        "p_value": test["p_value"],
        "method": test["method"],
        "significant_at_0.05": test["significant_at_0.05"],
        "verdict": verdict,
        "model_a": {"tol_in_n": a_in_n, "tol_in_pct": a_in_pct},
        "model_b": {"tol_in_n": b_in_n, "tol_in_pct": b_in_pct},
    }
