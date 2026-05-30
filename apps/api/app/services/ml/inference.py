"""Pipeline d'inference ML : load -> normalize -> predict -> denormalize.

Module extrait depuis ``app.routers.carte`` (refonte pre-execution). Centralise
le cycle complet de prediction sur un modele Keras + coefficients de
normalisation + training_config, ainsi que le cleanup TF (GPU off, gc,
clear_session).

Sommaire :

* ``_load_model``           : load model.keras (ou legacy .h5/json) + norm + cfg.
* ``_my_norm`` / ``_my_denorm`` : normalisation z-score avec masque on_off.
* ``_apply_year_mapping``   : year_mapped feature (production Lyon).
* ``_normalize_input_cols`` : retrocompat noms legacy de colonnes input.
* ``_peak_hour_err_pct``    : tranches IC v/h (HPM/HPS).
* ``_ensure_hourly_fcd_column`` : derive FCD_HPM_TV / FCD_HPS_TV depuis aliases.
* ``_predict_peak_hour``    : pipeline HPM/HPS complet (load+predict+cleanup).
* ``release_tf_model``      : helper de cleanup TF factorise (4 modeles max).

GPU off / TF verbosity : configures au top du module (une seule fois).
"""

from __future__ import annotations

# === GPU off / TF silencieux ============================================
# Doit etre fait AVANT tout import TF (transitif via les fonctions ci-dessous).
# Factorise depuis carte.py ou la sequence etait repetee a chaque appel de
# _load_model + _predict_peak_hour (4x dans le pire cas TV/PL/HPM/HPS).
import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import asyncio
import gc
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException

logger = logging.getLogger(__name__)


def _load_model(model_path: str):
    """Load a TensorFlow model with weights, norm coefficients, and training config.

    Accepts both legacy (.h5 weights + JSON arch) and new (model.keras) layouts
    via services.ml.packaging.load_model_compat (C4).
    """
    # GPU off / TF silencieux : factorise au top du module. On re-applique ici
    # par defense en profondeur (cas de re-execution dans un meme process avec
    # env mutee dans l'intervalle).
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    from .packaging import load_model_compat

    p = Path(model_path)
    norm_file = p / "NNnormCoefficients.json"
    if not norm_file.exists():
        raise FileNotFoundError(f"NNnormCoefficients.json introuvable dans {model_path}")

    model = load_model_compat(p)

    with open(norm_file, "r") as f:
        norm_coefficients = json.load(f)

    config = None
    config_file = p / "training_config.json"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

    return model, norm_coefficients, config


def release_tf_model(model: Any | None = None) -> None:
    """Libere les ressources TF apres un predict (factorise depuis carte.py).

    Sequence dupliquee 4x dans l'ancien carte.py (TV -> PL -> HPM -> HPS).
    Centralisee ici : del model + gc.collect() + tf.keras.backend.clear_session().

    Args:
        model : la reference du modele Keras (optionnelle ; passer None si
                l'appelant a deja fait ``del model`` lui-meme).
    """
    if model is not None:
        try:
            del model
        except Exception:  # noqa: BLE001 — defensive cleanup only
            pass
    gc.collect()
    try:
        import tensorflow as _tf
        _tf.keras.backend.clear_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("release_tf_model: clear_session failed: %s", exc)


def _my_norm(X: pd.DataFrame, on_off_norm: list[int], mu: list[float], S: list[float]):
    """Z-score normalisation with on/off mask, using pre-computed mu & S.

    The training pipeline stores mu/S only for the SUBSET of features that have
    on_off_norm=True (so a 7-feature model with year_mapped + functional_class
    left raw stores only 5 mu values). When that happens, expand mu/S to the
    full input_cols length, leaving zeros under the False mask — mirrors the
    eval pipeline expansion logic in /api/evaluation/run.
    """
    on_off = np.array(on_off_norm, dtype=bool)
    mu_arr = np.array(mu, dtype=float)
    S_arr = np.array(S, dtype=float)
    n_inputs = len(on_off)

    if len(mu_arr) < n_inputs:
        if int(on_off.sum()) != len(mu_arr):
            raise ValueError(
                f"Normalisation mismatch: mu has {len(mu_arr)} entries but "
                f"{int(on_off.sum())} columns are flagged as normalised."
            )
        full_mu = np.zeros(n_inputs, dtype=float)
        full_S = np.ones(n_inputs, dtype=float)
        full_mu[on_off] = mu_arr
        full_S[on_off] = S_arr
        mu_arr = full_mu
        S_arr = full_S

    Xnorm = pd.DataFrame(index=X.index, columns=X.columns)
    on_idx = np.where(on_off)[0]

    for idx in on_idx:
        Xnorm.iloc[:, idx] = (X.iloc[:, idx].values - mu_arr[idx]) / S_arr[idx]

    Xnorm.loc[:, ~on_off] = X.loc[:, ~on_off].values
    return Xnorm


def _my_denorm(Xnorm: np.ndarray, mu: float, S: float) -> np.ndarray:
    return Xnorm * S + mu


def _apply_year_mapping(data: pd.DataFrame, config: dict | None) -> pd.DataFrame:
    """Apply year feature mapping if configured in model config.

    Triggers when EITHER:
      - config["use_year_feature"] is True (legacy explicit flag), OR
      - "year_mapped" appears in config["input_cols"] (modern training_config
        does not set the use_year_feature flag — production Lyon models fall
        into this branch).
    """
    if not config:
        return data
    input_cols = config.get("input_cols") or []
    needs_year = config.get("use_year_feature", False) or ("year_mapped" in input_cols)
    if not needs_year:
        return data

    year_col = config.get("year_column_name", "Annee")
    year_mapping = config.get("year_value_mapping", {})

    if year_col in data.columns and year_mapping:
        data["year_mapped"] = data[year_col].astype(str).map(year_mapping)
        if data["year_mapped"].notna().sum() > 0:
            mean_year = data["year_mapped"].mean()
            data["year_mapped"] = data["year_mapped"].fillna(mean_year)
        else:
            data["year_mapped"] = 0
    else:
        if year_mapping:
            median_value = sorted(year_mapping.values())[len(year_mapping) // 2]
        else:
            median_value = 0
        data["year_mapped"] = median_value

    return data


# Legacy column names (used by older training_config.json or hand-mapped data)
# that need to be silently bridged to the official canonical names.
# Dupliquee depuis carte.py (LEGACY_RETROCOMPAT) pour autonomie du module ;
# la reference principale reste celle du routeur (re-exportee depuis ici).
_LEGACY_RETROCOMPAT_INPUT_COLS = {
    "TMJATV": "TMJOFCDTV",
    "TMJAPL": "TMJOFCDPL",
    "TMJAFCDTV": "TMJOFCDTV",
    "TMJAFCDPL": "TMJOFCDPL",
    "linkFC": "functional_class",
}


def _normalize_input_cols(input_cols: list[str]) -> list[str]:
    """Normalize legacy column names in input_cols to canonical ones."""
    return [_LEGACY_RETROCOMPAT_INPUT_COLS.get(c, c) for c in input_cols]


# ---------------------------------------------------------------------------
# HPM / HPS helpers (peak-hour, optional — v/h unit)
# ---------------------------------------------------------------------------
#
# Convention :
#   - HPM = Heure de Pointe Matin (8h00-8h59)  -> FCD_HPM_TV = FCDTV_h08
#   - HPS = Heure de Pointe Soir  (17h00-17h59) -> FCD_HPS_TV = FCDTV_h17
#
# Outputs are PM / PS in v/h (vehicules per hour), NOT v/j (per day). The
# corresponding IC tranches are recalibrated in PeakHourErrorThresholds.

def _peak_hour_err_pct(value: float, thresholds: Any) -> float:
    """Return the v/h confidence-interval error percentage for a PM/PS value.

    Tranches (D2): 0-100=25%, 100-300=18%, 300-600=18%, >600=14%.

    ``thresholds`` is a ``PeakHourErrorThresholds`` instance (typed in the
    router ; left as ``Any`` here to avoid the back-import).
    """
    if value < 100:
        return thresholds.err_0_100
    elif value < 300:
        return thresholds.err_100_300
    elif value < 600:
        return thresholds.err_300_600
    else:
        return thresholds.err_600_plus


def _ensure_hourly_fcd_column(
    data: pd.DataFrame,
    canonical: str,
    aliases: tuple[str, ...],
    kind_label: str,
) -> pd.DataFrame:
    """Materialise ``canonical`` (e.g. ``FCD_HPM_TV``) from one of its aliases.

    Mirrors the upstream :func:`derive_hpm_hps_columns` helper but only for
    the FCD numerator (the carte pipeline does not need ``TxPen_HPM`` / BC
    derivation — those are training-time artefacts).
    """
    if canonical in data.columns:
        return data
    for alias in aliases:
        if alias in data.columns:
            data[canonical] = pd.to_numeric(data[alias], errors="coerce")
            logger.info("Carte HPM/HPS: derived %s from %s (%s)", canonical, alias, kind_label)
            return data
    raise HTTPException(
        status_code=400,
        detail=(
            f"Colonne FCD horaire manquante pour le modele {kind_label}: "
            f"ni '{canonical}' ni un de ses alias {aliases} n'est present dans les donnees FCD. "
            f"Verifiez que le fichier source contient les colonnes horaires (FCDTV_h08 / FCDTV_h17)."
        ),
    )


async def _predict_peak_hour(
    *,
    raw_df: pd.DataFrame,
    rename_dict: dict[str, str],
    model_dir: str,
    kind: str,
    canonical_fcd: str,
    fcd_aliases: tuple[str, ...],
    fallback_input_cols: list[str],
    normalize_source_columns: Any,
    apply_column_aliases: Any,
) -> tuple[np.ndarray, np.ndarray]:
    """Run a peak-hour model (HPM/HPS) and return (TxPen_pred, debit_v_per_h).

    Pipeline mirrors the TV/PL blocks but :
      - silently derives ``FCD_HPM_TV`` / ``FCD_HPS_TV`` from ``FCDTV_h08`` /
        ``FCDTV_h17`` when not directly present;
      - returns the per-row v/h debit (FCD / |TxPen_pred| * 100), already
        guarded against division by zero;
      - applies the standard TF cleanup (del + gc + clear_session) before
        returning so the next model load starts from a clean slate.

    Args:
        raw_df                   : raw FCD dataframe (session.data["raw_df"]).
        rename_dict              : source -> target column rename dict (built
                                   from CarteGenerateRequest.column_mapping).
        model_dir                : HPM or HPS model directory path.
        kind                     : "HPM" or "HPS" (used in error messages / logs).
        canonical_fcd            : canonical FCD column ("FCD_HPM_TV" or "FCD_HPS_TV").
        fcd_aliases              : aliases tried in order (e.g. ("FCDTV_h08",)).
        fallback_input_cols      : default input_cols when training_config absent.
        normalize_source_columns : carte.py-provided helper (injected to avoid
                                   circular imports).
        apply_column_aliases     : carte.py-provided helper (injected).
    """
    # 1. Prepare a fresh copy with the same column-mapping/alias pipeline as TV/PL.
    data = raw_df.copy()
    data = data.rename(columns=rename_dict)
    data = normalize_source_columns(data)
    data = apply_column_aliases(data)

    # 2. Load model + config.
    try:
        model_pk, coeff_pk, config_pk = await asyncio.to_thread(_load_model, model_dir)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Erreur chargement modele {kind}: {exc}",
        )

    # 3. Apply year mapping (uses the model's own training_config).
    data = _apply_year_mapping(data, config_pk)

    # 4. Ensure the hourly FCD column exists (derive from FCDTV_hXX if needed).
    data = _ensure_hourly_fcd_column(data, canonical_fcd, fcd_aliases, kind)

    # 5. Resolve input_cols (config preferred; fallback to CONFIGS).
    if config_pk and "input_cols" in config_pk:
        input_cols = _normalize_input_cols(config_pk["input_cols"])
    else:
        input_cols = list(fallback_input_cols)

    missing = [c for c in input_cols if c not in data.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes pour le modele {kind}: {missing}",
        )

    # 6. Normalize, predict, denormalize.
    muY = coeff_pk["muY"][0]
    SY = coeff_pk["SY"][0]
    SX = coeff_pk["SX"][0]
    muX = coeff_pk["muX"][0]

    on_off_norm = config_pk.get("on_off_norm") if config_pk else None
    if not on_off_norm or len(on_off_norm) != len(input_cols):
        on_off_norm = [1] * len(input_cols)

    x_in = data[input_cols]
    x_norm = _my_norm(x_in, on_off_norm, muX, SX)
    x_arr = np.array(x_norm, dtype=np.float32)
    y_norm = await asyncio.to_thread(model_pk.predict, x_arr, verbose=0)
    y_denorm = _my_denorm(y_norm, muY, SY)

    tx_pen_pred = y_denorm[:, 0]
    fcd_values = pd.to_numeric(data[canonical_fcd], errors="coerce").to_numpy()
    # Guard against div-by-zero / NaN — keep the legacy ``round(0)`` semantics.
    safe_denom = np.where(np.abs(tx_pen_pred) > 1e-9, np.abs(tx_pen_pred), np.nan)
    debit_vh = fcd_values / safe_denom * 100.0

    # 7. TF cleanup (mandatory : 4 models loaded sequentially in the worst case).
    del model_pk, x_arr, y_norm
    gc.collect()
    try:
        import tensorflow as _tf
        _tf.keras.backend.clear_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear_session after %s predict failed: %s", kind, exc)

    return tx_pen_pred, debit_vh


__all__ = [
    "_load_model",
    "release_tf_model",
    "_my_norm",
    "_my_denorm",
    "_apply_year_mapping",
    "_normalize_input_cols",
    "_peak_hour_err_pct",
    "_ensure_hourly_fcd_column",
    "_predict_peak_hour",
]
