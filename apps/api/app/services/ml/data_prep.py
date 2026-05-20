"""Data preparation for training: column aliases, target derivation, split.

Exact reproduction of ``prepare_training_data()`` from
``xScripts/CreateMDL_TV.py`` / ``CreateMDL_PL.py``, unified via
``ModelTypeConfig``.

Phase 2A / 2B additions (all opt-in via config flags — defaults preserve
the original behaviour):

* P2A.4 – continuous sample weights ``log1p(TMJOBCTV)`` instead of the
  binary flag-based weighting. Sum is renormalised to ``N_train`` to keep
  the effective learning rate stable.
* P2A.5 – target transform ``log1p(TxPen)`` applied BEFORE normalisation.
  The flag is round-tripped via the artifact ``training_config`` dict so
  evaluation can apply ``expm1`` at inference.
* P2B.1 – derived feature ``ratio_PLTV = TMJOFCDPL / max(TMJOFCDTV, 1)``.
* P2B.2 – per-column ``log1p`` augmentation under ``log_<col>``.
* P2B.3 – one-hot expansion of ``functional_class`` into ``fc_1..fc_5``.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .types import ModelTypeConfig

logger = logging.getLogger(__name__)

# Functional class levels we materialise as one-hot columns. The HERE
# road-network spec defines exactly five levels (1 = highway … 5 = local).
_FUNCTIONAL_CLASS_LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5)


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


# Candidate column names (case-insensitive) holding the counter category
# (Permanent / Siredo / Ponctuel / FCD …). The first match wins.
_PERMANENT_TYPE_CANDIDATES: tuple[str, ...] = (
    "type compteur",
    "type_compteur",
    "typecompteur",
    "type_de_compteur",
    "type",  # legacy short alias
)

# Values that count as "permanent" (the most trustworthy sensors). Match is
# case-insensitive and whitespace-stripped.
_PERMANENT_TYPE_VALUES: frozenset[str] = frozenset(
    {"permanent", "siredo", "per", "tou"}
)


def _find_type_compteur_column(df: pd.DataFrame) -> str | None:
    """Return the first DataFrame column matching a known 'type compteur' alias.

    Comparison is case-insensitive and ignores surrounding whitespace so we
    pick up ``"Type Compteur"``, ``"TYPE_COMPTEUR"``, ``" type compteur "`` …
    """
    normalized = {
        col: col.strip().lower().replace("-", " ").replace("_", " ")
        for col in df.columns
    }
    for candidate in _PERMANENT_TYPE_CANDIDATES:
        target = candidate.strip().lower().replace("-", " ").replace("_", " ")
        for col, norm in normalized.items():
            if norm == target:
                return col
    return None


def _derive_flag_permanent(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``flag_permanent`` (= 1 for Permanent / Siredo capteurs).

    Backward compat: the legacy column name ``flag_comptage`` is kept in
    sync so downstream code (evaluation_pipeline, kfold) keeps working
    unchanged.
    """
    if "flag_permanent" not in df.columns:
        type_col = _find_type_compteur_column(df)
        if type_col is not None:
            values = df[type_col].astype(str).str.strip().str.lower()
            df["flag_permanent"] = values.isin(_PERMANENT_TYPE_VALUES).astype(int)
        elif "flag_comptage" in df.columns:
            # Legacy datasets where the upstream mapping already produced
            # the binary column — adopt it as-is.
            df["flag_permanent"] = pd.to_numeric(
                df["flag_comptage"], errors="coerce"
            ).fillna(0).astype(int)
        else:
            df["flag_permanent"] = 0

    # Keep the legacy column name in sync for backward compatibility with
    # downstream consumers (evaluation_pipeline, kfold, evaluation router).
    if "flag_comptage" not in df.columns:
        df["flag_comptage"] = df["flag_permanent"]

    return df


# Legacy alias — preserved so any external caller importing the old name
# keeps working. New code must use ``_derive_flag_permanent``.
_derive_flag_comptage = _derive_flag_permanent


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


# ---------------------------------------------------------------------------
# P2B.1 / P2B.2 / P2B.3 — feature engineering helpers
# ---------------------------------------------------------------------------

def _fe_settings(
    type_config: ModelTypeConfig, config: dict[str, Any]
) -> dict[str, Any]:
    """Resolve feature-engineering flags from *type_config* and *config*.

    The config dict can either nest the flags under ``feature_engineering``
    (preferred — matches the task spec) or expose them at the top level.
    Either form silently falls back to ``ModelTypeConfig`` defaults so
    existing callers behave unchanged.
    """
    fe = dict(config.get("feature_engineering") or {})

    def _get(key: str, default: Any) -> Any:
        if key in fe:
            return fe[key]
        if key in config:
            return config[key]
        return default

    return {
        "add_pl_tv_ratio": bool(
            _get("add_pl_tv_ratio", type_config.add_pl_tv_ratio)
        ),
        "log_transform_cols": list(
            _get("log_transform_cols", type_config.log_transform_cols)
        ),
        "one_hot_functional_class": bool(
            _get(
                "one_hot_functional_class",
                type_config.one_hot_functional_class,
            )
        ),
    }


def _add_pl_tv_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """P2B.1 — add ``ratio_PLTV = TMJOFCDPL / max(TMJOFCDTV, 1)``."""
    if "TMJOFCDPL" not in df.columns or "TMJOFCDTV" not in df.columns:
        logger.debug(
            "ratio_PLTV skipped: missing TMJOFCDPL or TMJOFCDTV (have=%s)",
            sorted(df.columns.tolist()),
        )
        return df

    df = df.copy()
    pl = pd.to_numeric(df["TMJOFCDPL"], errors="coerce")
    tv = pd.to_numeric(df["TMJOFCDTV"], errors="coerce")
    # Guard against zero / NaN denominators: floor to 1.
    denom = tv.where(tv >= 1.0, 1.0)
    df["ratio_PLTV"] = (pl / denom).astype(float)
    return df


def _apply_log_transform_cols(
    df: pd.DataFrame, cols: list[str]
) -> pd.DataFrame:
    """P2B.2 — for each col in *cols* add ``log_<col> = log1p(col)``."""
    if not cols:
        return df

    new_cols: dict[str, pd.Series] = {}
    for col in cols:
        if col not in df.columns:
            logger.debug("log_transform skipped: column '%s' not found", col)
            continue
        values = pd.to_numeric(df[col], errors="coerce")
        # log1p is only defined for x >= -1; clip negatives to 0 so the
        # transform never produces NaN purely because of bad source data.
        values = values.where(values >= 0, 0)
        new_cols[f"log_{col}"] = np.log1p(values)

    if not new_cols:
        return df

    df = df.copy()
    for name, series in new_cols.items():
        df[name] = series
    return df


def _one_hot_functional_class(df: pd.DataFrame) -> pd.DataFrame:
    """P2B.3 — expand integer ``functional_class`` into ``fc_1..fc_5``."""
    if "functional_class" not in df.columns:
        logger.debug("one_hot_functional_class skipped: column missing")
        return df

    df = df.copy()
    fc = pd.to_numeric(df["functional_class"], errors="coerce")
    for level in _FUNCTIONAL_CLASS_LEVELS:
        df[f"fc_{level}"] = (fc == level).astype(int)
    df = df.drop(columns=["functional_class"])
    return df


def _apply_feature_engineering(
    df: pd.DataFrame, fe: dict[str, Any]
) -> pd.DataFrame:
    """Apply the configured P2B.* feature-engineering steps in order."""
    if fe["add_pl_tv_ratio"]:
        df = _add_pl_tv_ratio(df)
    if fe["log_transform_cols"]:
        df = _apply_log_transform_cols(df, fe["log_transform_cols"])
    if fe["one_hot_functional_class"]:
        df = _one_hot_functional_class(df)
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

    # Step 3: flag_permanent (capteurs Permanent / Siredo). Legacy
    # `flag_comptage` is kept synced for back-compat with evaluation_pipeline.
    gdf = _derive_flag_permanent(gdf)

    # Step 4: year mapping
    gdf = _apply_year_mapping(gdf, config)

    # Step 5: feature engineering (P2B.1 / P2B.2 / P2B.3). Done BEFORE the
    # required-column check so user-supplied input_cols can reference the
    # newly derived columns (ratio_PLTV, log_*, fc_1..fc_5).
    fe = _fe_settings(type_config, config)
    gdf = _apply_feature_engineering(gdf, fe)

    # Step 6: check required columns
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


def _compute_log_flow_weights(
    df: pd.DataFrame,
    flow_col: str,
) -> np.ndarray | None:
    """P2A.4 — continuous sample weights from ``log1p(flow_col)``.

    Returns ``None`` if the column is missing so the caller can fall back
    to the binary flag-based weighting (or no weighting at all).
    """
    if flow_col not in df.columns:
        logger.debug(
            "log_flow_weighting requested but column '%s' missing", flow_col
        )
        return None
    flow = pd.to_numeric(df[flow_col], errors="coerce").fillna(0.0)
    # log1p is monotonic and well-defined for flow >= 0; clip negatives.
    flow = flow.where(flow >= 0, 0.0)
    return np.log1p(flow.values).astype(float)


def split_train_valid(
    df: pd.DataFrame,
    input_cols: list[str],
    output_cols: list[str],
    test_size: float,
    seed: int,
    use_flag_permanent_weighting: bool = False,
    flag_permanent_col: str = "flag_permanent",
    flag_priority_weight: float = 4.0,
    *,
    use_log_flow_weighting: bool = False,
    log_flow_weighting_col: str = "TMJOBCTV",
    target_log_transform: bool = False,
    use_flag_recent_year_weighting: bool = False,
    recent_year_priority_weight: float = 2.0,
    recent_year_col: str = "year_mapped",
    # Backward-compatible aliases (deprecated — accepted with a warning):
    use_flag_comptage_weighting: bool | None = None,
    flag_comptage_col: str | None = None,
) -> dict[str, Any]:
    """Split into train / valid arrays and compute sample weights.

    Returns a dict with keys:
        x_full, y, idx_train, idx_valid,
        y_train, y_valid,
        train_sample_weight, valid_sample_weight,
        target_log_transform  (echo of the flag — eval needs it to expm1)

    Notes
    -----
    * When ``use_log_flow_weighting`` is True it OVERRIDES the binary
      ``flag_permanent`` weighting and computes ``w = log1p(<flow_col>)``,
      re-scaled so ``sum(w) == N_train``.
    * When ``use_flag_permanent_weighting`` is True, rows where the
      ``flag_permanent`` column equals 1 receive
      ``flag_priority_weight`` (others stay at 1.0).
    * When ``use_flag_recent_year_weighting`` is True, the boost is
      multiplied (compounded) for rows belonging to the MAX value of
      ``recent_year_col`` — auto-detected from the data, not hardcoded.
    * When ``target_log_transform`` is True, ``y_train`` and ``y_valid``
      are replaced with ``log1p(y)`` BEFORE normalization (the caller is
      expected to z-score the transformed target as usual).
    * Legacy keyword arguments ``use_flag_comptage_weighting`` /
      ``flag_comptage_col`` are accepted and forwarded (with a warning).
    """
    # ---- Legacy alias handling -------------------------------------------
    if use_flag_comptage_weighting is not None:
        logger.warning(
            "split_train_valid: 'use_flag_comptage_weighting' is deprecated; "
            "use 'use_flag_permanent_weighting' instead."
        )
        # Only honour the legacy alias when the caller did NOT also pass the
        # new name (the new name wins to keep callers' intent explicit).
        if not use_flag_permanent_weighting:
            use_flag_permanent_weighting = bool(use_flag_comptage_weighting)
    if flag_comptage_col is not None:
        logger.warning(
            "split_train_valid: 'flag_comptage_col' is deprecated; "
            "use 'flag_permanent_col' instead."
        )
        if flag_permanent_col == "flag_permanent":
            flag_permanent_col = str(flag_comptage_col)
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

    # P2A.5 — target log transform. Applied AFTER the split so we never
    # leak validation rows into the training target moments.
    if target_log_transform:
        # log1p is defined for y >= -1; TxPen is a percentage (0..100ish)
        # so it should always satisfy that, but we clip defensively to
        # avoid NaNs from pathological inputs.
        y_train = np.log1p(np.clip(y_train, a_min=-0.999_999, a_max=None))
        if y_valid is not None:
            y_valid = np.log1p(np.clip(y_valid, a_min=-0.999_999, a_max=None))

    # ---- Sample weights ----------------------------------------------------
    train_sample_weight: np.ndarray | None = None
    valid_sample_weight: np.ndarray | None = None

    all_sw: np.ndarray | None = None
    if use_log_flow_weighting:
        all_sw = _compute_log_flow_weights(df, log_flow_weighting_col)

    # Binary flag-based weighting. flag_permanent and flag_recent_year
    # compound multiplicatively when both are active (so a row that is
    # permanent AND in the most-recent year gets the product of both
    # boosts). The normalisation step further down rescales the resulting
    # vector so sum(weights) == N_train, preserving effective LR.
    if all_sw is None and (
        use_flag_permanent_weighting or use_flag_recent_year_weighting
    ):
        base = np.ones(len(df), dtype=float)

        if use_flag_permanent_weighting and flag_permanent_col in df.columns:
            flag_series = pd.to_numeric(
                df[flag_permanent_col], errors="coerce"
            ).fillna(0)
            base = np.where(
                flag_series.values == 1,
                base * float(flag_priority_weight),
                base,
            )
        elif use_flag_permanent_weighting:
            logger.warning(
                "use_flag_permanent_weighting=True but column '%s' is missing"
                " — falling back to uniform weights for the permanent flag.",
                flag_permanent_col,
            )

        if use_flag_recent_year_weighting and recent_year_col in df.columns:
            year_series = pd.to_numeric(
                df[recent_year_col], errors="coerce"
            )
            if year_series.notna().any():
                # Auto-detect the most recent year as the MAX value in the
                # mapped column (typed pipeline encodes years as small
                # ascending integers 1..N — last is the newest).
                max_year = float(year_series.max())
                recent_mask = (year_series.values == max_year)
                base = np.where(
                    recent_mask,
                    base * float(recent_year_priority_weight),
                    base,
                )
        elif use_flag_recent_year_weighting:
            logger.warning(
                "use_flag_recent_year_weighting=True but column '%s' is"
                " missing — recent-year boost ignored.",
                recent_year_col,
            )

        all_sw = base.astype(float)

    if all_sw is not None:
        train_sample_weight = all_sw[idx_train]
        if idx_valid is not None:
            valid_sample_weight = all_sw[idx_valid]

        # Normalise so sum(weights) == N_train: keeps the effective LR
        # stable and lets EarlyStopping compare losses across weighted /
        # non-weighted runs. Same renormalisation rule applied to both
        # the binary flag scheme (P0.5) and the new log scheme (P2A.4).
        n = len(train_sample_weight)
        total = float(train_sample_weight.sum())
        if total > 0:
            train_sample_weight = train_sample_weight * (n / total)
        else:
            # Degenerate: all weights == 0. Fall back to uniform so we do
            # not produce a fit-time crash inside Keras.
            train_sample_weight = np.ones(n, dtype=float)

        if valid_sample_weight is not None:
            n_v = len(valid_sample_weight)
            total_v = float(valid_sample_weight.sum())
            if total_v > 0:
                valid_sample_weight = valid_sample_weight * (n_v / total_v)
            else:
                valid_sample_weight = np.ones(n_v, dtype=float)

    return {
        "x_full": x_full,
        "y": y,
        "idx_train": idx_train,
        "idx_valid": idx_valid,
        "y_train": y_train,
        "y_valid": y_valid,
        "train_sample_weight": train_sample_weight,
        "valid_sample_weight": valid_sample_weight,
        # Echoed back so the training pipeline can stamp the artifact's
        # training_config dict — evaluation reads it to apply expm1.
        "target_log_transform": bool(target_log_transform),
    }
