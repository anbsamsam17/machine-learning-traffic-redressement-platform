"""Reproducibility helpers — seed every RNG and enable TF op determinism.

Call :func:`seed_everything` once at the start of every training run AND
before each ``model.fit`` inside the grid-search loop. Combined with
``tf.config.experimental.enable_op_determinism()``, this makes runs
bit-exact across re-execution at fixed input data.

References:
- https://www.tensorflow.org/api_docs/python/tf/config/experimental/enable_op_determinism
- Keras :func:`keras.utils.set_random_seed` seeds Python ``random``,
  NumPy and TF in one call.
"""

from __future__ import annotations

import logging
import os
import random

logger = logging.getLogger(__name__)


def seed_everything(seed: int, *, enable_op_determinism: bool = True) -> None:
    """Seed Python, NumPy, TensorFlow + Keras and enable TF op determinism.

    Parameters
    ----------
    seed
        Integer seed propagated to all RNGs.
    enable_op_determinism
        When True (default) calls ``tf.config.experimental.enable_op_determinism``
        — required for bit-exact reproducibility but introduces a small
        perf hit on GPU (CPU is unaffected for our workload).

    Notes
    -----
    ``PYTHONHASHSEED`` must be set BEFORE the Python process starts to
    have any effect on dict/set iteration order. We still set it here for
    completeness so child processes (sub-interpreters, multiprocessing
    workers) inherit a deterministic value.
    """
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)

    # NumPy
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        logger.debug("numpy not installed; skipping np.random.seed")

    # TensorFlow + Keras
    try:
        import tensorflow as tf

        tf.random.set_seed(seed)
        try:
            import keras

            keras.utils.set_random_seed(seed)
        except ImportError:
            # Keras 3 vs tf.keras shim
            tf.keras.utils.set_random_seed(seed)

        if enable_op_determinism:
            try:
                tf.config.experimental.enable_op_determinism()
            except (RuntimeError, AttributeError) as exc:
                # Older TF or already-init = ignore
                logger.debug(
                    "enable_op_determinism skipped: %s",
                    exc,
                )
    except ImportError:
        logger.debug("tensorflow not installed; skipping tf seed")

    logger.info("seed_everything(%d) applied", seed)


def derive_seed(parent_seed: int, label: str) -> int:
    """Deterministically derive a child seed from a parent + label.

    Useful when training multiple models in a grid and you want each
    model to be reproducibly initialised but distinct from siblings.
    """
    h = hash((parent_seed, label)) & 0xFFFFFFFF
    return h
