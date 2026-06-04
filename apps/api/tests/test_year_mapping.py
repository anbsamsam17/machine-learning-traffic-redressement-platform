"""Tests for robust year mapping (float / int / str) + API overrides.

Bug context: the carte/eval pipeline encoded the year via
``data[year_col].astype(str).map(year_value_mapping)``. When the year column
was a float (``2024.0``), the key ``"2024.0"`` did not match the dict key
``"2024"`` -> all NaN -> fallback to the mean -> the year stopped mattering.

These tests exercise the canonicalisation helpers and ``_apply_year_mapping``
without TensorFlow / GPU. Seed fixe 1750 pour reproductibilite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services.ml.inference import (
    _apply_year_mapping,
    _normalize_year_keys,
    _normalize_year_mapping_keys,
)

SEED = 1750

# Canonical mapping: 2023 -> 1, 2024 -> 2, 2025 -> 3.
YEAR_MAPPING = {"2023": 1, "2024": 2, "2025": 3}


# ---------------------------------------------------------------------------
# Synthetic DataFrame builders (10 rows max)
# ---------------------------------------------------------------------------

def _make_df(annee_values, col_name: str = "Annee") -> pd.DataFrame:
    """Build a 10-row synthetic DataFrame with an Annee column."""
    rng = np.random.default_rng(SEED)
    n = len(annee_values)
    return pd.DataFrame(
        {
            col_name: annee_values,
            "TMJOFCDTV": rng.uniform(100, 20000, n),
        }
    )


def _config(input_cols=None, mapping=None, col="Annee") -> dict:
    return {
        "input_cols": input_cols if input_cols is not None else ["year_mapped"],
        "year_column_name": col,
        "year_value_mapping": mapping if mapping is not None else YEAR_MAPPING,
    }


# ---------------------------------------------------------------------------
# Helper-level tests
# ---------------------------------------------------------------------------

def test_normalize_year_keys_int():
    s = pd.Series([2023, 2024, 2025])
    assert _normalize_year_keys(s).tolist() == ["2023", "2024", "2025"]


def test_normalize_year_keys_float():
    s = pd.Series([2023.0, 2024.0, 2025.0])
    assert _normalize_year_keys(s).tolist() == ["2023", "2024", "2025"]


def test_normalize_year_keys_str():
    s = pd.Series(["2023", "2024", "2025"])
    assert _normalize_year_keys(s).tolist() == ["2023", "2024", "2025"]


def test_normalize_year_keys_non_integer_float_kept():
    s = pd.Series([2024.5])
    assert _normalize_year_keys(s).tolist() == ["2024.5"]


def test_normalize_year_keys_non_numeric_kept():
    s = pd.Series(["intervalle", "2024"])
    assert _normalize_year_keys(s).tolist() == ["intervalle", "2024"]


def test_normalize_year_mapping_keys_collapses_dtypes():
    # int, float-as-str and str keys all collapse to canonical str keys.
    mapping = {2023: 1, "2024.0": 2, "2025": 3}
    out = _normalize_year_mapping_keys(mapping)
    assert out == {"2023": 1, "2024": 2, "2025": 3}


def test_normalize_year_mapping_keys_empty():
    assert _normalize_year_mapping_keys({}) == {}


# ---------------------------------------------------------------------------
# (a) 2024 maps to the right value whatever the dtype
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "annee_values",
    [
        [2023, 2024, 2025],          # int
        [2023.0, 2024.0, 2025.0],    # float -> the original bug
        ["2023", "2024", "2025"],    # str
    ],
)
def test_year_mapped_correct_for_any_dtype(annee_values):
    df = _make_df(annee_values)
    out = _apply_year_mapping(df, _config())
    # 2024 -> 2 regardless of dtype.
    assert out["year_mapped"].tolist() == [1.0, 2.0, 3.0]
    # No NaN -> no silent fallback to the mean.
    assert out["year_mapped"].notna().all()


def test_float_year_not_collapsed_to_mean():
    """Regression guard: the float bug previously produced all-NaN -> mean."""
    df = _make_df([2023.0, 2024.0, 2025.0])
    out = _apply_year_mapping(df, _config())
    # If the bug were present every row would equal the mean (here 2.0),
    # erasing the per-year signal. Assert the values are distinct.
    assert out["year_mapped"].nunique() == 3


# ---------------------------------------------------------------------------
# (b) mapping override takes priority over config
# ---------------------------------------------------------------------------

def test_mapping_override_wins_over_config():
    df = _make_df([2023, 2024, 2025])
    override = {"2023": 10, "2024": 20, "2025": 30}
    out = _apply_year_mapping(
        df,
        _config(mapping={"2023": 1, "2024": 2, "2025": 3}),
        year_mapping_override=override,
    )
    assert out["year_mapped"].tolist() == [10.0, 20.0, 30.0]


def test_mapping_override_triggers_without_input_cols():
    """An override forces mapping even when year_mapped is not in input_cols."""
    df = _make_df([2024.0])
    out = _apply_year_mapping(
        df,
        {"input_cols": ["TMJOFCDTV"]},  # year_mapped NOT requested
        year_mapping_override={"2024": 42},
    )
    assert out["year_mapped"].tolist() == [42.0]


def test_override_with_no_config_at_all():
    df = _make_df([2024])
    out = _apply_year_mapping(
        df,
        None,
        year_column_override="Annee",
        year_mapping_override={"2024": 7},
    )
    assert out["year_mapped"].tolist() == [7.0]


# ---------------------------------------------------------------------------
# (c) column override
# ---------------------------------------------------------------------------

def test_column_override():
    df = _make_df([2023, 2024, 2025], col_name="MyYear")
    out = _apply_year_mapping(
        df,
        _config(col="Annee"),  # config points at the wrong column
        year_column_override="MyYear",
    )
    assert out["year_mapped"].tolist() == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# (d) fallback when the year column is absent
# ---------------------------------------------------------------------------

def test_fallback_when_year_column_missing():
    # No Annee column -> constant median value of the mapping (median of
    # sorted [1, 2, 3] = 2).
    df = pd.DataFrame({"TMJOFCDTV": [100.0, 200.0, 300.0]})
    out = _apply_year_mapping(df, _config())
    assert out["year_mapped"].tolist() == [2, 2, 2]


def test_year_column_resolved_case_insensitively():
    """Regression (Lyon 2023): carte.SOURCE_TO_CANONICAL renames 'Annee'->'annee'
    BEFORE _apply_year_mapping, which looked for 'Annee' literally -> not found ->
    year_mapped frozen to the mapping median (constant). The resolver must match
    the column case-insensitively so the real per-year encoding is applied."""
    df = _make_df([2023, 2024, 2025], col_name="annee")  # lowercased column
    out = _apply_year_mapping(
        df,
        _config(col="Annee"),          # config still uses the capitalised name
        year_column_override="Annee",  # UI sends "Annee" too
    )
    assert out["year_mapped"].tolist() == [1.0, 2.0, 3.0]
    assert out["year_mapped"].nunique() == 3  # NOT a constant


def test_no_trigger_when_not_needed():
    """Without use_year_feature / year_mapped / override, data is untouched."""
    df = _make_df([2024])
    out = _apply_year_mapping(df, {"input_cols": ["TMJOFCDTV"]})
    assert "year_mapped" not in out.columns


def test_unmapped_years_filled_with_mean():
    """Years absent from the mapping are filled with the mean of mapped rows."""
    df = _make_df([2024, 2099])  # 2099 not in mapping
    out = _apply_year_mapping(df, _config())
    # 2024 -> 2 ; 2099 -> NaN -> filled with mean of mapped (= 2.0).
    assert out["year_mapped"].tolist() == [2.0, 2.0]
    assert out["year_mapped"].notna().all()
