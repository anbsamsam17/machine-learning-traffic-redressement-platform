"""Compteurs router — generate counting-loops.geojson from uploaded data + column mapping."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compteurs", tags=["compteurs"])


# ---------------------------------------------------------------------------
# Target columns for counting-loops.geojson
# ---------------------------------------------------------------------------

TARGET_COLUMNS: list[str] = [
    "Identifiant du Poste / Section",
    "Annee",
    "Nom de la Commune",
    "RD",
    "PRD",
    "Type de capteur",
    "TMJA Tous Vehicules (veh/jour)",
    "TMJA Poids Lourds (veh/jour)",
    "Sens de comptage",
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CompteursGenerateRequest(BaseModel):
    session_id: str
    column_mapping: dict[str, str]  # target_col -> source_col
    missing_columns_action: dict[str, str] = {}  # col -> "default" | "remove"
    missing_columns_default: dict[str, str] = {}  # col -> default value
    filter_flag_comptage: bool = False
    longitude_col: str | None = None
    latitude_col: str | None = None
    output_filename: str = "counting-loops"


class CompteursStats(BaseModel):
    total_rows: int
    output_features: int
    columns: list[str]
    type_distribution: dict[str, int] | None = None
    year_distribution: dict[str, int] | None = None


class CompteursResponse(BaseModel):
    session_id: str
    stats: CompteursStats
    geojson_feature_count: int


# ---------------------------------------------------------------------------
# Core logic (mirrors Streamlit create_counting_loops_geojson)
# ---------------------------------------------------------------------------

def _build_compteurs_geojson(
    raw_df: pd.DataFrame,
    column_mapping: dict[str, str],
    missing_columns_action: dict[str, str],
    missing_columns_default: dict[str, str],
    filter_flag_comptage: bool,
    longitude_col: str | None,
    latitude_col: str | None,
) -> tuple[dict[str, Any], CompteursStats]:
    """Build a GeoJSON FeatureCollection for counting loops."""

    df = raw_df.copy()

    # ---- Optional filter: flag_comptage == 1 --------------------------------
    if filter_flag_comptage and "flag_comptage" in df.columns:
        flag = pd.to_numeric(df["flag_comptage"], errors="coerce")
        df = df.loc[flag == 1].copy()

    total_rows = len(df)

    # ---- Build columns from mapping -----------------------------------------
    gdf_data: dict[str, Any] = {}

    for target_col, source_col in column_mapping.items():
        if source_col and source_col in df.columns:
            gdf_data[target_col] = df[source_col].values
        # If source not found, skip — it'll be handled by missing_columns logic

    # ---- Handle missing columns (default or remove) -------------------------
    for col_name, action in missing_columns_action.items():
        if col_name in gdf_data:
            continue  # Already mapped, skip
        if action == "default":
            default_value = missing_columns_default.get(col_name, "")
            gdf_data[col_name] = [default_value] * total_rows
        # action == "remove" → don't include

    # Always include "Sens de comptage" if it has a default value
    if "Sens de comptage" not in gdf_data and "Sens de comptage" in missing_columns_default:
        gdf_data["Sens de comptage"] = [missing_columns_default["Sens de comptage"]] * total_rows

    result_df = pd.DataFrame(gdf_data)

    # ---- Format numeric columns ---------------------------------------------
    if "Annee" in result_df.columns:
        result_df["Annee"] = pd.to_numeric(result_df["Annee"], errors="coerce")

    if "PRD" in result_df.columns:
        result_df["PRD"] = pd.to_numeric(result_df["PRD"], errors="coerce")

    if "TMJA Tous Vehicules (veh/jour)" in result_df.columns:
        result_df["TMJA Tous Vehicules (veh/jour)"] = (
            pd.to_numeric(result_df["TMJA Tous Vehicules (veh/jour)"], errors="coerce")
            .round(0)
        )

    if "TMJA Poids Lourds (veh/jour)" in result_df.columns:
        result_df["TMJA Poids Lourds (veh/jour)"] = (
            pd.to_numeric(result_df["TMJA Poids Lourds (veh/jour)"], errors="coerce")
            .round(0)
        )

    # ---- Determine geometry -------------------------------------------------
    has_geojson_geometry = "geometry" in df.columns or "__geometry_json" in df.columns
    has_lonlat = longitude_col and latitude_col

    features: list[dict[str, Any]] = []
    for idx in range(len(result_df)):
        props: dict[str, Any] = {}
        for col in result_df.columns:
            v = result_df.iloc[idx][col]
            if isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.floating,)):
                v = float(v)
            if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                v = None
            props[col] = v

        # Resolve geometry
        geom = None
        if has_geojson_geometry:
            raw_geom = df.iloc[idx].get("__geometry_json") or df.iloc[idx].get("geometry")
            if isinstance(raw_geom, str):
                try:
                    geom = json.loads(raw_geom)
                except Exception:
                    geom = None
            elif isinstance(raw_geom, dict):
                geom = raw_geom
        elif has_lonlat:
            try:
                lon = float(df.iloc[idx][longitude_col])
                lat = float(df.iloc[idx][latitude_col])
                if not (np.isnan(lon) or np.isnan(lat)):
                    geom = {"type": "Point", "coordinates": [lon, lat]}
            except (ValueError, TypeError, KeyError):
                geom = None
        # Also check for __lon/__lat columns from GeoJSON upload parsing
        if geom is None and "__lon" in df.columns and "__lat" in df.columns:
            try:
                lon = float(df.iloc[idx]["__lon"])
                lat = float(df.iloc[idx]["__lat"])
                if not (np.isnan(lon) or np.isnan(lat)):
                    geom = {"type": "Point", "coordinates": [lon, lat]}
            except (ValueError, TypeError):
                pass

        features.append({"type": "Feature", "geometry": geom, "properties": props})

    geojson: dict[str, Any] = {"type": "FeatureCollection", "features": features}

    # ---- Build stats --------------------------------------------------------
    type_dist: dict[str, int] | None = None
    if "Type de capteur" in result_df.columns:
        counts = result_df["Type de capteur"].value_counts()
        type_dist = {str(k): int(v) for k, v in counts.items()}

    year_dist: dict[str, int] | None = None
    if "Annee" in result_df.columns:
        year_vals = result_df["Annee"].dropna()
        if len(year_vals) > 0:
            counts = year_vals.astype(int).value_counts()
            year_dist = {str(k): int(v) for k, v in counts.items()}

    stats = CompteursStats(
        total_rows=total_rows,
        output_features=len(features),
        columns=list(result_df.columns),
        type_distribution=type_dist,
        year_distribution=year_dist,
    )

    return geojson, stats


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=CompteursResponse)
async def generate_compteurs(
    body: CompteursGenerateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> CompteursResponse:
    """Generate counting-loops GeoJSON from uploaded data and column mapping."""
    session = require_owned_session(body.session_id, current_user)

    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        raise HTTPException(
            status_code=400,
            detail="Aucune donnee disponible. Uploadez un fichier d'abord.",
        )

    try:
        # B4: heavy DataFrame + geometry processing - offload to worker thread
        geojson, stats = await asyncio.to_thread(
            _build_compteurs_geojson,
            raw_df,
            body.column_mapping,
            body.missing_columns_action,
            body.missing_columns_default,
            body.filter_flag_comptage,
            body.longitude_col,
            body.latitude_col,
        )
    except Exception as exc:
        logger.exception("Compteurs generation failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Erreur lors de la generation: {exc}")

    # Store in session for later export
    session_manager.store_data(body.session_id, "compteurs_geojson", geojson)
    session_manager.store_data(body.session_id, "compteurs_filename", body.output_filename)

    logger.info(
        "Compteurs generated: session=%s total=%d features=%d",
        body.session_id, stats.total_rows, stats.output_features,
    )

    return CompteursResponse(
        session_id=body.session_id,
        stats=stats,
        geojson_feature_count=stats.output_features,
    )


@router.get("/download/{session_id}")
async def download_compteurs(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Download the generated counting-loops GeoJSON."""
    session = require_owned_session(session_id, current_user)

    compteurs_geojson = session.data.get("compteurs_geojson")
    if compteurs_geojson is None:
        raise HTTPException(
            status_code=400,
            detail="Aucun fichier compteurs genere. Lancez /api/compteurs/generate d'abord.",
        )

    filename = session.data.get("compteurs_filename", "counting-loops")
    content = json.dumps(compteurs_geojson, ensure_ascii=False, indent=2)

    return Response(
        content=content.encode("utf-8"),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.geojson"',
        },
    )
