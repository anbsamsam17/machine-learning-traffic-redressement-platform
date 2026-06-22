"""Tests for app.services.ml.kfold — fonction(s) pure(s).

Cible : ``_summary`` (moyenne / ecart-type NaN-safe sur les valeurs de folds).
Le reste de ``kfold.py`` re-entraine de vrais modeles via ``run_training`` —
on ne teste ici QUE la reduction statistique pure, sans TF ni donnees reelles.

Proprietes verifiees :
- moyenne / std calculees uniquement sur les valeurs finies (NaN filtres) ;
- liste vide -> {mean: NaN, std: NaN} ;
- un seul echantillon finit -> std = 0.0 (pas de division par zero ddof=1) ;
- std en estimateur non biaise (ddof=1, echantillon).
"""

from __future__ import annotations

import math

import numpy as np

from app.services.ml.kfold import _summary


class TestSummaryEmptyAndNaN:
    def test_empty_list_returns_nan(self):
        out = _summary([])
        assert math.isnan(out["mean"])
        assert math.isnan(out["std"])

    def test_all_nan_treated_as_empty(self):
        out = _summary([float("nan"), float("nan")])
        assert math.isnan(out["mean"])
        assert math.isnan(out["std"])

    def test_none_values_are_ignored(self):
        # None et NaN sont tous deux filtres avant le calcul.
        out = _summary([None, 4.0, None, 6.0])
        assert out["mean"] == 5.0

    def test_nan_filtered_before_mean(self):
        # Le NaN ne doit pas contaminer la moyenne (sinon mean=NaN).
        out = _summary([2.0, float("nan"), 4.0])
        assert out["mean"] == 3.0
        assert not math.isnan(out["std"])


class TestSummarySingleValue:
    def test_single_finite_value_std_zero(self):
        # Un seul echantillon : std forcee a 0.0 (ddof=1 sinon -> NaN/erreur).
        out = _summary([7.5])
        assert out["mean"] == 7.5
        assert out["std"] == 0.0

    def test_single_after_nan_filter(self):
        out = _summary([float("nan"), 3.0, float("nan")])
        assert out["mean"] == 3.0
        assert out["std"] == 0.0


class TestSummaryStatistics:
    def test_mean_matches_numpy(self):
        vals = [10.0, 20.0, 30.0, 40.0]
        out = _summary(vals)
        assert out["mean"] == float(np.mean(vals))

    def test_std_is_sample_ddof1(self):
        # ddof=1 (estimateur non biaise), distinct de la std population (ddof=0).
        vals = [2.0, 4.0, 6.0, 8.0]
        out = _summary(vals)
        expected = float(np.std(vals, ddof=1))
        assert out["std"] == expected
        assert out["std"] != float(np.std(vals, ddof=0))

    def test_constant_values_zero_std(self):
        out = _summary([5.0, 5.0, 5.0])
        assert out["mean"] == 5.0
        assert out["std"] == 0.0

    def test_returns_python_floats(self):
        out = _summary([1.0, 2.0])
        assert isinstance(out["mean"], float)
        assert isinstance(out["std"], float)
