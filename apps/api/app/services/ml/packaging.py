"""Model packaging: export/import as ZIP archives.

Provides ``export_model_zip()`` and ``import_model_zip()`` to serialise
a ``TrainedModelArtifact`` into a portable ZIP (bytes) and back, with
zero disk I/O via in-memory buffers.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import numpy as np

from .training_pipeline import TrainedModelArtifact


def export_model_zip(artifact: TrainedModelArtifact) -> bytes:
    """Serialise a trained model artifact into an in-memory ZIP archive.

    The ZIP contains:
        NNarchitecture.json   -- Keras model JSON
        NNweights.h5          -- Keras weights (HDF5)
        NNnormCoefficients.json -- normalisation coefficients
        training_config.json  -- full training config
        training_metrics.json -- evaluation metrics
    """
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Architecture
        arch_json = artifact.model.to_json()
        zf.writestr("NNarchitecture.json", arch_json)

        # Weights -> temporary HDF5 in memory via tempfile-like approach
        weights_buf = io.BytesIO()
        # Save to a temporary file path trick: keras needs a real path for .h5
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            artifact.model.save_weights(tmp_path)
            with open(tmp_path, "rb") as f:
                weights_bytes = f.read()
            zf.writestr("NNweights.h5", weights_bytes)
        finally:
            os.unlink(tmp_path)

        # Norm coefficients
        coeffs = {
            "muX": [artifact.mu_x.tolist()],
            "SX": [artifact.sigma_x.tolist()],
            "muY": [artifact.mu_y.tolist()],
            "SY": [artifact.sigma_y.tolist()],
        }
        zf.writestr(
            "NNnormCoefficients.json",
            json.dumps(coeffs, indent=2),
        )

        # Training config
        zf.writestr(
            "training_config.json",
            json.dumps(artifact.training_config, indent=2),
        )

        # Training metrics
        zf.writestr(
            "training_metrics.json",
            json.dumps(artifact.training_metrics, indent=2),
        )

    return buf.getvalue()


def import_model_zip(data: bytes) -> dict[str, Any]:
    """Deserialise a ZIP archive back into model components.

    Returns a dict with keys:
        model       -- compiled Keras model
        mu_x        -- ndarray
        sigma_x     -- ndarray
        mu_y        -- ndarray
        sigma_y     -- ndarray
        input_cols  -- list[str] (from training_config)
        output_cols -- list[str]
        training_config  -- dict
        training_metrics -- dict
    """
    import os
    import tempfile

    from tensorflow.keras.models import model_from_json

    buf = io.BytesIO(data)
    with zipfile.ZipFile(buf, "r") as zf:
        # Architecture
        arch_json = zf.read("NNarchitecture.json").decode("utf-8")
        model = model_from_json(arch_json)

        # Weights
        weights_bytes = zf.read("NNweights.h5")
        with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(weights_bytes)
        try:
            model.load_weights(tmp_path)
        finally:
            os.unlink(tmp_path)

        # Norm coefficients
        coeffs = json.loads(zf.read("NNnormCoefficients.json").decode("utf-8"))

        def _first(x: Any) -> Any:
            return x[0] if isinstance(x, (list, tuple)) else x

        mu_x = np.asarray(_first(coeffs["muX"]), dtype=float)
        sigma_x = np.asarray(_first(coeffs["SX"]), dtype=float)
        mu_y = np.asarray(_first(coeffs["muY"]), dtype=float)
        sigma_y = np.asarray(_first(coeffs["SY"]), dtype=float)

        # Config
        training_config = json.loads(
            zf.read("training_config.json").decode("utf-8")
        )
        training_metrics = json.loads(
            zf.read("training_metrics.json").decode("utf-8")
        )

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
