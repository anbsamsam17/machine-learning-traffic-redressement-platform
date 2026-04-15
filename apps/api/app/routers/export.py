"""Export router — download trained model, carte, and compteur results."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/model/{session_id}/{model_name}")
async def export_model(session_id: str, model_name: str) -> Response:
    """Export trained model as a ZIP archive (model.json + weights.h5 + norm_params.json)."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

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
    logger.info("Model exported: session=%s name=%s size=%d bytes", session_id, model_name, len(zip_bytes))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{model_name}.zip"'},
    )


@router.get("/carte/{session_id}")
async def export_carte(session_id: str) -> Response:
    """Export the generated carte de debits as GeoJSON."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

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
async def export_compteurs(session_id: str) -> Response:
    """Export the generated counting loops as GeoJSON."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

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
