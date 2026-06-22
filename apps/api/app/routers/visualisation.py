"""Visualisation router — upload + stream geojson segments and sensor points.

Distinct module from /api/carte (which is the generation pipeline). This one
serves the "visualisation libre" workflow: the user already has a generated
carte (geojson lines: agregId/JOr/... or agregId/TVr legacy) and a counter
dataset (CSV/xlsx with TMJA + lat/lon), and just wants to see them on the
same map.

Schema migration note (2026-05): the segment GeoJSON now exposes ``JOr``
(jour ouvre, the new canonical name) instead of ``TVr``. This router accepts
both — see ``REQUIRED_SEGMENT_BASE`` / ``FLOW_REQUIRED_ANY_OF`` below — so
legacy carte exports keep working.

Storage layout (per A5):
    WORKSPACE_ROOT/{user_id}/{session_id}/visualisation/
        segments.geojson   <- LineString FeatureCollection from upload-geojson
        sensors.geojson    <- Point FeatureCollection built from upload-sensors

Endpoints (all behind Depends(get_current_user)):
    POST /api/visualisation/upload-geojson    (multipart: file + session_id?)
    POST /api/visualisation/upload-sensors    (multipart: file + session_id)
    GET  /api/visualisation/geojson/{session_id}
    GET  /api/visualisation/sensors/{session_id}
    GET  /api/visualisation/metadata/{session_id}
"""

from __future__ import annotations

import io
import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings
from ..security import session_root
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/visualisation", tags=["visualisation"])


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Base columns required on every segment GeoJSON — without ``agregId`` we
#: cannot key per-feature interactions (popups, search, hover state).
REQUIRED_SEGMENT_BASE: tuple[str, ...] = ("agregId",)

#: Flow columns — the GeoJSON must expose AT LEAST ONE of these. ``JOr`` is
#: the new canonical name (jour ouvre, post 2026-05 carte schema) and
#: ``TVr`` is the legacy name kept for retro-compat with older exports.
FLOW_REQUIRED_ANY_OF: tuple[str, ...] = ("JOr", "TVr")

#: Backwards-compat alias kept for callers / tests still importing the
#: previous strict tuple. New code should branch on the two above.
REQUIRED_SEGMENT_COLUMNS: tuple[str, ...] = REQUIRED_SEGMENT_BASE + ("JOr",)

#: Known optional columns — surfaced to the frontend for legend / popups.
#: Covers the new 2026-05 carte schema (JOr / DPL / HPM / HPS / direction /
#: saturation v3 diagnostic) AND the legacy TVr* fields so older sessions
#: keep displaying without warnings.
OPTIONAL_SEGMENT_COLUMNS: tuple[str, ...] = (
    # Legacy TVr (retro-compat with pre-2026-05 carte exports).
    "TVrmin", "TVrmax",
    # New canonical jour-ouvre flow (JOr replaces TVr).
    "JOrmin", "JOrmax",
    # PL flow (unchanged from legacy schema).
    "DPL", "DPLmin", "DPLmax", "PL", "PLred", "VLred",
    # HPM (heure de pointe matin) — only present if HPM model loaded.
    "PM", "PMmin", "PMmax",
    # HPS (heure de pointe soir) — only present if HPS model loaded.
    "PS", "PSmin", "PSmax",
    # Direction / heading produced by the new carte pipeline.
    "DD", "HD",
    # Saturation v3 diagnostic columns (alpha effective + critical zone flag).
    "alpha_eff", "alpha_source", "is_critical_zone",
    # Topology / functional class (unchanged).
    "FC", "RAMP", "ROUNDABOUT", "functional_class",
    # FCD raw inputs (legacy).
    "TMJOFCDTV", "TMJOFCDPL",
    "avg_distance_car", "avg_distance_truck",
    "truck_avg_speed", "car_avg_speed",
    "length_m",
)

#: Sensor schema (mirrors apps/web/app/compteurs/page.tsx TARGET_COLUMNS).
SENSOR_REQUIRED_COLUMNS: tuple[str, ...] = (
    "Identifiant du Poste / Section",
    "Annee",
    "Nom de la Commune",
    "RD",
    "PRD",
    "Type de capteur",
    "TMJA Tous Vehicules (veh/jour)",
    "TMJA Poids Lourds (veh/jour)",
)

#: Aliases accepted for latitude / longitude detection (lowercased compare).
_LAT_ALIASES: tuple[str, ...] = (
    "lat", "latitude", "y", "ycoord", "y_coord", "coord_y", "wgs84_lat",
)
_LON_ALIASES: tuple[str, ...] = (
    "lon", "long", "longitude", "lng", "x", "xcoord", "x_coord", "coord_x", "wgs84_lon",
)

#: Canonical frontend keys — the map circle layers (apps/web/lib/map/setup.ts,
#: installSensorLayers) filter on EXACTLY these property names:
#:   TV : ["to-number", ["get", "TMJA Tous Vehicules (veh/jour)"], 0] > 0
#:   PL : ["to-number", ["get", "TMJA Poids Lourds (veh/jour)"], 0] > 0
#: We must therefore emit these keys in each feature's properties, otherwise
#: the filter evaluates to 0 everywhere and no circle is drawn.
CANONICAL_TV_KEY: str = "TMJA Tous Vehicules (veh/jour)"
CANONICAL_PL_KEY: str = "TMJA Poids Lourds (veh/jour)"

#: Aliases accepted for the TV (tous vehicules) debit column (lowercased
#: compare). The canonical name comes first, then the build_counting_loops
#: output name, then a few reasonable shorthand variants. NOTE: none of these
#: may contain "poids lourds" — that would collide with the PL detection.
_TV_DEBIT_ALIASES: tuple[str, ...] = (
    "tmja tous vehicules (veh/jour)",          # canonique
    "moyenne jours ouvrable (veh/jour)",        # counting-loops.geojson
    "tmjobctv",
    "tmjatv",
    "tmja tv",
    "tmja_tv",
)

#: Aliases accepted for the PL (poids lourds) debit column (lowercased compare).
_PL_DEBIT_ALIASES: tuple[str, ...] = (
    "tmja poids lourds (veh/jour)",                       # canonique
    "moyenne poids lourds jours ouvrable (veh/jour)",      # counting-loops-pl.geojson
    "tmjobcpl",
    "tmjapl",
    "tmja pl",
    "tmja_pl",
)


def _detect_debit_columns(columns: Any) -> tuple[str | None, str | None]:
    """Detect the source TV / PL debit columns among *columns* via aliases.

    Returns ``(tv_col, pl_col)`` as the real (original-cased) column names, or
    ``None`` when no alias matched. Matching is case-insensitive. The PL guard
    is applied first so a column containing "poids lourds" can never be picked
    as the TV column even if it also matched a looser TV alias.
    """
    lower_to_real: dict[str, str] = {}
    for c in columns:
        key = str(c).lower()
        # First occurrence wins (stable wrt column order).
        lower_to_real.setdefault(key, c)

    pl_col = next(
        (lower_to_real[a] for a in _PL_DEBIT_ALIASES if a in lower_to_real),
        None,
    )
    tv_col = next(
        (
            lower_to_real[a]
            for a in _TV_DEBIT_ALIASES
            if a in lower_to_real and "poids lourds" not in a
        ),
        None,
    )
    # Defensive: never let the same physical column be claimed by both.
    if tv_col is not None and tv_col == pl_col:
        tv_col = None
    return tv_col, pl_col


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class GeojsonUploadResponse(BaseModel):
    session_id: str
    filename: str
    n_features: int
    bbox: list[float] | None
    file_size_mb: float
    columns: list[str]


class SensorsUploadResponse(BaseModel):
    session_id: str
    filename: str
    n_sensors: int
    n_tv: int
    n_pl: int
    bbox: list[float] | None


class _SegmentsMetadata(BaseModel):
    n_features: int
    bbox: list[float] | None
    columns: list[str]
    file_size_mb: float


class _SensorsMetadata(BaseModel):
    n_sensors: int
    n_tv: int
    n_pl: int
    bbox: list[float] | None


class MetadataResponse(BaseModel):
    segments: _SegmentsMetadata | None
    sensors: _SensorsMetadata | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _viz_dir(user: UserRecord, session_id: str) -> Path:
    """Return (and create) the per-session visualisation directory.

    Uses ``security.session_root`` so the path is automatically confined to
    WORKSPACE_ROOT/{user_id}/{session_id}/ (A5) and segment names are
    validated against the traversal regex.
    """
    root = session_root(user.user_id, session_id)
    viz = root / "visualisation"
    viz.mkdir(parents=True, exist_ok=True)
    return viz


def _ensure_session(session_id: str | None, user: UserRecord, mode: str = "TV") -> str:
    """Return an existing owned session_id or create a new one bound to *user*.

    Mirrors the upload.py pattern where session creation is implicit on the
    first POST: callers may omit ``session_id`` and the server allocates a
    fresh one.
    """
    if session_id:
        # Ownership check raises 404 on mismatch (same code path as IDOR).
        require_owned_session(session_id, user)
        return session_id

    session = session_manager.create_session(mode=mode, owner_user_id=user.user_id)
    # Bind the new session to the user so /api/sessions/current restores it.
    try:
        session_manager.set_user_session(user.user_id, session.session_id)
    except Exception:  # noqa: BLE001 — non-fatal; binding is best-effort.
        logger.exception(
            "Failed to bind visualisation session %s to user %s",
            session.session_id[:8], user.user_id[:8],
        )
    return session.session_id


def _bbox_from_coords(xs: list[float], ys: list[float]) -> list[float] | None:
    """Return [xmin, ymin, xmax, ymax] from raw coord lists; None when empty."""
    if not xs or not ys:
        return None
    return [
        float(min(xs)),
        float(min(ys)),
        float(max(xs)),
        float(max(ys)),
    ]


def _walk_geometry_coords(geom: dict | None, xs: list[float], ys: list[float]) -> None:
    """Append all (lon, lat) pairs found inside *geom* into *xs* / *ys*.

    Handles Point / LineString / MultiLineString / Polygon / MultiPolygon /
    GeometryCollection. Non-finite values are skipped so a single bad coord
    does not poison the bbox.
    """
    if not isinstance(geom, dict):
        return
    gtype = geom.get("type")
    coords = geom.get("coordinates")

    def _add(lon: Any, lat: Any) -> None:
        try:
            x = float(lon)
            y = float(lat)
        except (TypeError, ValueError):
            return
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        xs.append(x)
        ys.append(y)

    if gtype == "Point":
        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
            _add(coords[0], coords[1])
    elif gtype in ("LineString", "MultiPoint"):
        for pt in coords or []:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                _add(pt[0], pt[1])
    elif gtype in ("MultiLineString", "Polygon"):
        for line in coords or []:
            for pt in line or []:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    _add(pt[0], pt[1])
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            for line in poly or []:
                for pt in line or []:
                    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                        _add(pt[0], pt[1])
    elif gtype == "GeometryCollection":
        for sub in geom.get("geometries") or []:
            _walk_geometry_coords(sub, xs, ys)


def _parse_geojson_payload(
    raw_bytes: bytes,
    filename: str,
) -> tuple[dict, list[str], int, list[float] | None, int]:
    """Parse incoming GeoJSON / JSON / Parquet payload into normalised parts.

    Returns ``(feature_collection, columns, n_line_features, bbox, total_features)``.

    Raises ``HTTPException(400)`` on parse/validation failure (no LineString,
    missing required cols, etc.).
    """
    suffix = Path(filename or "").suffix.lower()

    fc: dict
    if suffix == ".parquet":
        try:
            import geopandas as gpd  # noqa: WPS433 — lazy import, heavy dep.

            gdf = gpd.read_parquet(io.BytesIO(raw_bytes))
        except Exception as exc:  # noqa: BLE001 — wrap any parquet error.
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lire le parquet (geopandas requis): {exc}",
            ) from exc

        # Build a FeatureCollection from the GeoDataFrame.
        try:
            fc = json.loads(gdf.to_json())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de convertir le GeoDataFrame en GeoJSON: {exc}",
            ) from exc
    elif suffix in {".geojson", ".json", ""}:
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail="Le fichier n'est pas encode en UTF-8 valide.",
            ) from exc
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"JSON invalide: {exc.msg} (ligne {exc.lineno}, col {exc.colno})",
            ) from exc

        if isinstance(parsed, dict) and parsed.get("type") == "FeatureCollection":
            fc = parsed
        elif isinstance(parsed, dict) and parsed.get("type") == "Feature":
            fc = {"type": "FeatureCollection", "features": [parsed]}
        else:
            raise HTTPException(
                status_code=400,
                detail="Structure GeoJSON non reconnue: FeatureCollection ou Feature attendus.",
            )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Format non supporte: '{suffix}'. Utilisez .geojson, .json ou .parquet.",
        )

    features = fc.get("features")
    if not isinstance(features, list) or not features:
        raise HTTPException(
            status_code=400,
            detail="FeatureCollection vide: aucune feature exploitable.",
        )

    # Validate at least one LineString / MultiLineString feature is present.
    line_count = 0
    columns: set[str] = set()
    xs: list[float] = []
    ys: list[float] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") or {}
        if isinstance(props, dict):
            columns.update(props.keys())
        geom = feat.get("geometry")
        if isinstance(geom, dict) and geom.get("type") in ("LineString", "MultiLineString"):
            line_count += 1
        if isinstance(geom, dict):
            _walk_geometry_coords(geom, xs, ys)

    if line_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Aucune geometrie LineString trouvee. La visualisation segments attend des lignes.",
        )

    # Validation : agregId obligatoire + au moins une colonne de debit
    # (JOr = nouveau schema, TVr = legacy). Cf. REQUIRED_SEGMENT_BASE /
    # FLOW_REQUIRED_ANY_OF — la presence d'une seule des deux suffit.
    missing_base = [c for c in REQUIRED_SEGMENT_BASE if c not in columns]
    has_flow = any(c in columns for c in FLOW_REQUIRED_ANY_OF)
    if missing_base or not has_flow:
        detail_parts: list[str] = []
        if missing_base:
            detail_parts.append(f"colonnes manquantes: {missing_base}")
        if not has_flow:
            detail_parts.append(
                f"il faut au moins une colonne de debit: {list(FLOW_REQUIRED_ANY_OF)}"
            )
        raise HTTPException(
            status_code=400,
            detail=(
                "Colonnes invalides — "
                + " ; ".join(detail_parts)
                + ". Schema minimal: agregId + JOr (ou TVr legacy) + geometry."
            ),
        )

    bbox = _bbox_from_coords(xs, ys)
    return fc, sorted(columns), line_count, bbox, len(features)


def _resolve_latlon_columns(
    df_columns: list[str],
) -> tuple[str | None, str | None]:
    """Pick the (lon_col, lat_col) pair from a sensor dataframe's columns.

    Case-insensitive match against ``_LAT_ALIASES`` / ``_LON_ALIASES``. The
    first hit wins so the alias tuples are ordered most-specific first.
    """
    lower_to_real: dict[str, str] = {c.lower(): c for c in df_columns}

    lat_col = next((lower_to_real[a] for a in _LAT_ALIASES if a in lower_to_real), None)
    lon_col = next((lower_to_real[a] for a in _LON_ALIASES if a in lower_to_real), None)
    return lon_col, lat_col


def _parse_sensors_dataframe(raw_bytes: bytes, filename: str) -> pd.DataFrame:
    """Parse the uploaded CSV / xlsx into a DataFrame."""
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                return pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, sep=None, engine="python")
            except UnicodeDecodeError:
                continue
            except Exception as exc:  # noqa: BLE001 — try next encoding then surface.
                logger.debug("CSV parse with %s failed: %s", enc, exc)
        raise HTTPException(status_code=400, detail="Impossible de decoder le CSV (UTF-8 / latin-1 / cp1252).")

    if suffix in {".xlsx", ".xls"}:
        try:
            return pd.read_excel(io.BytesIO(raw_bytes))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lire le fichier Excel: {exc}",
            ) from exc

    raise HTTPException(
        status_code=400,
        detail=f"Format capteurs non supporte: '{suffix}'. Utilisez .csv ou .xlsx.",
    )


def _normalise_sensor_props(raw_props: dict) -> dict:
    """Sanitise a sensor properties dict for JSON / numeric coercion.

    Mirrors the per-cell logic in ``_build_sensors_geojson`` so geojson and
    parquet sources go through the same normalisation pipeline (drops NaN,
    casts numpy scalars to Python primitives, keeps strings as-is).
    """
    props: dict[str, Any] = {}
    for col, val in raw_props.items():
        if isinstance(val, (np.integer,)):
            props[col] = int(val)
        elif isinstance(val, (np.floating,)):
            fv = float(val)
            props[col] = fv if math.isfinite(fv) else None
        elif isinstance(val, (np.bool_,)):
            props[col] = bool(val)
        elif isinstance(val, float):
            props[col] = val if math.isfinite(val) else None
        elif val is None:
            props[col] = None
        else:
            # pd.isna would raise on list/dict — guard explicitly.
            if not isinstance(val, (list, dict, tuple)):
                try:
                    if pd.isna(val):
                        props[col] = None
                        continue
                except (TypeError, ValueError):
                    pass
            props[col] = val
    return props


def _inject_canonical_debit_keys(props: dict) -> dict:
    """Add the canonical TV / PL debit keys to *props* (in place) if absent.

    The frontend circle layers filter on the EXACT property names
    ``"TMJA Tous Vehicules (veh/jour)"`` / ``"TMJA Poids Lourds (veh/jour)"``.
    counting-loops files name the debit column differently, so we detect the
    source column via aliases and copy its coerced numeric value under the
    canonical key — only when the canonical key is not already present (to
    avoid clobbering files that already follow the canonical schema). The
    original column is kept untouched (used by the popup).
    """
    tv_col, pl_col = _detect_debit_columns(props.keys())
    if tv_col is not None and CANONICAL_TV_KEY not in props:
        v_tv = _coerce_numeric(props.get(tv_col))
        if v_tv is not None:
            props[CANONICAL_TV_KEY] = v_tv
    if pl_col is not None and CANONICAL_PL_KEY not in props:
        v_pl = _coerce_numeric(props.get(pl_col))
        if v_pl is not None:
            props[CANONICAL_PL_KEY] = v_pl
    return props


def _count_tv_pl_from_features(features: list[dict]) -> tuple[int, int]:
    """Count features whose TV / PL debit is > 0.

    Detection goes through ``_detect_debit_columns`` (alias-based,
    case-insensitive) so counting-loops files — which name the debit column
    ``Moyenne jours ouvrable (veh/jour)`` (TV) or
    ``Moyenne Poids Lourds jours ouvrable (veh/jour)`` (PL) — are counted, not
    just the canonical ``TMJA …`` names. Per-feature detection is used because
    geojson features may carry heterogeneous property sets.
    """
    n_tv = 0
    n_pl = 0
    for feat in features:
        props = feat.get("properties") or {}
        if not isinstance(props, dict):
            continue
        tv_col, pl_col = _detect_debit_columns(props.keys())
        if tv_col is not None:
            v_tv = _coerce_numeric(props.get(tv_col))
            if v_tv is not None and v_tv > 0:
                n_tv += 1
        if pl_col is not None:
            v_pl = _coerce_numeric(props.get(pl_col))
            if v_pl is not None and v_pl > 0:
                n_pl += 1
    return n_tv, n_pl


def _parse_sensors_geojson_bytes(raw_bytes: bytes) -> dict:
    """Parse a geojson/json blob into a FeatureCollection (raises on errors).

    Accepts a top-level FeatureCollection or a single Feature; rewraps the
    latter to keep downstream code uniform.
    """
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Le fichier capteurs n'est pas encode en UTF-8 valide.",
        ) from exc
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"GeoJSON capteurs invalide: {exc.msg} (ligne {exc.lineno}, col {exc.colno})",
        ) from exc
    if isinstance(parsed, dict) and parsed.get("type") == "FeatureCollection":
        return parsed
    if isinstance(parsed, dict) and parsed.get("type") == "Feature":
        return {"type": "FeatureCollection", "features": [parsed]}
    raise HTTPException(
        status_code=400,
        detail="Structure GeoJSON capteurs non reconnue: FeatureCollection ou Feature attendus.",
    )


def _build_point_fc_from_geojson(parsed: dict) -> tuple[dict, int, int, int, list[float] | None]:
    """Build a normalised Point FeatureCollection from a parsed geojson dict.

    Validates that the majority of features are Points, drops geometries
    without usable coordinates, and recomputes the bbox + n_tv/n_pl on the
    normalised output so the response stays consistent with the csv branch.
    """
    raw_features = parsed.get("features")
    if not isinstance(raw_features, list) or not raw_features:
        raise HTTPException(
            status_code=400,
            detail="FeatureCollection capteurs vide: aucune feature exploitable.",
        )

    features: list[dict] = []
    xs: list[float] = []
    ys: list[float] = []
    n_points = 0
    n_total = 0
    for feat in raw_features:
        if not isinstance(feat, dict):
            continue
        n_total += 1
        geom = feat.get("geometry")
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        lon = _coerce_numeric(coords[0])
        lat = _coerce_numeric(coords[1])
        if lon is None or lat is None:
            continue
        n_points += 1
        xs.append(lon)
        ys.append(lat)
        raw_props = feat.get("properties") or {}
        if not isinstance(raw_props, dict):
            raw_props = {}
        props = _normalise_sensor_props(raw_props)
        # Emit canonical TV/PL keys so the frontend circle filter matches.
        props = _inject_canonical_debit_keys(props)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    if n_total == 0:
        raise HTTPException(
            status_code=400,
            detail="FeatureCollection capteurs vide: aucune feature exploitable.",
        )
    # Require a clear majority of Point features — guards against accidental
    # uploads of LineString geojsons through the sensors dropzone.
    if n_points * 2 < n_total:
        raise HTTPException(
            status_code=400,
            detail=(
                "Geometries majoritairement non-Point. Attendu: capteurs ponctuels (Point)."
            ),
        )
    if not features:
        raise HTTPException(
            status_code=400,
            detail="Aucun capteur exploitable: coordonnees absentes ou invalides.",
        )

    fc = {"type": "FeatureCollection", "features": features}
    n_tv, n_pl = _count_tv_pl_from_features(features)
    bbox = _bbox_from_coords(xs, ys)
    return fc, len(features), n_tv, n_pl, bbox


def _parse_sensors_parquet(raw_bytes: bytes) -> tuple[dict, int, int, int, list[float] | None]:
    """Read a parquet file (geo or plain) into a Point FeatureCollection.

    Tries ``geopandas.read_parquet`` first; on failure (file has no geometry
    column or geopandas raises), falls back to ``pandas.read_parquet`` and
    re-uses ``_build_sensors_geojson`` with auto-detected lat/lon columns.
    """
    # Geo path: try geopandas first.
    try:
        import geopandas as gpd  # noqa: WPS433 — heavy optional dep.

        try:
            gdf = gpd.read_parquet(io.BytesIO(raw_bytes))
            geo_ok = True
        except Exception:  # noqa: BLE001 — not a geo-parquet, fall back.
            gdf = None
            geo_ok = False
    except ImportError:
        gdf = None
        geo_ok = False

    if geo_ok and gdf is not None:
        try:
            parsed = json.loads(gdf.to_json())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de convertir le GeoDataFrame en GeoJSON: {exc}",
            ) from exc
        return _build_point_fc_from_geojson(parsed)

    # Fallback: plain parquet — must have lat/lon columns.
    try:
        df = pd.read_parquet(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de lire le parquet: {exc}",
        ) from exc

    if df.empty:
        raise HTTPException(status_code=400, detail="Fichier capteurs parquet vide.")

    lon_col, lat_col = _resolve_latlon_columns(list(df.columns))
    if lon_col is None or lat_col is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Parquet sans geometrie ni colonnes lat/lon detectables. Attendues: "
                f"lon dans {list(_LON_ALIASES)} et lat dans {list(_LAT_ALIASES)}."
            ),
        )
    return _build_sensors_geojson(df, lon_col, lat_col)


def _coerce_numeric(value: Any) -> float | None:
    """Best-effort numeric coercion that tolerates French decimal commas."""
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        v = float(value)
        return v if math.isfinite(v) else None
    if isinstance(value, str):
        s = value.strip().replace(",", ".")
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def _build_sensors_geojson(
    df: pd.DataFrame,
    lon_col: str,
    lat_col: str,
) -> tuple[dict, int, int, int, list[float] | None]:
    """Convert *df* into a Point FeatureCollection + summary stats."""
    features: list[dict] = []
    xs: list[float] = []
    ys: list[float] = []
    n_tv = 0
    n_pl = 0

    # Pre-locate the TV / PL debit columns via aliases (operator + counting-
    # loops files name them differently — see _TV_DEBIT_ALIASES / _PL_…).
    tmja_tv_col, tmja_pl_col = _detect_debit_columns(df.columns)

    for _, row in df.iterrows():
        lon = _coerce_numeric(row.get(lon_col))
        lat = _coerce_numeric(row.get(lat_col))
        if lon is None or lat is None:
            # Skip points without usable coordinates (operator data often has
            # a few rows with empty cells — keep the rest rather than failing).
            continue

        xs.append(lon)
        ys.append(lat)

        props: dict[str, Any] = {}
        for col, val in row.items():
            # Skip the geometry source columns from properties — they're carried by geometry.
            if col == lon_col or col == lat_col:
                continue
            if isinstance(val, (np.integer,)):
                props[col] = int(val)
            elif isinstance(val, (np.floating,)):
                fv = float(val)
                props[col] = fv if math.isfinite(fv) else None
            elif isinstance(val, (np.bool_,)):
                props[col] = bool(val)
            elif isinstance(val, float):
                props[col] = val if math.isfinite(val) else None
            elif pd.isna(val) if not isinstance(val, (list, dict)) else False:
                props[col] = None
            else:
                props[col] = val

        if tmja_tv_col is not None:
            v_tv = _coerce_numeric(row.get(tmja_tv_col))
            # Emit the canonical TV key so the frontend circle filter matches.
            if v_tv is not None and CANONICAL_TV_KEY not in props:
                props[CANONICAL_TV_KEY] = v_tv
            if v_tv is not None and v_tv > 0:
                n_tv += 1
        if tmja_pl_col is not None:
            v_pl = _coerce_numeric(row.get(tmja_pl_col))
            # Emit the canonical PL key so the frontend circle filter matches.
            if v_pl is not None and CANONICAL_PL_KEY not in props:
                props[CANONICAL_PL_KEY] = v_pl
            if v_pl is not None and v_pl > 0:
                n_pl += 1

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    bbox = _bbox_from_coords(xs, ys)
    fc = {"type": "FeatureCollection", "features": features}
    return fc, len(features), n_tv, n_pl, bbox


def _read_meta_sidecar(viz: Path, kind: str) -> dict | None:
    """Load cached metadata sidecar (avoids re-parsing big geojsons on GETs)."""
    meta_path = viz / f"{kind}.meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Sidecar metadata corrupt: %s", meta_path)
        return None


def _write_meta_sidecar(viz: Path, kind: str, payload: dict) -> None:
    meta_path = viz / f"{kind}.meta.json"
    try:
        meta_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to persist sidecar %s: %s", meta_path, exc)


# ---------------------------------------------------------------------------
# Routes — uploads
# ---------------------------------------------------------------------------


@router.post("/upload-geojson", response_model=GeojsonUploadResponse)
async def upload_geojson(
    file: UploadFile = File(..., description="Fichier .geojson / .json / .parquet de segments LineString"),
    session_id: str | None = Form(None, description="Session ID existante (omettre pour en creer une)"),
    current_user: UserRecord = Depends(get_current_user),
) -> GeojsonUploadResponse:
    """Receive a segments GeoJSON / Parquet and persist it on disk.

    The payload MUST contain at least one LineString feature with the
    ``agregId`` property + at least one flow column among ``JOr`` (new
    canonical name) or ``TVr`` (legacy retro-compat). Other columns —
    DPL / HPM (PM*) / HPS (PS*) / direction (DD/HD) / saturation diagnostic
    — are optional and surfaced in the response so the frontend can build
    popups and legends dynamically.
    """
    settings = get_settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichier sans nom recu.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".geojson", ".json", ".parquet"}:
        raise HTTPException(
            status_code=400,
            detail=f"Extension '{suffix}' refusee. Acceptees: .geojson, .json, .parquet.",
        )

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier trop volumineux ({len(raw) // (1024*1024)} MB). "
                f"Limite: {settings.MAX_UPLOAD_MB} MB."
            ),
        )

    sid = _ensure_session(session_id, current_user, mode="TV")

    fc, columns, n_line_features, bbox, n_features = _parse_geojson_payload(raw, file.filename)

    viz = _viz_dir(current_user, sid)
    target = viz / "segments.geojson"
    # Re-serialise canonical FeatureCollection (drops noise, ensures UTF-8).
    payload_bytes = json.dumps(fc, ensure_ascii=False).encode("utf-8")
    try:
        target.write_bytes(payload_bytes)
    except OSError as exc:
        logger.exception("Failed to write segments.geojson for sid=%s", sid[:8])
        raise HTTPException(status_code=500, detail=f"Ecriture impossible: {exc}") from exc

    file_size_mb = round(len(payload_bytes) / (1024 * 1024), 3)

    _write_meta_sidecar(viz, "segments", {
        "n_features": n_features,
        "n_line_features": n_line_features,
        "bbox": bbox,
        "columns": columns,
        "file_size_mb": file_size_mb,
        "filename": file.filename,
    })

    logger.info(
        "Visualisation geojson uploaded: sid=%s file=%s n_features=%d lines=%d size=%.2fMB",
        sid[:8], file.filename, n_features, n_line_features, file_size_mb,
    )

    return GeojsonUploadResponse(
        session_id=sid,
        filename=file.filename,
        n_features=n_features,
        bbox=bbox,
        file_size_mb=file_size_mb,
        columns=columns,
    )


@router.post("/upload-sensors", response_model=SensorsUploadResponse)
async def upload_sensors(
    file: UploadFile = File(
        ...,
        description="Fichier capteurs .csv, .xlsx, .geojson, .json ou .parquet",
    ),
    session_id: str = Form(..., description="Session ID existante"),
    current_user: UserRecord = Depends(get_current_user),
) -> SensorsUploadResponse:
    """Receive a counter file, build a Point FeatureCollection.

    Accepted formats:
      - ``.csv`` / ``.xlsx`` : tabular, lat/lon auto-detected from column
        aliases (lat / latitude / Y / lon / longitude / X / ...).
      - ``.geojson`` / ``.json`` : Point FeatureCollection — coordinates are
        already in ``geometry.coordinates``, properties are kept as-is.
      - ``.parquet`` : geo-parquet (with geometry) read via geopandas, or
        plain parquet with lat/lon columns.

    Rows / features without usable coordinates are skipped. The TMJA TV / PL
    counter columns are optional: missing them only sets the counters to 0
    instead of failing the upload.
    """
    settings = get_settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichier sans nom recu.")

    suffix = Path(file.filename).suffix.lower()
    accepted = {".csv", ".xlsx", ".xls", ".geojson", ".json", ".parquet"}
    if suffix not in accepted:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Extension '{suffix}' refusee. Acceptees: .csv, .xlsx, "
                ".geojson, .json, .parquet."
            ),
        )

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier trop volumineux ({len(raw) // (1024*1024)} MB). "
                f"Limite: {settings.MAX_UPLOAD_MB} MB."
            ),
        )

    sid = _ensure_session(session_id, current_user, mode="TV")

    # Dispatch by format. csv/xlsx → DataFrame path; geojson/parquet → direct FC path.
    fc: dict
    n_sensors: int
    n_tv: int
    n_pl: int
    bbox: list[float] | None
    lon_col: str | None = None
    lat_col: str | None = None
    missing_optional: list[str] = []

    if suffix in {".csv", ".xlsx", ".xls"}:
        df = _parse_sensors_dataframe(raw, file.filename)
        if df.empty:
            raise HTTPException(status_code=400, detail="Fichier capteurs vide.")

        lon_col, lat_col = _resolve_latlon_columns(list(df.columns))
        if lon_col is None or lat_col is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Colonnes lat/lon introuvables. Attendues: "
                    f"lon dans {list(_LON_ALIASES)} et lat dans {list(_LAT_ALIASES)}."
                ),
            )

        # Warn (don't fail) on missing optional schema columns — operator files
        # vary. The two canonical TMJA columns are considered present whenever
        # an alias is detected (counting-loops files name them differently), so
        # a valid counting-loops upload is NOT flagged as missing its debit col.
        present_lower = {c.lower() for c in df.columns}
        tv_col_alias, pl_col_alias = _detect_debit_columns(df.columns)
        alias_satisfied: set[str] = set()
        if tv_col_alias is not None:
            alias_satisfied.add(CANONICAL_TV_KEY.lower())
        if pl_col_alias is not None:
            alias_satisfied.add(CANONICAL_PL_KEY.lower())
        missing_optional = [
            c
            for c in SENSOR_REQUIRED_COLUMNS
            if c.lower() not in present_lower and c.lower() not in alias_satisfied
        ]
        if missing_optional:
            logger.warning(
                "Visualisation sensors: colonnes attendues manquantes (sid=%s): %s",
                sid[:8], missing_optional,
            )

        fc, n_sensors, n_tv, n_pl, bbox = _build_sensors_geojson(df, lon_col, lat_col)
    elif suffix in {".geojson", ".json"}:
        parsed = _parse_sensors_geojson_bytes(raw)
        fc, n_sensors, n_tv, n_pl, bbox = _build_point_fc_from_geojson(parsed)
    else:  # .parquet
        fc, n_sensors, n_tv, n_pl, bbox = _parse_sensors_parquet(raw)

    if n_sensors == 0:
        raise HTTPException(
            status_code=400,
            detail="Aucun capteur exploitable: toutes les lignes ont des coordonnees invalides.",
        )

    viz = _viz_dir(current_user, sid)
    target = viz / "sensors.geojson"
    payload_bytes = json.dumps(fc, ensure_ascii=False).encode("utf-8")
    try:
        target.write_bytes(payload_bytes)
    except OSError as exc:
        logger.exception("Failed to write sensors.geojson for sid=%s", sid[:8])
        raise HTTPException(status_code=500, detail=f"Ecriture impossible: {exc}") from exc

    file_size_mb = round(len(payload_bytes) / (1024 * 1024), 3)
    _write_meta_sidecar(viz, "sensors", {
        "n_sensors": n_sensors,
        "n_tv": n_tv,
        "n_pl": n_pl,
        "bbox": bbox,
        "file_size_mb": file_size_mb,
        "filename": file.filename,
        "lon_col": lon_col,
        "lat_col": lat_col,
        "missing_optional_columns": missing_optional,
        "source_format": suffix.lstrip("."),
    })

    logger.info(
        "Visualisation sensors uploaded: sid=%s file=%s fmt=%s n=%d tv=%d pl=%d size=%.2fMB",
        sid[:8], file.filename, suffix.lstrip("."), n_sensors, n_tv, n_pl, file_size_mb,
    )

    return SensorsUploadResponse(
        session_id=sid,
        filename=file.filename,
        n_sensors=n_sensors,
        n_tv=n_tv,
        n_pl=n_pl,
        bbox=bbox,
    )


# ---------------------------------------------------------------------------
# Routes — GETs
# ---------------------------------------------------------------------------


def _serve_geojson_file(viz: Path, kind: str, detail_missing: str) -> FileResponse:
    """Common implementation for GET segments / sensors.

    Streams the file with cache-friendly headers. ``kind`` is ``"segments"``
    or ``"sensors"``; ``detail_missing`` is the 404 message when the file
    has not been uploaded yet for this session.
    """
    path = viz / f"{kind}.geojson"
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=detail_missing)

    headers = {
        "Content-Type": "application/geo+json",
        "Cache-Control": "private, max-age=3600",
    }
    return FileResponse(
        path=str(path),
        media_type="application/geo+json",
        headers=headers,
    )


@router.get("/geojson/{session_id}")
async def get_segments_geojson(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Stream the uploaded ``segments.geojson`` (LineString FeatureCollection)."""
    require_owned_session(session_id, current_user)
    viz = _viz_dir(current_user, session_id)
    return _serve_geojson_file(
        viz,
        "segments",
        "Aucun GeoJSON segments uploade pour cette session.",
    )


@router.get("/sensors/{session_id}")
async def get_sensors_geojson(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Stream the derived ``sensors.geojson`` (Point FeatureCollection)."""
    require_owned_session(session_id, current_user)
    viz = _viz_dir(current_user, session_id)
    return _serve_geojson_file(
        viz,
        "sensors",
        "Aucun fichier capteurs uploade pour cette session.",
    )


@router.get("/metadata/{session_id}", response_model=MetadataResponse)
async def get_visualisation_metadata(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> MetadataResponse:
    """Return summary metadata for the uploaded segments + sensors.

    Either field may be ``null`` independently: a session can have only
    segments uploaded, only sensors, both, or neither (in which case both
    are ``null`` — the response is still 200 to let the frontend distinguish
    "session valid, nothing uploaded" from "session not found").
    """
    require_owned_session(session_id, current_user)
    viz = _viz_dir(current_user, session_id)

    segments_meta: _SegmentsMetadata | None = None
    sensors_meta: _SensorsMetadata | None = None

    seg_payload = _read_meta_sidecar(viz, "segments")
    if seg_payload is not None:
        segments_meta = _SegmentsMetadata(
            n_features=int(seg_payload.get("n_features", 0)),
            bbox=seg_payload.get("bbox"),
            columns=list(seg_payload.get("columns") or []),
            file_size_mb=float(seg_payload.get("file_size_mb", 0.0)),
        )
    elif (viz / "segments.geojson").exists():
        # No sidecar (legacy upload) — derive minimum stats from the file.
        try:
            fc = json.loads((viz / "segments.geojson").read_text(encoding="utf-8"))
            feats = fc.get("features") or []
            cols: set[str] = set()
            xs: list[float] = []
            ys: list[float] = []
            for f in feats:
                if isinstance(f, dict):
                    props = f.get("properties") or {}
                    if isinstance(props, dict):
                        cols.update(props.keys())
                    _walk_geometry_coords(f.get("geometry"), xs, ys)
            segments_meta = _SegmentsMetadata(
                n_features=len(feats),
                bbox=_bbox_from_coords(xs, ys),
                columns=sorted(cols),
                file_size_mb=round((viz / "segments.geojson").stat().st_size / (1024 * 1024), 3),
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to derive segments metadata: %s", exc)

    sen_payload = _read_meta_sidecar(viz, "sensors")
    if sen_payload is not None:
        sensors_meta = _SensorsMetadata(
            n_sensors=int(sen_payload.get("n_sensors", 0)),
            n_tv=int(sen_payload.get("n_tv", 0)),
            n_pl=int(sen_payload.get("n_pl", 0)),
            bbox=sen_payload.get("bbox"),
        )
    elif (viz / "sensors.geojson").exists():
        try:
            fc = json.loads((viz / "sensors.geojson").read_text(encoding="utf-8"))
            feats = fc.get("features") or []
            xs: list[float] = []
            ys: list[float] = []
            for f in feats:
                if isinstance(f, dict):
                    _walk_geometry_coords(f.get("geometry"), xs, ys)
            sensors_meta = _SensorsMetadata(
                n_sensors=len(feats),
                n_tv=0,
                n_pl=0,
                bbox=_bbox_from_coords(xs, ys),
            )
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to derive sensors metadata: %s", exc)

    return MetadataResponse(segments=segments_meta, sensors=sensors_meta)
