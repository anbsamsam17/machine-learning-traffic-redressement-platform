"""Tests for app.services.ml.normalize — Z-score with ON_OFF_NORM mask."""

from __future__ import annotations

import numpy as np
import pytest

from app.services.ml.normalize import denormalize, normalize, simple_norm


class TestNormalize:
    """Tests for the normalize() function reproducing CreateMDL_TV.py logic."""

    def test_basic_zscore_all_on(self):
        """All columns normalised: standard Z-score."""
        x = np.array([[10.0, 20.0], [30.0, 40.0], [50.0, 60.0]])
        on_off = np.array([True, True])
        x_norm, mu, sigma = normalize(x, on_off)

        np.testing.assert_allclose(mu, np.mean(x, axis=0))
        np.testing.assert_allclose(sigma, np.std(x, axis=0))
        expected = (x - mu) / sigma
        np.testing.assert_allclose(x_norm, expected)

    def test_partial_on_off_norm(self):
        """Only first column normalised, second passes through."""
        x = np.array([[10.0, 100.0], [30.0, 200.0], [50.0, 300.0]])
        on_off = np.array([True, False])

        x_norm, mu, sigma = normalize(x, on_off)

        # mu and sigma only computed on normalised columns
        assert mu.shape == (1,)
        assert sigma.shape == (1,)
        np.testing.assert_allclose(mu, [np.mean(x[:, 0])])
        np.testing.assert_allclose(sigma, [np.std(x[:, 0])])

        # Normalised column
        expected_col0 = (x[:, 0] - mu[0]) / sigma[0]
        np.testing.assert_allclose(x_norm[:, 0], expected_col0)

        # Passthrough column
        np.testing.assert_allclose(x_norm[:, 1], x[:, 1])

    def test_sigma_zero_replaced_by_one(self):
        """When sigma=0, it should be replaced by 1 (no division by zero)."""
        x = np.array([[5.0, 10.0], [5.0, 20.0], [5.0, 30.0]])
        on_off = np.array([True, True])

        x_norm, mu, sigma = normalize(x, on_off)

        # Col 0 has zero std -> sigma forced to 1
        assert sigma[0] == 1.0
        # Result: (5 - 5) / 1 = 0
        np.testing.assert_allclose(x_norm[:, 0], 0.0)

    def test_precomputed_mu_sigma(self):
        """Use pre-computed stats (validation / inference path)."""
        x = np.array([[10.0, 20.0], [30.0, 40.0]])
        on_off = np.array([True, True])
        mu = np.array([20.0, 30.0])
        sigma = np.array([10.0, 10.0])

        x_norm, mu_out, sigma_out = normalize(x, on_off, mu, sigma)

        np.testing.assert_allclose(mu_out, mu)
        np.testing.assert_allclose(sigma_out, sigma)
        np.testing.assert_allclose(x_norm[0], [-1.0, -1.0])
        np.testing.assert_allclose(x_norm[1], [1.0, 1.0])

    def test_round_trip(self):
        """normalize then denormalize on output col should recover original."""
        y = np.array([[15.0], [25.0], [35.0]])
        on_off = np.array([True])

        y_norm, mu, sigma = normalize(y, on_off)
        y_recovered = denormalize(y_norm, mu, sigma)

        np.testing.assert_allclose(y_recovered, y, atol=1e-10)

    def test_output_dtype_float(self):
        x = np.array([[1, 2], [3, 4]], dtype=int)
        on_off = np.array([True, True])
        x_norm, _, _ = normalize(x, on_off)
        assert x_norm.dtype == float

    def test_does_not_modify_input(self):
        """normalize should not modify the original array."""
        x = np.array([[10.0, 20.0], [30.0, 40.0]])
        x_copy = x.copy()
        on_off = np.array([True, True])
        normalize(x, on_off)
        np.testing.assert_array_equal(x, x_copy)


class TestDenormalize:
    def test_basic(self):
        x_norm = np.array([[0.0], [1.0], [-1.0]])
        mu = np.array([10.0])
        sigma = np.array([5.0])
        result = denormalize(x_norm, mu, sigma)
        np.testing.assert_allclose(result, [[10.0], [15.0], [5.0]])


class TestSimpleNorm:
    def test_matches_manual_zscore(self):
        x = np.array([[10.0, 20.0], [30.0, 40.0]])
        mu = np.array([20.0, 30.0])
        sigma = np.array([10.0, 10.0])
        result = simple_norm(x, mu, sigma)
        np.testing.assert_allclose(result, [[-1.0, -1.0], [1.0, 1.0]])

    def test_sigma_zero(self):
        x = np.array([[5.0]])
        mu = np.array([5.0])
        sigma = np.array([0.0])
        result = simple_norm(x, mu, sigma)
        np.testing.assert_allclose(result, [[0.0]])
