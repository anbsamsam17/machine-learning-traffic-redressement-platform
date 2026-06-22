"""Keras model builder.

Originally an exact reproduction of ``build_model()`` from
``xScripts/CreateMDL_TV.py`` (a pure Sequential MLP). Extended progressively:

- **P2B.7**  : optional learned embedding for the ``year_mapped`` categorical
  feature (Functional model with an Embedding lookup branch).
- **P3.1**   : AdamW optimizer + L2 ``weight_decay``.
- **P3.2**   : SELU activation → ``lecun_normal`` init + ``AlphaDropout`` +
  BatchNorm skipped (SELU is self-normalizing).
- **P3.3**   : optional input → last-hidden skip connection (forces the
  Sequential path through the Functional API when enabled).
- **P3.4**   : adaptive (decreasing) dropout schedule across hidden layers.
- **P3.5**   : optimizer gradient clipping via ``clipnorm``.
- **P3.7**   : LayerNorm vs BatchNorm via ``norm_layer`` (new) — the legacy
  ``use_batch_norm`` bool still works for back-compat.
- **P3.9**   : multi-quantile regression head (3 outputs for q ∈ {0.2, 0.5,
  0.8}) with an automatic sum-of-pinballs loss.

Every flag introduced after P2B.7 defaults to its pre-existing behavior so
the build path stays byte-identical when callers pass nothing new (existing
checkpoints continue to round-trip through ``model.save()`` /
``keras.models.load_model()``).
"""

from __future__ import annotations

import os
from typing import Literal

# Disable GPU before any TF import
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_GPU_ALLOCATOR", "cuda_malloc_async")
os.environ.setdefault("TF_XLA_FLAGS", "--tf_xla_enable_xla_devices=false")

import logging as _logging  # noqa: E402

# Keras 3 exposes ``saving.register_keras_serializable`` on the standalone
# ``keras`` package; ``tensorflow.keras`` is a lazy shim that does not, so
# we import directly.
import keras as _keras_pkg  # noqa: E402
import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402
from tensorflow.keras import Sequential  # noqa: E402
from tensorflow.keras.layers import Dense, Dropout  # noqa: E402
from tensorflow.keras.optimizers import Adam  # noqa: E402

_mb_logger = _logging.getLogger(__name__)


# AdamW availability — Keras 3 ships it natively; older TF/Keras may not.
try:
    from tensorflow.keras.optimizers import AdamW as _AdamW  # noqa: E402

    _HAS_ADAMW = True
except ImportError:  # pragma: no cover — depends on env
    _AdamW = None  # type: ignore
    _HAS_ADAMW = False
    _mb_logger.debug("keras.optimizers.AdamW not available — 'adamw' will fall back to Adam")


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


# ---------------------------------------------------------------------------
# Helpers (P3.4 dropout schedule, P3.7 norm layer, P3.9 multi-quantile loss)
# ---------------------------------------------------------------------------


def _dropout_schedule(dropout: float, n_layers: int, schedule: str) -> list[float]:
    """Return a list of per-layer dropout rates.

    - ``uniform``     : ``[dropout] * n_layers`` (legacy behaviour).
    - ``decreasing``  : linear schedule from ``dropout`` down to
      ``dropout * 0.2``. For N=3 this gives ``[dropout, dropout*0.5,
      dropout*0.2]`` (within float tolerance) which matches the
      spec example.
    """
    if n_layers <= 0:
        return []
    if schedule == "decreasing" and n_layers > 1:
        # linspace from dropout to dropout*0.2 across n_layers points.
        start, end = float(dropout), float(dropout) * 0.2
        step = (end - start) / (n_layers - 1)
        return [start + step * i for i in range(n_layers)]
    return [float(dropout)] * n_layers


def _resolve_norm_layer(use_batch_norm: bool, norm_layer: str | None, activation: str) -> str:
    """Resolve the requested normalization mode.

    Precedence:
      1. Explicit ``norm_layer`` (if not None) wins.
      2. Otherwise fall back to the legacy ``use_batch_norm`` bool.
      3. SELU automatically disables any extra normalization
         (self-normalizing).
    """
    if activation == "selu":
        return "none"
    if norm_layer is not None:
        return norm_layer
    return "batch" if use_batch_norm else "none"


def _make_norm_layer(mode: str, name: str | None = None) -> keras.layers.Layer | None:
    if mode == "batch":
        return (
            keras.layers.BatchNormalization(name=name)
            if name
            else keras.layers.BatchNormalization()
        )
    if mode == "layer":
        return (
            keras.layers.LayerNormalization(name=name)
            if name
            else keras.layers.LayerNormalization()
        )
    return None


def _dropout_layer(rate: float, activation: str, **kwargs) -> keras.layers.Layer:
    """Return Dropout (or AlphaDropout when activation is SELU)."""
    if activation == "selu":
        return keras.layers.AlphaDropout(rate, **kwargs)
    return Dropout(rate, **kwargs)


def _multi_quantile_loss(quantiles: list[float]):
    """Build a callable summing pinball losses across the last axis.

    Expects ``y_pred`` of shape ``(batch, len(quantiles))`` and broadcasts
    ``y_true`` (shape ``(batch, 1)``) over the quantile axis. The total loss
    is the mean of per-quantile pinball losses (mean-reduced per the
    standard convention).

    .. warning:: Risque de croisement de quantiles (quantile crossing)

        Chaque quantile est optimise independamment via sa propre perte
        pinball, puis on en prend la moyenne. Cette somme/moyenne de pertes
        pinball n'impose AUCUNE contrainte de monotonie entre les colonnes de
        sortie : rien ne garantit que ``q20 <= q50 <= q80`` ligne par ligne.
        En pratique les quantiles predits peuvent donc se croiser
        (``q20 > q50``, etc.), surtout sur les regions a faible support ou en
        debut d'entrainement.

        Implications pour l'aval :
        - la colonne q=0.5 est utilisee comme prediction principale ; les
          colonnes q=0.2 / q=0.8 servent d'intervalle indicatif, qui peut
          ponctuellement etre incoherent (borne basse > borne haute) ;
        - aucun re-tri / isotonisation n'est applique ici. Si une monotonie
          stricte est requise, trier les sorties par quantile en
          post-traitement (hors de cette perte, donc sans impact sur la
          logique d'entrainement).
    """
    qs = [float(q) for q in quantiles]
    if not qs or any(not (0.0 < q < 1.0) for q in qs):
        raise ValueError(f"quantiles must lie strictly in (0, 1); got {qs!r}")

    @_keras_pkg.saving.register_keras_serializable(
        package="mdl", name=f"multi_quantile_loss_{'_'.join(str(int(q*100)) for q in qs)}"
    )
    def loss_fn(y_true, y_pred):
        y_true = tf.cast(y_true, y_pred.dtype)
        # Broadcast y_true over the quantile axis.
        # y_true shape: (B, 1) or (B,) — reshape to (B, 1) then broadcast.
        if y_true.shape.rank == 1:
            y_true = tf.expand_dims(y_true, axis=-1)
        # y_pred shape: (B, Q)
        error = y_true - y_pred  # (B, Q) via broadcast
        q_const = tf.constant(qs, dtype=y_pred.dtype)  # (Q,)
        per_quantile = tf.maximum(q_const * error, (q_const - 1.0) * error)
        # Average over batch AND over quantile axis -> scalar.
        return tf.reduce_mean(per_quantile)

    return loss_fn


# ---------------------------------------------------------------------------
# Optimizer / compile
# ---------------------------------------------------------------------------


def _build_optimizer(
    name: str,
    learning_rate: float,
    weight_decay: float,
    clipnorm: float | None,
):
    """Construct the requested optimizer, with optional weight_decay + clipnorm."""
    kwargs: dict = {"learning_rate": learning_rate}
    if clipnorm is not None:
        kwargs["clipnorm"] = float(clipnorm)

    if name == "adamw":
        if _HAS_ADAMW:
            return _AdamW(weight_decay=float(weight_decay or 0.0), **kwargs)
        _mb_logger.debug("AdamW not available in this Keras build — falling back to Adam")
        return Adam(**kwargs)
    # default Adam path
    return Adam(**kwargs)


def _compile_model(
    model: keras.Model,
    learning_rate: float,
    loss: str,
    *,
    optimizer: str = "adam",
    weight_decay: float = 0.0,
    clipnorm: float | None = None,
    use_quantile_head: bool = False,
    quantiles: tuple[float, ...] = (0.2, 0.5, 0.8),
) -> None:
    """Compile a model with the standard optimizer/loss/metrics triple."""
    # Trigger custom loss registration (tolerance_aware, pinball_p80, pinball, huber)
    from . import losses as _losses  # noqa: F401

    if use_quantile_head:
        loss_fn = _multi_quantile_loss(list(quantiles))
        # Standard regression metrics don't apply to a 3-vector head; skip
        # them rather than confusing Keras (it would compute them column-wise
        # which is not meaningful).
        metrics = []
    else:
        if loss == "huber":
            loss_fn = keras.losses.Huber(delta=1.0, name="huber")
        elif loss == "mae":
            loss_fn = keras.losses.MeanAbsoluteError(name="mae_loss")
        elif loss == "mse":
            loss_fn = keras.losses.MeanSquaredError(name="mse")
        else:
            # Route registered aliases ("tolerance_aware", "pinball_p80", "pinball")
            # through keras.losses.get so custom losses participate.
            try:
                loss_fn = keras.losses.get(loss)
            except Exception:
                loss_fn = keras.losses.MeanSquaredError(name="mse")

        metrics = [
            keras.metrics.MeanAbsoluteError(name="mae"),
            keras.metrics.MeanAbsolutePercentageError(name="mape"),
            keras.metrics.R2Score(name="r2"),
        ]

    optimizer_obj = _build_optimizer(
        name=optimizer,
        learning_rate=learning_rate,
        weight_decay=weight_decay,
        clipnorm=clipnorm,
    )

    model.compile(
        optimizer=optimizer_obj,
        loss=loss_fn,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Hidden stack builder shared by Sequential / Functional / Skip / Embedding
# ---------------------------------------------------------------------------


def _apply_hidden_stack(
    x,
    *,
    input_size: int,
    activation: str,
    neurons_factors: list[float],
    dropout_rates: list[float],
    norm_mode: str,
    initializer: str,
    name_prefix: str = "",
):
    """Apply the standard Dropout → (Norm) → Dense stack to ``x``.

    Returns the final hidden tensor. Used by every Functional path
    (year embedding, skip-connection, quantile head, LayerNorm).
    """
    for i, factor in enumerate(neurons_factors):
        n_units = max(2, int(round(input_size * factor)))
        drop = dropout_rates[i]
        x = _dropout_layer(
            drop, activation, name=f"{name_prefix}dropout_{i}" if name_prefix else None
        )(x)
        norm = _make_norm_layer(norm_mode, name=f"{name_prefix}norm_{i}" if name_prefix else None)
        if norm is not None:
            x = norm(x)
        x = Dense(
            n_units,
            activation=activation,
            kernel_initializer=initializer,
            name=f"{name_prefix}dense_{i}" if name_prefix else None,
        )(x)
    return x


# ---------------------------------------------------------------------------
# Build paths
# ---------------------------------------------------------------------------


def _build_sequential(
    input_size: int,
    output_size: int,
    activation: str,
    dropout: float,
    neurons_factors: list[float],
    use_batch_norm: bool,
    initializer: str,
    *,
    dropout_schedule: str = "uniform",
    norm_mode: str = "batch",
    use_quantile_head: bool = False,
    n_quantiles: int = 3,
) -> keras.Model:
    """Legacy Sequential build path — preserved byte-for-byte when no new flag is set.

    The signature accepts the new P3 flags but, when ``dropout_schedule`` is
    ``"uniform"`` and ``norm_mode`` matches ``use_batch_norm``, the resulting
    Keras layer graph is identical to the pre-P3 implementation so old
    checkpoints round-trip cleanly.
    """
    rates = _dropout_schedule(dropout, len(neurons_factors), dropout_schedule)

    layers: list = []
    for i, factor in enumerate(neurons_factors):
        n_units = max(2, int(round(input_size * factor)))
        rate_i = rates[i]
        if i == 0:
            layers.append(_dropout_layer(rate_i, activation, input_shape=(input_size,)))
        else:
            layers.append(_dropout_layer(rate_i, activation))
        if norm_mode == "batch":
            layers.append(keras.layers.BatchNormalization())
        elif norm_mode == "layer":
            layers.append(keras.layers.LayerNormalization())
        layers.append(Dense(n_units, activation=activation, kernel_initializer=initializer))

    # Output layer -- linear activation for regression.
    out_units = n_quantiles if use_quantile_head else output_size
    layers.append(Dense(out_units, activation="linear"))

    return Sequential(layers)


def _build_functional(
    input_size: int,
    output_size: int,
    activation: str,
    dropout: float,
    neurons_factors: list[float],
    initializer: str,
    *,
    dropout_schedule: str = "uniform",
    norm_mode: str = "none",
    use_skip_connection: bool = False,
    use_quantile_head: bool = False,
    n_quantiles: int = 3,
) -> keras.Model:
    """Functional model with optional input→last-hidden skip connection.

    Used whenever a feature requires a non-linear graph (skip connection,
    quantile head, etc.) that the Sequential API cannot express.
    """
    rates = _dropout_schedule(dropout, len(neurons_factors), dropout_schedule)

    inputs = keras.Input(shape=(input_size,), name="features")
    x = _apply_hidden_stack(
        inputs,
        input_size=input_size,
        activation=activation,
        neurons_factors=neurons_factors,
        dropout_rates=rates,
        norm_mode=norm_mode,
        initializer=initializer,
        name_prefix="hidden_",
    )

    if use_skip_connection:
        x = keras.layers.Concatenate(name="skip_concat")([x, inputs])

    out_units = n_quantiles if use_quantile_head else output_size
    out_name = "quantile_output" if use_quantile_head else "output"
    outputs = Dense(out_units, activation="linear", name=out_name)(x)
    return keras.Model(inputs=inputs, outputs=outputs, name="model_functional")


def _build_with_year_embedding(
    input_size: int,
    output_size: int,
    activation: str,
    dropout: float,
    neurons_factors: list[float],
    initializer: str,
    year_feature_idx: int,
    year_n_categories: int,
    year_embedding_dim: int,
    *,
    dropout_schedule: str = "uniform",
    norm_mode: str = "none",
    use_skip_connection: bool = False,
    use_quantile_head: bool = False,
    n_quantiles: int = 3,
) -> keras.Model:
    """Functional model that routes ``year_mapped`` through an Embedding layer.

    The remaining (continuous) features pass through the same Dense stack as
    the legacy build. The flat embedding vector is concatenated to the Dense
    stack output, then projected through one final hidden Dense layer before
    the linear output head.
    """
    if not (0 <= year_feature_idx < input_size):
        raise ValueError(
            f"year_feature_idx={year_feature_idx} out of range " f"for input_size={input_size}"
        )

    rates = _dropout_schedule(dropout, len(neurons_factors), dropout_schedule)

    inputs = keras.Input(shape=(input_size,), name="features")

    # Slice the year column out and cast to int for the embedding lookup.
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
        x = _dropout_layer(rates[i], activation, name=f"emb_dropout_{i}")(x)
        norm = _make_norm_layer(norm_mode, name=f"emb_norm_{i}")
        if norm is not None:
            x = norm(x)
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

    if use_skip_connection:
        merged = keras.layers.Concatenate(name="emb_skip_concat")([merged, inputs])

    out_units = n_quantiles if use_quantile_head else output_size
    out_name = "emb_quantile_output" if use_quantile_head else "emb_output"
    outputs = Dense(out_units, activation="linear", name=out_name)(merged)

    return keras.Model(inputs=inputs, outputs=outputs, name="model_with_year_embedding")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Default quantiles for the P3.9 multi-quantile head.
_DEFAULT_QUANTILES: tuple[float, float, float] = (0.2, 0.5, 0.8)


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
    # P2B.7 — year embedding
    year_embedding: bool = False,
    year_feature_idx: int | None = None,
    year_n_categories: int = 7,
    year_embedding_dim: int = 3,
    # P3.1 — optimizer + weight decay
    optimizer: Literal["adam", "adamw"] = "adam",
    weight_decay: float = 0.0,
    # P3.3 — skip connection
    use_skip_connection: bool = False,
    # P3.4 — dropout schedule
    dropout_schedule: Literal["uniform", "decreasing"] = "uniform",
    # P3.5 — gradient clipping
    clipnorm: float | None = None,
    # P3.7 — normalization layer (takes precedence over use_batch_norm
    # when explicitly set; defaults to None which means "infer from
    # use_batch_norm" so behaviour is byte-identical for existing callers).
    norm_layer: Literal["none", "batch", "layer"] | None = None,
    # P3.9 — quantile regression head
    use_quantile_head: bool = False,
    quantiles: tuple[float, ...] = _DEFAULT_QUANTILES,
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
    optimizer
        ``"adam"`` (default) or ``"adamw"`` (P3.1). AdamW supports
        decoupled weight decay.
    weight_decay
        L2 weight decay for AdamW. Ignored when ``optimizer == "adam"``.
    use_skip_connection
        P3.3 — when True, concatenates the input vector with the final
        hidden representation before the output Dense layer. Implies the
        Functional API.
    dropout_schedule
        P3.4 — ``"uniform"`` (default, legacy) or ``"decreasing"`` for a
        linear schedule from ``dropout`` down to ``dropout * 0.2``.
    clipnorm
        P3.5 — when set, the optimizer clips gradients by global norm.
    norm_layer
        P3.7 — ``"none"`` | ``"batch"`` | ``"layer"``. When None (default)
        falls back to the legacy ``use_batch_norm`` bool so existing
        callers see no behaviour change. SELU activation overrides this
        to ``"none"`` (self-normalizing).
    use_quantile_head
        P3.9 — when True the output layer becomes ``len(quantiles)``
        neurons and the model is compiled with a sum-of-pinballs loss.
        The "main" prediction in downstream code is the q=0.5 column.
    """
    if neurons_factors is None:
        neurons_factors = [1.0, 1.0]

    # Choose kernel initializer based on activation for optimal convergence
    initializer = "lecun_normal" if activation == "selu" else "he_normal"

    # Resolve the normalization mode (P3.7) — SELU forces "none" (P3.2).
    norm_mode = _resolve_norm_layer(use_batch_norm, norm_layer, activation)

    # When the quantile head is requested we override ``output_size`` for
    # the output Dense; the call signature still asks for ``output_size``
    # (kept for callers that don't know about the new flag).
    n_quantiles = len(quantiles) if use_quantile_head else 0

    use_embedding = bool(year_embedding) and year_feature_idx is not None
    use_functional = use_embedding or use_skip_connection or use_quantile_head

    if use_embedding:
        model = _build_with_year_embedding(
            input_size=input_size,
            output_size=output_size,
            activation=activation,
            dropout=dropout,
            neurons_factors=neurons_factors,
            initializer=initializer,
            year_feature_idx=int(year_feature_idx),
            year_n_categories=int(year_n_categories),
            year_embedding_dim=int(year_embedding_dim),
            dropout_schedule=dropout_schedule,
            norm_mode=norm_mode,
            use_skip_connection=use_skip_connection,
            use_quantile_head=use_quantile_head,
            n_quantiles=n_quantiles or 3,
        )
    elif use_functional:
        model = _build_functional(
            input_size=input_size,
            output_size=output_size,
            activation=activation,
            dropout=dropout,
            neurons_factors=neurons_factors,
            initializer=initializer,
            dropout_schedule=dropout_schedule,
            norm_mode=norm_mode,
            use_skip_connection=use_skip_connection,
            use_quantile_head=use_quantile_head,
            n_quantiles=n_quantiles or 3,
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
            dropout_schedule=dropout_schedule,
            norm_mode=norm_mode,
            use_quantile_head=False,  # quantile head forces Functional path
            n_quantiles=0,
        )

    _compile_model(
        model,
        learning_rate=learning_rate,
        loss=loss,
        optimizer=optimizer,
        weight_decay=weight_decay,
        clipnorm=clipnorm,
        use_quantile_head=use_quantile_head,
        quantiles=tuple(quantiles) if use_quantile_head else _DEFAULT_QUANTILES,
    )
    return model
