"""Tests for app.services.ml.model_builder — helpers purs + build minimal.

Couverture :
- ``_dropout_schedule`` : schedule uniform / decreasing, cas limites ;
- ``_resolve_norm_layer`` : precedence norm_layer > use_batch_norm, override SELU ;
- ``_make_norm_layer`` : type de couche retourne (batch / layer / none) ;
- ``build_model`` minimal (2 couches cachees) : shapes I/O et reproductibilite
  a seed fixe 1750.

CPU only, pas de GPU, pas d'entrainement (au plus un build + un predict).
"""

from __future__ import annotations

import os

# TF CPU only — doit preceder tout import TF/Keras (cf code-style.md).
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.services.ml.model_builder import (  # noqa: E402
    _dropout_schedule,
    _make_norm_layer,
    _resolve_norm_layer,
    build_model,
)
from app.services.ml.seeding import seed_everything  # noqa: E402

SEED = 1750


# ---------------------------------------------------------------------------
# _dropout_schedule
# ---------------------------------------------------------------------------


class TestDropoutSchedule:
    def test_uniform_repeats_rate(self):
        assert _dropout_schedule(0.1, 3, "uniform") == [0.1, 0.1, 0.1]

    def test_empty_when_no_layers(self):
        assert _dropout_schedule(0.1, 0, "decreasing") == []

    def test_single_layer_falls_back_to_uniform(self):
        # n_layers == 1 : pas de schedule decroissant possible.
        assert _dropout_schedule(0.2, 1, "decreasing") == [0.2]

    def test_decreasing_endpoints(self):
        # Linspace de dropout a dropout*0.2.
        rates = _dropout_schedule(0.5, 3, "decreasing")
        assert len(rates) == 3
        assert rates[0] == pytest.approx(0.5)
        assert rates[-1] == pytest.approx(0.5 * 0.2)

    def test_decreasing_is_monotonic(self):
        rates = _dropout_schedule(0.4, 4, "decreasing")
        assert all(rates[i] >= rates[i + 1] for i in range(len(rates) - 1))


# ---------------------------------------------------------------------------
# _resolve_norm_layer
# ---------------------------------------------------------------------------


class TestResolveNormLayer:
    def test_selu_forces_none(self):
        # SELU est auto-normalisant : toute normalisation est desactivee.
        assert _resolve_norm_layer(True, "batch", "selu") == "none"

    def test_explicit_norm_layer_wins(self):
        assert _resolve_norm_layer(True, "layer", "elu") == "layer"

    def test_legacy_use_batch_norm_true(self):
        assert _resolve_norm_layer(True, None, "elu") == "batch"

    def test_legacy_use_batch_norm_false(self):
        assert _resolve_norm_layer(False, None, "elu") == "none"


# ---------------------------------------------------------------------------
# _make_norm_layer
# ---------------------------------------------------------------------------


class TestMakeNormLayer:
    def test_none_mode_returns_none(self):
        assert _make_norm_layer("none") is None

    def test_batch_mode(self):
        import keras

        layer = _make_norm_layer("batch")
        assert isinstance(layer, keras.layers.BatchNormalization)

    def test_layer_mode(self):
        import keras

        layer = _make_norm_layer("layer")
        assert isinstance(layer, keras.layers.LayerNormalization)


# ---------------------------------------------------------------------------
# build_model — minimal 2 couches
# ---------------------------------------------------------------------------


class TestBuildModelMinimal:
    def _build(self):
        return build_model(
            input_size=4,
            output_size=1,
            learning_rate=0.01,
            activation="elu",
            dropout=0.05,
            loss="mse",
            neurons_factors=[1.0, 1.0],
        )

    def test_input_output_shapes(self):
        model = self._build()
        x = np.zeros((3, 4), dtype=np.float32)
        y = model.predict(x, verbose=0)
        assert y.shape == (3, 1)

    def test_two_hidden_dense_layers(self):
        # 2 neurons_factors -> 2 couches Dense cachees + 1 Dense de sortie.
        model = self._build()
        import keras

        dense = [lyr for lyr in model.layers if isinstance(lyr, keras.layers.Dense)]
        assert len(dense) == 3  # 2 cachees + sortie lineaire

    def test_seed_reproducible_weights(self):
        # A seed fixe identique, deux builds donnent les memes poids initiaux.
        seed_everything(SEED)
        m1 = self._build()
        seed_everything(SEED)
        m2 = self._build()

        w1 = m1.get_weights()
        w2 = m2.get_weights()
        assert len(w1) == len(w2)
        for a, b in zip(w1, w2, strict=True):
            np.testing.assert_allclose(a, b)
