"""Compteurs router — generate counting loops from model predictions."""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compteurs", tags=["compteurs"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CompteursRequest(BaseModel):
    session_id: str
    type_filter: list[str] | None = None  # e.g. ["per", "tou"]
    min_txpen: float | None = None
    max_txpen: float | None = None


class CompteursStats(BaseModel):
    total_loops: int
    filtered_loops: int
    territory: str


class CompteursResponse(BaseModel):
    session_id: str
    stats: CompteursStats
    geojson_feature_count: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=CompteursResponse)
async def generate_compteurs(body: CompteursRequest) -> CompteursResponse:
    """Generate counting loops (boucles de comptage) from the carte de debits or learning data."""
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    # Try to use carte data first, then learning df, then raw df
    carte_geojson: dict | None = session.data.get("carte_geojson")
    if carte_geojson is not None:
        features = carte_geojson.get("features", [])
        rows = []
        for f in features:
            props = dict(f.get("properties", {}))
            props["geometry"] = f.get("geometry")
            rows.append(props)
        df = pd.DataFrame(rows)
    else:
        df = session.data.get("learning_df")
        if df is None:
            df = session.data.get("raw_df")
        if df is None:
            raise HTTPException(
                status_code=400,
                detail="Aucune donnee disponible. Uploadez des donnees ou generez une carte d'abord.",
            )
        df = df.copy()

    # Filter for counting loops: flag_comptage == 1 or Type in filter list
    mask = pd.Series([True] * len(df), index=df.index)

    if "flag_comptage" in df.columns:
        flag = pd.to_numeric(df["flag_comptage"], errors="coerce")
        mask = mask & (flag == 1)
    elif "Type" in df.columns:
        types = df["Type"].astype(str).str.strip().str.lower()
        default_types = body.type_filter or ["per", "tou"]
        mask = mask & types.isin([t.lower() for t in default_types])

    # Optional TxPen filters
    txpen_col = None
    for col_name in ["predicted_TxPenTVRef", "predicted_TxPen", "TxPen", "TxPenTVRef"]:
        if col_name in df.columns:
            txpen_col = col_name
            break

    if txpen_col and body.min_txpen is not None:
        vals = pd.to_numeric(df[txpen_col], errors="coerce")
        mask = mask & (vals >= body.min_txpen)
    if txpen_col and body.max_txpen is not None:
        vals = pd.to_numeric(df[txpen_col], errors="coerce")
        mask = mask & (vals <= body.max_txpen)

    filtered = df.loc[mask].copy()

    # Build GeoJSON for counting loops
    features_out: list[dict] = []
    for _, row in filtered.iterrows():
        geom = row.get("geometry")
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except Exception:
                geom = None
        elif not isinstance(geom, dict):
            geom = None

        props: dict[str, Any] = {}
        for k, v in row.items():
            if k == "geometry":
                continue
            if isinstance(v, (np.integer, np.floating)):
                v = v.item()
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                v = None
            props[k] = v

        features_out.append({"type": "Feature", "geometry": geom, "properties": props})

    compteurs_geojson = {"type": "FeatureCollection", "features": features_out}
    territory = session.data.get("territory", "unknown")

    session_manager.store_data(body.session_id, "compteurs_geojson", compteurs_geojson)

    stats = CompteursStats(
        total_loops=len(df),
        filtered_loops=len(filtered),
        territory=territory,
    )

    logger.info(
        "Compteurs generated: session=%s total=%d filtered=%d",
        body.session_id, len(df), len(filtered),
    )

    return CompteursResponse(
        session_id=body.session_id,
        stats=stats,
        geojson_feature_count=len(features_out),
    )
