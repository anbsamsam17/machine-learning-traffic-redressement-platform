"""Custom training losses for the TV / PL model.

All losses operate in *normalized space* (z-scored target) unless noted.
They are registered with Keras at import time so that
``model.compile(loss="huber")`` etc. resolves automatically.

Losses provided
---------------
- ``HuberLoss(delta=0.25)`` — Huber loss factory (registered as ``"huber"``).
- ``ToleranceAwareLoss(tolerance=0.15, penalty_factor=1.5)`` — MAE in z-score
  space with an extra penalty on samples that exceed ±``tolerance`` σ
  (registered as ``"tolerance_aware"``).
- ``PinballLoss(quantile=0.8)`` — pinball / quantile loss
  (registered as ``"pinball_p80"`` for the default quantile=0.8).

All classes subclass :class:`keras.losses.Loss` and implement
``get_config`` / ``from_config`` so they survive a ``model.save()`` →
``keras.models.load_model()`` round-trip.

Side effect on import
---------------------
``keras.utils.get_custom_objects().update({...})`` is called at module
import time so the string aliases above resolve transparently in
``model.compile(loss=...)`` and ``keras.models.load_model(custom_objects=None)``
in downstream code paths.
"""

from __future__ import annotations

import os

# Disable GPU before any TF import — matches the rest of the ml/ package.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import tensorflow as tf  # noqa: E402
from tensorflow import keras  # noqa: E402

# ---------------------------------------------------------------------------
# Huber (P2A.1)
# ---------------------------------------------------------------------------


@keras.utils.register_keras_serializable(package="mdl_redressement", name="HuberLoss")
class HuberLoss(keras.losses.Loss):
    """Huber loss with a configurable ``delta``.

    Equivalent to :class:`keras.losses.Huber` but exposed as a project-local
    class so that the string alias ``"huber"`` always resolves to *our*
    default ``delta=0.25`` (Keras's default is 1.0, which is too lenient for
    z-scored TxPen targets where typical residuals live in ~[0, 1]).
    """

    def __init__(
        self,
        delta: float = 0.25,
        name: str = "huber",
        reduction: str = "sum_over_batch_size",
    ) -> None:
        super().__init__(name=name, reduction=reduction)
        self.delta = float(delta)

    def call(self, y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
        y_true = tf.cast(y_true, y_pred.dtype)
        error = y_true - y_pred
        abs_error = tf.abs(error)
        quadratic = tf.minimum(abs_error, self.delta)
        linear = abs_error - quadratic
        per_sample = 0.5 * tf.square(quadratic) + self.delta * linear
        # Reduce extra (non-batch) dims so the parent reducer collapses
        # cleanly to a scalar regardless of output shape.
        return tf.reduce_mean(per_sample, axis=-1)

    def get_config(self) -> dict:
        cfg = super().get_config()
        cfg.update({"delta": self.delta})
        return cfg


# ---------------------------------------------------------------------------
# Tolerance-aware (P2A.2)
# ---------------------------------------------------------------------------


@keras.utils.register_keras_serializable(package="mdl_redressement", name="ToleranceAwareLoss")
class ToleranceAwareLoss(keras.losses.Loss):
    """MAE with an extra penalty on out-of-tolerance samples.

    Computes mean absolute error on the (z-scored) predictions, then adds
    ``(penalty_factor - 1)`` × MAE for every sample whose absolute residual
    exceeds ``tolerance``.

    Approximation note
    ------------------
    The training tensor is in z-score space (target normalized by ``mu_y``,
    ``sigma_y``), so we cannot evaluate a *relative* tolerance (e.g. ±15 %
    of the de-normalized prediction) without injecting ``mu_y / sigma_y`` as
    graph constants. We instead interpret ``tolerance`` as a fraction of one
    standard deviation: a residual of magnitude ``tolerance`` in z-score
    space corresponds to ``tolerance × sigma_y`` in original units. For the
    default ``tolerance=0.15`` and TxPen z-scoring this is a close proxy of
    the operational ±15 % tolerance band that downstream evaluation uses.

    Parameters
    ----------
    tolerance : float
        Threshold above which a sample is considered out-of-tolerance
        (in z-score units).
    penalty_factor : float
        Multiplier applied to the absolute error of out-of-tolerance
        samples. ``1.0`` disables the penalty; ``1.5`` corresponds to a
        +50 % penalty (the default used in P2A.2).
    """

    def __init__(
        self,
        tolerance: float = 0.15,
        penalty_factor: float = 1.5,
        name: str = "tolerance_aware",
        reduction: str = "sum_over_batch_size",
    ) -> None:
        super().__init__(name=name, reduction=reduction)
        self.tolerance = float(tolerance)
        self.penalty_factor = float(penalty_factor)

    def call(self, y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
        y_true = tf.cast(y_true, y_pred.dtype)
        abs_error = tf.abs(y_true - y_pred)
        # Masque out-of-tolerance — float pour differentier proprement.
        #
        # NB : le masque est applique comme une PONDERATION CONSTANTE de
        # l'erreur absolue, pas comme un seuil derivable. ``oot_mask`` est issu
        # d'un ``>`` (indicatrice 0/1) dont le gradient est nul presque partout :
        # il agit donc comme un poids fige par echantillon (1.0 dans la bande de
        # tolerance, ``penalty_factor`` au-dela) et n'introduit aucune
        # discontinuite dans le gradient propage. La perte resultante est ainsi
        # une MAE PONDEREE (chaque |erreur| multipliee par son poids), et non une
        # perte a seuil dur du type hinge.
        oot_mask = tf.cast(abs_error > self.tolerance, y_pred.dtype)
        extra_factor = (self.penalty_factor - 1.0) * oot_mask
        per_sample = abs_error * (1.0 + extra_factor)
        return tf.reduce_mean(per_sample, axis=-1)

    def get_config(self) -> dict:
        cfg = super().get_config()
        cfg.update(
            {
                "tolerance": self.tolerance,
                "penalty_factor": self.penalty_factor,
            }
        )
        return cfg


# ---------------------------------------------------------------------------
# Pinball / quantile (P2A.3)
# ---------------------------------------------------------------------------


@keras.utils.register_keras_serializable(package="mdl_redressement", name="PinballP80Loss")
class PinballP80Loss(keras.losses.Loss):
    """Convenience subclass: pinball loss hard-coded to q=0.8.

    Used as the resolvable target of the string alias ``"pinball_p80"`` so
    that ``keras.losses.get("pinball_p80")`` returns an instantiable class
    (Keras' string-identifier path expects a class or a callable that takes
    ``y_true, y_pred`` — never a 0-arg factory).
    """

    def __init__(
        self,
        name: str = "pinball_p80",
        reduction: str = "sum_over_batch_size",
    ) -> None:
        super().__init__(name=name, reduction=reduction)

    def call(self, y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
        y_true = tf.cast(y_true, y_pred.dtype)
        error = y_true - y_pred
        q = tf.constant(0.8, dtype=y_pred.dtype)
        per_sample = tf.maximum(q * error, (q - 1.0) * error)
        return tf.reduce_mean(per_sample, axis=-1)


@keras.utils.register_keras_serializable(package="mdl_redressement", name="PinballLoss")
class PinballLoss(keras.losses.Loss):
    """Pinball (quantile) loss.

    ``mean(max(q * (y - yhat), (q - 1) * (y - yhat)))``

    For ``q > 0.5`` the loss penalizes *under-prediction* more than
    over-prediction (the regression line is pushed up toward the q-th
    quantile of the conditional distribution). This is the desired
    behaviour for TxPen / DPL where systematic under-correction of high
    flows is the operational failure mode.

    Parameters
    ----------
    quantile : float
        The target quantile in (0, 1). Default 0.8.
    """

    def __init__(
        self,
        quantile: float = 0.8,
        name: str = "pinball",
        reduction: str = "sum_over_batch_size",
    ) -> None:
        if not (0.0 < float(quantile) < 1.0):
            raise ValueError(f"quantile must lie strictly in (0, 1), got {quantile!r}")
        super().__init__(name=name, reduction=reduction)
        self.quantile = float(quantile)

    def call(self, y_true: tf.Tensor, y_pred: tf.Tensor) -> tf.Tensor:
        y_true = tf.cast(y_true, y_pred.dtype)
        error = y_true - y_pred
        q = tf.constant(self.quantile, dtype=y_pred.dtype)
        per_sample = tf.maximum(q * error, (q - 1.0) * error)
        return tf.reduce_mean(per_sample, axis=-1)

    def get_config(self) -> dict:
        cfg = super().get_config()
        cfg.update({"quantile": self.quantile})
        return cfg


# ---------------------------------------------------------------------------
# String-alias registration (resolves keras.losses.get("huber") etc.)
# ---------------------------------------------------------------------------
#
# The short aliases below resolve to the loss *classes* — Keras's string
# identifier path inspects ``ALL_OBJECTS_DICT[id]`` and, if the entry is a
# class, instantiates it with no arguments. That's why every aliased class
# needs sensible default ``__init__`` values (HuberLoss.delta=0.25,
# ToleranceAwareLoss.tolerance=0.15 / penalty_factor=1.5, PinballP80Loss
# fixed at q=0.8).

_CUSTOM_OBJECTS: dict[str, object] = {
    # Class names — needed when loading saved models that recorded the
    # qualified class name in their config.
    "HuberLoss": HuberLoss,
    "ToleranceAwareLoss": ToleranceAwareLoss,
    "PinballLoss": PinballLoss,
    "PinballP80Loss": PinballP80Loss,
    # Short string aliases — resolved by keras.losses.get(...) and
    # model.compile(loss="<alias>").
    "huber": HuberLoss,
    "tolerance_aware": ToleranceAwareLoss,
    "pinball_p80": PinballP80Loss,
    # Generic pinball alias — points to the q=0.8 default so a user picking
    # "pinball" gets the recommended quantile out of the box.
    "pinball": PinballP80Loss,
}

keras.utils.get_custom_objects().update(_CUSTOM_OBJECTS)

# Keras 3 string-identifier resolution (``keras.losses.get("xxx")``) does NOT
# consult ``get_custom_objects()`` — it looks up ``keras.src.losses.ALL_OBJECTS_DICT``
# directly. Inject our aliases there so that ``model.compile(loss="tolerance_aware")``
# resolves at compile/fit time without touching ``model_builder.py``.
# Wrapped in try/except so the module still imports on older Keras versions
# that don't expose this private dict.
try:  # pragma: no cover — exercised by the validation script
    from keras.src.losses import ALL_OBJECTS_DICT as _KERAS_LOSS_REGISTRY  # type: ignore

    _KERAS_LOSS_REGISTRY.update(_CUSTOM_OBJECTS)
except ImportError:
    pass


__all__ = [
    "HuberLoss",
    "ToleranceAwareLoss",
    "PinballLoss",
]
