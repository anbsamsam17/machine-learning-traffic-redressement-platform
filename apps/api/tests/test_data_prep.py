"""Tests for app.services.ml.data_prep — alias resolution, target derivation, split."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ml.data_prep import (
    _resolve_aliases,
    _derive_target,
    _derive_flag_comptage,
    prepare_training_data,
    split_train_valid,
)
from app.services.ml.types import TV_CONFIG, PL_CONFIG


# ---------------------------------------------------------------------------
# Synthetic DataFrame builder
# ---------------------------------------------------------------------------

def _make_tv_df(n: int = 10, use_aliases: bool = False) -> pd.DataFrame:
    """Create a synthetic training DataFrame for TV.

    T2 : schema modernise (TMJOFCDTV / TxPen / TMJOBCTV) au lieu du legacy.
    Si use_aliases=True, on injecte les anciens noms (TMJATV, TxPen) pour
    tester le code de retro-compat (column_aliases du TV_CONFIG).
    """
    rng = np.random.default_rng(1750)
    # Noms de colonnes canoniques HERE (V2)
    data = {
        "avg_distance_m": rng.uniform(5, 50, n) * 1000,
        "avg_speed_kmh": rng.uniform(30, 130, n),
        "truck_avg_min_distance_m": rng.uniform(10, 80, n) * 1000,
        "truck_avg_speed_kmh": rng.uniform(40, 90, n),
        "functional_class": rng.choice([1, 2, 3, 4, 5], n),
        "TMJOBCTV": rng.uniform(500, 20000, n),
        "Type": rng.choice(["Permanent", "Temporaire", "Ponctuel"], n),
    }
    if use_aliases:
        # Legacy alias : TMJATV / TxPen -> TMJOFCDTV / TxPen (resolu par
        # TV_CONFIG.column_aliases).
        data["TMJATV"] = rng.uniform(100, 5000, n)
        data["TMJAPL"] = rng.uniform(50, 1000, n)
        data["TxPen"] = data["TMJATV"] / data["TMJOBCTV"] * 100
    else:
        # Noms canoniques HERE
        data["TMJOFCDTV"] = rng.uniform(100, 5000, n)
        data["TMJOFCDPL"] = rng.uniform(50, 1000, n)
        data["TxPen"] = data["TMJOFCDTV"] / data["TMJOBCTV"] * 100

    return pd.DataFrame(data)


def _make_pl_df(n: int = 10) -> pd.DataFrame:
    """Synthetic PL training DataFrame, schema modernise (HERE V2)."""
    rng = np.random.default_rng(1750)
    return pd.DataFrame({
        "TMJOFCDPL": rng.uniform(50, 1000, n),
        "TMJOFCDTV": rng.uniform(500, 5000, n),
        "functional_class": rng.choice([1, 2, 3, 4, 5], n),
        "truck_avg_distance_m": rng.uniform(10, 80, n) * 1000,
        "truck_avg_min_distance_m": rng.uniform(10, 80, n) * 1000,
        "truck_avg_distance_before_m": rng.uniform(10, 80, n) * 1000,
        "truck_avg_distance_after_m": rng.uniform(10, 80, n) * 1000,
        "fcd_log": rng.uniform(0, 10, n),
        "tv_pl_ratio": rng.uniform(0.05, 0.4, n),
        "dist_to_lyon_center": rng.uniform(0, 30000, n),
        "TxPenPL": rng.uniform(1, 30, n),
        "TMJOBCPL": rng.uniform(100, 5000, n),
    })


# ---------------------------------------------------------------------------
# _resolve_aliases
# ---------------------------------------------------------------------------

class TestResolveAliases:
    def test_tv_aliases_create_canonical_cols(self):
        """T2: legacy TMJATV/TxPen -> canonical HERE (TMJOFCDTV, TxPen)."""
        df = pd.DataFrame({
            "TMJATV": [100.0, 200.0],
            "TMJAPL": [50.0, 60.0],
            "TxPen": [10.1234, 20.5678],
        })
        result = _resolve_aliases(df, TV_CONFIG)
        # Resolution vers le schema canonique HERE
        assert "TMJOFCDTV" in result.columns
        assert "TMJOFCDPL" in result.columns
        # TxPen est deja le nom canonique TV_CONFIG.target_col -> doit etre present
        assert "TxPen" in result.columns
        np.testing.assert_allclose(result["TxPen"].values, [10.1234, 20.5678])

    def test_no_overwrite_existing_col(self):
        """If destination column already exists, alias should NOT overwrite it."""
        df = pd.DataFrame({
            "TMJATV": [999.0],
            "TMJOFCDTV": [123.0],  # canonique deja present
        })
        result = _resolve_aliases(df, TV_CONFIG)
        # La canonique deja presente n'est PAS ecrasee par l'alias.
        assert result["TMJOFCDTV"].iloc[0] == 123.0

    def test_pl_aliases(self):
        """T2: legacy TMJAPL/TxPenPL -> canonical HERE (TMJOFCDPL, TxPenPL)."""
        df = pd.DataFrame({
            "TMJAPL": [100.0],
            "TxPenPL": [15.0],
        })
        result = _resolve_aliases(df, PL_CONFIG)
        # Canonique HERE
        assert "TMJOFCDPL" in result.columns
        # TxPenPL est le target_col canonique du PL_CONFIG -> present
        assert "TxPenPL" in result.columns

    def test_tmjfcdtv_alias(self):
        """T2: TMJFCDTV (sans le A) -> TMJOFCDTV (canonique HERE)."""
        df = pd.DataFrame({"TMJFCDTV": [500.0]})
        result = _resolve_aliases(df, TV_CONFIG)
        assert "TMJOFCDTV" in result.columns
        np.testing.assert_allclose(result["TMJOFCDTV"].values, [500.0])


# ---------------------------------------------------------------------------
# _derive_target
# ---------------------------------------------------------------------------

class TestDeriveTarget:
    def test_tv_derives_txpen_from_bc_fcd(self):
        """T2: target_col canonique = TxPen ; FCD/BC en TMJOFCDTV/TMJOBCTV."""
        df = pd.DataFrame({
            "TMJOFCDTV": [1000.0, 2000.0],
            "TMJOBCTV": [5000.0, 10000.0],
        })
        result = _derive_target(df, TV_CONFIG)
        # Target name canonique = TV_CONFIG.target_col = "TxPen"
        assert TV_CONFIG.target_col in result.columns
        expected = [1000.0 / 5000.0 * 100, 2000.0 / 10000.0 * 100]
        np.testing.assert_allclose(result[TV_CONFIG.target_col].values, expected)

    def test_does_not_overwrite_existing_target(self):
        df = pd.DataFrame({
            "TMJOFCDTV": [1000.0],
            "TMJOBCTV": [5000.0],
            "TxPen": [99.0],
        })
        result = _derive_target(df, TV_CONFIG)
        assert result["TxPen"].iloc[0] == 99.0

    def test_zero_bc_produces_zero_via_fillna(self):
        """T2: TMJOBCTV=0 -> mask False -> target = 0 (NaN-safe)."""
        df = pd.DataFrame({
            "TMJOFCDTV": [1000.0],
            "TMJOBCTV": [0.0],
        })
        result = _derive_target(df, TV_CONFIG)
        assert result[TV_CONFIG.target_col].iloc[0] == 0.0

    def test_pl_target_derivation(self):
        """T2: PL_CONFIG.target_col = TxPenPL ; FCD/BC en TMJOFCDPL/TMJOBCPL."""
        df = pd.DataFrame({
            "TMJOFCDPL": [500.0],
            "TMJOBCPL": [2000.0],
        })
        result = _derive_target(df, PL_CONFIG)
        assert PL_CONFIG.target_col in result.columns  # = "TxPenPL"
        np.testing.assert_allclose(result[PL_CONFIG.target_col].values, [25.0])


# ---------------------------------------------------------------------------
# _derive_flag_comptage
# ---------------------------------------------------------------------------

class TestDeriveFlagComptage:
    def test_from_type_column(self):
        df = pd.DataFrame({"Type": ["Per", "Tou", "Pon", "  per  ", "TOU"]})
        result = _derive_flag_comptage(df)
        expected = [1, 1, 0, 1, 1]
        np.testing.assert_array_equal(result["flag_comptage"].values, expected)

    def test_default_zero_when_no_type(self):
        df = pd.DataFrame({"col_a": [1, 2, 3]})
        result = _derive_flag_comptage(df)
        np.testing.assert_array_equal(result["flag_comptage"].values, [0, 0, 0])

    def test_does_not_overwrite_existing(self):
        df = pd.DataFrame({"flag_comptage": [1, 0, 1], "Type": ["Pon", "Pon", "Pon"]})
        result = _derive_flag_comptage(df)
        np.testing.assert_array_equal(result["flag_comptage"].values, [1, 0, 1])


# ---------------------------------------------------------------------------
# prepare_training_data (full pipeline)
# ---------------------------------------------------------------------------

class TestPrepareTrainingData:
    def test_standard_columns_pass_through(self):
        df = _make_tv_df(n=10, use_aliases=False)
        result = prepare_training_data(df, TV_CONFIG)
        assert len(result) <= 10
        # T2 : on verifie au moins la presence des input/output canoniques.
        # Certaines features (functional_class) peuvent etre transformees ou
        # absentes du resultat final selon les options.
        for col in TV_CONFIG.output_cols:
            assert col in result.columns
        # Au moins les FCD canoniques
        assert "TMJOFCDTV" in result.columns

    def test_aliases_resolved(self):
        df = _make_tv_df(n=10, use_aliases=True)
        result = prepare_training_data(df, TV_CONFIG)
        # T2: aliases resolus vers les noms canoniques HERE.
        assert "TMJOFCDTV" in result.columns
        # Target canonique (TxPen) present.
        assert TV_CONFIG.target_col in result.columns

    def test_target_derived_when_missing(self):
        """T2: TxPen derive de TMJOFCDTV/TMJOBCTV quand absent."""
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "TMJOFCDTV": rng.uniform(100, 5000, 10),
            "TMJOFCDPL": rng.uniform(50, 1000, 10),
            "avg_distance_m": rng.uniform(5, 50, 10) * 1000,
            "avg_speed_kmh": rng.uniform(30, 130, 10),
            "truck_avg_min_distance_m": rng.uniform(10, 80, 10) * 1000,
            "truck_avg_speed_kmh": rng.uniform(40, 90, 10),
            "functional_class": rng.choice([1, 2, 3, 4, 5], 10),
            "TMJOBCTV": rng.uniform(500, 20000, 10),
        })
        result = prepare_training_data(df, TV_CONFIG)
        assert TV_CONFIG.target_col in result.columns
        assert result[TV_CONFIG.target_col].notna().all()

    def test_missing_required_cols_raises(self):
        df = pd.DataFrame({"col_a": [1, 2, 3]})
        with pytest.raises(ValueError, match="Missing required columns"):
            prepare_training_data(df, TV_CONFIG)

    def test_empty_after_dropna_raises(self):
        df = pd.DataFrame({col: [np.nan] for col in TV_CONFIG.input_cols + TV_CONFIG.output_cols})
        with pytest.raises(ValueError, match="empty after dropna"):
            prepare_training_data(df, TV_CONFIG)

    def test_flag_comptage_created(self):
        df = _make_tv_df(n=10)
        result = prepare_training_data(df, TV_CONFIG)
        # T2: peut etre flag_comptage OU flag_permanent (rename pending P2A.4).
        assert ("flag_comptage" in result.columns) or ("flag_permanent" in result.columns)

    def test_pl_pipeline(self):
        df = _make_pl_df(n=10)
        result = prepare_training_data(df, PL_CONFIG)
        # T2: target_col PL canonique
        assert PL_CONFIG.target_col in result.columns
        # Et TMJOFCDPL canonique present
        assert "TMJOFCDPL" in result.columns


# ---------------------------------------------------------------------------
# split_train_valid
# ---------------------------------------------------------------------------

class TestSplitTrainValid:
    def test_no_split_when_test_size_zero(self):
        df = _make_tv_df(n=10)
        result = prepare_training_data(df, TV_CONFIG)
        split = split_train_valid(
            result,
            input_cols=TV_CONFIG.input_cols,
            output_cols=TV_CONFIG.output_cols,
            test_size=0.0,
            seed=1750,
        )
        assert split["idx_valid"] is None
        assert split["y_valid"] is None
        assert len(split["idx_train"]) == len(result)

    def test_split_with_test_size(self):
        df = _make_tv_df(n=10)
        result = prepare_training_data(df, TV_CONFIG)
        split = split_train_valid(
            result,
            input_cols=TV_CONFIG.input_cols,
            output_cols=TV_CONFIG.output_cols,
            test_size=0.3,
            seed=1750,
        )
        assert split["idx_valid"] is not None
        n_total = len(result)
        assert len(split["idx_train"]) + len(split["idx_valid"]) == n_total

    def test_sample_weights_flag_comptage(self):
        """T2: les poids sont desormais normalises (mean == 1.0) au lieu d'etre
        1.0/4.0 brut. On verifie le RATIO entre les 2 classes (priority/normal)."""
        df = _make_tv_df(n=10)
        df["flag_comptage"] = [1, 0, 1, 0, 0, 1, 0, 0, 1, 0]
        result = prepare_training_data(df, TV_CONFIG)
        split = split_train_valid(
            result,
            input_cols=TV_CONFIG.input_cols,
            output_cols=TV_CONFIG.output_cols,
            test_size=0.0,
            seed=1750,
            use_flag_comptage_weighting=True,
            flag_priority_weight=4.0,
        )
        sw = split["train_sample_weight"]
        assert sw is not None
        unique_weights = set(np.unique(sw))
        # Doit y avoir exactement 2 poids distincts (flag 0 et flag 1)
        assert len(unique_weights) == 2, f"expected 2 weights, got: {unique_weights}"
        # Le ratio max/min doit etre 4.0 (flag_priority_weight)
        weights_sorted = sorted(unique_weights)
        ratio = weights_sorted[1] / weights_sorted[0]
        assert abs(ratio - 4.0) < 1e-6, f"expected ratio 4.0, got {ratio}"

    def test_x_full_shape(self):
        df = _make_tv_df(n=10)
        result = prepare_training_data(df, TV_CONFIG)
        split = split_train_valid(
            result,
            input_cols=TV_CONFIG.input_cols,
            output_cols=TV_CONFIG.output_cols,
            test_size=0.0,
            seed=1750,
        )
        assert split["x_full"].shape[1] == len(TV_CONFIG.input_cols)
        assert split["y"].shape[1] == len(TV_CONFIG.output_cols)
