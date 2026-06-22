"""Evolution router — carte d'evolution des debits (metrique JOr).

A partir de DEUX cartes de debits redressees (annee1=T1, annee2=T2, base=T2),
produit une carte d'evolution par troncon : appariement 3 niveaux (cle exacte
``agregId`` -> map-matching geometrique -> verification BAN), puis calcul du
pourcentage d'evolution JOr=(T2-T1)/T1*100 (et Delta absolu dJOr), avec
garde-fous (plancher emergent, JOr null si T1<=0, clamp d'affichage +/-100 %)
et indicateur de significativite ``sig`` (IC JOr disjoints).

Le calcul (map-matching + BAN reverse-geocoding) est LONG : il est lance en
tache de fond (``asyncio.to_thread``) et alimente une progression lue par
``GET /status/{session_id}``. Le GeoJSON resultat est consomme par le viewer
MapLibre existant (``/carte/visualiser``), avec palette divergente rouge<->vert
centree sur 0 (champ ``JOr_display`` pour la couleur, ``sig`` pour l'attenuation).

Toute la logique metier vit dans ``app.services.evolution`` (io / matching /
compute / service) ; ce routeur n'orchestre que le transport HTTP, l'auth, la
session et la progression (calque sur ``routers/carte.py`` et ``routers/upload.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evolution", tags=["evolution"])


# ---------------------------------------------------------------------------
# Status registry (process-local)
# ---------------------------------------------------------------------------
#
# La generation tourne dans un thread worker (``asyncio.to_thread``). Pour
# exposer la progression sans dependre du backend de session (le RedisBackend
# n'observe pas les mutations en place d'un dict), on tient un registre
# process-local ``session_id -> status dict`` protege par un verrou. Le
# resultat final (GeoJSON + stats) est lui persiste dans la session pour
# survivre au-dela de la duree de vie du process worker et beneficier du TTL.
_status_lock = threading.Lock()
_status_registry: dict[str, dict[str, Any]] = {}

# Clefs de stockage dans la session.
_KEY_T1 = "evolution_t1_geojson"
_KEY_T2 = "evolution_t2_geojson"
_KEY_RESULT = "evolution_result_geojson"
_KEY_STATS = "evolution_stats"
_KEY_STATUS = "evolution_status"


def _init_status(session_id: str) -> dict[str, Any]:
    """(Re)initialise l'etat de progression d'une session."""
    st: dict[str, Any] = {
        "stage": "queued",
        "progress": 0.0,
        "done": False,
        "error": None,
        "stats": None,
    }
    with _status_lock:
        _status_registry[session_id] = st
    return st


def _set_status(session_id: str, **changes: Any) -> None:
    """Mise a jour atomique de l'etat de progression process-local."""
    with _status_lock:
        st = _status_registry.setdefault(
            session_id,
            {"stage": "queued", "progress": 0.0, "done": False, "error": None, "stats": None},
        )
        st.update(changes)


def _read_status(session_id: str) -> dict[str, Any] | None:
    """Lecture defensive (copie) de l'etat process-local, sinon None."""
    with _status_lock:
        st = _status_registry.get(session_id)
        return dict(st) if st is not None else None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EvolutionUploadResponse(BaseModel):
    session_id: str


class EvolutionGenerateRequest(BaseModel):
    session_id: str
    use_ban: bool = True
    plancher_t1: float = Field(default=50.0, ge=0)
    include_new: bool = False


class EvolutionGenerateResponse(BaseModel):
    session_id: str
    started: bool


class EvolutionStatusResponse(BaseModel):
    stage: str
    progress: float
    done: bool
    error: str | None = None
    stats: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _read_geojson_upload(file: UploadFile, label: str) -> bytes:
    """Lire et valider sommairement un upload GeoJSON (taille + extension + JSON).

    Retourne les octets bruts (le service ``io.load_carte_geojson`` accepte les
    bytes directement et fait la validation geometrique complete).
    """
    settings = get_settings()
    name = (file.filename or "").lower()
    if not name.endswith((".geojson", ".json")):
        raise HTTPException(
            status_code=400,
            detail=f"{label} doit etre un fichier .geojson ou .json",
        )

    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"{label} trop volumineux ({len(content) // (1024 * 1024)} MB). "
                f"Maximum autorise : {settings.MAX_UPLOAD_MB} MB."
            ),
        )
    if not content:
        raise HTTPException(status_code=400, detail=f"{label} est vide.")

    # Validation legere : JSON parseable + FeatureCollection. La validation
    # geometrique fine (LineString, EPSG) est faite par le service au load.
    try:
        head = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"{label} : GeoJSON invalide ({exc}).") from exc
    if not isinstance(head, dict) or head.get("type") != "FeatureCollection":
        raise HTTPException(
            status_code=400,
            detail=f"{label} doit etre une FeatureCollection GeoJSON.",
        )
    return content


def _run_generation(
    session_id: str,
    t1_bytes: bytes,
    t2_bytes: bytes,
    *,
    use_ban: bool,
    plancher_t1: float,
    include_new: bool,
) -> None:
    """Corps de la generation, execute dans un thread worker (bloquant).

    Alimente le registre de statut process-local via le callback ``progress``
    du service, puis persiste le resultat (GeoJSON + stats) dans la session.
    """
    # Import differe (geopandas / shapely / le service sont lourds — on ne
    # paie le cout qu'au lancement d'une generation, pas a l'import du routeur).
    from ..services.evolution import EvolutionOptions, generate_evolution

    def _progress(pct: float, stage: str) -> None:
        # Le service emet pct dans [0, 1] ; on expose 0..100 pour /status.
        try:
            value = max(0.0, min(100.0, float(pct) * 100.0))
        except (TypeError, ValueError):
            value = 0.0
        _set_status(session_id, stage=str(stage), progress=round(value, 1))

    try:
        _set_status(session_id, stage="load", progress=0.0, done=False, error=None)
        options = EvolutionOptions(
            use_ban=use_ban,
            plancher_t1=plancher_t1,
            progress=_progress,
        )
        # ``include_new`` (troncons "nouveau" = T2 seul) : conserve dans le
        # GeoJSON par defaut (categorie "nouveau"). Quand False, on filtre la
        # FeatureCollection en sortie. Le contrat metier garde la valeur brute
        # dans la data ; on se contente d'un filtre de la collection.
        geojson, stats = generate_evolution(
            t1_bytes,
            t2_bytes,
            options=options,
        )

        if not include_new:
            feats = geojson.get("features", []) if isinstance(geojson, dict) else []
            kept = [f for f in feats if (f.get("properties") or {}).get("categorie") != "nouveau"]
            geojson = {**geojson, "features": kept}

        # Persistance du resultat dans la session (survit au worker, TTL gere).
        # json.dumps cote io/compute garantit deja l'absence de NaN/inf ; on
        # stocke le dict tel quel (serialisation JSON faite par /result).
        session_manager.store_data(session_id, _KEY_RESULT, geojson)
        session_manager.store_data(session_id, _KEY_STATS, stats)

        _set_status(
            session_id,
            stage="done",
            progress=100.0,
            done=True,
            error=None,
            stats=stats,
        )
        logger.info(
            "Evolution generation done: session=%s features=%d stats=%s",
            session_id[:8],
            len(geojson.get("features", [])) if isinstance(geojson, dict) else 0,
            {k: stats.get(k) for k in ("n_total", "n_sig") if isinstance(stats, dict)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Evolution generation failed: session=%s", session_id[:8])
        _set_status(
            session_id,
            stage="error",
            done=True,
            error=str(exc) or exc.__class__.__name__,
        )


async def _generation_task(
    session_id: str,
    t1_bytes: bytes,
    t2_bytes: bytes,
    *,
    use_ban: bool,
    plancher_t1: float,
    include_new: bool,
) -> None:
    """Wrapper async : delegue le travail bloquant a un thread worker."""
    await asyncio.to_thread(
        _run_generation,
        session_id,
        t1_bytes,
        t2_bytes,
        use_ban=use_ban,
        plancher_t1=plancher_t1,
        include_new=include_new,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/upload", response_model=EvolutionUploadResponse)
async def upload_cartes(
    file_t1: UploadFile = File(..., description="Carte de debits annee 1 (T1) — GeoJSON"),
    file_t2: UploadFile = File(..., description="Carte de debits annee 2 (T2, base) — GeoJSON"),
    current_user: UserRecord = Depends(get_current_user),
) -> EvolutionUploadResponse:
    """Uploader les DEUX cartes de debits (T1 et T2=base) dans une session.

    Stocke les octets bruts GeoJSON dans la session ; la generation se lance
    ensuite via ``POST /api/evolution/generate``.
    """
    t1_bytes = await _read_geojson_upload(file_t1, "Carte T1")
    t2_bytes = await _read_geojson_upload(file_t2, "Carte T2")

    # Nouvelle session liee a l'utilisateur (isolation tenant — cf upload.py).
    session = session_manager.create_session(
        mode="evolution",
        owner_user_id=current_user.user_id,
    )
    session_manager.store_data(session.session_id, _KEY_T1, t1_bytes)
    session_manager.store_data(session.session_id, _KEY_T2, t2_bytes)

    # Active session pour /api/sessions/current (cf upload.py).
    try:
        session_manager.set_user_session(current_user.user_id, session.session_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to bind evolution session %s to user %s",
            session.session_id[:8],
            current_user.user_id[:8],
        )

    _init_status(session.session_id)

    logger.info(
        "Evolution upload OK: session=%s t1=%dB t2=%dB",
        session.session_id[:8],
        len(t1_bytes),
        len(t2_bytes),
    )
    return EvolutionUploadResponse(session_id=session.session_id)


@router.post("/generate", response_model=EvolutionGenerateResponse)
async def generate_evolution_route(
    body: EvolutionGenerateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> EvolutionGenerateResponse:
    """Lancer la generation de la carte d'evolution en tache de fond.

    Recharge les deux cartes depuis la session, demarre le map-matching + BAN
    dans un thread worker et retourne immediatement. Suivre l'avancement via
    ``GET /api/evolution/status/{session_id}``.
    """
    require_owned_session(body.session_id, current_user)

    try:
        t1_bytes = session_manager.get_data(body.session_id, _KEY_T1)
        t2_bytes = session_manager.get_data(body.session_id, _KEY_T2)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.") from None

    if not t1_bytes or not t2_bytes:
        raise HTTPException(
            status_code=400,
            detail="Cartes T1/T2 absentes de la session. Uploadez-les d'abord.",
        )

    # Le RedisBackend re-serialise les bytes en JSON (str) — on retombe sur des
    # bytes utf-8 si besoin pour que le service les charge correctement.
    if isinstance(t1_bytes, str):
        t1_bytes = t1_bytes.encode("utf-8")
    if isinstance(t2_bytes, str):
        t2_bytes = t2_bytes.encode("utf-8")

    # Reset du statut + persistance d'un marqueur "running" dans la session.
    _init_status(body.session_id)
    _set_status(body.session_id, stage="started", progress=0.0)
    try:
        session_manager.store_data(body.session_id, _KEY_STATUS, "running")
    except KeyError:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.") from None

    # Lancement non bloquant : la tache survit a la reponse HTTP.
    asyncio.create_task(
        _generation_task(
            body.session_id,
            t1_bytes,
            t2_bytes,
            use_ban=body.use_ban,
            plancher_t1=body.plancher_t1,
            include_new=body.include_new,
        )
    )

    logger.info(
        "Evolution generation started: session=%s use_ban=%s plancher=%.1f include_new=%s",
        body.session_id[:8],
        body.use_ban,
        body.plancher_t1,
        body.include_new,
    )
    return EvolutionGenerateResponse(session_id=body.session_id, started=True)


@router.get("/status/{session_id}", response_model=EvolutionStatusResponse)
async def evolution_status(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> EvolutionStatusResponse:
    """Etat d'avancement de la generation (stage / progress / done / error / stats)."""
    require_owned_session(session_id, current_user)

    st = _read_status(session_id)
    if st is None:
        # Pas de generation en cours dans ce process : peut-etre deja terminee
        # et persistee (rechargement / autre worker). On infere depuis la session.
        try:
            stats = session_manager.get_data(session_id, _KEY_STATS, None)
            result = session_manager.get_data(session_id, _KEY_RESULT, None)
        except KeyError:
            raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.") from None
        if result is not None:
            return EvolutionStatusResponse(
                stage="done",
                progress=100.0,
                done=True,
                error=None,
                stats=stats,
            )
        return EvolutionStatusResponse(
            stage="idle",
            progress=0.0,
            done=False,
            error=None,
            stats=None,
        )

    return EvolutionStatusResponse(
        stage=st.get("stage", "idle"),
        progress=float(st.get("progress", 0.0)),
        done=bool(st.get("done", False)),
        error=st.get("error"),
        stats=st.get("stats"),
    )


@router.get("/result/{session_id}")
async def evolution_result(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> JSONResponse:
    """Retourner le GeoJSON d'evolution (pour le viewer MapLibre)."""
    require_owned_session(session_id, current_user)

    try:
        geojson = session_manager.get_data(session_id, _KEY_RESULT, None)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.") from None

    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun resultat d'evolution. Lancez la generation et attendez sa fin.",
        )
    return JSONResponse(content=geojson)


@router.get("/download/{session_id}")
async def evolution_download(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Telecharger le GeoJSON d'evolution en piece jointe (application/geo+json)."""
    require_owned_session(session_id, current_user)

    try:
        geojson = session_manager.get_data(session_id, _KEY_RESULT, None)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.") from None

    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun resultat d'evolution. Lancez la generation et attendez sa fin.",
        )

    # allow_nan=False : garantit un GeoJSON strict (cf garde-fous du service —
    # jamais d'Infinity/NaN). Le service produit deja une data conforme.
    body = json.dumps(geojson, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return Response(
        content=body,
        media_type="application/geo+json",
        headers={
            "Content-Disposition": (f'attachment; filename="evolution_{session_id[:8]}.geojson"'),
        },
    )
