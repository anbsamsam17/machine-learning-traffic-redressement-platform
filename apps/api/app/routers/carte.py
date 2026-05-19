"""Carte router — generate carte de debits (apply TV+PL models on FCD data).

Reproduces the full logic from the Streamlit page 8_Generation_Carte_Debits.py:
  load TV model + PL model + FCD data -> map columns -> predict TxPen ->
  compute TVr, DPL, PLr, confidence intervals -> filter -> round -> GeoJSON.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import math
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/carte", tags=["carte"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ErrorThresholds(BaseModel):
    err_0_1000: float = 0.25
    err_1000_2000: float = 0.18
    err_2000_4000: float = 0.18
    err_4000_plus: float = 0.14


class CarteGenerateRequest(BaseModel):
    session_id: str
    model_tv_dir: str
    model_pl_dir: str
    column_mapping: dict[str, str | None] = Field(
        default_factory=dict,
        description="Mapping: target_col -> source_col in data (None = skip)",
    )
    filter_tvr_enabled: bool = True
    filter_tvr_value: int = 100
    filter_fc_enabled: bool = True
    error_thresholds: ErrorThresholds = Field(default_factory=ErrorThresholds)


class CarteStats(BaseModel):
    total_segments: int
    filtered_segments: int
    mean_tvr: float | None = None
    mean_dpl: float | None = None


class CarteGenerateResponse(BaseModel):
    session_id: str
    stats: CarteStats
    geojson_feature_count: int


class ModelValidateRequest(BaseModel):
    model_dir: str


class ModelValidateResponse(BaseModel):
    valid: bool
    missing_files: list[str]
    training_config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers — normalisation / denormalisation (from Streamlit original)
# ---------------------------------------------------------------------------

def _my_norm(X: pd.DataFrame, on_off_norm: list[int], mu: list[float], S: list[float]):
    """Z-score normalisation with on/off mask, using pre-computed mu & S."""
    on_off = np.array(on_off_norm, dtype=bool)
    mu_arr = np.array(mu)
    S_arr = np.array(S)

    Xnorm = pd.DataFrame(index=X.index, columns=X.columns)
    on_idx = np.where(on_off)[0]

    for idx in on_idx:
        Xnorm.iloc[:, idx] = (X.iloc[:, idx].values - mu_arr[idx]) / S_arr[idx]

    Xnorm.loc[:, ~on_off] = X.loc[:, ~on_off].values
    return Xnorm


def _my_denorm(Xnorm: np.ndarray, mu: float, S: float) -> np.ndarray:
    return Xnorm * S + mu


def _apply_year_mapping(data: pd.DataFrame, config: dict | None) -> pd.DataFrame:
    """Apply year feature mapping if configured in model config."""
    if not config or not config.get("use_year_feature", False):
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


def _calculate_heading(geom: dict | None) -> float:
    """Compute heading from a GeoJSON LineString geometry."""
    if geom is None:
        return 0.0
    coords = geom.get("coordinates", [])
    if not coords or len(coords) < 2:
        return 0.0
    lat1, lon1 = math.radians(coords[0][1]), math.radians(coords[0][0])
    lat2, lon2 = math.radians(coords[-1][1]), math.radians(coords[-1][0])
    delta_long = lon2 - lon1
    X = math.cos(lat2) * math.sin(delta_long)
    Y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_long)
    return math.degrees(math.atan2(Y, X))


def _erreur_pourcentage(tvr: float, thresholds: ErrorThresholds) -> float:
    """Dynamic error % based on TVr thresholds."""
    if tvr > 4000:
        return thresholds.err_4000_plus
    elif tvr > 2000:
        return thresholds.err_2000_4000
    elif tvr > 1000:
        return thresholds.err_1000_2000
    else:
        return thresholds.err_0_1000


def _calculer_DPLmin(JOr: float) -> float:
    if JOr < 500:
        return max(0.0, 0.75 * JOr)
    elif JOr < 1000:
        return max(0.0, 0.85 * JOr)
    elif JOr < 2000:
        return max(0.0, 0.85 * JOr)
    elif JOr < 4000:
        return max(0.0, 0.88 * JOr)
    elif JOr < 6000:
        return max(0.0, 0.88 * JOr)
    elif JOr < 10000:
        return max(0.0, 0.88 * JOr)
    else:
        return round(max(JOr - 1500, round(0.88 * JOr, -2)), -2)


def _calculer_DPLmax(JOr: float) -> float:
    if JOr < 500:
        return max(1.25 * JOr, JOr + 10)
    elif JOr < 1000:
        return round(max(1.25 * JOr, JOr + 10), -2)
    elif JOr < 2000:
        return round(max(1.15 * JOr, JOr + 10), -2)
    elif JOr < 4000:
        return round(max(1.12 * JOr, JOr + 10), -2)
    elif JOr < 6000:
        return round(max(1.12 * JOr, JOr + 10), -2)
    elif JOr < 10000:
        return round(max(1.12 * JOr, JOr + 10), -2)
    else:
        return round(min(round(max(1.12 * JOr, JOr + 10), -2), JOr + 1500), -2)


def _load_model(model_path: str):
    """Load a TensorFlow model with weights, norm coefficients, and training config.

    Accepts both legacy (.h5 weights + JSON arch) and new (model.keras) layouts
    via services.ml.packaging.load_model_compat (C4).
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    from ..services.ml.packaging import load_model_compat

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


def _verify_model_structure(model_path: str) -> tuple[bool, list[str], dict | None]:
    """Verify model directory has all required files. Returns (valid, missing, config).

    C4: accept either the new model.keras artefact or the legacy
    NNarchitecture.json + NNweights{.weights}.h5 pair.
    """
    p = Path(model_path)
    has_native = (p / "model.keras").exists()

    missing: list[str] = []
    if not (p / "NNnormCoefficients.json").exists():
        missing.append("NNnormCoefficients.json")

    if not has_native:
        if not (p / "NNarchitecture.json").exists():
            missing.append("NNarchitecture.json")
        if not any((p / w).exists() for w in ("NNweights.h5", "NNweights.weights.h5")):
            missing.append("NNweights.h5")

    config = None
    config_file = p / "training_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load training_config.json at %s: %s", config_file, exc)

    return len(missing) == 0, missing, config


def _apply_column_aliases(data: pd.DataFrame) -> pd.DataFrame:
    """Create column aliases for compatibility (TMJATV <-> TMJAFCDTV etc.)."""
    alias_pairs = [
        ("TMJATV", "TMJAFCDTV"),
        ("TMJAPL", "TMJAFCDPL"),
        ("TMJAVL", "TMJAFCDVL"),
    ]
    for a, b in alias_pairs:
        if a in data.columns and b not in data.columns:
            data[b] = pd.to_numeric(data[a], errors="coerce")
        elif b in data.columns and a not in data.columns:
            data[a] = pd.to_numeric(data[b], errors="coerce")
    return data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/validate-model", response_model=ModelValidateResponse)
async def validate_model(body: ModelValidateRequest) -> ModelValidateResponse:
    """Validate that a model directory contains all required files."""
    p = Path(body.model_dir)
    if not p.exists() or not p.is_dir():
        return ModelValidateResponse(valid=False, missing_files=["(dossier introuvable)"])

    valid, missing, config = _verify_model_structure(body.model_dir)
    return ModelValidateResponse(valid=valid, missing_files=missing, training_config=config)


class CarteModelUploadResponse(BaseModel):
    model_dir: str
    valid: bool
    missing_files: list[str]
    training_config: dict[str, Any] | None = None


@router.post("/upload-model", response_model=CarteModelUploadResponse)
async def upload_carte_model(
    file: UploadFile = File(..., description="Fichier ZIP contenant le dossier du modele"),
    session_id: str = Form(..., description="Session ID"),
    model_type: str = Form(..., description="Type de modele: tv ou pl"),
    current_user: UserRecord = Depends(get_current_user),
) -> CarteModelUploadResponse:
    """Upload a model ZIP for carte generation (TV or PL).

    Extracts into WORKSPACE_ROOT/{session_id}/carte_models/{model_type}/ and validates.
    """
    require_owned_session(session_id, current_user)

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Le fichier doit etre un .zip")

    if model_type.lower() not in ("tv", "pl"):
        raise HTTPException(status_code=400, detail="model_type doit etre 'tv' ou 'pl'")

    settings = get_settings()
    dest_dir = Path(settings.WORKSPACE_ROOT) / session_id / "carte_models" / model_type.lower()
    # Clean existing content
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    buf = io.BytesIO(contents)
    if not zipfile.is_zipfile(buf):
        raise HTTPException(status_code=400, detail="Le fichier n'est pas un ZIP valide.")

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        for name in zf.namelist():
            if ".." in name or name.startswith("/") or name.startswith("\\"):
                raise HTTPException(status_code=400, detail=f"Chemin invalide dans le ZIP: {name}")
        zf.extractall(dest_dir)

    # Remove __MACOSX
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Find the actual model directory — could be dest_dir itself, or a subfolder
    model_dir = dest_dir
    if not (model_dir / "NNarchitecture.json").exists():
        # Check one level deeper
        for child in model_dir.iterdir():
            if child.is_dir() and (child / "NNarchitecture.json").exists():
                model_dir = child
                break

    valid, missing, config = _verify_model_structure(str(model_dir))

    logger.info("Carte model upload (%s): valid=%s, dir=%s", model_type, valid, model_dir)

    return CarteModelUploadResponse(
        model_dir=str(model_dir),
        valid=valid,
        missing_files=missing,
        training_config=config,
    )


@router.post("/upload-model-folder", response_model=CarteModelUploadResponse)
async def upload_carte_model_folder(
    files: list[UploadFile] = File(..., description="Fichiers du dossier de modele (via webkitdirectory)"),
    session_id: str = Form(..., description="Session ID"),
    model_type: str = Form(..., description="Type de modele: tv ou pl"),
    current_user: UserRecord = Depends(get_current_user),
) -> CarteModelUploadResponse:
    """Upload model files from a folder selection (webkitdirectory) for carte generation.

    Each file's ``filename`` contains its relative path. The endpoint reconstructs
    the tree under WORKSPACE_ROOT/{session_id}/carte_models/{model_type}/ and
    validates the model structure.
    """
    require_owned_session(session_id, current_user)

    if model_type.lower() not in ("tv", "pl"):
        raise HTTPException(status_code=400, detail="model_type doit etre 'tv' ou 'pl'")

    settings = get_settings()
    dest_dir = Path(settings.WORKSPACE_ROOT) / session_id / "carte_models" / model_type.lower()
    # Clean existing content
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for upload_file in files:
        if not upload_file.filename:
            continue
        rel = upload_file.filename.replace("\\", "/").lstrip("/")
        if ".." in rel:
            raise HTTPException(status_code=400, detail=f"Chemin invalide: {rel}")

        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = await upload_file.read()
        target.write_bytes(contents)

    logger.info("Carte model folder upload (%s): wrote %d files to %s", model_type, len(files), dest_dir)

    # Remove macOS artefacts
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Find the actual model directory
    model_dir = dest_dir
    if not (model_dir / "NNarchitecture.json").exists():
        # Check one level deeper
        for child in model_dir.iterdir():
            if child.is_dir() and (child / "NNarchitecture.json").exists():
                model_dir = child
                break
        else:
            # Check two levels deep
            for child in dest_dir.iterdir():
                if child.is_dir():
                    for grandchild in child.iterdir():
                        if grandchild.is_dir() and (grandchild / "NNarchitecture.json").exists():
                            model_dir = grandchild
                            break
                    if (model_dir / "NNarchitecture.json").exists():
                        break

    valid, missing, config = _verify_model_structure(str(model_dir))

    logger.info("Carte model folder upload (%s): valid=%s, dir=%s", model_type, valid, model_dir)

    return CarteModelUploadResponse(
        model_dir=str(model_dir),
        valid=valid,
        missing_files=missing,
        training_config=config,
    )


@router.post("/generate", response_model=CarteGenerateResponse)
async def generate_carte(
    body: CarteGenerateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> CarteGenerateResponse:
    """Apply TV + PL models on FCD data to produce a carte de debits GeoJSON."""

    # 1. Validate session ownership
    session = require_owned_session(body.session_id, current_user)

    # 2. Load raw data from session
    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        raise HTTPException(status_code=400, detail="Aucune donnee FCD dans la session. Uploadez un fichier d'abord.")

    # 3. Load both models
    try:
        model_tv, coeff_tv, config_tv = await asyncio.to_thread(_load_model, body.model_tv_dir)
    except (FileNotFoundError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Erreur chargement modele TV: {e}")

    try:
        model_pl, coeff_pl, config_pl = await asyncio.to_thread(_load_model, body.model_pl_dir)
    except (FileNotFoundError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Erreur chargement modele PL: {e}")

    # 4. Extract norm coefficients
    muY_tv = coeff_tv["muY"][0]
    SY_tv = coeff_tv["SY"][0]
    SX_tv = coeff_tv["SX"][0]
    muX_tv = coeff_tv["muX"][0]

    muY_pl = coeff_pl["muY"][0]
    SY_pl = coeff_pl["SY"][0]
    SX_pl = coeff_pl["SX"][0]
    muX_pl = coeff_pl["muX"][0]

    # 5. Prepare data — apply column mapping
    data = raw_df.copy()

    # Build rename dict: source_col -> target_col (skip None mappings)
    rename_dict = {v: k for k, v in body.column_mapping.items() if v is not None}
    data = data.rename(columns=rename_dict)

    # Apply column aliases
    data = _apply_column_aliases(data)

    # Apply year mapping for TV
    data = _apply_year_mapping(data, config_tv)

    # 6. TV prediction
    if config_tv and "input_cols" in config_tv:
        input_cols_tv = config_tv["input_cols"]
    else:
        input_cols_tv = [
            "TMJATV", "TMJAPL", "car_average_distance_km", "car_average_speed_kmh",
            "truck_min_average_distance_km", "truck_average_speed_kmh",
        ]

    missing_tv = [c for c in input_cols_tv if c not in data.columns]
    if missing_tv:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes pour le modele TV: {missing_tv}",
        )

    x1_tv = data[input_cols_tv]
    onOffNorm_tv = [1] * len(input_cols_tv)
    xNorm_tv = _my_norm(x1_tv, onOffNorm_tv, muX_tv, SX_tv)
    x_tv = np.array(xNorm_tv).astype(np.float32)
    # B4: TF predict can take several seconds - offload to worker thread
    yestTNorm_tv = await asyncio.to_thread(model_tv.predict, x_tv, verbose=0)
    yestT_tv = _my_denorm(yestTNorm_tv, muY_tv, SY_tv)

    data["TxPenTVpred"] = yestT_tv[:, 0]
    data["TMJATVred"] = data["TMJATV"] / np.abs(yestT_tv[:, 0]) * 100

    # C7: release TV model resources before loading the PL model
    del model_tv, x_tv, yestTNorm_tv
    import gc as _gc
    _gc.collect()
    try:
        import tensorflow as _tf
        _tf.keras.backend.clear_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear_session after TV predict failed: %s", exc)

    # Format intermediates
    data["TMJAVL"] = pd.to_numeric(data.get("TMJAVL", 0), errors="coerce").round(1)
    data["TMJAPL"] = pd.to_numeric(data["TMJAPL"], errors="coerce").round(1)
    data["TMJATVred"] = data["TMJATVred"].round(0)
    data["TxPenTV"] = data["TxPenTVpred"].round(1)

    # Rename columns
    data = data.rename(columns={
        "TMJAPL": "PL",
        "TxPenTV": "TP",
        "TMJATVred": "TVr",
        "linkFC": "FC",
        "TMJAVL": "VL",
    })

    # Handle AgregId
    if "agregId" in data.columns:
        data = data.rename(columns={"agregId": "AgregId"})
    elif "id" in data.columns:
        data = data.rename(columns={"id": "AgregId"})
    else:
        data["AgregId"] = range(len(data))

    # Compute heading from geometry
    geom_col = "geometry" if "geometry" in data.columns else "__geometry_json"
    if geom_col in data.columns:
        def _parse_and_heading(g):
            if g is None:
                return 0.0
            if isinstance(g, str):
                try:
                    g = json.loads(g)
                except Exception:
                    return 0.0
            if isinstance(g, dict):
                return _calculate_heading(g)
            return 0.0
        data["HD"] = data[geom_col].apply(_parse_and_heading)
    else:
        data["HD"] = 0.0

    # DD (double direction)
    if "DIR_TRAVEL" in data.columns:
        data["DD"] = (data["DIR_TRAVEL"] == "B")
    else:
        data["DD"] = False

    # Select columns for intermediate result
    selected_columns = [
        "AgregId", "PL", "FC", "VL", "TP", "TVr", "DD", "HD",
        "car_count", "car_average_speed_kmh", "car_average_distance_km",
        "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
        "geometry", "__geometry_json",
    ]
    available_cols = [c for c in selected_columns if c in data.columns]
    prod = data[available_cols].copy()

    # 7. PL prediction — use a fresh copy from raw with mapping
    data_pl = raw_df.copy()
    data_pl = data_pl.rename(columns=rename_dict)
    data_pl = _apply_column_aliases(data_pl)
    data_pl = _apply_year_mapping(data_pl, config_pl)

    if config_pl and "input_cols" in config_pl:
        input_cols_pl = config_pl["input_cols"]
    else:
        input_cols_pl = [
            "TMJAPL", "car_average_distance_km", "car_average_speed_kmh",
            "truck_min_average_distance_km", "truck_average_speed_kmh",
        ]

    missing_pl = [c for c in input_cols_pl if c not in data_pl.columns]
    if missing_pl:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes pour le modele PL: {missing_pl}",
        )

    x1_pl = data_pl[input_cols_pl]
    onOffNorm_pl = [1] * len(input_cols_pl)
    xNorm_pl = _my_norm(x1_pl, onOffNorm_pl, muX_pl, SX_pl)
    x_pl = np.array(xNorm_pl).astype(np.float32)
    # B4: TF predict can take several seconds - offload to worker thread
    yestTNorm_pl = await asyncio.to_thread(model_pl.predict, x_pl, verbose=0)
    yestT_pl = _my_denorm(yestTNorm_pl, muY_pl, SY_pl)

    data_pl["TxPenPL"] = yestT_pl[:, 0]
    data_pl["TMJAPLred"] = data_pl["TMJAPL"] / yestT_pl[:, 0] * 100

    # C7: release PL model resources after predict
    del model_pl, x_pl, yestTNorm_pl
    _gc.collect()
    try:
        import tensorflow as _tf2
        _tf2.keras.backend.clear_session()
    except Exception as exc:  # noqa: BLE001
        logger.warning("clear_session after PL predict failed: %s", exc)

    # Add PL results
    prod["DPL"] = data_pl["TMJAPLred"].round(0).values
    prod["PLr"] = (prod["DPL"] / prod["TVr"] * 100).round(1)
    prod["PLr"] = prod["PLr"].replace([np.nan, np.inf, -np.inf], 0)

    # 8. Confidence intervals — TVr
    thresholds = body.error_thresholds
    prod["Erreur_dyn"] = prod["TVr"].apply(lambda x: _erreur_pourcentage(x, thresholds))
    prod["TVrmin"] = (prod["TVr"] * (1 - prod["Erreur_dyn"])).round(0)
    prod["TVrmax"] = (prod["TVr"] * (1 + prod["Erreur_dyn"])).round(0)

    # Rounding TVr bounds
    mask10 = prod["TVr"] > 10000
    prod.loc[mask10, "TVrmin"] = np.round(prod.loc[mask10, "TVrmin"], -2)
    prod.loc[mask10, "TVrmax"] = np.round(prod.loc[mask10, "TVrmax"], -2)

    mask500 = prod["TVr"] < 500
    prod.loc[mask500, "TVrmin"] = 10 * np.floor(prod.loc[mask500, "TVrmin"] / 10)
    prod.loc[mask500, "TVrmax"] = 10 * np.ceil(prod.loc[mask500, "TVrmax"] / 10)

    mask_middle = prod["TVr"] >= 500
    prod.loc[mask_middle, "TVrmin"] = 100 * np.floor(prod.loc[mask_middle, "TVrmin"] / 100)
    prod.loc[mask_middle, "TVrmax"] = 100 * np.ceil(prod.loc[mask_middle, "TVrmax"] / 100)

    mask_min = prod["TVrmin"].notna() & (prod["TVrmin"] < 100)
    mask_max = prod["TVrmax"].notna() & (prod["TVrmax"] < 100)
    prod.loc[mask_min, "TVrmin"] = 0
    prod.loc[mask_max, "TVrmax"] = 100

    # 9. Confidence intervals — DPL
    prod["DPLmin"] = prod["DPL"].apply(_calculer_DPLmin)
    prod.loc[prod["DPLmin"] > 1e4, "DPLmin"] = np.round(
        prod.loc[prod["DPLmin"] > 1e4, "DPLmin"], -3
    )
    prod["DPLmax"] = prod["DPL"].apply(_calculer_DPLmax)
    prod.loc[prod["DPLmax"] > 1e4, "DPLmax"] = np.round(
        prod.loc[prod["DPLmax"] > 1e4, "DPLmax"], -3
    )
    prod.loc[prod["DPLmin"] > 50, "DPLmin"] = 10 * np.floor(
        prod.loc[prod["DPLmin"] > 50, "DPLmin"] / 10
    )
    prod.loc[prod["DPLmax"] > 50, "DPLmax"] = 10 * np.ceil(
        prod.loc[prod["DPLmax"] > 50, "DPLmax"] / 10
    )

    # 10. Confidence intervals — PLr
    prod["PLrmin"] = np.maximum(0, np.round(np.minimum(prod["PLr"] - 2, 0.85 * prod["PLr"])))
    prod["PLrmax"] = np.round(np.maximum(prod["PLr"] + 2, 1.15 * prod["PLr"]))
    prod["PLrmin"] = prod["PLrmin"].fillna(0)
    prod["PLrmax"] = prod["PLrmax"].fillna(0)

    # 11. Final computed columns
    prod["PLred"] = prod["DPL"]
    prod["VLred"] = prod["TVr"] - prod["PLred"]

    # Clean non-finite values
    prod = prod.replace([np.inf, -np.inf], np.nan)
    prod = prod.fillna(0)

    # Integer conversions
    int_cols = ["TVrmin", "TVrmax", "PLrmin", "PLrmax", "DPLmin", "DPLmax",
                "PLred", "VLred", "HD", "DPL", "TVr"]
    existing_int_cols = [c for c in int_cols if c in prod.columns]
    prod[existing_int_cols] = prod[existing_int_cols].round(0).astype(int)

    if "TP" in prod.columns:
        prod["TP"] = prod["TP"].round(1).astype(float)

    if "PL" in prod.columns:
        prod["PL"] = prod["PL"].round(1)

    # Recalculate heading (same as original)
    def _parse_geom_heading(g):
        if g is None:
            return 0.0
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except Exception:
                return 0.0
        if isinstance(g, dict):
            return _calculate_heading(g)
        return 0.0

    if geom_col in prod.columns:
        prod["HD"] = prod[geom_col].apply(_parse_geom_heading)

    prod = prod.rename(columns={"AgregId": "agregId"})

    if "DD" in prod.columns:
        prod["DD"] = prod["DD"].astype(bool)
    else:
        prod["DD"] = False

    # 12. Apply filters
    count_before = len(prod)

    if body.filter_tvr_enabled:
        prod = prod[prod["TVr"] > body.filter_tvr_value]

    if body.filter_fc_enabled and "FC" in prod.columns:
        prod = prod[prod["FC"] != 1]

    # 13. Final rounding
    tvr = pd.to_numeric(prod["TVr"], errors="coerce")
    prod["TVr"] = np.where(
        tvr < 10_000,
        np.round(tvr / 10) * 10,
        np.round(tvr / 100) * 100,
    ).astype(int)

    cols_round_10 = ["DPL", "DPLmin", "DPLmax"]
    for col in cols_round_10:
        if col in prod.columns:
            values = pd.to_numeric(prod[col], errors="coerce")
            values = values.replace([np.inf, -np.inf], 0).fillna(0)
            prod[col] = (np.round(values / 10) * 10).astype(int)

    # 14. Build GeoJSON output
    # Determine geometry column
    geom_key = "geometry" if "geometry" in prod.columns else "__geometry_json"

    output_columns = [
        "agregId", "PL", "FC", "VL", "TP", "TVr", "DD", "HD",
        "car_count", "car_average_speed_kmh", "car_average_distance_km",
        "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
        "DPL", "PLr", "TVrmin", "TVrmax", "DPLmin", "DPLmax",
        "PLrmin", "PLrmax", "PLred", "VLred",
    ]

    features = []
    for _, row in prod.iterrows():
        # Parse geometry
        geom = row.get(geom_key)
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except Exception:
                geom = None
        elif not isinstance(geom, dict):
            geom = None

        props = {}
        for col in output_columns:
            if col in row.index:
                v = row[col]
                if isinstance(v, (np.integer, np.floating)):
                    v = v.item()
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    v = None
                if isinstance(v, (np.bool_,)):
                    v = bool(v)
                props[col] = v

        features.append({"type": "Feature", "geometry": geom, "properties": props})

    geojson = {"type": "FeatureCollection", "features": features}

    # Store in session for later download
    session_manager.store_data(body.session_id, "carte_geojson", geojson)

    # Compute stats
    mean_tvr = None
    mean_dpl = None
    if len(prod) > 0:
        mean_tvr = round(float(prod["TVr"].mean()), 1)
        if "DPL" in prod.columns:
            mean_dpl = round(float(prod["DPL"].mean()), 1)

    stats = CarteStats(
        total_segments=count_before,
        filtered_segments=len(prod),
        mean_tvr=mean_tvr,
        mean_dpl=mean_dpl,
    )

    logger.info(
        "Carte generated: session=%s total=%d filtered=%d mean_tvr=%s mean_dpl=%s",
        body.session_id, count_before, len(prod), mean_tvr, mean_dpl,
    )

    return CarteGenerateResponse(
        session_id=body.session_id,
        stats=stats,
        geojson_feature_count=len(features),
    )


@router.get("/download/{session_id}")
async def download_carte(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Download the generated carte GeoJSON."""
    from fastapi.responses import JSONResponse

    session = require_owned_session(session_id, current_user)

    geojson = session.data.get("carte_geojson")
    if geojson is None:
        raise HTTPException(status_code=400, detail="Aucune carte generee. Lancez la generation d'abord.")

    return JSONResponse(
        content=geojson,
        headers={
            "Content-Disposition": f'attachment; filename="carte_debits_{session_id[:8]}.geojson"',
            "Content-Type": "application/geo+json",
        },
    )
