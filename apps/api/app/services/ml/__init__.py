"""Unified ML pipeline for TV/PL model training and evaluation.

Public API
----------
Types & configs:
    ModelTypeConfig, TV_CONFIG, PL_CONFIG

Normalisation:
    normalize, denormalize, simple_norm

Model building:
    build_model

Data preparation:
    prepare_training_data, split_train_valid

Grid search:
    build_feature_sets, feature_mask_name,
    generate_all_combinations, GridCombination

Training:
    run_training, TrainedModelArtifact

Evaluation:
    run_evaluation, apply_model, add_tolerance_columns,
    compute_flow_metrics, compute_tolerance_counts, choose_best_model

Packaging:
    export_model_zip, import_model_zip

Progress:
    TrainingProgressCallback, ProgressPayload

Note: TensorFlow-dependent modules (model_builder, training_pipeline,
packaging, progress, evaluation_pipeline.apply_model) are imported lazily
so the non-TF parts can be used without TF installed.
"""

from __future__ import annotations

# --- Always available (no TF dependency) ---
from .types import ModelTypeConfig, TV_CONFIG, PL_CONFIG

from .normalize import normalize, denormalize, simple_norm

from .data_prep import prepare_training_data, split_train_valid

from .grid_search import (
    build_feature_sets,
    feature_mask_name,
    generate_all_combinations,
    GridCombination,
)

# --- Lazy imports for TF-dependent modules ---

def __getattr__(name: str):
    """Lazy-load TensorFlow-dependent symbols on first access."""
    _tf_symbols = {
        # model_builder
        "build_model": (".model_builder", "build_model"),
        # training_pipeline
        "run_training": (".training_pipeline", "run_training"),
        "TrainedModelArtifact": (".training_pipeline", "TrainedModelArtifact"),
        # evaluation_pipeline
        "run_evaluation": (".evaluation_pipeline", "run_evaluation"),
        "apply_model": (".evaluation_pipeline", "apply_model"),
        "add_tolerance_columns": (".evaluation_pipeline", "add_tolerance_columns"),
        "compute_flow_metrics": (".evaluation_pipeline", "compute_flow_metrics"),
        "compute_tolerance_counts": (".evaluation_pipeline", "compute_tolerance_counts"),
        "choose_best_model": (".evaluation_pipeline", "choose_best_model"),
        # packaging
        "export_model_zip": (".packaging", "export_model_zip"),
        "import_model_zip": (".packaging", "import_model_zip"),
        # progress
        "TrainingProgressCallback": (".progress", "TrainingProgressCallback"),
        "ProgressPayload": (".progress", "ProgressPayload"),
    }

    if name in _tf_symbols:
        module_path, attr = _tf_symbols[name]
        import importlib
        mod = importlib.import_module(module_path, __package__)
        return getattr(mod, attr)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Types
    "ModelTypeConfig",
    "TV_CONFIG",
    "PL_CONFIG",
    # Normalize
    "normalize",
    "denormalize",
    "simple_norm",
    # Data
    "prepare_training_data",
    "split_train_valid",
    # Grid search
    "build_feature_sets",
    "feature_mask_name",
    "generate_all_combinations",
    "GridCombination",
    # Training (lazy)
    "run_training",
    "TrainedModelArtifact",
    # Model (lazy)
    "build_model",
    # Evaluation (lazy)
    "run_evaluation",
    "apply_model",
    "add_tolerance_columns",
    "compute_flow_metrics",
    "compute_tolerance_counts",
    "choose_best_model",
    # Packaging (lazy)
    "export_model_zip",
    "import_model_zip",
    # Progress (lazy)
    "TrainingProgressCallback",
    "ProgressPayload",
]
