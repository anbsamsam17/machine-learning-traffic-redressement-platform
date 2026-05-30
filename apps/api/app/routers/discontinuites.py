"""Discontinuites router — upload reseau + pipeline + stream noeuds avec cause.

Mirroir structurel de ``visualisation.py`` :
- A1 : tous les endpoints sont proteges par ``Depends(get_current_user)``
  (cf. ``main.py``).
- A5 : les fichiers de session sont confines a ``WORKSPACE_ROOT/{user_id}/
  {session_id}/discontinuites/`` via ``security.session_root``.
- IDOR : ``require_owned_session`` est appele systematiquement (404-sur-mismatch).

Layout disque par session :
    WORKSPACE_ROOT/{user_id}/{session_id}/discontinuites/
        segments.geojson         <- LineString FeatureCollection (input)
        nodes_with_cause.geojson <- Point FeatureCollection (output)
        stats.json               <- KPIs et cross-tab cause x topology

Endpoints :
    POST /api/discontinuites/upload-geojson    (file + session_id?)
    POST /api/discontinuites/upload-fcd        (file parquet + session_id)
    POST /api/discontinuites/analyze           (session_id)
    GET  /api/discontinuites/nodes/{session_id}
    GET  /api/discontinuites/stats/{session_id}
"""

from __future__ import annotations

import io
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings
from ..security import session_root
from ..services import discontinuites as svc
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/discontinuites", tags=["discontinuites"])


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

#: Base columns required on every segment GeoJSON (identifiant de la feature).
REQUIRED_SEGMENT_BASE: tuple[str, ...] = ("agregId",)

#: Flow columns — le GeoJSON doit exposer AU MOINS UNE de ces colonnes.
#: ``JOr`` (jour ouvre) est le nouveau nom canonique post 2026-05 — ``TVr``
#: reste accepte pour retro-compat avec les anciens exports.
FLOW_REQUIRED_ANY_OF: tuple[str, ...] = ("JOr", "TVr")

#: Backwards-compat alias kept for callers / tests still importing the
#: previous strict tuple. New code should branch on the two above.
REQUIRED_SEGMENT_COLUMNS: tuple[str, ...] = REQUIRED_SEGMENT_BASE + ("JOr",)

#: Colonnes additionnelles requises pour reconstruire le graphe HERE.
REQUIRED_GRAPH_COLUMNS: tuple[str, ...] = ("REF_IN_ID", "NREF_IN_ID")

#: Colonnes optionnelles surfaceees au scoring (drivers + topologie).
OPTIONAL_SEGMENT_COLUMNS: tuple[str, ...] = (
    "TMJOFCDTV", "TMJOFCDPL", "functional_class", "FC",
    "RAMP", "ROUNDABOUT",
    "avg_distance_before_m", "avg_min_distance_m", "truck_avg_distance_before_m",
)


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class UploadGeojsonResponse(BaseModel):
    session_id: str
    n_features: int
    bbox: list[float] | None
    file_size_mb: float
    columns: list[str]
    graph_columns_present: bool = True
    warning: str | None = None


class UploadFcdResponse(BaseModel):
    session_id: str
    n_segments: int
    columns_detected: list[str]
    file_size_mb: float


class AnalyzeResponse(BaseModel):
    session_id: str
    n_nodes_flagged: int
    n_total_nodes: int
    n_boundary_nodes: int
    n_edges: int
    pipeline_duration_s: float
    n_causes: dict[str, int]
    n_topology: dict[str, int]
    n_tier: dict[str, int]
    fcd_joined: bool = False
    fcd_columns_count: int = 0
    warning: str | None = None


class StatsResponse(BaseModel):
    session_id: str
    n_features: int
    n_total_nodes: int
    n_boundary_nodes: int
    n_edges: int
    pipeline_duration_s: float
    n_causes: dict[str, int]
    n_topology: dict[str, int]
    n_tier: dict[str, int]
    cross_tab: dict[str, dict[str, int]]
    user_rule: dict[str, float]
    fcd_joined: bool = False
    fcd_columns_count: int = 0
    fcd_columns: list[str] = []
    fcd_matched: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _disc_dir(user: UserRecord, session_id: str) -> Path:
    """Retourne le repertoire ``discontinuites/`` de la session (cree au besoin)."""
    root = session_root(user.user_id, session_id)
    target = root / "discontinuites"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _ensure_session(session_id: str | None, user: UserRecord, mode: str = "TV") -> str:
    """Retourne une session existante (verifiee) ou en cree une nouvelle."""
    if session_id:
        require_owned_session(session_id, user)
        return session_id
    session = session_manager.create_session(mode=mode, owner_user_id=user.user_id)
    try:
        session_manager.set_user_session(user.user_id, session.session_id)
    except Exception:  # noqa: BLE001 — binding best-effort.
        logger.exception(
            "Echec liaison session discontinuites %s a user %s",
            session.session_id[:8], user.user_id[:8],
        )
    return session.session_id


def _bbox_from_coords(xs: list[float], ys: list[float]) -> list[float] | None:
    if not xs or not ys:
        return None
    return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]


def _walk_geometry_coords(geom: Any, xs: list[float], ys: list[float]) -> None:
    """Append all (lon, lat) pairs from *geom* into the buffers (LineString-aware)."""
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
) -> tuple[dict, list[str], int, list[float] | None, int, list[str]]:
    """Parse .geojson / .json / .parquet en FeatureCollection canonique.

    Renvoie ``(fc, columns, n_line_features, bbox, n_features, missing_graph_cols)``.
    Leve ``HTTPException(400)`` si schema invalide.

    Les colonnes graphe HERE (REF_IN_ID/NREF_IN_ID) ne sont **plus bloquantes**
    a l'upload : leur absence est rapportee via ``missing_graph_cols`` afin que
    l'appelant puisse emettre un warning et laisser l'utilisateur ajouter ces
    colonnes via un parquet FCD ulterieur (cf. /upload-fcd).
    """
    suffix = Path(filename or "").suffix.lower()
    fc: dict

    if suffix == ".parquet":
        try:
            import geopandas as gpd

            gdf = gpd.read_parquet(io.BytesIO(raw_bytes))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=400,
                detail=f"Impossible de lire le parquet (geopandas requis): {exc}",
            ) from exc
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
            detail=(
                "Aucune geometrie LineString trouvee. Le pipeline discontinuites "
                "attend un reseau d'aretes (LineString)."
            ),
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
    # REF_IN_ID / NREF_IN_ID ne sont plus bloquants a l'upload : ils peuvent
    # arriver plus tard via /upload-fcd (le parquet FCDREFGLOBAL les contient).
    # On les remonte au caller pour generer un warning explicite.
    missing_graph = [c for c in REQUIRED_GRAPH_COLUMNS if c not in columns]

    bbox = _bbox_from_coords(xs, ys)
    return fc, sorted(columns), line_count, bbox, len(features), missing_graph


def _read_segments_geojson(path: Path):
    """Charge un GeoJSON segments en GeoDataFrame (latence minimale)."""
    import geopandas as gpd  # noqa: WPS433 — heavy dep, lazy.

    try:
        return gpd.read_file(path, engine="pyogrio")
    except Exception as exc:  # noqa: BLE001
        # Fallback : lecture JSON + from_features (cas ou pyogrio est en defaut)
        try:
            fc = json.loads(path.read_text(encoding="utf-8"))
            return gpd.GeoDataFrame.from_features(fc["features"], crs="EPSG:4326")
        except Exception as exc2:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail=f"Impossible de relire segments.geojson: {exc} / fallback: {exc2}",
            ) from exc2


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/upload-geojson", response_model=UploadGeojsonResponse)
async def upload_geojson(
    file: UploadFile = File(..., description="Fichier .geojson / .json / .parquet (aretes LineString)"),
    session_id: str | None = Form(None, description="Session ID existante (sinon nouvelle)"),
    current_user: UserRecord = Depends(get_current_user),
) -> UploadGeojsonResponse:
    """Stocke le reseau d'aretes pour le pipeline de discontinuites.

    Validation :
      - une feature LineString minimum ;
      - colonne obligatoire : ``agregId`` ;
      - au moins une colonne de debit parmi ``JOr`` (nouveau) ou ``TVr`` (legacy) ;
      - ``REF_IN_ID`` / ``NREF_IN_ID`` recommandes (peuvent venir du parquet FCD) ;
      - extension dans .geojson / .json / .parquet.
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
                f"Fichier trop volumineux ({len(raw) // (1024 * 1024)} MB). "
                f"Limite: {settings.MAX_UPLOAD_MB} MB."
            ),
        )

    sid = _ensure_session(session_id, current_user, mode="TV")

    fc, columns, n_lines, bbox, n_features, missing_graph = _parse_geojson_payload(
        raw, file.filename
    )
    graph_columns_present = not missing_graph
    warning: str | None = None
    if missing_graph:
        warning = (
            f"Colonnes graphe HERE absentes : {missing_graph}. "
            "Le pipeline a besoin de REF_IN_ID + NREF_IN_ID pour reconstruire "
            "l'adjacence des noeuds. Uploadez un parquet FCDREFGLOBAL via "
            "/upload-fcd : s'il contient ces colonnes elles seront jointes au "
            "reseau lors de /analyze."
        )

    target_dir = _disc_dir(current_user, sid)
    target = target_dir / "segments.geojson"
    payload_bytes = json.dumps(fc, ensure_ascii=False).encode("utf-8")
    try:
        target.write_bytes(payload_bytes)
    except OSError as exc:
        logger.exception("Echec ecriture segments.geojson pour sid=%s", sid[:8])
        raise HTTPException(status_code=500, detail=f"Ecriture impossible: {exc}") from exc

    # Invalide d'anciens resultats si re-upload pour eviter de servir des stats stales.
    # NOTE: on conserve fcdref.parquet — l'utilisateur peut re-uploader un geojson
    # sans avoir a re-uploader le parquet FCD (cas reel : iteration sur le reseau).
    for stale in ("nodes_with_cause.geojson", "stats.json"):
        stale_path = target_dir / stale
        if stale_path.exists():
            try:
                stale_path.unlink()
            except OSError:
                logger.warning("Impossible de supprimer %s (sid=%s)", stale, sid[:8])

    file_size_mb = round(len(payload_bytes) / (1024 * 1024), 3)

    logger.info(
        "Discontinuites upload: sid=%s file=%s n_features=%d lines=%d size=%.2fMB",
        sid[:8], file.filename, n_features, n_lines, file_size_mb,
    )

    return UploadGeojsonResponse(
        session_id=sid,
        n_features=n_features,
        bbox=bbox,
        file_size_mb=file_size_mb,
        columns=columns,
        graph_columns_present=graph_columns_present,
        warning=warning,
    )


@router.post("/upload-fcd", response_model=UploadFcdResponse)
async def upload_fcd(
    file: UploadFile = File(..., description="Fichier .parquet FCDREFGLOBAL"),
    session_id: str = Form(..., description="Session ID existante (un geojson doit deja avoir ete uploade)"),
    current_user: UserRecord = Depends(get_current_user),
) -> UploadFcdResponse:
    """Stocke un parquet FCDREFGLOBAL en complement du geojson de segments.

    Apres upload, le prochain ``/analyze`` joindra le parquet via
    ``agregId == segment_id`` (cf. ``services.discontinuites.join_fcdref``).
    Sans ce parquet, le pipeline tourne en mode degrade et les causes
    ``FCD_TV_cliff`` / ``FCD_PL_cliff`` ne peuvent pas se declencher pour
    les reseaux qui n'embarquent pas les inputs FCD bruts (cas du
    `2025_light.geojson`).

    Validation :
      - extension ``.parquet`` ;
      - colonnes minimales : ``segment_id`` + au moins une colonne
        parmi ``TMJOFCDTV, TMJOFCDPL, functional_class, RAMP, ROUNDABOUT,
        avg_distance_before_m, avg_min_distance_m, truck_avg_distance_before_m``.
    """
    settings = get_settings()
    if not file.filename:
        raise HTTPException(status_code=400, detail="Fichier sans nom recu.")

    suffix = Path(file.filename).suffix.lower()
    if suffix != ".parquet":
        raise HTTPException(
            status_code=400,
            detail=f"Extension '{suffix}' refusee pour FCDREFGLOBAL. Attendue : .parquet.",
        )

    require_owned_session(session_id, current_user)
    target_dir = _disc_dir(current_user, session_id)

    # Pre-requis : un geojson doit avoir ete uploade dans la session.
    segments_path = target_dir / "segments.geojson"
    if not segments_path.exists():
        raise HTTPException(
            status_code=400,
            detail=(
                "Aucun segments.geojson dans la session — uploadez d'abord le "
                "reseau via /upload-geojson avant de joindre le parquet FCD."
            ),
        )

    raw = await file.read()
    if len(raw) == 0:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(raw) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Fichier trop volumineux ({len(raw) // (1024 * 1024)} MB). "
                f"Limite: {settings.MAX_UPLOAD_MB} MB."
            ),
        )

    # Validation parquet : colonnes minimales + lecture par geopandas/pandas.
    try:
        import io as _io

        try:
            import geopandas as gpd  # type: ignore[import-not-found]

            df = gpd.read_parquet(_io.BytesIO(raw))
        except Exception:  # noqa: BLE001 — parquet non-geo : on retombe sur pandas.
            import pandas as pd  # type: ignore[import-not-found]

            df = pd.read_parquet(_io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001 — wrap en 400.
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de lire le parquet FCD : {exc}",
        ) from exc

    cols_present = list(df.columns)
    # Cle de jointure : on accepte plusieurs alias (segment_id, AgregId, agregId).
    # Le pipeline normalisera en interne vers 'segment_id'.
    has_join_key = any(alias in cols_present for alias in svc.FCD_JOIN_KEY_ALIASES)
    if not has_join_key:
        raise HTTPException(
            status_code=400,
            detail=(
                "Colonne de jointure absente dans le parquet FCD. Le parquet "
                "doit contenir au moins une des colonnes suivantes : "
                f"{list(svc.FCD_JOIN_KEY_ALIASES)} (cle vers 'agregId' du geojson). "
                "Schema attendu : cle de jointure + au moins une colonne FCD parmi "
                f"{list(svc.FCD_COLUMN_MAPPING.keys())}."
            ),
        )

    # Detecte les colonnes joignables via le mapping (cf. svc.FCD_COLUMN_MAPPING).
    # Une colonne est joinable si son nom de source figure dans le mapping.
    # On renvoie le nom canonique cible pour informer le client.
    cols_joinable: list[str] = []
    for source_col in cols_present:
        if source_col in svc.FCD_COLUMN_MAPPING:
            target, _scale = svc.FCD_COLUMN_MAPPING[source_col]
            if target not in cols_joinable:
                cols_joinable.append(target)
    if not cols_joinable:
        raise HTTPException(
            status_code=400,
            detail=(
                "Le parquet FCD ne contient aucune des colonnes attendues. "
                f"Sources acceptees : {list(svc.FCD_COLUMN_MAPPING.keys())}."
            ),
        )

    target = target_dir / "fcdref.parquet"
    try:
        target.write_bytes(raw)
    except OSError as exc:
        logger.exception("Echec ecriture fcdref.parquet pour sid=%s", session_id[:8])
        raise HTTPException(status_code=500, detail=f"Ecriture impossible: {exc}") from exc

    # Invalide les anciens resultats : ils ont ete calcules sans cette jointure.
    for stale in ("nodes_with_cause.geojson", "stats.json"):
        stale_path = target_dir / stale
        if stale_path.exists():
            try:
                stale_path.unlink()
            except OSError:
                logger.warning("Impossible de supprimer %s (sid=%s)", stale, session_id[:8])

    file_size_mb = round(len(raw) / (1024 * 1024), 3)
    n_segments = int(len(df))

    logger.info(
        "Discontinuites upload-fcd: sid=%s file=%s n_segments=%d cols_joinable=%d size=%.2fMB",
        session_id[:8], file.filename, n_segments, len(cols_joinable), file_size_mb,
    )

    return UploadFcdResponse(
        session_id=session_id,
        n_segments=n_segments,
        columns_detected=cols_joinable,
        file_size_mb=file_size_mb,
    )


def _load_fcd_parquet(path: Path):
    """Lecture defensive du fcdref.parquet — geopandas d'abord, pandas en fallback."""
    import io as _io

    raw = path.read_bytes()
    try:
        import geopandas as gpd  # type: ignore[import-not-found]

        try:
            return gpd.read_parquet(_io.BytesIO(raw))
        except Exception:  # noqa: BLE001 — pas un geo-parquet, fallback pandas.
            pass
    except ImportError:
        pass
    import pandas as pd  # type: ignore[import-not-found]

    return pd.read_parquet(_io.BytesIO(raw))


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    session_id: str = Form(..., description="Session ID avec un segments.geojson uploade"),
    current_user: UserRecord = Depends(get_current_user),
) -> AnalyzeResponse:
    """Lance le pipeline complet sur le geojson uploade (synchrone).

    Si un ``fcdref.parquet`` a ete uploade dans la session (cf.
    ``/upload-fcd``), il est joint au reseau par ``agregId == segment_id``
    avant d'executer le pipeline (mode nominal v4).

    Si aucun parquet FCD n'est present et que le geojson ne contient pas
    deja les inputs FCD bruts, l'analyse continue en mode degrade : un
    ``warning`` est renvoye dans le body (status 200) et la majorite des
    noeuds retombent en ``Coverage_gap``. Cela reste utilisable pour
    explorer la topologie du reseau.

    Le pipeline est entierement in-memory (cf. ``services.discontinuites``).
    Sur 241k aretes le run est de l'ordre de 90-120 s ; on garde l'execution
    synchrone — le frontend dispose deja d'un timeout 5 min sur les routes
    de generation lourdes (pattern carte).
    """
    require_owned_session(session_id, current_user)
    target_dir = _disc_dir(current_user, session_id)
    segments_path = target_dir / "segments.geojson"
    if not segments_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Aucun segments.geojson dans la session — appeler /upload-geojson d'abord.",
        )

    t0 = time.perf_counter()
    gdf = _read_segments_geojson(segments_path)

    # Detection optionnelle d'un parquet FCD pre-uploade.
    fcd_path = target_dir / "fcdref.parquet"
    fcd_df = None
    if fcd_path.exists() and fcd_path.is_file():
        try:
            fcd_df = _load_fcd_parquet(fcd_path)
            logger.info(
                "Discontinuites analyze: sid=%s fcdref.parquet detecte (%d lignes)",
                session_id[:8], len(fcd_df),
            )
        except Exception as exc:  # noqa: BLE001 — degrade gracefully.
            logger.warning(
                "Discontinuites analyze: sid=%s fcdref.parquet illisible (%s) — mode degrade",
                session_id[:8], exc,
            )
            fcd_df = None

    try:
        fc, stats = svc.run_full_pipeline(gdf, fcd_df=fcd_df)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — wrap en 500 propre.
        logger.exception("Echec pipeline discontinuites pour sid=%s", session_id[:8])
        raise HTTPException(status_code=500, detail=f"Pipeline echoue: {exc}") from exc

    nodes_path = target_dir / "nodes_with_cause.geojson"
    stats_path = target_dir / "stats.json"
    try:
        nodes_path.write_text(
            json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        stats_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.exception("Echec ecriture sorties discontinuites sid=%s", session_id[:8])
        raise HTTPException(status_code=500, detail=f"Ecriture sorties impossible: {exc}") from exc

    duration_total = round(time.perf_counter() - t0, 3)
    logger.info(
        "Discontinuites analyze: sid=%s n_nodes=%d duree=%.2fs (pipeline=%.2fs) fcd_joined=%s",
        session_id[:8], stats["n_features"], duration_total,
        stats["pipeline_duration_s"], stats.get("fcd_joined", False),
    )

    warning: str | None = None
    if not stats.get("fcd_joined", False):
        # Detection mode degrade : si la majorite des noeuds finit en Coverage_gap
        # ou Unexplained, c'est probablement faute d'inputs FCD. On previent l'user.
        causes = stats.get("n_causes") or {}
        n_total = sum(int(v) for v in causes.values())
        n_degraded = int(causes.get("Coverage_gap", 0)) + int(causes.get("Unexplained", 0))
        if n_total > 0 and n_degraded / n_total >= 0.5:
            warning = (
                "Inputs FCD non disponibles - la classification se fait en mode degrade "
                "(Coverage_gap dominant). Uploadez FCDREFGLOBAL_2025.parquet via "
                "/api/discontinuites/upload-fcd pour activer FCD_TV_cliff et FCD_PL_cliff."
            )

    return AnalyzeResponse(
        session_id=session_id,
        n_nodes_flagged=stats["n_features"],
        n_total_nodes=stats["n_total_nodes"],
        n_boundary_nodes=stats["n_boundary_nodes"],
        n_edges=stats["n_edges"],
        pipeline_duration_s=stats["pipeline_duration_s"],
        n_causes=stats["n_causes"],
        n_topology=stats["n_topology"],
        n_tier=stats["n_tier"],
        fcd_joined=bool(stats.get("fcd_joined", False)),
        fcd_columns_count=int(stats.get("fcd_columns_count", 0)),
        warning=warning,
    )


@router.get("/nodes/{session_id}")
async def get_nodes(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Stream le ``nodes_with_cause.geojson`` (Point FeatureCollection)."""
    require_owned_session(session_id, current_user)
    target_dir = _disc_dir(current_user, session_id)
    path = target_dir / "nodes_with_cause.geojson"
    if not path.exists() or not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Aucun resultat — appeler /analyze d'abord.",
        )
    return FileResponse(
        path=str(path),
        media_type="application/geo+json",
        headers={
            "Content-Type": "application/geo+json",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/stats/{session_id}", response_model=StatsResponse)
async def get_stats(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> StatsResponse:
    """Retourne les stats agregees + cross-tab cause x topology."""
    require_owned_session(session_id, current_user)
    target_dir = _disc_dir(current_user, session_id)
    stats_path = target_dir / "stats.json"
    if not stats_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Aucune statistique — appeler /analyze d'abord.",
        )
    try:
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.exception("Stats corrompues pour sid=%s", session_id[:8])
        raise HTTPException(status_code=500, detail=f"Stats illisibles: {exc}") from exc

    return StatsResponse(
        session_id=session_id,
        n_features=int(stats.get("n_features", 0)),
        n_total_nodes=int(stats.get("n_total_nodes", 0)),
        n_boundary_nodes=int(stats.get("n_boundary_nodes", 0)),
        n_edges=int(stats.get("n_edges", 0)),
        pipeline_duration_s=float(stats.get("pipeline_duration_s", 0.0)),
        n_causes={str(k): int(v) for k, v in (stats.get("n_causes") or {}).items()},
        n_topology={str(k): int(v) for k, v in (stats.get("n_topology") or {}).items()},
        n_tier={str(k): int(v) for k, v in (stats.get("n_tier") or {}).items()},
        cross_tab={
            str(cause): {str(topo): int(n) for topo, n in (tbl or {}).items()}
            for cause, tbl in (stats.get("cross_tab") or {}).items()
        },
        user_rule={str(k): float(v) for k, v in (stats.get("user_rule") or {}).items()},
        fcd_joined=bool(stats.get("fcd_joined", False)),
        fcd_columns_count=int(stats.get("fcd_columns_count", 0)),
        fcd_columns=[str(c) for c in (stats.get("fcd_columns") or [])],
        fcd_matched=int(stats.get("fcd_matched", 0)),
    )
