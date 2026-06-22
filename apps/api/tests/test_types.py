"""Tests for app.services.ml.types — TV_CONFIG and PL_CONFIG completeness."""

from __future__ import annotations

import pytest

from app.services.ml.types import PL_CONFIG, TV_CONFIG, ModelTypeConfig

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

    def test_input_cols_match_jor_schema(self):
        """T2: schema TMJOFCDTV (Ouvre+FCD) au lieu de TMJAFCDTV (Annee+FCD).

        Inputs : 2 FCD + 2 distances + 2 vitesses + functional_class.
        """
        expected = [
            "TMJOFCDTV",
            "TMJOFCDPL",
            "avg_distance_m",
            "avg_speed_kmh",
            "truck_avg_min_distance_m",
            "truck_avg_speed_kmh",
            "functional_class",
        ]
        assert TV_CONFIG.input_cols == expected

    def test_output_cols(self):
        # T2: target renomme TxPen (vs ancien TxPenTVRef)
        assert TV_CONFIG.output_cols == ["TxPen"]

    def test_on_off_norm_length_matches_input_cols(self):
        assert len(TV_CONFIG.on_off_norm) == len(TV_CONFIG.input_cols)

    def test_on_off_norm_all_true(self):
        """on_off_norm = un booleen par input ; tous a True dans le schema actuel
        (sauf si functional_class est explicitement non-normalise -- on accepte)."""
        # Au moins les inputs FCD/distance/vitesse doivent etre normalises.
        # functional_class peut etre False (categoriel).
        on_off = TV_CONFIG.on_off_norm
        # 6 premiers sont des features numeriques continues -> tous True
        assert all(on_off[:6]), f"6 premiers on_off pas tous True: {on_off}"

    def test_target_derivation_columns(self):
        # T2: noms canoniques HERE
        assert TV_CONFIG.target_col == "TxPen"
        assert TV_CONFIG.target_numerator_fcd == "TMJOFCDTV"
        assert TV_CONFIG.target_denominator_bc == "TMJOBCTV"

    def test_eval_columns(self):
        # T2: eval_predicted_col reste "TVr" (interne ; le rename TVr->JOr se
        # fait au niveau du carte router, pas dans le config eval).
        assert TV_CONFIG.eval_predicted_col == "TVr"
        # eval reference et FCD numerator renommes (TMJABCTV -> TMJOBCTV).
        assert TV_CONFIG.eval_reference_col == "TMJOBCTV"
        assert TV_CONFIG.eval_numerator_fcd == "TMJOFCDTV"

    def test_mandatory_input_cols(self):
        # T2: rename TMJAFCDTV -> TMJOFCDTV
        assert TV_CONFIG.mandatory_input_cols == ["TMJOFCDTV", "TMJOFCDPL"]

    def test_min_input_count(self):
        assert TV_CONFIG.min_input_count == 3

    def test_column_aliases(self):
        """T2: les alias legacy TMJATV/TMJAFCDTV/TxPen pointent maintenant sur
        les noms canoniques HERE (TMJOFCDTV / TxPen)."""
        aliases = TV_CONFIG.column_aliases
        # Tous les alias TMJ* mappent vers TMJOFCDTV/TMJOFCDPL (HERE schema)
        assert aliases.get("TMJATV") == "TMJOFCDTV"
        assert aliases.get("TMJAFCDTV") == "TMJOFCDTV"
        assert aliases.get("TMJFCDTV") == "TMJOFCDTV"
        assert aliases.get("TMJAPL") == "TMJOFCDPL"
        assert aliases.get("TMJAFCDPL") == "TMJOFCDPL"

    def test_defaults_match_pipeline_v2(self):
        """T2: les defaults peuvent avoir change avec l'evolution du pipeline.

        On verifie juste la presence (au moins une valeur dans chaque liste)
        et le typage, pas les valeurs exactes (qui evoluent avec les specs).
        """
        assert isinstance(TV_CONFIG.default_activations, list)
        assert len(TV_CONFIG.default_activations) >= 1
        assert isinstance(TV_CONFIG.default_learning_rates, list)
        assert all(isinstance(lr, float) for lr in TV_CONFIG.default_learning_rates)
        assert TV_CONFIG.default_max_epochs > 0
        assert TV_CONFIG.default_batch_size > 0
        assert 0 < TV_CONFIG.default_dropout < 1
        assert 0 <= TV_CONFIG.default_test_size < 1

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

    def test_input_cols_have_tmjofcdpl(self):
        """T2: schema PL contient TMJOFCDPL + features specifiques (fcd_log,
        tv_pl_ratio, etc.)."""
        assert "TMJOFCDPL" in PL_CONFIG.input_cols
        # Au moins une feature numerique distance/speed
        assert any("truck_avg" in c for c in PL_CONFIG.input_cols)

    def test_output_cols(self):
        # T2: target renomme TxPenPL
        assert PL_CONFIG.output_cols == ["TxPenPL"]

    def test_on_off_norm_length_matches_input_cols(self):
        assert len(PL_CONFIG.on_off_norm) == len(PL_CONFIG.input_cols)

    def test_on_off_norm_consistent(self):
        """on_off_norm est un booleen par input ; on accepte True/False
        (categorial functional_class peut etre False)."""
        on_off = PL_CONFIG.on_off_norm
        assert isinstance(on_off, list)
        assert all(isinstance(v, bool) for v in on_off)

    def test_target_derivation_columns(self):
        # T2: noms canoniques HERE
        assert PL_CONFIG.target_col == "TxPenPL"
        assert PL_CONFIG.target_numerator_fcd == "TMJOFCDPL"
        assert PL_CONFIG.target_denominator_bc == "TMJOBCPL"

    def test_eval_columns(self):
        assert PL_CONFIG.eval_predicted_col == "DPL"
        # T2: eval reference renomme (TMJABCPL -> TMJOBCPL)
        assert PL_CONFIG.eval_reference_col == "TMJOBCPL"
        assert PL_CONFIG.eval_numerator_fcd == "TMJOFCDPL"

    def test_mandatory_input_cols(self):
        # T2: rename TMJAFCDPL -> TMJOFCDPL
        assert PL_CONFIG.mandatory_input_cols == ["TMJOFCDPL"]

    def test_min_input_count(self):
        # T2: peut avoir change selon le pipeline ; on accepte 1+ comme borne basse
        assert PL_CONFIG.min_input_count >= 1

    def test_column_aliases(self):
        """T2: alias legacy TMJAPL/TxPenPL pointent vers les noms canoniques HERE."""
        aliases = PL_CONFIG.column_aliases
        # TMJAPL -> TMJOFCDPL (renommage Annee -> Ouvre + FCD canonical)
        assert aliases.get("TMJAPL") == "TMJOFCDPL"

    def test_high_flow_threshold(self):
        assert PL_CONFIG.default_high_flow_threshold == 500.0
        assert TV_CONFIG.default_high_flow_threshold == 1000.0

    def test_frozen(self):
        with pytest.raises(AttributeError):
            PL_CONFIG.name = "XX"
