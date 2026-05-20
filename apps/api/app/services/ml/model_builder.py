"""Keras model builder.

Originally an exact reproduction of ``build_model()`` from
``xScripts/CreateMDL_TV.py`` (a pure Sequential MLP). Extended in P2B.7 with
an optional learned embedding for the ``year_mapped`` categorical feature.

When ``year_embedding=False`` (default), the build path is byte-identical to
the legacy Sequential code path so that previously trained checkpoints keep
loading without surprise.
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

# Keras 3 exposes ``saving.register_keras_serializable`` on the standalone
# ``keras`` package; ``tensorflow.keras`` is a lazy shim that does not, so
# we import directly.
import keras as _keras_pkg  # noqa: E402

import logging as _logging  # noqa: E402
_mb_logger = _logging.getLogger(__name__)


# --- Custom layers for year embedding (named so they can be safely
# deserialized by keras.models.load_model without enable_unsafe_deserialization).
@_keras_pkg.saving.register_keras_serializable(package="mdl", name="YearSlice")
class _YearSlice(keras.layers.Layer):
    """Pick a single column (the year_mapped index) from a 2-D feature tensor."""

    def __init__(self, feature_idx: int, **kwargs):
        super().__init__(**kwargs)
        self.feature_idx = int(feature_idx)

    def call(self, inputs):
        return inputs[:, self.feature_idx]

    def compute_output_shape(self, input_shape):
        return (input_shape[0],)

    def get_config(self):
        config = super().get_config()
        config["feature_idx"] = self.feature_idx
        return config


@_keras_pkg.saving.register_keras_serializable(package="mdl", name="YearToIndex")
class _YearToIndex(keras.layers.Layer):
    """Cast year (float, 1..N) -> int (0..N-1) and clip in range."""

    def __init__(self, n_categories: int, **kwargs):
        super().__init__(**kwargs)
        self.n_categories = int(n_categories)

    def call(self, inputs):
        from keras import ops as kops
        return kops.clip(kops.cast(inputs, "int32") - 1, 0, self.n_categories - 1)

    def compute_output_shape(self, input_shape):
        return input_shape

    def get_config(self):
        config = super().get_config()
        config["n_categories"] = self.n_categories
        return config


@_keras_pkg.saving.register_keras_serializable(package="mdl", name="OtherFeatures")
class _OtherFeatures(keras.layers.Layer):
    """Gather all feature columns except the one at ``skip_idx``."""

    def __init__(self, skip_idx: int, input_size: int, **kwargs):
        super().__init__(**kwargs)
        self.skip_idx = int(skip_idx)
        self.input_size = int(input_size)
        self._keep = [i for i in range(self.input_size) if i != self.skip_idx]

    def call(self, inputs):
        from keras import ops as kops
        return kops.take(inputs, self._keep, axis=1)

    def compute_output_shape(self, input_shape):
        return (input_shape[0], self.input_size - 1)

    def get_config(self):
        config = super().get_config()
        config["skip_idx"] = self.skip_idx
        config["input_size"] = self.input_size
        return config

# TF threads — derived from CPU count instead of hardcoded.
# intra_op = parallelism inside one op (matmul, conv). Benefits from many cores.
# inter_op = parallelism between independent ops. 2 is enough for sequential
# Dense networks. Override via env vars MDL_TF_INTRA / MDL_TF_INTER for ops tuning.
_cpu_count = os.cpu_count() or 4
_intra = int(os.environ.get("MDL_TF_INTRA", max(2, _cpu_count - 1)))
_inter = int(os.environ.get("MDL_TF_INTER", min(4, max(2, _cpu_count // 2))))
_mb_logger.info("TF threading: intra_op=%d inter_op=%d (cpu_count=%d)", _intra, _inter, _cpu_count)

for _setter, _label in (
    (lambda: tf.config.threading.set_intra_op_parallelism_threads(_intra), "intra_op_threads"),
    (lambda: tf.config.threading.set_inter_op_parallelism_threads(_inter), "inter_op_threads"),
    (lambda: tf.config.optimizer.set_jit(False), "jit_disable"),
):
    try:
        _setter()
    except RuntimeError as exc:
        _mb_logger.debug("TF setter %s skipped (already initialised): %s", _label, exc)


def _compile_model(model: keras.Model, learning_rate: float, loss: str) -> None:
    """Compile a model with the standard optimizer/loss/metrics triple."""
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


def _build_sequential(
    input_size: int,
    output_size: int,
    activation: str,
    dropout: float,
    neurons_factors: list[float],
    use_batch_norm: bool,
    initializer: str,
) -> keras.Model:
    """Legacy Sequential build path — preserved byte-for-byte from the original."""
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

    return Sequential(layers)


def _build_with_year_embedding(
    input_size: int,
    output_size: int,
    activation: str,
    dropout: float,
    neurons_factors: list[float],
    use_batch_norm: bool,
    initializer: str,
    year_feature_idx: int,
    year_n_categories: int,
    year_embedding_dim: int,
) -> keras.Model:
    """Functional model that routes ``year_mapped`` through an Embedding layer.

    The remaining (continuous) features pass through the same Dense stack as
    the legacy build. The flat embedding vector is concatenated to the Dense
    stack output, then projected through one final hidden Dense layer before
    the linear output head.
    """
    if not (0 <= year_feature_idx < input_size):
        raise ValueError(
            f"year_feature_idx={year_feature_idx} out of range "
            f"for input_size={input_size}"
        )

    inputs = keras.Input(shape=(input_size,), name="features")

    # Slice the year column out and cast to int for the embedding lookup.
    # Indices in the model are expected to be 1..year_n_categories (e.g. 1..7
    # for 2019..2025) so we subtract 1 to map to 0..n-1.
    # Keras 3 forbids raw tf ops on KerasTensors — we use small custom Layer
    # subclasses (registered serializable) so save/load works without
    # enable_unsafe_deserialization().
    year_raw = _YearSlice(year_feature_idx, name="year_slice")(inputs)
    year_idx = _YearToIndex(year_n_categories, name="year_to_index")(year_raw)
    year_emb = keras.layers.Embedding(
        input_dim=year_n_categories,
        output_dim=year_embedding_dim,
        name="year_embedding",
    )(year_idx)
    year_emb = keras.layers.Flatten(name="year_embedding_flat")(year_emb)

    # Gather the remaining feature indices (all columns except the year one).
    other_features = _OtherFeatures(
        skip_idx=year_feature_idx,
        input_size=input_size,
        name="other_features",
    )(inputs)

    # Dense stack on the continuous features — mirrors the Sequential path.
    x = other_features
    for i, factor in enumerate(neurons_factors):
        n_units = max(2, int(round(input_size * factor)))
        x = Dropout(dropout, name=f"emb_dropout_{i}")(x)
        if use_batch_norm:
            x = keras.layers.BatchNormalization(name=f"emb_bn_{i}")(x)
        x = Dense(
            n_units,
            activation=activation,
            kernel_initializer=initializer,
            name=f"emb_dense_{i}",
        )(x)

    # Concatenate Dense stack output with the flat year embedding, then run a
    # small joint Dense layer before the linear output head.
    merged = keras.layers.Concatenate(name="merge_year")([x, year_emb])
    joint_units = max(2, int(round(input_size * (neurons_factors[-1] if neurons_factors else 1.0))))
    merged = Dense(
        joint_units,
        activation=activation,
        kernel_initializer=initializer,
        name="emb_joint_dense",
    )(merged)
    outputs = Dense(output_size, activation="linear", name="emb_output")(merged)

    return keras.Model(inputs=inputs, outputs=outputs, name="model_with_year_embedding")


def build_model(
    input_size: int,
    output_size: int,
    learning_rate: float,
    activation: str,
    dropout: float,
    loss: str = "mse",
    neurons_factors: list[float] | None = None,
    use_batch_norm: bool = False,
    *,
    year_embedding: bool = False,
    year_feature_idx: int | None = None,
    year_n_categories: int = 7,
    year_embedding_dim: int = 3,
) -> keras.Model:
    """Build a fully-connected network with dynamic depth/width.

    Parameters
    ----------
    neurons_factors
        e.g. ``[2, 1, 0.5]`` gives hidden layers of
        ``input_size*2``, ``input_size*1``, ``input_size*0.5`` neurons.
        Defaults to ``[1.0, 1.0]`` (legacy architecture).
    year_embedding
        If True *and* ``year_feature_idx`` is not None, the network switches
        to the Functional API and learns an embedding for the year column.
        When False (default) the legacy Sequential graph is built — any value
        passed for ``year_feature_idx`` is silently ignored to keep callers
        simple.
    year_feature_idx
        Index of the ``year_mapped`` column inside the input feature vector.
        Required when ``year_embedding`` is True; ignored otherwise.
    year_n_categories
        Number of distinct year values (default 7 = 2019..2025).
    year_embedding_dim
        Output dimensionality of the embedding lookup (default 3).
    """
    if neurons_factors is None:
        neurons_factors = [1.0, 1.0]

    # Choose kernel initializer based on activation for optimal convergence
    initializer = "lecun_normal" if activation == "selu" else "he_normal"

    use_embedding = bool(year_embedding) and year_feature_idx is not None
    if use_embedding:
        model = _build_with_year_embedding(
            input_size=input_size,
            output_size=output_size,
            activation=activation,
            dropout=dropout,
            neurons_factors=neurons_factors,
            use_batch_norm=use_batch_norm,
            initializer=initializer,
            year_feature_idx=int(year_feature_idx),
            year_n_categories=int(year_n_categories),
            year_embedding_dim=int(year_embedding_dim),
        )
    else:
        model = _build_sequential(
            input_size=input_size,
            output_size=output_size,
            activation=activation,
            dropout=dropout,
            neurons_factors=neurons_factors,
            use_batch_norm=use_batch_norm,
            initializer=initializer,
        )

    _compile_model(model, learning_rate=learning_rate, loss=loss)
    return model
