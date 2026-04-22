"""Mapping router — auto-detect columns + validate/build learning DataFrame."""

from __future__ import annotations

import json
import logging
from difflib import get_close_matches

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mapping", tags=["mapping"])


# ---------------------------------------------------------------------------
# 35 target columns (mirrored from column_mapper.py)
# ---------------------------------------------------------------------------

TARGET_COLUMNS: list[str] = [
    "Type", "Identifiant", "Commune", "Route", "PRD",
    "MJA TV 2023", "MJA PL 2023", "MJA TV 2024", "MJA PL 2024",
    "MJA TV 2025", "MJA PL 2025",
    "TMJABCTV", "TMJABCPL", "Annee", "Road", "TMJAVL", "TMJAPL", "TMJATV",
    "TxPen", "TxPenPL", "variabilite_FCD",
    "car_count", "car_average_speed_kmh", "car_average_distance_km",
    "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
    "REF_IN_ID", "NREF_IN_ID", "TUNNEL", "status", "RAMP", "ROUNDABOUT",
    "ST_NAME", "flag_comptage", "geometry",
]

SYNONYMS: dict[str, list[str]] = {
    "TxPen": ["TxPenTVRef", "TxPenRef", "TXPENTV", "TXPENTVREF", "txpen", "TxPen"],
    "TxPenPL": ["TxPenPLRef", "TXPENPL", "TXPENPLREF", "txpenpl"],
    "TMJATV": ["TMJAFCDTV", "TMJFCDTV", "tmjatv"],
    "TMJAPL": ["TMJAFCDPL", "TMJFCDPL", "tmjapl"],
    "geometry": ["__geometry_json", "geom", "the_geom", "shape", "SHAPE"],
}

CRITICAL_COLS: list[str] = [
    "TMJATV", "TMJAPL", "TxPen",
    "car_average_distance_km", "car_average_speed_kmh",
    "truck_min_average_distance_km", "truck_average_speed_kmh",
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class AutoMapRequest(BaseModel):
    session_id: str


class ColumnMapping(BaseModel):
    target: str
    source: str | None
    confidence: str  # "exact" | "synonym" | "fuzzy" | "missing"


class AutoMapResponse(BaseModel):
    session_id: str
    mappings: list[ColumnMapping]
    source_columns: list[str]
    unmapped_count: int


class ValidateRequest(BaseModel):
    session_id: str
    mapping: dict[str, str | None]  # target -> source (user-confirmed)
    territory: str = "default"


class ValidateResponse(BaseModel):
    session_id: str
    rows: int
    columns: list[str]
    missing_critical: list[str]
    warnings: list[str]
    preview: list[dict]


# ---------------------------------------------------------------------------
# Core logic (ported from column_mapper.py)
# ---------------------------------------------------------------------------

def _auto_map(source_cols: list[str]) -> list[ColumnMapping]:
    source_lower = {c.lower(): c for c in source_cols}
    result: list[ColumnMapping] = []

    for target in TARGET_COLUMNS:
        # 1. Exact match (case-insensitive)
        if target.lower() in source_lower:
            result.append(ColumnMapping(
                target=target,
                source=source_lower[target.lower()],
                confidence="exact",
            ))
            continue

        # 2. Synonym match
        found = None
        for alias in SYNONYMS.get(target, []):
            if alias.lower() in source_lower:
                found = source_lower[alias.lower()]
                break
        if found:
            result.append(ColumnMapping(target=target, source=found, confidence="synonym"))
            continue

        # 3. Fuzzy match
        matches = get_close_matches(target.lower(), source_lower.keys(), n=1, cutoff=0.75)
        if matches:
            result.append(ColumnMapping(
                target=target,
                source=source_lower[matches[0]],
                confidence="fuzzy",
            ))
            continue

        # 4. Not found
        result.append(ColumnMapping(target=target, source=None, confidence="missing"))

    return result


def _build_learning_df(
    raw_df: pd.DataFrame,
    mapping: dict[str, str | None],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the standardised 35-column DataFrame (in-memory, no disk save)."""
    cols: dict[str, pd.Series] = {}
    warnings: list[str] = []
    n = len(raw_df)

    # Ensure all 35+1 target columns exist, even if frontend sent a partial mapping
    for target in TARGET_COLUMNS:
        source = mapping.get(target)
        if source is not None and source in raw_df.columns:
            cols[target] = raw_df[source].reset_index(drop=True)
        else:
            cols[target] = pd.Series([np.nan] * n)
            if source is None:
                warnings.append(f"Colonne '{target}' non trouvee dans les donnees source.")

    df = pd.DataFrame(cols)

    # Derive TxPen if absent
    if "TxPen" in df.columns and df["TxPen"].isna().all():
        tmjatv = pd.to_numeric(df.get("TMJATV"), errors="coerce")
        tmjabctv = pd.to_numeric(df.get("TMJABCTV"), errors="coerce")
        mask = tmjabctv > 0
        df.loc[mask, "TxPen"] = (tmjatv[mask] / tmjabctv[mask] * 100.0).round(4)

    # Derive TxPenPL if absent
    if "TxPenPL" in df.columns and df["TxPenPL"].isna().all():
        tmjapl = pd.to_numeric(df.get("TMJAPL"), errors="coerce")
        tmjabcpl = pd.to_numeric(df.get("TMJABCPL"), errors="coerce")
        mask = tmjabcpl > 0
        df.loc[mask, "TxPenPL"] = (tmjapl[mask] / tmjabcpl[mask] * 100.0).round(4)

    # Derive flag_comptage if absent
    if "flag_comptage" in df.columns and df["flag_comptage"].isna().all() and "Type" in df.columns:
        types = df["Type"].astype(str).str.strip().str.lower()
        df["flag_comptage"] = types.isin(["per", "tou"]).astype(int)

    missing_critical = [c for c in CRITICAL_COLS if c in df.columns and df[c].isna().all()]
    if missing_critical:
        warnings.append(
            f"Colonnes critiques manquantes: {missing_critical}. "
            "L'entrainement risque d'echouer."
        )

    return df, missing_critical, warnings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/auto", response_model=AutoMapResponse)
async def auto_map(body: AutoMapRequest) -> AutoMapResponse:
    """Run fuzzy auto-mapping of source columns to the 35 target columns."""
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        raise HTTPException(status_code=400, detail="Aucun fichier uploade dans cette session.")

    source_cols = list(raw_df.columns)
    mappings = _auto_map(source_cols)

    # Store proposed mapping
    proposed = {m.target: m.source for m in mappings}
    session_manager.store_data(body.session_id, "proposed_mapping", proposed)

    unmapped = sum(1 for m in mappings if m.source is None)

    logger.info(
        "Auto-map: session=%s mapped=%d/%d",
        body.session_id, len(mappings) - unmapped, len(mappings),
    )

    return AutoMapResponse(
        session_id=body.session_id,
        mappings=mappings,
        source_columns=source_cols,
        unmapped_count=unmapped,
    )


@router.put("/validate", response_model=ValidateResponse)
async def validate_mapping(body: ValidateRequest) -> ValidateResponse:
    """Accept the user-confirmed mapping and build the learning DataFrame."""
    logger.info("validate_mapping: start session=%s territory=%s", body.session_id, body.territory)
    session = session_manager.get_session(body.session_id)
    if session is None:
        logger.warning("validate_mapping: session not found %s", body.session_id)
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        logger.warning("validate_mapping: raw_df missing for session %s", body.session_id)
        raise HTTPException(status_code=400, detail="Aucun fichier uploade dans cette session.")

    logger.info("validate_mapping: raw_df shape=%s", raw_df.shape)
    df, missing_critical, warnings = _build_learning_df(raw_df, body.mapping)
    logger.info("validate_mapping: learning_df built shape=%s missing=%s", df.shape, missing_critical)

    # Coerce geometry dicts -> JSON strings so pyarrow doesn't choke on nested dict columns
    if "geometry" in df.columns:
        df["geometry"] = df["geometry"].apply(
            lambda v: json.dumps(v) if isinstance(v, dict) else v
        )

    session_manager.store_data(body.session_id, "learning_df", df)
    session_manager.store_data(body.session_id, "confirmed_mapping", body.mapping)
    session_manager.store_data(body.session_id, "territory", body.territory)
    logger.info("validate_mapping: session data stored")

    # Build a JSON-safe preview — coerce any non-JSON-native values to string
    def _to_json_safe(v):
        if v is None:
            return ""
        if isinstance(v, (str, bool, int)):
            return v
        if isinstance(v, float):
            # NaN / inf aren't valid JSON
            if v != v or v in (float("inf"), float("-inf")):
                return ""
            return v
        if isinstance(v, dict):
            try:
                return json.dumps(v, default=str)
            except Exception:
                return str(v)
        if isinstance(v, (list, tuple)):
            try:
                return json.dumps(list(v), default=str)
            except Exception:
                return str(v)
        # numpy scalars / arrays / pandas types / everything else
        if hasattr(v, "tolist"):
            try:
                return json.dumps(v.tolist(), default=str)
            except Exception:
                return str(v)
        return str(v)

    preview_df = df.head(10).copy()
    preview = [
        {col: _to_json_safe(row[col]) for col in preview_df.columns}
        for _, row in preview_df.iterrows()
    ]

    logger.info(
        "Mapping validated: session=%s rows=%d missing_critical=%s",
        body.session_id, len(df), missing_critical,
    )

    return ValidateResponse(
        session_id=body.session_id,
        rows=len(df),
        columns=list(df.columns),
        missing_critical=missing_critical,
        warnings=warnings,
        preview=preview,
    )
