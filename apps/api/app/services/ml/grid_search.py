"""Grid search combinatorics: feature subsets and hyper-parameter combinations.

Exact reproduction of ``build_feature_sets()``, ``feature_mask_name()``,
and ``generate_all_combinations()`` from ``xScripts/CreateMDL_TV.py``.

No minimum number of inputs is enforced by default -- the caller can set
``min_input_count=0`` to allow any subset size.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Literal

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

# --- P3 grid axes valid values ---------------------------------------------
VALID_OPTIMIZERS: frozenset[str] = frozenset({"adam", "adamw"})
VALID_DROPOUT_SCHEDULES: frozenset[str] = frozenset({"uniform", "decreasing"})
VALID_NORM_LAYERS: frozenset[str] = frozenset({"none", "batch", "layer"})


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
        raise ValueError(f"Mandatory columns are not part of input-cols: {missing_mandatory}")

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

    # --- P3 architecture axes -------------------------------------------
    # Defaults preserve legacy behaviour for callers that don't iterate on
    # these axes (the grid expander below only varies them when the caller
    # supplies non-default lists).
    optimizer: Literal["adam", "adamw"] = "adam"
    weight_decay: float = 0.0
    use_skip_connection: bool = False
    dropout_schedule: Literal["uniform", "decreasing"] = "uniform"
    clipnorm: float | None = None
    norm_layer: Literal["none", "batch", "layer"] | None = None
    use_quantile_head: bool = False


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
    # --- P3 axes (all optional; when not supplied the legacy single-value
    # grid is preserved so existing callers see no change in run_name or
    # combo count).
    optimizers: list[str] | None = None,
    weight_decays: list[float] | None = None,
    skip_connection_options: list[bool] | None = None,
    dropout_schedules: list[str] | None = None,
    clipnorms: list[float | None] | None = None,
    norm_layers: list[str | None] | None = None,
    quantile_head_options: list[bool] | None = None,
) -> list[GridCombination]:
    """Cartesian product of all hyper-parameter axes.

    Returns a list of ``GridCombination`` with a deterministic ``run_name``.

    The legacy axes (activation × lr × min_epochs × loss × dropout ×
    neurons_factors × batch_size) are unconditionally expanded. Each P3
    axis is expanded only when the caller supplies a non-default list; when
    omitted the axis collapses to its single legacy value, preserving the
    pre-P3 ``run_name`` format and combo count for back-compat.
    """
    losses = losses or ["mse"]
    dropouts = dropouts or [0.05]
    neurons_factors_list = neurons_factors_list or [[1.0, 1.0]]
    batch_sizes = batch_sizes or [256]

    invalid_losses = [loss for loss in losses if loss not in VALID_LOSSES]
    if invalid_losses:
        raise ValueError(
            f"Unknown loss(es) requested: {invalid_losses}. "
            f"Allowed values: {sorted(VALID_LOSSES)}."
        )

    # ---- P3 axes: validate, default to legacy single-value lists ----------
    optimizers = optimizers or ["adam"]
    invalid_opts = [o for o in optimizers if o not in VALID_OPTIMIZERS]
    if invalid_opts:
        raise ValueError(
            f"Unknown optimizer(s): {invalid_opts}. " f"Allowed values: {sorted(VALID_OPTIMIZERS)}."
        )

    weight_decays = weight_decays or [0.0]
    skip_connection_options = skip_connection_options or [False]

    dropout_schedules = dropout_schedules or ["uniform"]
    invalid_schedules = [s for s in dropout_schedules if s not in VALID_DROPOUT_SCHEDULES]
    if invalid_schedules:
        raise ValueError(
            f"Unknown dropout_schedule(s): {invalid_schedules}. "
            f"Allowed values: {sorted(VALID_DROPOUT_SCHEDULES)}."
        )

    clipnorms = clipnorms or [None]

    norm_layers = norm_layers or [None]
    invalid_norms = [n for n in norm_layers if n is not None and n not in VALID_NORM_LAYERS]
    if invalid_norms:
        raise ValueError(
            f"Unknown norm_layer(s): {invalid_norms}. "
            f"Allowed values: {sorted(VALID_NORM_LAYERS)} or None."
        )

    quantile_head_options = quantile_head_options or [False]

    # Detect whether each P3 axis was actually varied. When the axis stays
    # at its single legacy value we DON'T append a suffix to run_name (this
    # keeps existing fixture/run names byte-identical to pre-P3 behaviour).
    suffix_opt = optimizers != ["adam"]
    suffix_wd = weight_decays != [0.0]
    suffix_skip = skip_connection_options != [False]
    suffix_sched = dropout_schedules != ["uniform"]
    suffix_clip = clipnorms != [None]
    suffix_norm = norm_layers != [None]
    suffix_q = quantile_head_options != [False]

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
                                    for opt in optimizers:
                                        for wd in weight_decays:
                                            for skip in skip_connection_options:
                                                for sched in dropout_schedules:
                                                    for clip in clipnorms:
                                                        for norm in norm_layers:
                                                            for q_head in quantile_head_options:
                                                                nf_label = "x".join(
                                                                    str(f) for f in nf
                                                                )
                                                                run_name = (
                                                                    f"{activation}_lr{lr}"
                                                                    f"_ep{mne}_{loss_name}"
                                                                    f"_drp{drp}_nf{nf_label}"
                                                                    f"_bs{bs}_{fmask}"
                                                                )
                                                                if suffix_opt:
                                                                    run_name += f"_{opt}"
                                                                if suffix_wd:
                                                                    run_name += f"_wd{wd}"
                                                                if suffix_skip and skip:
                                                                    run_name += "_skip"
                                                                if suffix_sched:
                                                                    run_name += f"_{sched}"
                                                                if suffix_clip and clip is not None:
                                                                    run_name += f"_cn{clip}"
                                                                if suffix_norm and norm is not None:
                                                                    run_name += f"_norm{norm}"
                                                                if suffix_q and q_head:
                                                                    run_name += "_qhead"
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
                                                                        optimizer=opt,
                                                                        weight_decay=wd,
                                                                        use_skip_connection=skip,
                                                                        dropout_schedule=sched,
                                                                        clipnorm=clip,
                                                                        norm_layer=norm,
                                                                        use_quantile_head=q_head,
                                                                    )
                                                                )

    return combos
