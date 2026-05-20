"""Z-score normalisation with selective ON_OFF_NORM mask.

Exact reproduction of the normalize / denormalize logic from
``xScripts/CreateMDL_TV.py`` and ``evaluate_best_model.py``, augmented
with an optional ``robust`` scaler (P2B.5) that uses median and
IQR / 1.349 so the resulting scale matches std under a Gaussian input.

The function signature remains backwards-compatible: callers that do
NOT pass ``scaler`` get the original standard z-score behaviour and
identical return semantics.
"""

from __future__ import annotations

from typing import Literal

import numpy as np

ScalerType = Literal["standard", "robust"]

# Scale factor that maps IQR back onto the std of a standard normal so
# robust-scaled outputs share the magnitude of standard-scaled outputs.
# scipy.stats.norm.ppf(0.75) - scipy.stats.norm.ppf(0.25) ≈ 1.349.
_IQR_TO_STD = 1.349


def _compute_robust_stats(x_cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (median, IQR/1.349) for the supplied (n_samples, k) array."""
    mu = np.median(x_cols, axis=0)
    q75, q25 = np.percentile(x_cols, [75, 25], axis=0)
    sigma = (q75 - q25) / _IQR_TO_STD
    return mu, sigma


def normalize(
    x: np.ndarray,
    on_off_norm: np.ndarray,
    mu: np.ndarray | None = None,
    sigma: np.ndarray | None = None,
    scaler: ScalerType = "standard",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score (or robust) normalise *x* for columns where *on_off_norm* is True.

    Parameters
    ----------
    x : ndarray of shape (n_samples, n_features)
    on_off_norm : boolean ndarray of shape (n_features,)
        ``True`` for features that should be normalised.
    mu, sigma : optional pre-computed statistics (for validation / inference).
        When supplied, *scaler* is ignored — the caller is responsible for
        having fit those stats with the same scaler.
    scaler : "standard" (mean / std, default) or "robust" (median, IQR / 1.349).

    Returns
    -------
    x_norm, mu, sigma — same shapes as before.
    """
    if mu is None or sigma is None:
        cols = x[:, on_off_norm]
        if scaler == "robust":
            mu, sigma = _compute_robust_stats(cols)
        else:
            mu = np.mean(cols, axis=0)
            sigma = np.std(cols, axis=0)
    sigma = np.where(sigma == 0, 1.0, sigma)

    x_norm = np.zeros_like(x, dtype=float)
    x_norm[:, on_off_norm] = (x[:, on_off_norm] - mu) / sigma
    x_norm[:, ~on_off_norm] = x[:, ~on_off_norm]
    return x_norm, mu, sigma


def denormalize(x_norm: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Inverse Z-score: ``x = x_norm * sigma + mu``.

    Applies to **all** columns (used for the output / target). The same
    formula round-trips for both standard and robust scalers since the
    robust path simply substitutes (median, IQR/1.349) for (mean, std).
    """
    return x_norm * sigma + mu


def simple_norm(x_values: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Element-wise Z-score without mask (used by apply_model).

    Identical for standard and robust scalers — the scaler choice only
    affects how *mu* and *sigma* were fit.
    """
    sigma = np.where(sigma == 0, 1.0, sigma)
    return (x_values - mu) / sigma
