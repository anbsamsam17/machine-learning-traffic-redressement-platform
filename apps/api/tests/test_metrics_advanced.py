"""Tests pour app.services.ml.metrics_advanced — metriques d'evaluation avancees.

Couvre les fonctions pure-numpy / pure-pandas du module : intervalle de
confiance bootstrap (CI95), adaptateurs de metriques (R2, p80 erreur
relative, tol_in_pct), stratification par bucket de trafic, donnees de
calibration et table de derive annuelle.

Deterministe, sans GPU, sans donnees reelles. Le module est pur numpy/pandas
(aucun import TensorFlow), donc pas besoin de desactiver le GPU ici.
Seed projet fixe a 1750 pour la reproductibilite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ml.metrics_advanced import (
    _BOOTSTRAP_MIN_SAMPLES,
    _DRIFT_MIN_SAMPLES,
    _TMJA_BUCKETS,
    _compute_calibration_data,
    _compute_drift_by_year,
    _metric_p80_err_rel,
    _metric_r2,
    _metric_tol_in_pct,
    _stratify_by_tmja,
    bootstrap_ci95,
)

SEED = 1750


# ---------------------------------------------------------------------------
# Adaptateurs de metriques : (obs, pred, weights | None) -> float
# ---------------------------------------------------------------------------


class TestMetricR2:
    def test_perfect_fit_gives_one(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert _metric_r2(obs, obs.copy(), None) == pytest.approx(1.0)

    def test_matches_closed_form(self):
        obs = np.array([10.0, 20.0, 30.0, 40.0])
        pred = np.array([12.0, 18.0, 33.0, 39.0])
        ss_res = float(np.sum((obs - pred) ** 2))
        ss_tot = float(np.sum((obs - obs.mean()) ** 2))
        expected = 1.0 - ss_res / ss_tot
        assert _metric_r2(obs, pred, None) == pytest.approx(expected)

    def test_zero_variance_returns_zero(self):
        # ss_tot == 0 -> la fonction renvoie 0.0 par convention.
        obs = np.array([5.0, 5.0, 5.0])
        pred = np.array([4.0, 6.0, 5.0])
        assert _metric_r2(obs, pred, None) == 0.0

    def test_weighted_r2_runs_and_is_finite(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        pred = np.array([1.1, 1.9, 3.2, 3.8])
        w = np.array([1.0, 2.0, 1.0, 2.0])
        val = _metric_r2(obs, pred, w)
        assert np.isfinite(val)
        assert val <= 1.0


class TestMetricP80:
    def test_zero_error_gives_zero(self):
        obs = np.array([100.0, 200.0, 300.0, 400.0, 500.0])
        assert _metric_p80_err_rel(obs, obs.copy(), None) == pytest.approx(0.0)

    def test_matches_numpy_percentile(self):
        obs = np.array([100.0, 200.0, 400.0, 500.0])
        pred = np.array([110.0, 180.0, 440.0, 450.0])
        err_rel = np.abs((obs - pred) / obs) * 100.0
        expected = float(np.nanpercentile(err_rel, 80))
        assert _metric_p80_err_rel(obs, pred, None) == pytest.approx(expected)

    def test_all_zero_obs_returns_nan(self):
        obs = np.zeros(4)
        pred = np.array([1.0, 2.0, 3.0, 4.0])
        assert np.isnan(_metric_p80_err_rel(obs, pred, None))


class TestMetricTolInPct:
    def test_counts_code_one_ratio(self):
        # obs porte les codes Tolerance_IN_OUT ; pred est ignore.
        codes = np.array([1.0, 1.0, 2.0, 3.0])  # 2 "in" sur 4 -> 50%
        assert _metric_tol_in_pct(codes, np.zeros(4), None) == pytest.approx(50.0)

    def test_ignores_nan_codes(self):
        codes = np.array([1.0, np.nan, 1.0, 2.0])  # 2 "in" sur 3 valides
        assert _metric_tol_in_pct(codes, np.zeros(4), None) == pytest.approx(200.0 / 3.0)

    def test_all_nan_returns_nan(self):
        codes = np.array([np.nan, np.nan])
        assert np.isnan(_metric_tol_in_pct(codes, np.zeros(2), None))


# ---------------------------------------------------------------------------
# bootstrap_ci95 — CI95 par percentile
# ---------------------------------------------------------------------------


class TestBootstrapCI95:
    def test_below_min_samples_returns_none(self):
        n = _BOOTSTRAP_MIN_SAMPLES - 1
        obs = np.linspace(1.0, 2.0, n)
        pred = obs.copy()
        assert bootstrap_ci95(_metric_r2, obs, pred, n_iter=50, seed=SEED) is None

    def test_at_min_samples_returns_tuple(self):
        rng = np.random.default_rng(SEED)
        n = _BOOTSTRAP_MIN_SAMPLES
        obs = rng.normal(100.0, 10.0, size=n)
        pred = obs + rng.normal(0.0, 1.0, size=n)
        out = bootstrap_ci95(_metric_r2, obs, pred, n_iter=200, seed=SEED)
        assert out is not None
        assert len(out) == 3

    def test_low_le_mean_le_high(self):
        rng = np.random.default_rng(SEED)
        n = 80
        obs = rng.normal(100.0, 15.0, size=n)
        pred = obs + rng.normal(0.0, 3.0, size=n)
        mean, low, high = bootstrap_ci95(_metric_r2, obs, pred, n_iter=300, seed=SEED)
        assert low <= mean <= high

    def test_reproducible_at_fixed_seed(self):
        rng = np.random.default_rng(SEED)
        n = 60
        obs = rng.normal(50.0, 5.0, size=n)
        pred = obs + rng.normal(0.0, 2.0, size=n)
        out_a = bootstrap_ci95(_metric_r2, obs, pred, n_iter=250, seed=SEED)
        out_b = bootstrap_ci95(_metric_r2, obs, pred, n_iter=250, seed=SEED)
        assert out_a == out_b

    def test_different_seed_changes_result(self):
        rng = np.random.default_rng(SEED)
        n = 60
        obs = rng.normal(50.0, 5.0, size=n)
        pred = obs + rng.normal(0.0, 2.0, size=n)
        out_a = bootstrap_ci95(_metric_r2, obs, pred, n_iter=250, seed=SEED)
        out_b = bootstrap_ci95(_metric_r2, obs, pred, n_iter=250, seed=SEED + 1)
        assert out_a != out_b

    def test_zero_iter_returns_none(self):
        obs = np.linspace(1.0, 2.0, 40)
        pred = obs.copy()
        assert bootstrap_ci95(_metric_r2, obs, pred, n_iter=0, seed=SEED) is None

    def test_length_mismatch_returns_none(self):
        obs = np.linspace(1.0, 2.0, 40)
        pred = np.linspace(1.0, 2.0, 39)
        assert bootstrap_ci95(_metric_r2, obs, pred, n_iter=50, seed=SEED) is None

    def test_mismatched_weights_dropped_not_crash(self):
        rng = np.random.default_rng(SEED)
        n = 40
        obs = rng.normal(100.0, 10.0, size=n)
        pred = obs + rng.normal(0.0, 2.0, size=n)
        bad_w = np.ones(n - 5)  # mauvaise taille -> ignore en interne
        out = bootstrap_ci95(_metric_r2, obs, pred, weights=bad_w, n_iter=100, seed=SEED)
        assert out is not None and len(out) == 3


# ---------------------------------------------------------------------------
# _stratify_by_tmja — stratification par bucket de trafic
# ---------------------------------------------------------------------------


class TestStratifyByTmja:
    def _make_df(self, n_per_bucket: int = 20):
        rng = np.random.default_rng(SEED)
        flows, y_true, y_pred, tol_codes = [], [], [], []
        # Une valeur de flux representative dans chaque bucket canonique.
        centers = [500.0, 3000.0, 10000.0, 50000.0]
        for c in centers:
            for _ in range(n_per_bucket):
                f = c
                t = c + rng.normal(0.0, c * 0.05)
                p = t + rng.normal(0.0, c * 0.03)
                flows.append(f)
                y_true.append(t)
                y_pred.append(p)
                tol_codes.append(1.0)
        df = pd.DataFrame(
            {
                "TMJOBCTV": flows,
                "Tolerance_IN_OUT": tol_codes,
            }
        )
        return df, np.asarray(y_true), np.asarray(y_pred)

    def test_returns_one_row_per_bucket(self):
        df, yt, yp = self._make_df()
        rows = _stratify_by_tmja(df, "TMJOBCTV", yt, yp)
        assert len(rows) == len(_TMJA_BUCKETS)
        labels = [r["bucket"] for r in rows]
        assert labels == [b[0] for b in _TMJA_BUCKETS]

    def test_missing_flow_col_returns_empty(self):
        df, yt, yp = self._make_df()
        assert _stratify_by_tmja(df, "DOES_NOT_EXIST", yt, yp) == []

    def test_n_samples_sum_matches_total(self):
        df, yt, yp = self._make_df(n_per_bucket=15)
        rows = _stratify_by_tmja(df, "TMJOBCTV", yt, yp)
        assert sum(r["n_samples"] for r in rows) == len(df)

    def test_low_sample_warning_flag(self):
        # 5 lignes dans un seul bucket -> warning (< seuil 10), pas dropped.
        df = pd.DataFrame(
            {
                "TMJOBCTV": [500.0] * 5,
                "Tolerance_IN_OUT": [1.0] * 5,
            }
        )
        yt = np.array([500.0, 510.0, 490.0, 505.0, 495.0])
        yp = np.array([500.0, 505.0, 495.0, 500.0, 500.0])
        rows = _stratify_by_tmja(df, "TMJOBCTV", yt, yp)
        first = next(r for r in rows if r["bucket"] == "0-1k")
        assert first["n_samples"] == 5
        assert first["low_sample_warning"] is True

    def test_tol_in_pct_full_in(self):
        df, yt, yp = self._make_df()
        rows = _stratify_by_tmja(df, "TMJOBCTV", yt, yp)
        for r in rows:
            if r["n_samples"] > 0:
                assert r["tol_in_pct"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# _compute_calibration_data
# ---------------------------------------------------------------------------


class TestCalibrationData:
    def test_basic_payload(self):
        obs = np.array([1.0, 2.0, 3.0, 4.0])
        pred = np.array([1.1, 2.1, 2.9, 4.2])
        out = _compute_calibration_data(obs, pred)
        assert out is not None
        assert out["n"] == 4
        assert out["n_plotted"] == 4
        assert len(out["obs"]) == 4
        assert len(out["pred"]) == 4

    def test_drops_non_finite_pairs(self):
        obs = np.array([1.0, np.nan, 3.0, np.inf])
        pred = np.array([1.0, 2.0, 3.0, 4.0])
        out = _compute_calibration_data(obs, pred)
        assert out is not None
        assert out["n"] == 2

    def test_empty_returns_none(self):
        assert _compute_calibration_data(np.array([]), np.array([])) is None

    def test_downsample_deterministic(self):
        rng = np.random.default_rng(SEED)
        obs = rng.normal(100.0, 10.0, size=50)
        pred = obs + rng.normal(0.0, 2.0, size=50)
        a = _compute_calibration_data(obs, pred, max_points=20, seed=SEED)
        b = _compute_calibration_data(obs, pred, max_points=20, seed=SEED)
        assert a is not None and b is not None
        assert a["n_plotted"] == 20
        assert a["n"] == 50
        assert a["obs"] == b["obs"]
        assert a["pred"] == b["pred"]


# ---------------------------------------------------------------------------
# _compute_drift_by_year
# ---------------------------------------------------------------------------


class TestDriftByYear:
    def _make_df(self, years, n_per_year):
        rng = np.random.default_rng(SEED)
        ym, y_true, y_pred = [], [], []
        for yr in years:
            for _ in range(n_per_year):
                t = rng.normal(1000.0, 100.0)
                p = t + rng.normal(0.0, 30.0)
                ym.append(float(yr))
                y_true.append(t)
                y_pred.append(p)
        df = pd.DataFrame({"year_mapped": ym})
        return df, np.asarray(y_true), np.asarray(y_pred)

    def test_no_year_column_returns_empty(self):
        df = pd.DataFrame({"foo": [1, 2, 3]})
        assert _compute_drift_by_year(df, np.array([1.0]), np.array([1.0])) == []

    def test_one_row_per_eligible_year(self):
        df, yt, yp = self._make_df([1, 2, 3], n_per_year=20)
        rows = _compute_drift_by_year(df, yt, yp)
        assert {r["year_mapped"] for r in rows} == {1, 2, 3}

    def test_skips_years_below_min_samples(self):
        # Annee 1 a assez de lignes ; annee 2 en dessous du seuil -> exclue.
        df, yt, yp = self._make_df([1], n_per_year=_DRIFT_MIN_SAMPLES + 5)
        df_small, yt_s, yp_s = self._make_df([2], n_per_year=_DRIFT_MIN_SAMPLES - 1)
        df_all = pd.concat([df, df_small], ignore_index=True)
        yt_all = np.concatenate([yt, yt_s])
        yp_all = np.concatenate([yp, yp_s])
        rows = _compute_drift_by_year(df_all, yt_all, yp_all)
        years = {r["year_mapped"] for r in rows}
        assert 1 in years
        assert 2 not in years

    def test_uses_reverse_label_mapping(self):
        df, yt, yp = self._make_df([1, 2], n_per_year=20)
        mapping = {"2019": 1.0, "2020": 2.0}
        rows = _compute_drift_by_year(df, yt, yp, year_value_mapping=mapping)
        labels = {r["year_mapped"]: r["year_label"] for r in rows}
        assert labels[1] == "2019"
        assert labels[2] == "2020"

    def test_fallback_label_when_no_mapping(self):
        df, yt, yp = self._make_df([3], n_per_year=20)
        rows = _compute_drift_by_year(df, yt, yp)
        assert rows[0]["year_label"] == "year_3"

    def test_metrics_are_finite_and_bounded(self):
        df, yt, yp = self._make_df([1], n_per_year=40)
        rows = _compute_drift_by_year(df, yt, yp)
        r = rows[0]
        assert r["mae"] >= 0.0
        assert r["r2"] <= 1.0
        assert 0.0 <= r["tol_in_pct"] <= 100.0
