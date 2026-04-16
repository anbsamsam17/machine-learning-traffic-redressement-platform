"""Models router — list available trained models in a directory."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query

from pydantic import BaseModel

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


@router.get("/list", response_model=ModelsListResponse)
async def list_models(dir: str = Query(..., description="Dossier contenant les modeles entraines")) -> ModelsListResponse:
    """List all model sub-directories that contain NNarchitecture.json."""
    # Validate the directory is within the allowed workspace
    validate_path(dir)
    base = Path(dir)
    if not base.exists() or not base.is_dir():
        return ModelsListResponse(models=[])

    models: list[ModelInfo] = []

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

    logger.info("Listed %d models in %s", len(models), dir)
    return ModelsListResponse(models=models)
