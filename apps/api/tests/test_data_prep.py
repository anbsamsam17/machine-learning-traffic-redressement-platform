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

    If use_aliases=True, uses legacy column names (TMJATV, TxPen) instead
    of standard names (TMJAFCDTV, TxPenTVRef).
    """
    rng = np.random.default_rng(1750)
    data = {
        "car_average_distance_km": rng.uniform(5, 50, n),
        "car_average_speed_kmh": rng.uniform(30, 130, n),
        "truck_min_average_distance_km": rng.uniform(10, 80, n),
        "truck_average_speed_kmh": rng.uniform(40, 90, n),
        "TMJABCTV": rng.uniform(500, 20000, n),
        "Type": rng.choice(["Per", "Tou", "Pon"], n),
    }
    if use_aliases:
        data["TMJATV"] = rng.uniform(100, 5000, n)
        data["TMJAPL"] = rng.uniform(50, 1000, n)
        data["TxPen"] = data["TMJATV"] / data["TMJABCTV"] * 100
    else:
        data["TMJAFCDTV"] = rng.uniform(100, 5000, n)
        data["TMJAFCDPL"] = rng.uniform(50, 1000, n)
        data["TxPenTVRef"] = data["TMJAFCDTV"] / data["TMJABCTV"] * 100

    return pd.DataFrame(data)


def _make_pl_df(n: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(1750)
    return pd.DataFrame({
        "TMJAFCDPL": rng.uniform(50, 1000, n),
        "car_average_distance_km": rng.uniform(5, 50, n),
        "car_average_speed_kmh": rng.uniform(30, 130, n),
        "truck_min_average_distance_km": rng.uniform(10, 80, n),
        "truck_average_speed_kmh": rng.uniform(40, 90, n),
        "TxPenPLRef": rng.uniform(1, 30, n),
        "TMJABCPL": rng.uniform(100, 5000, n),
    })


# ---------------------------------------------------------------------------
# _resolve_aliases
# ---------------------------------------------------------------------------

class TestResolveAliases:
    def test_tv_aliases_create_standard_cols(self):
        df = pd.DataFrame({
            "TMJATV": [100.0, 200.0],
            "TMJAPL": [50.0, 60.0],
            "TxPen": [10.1234, 20.5678],
        })
        result = _resolve_aliases(df, TV_CONFIG)
        assert "TMJAFCDTV" in result.columns
        assert "TMJAFCDPL" in result.columns
        assert "TxPenTVRef" in result.columns
        # Check rounding: TxPen -> TxPenTVRef rounds to 4 decimals
        np.testing.assert_allclose(result["TxPenTVRef"].values, [10.1234, 20.5678])

    def test_no_overwrite_existing_col(self):
        """If destination column already exists, alias should NOT overwrite it."""
        df = pd.DataFrame({
            "TMJATV": [999.0],
            "TMJAFCDTV": [123.0],
        })
        result = _resolve_aliases(df, TV_CONFIG)
        assert result["TMJAFCDTV"].iloc[0] == 123.0  # not overwritten

    def test_pl_aliases(self):
        df = pd.DataFrame({
            "TMJAPL": [100.0],
            "TxPenPL": [15.0],
        })
        result = _resolve_aliases(df, PL_CONFIG)
        assert "TMJAFCDPL" in result.columns
        assert "TxPenPLRef" in result.columns

    def test_tmjfcdtv_alias(self):
        """TMJFCDTV -> TMJAFCDTV alias from TV_CONFIG."""
        df = pd.DataFrame({"TMJFCDTV": [500.0]})
        result = _resolve_aliases(df, TV_CONFIG)
        assert "TMJAFCDTV" in result.columns
        np.testing.assert_allclose(result["TMJAFCDTV"].values, [500.0])


# ---------------------------------------------------------------------------
# _derive_target
# ---------------------------------------------------------------------------

class TestDeriveTarget:
    def test_tv_derives_txpentvref_from_bc_fcd(self):
        df = pd.DataFrame({
            "TMJAFCDTV": [1000.0, 2000.0],
            "TMJABCTV": [5000.0, 10000.0],
        })
        result = _derive_target(df, TV_CONFIG)
        assert "TxPenTVRef" in result.columns
        expected = [1000.0 / 5000.0 * 100, 2000.0 / 10000.0 * 100]
        np.testing.assert_allclose(result["TxPenTVRef"].values, expected)

    def test_does_not_overwrite_existing_target(self):
        df = pd.DataFrame({
            "TMJAFCDTV": [1000.0],
            "TMJABCTV": [5000.0],
            "TxPenTVRef": [99.0],
        })
        result = _derive_target(df, TV_CONFIG)
        assert result["TxPenTVRef"].iloc[0] == 99.0

    def test_zero_bc_produces_zero_via_fillna(self):
        """When TMJABCTV=0, mask is False, TxPenTVRef filled to 0."""
        df = pd.DataFrame({
            "TMJAFCDTV": [1000.0],
            "TMJABCTV": [0.0],
        })
        result = _derive_target(df, TV_CONFIG)
        assert result["TxPenTVRef"].iloc[0] == 0.0

    def test_pl_target_derivation(self):
        df = pd.DataFrame({
            "TMJAFCDPL": [500.0],
            "TMJABCPL": [2000.0],
        })
        result = _derive_target(df, PL_CONFIG)
        assert "TxPenPLRef" in result.columns
        np.testing.assert_allclose(result["TxPenPLRef"].values, [25.0])


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
        for col in TV_CONFIG.input_cols + TV_CONFIG.output_cols:
            assert col in result.columns

    def test_aliases_resolved(self):
        df = _make_tv_df(n=10, use_aliases=True)
        result = prepare_training_data(df, TV_CONFIG)
        assert "TMJAFCDTV" in result.columns
        assert "TxPenTVRef" in result.columns

    def test_target_derived_when_missing(self):
        """TxPenTVRef should be derived from TMJABCTV if not present."""
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "TMJAFCDTV": rng.uniform(100, 5000, 10),
            "TMJAFCDPL": rng.uniform(50, 1000, 10),
            "car_average_distance_km": rng.uniform(5, 50, 10),
            "car_average_speed_kmh": rng.uniform(30, 130, 10),
            "truck_min_average_distance_km": rng.uniform(10, 80, 10),
            "truck_average_speed_kmh": rng.uniform(40, 90, 10),
            "TMJABCTV": rng.uniform(500, 20000, 10),
        })
        result = prepare_training_data(df, TV_CONFIG)
        assert "TxPenTVRef" in result.columns
        assert result["TxPenTVRef"].notna().all()

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
        assert "flag_comptage" in result.columns

    def test_pl_pipeline(self):
        df = _make_pl_df(n=10)
        result = prepare_training_data(df, PL_CONFIG)
        for col in PL_CONFIG.input_cols + PL_CONFIG.output_cols:
            assert col in result.columns


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
        assert set(np.unique(sw)).issubset({1.0, 4.0})

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
