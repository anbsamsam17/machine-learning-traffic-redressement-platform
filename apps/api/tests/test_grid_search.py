"""Tests for app.services.ml.grid_search — feature subsets and grid combinations."""

from __future__ import annotations

import pytest

from app.services.ml.grid_search import (
    GridCombination,
    build_feature_sets,
    feature_mask_name,
    generate_all_combinations,
)

# ---------------------------------------------------------------------------
# build_feature_sets
# ---------------------------------------------------------------------------


class TestBuildFeatureSets:
    ALL_COLS = ["A", "B", "C", "D"]

    def test_no_grid_returns_all(self):
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=["A"],
            min_input_count=1,
            enable_feature_subset_grid=False,
        )
        assert result == [self.ALL_COLS]

    def test_all_mandatory_returns_single_set(self):
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=self.ALL_COLS,
            min_input_count=4,
            enable_feature_subset_grid=True,
        )
        assert len(result) == 1
        assert set(result[0]) == set(self.ALL_COLS)

    def test_mandatory_always_present(self):
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=["A"],
            min_input_count=1,
            enable_feature_subset_grid=True,
        )
        for fs in result:
            assert "A" in fs

    def test_min_input_count_enforced(self):
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=["A"],
            min_input_count=3,
            enable_feature_subset_grid=True,
        )
        for fs in result:
            assert len(fs) >= 3

    def test_total_combinations_count(self):
        """With 4 cols, 1 mandatory, min_input=1: 2^3 = 8 optional subsets."""
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=["A"],
            min_input_count=1,
            enable_feature_subset_grid=True,
        )
        # optional = [B, C, D] => subsets of size 0..3 = C(3,0)+C(3,1)+C(3,2)+C(3,3) = 8
        assert len(result) == 8

    def test_order_preserved(self):
        """Output column order should match all_input_cols order."""
        result = build_feature_sets(
            self.ALL_COLS,
            mandatory_cols=["A"],
            min_input_count=1,
            enable_feature_subset_grid=True,
        )
        for fs in result:
            indices = [self.ALL_COLS.index(c) for c in fs]
            assert indices == sorted(indices)

    def test_missing_mandatory_raises(self):
        with pytest.raises(ValueError, match="Mandatory columns are not part of input-cols"):
            build_feature_sets(
                self.ALL_COLS,
                mandatory_cols=["X"],
                min_input_count=1,
                enable_feature_subset_grid=True,
            )

    def test_min_input_less_than_mandatory_raises(self):
        with pytest.raises(ValueError, match="min-input-count"):
            build_feature_sets(
                self.ALL_COLS,
                mandatory_cols=["A", "B"],
                min_input_count=1,
                enable_feature_subset_grid=True,
            )

    def test_tv_default_config(self):
        """Test with actual TV input cols and mandatory cols."""
        input_cols = [
            "TMJAFCDTV",
            "TMJAFCDPL",
            "car_average_distance_km",
            "car_average_speed_kmh",
            "truck_min_average_distance_km",
            "truck_average_speed_kmh",
        ]
        mandatory = ["TMJAFCDTV", "TMJAFCDPL"]
        result = build_feature_sets(
            input_cols,
            mandatory_cols=mandatory,
            min_input_count=3,
            enable_feature_subset_grid=True,
        )
        # 4 optional, min 1 optional => C(4,1)+C(4,2)+C(4,3)+C(4,4) = 4+6+4+1 = 15
        assert len(result) == 15
        for fs in result:
            assert "TMJAFCDTV" in fs
            assert "TMJAFCDPL" in fs
            assert len(fs) >= 3

    def test_empty_mandatory_list(self):
        result = build_feature_sets(
            ["A", "B"],
            mandatory_cols=[],
            min_input_count=0,
            enable_feature_subset_grid=True,
        )
        # All subsets including empty set: C(2,0)+C(2,1)+C(2,2) = 1+2+1 = 4
        assert len(result) == 4


# ---------------------------------------------------------------------------
# feature_mask_name
# ---------------------------------------------------------------------------


class TestFeatureMaskName:
    def test_all_features(self):
        all_cols = ["A", "B", "C"]
        result = feature_mask_name(["A", "B", "C"], all_cols)
        assert result == "fmask_111"

    def test_subset(self):
        all_cols = ["A", "B", "C", "D"]
        result = feature_mask_name(["A", "C"], all_cols)
        assert result == "fmask_1010"

    def test_single_feature(self):
        all_cols = ["A", "B", "C"]
        result = feature_mask_name(["B"], all_cols)
        assert result == "fmask_010"

    def test_empty_features(self):
        all_cols = ["A", "B"]
        result = feature_mask_name([], all_cols)
        assert result == "fmask_00"


# ---------------------------------------------------------------------------
# generate_all_combinations
# ---------------------------------------------------------------------------


class TestGenerateAllCombinations:
    def test_single_feature_set_single_params(self):
        combos = generate_all_combinations(
            feature_sets=[["A", "B"]],
            all_input_cols=["A", "B", "C"],
            activations=["elu"],
            learning_rates=[0.01],
            min_nb_epochs_list=[500],
        )
        assert len(combos) == 1
        c = combos[0]
        assert isinstance(c, GridCombination)
        assert c.feature_cols == ["A", "B"]
        assert c.activation == "elu"
        assert c.learning_rate == 0.01
        assert c.min_nb_epochs == 500
        assert c.feature_mask == "fmask_110"

    def test_cartesian_product_count(self):
        combos = generate_all_combinations(
            feature_sets=[["A"], ["A", "B"]],
            all_input_cols=["A", "B"],
            activations=["elu", "relu"],
            learning_rates=[0.01, 0.001],
            min_nb_epochs_list=[500, 1000],
        )
        # 2 feature_sets * 2 activations * 2 lr * 2 epochs * 1 loss * 1 dropout * 1 nf * 1 bs = 16
        assert len(combos) == 16

    def test_run_name_format(self):
        combos = generate_all_combinations(
            feature_sets=[["A", "B"]],
            all_input_cols=["A", "B"],
            activations=["elu"],
            learning_rates=[0.01],
            min_nb_epochs_list=[500],
            losses=["mse"],
            dropouts=[0.05],
            neurons_factors_list=[[1.0, 1.0]],
            batch_sizes=[256],
        )
        c = combos[0]
        assert c.run_name == "elu_lr0.01_ep500_mse_drp0.05_nf1.0x1.0_bs256_fmask_11"

    def test_all_run_names_unique(self):
        combos = generate_all_combinations(
            feature_sets=[["A"], ["B"], ["A", "B"]],
            all_input_cols=["A", "B"],
            activations=["elu", "relu"],
            learning_rates=[0.01],
            min_nb_epochs_list=[500, 1000],
        )
        names = [c.run_name for c in combos]
        assert len(names) == len(set(names)), "Duplicate run_names found"

    def test_custom_neurons_factors(self):
        combos = generate_all_combinations(
            feature_sets=[["A"]],
            all_input_cols=["A"],
            activations=["elu"],
            learning_rates=[0.01],
            min_nb_epochs_list=[500],
            neurons_factors_list=[[2.0, 1.0, 0.5]],
        )
        assert combos[0].neurons_factors == [2.0, 1.0, 0.5]
        assert "nf2.0x1.0x0.5" in combos[0].run_name

    def test_multiple_batch_sizes(self):
        combos = generate_all_combinations(
            feature_sets=[["A"]],
            all_input_cols=["A"],
            activations=["elu"],
            learning_rates=[0.01],
            min_nb_epochs_list=[500],
            batch_sizes=[128, 256],
        )
        assert len(combos) == 2
        assert combos[0].batch_size == 128
        assert combos[1].batch_size == 256
