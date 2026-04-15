"""Carte router — generate carte de debits (apply TV+PL models on FCD data)."""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/carte", tags=["carte"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CarteRequest(BaseModel):
    session_id: str
    fcd_columns: dict[str, str] | None = None  # optional remap


class CarteStats(BaseModel):
    total_segments: int
    segments_with_prediction: int
    mean_predicted_txpen: float | None = None
    territory: str


class CarteResponse(BaseModel):
    session_id: str
    stats: CarteStats
    geojson_feature_count: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_model_from_session(session_data: dict[str, Any]):
    """Load Keras model from session data. Returns (model, norm_params) or raises."""
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    from tensorflow.keras.models import model_from_json

    model_json_str = session_data.get("trained_model_json")
    weights_bytes = session_data.get("trained_weights")
    norm_params = session_data.get("norm_params")

    if not all([model_json_str, weights_bytes, norm_params]):
        return None, None

    model = model_from_json(model_json_str)

    with tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False) as tmp:
        tmp.write(weights_bytes)
        tmp_path = tmp.name
    model.load_weights(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)

    return model, norm_params


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=CarteResponse)
async def generate_carte(body: CarteRequest) -> CarteResponse:
    """Apply the trained model on the full FCD dataset to produce a carte de debits."""
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    model, norm_params = _load_model_from_session(session.data)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail="Aucun modele entraine. Lancez l'entrainement d'abord.",
        )

    # Use learning_df as the base dataset (contains all segments)
    base_df: pd.DataFrame | None = session.data.get("learning_df")
    if base_df is None:
        base_df = session.data.get("raw_df")
    if base_df is None:
        raise HTTPException(status_code=400, detail="Aucune donnee disponible dans la session.")

    df = base_df.copy()
    # Rename columns for compatibility
    renames = {"TMJATV": "TMJAFCDTV", "TMJAPL": "TMJAFCDPL", "TxPen": "TxPenTVRef"}
    for old, new in renames.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # Apply custom column remapping if provided
    if body.fcd_columns:
        for target, source in body.fcd_columns.items():
            if source in df.columns:
                df[target] = df[source]

    input_cols: list[str] = norm_params["input_cols"]
    output_col: str = norm_params["output_col"]

    x_mean = np.array(norm_params["x_mean"])
    x_std = np.array(norm_params["x_std"])
    y_mean = norm_params["y_mean"]
    y_std = norm_params["y_std"]

    # Check which rows can be predicted
    available = [c for c in input_cols if c in df.columns]
    if len(available) < len(input_cols):
        missing = [c for c in input_cols if c not in df.columns]
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes pour la prediction: {missing}",
        )

    # Predict where all input cols are non-null
    mask = df[input_cols].notna().all(axis=1)
    pred_df = df.loc[mask, input_cols].copy()

    X = pred_df.values.astype(np.float64)
    X_norm = (X - x_mean) / x_std
    y_pred_norm = model.predict(X_norm, verbose=0).flatten()
    y_pred = y_pred_norm * y_std + y_mean

    df.loc[mask, "predicted_" + output_col] = y_pred

    # If output is TxPen, compute estimated TMJA
    if output_col in ("TxPenTVRef", "TxPen"):
        tmja_col = "TMJAFCDTV" if "TMJAFCDTV" in df.columns else "TMJATV"
        if tmja_col in df.columns:
            tmja = pd.to_numeric(df[tmja_col], errors="coerce")
            txpen_pred = df["predicted_" + output_col]
            valid = txpen_pred.notna() & (txpen_pred > 0)
            df.loc[valid, "TMJA_redresse"] = (tmja[valid] / txpen_pred[valid] * 100).round(0)

    # Build GeoJSON output
    features = []
    for _, row in df.iterrows():
        geom = row.get("geometry")
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except Exception:
                geom = None
        elif not isinstance(geom, dict):
            geom = None

        props = {}
        for k, v in row.items():
            if k == "geometry":
                continue
            if isinstance(v, (np.integer, np.floating)):
                v = v.item()
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                v = None
            props[k] = v
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    geojson = {"type": "FeatureCollection", "features": features}
    territory = session.data.get("territory", "unknown")

    session_manager.store_data(body.session_id, "carte_geojson", geojson)

    mean_pred = None
    pred_col = "predicted_" + output_col
    if pred_col in df.columns:
        vals = df[pred_col].dropna()
        mean_pred = round(float(vals.mean()), 4) if len(vals) > 0 else None

    stats = CarteStats(
        total_segments=len(df),
        segments_with_prediction=int(mask.sum()),
        mean_predicted_txpen=mean_pred,
        territory=territory,
    )

    logger.info(
        "Carte generated: session=%s segments=%d predicted=%d",
        body.session_id, len(df), int(mask.sum()),
    )

    return CarteResponse(
        session_id=body.session_id,
        stats=stats,
        geojson_feature_count=len(features),
    )
