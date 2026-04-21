"""Models router — list available trained models in a directory, upload model ZIPs."""

from __future__ import annotations

import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form

from pydantic import BaseModel

from ..config import get_settings
from ..security import validate_path

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/models", tags=["models"])


class ModelInfo(BaseModel):
    name: str
    path: str
    has_weights: bool
    has_architecture: bool
    has_norm: bool
    training_config: dict[str, Any] | None = None


class ModelsListResponse(BaseModel):
    models: list[ModelInfo]


class ModelUploadResponse(BaseModel):
    session_id: str
    models: list[ModelInfo]
    extract_dir: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scan_models_in_dir(base: Path) -> list[ModelInfo]:
    """Scan a directory for model sub-folders containing NNarchitecture.json."""
    if not base.exists() or not base.is_dir():
        return []

    models: list[ModelInfo] = []

    # Check if base itself is a model directory (flat zip)
    if (base / "NNarchitecture.json").exists():
        weights_h5 = (base / "NNweights.weights.h5").exists() or (base / "NNweights.h5").exists()
        norm_file = (base / "NNnormCoefficients.json").exists()
        training_config = None
        config_file = base / "training_config.json"
        if config_file.exists():
            try:
                training_config = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        models.append(ModelInfo(
            name=base.name,
            path=str(base),
            has_weights=weights_h5,
            has_architecture=True,
            has_norm=norm_file,
            training_config=training_config,
        ))
        return models

    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue

        arch_file = sub / "NNarchitecture.json"
        if not arch_file.exists():
            continue

        weights_h5 = (sub / "NNweights.weights.h5").exists() or (sub / "NNweights.h5").exists()
        norm_file = (sub / "NNnormCoefficients.json").exists()

        # Load training config if available
        training_config = None
        config_file = sub / "training_config.json"
        if config_file.exists():
            try:
                training_config = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        models.append(ModelInfo(
            name=sub.name,
            path=str(sub),
            has_weights=weights_h5,
            has_architecture=True,
            has_norm=norm_file,
            training_config=training_config,
        ))

    return models


def _get_session_models_dir(session_id: str) -> Path:
    """Return the models directory for a session inside WORKSPACE_ROOT."""
    settings = get_settings()
    return Path(settings.WORKSPACE_ROOT) / session_id / "models"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/list", response_model=ModelsListResponse)
async def list_models(
    dir: str = Query(None, description="Dossier contenant les modeles entraines"),
    session_id: str = Query(None, description="Session ID — cherche dans le workspace serveur"),
) -> ModelsListResponse:
    """List all model sub-directories that contain NNarchitecture.json.

    Accepts either ``dir`` (explicit path) or ``session_id`` (uses WORKSPACE_ROOT/{session_id}/models/).
    """
    if session_id:
        base = _get_session_models_dir(session_id)
    elif dir:
        validate_path(dir)
        base = Path(dir)
    else:
        raise HTTPException(status_code=400, detail="Fournissez 'dir' ou 'session_id'.")

    models = _scan_models_in_dir(base)
    logger.info("Listed %d models in %s", len(models), base)
    return ModelsListResponse(models=models)


@router.post("/upload", response_model=ModelUploadResponse)
async def upload_models_zip(
    file: UploadFile = File(..., description="Fichier ZIP contenant un ou plusieurs dossiers de modeles"),
    session_id: str = Form(..., description="Session ID"),
) -> ModelUploadResponse:
    """Upload a ZIP file containing one or more model directories.

    Each model directory must contain at minimum NNarchitecture.json and
    NNweights.weights.h5 (or NNweights.h5).

    The ZIP is extracted into WORKSPACE_ROOT/{session_id}/models/.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Le fichier doit etre un .zip")

    dest_dir = _get_session_models_dir(session_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Read uploaded file into memory and validate it is a valid zip
    contents = await file.read()
    import io
    buf = io.BytesIO(contents)
    if not zipfile.is_zipfile(buf):
        raise HTTPException(status_code=400, detail="Le fichier n'est pas un ZIP valide.")

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        # Security: reject paths with .. or absolute paths
        for name in zf.namelist():
            if ".." in name or name.startswith("/") or name.startswith("\\"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Le ZIP contient un chemin invalide: {name}",
                )
        zf.extractall(dest_dir)

    logger.info("Extracted model ZIP to %s", dest_dir)

    # Handle __MACOSX and nested single-folder case
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Scan for models
    models = _scan_models_in_dir(dest_dir)

    # If no models found at top level, check one level deeper (zip may have a wrapper folder)
    if not models:
        for child in dest_dir.iterdir():
            if child.is_dir():
                deeper = _scan_models_in_dir(child)
                if deeper:
                    models.extend(deeper)

    if not models:
        logger.warning("No valid models found in uploaded ZIP at %s", dest_dir)

    logger.info("Upload complete: %d model(s) found for session %s", len(models), session_id)

    return ModelUploadResponse(
        session_id=session_id,
        models=models,
        extract_dir=str(dest_dir),
    )
