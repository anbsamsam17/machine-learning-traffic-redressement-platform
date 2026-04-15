"""Tests for app.services.ml.types — TV_CONFIG and PL_CONFIG completeness."""

from __future__ import annotations

import pytest

from app.services.ml.types import TV_CONFIG, PL_CONFIG, ModelTypeConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = [
    "name",
    "input_cols",
    "output_cols",
    "on_off_norm",
    "column_aliases",
    "target_col",
    "target_numerator_fcd",
    "target_denominator_bc",
    "target_alias",
    "eval_predicted_col",
    "eval_reference_col",
    "eval_numerator_fcd",
    "mandatory_input_cols",
    "min_input_count",
    "default_activations",
    "default_learning_rates",
    "default_min_nb_epochs",
    "default_max_epochs",
    "default_batch_size",
    "default_dropout",
    "default_test_size",
    "default_high_flow_threshold",
]


# ---------------------------------------------------------------------------
# TV_CONFIG
# ---------------------------------------------------------------------------

class TestTVConfig:
    def test_is_model_type_config(self):
        assert isinstance(TV_CONFIG, ModelTypeConfig)

    def test_has_all_required_fields(self):
        for field in REQUIRED_FIELDS:
            assert hasattr(TV_CONFIG, field), f"TV_CONFIG missing field: {field}"

    def test_name(self):
        assert TV_CONFIG.name == "TV"

    def test_input_cols_match_original(self):
        expected = [
            "TMJAFCDTV",
            "TMJAFCDPL",
            "car_average_distance_km",
            "car_average_speed_kmh",
            "truck_min_average_distance_km",
            "truck_average_speed_kmh",
        ]
        assert TV_CONFIG.input_cols == expected

    def test_output_cols(self):
        assert TV_CONFIG.output_cols == ["TxPenTVRef"]

    def test_on_off_norm_length_matches_input_cols(self):
        assert len(TV_CONFIG.on_off_norm) == len(TV_CONFIG.input_cols)

    def test_on_off_norm_all_true(self):
        """Original: ON_OFF_NORM = np.array([1, 1, 1, 1, 1, 1], dtype=bool)"""
        assert all(TV_CONFIG.on_off_norm)

    def test_target_derivation_columns(self):
        assert TV_CONFIG.target_col == "TxPenTVRef"
        assert TV_CONFIG.target_numerator_fcd == "TMJAFCDTV"
        assert TV_CONFIG.target_denominator_bc == "TMJABCTV"

    def test_eval_columns(self):
        assert TV_CONFIG.eval_predicted_col == "TVr"
        assert TV_CONFIG.eval_reference_col == "TMJABCTV"
        assert TV_CONFIG.eval_numerator_fcd == "TMJAFCDTV"

    def test_mandatory_input_cols(self):
        assert TV_CONFIG.mandatory_input_cols == ["TMJAFCDTV", "TMJAFCDPL"]

    def test_min_input_count(self):
        assert TV_CONFIG.min_input_count == 3

    def test_column_aliases(self):
        aliases = TV_CONFIG.column_aliases
        assert aliases["TMJATV"] == "TMJAFCDTV"
        assert aliases["TMJFCDTV"] == "TMJAFCDTV"
        assert aliases["TMJAPL"] == "TMJAFCDPL"
        assert aliases["TMJAVL"] == "TMJAFCDVL"
        assert aliases["TxPen"] == "TxPenTVRef"

    def test_defaults_match_original(self):
        assert TV_CONFIG.default_activations == ["elu"]
        assert TV_CONFIG.default_learning_rates == [0.01]
        assert TV_CONFIG.default_min_nb_epochs == [500, 1000]
        assert TV_CONFIG.default_max_epochs == 2050
        assert TV_CONFIG.default_batch_size == 256
        assert TV_CONFIG.default_dropout == 0.05
        assert TV_CONFIG.default_test_size == 0.0

    def test_frozen(self):
        """Config should be immutable."""
        with pytest.raises(AttributeError):
            TV_CONFIG.name = "XX"


# ---------------------------------------------------------------------------
# PL_CONFIG
# ---------------------------------------------------------------------------

class TestPLConfig:
    def test_is_model_type_config(self):
        assert isinstance(PL_CONFIG, ModelTypeConfig)

    def test_has_all_required_fields(self):
        for field in REQUIRED_FIELDS:
            assert hasattr(PL_CONFIG, field), f"PL_CONFIG missing field: {field}"

    def test_name(self):
        assert PL_CONFIG.name == "PL"

    def test_input_cols_match_original(self):
        expected = [
            "TMJAFCDPL",
            "car_average_distance_km",
            "car_average_speed_kmh",
            "truck_min_average_distance_km",
            "truck_average_speed_kmh",
        ]
        assert PL_CONFIG.input_cols == expected

    def test_output_cols(self):
        assert PL_CONFIG.output_cols == ["TxPenPLRef"]

    def test_on_off_norm_length_matches_input_cols(self):
        assert len(PL_CONFIG.on_off_norm) == len(PL_CONFIG.input_cols)

    def test_on_off_norm_all_true(self):
        assert all(PL_CONFIG.on_off_norm)

    def test_target_derivation_columns(self):
        assert PL_CONFIG.target_col == "TxPenPLRef"
        assert PL_CONFIG.target_numerator_fcd == "TMJAFCDPL"
        assert PL_CONFIG.target_denominator_bc == "TMJABCPL"

    def test_eval_columns(self):
        assert PL_CONFIG.eval_predicted_col == "DPL"
        assert PL_CONFIG.eval_reference_col == "TMJABCPL"
        assert PL_CONFIG.eval_numerator_fcd == "TMJAFCDPL"

    def test_mandatory_input_cols(self):
        assert PL_CONFIG.mandatory_input_cols == ["TMJAFCDPL"]

    def test_min_input_count(self):
        assert PL_CONFIG.min_input_count == 2

    def test_column_aliases(self):
        aliases = PL_CONFIG.column_aliases
        assert aliases["TMJAPL"] == "TMJAFCDPL"
        assert aliases["TMJAVL"] == "TMJAFCDVL"
        assert aliases["TxPenPL"] == "TxPenPLRef"

    def test_high_flow_threshold(self):
        assert PL_CONFIG.default_high_flow_threshold == 500.0
        assert TV_CONFIG.default_high_flow_threshold == 1000.0

    def test_frozen(self):
        with pytest.raises(AttributeError):
            PL_CONFIG.name = "XX"
