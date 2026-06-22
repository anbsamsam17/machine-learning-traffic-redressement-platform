"""Model packaging: export/import as ZIP archives, native .keras saves,
and run metadata (env versions + git SHA + seed + data hash).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import platform
import socket
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from .training_pipeline import TrainedModelArtifact

logger = logging.getLogger(__name__)


class ImportedModel(TypedDict):
    """Structured result of :func:`import_model_zip` (a deserialised model bundle)."""

    model: Any
    mu_x: np.ndarray
    sigma_x: np.ndarray
    mu_y: np.ndarray
    sigma_y: np.ndarray
    input_cols: list
    output_cols: list
    training_config: dict
    training_metrics: dict


def build_meta(
    *,
    seed: int | None = None,
    data_sha256: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Build run metadata: timestamp, env/library versions, host, seed, git SHA.

    Each optional dependency (TensorFlow, Keras, scikit-learn) and the git
    lookup is probed defensively; failures are recorded in the metadata (or
    skipped) rather than raised, so packaging never fails on a missing tool.
    """
    meta = {
        "saved_at": datetime.now(UTC).isoformat() + "Z",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "seed": seed,
        "data_sha256": data_sha256,
    }
    try:
        import tensorflow as _tf

        meta["tf_version"] = _tf.__version__
    except Exception as exc:  # noqa: BLE001
        meta["tf_version_error"] = str(exc)
    try:
        import keras as _k

        meta["keras_version"] = _k.__version__
    except Exception as exc:  # noqa: BLE001
        meta["keras_version_error"] = str(exc)
    try:
        meta["numpy_version"] = np.__version__
    except Exception as exc:  # noqa: BLE001
        logger.debug("build_meta: numpy version unavailable: %s", exc)
    try:
        import sklearn as _sk

        meta["sklearn_version"] = _sk.__version__
    except Exception as exc:  # noqa: BLE001
        logger.debug("build_meta: sklearn version unavailable: %s", exc)
    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parent,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            .decode()
            .strip()
        )
        meta["git_sha"] = sha
    except Exception as exc:  # noqa: BLE001
        logger.debug("build_meta: git SHA unavailable: %s", exc)
        meta["git_sha"] = None
    if extra:
        meta.update(extra)
    return meta


def data_sha256_of(df: pd.DataFrame) -> str:
    """Return a stable SHA-256 of *df* content, falling back to its shape on error."""
    try:
        return hashlib.sha256(
            pd.util.hash_pandas_object(df, index=True).values.tobytes()
        ).hexdigest()
    except Exception as exc:  # noqa: BLE001
        logger.debug("data_sha256_of: content hash failed, using shape: %s", exc)
        return hashlib.sha256(repr(df.shape).encode()).hexdigest()


def save_model_native(model: Any, target_dir: Path | str) -> Path:
    """Save *model* natively as ``model.keras`` under *target_dir*; return its path."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "model.keras"
    model.save(out)
    return out


def load_model_compat(model_dir: Path | str) -> Any:
    """Load a model from *model_dir*, preferring native ``.keras`` over legacy JSON+H5.

    Raises ``FileNotFoundError`` when neither a native model nor an
    architecture/weights pair can be found.
    """
    from tensorflow.keras.models import load_model, model_from_json

    model_dir = Path(model_dir)
    native = model_dir / "model.keras"
    if native.exists():
        return load_model(native, compile=False)

    arch = model_dir / "NNarchitecture.json"
    if not arch.exists():
        raise FileNotFoundError(f"Neither model.keras nor NNarchitecture.json found in {model_dir}")
    model = model_from_json(arch.read_text(encoding="utf-8"))
    weights = model_dir / "NNweights.weights.h5"
    if not weights.exists():
        weights = model_dir / "NNweights.h5"
    if not weights.exists():
        raise FileNotFoundError(
            f"No weights file (NNweights.weights.h5 / NNweights.h5) in {model_dir}"
        )
    model.load_weights(str(weights))
    return model


def export_model_zip(artifact: TrainedModelArtifact) -> bytes:
    """Serialise *artifact* into a legacy-H5 ZIP archive and return its raw bytes.

    The archive bundles the architecture JSON, H5 weights, normalisation
    coefficients, training config/metrics and run metadata.
    """
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        arch_json = artifact.model.to_json()
        zf.writestr("NNarchitecture.json", arch_json)

        import os
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            artifact.model.save_weights(tmp_path)
            with open(tmp_path, "rb") as f:
                weights_bytes = f.read()
            zf.writestr("NNweights.h5", weights_bytes)
        finally:
            os.unlink(tmp_path)

        coeffs = {
            "muX": [artifact.mu_x.tolist()],
            "SX": [artifact.sigma_x.tolist()],
            "muY": [artifact.mu_y.tolist()],
            "SY": [artifact.sigma_y.tolist()],
        }
        zf.writestr("NNnormCoefficients.json", json.dumps(coeffs, indent=2))
        zf.writestr("training_config.json", json.dumps(artifact.training_config, indent=2))
        zf.writestr("training_metrics.json", json.dumps(artifact.training_metrics, indent=2))

        meta = build_meta(
            seed=artifact.training_config.get("seed"),
            data_sha256=artifact.training_config.get("data_sha256"),
            extra={"format": "legacy-h5-zip"},
        )
        zf.writestr("meta.json", json.dumps(meta, indent=2))

    return buf.getvalue()


def import_model_zip(data: bytes) -> ImportedModel:
    """Deserialise a model ZIP archive (as produced by :func:`export_model_zip`).

    Returns the rebuilt Keras model alongside its normalisation coefficients,
    column lists and training config/metrics.
    """
    import os
    import tempfile

    from tensorflow.keras.models import model_from_json

    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "r") as zf:
        arch_json = zf.read("NNarchitecture.json").decode("utf-8")
        model = model_from_json(arch_json)

        weights_bytes = zf.read("NNweights.h5")
        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(weights_bytes)
        try:
            model.load_weights(tmp_path)
        finally:
            os.unlink(tmp_path)

        coeffs = json.loads(zf.read("NNnormCoefficients.json").decode("utf-8"))

        def _first(x):
            return x[0] if isinstance(x, (list, tuple)) else x

        mu_x = np.asarray(_first(coeffs["muX"]), dtype=float)
        sigma_x = np.asarray(_first(coeffs["SX"]), dtype=float)
        mu_y = np.asarray(_first(coeffs["muY"]), dtype=float)
        sigma_y = np.asarray(_first(coeffs["SY"]), dtype=float)

        training_config = json.loads(zf.read("training_config.json").decode("utf-8"))
        training_metrics = json.loads(zf.read("training_metrics.json").decode("utf-8"))

    return {
        "model": model,
        "mu_x": mu_x,
        "sigma_x": sigma_x,
        "mu_y": mu_y,
        "sigma_y": sigma_y,
        "input_cols": training_config.get("input_cols", []),
        "output_cols": training_config.get("output_cols", []),
        "training_config": training_config,
        "training_metrics": training_metrics,
    }
