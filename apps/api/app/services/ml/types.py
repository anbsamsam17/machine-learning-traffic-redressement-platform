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

    # Nouveau schema FCD HERE (cf. Etape1_MDL_TV.txt).
    # Inputs : 2 FCD + 4 distances (VL min/total + PL min/total) + 2 vitesses
    # + functional_class (categoriel).
    input_cols=[
        "TMJOFCDTV",
        "TMJOFCDPL",
        "avg_distance_m",
        "avg_speed_kmh",
        "truck_avg_min_distance_m",
        "truck_avg_speed_kmh",
        "functional_class",
    ],
    output_cols=["TxPen"],
    on_off_norm=[True, True, True, True, True, True, False],   # functional_class categoriel : pas de norm

    # Retrocompat des datasets historiques (Bordeaux : TMJATV/TMJAFCDTV/car_*/km).
    # Note unite : car_*_distance_km est en km, la cible m. La conversion est
    # supposee deja appliquee en amont (data_prep) si applicable.
    column_aliases={
        # FCD
        "TMJATV":    "TMJOFCDTV",
        "TMJAFCDTV": "TMJOFCDTV",
        "TMJFCDTV":  "TMJOFCDTV",
        "TMJAPL":    "TMJOFCDPL",
        "TMJAFCDPL": "TMJOFCDPL",
        "TMJFCDPL":  "TMJOFCDPL",
        # Capteurs (target)
        "TMJABCTV":  "TMJOBCTV",
        "TMJABCPL":  "TMJOBCPL",
        # TxPen
        "TxPenTVRef": "TxPen",
        # Vitesses
        "car_average_speed_kmh":   "avg_speed_kmh",
        "truck_average_speed_kmh": "truck_avg_speed_kmh",
        # Distances (unite : Lyon en m, Bordeaux en km — voir data_prep)
        "car_average_distance_km":       "avg_distance_m",
        "truck_min_average_distance_km": "truck_avg_min_distance_m",
        "truck_average_distance_km":     "truck_avg_distance_m",
        # Reseau
        "linkFC": "functional_class",
        "FC":     "functional_class",
    },

    target_col="TxPen",
    target_numerator_fcd="TMJOFCDTV",
    target_denominator_bc="TMJOBCTV",
    target_alias="TxPen",

    eval_predicted_col="TVr",
    eval_reference_col="TMJOBCTV",
    eval_numerator_fcd="TMJOFCDTV",

    mandatory_input_cols=["TMJOFCDTV", "TMJOFCDPL"],
    min_input_count=3,
    default_high_flow_threshold=1000.0,
)


# ── PL configuration ────────────────────────────────────────────────────────

PL_CONFIG = ModelTypeConfig(
    name="PL",

    input_cols=[
        "TMJOFCDPL",
        "avg_distance_m",
        "avg_speed_kmh",
        "truck_avg_min_distance_m",
        "truck_avg_speed_kmh",
        "functional_class",
    ],
    output_cols=["TxPenPL"],
    on_off_norm=[True, True, True, True, True, False],

    column_aliases={
        "TMJAPL":    "TMJOFCDPL",
        "TMJAFCDPL": "TMJOFCDPL",
        "TMJABCPL":  "TMJOBCPL",
        "TxPenPLRef": "TxPenPL",
        "car_average_speed_kmh":   "avg_speed_kmh",
        "truck_average_speed_kmh": "truck_avg_speed_kmh",
        "car_average_distance_km":       "avg_distance_m",
        "truck_min_average_distance_km": "truck_avg_min_distance_m",
        "linkFC": "functional_class",
        "FC":     "functional_class",
    },

    target_col="TxPenPL",
    target_numerator_fcd="TMJOFCDPL",
    target_denominator_bc="TMJOBCPL",
    target_alias="TxPenPL",

    eval_predicted_col="DPL",
    eval_reference_col="TMJOBCPL",
    eval_numerator_fcd="TMJOFCDPL",

    mandatory_input_cols=["TMJOFCDPL"],
    min_input_count=2,
    default_high_flow_threshold=500.0,
)
