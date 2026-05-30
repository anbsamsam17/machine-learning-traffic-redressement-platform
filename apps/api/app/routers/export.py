"""Export router — download trained model, carte, and compteur results."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _resolve_export_kind(session, model_name: str) -> str:
    """Best-effort resolution of the model kind for the export filename.

    Reads, in priority :
    1. ``model_kind`` echoed inside the session's ``norm_params`` /
       ``training_result`` payloads.
    2. ``model_name`` prefix (``model_HPM_*`` / ``model_HPS_*`` / ``model_PL_*``).
    3. Default ``"TV"``.
    """
    for key in ("model_kind", "training_config"):
        val = session.data.get(key)
        if isinstance(val, dict):
            k = str(val.get("model_kind") or "").upper()
            if k in {"TV", "PL", "HPM", "HPS"}:
                return k
        if isinstance(val, str) and val.upper() in {"TV", "PL", "HPM", "HPS"}:
            return val.upper()
    fn_up = (model_name or "").upper()
    for k in ("HPM", "HPS", "PL", "TV"):
        if fn_up.startswith(f"MODEL_{k}_"):
            return k
    return "TV"


@router.get("/model/{session_id}/{model_name}")
async def export_model(
    session_id: str,
    model_name: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Export trained model as a ZIP archive (model.json + weights.h5 + norm_params.json).

    Le nom du ZIP inclut le kind ("model_TV_xxx.zip", "model_HPM_xxx.zip", ...).
    """
    session = require_owned_session(session_id, current_user)

    model_json_str = session.data.get("trained_model_json")
    weights_bytes = session.data.get("trained_weights")
    norm_params = session.data.get("norm_params")

    if not all([model_json_str, weights_bytes, norm_params]):
        raise HTTPException(
            status_code=400,
            detail="Aucun modele entraine a exporter dans cette session.",
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{model_name}/model.json", model_json_str)
        zf.writestr(f"{model_name}/weights.h5", weights_bytes)
        zf.writestr(
            f"{model_name}/norm_params.json",
            json.dumps(norm_params, ensure_ascii=False, indent=2),
        )
        # Include training metrics if available
        training_result = session.data.get("training_result")
        if training_result:
            zf.writestr(
                f"{model_name}/training_result.json",
                json.dumps(training_result, ensure_ascii=False, indent=2),
            )
        eval_metrics = session.data.get("eval_metrics")
        if eval_metrics:
            zf.writestr(
                f"{model_name}/eval_metrics.json",
                json.dumps(eval_metrics, ensure_ascii=False, indent=2),
            )

    zip_bytes = buf.getvalue()
    # Inject le kind dans le nom du ZIP exporte (HPM / HPS / PL / TV).
    kind = _resolve_export_kind(session, model_name)
    fn_up = (model_name or "").upper()
    already_prefixed = any(
        fn_up.startswith(f"MODEL_{k}_") for k in ("TV", "PL", "HPM", "HPS")
    )
    export_basename = model_name if already_prefixed else f"model_{kind}_{model_name}"
    logger.info(
        "Model exported: session=%s name=%s kind=%s size=%d bytes",
        session_id, model_name, kind, len(zip_bytes),
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{export_basename}.zip"'},
    )


@router.get("/models-all/{session_id}")
async def export_all_models(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Zip every trained model directory for this session and return it."""
    session = require_owned_session(session_id, current_user)

    output_dir = session.data.get("output_dir")
    if not output_dir:
        raise HTTPException(
            status_code=400,
            detail="Aucun entrainement effectue dans cette session.",
        )

    out_path = Path(output_dir)
    if not out_path.exists() or not out_path.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Dossier de sortie introuvable cote serveur: {out_path}",
        )

    buf = io.BytesIO()
    file_count = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in out_path.rglob("*"):
            if p.is_file():
                zf.write(p, arcname=p.relative_to(out_path))
                file_count += 1

    if file_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Aucun fichier de modele a exporter.",
        )

    zip_bytes = buf.getvalue()
    label = session.data.get("output_label") or session.data.get("territory") or "models"
    # sanitize for filename
    label = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(label))[:60] or "models"
    logger.info(
        "Bulk models export: session=%s files=%d size=%d bytes label=%s",
        session_id, file_count, len(zip_bytes), label,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{label}_models.zip"'},
    )


@router.get("/carte/{session_id}")
async def export_carte(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Export the generated carte de debits as GeoJSON."""
    session = require_owned_session(session_id, current_user)

    carte_geojson = session.data.get("carte_geojson")
    if carte_geojson is None:
        raise HTTPException(
            status_code=400,
            detail="Aucune carte generee. Lancez /api/carte/generate d'abord.",
        )

    content = json.dumps(carte_geojson, ensure_ascii=False, indent=2)
    territory = session.data.get("territory", "export")

    return Response(
        content=content.encode("utf-8"),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="carte_debits_{territory}.geojson"',
        },
    )


@router.get("/compteurs/{session_id}")
async def export_compteurs(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
) -> Response:
    """Export the generated counting loops as GeoJSON."""
    session = require_owned_session(session_id, current_user)

    compteurs_geojson = session.data.get("compteurs_geojson")
    if compteurs_geojson is None:
        raise HTTPException(
            status_code=400,
            detail="Aucun compteur genere. Lancez /api/compteurs/generate d'abord.",
        )

    content = json.dumps(compteurs_geojson, ensure_ascii=False, indent=2)
    territory = session.data.get("territory", "export")

    return Response(
        content=content.encode("utf-8"),
        media_type="application/geo+json",
        headers={
            "Content-Disposition": f'attachment; filename="compteurs_{territory}.geojson"',
        },
    )
