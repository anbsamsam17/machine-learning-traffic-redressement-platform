"""Keras Sequential model builder.

Exact reproduction of ``build_model()`` from ``xScripts/CreateMDL_TV.py``.
"""

from __future__ import annotations

import os

# Disable GPU before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_GPU_ALLOCATOR", "cuda_malloc_async")
os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_enable_xla_devices=false")

import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402
from tensorflow.keras import Sequential  # noqa: E402
from tensorflow.keras.layers import Dense, Dropout  # noqa: E402
from tensorflow.keras.optimizers import Adam  # noqa: E402

import logging as _logging  # noqa: E402
_mb_logger = _logging.getLogger(__name__)

# Limit TF threads — must run before TF initialises. If TF was already
# initialised (e.g. by a previous training run in the same worker), these
# calls raise RuntimeError("cannot be modified after initialization").
for _setter, _label in (
    (lambda: tf.config.threading.set_intra_op_parallelism_threads(4), "intra_op_threads"),
    (lambda: tf.config.threading.set_inter_op_parallelism_threads(2), "inter_op_threads"),
    (lambda: tf.config.optimizer.set_jit(False), "jit_disable"),
):
    try:
        _setter()
    except RuntimeError as exc:
        _mb_logger.debug("TF setter %s skipped (already initialised): %s", _label, exc)


def build_model(
    input_size: int,
    output_size: int,
    learning_rate: float,
    activation: str,
    dropout: float,
    loss: str = "mse",
    neurons_factors: list[float] | None = None,
    use_batch_norm: bool = False,
) -> keras.Model:
    """Build a fully-connected network with dynamic depth/width.

    Parameters
    ----------
    neurons_factors
        e.g. ``[2, 1, 0.5]`` gives hidden layers of
        ``input_size*2``, ``input_size*1``, ``input_size*0.5`` neurons.
        Defaults to ``[1.0, 1.0]`` (legacy architecture).
    """
    if neurons_factors is None:
        neurons_factors = [1.0, 1.0]

    # Choose kernel initializer based on activation for optimal convergence
    initializer = "lecun_normal" if activation == "selu" else "he_normal"

    layers: list = []
    for i, factor in enumerate(neurons_factors):
        n_units = max(2, int(round(input_size * factor)))
        if i == 0:
            layers.append(Dropout(dropout, input_shape=(input_size,)))
        else:
            layers.append(Dropout(dropout))
        if use_batch_norm:
            layers.append(keras.layers.BatchNormalization())
        layers.append(
            Dense(n_units, activation=activation, kernel_initializer=initializer)
        )

    # Output layer -- linear activation for regression
    layers.append(Dense(output_size, activation="linear"))

    model = Sequential(layers)

    # Loss selection
    if loss == "huber":
        loss_fn = keras.losses.Huber(delta=1.0, name="huber")
    elif loss == "mae":
        loss_fn = keras.losses.MeanAbsoluteError(name="mae_loss")
    else:
        loss_fn = keras.losses.MeanSquaredError(name="mse")

    model.compile(
        optimizer=Adam(learning_rate=learning_rate),
        loss=loss_fn,
        metrics=[
            keras.metrics.MeanAbsoluteError(name="mae"),
            keras.metrics.MeanAbsolutePercentageError(name="mape"),
            keras.metrics.R2Score(name="r2"),
        ],
    )
    return model
