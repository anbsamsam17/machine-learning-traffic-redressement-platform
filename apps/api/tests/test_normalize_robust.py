"""Tests for the robust scaler path of app.services.ml.normalize (P2B.5).

The existing test_normalize.py covers the standard z-score path. This file
focuses on the ``scaler="robust"`` branch (median + IQR / 1.349) and the
fit-on-train -> transform/inverse round-trip property, with a fixed seed
(1750) and synthetic data only — no GPU, no real data.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.services.ml.normalize import denormalize, normalize

SEED = 1750

# Documented constant: IQR(N(0,1)) = ppf(0.75) - ppf(0.25) ~= 1.349.
_IQR_TO_STD = 1.349


class TestRobustScaler:
    def test_robust_uses_median_and_iqr_over_1349(self):
        """Robust stats must be (median, IQR / 1.349), per the docstring."""
        # Asymmetric column with an outlier so median != mean.
        x = np.array(
            [[1.0], [2.0], [3.0], [4.0], [100.0]],
            dtype=float,
        )
        on_off = np.array([True])

        _, mu, sigma = normalize(x, on_off, scaler="robust")

        col = x[:, 0]
        expected_median = np.median(col)
        q75, q25 = np.percentile(col, [75, 25])
        expected_sigma = (q75 - q25) / _IQR_TO_STD

        np.testing.assert_allclose(mu, [expected_median])
        np.testing.assert_allclose(sigma, [expected_sigma])

    def test_robust_differs_from_standard_on_skewed_data(self):
        """With an outlier, robust center (median) should differ from the mean."""
        x = np.array([[1.0], [2.0], [3.0], [4.0], [100.0]], dtype=float)
        on_off = np.array([True])

        _, mu_std, _ = normalize(x, on_off, scaler="standard")
        _, mu_rob, _ = normalize(x, on_off, scaler="robust")

        # mean is dragged up by the outlier; median is not.
        assert mu_std[0] > mu_rob[0]
        np.testing.assert_allclose(mu_rob, [3.0])

    def test_robust_matches_std_under_gaussian(self):
        """Under a (large) Gaussian sample, IQR/1.349 ~= std (the design goal)."""
        rng = np.random.default_rng(SEED)
        col = rng.normal(loc=5.0, scale=2.0, size=(5000, 1))
        on_off = np.array([True])

        _, mu_rob, sigma_rob = normalize(col, on_off, scaler="robust")

        # Center ~= true mean, scale ~= true std (within sampling tolerance).
        np.testing.assert_allclose(mu_rob, [5.0], atol=0.1)
        np.testing.assert_allclose(sigma_rob, [2.0], rtol=0.05)

    def test_robust_default_is_standard(self):
        """Omitting scaler must reproduce the standard z-score (back-compat)."""
        rng = np.random.default_rng(SEED)
        x = rng.normal(size=(10, 3))
        on_off = np.array([True, True, True])

        _, mu_default, sigma_default = normalize(x, on_off)
        _, mu_std, sigma_std = normalize(x, on_off, scaler="standard")

        np.testing.assert_allclose(mu_default, mu_std)
        np.testing.assert_allclose(sigma_default, sigma_std)


class TestFitTransformInverseRoundTrip:
    """Fit stats on TRAIN, apply to a held-out array, inverse back."""

    @pytest.mark.parametrize("scaler", ["standard", "robust"])
    def test_train_fit_then_transform_inverse(self, scaler):
        rng = np.random.default_rng(SEED)
        on_off = np.array([True, True])

        train = rng.normal(loc=[3.0, -7.0], scale=[2.0, 5.0], size=(10, 2))
        valid = rng.normal(loc=[3.0, -7.0], scale=[2.0, 5.0], size=(8, 2))

        # 1) Fit on train -> learn mu/sigma.
        _, mu, sigma = normalize(train, on_off, scaler=scaler)

        # 2) Transform validation with frozen stats (inference path).
        valid_norm, mu2, sigma2 = normalize(valid, on_off, mu=mu, sigma=sigma)
        # Frozen stats are returned unchanged.
        np.testing.assert_allclose(mu2, mu)
        np.testing.assert_allclose(sigma2, sigma)

        # 3) Inverse transform must recover the original validation values.
        valid_recovered = denormalize(valid_norm, mu, sigma)
        np.testing.assert_allclose(valid_recovered, valid, atol=1e-9)

    def test_shapes_preserved(self):
        rng = np.random.default_rng(SEED)
        x = rng.normal(size=(10, 4))
        on_off = np.array([True, False, True, False])

        x_norm, mu, sigma = normalize(x, on_off, scaler="robust")
        assert x_norm.shape == x.shape
        # mu/sigma only over the 2 normalised columns.
        assert mu.shape == (2,)
        assert sigma.shape == (2,)
