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

def _is_model_dir(p: Path) -> bool:
    """Return True if ``p`` looks like a serialised model directory.

    Accepts either the modern ``model.keras`` archive or the legacy
    ``NNarchitecture.json`` + ``NNweights*.h5`` layout.
    """
    if not p.is_dir():
        return False
    if (p / "model.keras").exists():
        return True
    if (p / "NNarchitecture.json").exists():
        if (p / "NNweights.weights.h5").exists() or (p / "NNweights.h5").exists():
            return True
    return False


def _make_model_info(p: Path) -> ModelInfo:
    has_keras = (p / "model.keras").exists()
    has_arch = (p / "NNarchitecture.json").exists()
    weights_h5 = (p / "NNweights.weights.h5").exists() or (p / "NNweights.h5").exists()
    norm_file = (p / "NNnormCoefficients.json").exists()

    training_config = None
    config_file = p / "training_config.json"
    if config_file.exists():
        try:
            training_config = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return ModelInfo(
        name=p.name,
        path=str(p),
        # model.keras embeds weights; treat presence as "has_weights"
        has_weights=weights_h5 or has_keras,
        has_architecture=has_arch or has_keras,
        has_norm=norm_file,
        training_config=training_config,
    )


def _scan_models_in_dir(base: Path, max_depth: int = 6) -> list[ModelInfo]:
    """Recursively scan ``base`` for model sub-folders.

    A folder counts as a model if it contains ``model.keras`` OR the pair
    ``NNarchitecture.json`` + ``NNweights*.h5``. Recursion stops at any folder
    matched as a model (it does not look inside model folders themselves).
    """
    if not base.exists() or not base.is_dir():
        return []

    models: list[ModelInfo] = []
    seen: set[str] = set()

    # Base itself may be a model dir (e.g. flat ZIP upload)
    if _is_model_dir(base):
        info = _make_model_info(base)
        seen.add(info.path)
        models.append(info)
        return models

    def _walk(p: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(p.iterdir())
        except (PermissionError, OSError):
            return
        for sub in entries:
            if not sub.is_dir():
                continue
            # Skip noise/system folders
            if sub.name.startswith(".") or sub.name in {"__MACOSX", "__pycache__"}:
                continue
            if _is_model_dir(sub):
                info = _make_model_info(sub)
                if info.path not in seen:
                    seen.add(info.path)
                    models.append(info)
                # Don't recurse into a model folder
                continue
            _walk(sub, depth + 1)

    _walk(base, 0)
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
    root: str = Query(None, description="Racine du scan recursif (chemin absolu)"),
    dir: str = Query(None, description="Alias historique pour 'root'"),
    session_id: str = Query(None, description="Session ID — cherche dans le workspace serveur"),
) -> ModelsListResponse:
    """List all model sub-directories under a root, recursively.

    A folder is a model if it contains ``model.keras`` OR the legacy pair
    ``NNarchitecture.json`` + ``NNweights*.h5``.

    Resolution order:
    1. ``root`` (preferred) or ``dir`` (legacy alias) — explicit absolute path
    2. ``session_id`` — uses ``WORKSPACE_ROOT/{session_id}/models/``
    """
    scan_root = root or dir
    if scan_root:
        validate_path(scan_root)
        base = Path(scan_root)
    elif session_id:
        base = _get_session_models_dir(session_id)
    else:
        raise HTTPException(
            status_code=400, detail="Fournissez 'root' (ou 'dir') ou 'session_id'."
        )

    models = _scan_models_in_dir(base)
    logger.info("Listed %d models under %s", len(models), base)
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


@router.post("/upload-folder", response_model=ModelUploadResponse)
async def upload_models_folder(
    files: list[UploadFile] = File(..., description="Fichiers du dossier de modeles (via webkitdirectory)"),
    session_id: str = Form(..., description="Session ID"),
) -> ModelUploadResponse:
    """Upload multiple files from a folder selection (webkitdirectory).

    Each file's ``filename`` field contains its relative path within the selected
    folder (e.g. ``elu_lr0.01_ep500/NNarchitecture.json``).  The endpoint
    reconstructs the directory tree under WORKSPACE_ROOT/{session_id}/models/
    and returns the list of valid models found.
    """
    dest_dir = _get_session_models_dir(session_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for upload_file in files:
        if not upload_file.filename:
            continue
        # The filename comes as relative path, e.g. "MyModels/sub/NNarchitecture.json"
        # Normalise separators and strip leading slashes
        rel = upload_file.filename.replace("\\", "/").lstrip("/")

        # Security: reject path traversal
        if ".." in rel:
            raise HTTPException(
                status_code=400,
                detail=f"Chemin invalide dans les fichiers: {rel}",
            )

        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        contents = await upload_file.read()
        target.write_bytes(contents)

    logger.info("Folder upload: wrote %d files to %s", len(files), dest_dir)

    # Remove macOS artefacts
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Scan for models
    models = _scan_models_in_dir(dest_dir)

    # If no models at top level, check one level deeper (folder may have a wrapper)
    if not models:
        for child in dest_dir.iterdir():
            if child.is_dir():
                deeper = _scan_models_in_dir(child)
                if deeper:
                    models.extend(deeper)

    # If still nothing, check two levels deep
    if not models:
        for child in dest_dir.iterdir():
            if child.is_dir():
                for grandchild in child.iterdir():
                    if grandchild.is_dir():
                        deeper = _scan_models_in_dir(grandchild)
                        if deeper:
                            models.extend(deeper)

    if not models:
        logger.warning("No valid models found in uploaded folder at %s", dest_dir)

    logger.info("Folder upload complete: %d model(s) found for session %s", len(models), session_id)

    return ModelUploadResponse(
        session_id=session_id,
        models=models,
        extract_dir=str(dest_dir),
    )
