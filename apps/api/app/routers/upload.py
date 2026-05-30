"""Upload router — parse GeoJSON/CSV/SHP, upload validation data, upload model zip."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings
from ..error_messages import user_message
from ..session import session_manager
from .sessions import get_current_user_optional

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])

# Maximum decompressed size (1 GB) — zip bomb protection
_MAX_DECOMPRESSED_BYTES = 1 * 1024 * 1024 * 1024


def _check_zip_bomb(content: bytes) -> None:
    """Raise HTTPException if total uncompressed size exceeds 1 GB."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > _MAX_DECOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Archive suspecte: taille decompressee "
                           f"({total_uncompressed // (1024*1024)} MB) depasse la limite de 1 GB.",
                )
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Archive ZIP invalide.")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class UploadResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: list[str]
    preview: list[dict]


class ValidationUploadResponse(BaseModel):
    session_id: str
    filename: str
    rows: int
    columns: list[str]


class ModelUploadResponse(BaseModel):
    session_id: str
    model_files: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_file_to_df(content: bytes, filename: str) -> pd.DataFrame:
    """Parse raw bytes into a pandas DataFrame (GeoJSON, CSV, SHP, or Parquet).

    Parquet supports the geo-parquet flavour (geometry stored as WKB) used by
    FCDREFGLOBAL — when present, the geometry column is converted to GeoJSON
    dicts so the rest of the pipeline (heading, map) can consume it like any
    other geojson upload.
    """
    suffix = Path(filename).suffix.lower()

    if suffix == ".csv":
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                return pd.read_csv(io.BytesIO(content), encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError("Impossible de decoder le fichier CSV.")

    if suffix == ".parquet":
        try:
            import geopandas as gpd
            gdf = gpd.read_parquet(io.BytesIO(content))
            df = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))
            if "geometry" in gdf.columns:
                df["geometry"] = gdf["geometry"].apply(
                    lambda g: g.__geo_interface__ if g else None
                )
                df["__geometry_json"] = gdf["geometry"].apply(
                    lambda g: json.dumps(g.__geo_interface__) if g else None
                )
            return df
        except Exception:
            # Fall back to plain parquet (no geometry)
            return pd.read_parquet(io.BytesIO(content))

    if suffix in {".geojson", ".json"}:
        raw = json.loads(content.decode("utf-8"))
        if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
            rows = []
            for feature in raw.get("features", []):
                props = dict(feature.get("properties", {}))
                geom = feature.get("geometry")
                if isinstance(geom, dict) and geom.get("type") == "Point":
                    coords = geom.get("coordinates") or []
                    props["__lon"] = coords[0] if len(coords) > 0 else None
                    props["__lat"] = coords[1] if len(coords) > 1 else None
                props["geometry"] = geom
                props["__geometry_json"] = json.dumps(geom) if geom else None
                rows.append(props)
            return pd.DataFrame(rows)
        if isinstance(raw, list):
            return pd.DataFrame(raw)
        raise ValueError("Structure JSON/GeoJSON non supportee.")

    if suffix == ".shp":
        raise HTTPException(
            status_code=400,
            detail="Shapefile upload requires a .zip containing .shp, .shx, .dbf. Use /api/upload/model endpoint.",
        )

    if suffix == ".zip":
        # ZIP containing shapefile components — check for zip bomb first
        _check_zip_bomb(content)
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                zf.extractall(tmpdir)
            shp_files = list(Path(tmpdir).rglob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found in the ZIP archive.")
            try:
                import geopandas as gpd
                gdf = gpd.read_file(str(shp_files[0]))
                df = pd.DataFrame(gdf.drop(columns="geometry", errors="ignore"))
                if "geometry" in gdf.columns:
                    df["geometry"] = gdf["geometry"].apply(
                        lambda g: g.__geo_interface__ if g else None
                    )
                    df["__geometry_json"] = gdf["geometry"].apply(
                        lambda g: json.dumps(g.__geo_interface__) if g else None
                    )
                return df
            except Exception as exc:
                raise ValueError(f"Impossible de lire le Shapefile: {exc}")

    raise ValueError(f"Format de fichier non supporte: {suffix}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=UploadResponse)
async def upload_data(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("TV"),
    current_user: UserRecord = Depends(get_current_user),
) -> UploadResponse:
    """Upload a raw data file (GeoJSON, CSV, or zipped Shapefile), parse it in memory."""
    settings = get_settings()

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux ({len(content) // (1024*1024)} MB). "
                   f"Maximum autorise: {settings.MAX_UPLOAD_MB} MB.",
        )

    try:
        df = _parse_file_to_df(content, file.filename or "data.csv")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("upload_data: failed to parse file %s", file.filename)
        raise HTTPException(status_code=400, detail=user_message(exc))

    # P0-1: bind the session to the authenticated user so subsequent calls
    # can enforce ownership via `require_owned_session(...)`. Without the
    # owner, any authenticated user could access any session by guessing
    # its id (IDOR).
    session = session_manager.create_session(mode=mode, owner_user_id=current_user.user_id)
    session_manager.store_data(session.session_id, "raw_df", df)
    session_manager.store_data(session.session_id, "filename", file.filename)

    # Register this session as the user's active one so
    # GET /api/sessions/current can restore the frontend state after a
    # reload (APP-P0-4). Done after data is stored so the very next call to
    # /current already sees a usable session.
    try:
        session_manager.set_user_session(current_user.user_id, session.session_id)
    except Exception:
        logger.exception("Failed to bind session %s to user %s", session.session_id, current_user.user_id)

    preview = df.head(10).fillna("").to_dict(orient="records")
    # Convert geometry dicts to string in preview for JSON serialization
    for row in preview:
        for k, v in row.items():
            if isinstance(v, dict):
                row[k] = json.dumps(v)

    logger.info(
        "Upload OK: session=%s file=%s rows=%d cols=%d",
        session.session_id, file.filename, len(df), len(df.columns),
    )

    return UploadResponse(
        session_id=session.session_id,
        filename=file.filename or "unknown",
        rows=len(df),
        columns=list(df.columns),
        preview=preview,
    )


@router.post("/validation", response_model=ValidationUploadResponse)
async def upload_validation_data(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: UserRecord = Depends(get_current_user),
) -> ValidationUploadResponse:
    """Upload a validation dataset for model evaluation."""
    # P0-2: enforce ownership — refuses cross-tenant access with 404 (not 403
    # to avoid leaking session id existence).
    session = require_owned_session(session_id, current_user)

    settings = get_settings()
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux.")

    try:
        df = _parse_file_to_df(content, file.filename or "validation.csv")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "upload_validation_data: failed to parse file %s (session=%s)",
            file.filename, session_id,
        )
        raise HTTPException(status_code=400, detail=user_message(exc))

    session_manager.store_data(session_id, "validation_df", df)
    session_manager.store_data(session_id, "validation_filename", file.filename)

    logger.info("Validation data uploaded: session=%s rows=%d", session_id, len(df))

    return ValidationUploadResponse(
        session_id=session_id,
        filename=file.filename or "unknown",
        rows=len(df),
        columns=list(df.columns),
    )


@router.post("/model", response_model=ModelUploadResponse)
async def upload_model(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    current_user: UserRecord = Depends(get_current_user),
) -> ModelUploadResponse:
    """Upload a model archive (.zip containing .h5, .json, .mat)."""
    # P0-2: enforce ownership before touching the session.
    session = require_owned_session(session_id, current_user)

    content = await file.read()
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Un fichier .zip est attendu.")

    # Zip bomb protection for model uploads
    _check_zip_bomb(content)

    try:
        model_files: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.endswith((".h5", ".json", ".mat", ".weights.h5")):
                    model_files[name] = zf.read(name)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Archive ZIP invalide.")
    except Exception as exc:
        logger.exception(
            "upload_model: failed to extract model archive (session=%s)", session_id,
        )
        raise HTTPException(status_code=400, detail=user_message(exc))

    if not model_files:
        raise HTTPException(
            status_code=400,
            detail="Aucun fichier modele (.h5, .json, .mat) trouve dans l'archive.",
        )

    session_manager.store_data(session_id, "uploaded_models", model_files)

    logger.info("Model uploaded: session=%s files=%s", session_id, list(model_files.keys()))

    return ModelUploadResponse(
        session_id=session_id,
        model_files=list(model_files.keys()),
    )
