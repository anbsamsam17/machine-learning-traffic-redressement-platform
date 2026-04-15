"""Z-score normalisation with selective ON_OFF_NORM mask.

Exact reproduction of the normalize / denormalize logic from
``xScripts/CreateMDL_TV.py`` and ``evaluate_best_model.py``.
"""

from __future__ import annotations

import numpy as np


def normalize(
    x: np.ndarray,
    on_off_norm: np.ndarray,
    mu: np.ndarray | None = None,
    sigma: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Z-score normalise *x* in-place for columns where *on_off_norm* is True.

    Parameters
    ----------
    x : ndarray of shape (n_samples, n_features)
    on_off_norm : boolean ndarray of shape (n_features,)
        ``True`` for features that should be normalised.
    mu, sigma : optional pre-computed statistics (for validation / inference).

    Returns
    -------
    x_norm, mu, sigma
    """
    if mu is None or sigma is None:
        mu = np.mean(x[:, on_off_norm], axis=0)
        sigma = np.std(x[:, on_off_norm], axis=0)
    sigma = np.where(sigma == 0, 1.0, sigma)

    x_norm = np.zeros_like(x, dtype=float)
    x_norm[:, on_off_norm] = (x[:, on_off_norm] - mu) / sigma
    x_norm[:, ~on_off_norm] = x[:, ~on_off_norm]
    return x_norm, mu, sigma


def denormalize(x_norm: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Inverse Z-score: ``x = x_norm * sigma + mu``.

    Applies to **all** columns (used for the output / target).
    """
    return x_norm * sigma + mu


def simple_norm(x_values: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Element-wise Z-score without mask (used by apply_model)."""
    sigma = np.where(sigma == 0, 1.0, sigma)
    return (x_values - mu) / sigma
