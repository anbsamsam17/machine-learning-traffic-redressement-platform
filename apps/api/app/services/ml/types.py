"""Model type configurations for TV and PL pipelines.

Encapsulates every type-specific constant so the rest of the pipeline
is fully parametric on ``ModelTypeConfig``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelTypeConfig:
    """Immutable descriptor for a model type (TV or PL)."""

    # --- identity ---
    name: str                       # "TV" or "PL"

    # --- columns ---
    input_cols: list[str]
    output_cols: list[str]
    on_off_norm: list[bool]

    # --- column aliases  (src -> dst) applied during prepare_training_data ---
    column_aliases: dict[str, str]

    # --- target derivation ---
    #   For TV: TxPenTVRef = TMJAFCDTV / TMJABCTV * 100
    #   For PL: TxPenPLRef = TMJAFCDPL / TMJABCPL * 100
    target_col: str                 # output column name (TxPenTVRef / TxPenPLRef)
    target_numerator_fcd: str       # TMJAFCDTV / TMJAFCDPL
    target_denominator_bc: str      # TMJABCTV  / TMJABCPL
    target_alias: str               # short alias ("TxPen" / "TxPenPL")

    # --- evaluation ---
    #   TVr = TMJAFCDTV / TxPen_pred * 100   (TV)
    #   DPL = TMJAFCDPL / TxPen_pred * 100   (PL)
    eval_predicted_col: str         # "TVr" / "DPL"
    eval_reference_col: str         # "TMJABCTV" / "TMJABCPL"
    eval_numerator_fcd: str         # "TMJAFCDTV" / "TMJAFCDPL"

    # --- grid search defaults ---
    mandatory_input_cols: list[str]
    min_input_count: int
    default_activations: list[str]       = field(default_factory=lambda: ["elu"])
    default_learning_rates: list[float]  = field(default_factory=lambda: [0.01])
    default_min_nb_epochs: list[int]     = field(default_factory=lambda: [500, 1000])
    default_max_epochs: int              = 2050
    default_batch_size: int              = 256
    default_dropout: float               = 0.05
    default_test_size: float             = 0.0
    default_high_flow_threshold: float   = 1000.0


# ── TV configuration ────────────────────────────────────────────────────────

TV_CONFIG = ModelTypeConfig(
    name="TV",

    input_cols=[
        "TMJAFCDTV",
        "TMJAFCDPL",
        "car_average_distance_km",
        "car_average_speed_kmh",
        "truck_min_average_distance_km",
        "truck_average_speed_kmh",
    ],
    output_cols=["TxPenTVRef"],
    on_off_norm=[True, True, True, True, True, True],

    column_aliases={
        "TMJATV":  "TMJAFCDTV",
        "TMJFCDTV": "TMJAFCDTV",
        "TMJAPL":  "TMJAFCDPL",
        "TMJAVL":  "TMJAFCDVL",
        "TxPen":   "TxPenTVRef",
    },

    target_col="TxPenTVRef",
    target_numerator_fcd="TMJAFCDTV",
    target_denominator_bc="TMJABCTV",
    target_alias="TxPen",

    eval_predicted_col="TVr",
    eval_reference_col="TMJABCTV",
    eval_numerator_fcd="TMJAFCDTV",

    mandatory_input_cols=["TMJAFCDTV", "TMJAFCDPL"],
    min_input_count=3,
    default_high_flow_threshold=1000.0,
)


# ── PL configuration ────────────────────────────────────────────────────────

PL_CONFIG = ModelTypeConfig(
    name="PL",

    input_cols=[
        "TMJAFCDPL",
        "car_average_distance_km",
        "car_average_speed_kmh",
        "truck_min_average_distance_km",
        "truck_average_speed_kmh",
    ],
    output_cols=["TxPenPLRef"],
    on_off_norm=[True, True, True, True, True],

    column_aliases={
        "TMJAPL": "TMJAFCDPL",
        "TMJAVL": "TMJAFCDVL",
        "TxPenPL": "TxPenPLRef",
    },

    target_col="TxPenPLRef",
    target_numerator_fcd="TMJAFCDPL",
    target_denominator_bc="TMJABCPL",
    target_alias="TxPenPL",

    eval_predicted_col="DPL",
    eval_reference_col="TMJABCPL",
    eval_numerator_fcd="TMJAFCDPL",

    mandatory_input_cols=["TMJAFCDPL"],
    min_input_count=2,
    default_high_flow_threshold=500.0,
)
