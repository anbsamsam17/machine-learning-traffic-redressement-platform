"""Grid search combinatorics: feature subsets and hyper-parameter combinations.

Exact reproduction of ``build_feature_sets()``, ``feature_mask_name()``,
and ``generate_all_combinations()`` from ``xScripts/CreateMDL_TV.py``.

No minimum number of inputs is enforced by default -- the caller can set
``min_input_count=0`` to allow any subset size.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Iterator

# Loss names accepted by ``model.compile(loss=...)``. The first three are
# Keras built-ins; the last three are project-local custom losses defined
# in ``losses.py`` and registered with ``keras.utils.get_custom_objects()``
# at import time. Any combo whose ``loss`` is not in this set is rejected
# by :func:`generate_all_combinations` to fail fast in the UI instead of
# silently falling back to MSE in the model builder.
VALID_LOSSES: frozenset[str] = frozenset(
    {
        "mse",
        "mae",
        "huber",
        "tolerance_aware",
        "pinball_p80",
        "pinball",
    }
)


def build_feature_sets(
    all_input_cols: list[str],
    mandatory_cols: list[str],
    min_input_count: int = 0,
    enable_feature_subset_grid: bool = True,
) -> list[list[str]]:
    """Generate all valid feature subsets.

    Parameters
    ----------
    all_input_cols : full list of candidate input columns.
    mandatory_cols : columns that must always be present.
    min_input_count : minimum number of total input features.
        Set to 0 for no minimum.
    enable_feature_subset_grid : if False, return ``[all_input_cols]`` only.

    Returns
    -------
    List of ordered column lists.
    """
    mandatory_cols = [c for c in mandatory_cols if c]
    missing_mandatory = [c for c in mandatory_cols if c not in all_input_cols]
    if missing_mandatory:
        raise ValueError(
            f"Mandatory columns are not part of input-cols: {missing_mandatory}"
        )

    if min_input_count < len(mandatory_cols):
        raise ValueError(
            f"min-input-count={min_input_count} cannot be less than "
            f"number of mandatory columns={len(mandatory_cols)}"
        )

    if not enable_feature_subset_grid:
        return [all_input_cols.copy()]

    optional_cols = [c for c in all_input_cols if c not in mandatory_cols]
    min_optional = max(0, min_input_count - len(mandatory_cols))

    feature_sets: list[list[str]] = []
    for k in range(min_optional, len(optional_cols) + 1):
        for subset in itertools.combinations(optional_cols, k):
            chosen = set(mandatory_cols).union(subset)
            ordered = [c for c in all_input_cols if c in chosen]
            feature_sets.append(ordered)

    if not feature_sets:
        raise ValueError("No valid feature-set generated with current constraints.")
    return feature_sets


def feature_mask_name(feature_cols: list[str], all_input_cols: list[str]) -> str:
    """Compact bitmask identifier, e.g. ``fmask_111010``."""
    feature_set = set(feature_cols)
    bits = "".join("1" if c in feature_set else "0" for c in all_input_cols)
    return f"fmask_{bits}"


@dataclass
class GridCombination:
    """A single point in the hyper-parameter grid."""

    feature_cols: list[str]
    feature_mask: str
    activation: str
    learning_rate: float
    min_nb_epochs: int
    loss: str
    dropout: float
    neurons_factors: list[float]
    batch_size: int
    run_name: str


def generate_all_combinations(
    feature_sets: list[list[str]],
    all_input_cols: list[str],
    activations: list[str],
    learning_rates: list[float],
    min_nb_epochs_list: list[int],
    losses: list[str] | None = None,
    dropouts: list[float] | None = None,
    neurons_factors_list: list[list[float]] | None = None,
    batch_sizes: list[int] | None = None,
) -> list[GridCombination]:
    """Cartesian product of all hyper-parameter axes.

    Returns a list of ``GridCombination`` with a deterministic ``run_name``.
    """
    losses = losses or ["mse"]
    dropouts = dropouts or [0.05]
    neurons_factors_list = neurons_factors_list or [[1.0, 1.0]]
    batch_sizes = batch_sizes or [256]

    invalid_losses = [l for l in losses if l not in VALID_LOSSES]
    if invalid_losses:
        raise ValueError(
            f"Unknown loss(es) requested: {invalid_losses}. "
            f"Allowed values: {sorted(VALID_LOSSES)}."
        )

    combos: list[GridCombination] = []

    for feature_cols in feature_sets:
        fmask = feature_mask_name(feature_cols, all_input_cols)
        for activation in activations:
            for lr in learning_rates:
                for mne in min_nb_epochs_list:
                    for loss_name in losses:
                        for drp in dropouts:
                            for nf in neurons_factors_list:
                                for bs in batch_sizes:
                                    nf_label = "x".join(str(f) for f in nf)
                                    run_name = (
                                        f"{activation}_lr{lr}"
                                        f"_ep{mne}_{loss_name}"
                                        f"_drp{drp}_nf{nf_label}"
                                        f"_bs{bs}_{fmask}"
                                    )
                                    combos.append(
                                        GridCombination(
                                            feature_cols=feature_cols,
                                            feature_mask=fmask,
                                            activation=activation,
                                            learning_rate=lr,
                                            min_nb_epochs=mne,
                                            loss=loss_name,
                                            dropout=drp,
                                            neurons_factors=nf,
                                            batch_size=bs,
                                            run_name=run_name,
                                        )
                                    )

    return combos
