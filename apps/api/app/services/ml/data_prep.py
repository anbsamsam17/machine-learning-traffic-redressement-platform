"""Data preparation for training: column aliases, target derivation, split.

Exact reproduction of ``prepare_training_data()`` from
``xScripts/CreateMDL_TV.py`` / ``CreateMDL_PL.py``, unified via
``ModelTypeConfig``.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .types import ModelTypeConfig


def _resolve_aliases(
    df: pd.DataFrame, type_config: ModelTypeConfig
) -> pd.DataFrame:
    """Apply column aliases defined in *type_config* (in-place on copy)."""
    for src, dst in type_config.column_aliases.items():
        if src in df.columns and dst not in df.columns:
            df[dst] = pd.to_numeric(df[src], errors="coerce").round(
                4 if "TxPen" in dst else 2
            )
    return df


def _derive_target(
    df: pd.DataFrame, type_config: ModelTypeConfig
) -> pd.DataFrame:
    """Compute target column (TxPenTVRef / TxPenPLRef) from BC / FCD if missing."""
    target = type_config.target_col
    bc_col = type_config.target_denominator_bc
    fcd_col = type_config.target_numerator_fcd

    if bc_col in df.columns and target not in df.columns:
        if fcd_col in df.columns:
            bc = pd.to_numeric(df[bc_col], errors="coerce")
            fcd = pd.to_numeric(df[fcd_col], errors="coerce")
            mask = (bc > 0) & fcd.notna()
            df.loc[mask, target] = fcd[mask] / bc[mask] * 100.0
        df[target] = df.get(target, pd.Series(dtype=float)).fillna(0)

    return df


def _derive_flag_comptage(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``flag_comptage`` if absent (same logic as original scripts)."""
    if "flag_comptage" not in df.columns:
        if "Type" in df.columns:
            types = df["Type"].astype(str).str.strip().str.lower()
            df["flag_comptage"] = types.isin(["per", "tou"]).astype(int)
        else:
            df["flag_comptage"] = 0
    return df


def _apply_year_mapping(
    df: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    """Create ``year_mapped`` column from config if needed."""
    if "year_mapped" not in config.get("input_cols", []):
        return df

    year_column = config.get("year_column_name")
    year_mapping = config.get("year_value_mapping", {})

    if year_column and year_column in df.columns and year_mapping:
        df["year_mapped"] = df[year_column].astype(str).map(year_mapping)
        if df["year_mapped"].isna().any():
            mean_val = df["year_mapped"].mean()
            df["year_mapped"] = df["year_mapped"].fillna(mean_val)
    else:
        if year_mapping:
            median_value = sorted(year_mapping.values())[len(year_mapping) // 2]
        else:
            median_value = 0
        df["year_mapped"] = median_value

    return df


def prepare_training_data(
    df_raw: pd.DataFrame,
    type_config: ModelTypeConfig,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Full preprocessing: aliases, target derivation, year mapping, dropna.

    Parameters
    ----------
    df_raw : raw DataFrame (e.g. from GeoJSON upload).
    type_config : TV_CONFIG or PL_CONFIG.
    config : user-supplied training configuration dict (optional).

    Returns
    -------
    Cleaned DataFrame ready for feature / target extraction.
    """
    config = config or {}
    input_cols = list(config.get("input_cols", type_config.input_cols))
    output_cols = list(config.get("output_cols", type_config.output_cols))

    gdf = df_raw.copy()

    # Step 1: resolve aliases
    gdf = _resolve_aliases(gdf, type_config)

    # Step 2: derive target
    gdf = _derive_target(gdf, type_config)

    # Step 3: flag_comptage
    gdf = _derive_flag_comptage(gdf)

    # Step 4: year mapping
    gdf = _apply_year_mapping(gdf, config)

    # Step 5: check required columns
    required_cols = [*input_cols, *output_cols]
    missing_cols = [c for c in required_cols if c not in gdf.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns in training data: {missing_cols}")

    df = gdf.dropna(subset=required_cols).copy()
    if df.empty:
        nan_info = {col: int(gdf[col].isna().sum()) for col in required_cols}
        raise ValueError(
            f"Training dataset is empty after dropna on required columns.\n"
            f"  NaN par colonne requise : {nan_info}"
        )

    return df


def split_train_valid(
    df: pd.DataFrame,
    input_cols: list[str],
    output_cols: list[str],
    test_size: float,
    seed: int,
    use_flag_comptage_weighting: bool = False,
    flag_comptage_col: str = "flag_comptage",
    flag_priority_weight: float = 4.0,
) -> dict[str, Any]:
    """Split into train / valid arrays and compute sample weights.

    Returns a dict with keys:
        x_full, y, idx_train, idx_valid,
        y_train, y_valid,
        train_sample_weight, valid_sample_weight
    """
    x_full = df[input_cols].values.astype(float)
    y = df[output_cols].values.astype(float)

    if 0 < test_size < 1:
        indices = np.arange(len(x_full))
        idx_train, idx_valid = train_test_split(
            indices, test_size=test_size, random_state=seed
        )
        y_train = y[idx_train]
        y_valid = y[idx_valid]
    else:
        idx_train = np.arange(len(x_full))
        idx_valid = None
        y_train = y
        y_valid = None

    # Sample weights
    train_sample_weight = None
    valid_sample_weight = None
    if use_flag_comptage_weighting and flag_comptage_col in df.columns:
        flag_series = pd.to_numeric(df[flag_comptage_col], errors="coerce").fillna(0)
        all_sw = np.where(
            flag_series.values == 1, flag_priority_weight, 1.0
        ).astype(float)
        train_sample_weight = all_sw[idx_train]
        if idx_valid is not None:
            valid_sample_weight = all_sw[idx_valid]

        # Normalise so sum(weights) == N_train: keeps the effective LR
        # stable and lets EarlyStopping compare losses across weighted /
        # non-weighted runs.
        n = len(train_sample_weight)
        total = float(train_sample_weight.sum())
        if total > 0:
            train_sample_weight = train_sample_weight * (n / total)

        if valid_sample_weight is not None:
            n_v = len(valid_sample_weight)
            total_v = float(valid_sample_weight.sum())
            if total_v > 0:
                valid_sample_weight = valid_sample_weight * (n_v / total_v)

    return {
        "x_full": x_full,
        "y": y,
        "idx_train": idx_train,
        "idx_valid": idx_valid,
        "y_train": y_train,
        "y_valid": y_valid,
        "train_sample_weight": train_sample_weight,
        "valid_sample_weight": valid_sample_weight,
    }
