"""Training router - grid search training, SSE streaming, cancellation.

Thin wrapper around services.ml.training_pipeline.run_training. Handles:
- SSE progress event registry (TrainingTask)
- Cancellation via threading.Event passed to the pipeline
- Persistence of model artefacts to disk via packaging helpers
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import get_settings
from ..session import session_manager
from ..services.ml.grid_search import (
    build_feature_sets,
    generate_all_combinations,
)
from ..services.ml.packaging import build_meta, data_sha256_of
from ..services.ml.progress import ProgressPayload
from ..services.ml.seeding import seed_everything
from ..services.ml.training_pipeline import (
    SEED,
    TrainedModelArtifact,
    run_training,
)
from ..services.ml.types import PL_CONFIG, TV_CONFIG, ModelTypeConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/training", tags=["training"])


class TrainingTask:
    """One in-flight or completed training run."""

    def __init__(self, task_id: str, session_id: str, config: dict[str, Any]) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self.config = config
        self.status: str = "pending"
        self.progress: list[dict[str, Any]] = []
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.started_at: float = time.time()
        self._cancel_event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def cancel(self) -> None:
        self._cancel_event.set()


_tasks: dict[str, TrainingTask] = {}
_tasks_lock = threading.Lock()


class TrainingConfig(BaseModel):
    session_id: str
    output_dir: str | None = None

    model_type: str = "TV"
    input_cols: list[str] = [
        "TMJAFCDTV", "TMJAFCDPL",
        "car_average_distance_km", "car_average_speed_kmh",
        "truck_min_average_distance_km", "truck_average_speed_kmh",
    ]
    output_cols: list[str] = ["TxPenTVRef"]
    on_off_norm: list[bool] = []
    activations: list[str] = ["elu"]
    learning_rates: list[float] = [0.01]
    losses: list[str] = ["mse"]
    min_nb_epochs_list: list[int] = [500, 1000]
    max_epochs: int = 2050
    test_size: float = 0.0
    neurons_factors_list: list[list[float]] = [[1.0, 1.0]]
    use_batch_norm: bool = False
    dropouts: list[float] = [0.05]
    batch_sizes: list[int] = [256]
    seed: int = SEED

    mandatory_input_cols: list[str] = []
    min_input_count: int = 0
    feature_subset_grid: bool = False
    use_flag_comptage_weighting: bool = True
    flag_priority_weight: float = 4.0

    class Config:
        extra = "allow"


class TrainingStartResponse(BaseModel):
    task_id: str
    session_id: str
    status: str
    total_combinations: int
    output_dir: str | None = None


class TrainingStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_pct: float
    current_epoch: int
    total_epochs: int
    current_model: int
    total_models: int
    current_model_name: str
    loss: float | None = None
    val_loss: float | None = None
    best_val_loss: float | None = None
    error: str | None = None


class TrainingCancelResponse(BaseModel):
    task_id: str
    status: str


_COL_RENAMES = {
    "TMJATV": "TMJAFCDTV",
    "TMJAPL": "TMJAFCDPL",
    "TxPen": "TxPenTVRef",
    "TxPenPL": "TxPenPLRef",
}


def _type_config_for(model_type: str) -> ModelTypeConfig:
    if model_type and model_type.upper() == "PL":
        return PL_CONFIG
    return TV_CONFIG


def _count_combinations(cfg: dict[str, Any]) -> int:
    """Compute the number of grid combinations without running anything."""
    input_cols = list(cfg.get("input_cols", []))
    mandatory = list(cfg.get("mandatory_input_cols", []))
    min_input = int(cfg.get("min_input_count", 0))
    feature_subset_grid = bool(cfg.get("feature_subset_grid", False))

    try:
        feature_sets = build_feature_sets(
            all_input_cols=input_cols,
            mandatory_cols=mandatory,
            min_input_count=min_input,
            enable_feature_subset_grid=feature_subset_grid,
        )
    except ValueError:
        return 0

    combos = generate_all_combinations(
        feature_sets=feature_sets,
        all_input_cols=input_cols,
        activations=list(cfg.get("activations", ["elu"])),
        learning_rates=[float(v) for v in cfg.get("learning_rates", [0.01])],
        min_nb_epochs_list=[int(v) for v in cfg.get("min_nb_epochs_list", [500])],
        losses=list(cfg.get("losses", ["mse"])),
        dropouts=[float(v) for v in cfg.get("dropouts", [0.05])],
        neurons_factors_list=list(cfg.get("neurons_factors_list", [[1.0, 1.0]])),
        batch_sizes=[int(v) for v in cfg.get("batch_sizes", [256])],
    )
    return len(combos)


def _make_progress_callback(task: TrainingTask, max_epochs: int):
    """Forward run_training ProgressPayload events into task.progress."""
    last_model_idx: dict[str, int | None] = {"idx": None}

    def _push(p: ProgressPayload) -> None:
        if last_model_idx["idx"] != p.model_idx:
            last_model_idx["idx"] = p.model_idx
            task.progress.append({
                "type": "model_start",
                "model_index": p.model_idx - 1,
                "total_models": p.total_models,
                "model_name": p.run_name,
            })

        task.progress.append({
            "type": "epoch",
            "model_index": p.model_idx - 1,
            "total_models": p.total_models,
            "model_name": p.run_name,
            "epoch": p.epoch,
            "total_epochs": max_epochs,
            "loss": p.loss,
            "val_loss": p.val_loss if p.val_loss is not None else p.loss,
            "elapsed": time.time() - task.started_at,
        })

    return _push


def _serialise_artifact_to_disk(
    artifact: TrainedModelArtifact,
    out_root: Path,
    *,
    seed: int,
    data_sha256: str,
) -> Path:
    """Write a TrainedModelArtifact under out_root/run_name/ in both
    native .keras and legacy h5+json layouts (+ meta.json)."""
    model_dir = out_root / artifact.run_name
    model_dir.mkdir(parents=True, exist_ok=True)

    try:
        artifact.model.save(str(model_dir / "model.keras"))
    except Exception as save_exc:  # noqa: BLE001
        logger.warning(
            "model.save(.keras) failed for %s (%s) - legacy h5 only",
            artifact.run_name, save_exc,
        )
    (model_dir / "NNarchitecture.json").write_text(
        artifact.model.to_json(), encoding="utf-8",
    )
    artifact.model.save_weights(str(model_dir / "NNweights.weights.h5"))

    coeffs = {
        "muX": [artifact.mu_x.tolist()],
        "SX": [artifact.sigma_x.tolist()],
        "muY": [artifact.mu_y.tolist()],
        "SY": [artifact.sigma_y.tolist()],
    }
    (model_dir / "NNnormCoefficients.json").write_text(
        json.dumps(coeffs, indent=2), encoding="utf-8",
    )
    (model_dir / "training_config.json").write_text(
        json.dumps(artifact.training_config, indent=2), encoding="utf-8",
    )
    (model_dir / "training_metrics.json").write_text(
        json.dumps(artifact.training_metrics, indent=2), encoding="utf-8",
    )

    try:
        meta = build_meta(
            seed=seed,
            data_sha256=data_sha256,
            extra={"format": "keras-native+legacy-h5"},
        )
        (model_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8",
        )
    except Exception as meta_exc:  # noqa: BLE001
        logger.warning("meta.json write failed for %s: %s", artifact.run_name, meta_exc)

    return model_dir


def _training_worker(task: TrainingTask) -> None:
    """Run grid search via services.ml.training_pipeline.run_training.

    The legacy 440-line inline implementation has been removed; the
    worker delegates the actual training loop to the shared service.
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
    os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_enable_xla_devices=false")

    try:
        task.status = "running"
        cfg = task.config

        session = session_manager.get_session(task.session_id)
        if session is None:
            raise RuntimeError("Session expiree.")
        learning_df = session.data.get("learning_df")
        if learning_df is None:
            raise RuntimeError("Pas de DataFrame d apprentissage dans la session.")

        df = learning_df.copy()
        for old_name, new_name in _COL_RENAMES.items():
            if old_name in df.columns and new_name not in df.columns:
                df[new_name] = df[old_name]

        type_config = _type_config_for(cfg.get("model_type", "TV"))
        max_epochs = int(cfg.get("max_epochs", 2050))
        output_dir = cfg.get("output_dir")
        seed = int(cfg.get("seed", SEED))

        seed_everything(seed)

        try:
            data_sha = data_sha256_of(df)
        except Exception:  # noqa: BLE001
            data_sha = ""

        settings = get_settings()
        cfg = {**cfg, "_max_grid_combinations": settings.MAX_GRID_COMBINATIONS}

        total_combinations = _count_combinations(cfg)
        task.progress.append({
            "type": "info",
            "message": f"Demarrage du grid search : {total_combinations} combinaisons",
            "total_models": total_combinations,
        })

        if total_combinations == 0:
            task.result = {
                "total_models": 0,
                "skipped": 0,
                "best_model": "",
                "best_val_loss": None,
                "output_dir": output_dir,
                "results": [],
            }
            task.status = "completed"
            return

        progress_cb = _make_progress_callback(task, max_epochs)
        results = run_training(
            df=df,
            config=cfg,
            type_config=type_config,
            progress_callback=progress_cb,
            cancel_event=task.cancel_event,
        )

        if task.cancelled:
            task.status = "cancelled"
            return

        results_list: list[dict[str, Any]] = []
        best_val_loss = float("inf")
        best_name = ""

        out_path = Path(output_dir) if output_dir else None
        if out_path is not None:
            out_path.mkdir(parents=True, exist_ok=True)
            logger.info("Output directory verified: %s", out_path.resolve())
        else:
            logger.warning("No output_dir specified - models will NOT be saved to disk!")

        for run_name, artifact in results.items():
            metrics = artifact.training_metrics or {}
            val_loss = float(metrics.get("loss", metrics.get("val_loss", float("nan"))))
            epochs_trained = int(artifact.training_config.get("epochs_trained", 0))

            results_list.append({
                "run_name": run_name,
                "val_loss": val_loss,
                "epochs_trained": epochs_trained,
                **artifact.training_config,
            })

            if val_loss == val_loss and val_loss < best_val_loss:
                best_val_loss = val_loss
                best_name = run_name

            if out_path is not None:
                artifact.training_config["seed"] = seed
                artifact.training_config["data_sha256"] = data_sha
                _serialise_artifact_to_disk(
                    artifact, out_path, seed=seed, data_sha256=data_sha,
                )

            task.progress.append({
                "type": "model_end",
                "model_index": len(results_list) - 1,
                "model_name": run_name,
                "val_loss": val_loss,
                "epochs_trained": epochs_trained,
                "best_val_loss": best_val_loss if best_val_loss != float("inf") else None,
                "best_model_name": best_name,
            })

        task.result = {
            "total_models": len(results_list),
            "skipped": max(0, total_combinations - len(results_list)),
            "best_model": best_name,
            "best_val_loss": best_val_loss if best_val_loss != float("inf") else None,
            "output_dir": output_dir,
            "results": results_list,
        }
        task.status = "completed"
        logger.info(
            "Grid search completed: %d models trained, best=%s",
            len(results_list), best_name,
        )

    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.error = str(exc)
        logger.exception("Training failed: task=%s", task.task_id)


@router.post("/start", response_model=TrainingStartResponse)
async def start_training(body: TrainingConfig) -> TrainingStartResponse:
    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")
    if session.data.get("learning_df") is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pas de DataFrame d apprentissage dans cette session. "
                "Retournez a l etape Donnees, importez un fichier et validez le mapping."
            ),
        )

    config_dict = body.model_dump()
    settings = get_settings()

    user_label = config_dict.get("output_dir") or ""
    server_output = str(Path(settings.WORKSPACE_ROOT) / body.session_id / "models")
    config_dict["output_dir"] = server_output
    config_dict["output_label"] = user_label
    logger.info(
        "Training output - user label=%r, server path=%s",
        user_label, server_output,
    )
    session_manager.store_data(body.session_id, "output_dir", server_output)
    session_manager.store_data(body.session_id, "output_label", user_label)

    total = _count_combinations(config_dict)
    if total > settings.MAX_GRID_COMBINATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Grid search demanderait {total} combinaisons, "
                f"limite serveur MAX_GRID_COMBINATIONS={settings.MAX_GRID_COMBINATIONS}. "
                "Reduisez les axes ou desactivez feature_subset_grid."
            ),
        )

    task_id = uuid.uuid4().hex[:12]
    task = TrainingTask(
        task_id=task_id,
        session_id=body.session_id,
        config=config_dict,
    )

    with _tasks_lock:
        _tasks[task_id] = task

    thread = threading.Thread(target=_training_worker, args=(task,), daemon=True)
    thread.start()

    logger.info(
        "Grid search started: task=%s session=%s combos=%d output_dir=%s max_epochs=%d",
        task_id, body.session_id, total, server_output, body.max_epochs,
    )

    return TrainingStartResponse(
        task_id=task_id,
        session_id=body.session_id,
        status="pending",
        total_combinations=total,
        output_dir=server_output,
    )


@router.get("/stream/{task_id}")
async def stream_training(task_id: str) -> StreamingResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    async def event_generator():
        last_idx = 0
        while True:
            current_progress = task.progress[last_idx:]
            for entry in current_progress:
                yield f"data: {json.dumps(entry)}\n\n"
                last_idx += 1

            if task.status in ("completed", "failed", "cancelled"):
                final = {
                    "type": "complete",
                    "status": task.status,
                    "result": task.result,
                    "error": task.error,
                }
                yield f"data: {json.dumps(final)}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{task_id}", response_model=TrainingStatusResponse)
async def training_status(task_id: str) -> TrainingStatusResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")

    last_epoch: dict[str, Any] = {}
    last_model_end: dict[str, Any] = {}
    current_model = 0
    total_models = 1
    model_name = ""

    for entry in reversed(task.progress):
        if entry.get("type") == "epoch" and not last_epoch:
            last_epoch = entry
        if entry.get("type") == "model_end" and not last_model_end:
            last_model_end = entry
        if entry.get("type") in ("model_start", "epoch") and not model_name:
            current_model = entry.get("model_index", 0)
            total_models = entry.get("total_models", 1)
            model_name = entry.get("model_name", "")
        if entry.get("type") == "info" and total_models <= 1 and "total_models" in entry:
            total_models = entry["total_models"]
        if last_epoch and last_model_end and model_name:
            break

    return TrainingStatusResponse(
        task_id=task_id,
        status=task.status,
        progress_pct=round(
            ((current_model + (last_epoch.get("epoch", 0) / max(last_epoch.get("total_epochs", 1), 1)))
             / max(total_models, 1)) * 100, 1,
        ),
        current_epoch=last_epoch.get("epoch", 0),
        total_epochs=last_epoch.get("total_epochs", 0),
        current_model=current_model,
        total_models=total_models,
        current_model_name=model_name,
        loss=last_epoch.get("loss"),
        val_loss=last_epoch.get("val_loss"),
        best_val_loss=last_model_end.get("best_val_loss"),
        error=task.error,
    )


@router.post("/cancel/{task_id}", response_model=TrainingCancelResponse)
async def cancel_training(task_id: str) -> TrainingCancelResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task non trouvee.")
    task.cancel()
    return TrainingCancelResponse(task_id=task_id, status="cancelling")
