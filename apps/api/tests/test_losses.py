"""Tests for app.services.ml.losses — custom Keras losses.

Verifies the loss VALUES against hand-computed formulas on tiny tensors and
checks the quantile asymmetry property. CPU only, no GPU, no training.
"""

from __future__ import annotations

import os

# TF CPU only — must precede any TF/Keras import.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import tensorflow as tf  # noqa: E402

from app.services.ml.losses import (  # noqa: E402
    HuberLoss,
    PinballLoss,
    ToleranceAwareLoss,
)


def _t(values):
    return tf.constant(np.asarray(values, dtype=np.float32))


# ---------------------------------------------------------------------------
# Pinball / quantile
# ---------------------------------------------------------------------------

class TestPinballLoss:
    def test_matches_hand_computed_formula(self):
        """pinball = mean(max(q*e, (q-1)*e)) with e = y_true - y_pred."""
        q = 0.8
        y_true = _t([[1.0], [2.0], [3.0]])
        y_pred = _t([[0.0], [3.0], [3.0]])  # errors: +1, -1, 0

        loss = PinballLoss(quantile=q)
        value = float(loss(y_true, y_pred).numpy())

        e = np.array([1.0, -1.0, 0.0])
        expected = np.mean(np.maximum(q * e, (q - 1.0) * e))
        assert value == pytest.approx(expected, abs=1e-6)
        # Concrete check: max(0.8, -0.2)=0.8 ; max(-0.8, 0.2)=0.2 ; 0 -> mean=1/3
        assert value == pytest.approx((0.8 + 0.2 + 0.0) / 3.0, abs=1e-6)

    def test_asymmetry_high_quantile_penalises_underprediction(self):
        """For q>0.5, under-prediction (y_pred<y_true) costs more than over."""
        q = 0.8
        loss = PinballLoss(quantile=q)
        y_true = _t([[10.0]])
        under = _t([[8.0]])   # under-prediction, e = +2
        over = _t([[12.0]])   # over-prediction,  e = -2

        l_under = float(loss(y_true, under).numpy())
        l_over = float(loss(y_true, over).numpy())

        assert l_under > l_over
        # Exact values: under -> q*2 = 1.6 ; over -> (1-q)*2 = 0.4
        assert l_under == pytest.approx(q * 2.0, abs=1e-6)
        assert l_over == pytest.approx((1.0 - q) * 2.0, abs=1e-6)

    def test_low_quantile_penalises_overprediction(self):
        q = 0.2
        loss = PinballLoss(quantile=q)
        y_true = _t([[10.0]])
        under = _t([[8.0]])   # e = +2 -> q*2 = 0.4
        over = _t([[12.0]])   # e = -2 -> (1-q)*2 = 1.6

        l_under = float(loss(y_true, under).numpy())
        l_over = float(loss(y_true, over).numpy())
        assert l_over > l_under

    def test_median_quantile_is_symmetric_half_mae(self):
        """q=0.5 pinball == 0.5 * MAE."""
        loss = PinballLoss(quantile=0.5)
        y_true = _t([[1.0], [2.0]])
        y_pred = _t([[3.0], [-2.0]])  # |e| = 2, 4
        value = float(loss(y_true, y_pred).numpy())
        expected = 0.5 * np.mean([2.0, 4.0])
        assert value == pytest.approx(expected, abs=1e-6)

    def test_invalid_quantile_raises(self):
        with pytest.raises(ValueError):
            PinballLoss(quantile=0.0)
        with pytest.raises(ValueError):
            PinballLoss(quantile=1.0)
        with pytest.raises(ValueError):
            PinballLoss(quantile=1.5)

    def test_get_config_roundtrip(self):
        loss = PinballLoss(quantile=0.7)
        cfg = loss.get_config()
        assert cfg["quantile"] == pytest.approx(0.7)
        rebuilt = PinballLoss.from_config(cfg)
        assert rebuilt.quantile == pytest.approx(0.7)


# ---------------------------------------------------------------------------
# Huber
# ---------------------------------------------------------------------------

class TestHuberLoss:
    def test_matches_hand_computed_formula(self):
        delta = 0.25
        y_true = _t([[1.0], [2.0]])
        y_pred = _t([[0.9], [5.0]])  # errors: 0.1 (quad), -3.0 (linear)

        loss = HuberLoss(delta=delta)
        value = float(loss(y_true, y_pred).numpy())

        def huber(e):
            a = abs(e)
            quad = min(a, delta)
            lin = a - quad
            return 0.5 * quad ** 2 + delta * lin

        expected = np.mean([huber(0.1), huber(3.0)])
        assert value == pytest.approx(expected, abs=1e-6)

    def test_default_delta_is_025(self):
        assert HuberLoss().delta == pytest.approx(0.25)

    def test_quadratic_regime_equals_half_squared_error(self):
        """For |e| <= delta, Huber == 0.5 * e^2."""
        delta = 1.0
        loss = HuberLoss(delta=delta)
        y_true = _t([[0.0]])
        y_pred = _t([[0.5]])  # |e| = 0.5 < delta
        value = float(loss(y_true, y_pred).numpy())
        assert value == pytest.approx(0.5 * 0.5 ** 2, abs=1e-6)


# ---------------------------------------------------------------------------
# Tolerance-aware
# ---------------------------------------------------------------------------

class TestToleranceAwareLoss:
    def test_matches_hand_computed_formula(self):
        tol = 0.15
        pf = 1.5
        loss = ToleranceAwareLoss(tolerance=tol, penalty_factor=pf)

        y_true = _t([[1.0], [2.0]])
        y_pred = _t([[1.05], [2.5]])  # |e| = 0.05 (in tol), 0.5 (out of tol)
        value = float(loss(y_true, y_pred).numpy())

        # in-tol sample keeps |e|; out-of-tol sample gets *penalty_factor.
        expected = np.mean([0.05 * 1.0, 0.5 * pf])
        assert value == pytest.approx(expected, abs=1e-6)

    def test_penalty_factor_one_equals_mae(self):
        loss = ToleranceAwareLoss(tolerance=0.15, penalty_factor=1.0)
        y_true = _t([[1.0], [2.0]])
        y_pred = _t([[1.5], [2.9]])  # both out-of-tol
        value = float(loss(y_true, y_pred).numpy())
        expected = np.mean([0.5, 0.9])  # plain MAE
        assert value == pytest.approx(expected, abs=1e-6)

    def test_out_of_tolerance_increases_loss(self):
        loss = ToleranceAwareLoss(tolerance=0.15, penalty_factor=1.5)
        y_true = _t([[1.0]])
        in_tol = float(loss(y_true, _t([[1.10]])).numpy())   # |e|=0.10 in tol
        out_tol = float(loss(y_true, _t([[1.10 + 0.10]])).numpy())  # |e|=0.20 out
        # The out-of-tol residual is larger AND penalised.
        assert out_tol > in_tol
