"""Model type configurations for TV, PL, HPM and HPS pipelines.

Encapsulates every type-specific constant so the rest of the pipeline
is fully parametric on ``ModelTypeConfig``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Public literal alias so callers can statically type the scaler choice
# (used by normalize() and persisted in the artifact training_config).
ScalerType = Literal["standard", "robust"]

# Public literal alias enumerating every supported model kind. Downstream
# code can statically narrow by ``kind`` (e.g. dispatch HPM/HPS through the
# TV pipeline since they are mono-output TxPen-like targets).
ModelKind = Literal["TV", "PL", "HPM", "HPS"]


@dataclass(frozen=True)
class ModelTypeConfig:
    """Immutable descriptor for a model type (TV / PL / HPM / HPS)."""

    # --- identity ---
    name: str                       # "TV", "PL", "HPM" or "HPS"

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
    default_test_size: float             = 0.05
    default_high_flow_threshold: float   = 1000.0

    # --- P2A.4 / P2A.5 / P2B feature engineering defaults --------------------
    # All flags below are additive: defaults preserve pre-refactor behaviour
    # so existing tests / smoke scripts keep passing.

    # P2A.4: continuous weighting via log1p(TMJOBCTV) instead of the binary
    # flag_permanent / flag_recent_year. False -> original binary weighting.
    use_log_flow_weighting: bool = False
    # Column read for log flow weighting (capteur reference). Defaults to the
    # TV BC column; PL pipeline can override via config dict.
    log_flow_weighting_col: str = "TMJOBCTV"

    # --- Binary sample-weight defaults (rename of flag_comptage → flag_permanent)
    # Defaults preserve the pre-rename behaviour: no weighting unless the
    # caller explicitly opts in via the training config dict.
    default_use_flag_permanent_weighting: bool = False
    default_flag_priority_weight: float = 4.0

    # New: configurable recent-year boost. The "recent year" is auto-detected
    # at training time as the MAX value of ``year_mapped`` in the prepared
    # DataFrame (no hardcoded 2025). Default OFF.
    default_use_flag_recent_year_weighting: bool = False
    default_recent_year_priority_weight: float = 2.0

    # P2A.5: target transform log1p(TxPen). When True, y_train and y_valid
    # are log1p-transformed BEFORE normalization. Evaluation re-applies expm1.
    target_log_transform: bool = False

    # P2B.1: ratio feature TMJOFCDPL / max(TMJOFCDTV, 1) — kept ON by default
    # but only added when both source columns are present (silent skip
    # otherwise) so it cannot break upstream data flows.
    add_pl_tv_ratio: bool = True

    # P2B.2: list of columns to additionally expose as log1p(col) under the
    # name "log_<col>". Originals are NEVER dropped.
    log_transform_cols: list[str] = field(default_factory=list)

    # P2B.3: one-hot expansion for functional_class. When True, columns
    # fc_1..fc_5 replace the integer functional_class column.
    one_hot_functional_class: bool = False

    # P2B.5: scaler choice for normalize(). "standard" (mean/std, default
    # = unchanged behaviour) or "robust" (median, IQR/1.349).
    scaler: ScalerType = "standard"

    # P2B.7: learned categorical embedding for the year_mapped column. When
    # True, build_model() routes year_mapped through a small Embedding layer
    # instead of feeding it as a scalar through the Dense stack. Default
    # False preserves the legacy Sequential graph so previously trained
    # checkpoints keep loading without surprise.
    use_year_embedding: bool = False

    # --- P3 architecture defaults -------------------------------------------
    # All flags below are additive and default to the pre-P3 behavior so
    # existing tests / smoke scripts keep passing.

    # P3.1: optimizer choice + L2 weight decay (only used with AdamW).
    default_optimizer: Literal["adam", "adamw"] = "adam"
    default_weight_decay: float = 0.0

    # P3.3: input -> last-hidden skip connection (forces Functional API).
    default_use_skip_connection: bool = False

    # P3.4: dropout schedule across hidden layers.
    default_dropout_schedule: Literal["uniform", "decreasing"] = "uniform"

    # P3.5: optimizer gradient clipping (None = disabled, byte-identical to
    # the pre-P3 builder).
    default_clipnorm: float | None = None

    # P3.7: norm layer ("none" | "batch" | "layer"). When None, the legacy
    # `use_batch_norm` bool drives the behaviour (back-compat).
    default_norm_layer: Literal["none", "batch", "layer"] | None = None

    # P3.9: multi-quantile regression head (q=0.2/0.5/0.8 by default).
    default_use_quantile_head: bool = False
    default_quantiles: tuple[float, ...] = (0.2, 0.5, 0.8)

    # --- P4 training-pipeline defaults --------------------------------------
    # All flags below are additive and default to a no-op (backward compat).

    # P4.4: multi-seed runs. When > 1, each grid combo is trained `n_seeds`
    # times with seed = base_seed + run_idx*n_seeds + seed_idx so the
    # downstream ensemble can average/select across replicas. Allowed range
    # 1..10 (validated at runtime).
    default_n_seeds: int = 1

    # P4.5: hard-example mining. When True, every 10 epochs (after epoch 30)
    # samples with |pred - obs|/obs > 0.15 get their sample_weight multiplied
    # by 1.5 (compound boost capped at 3x). Mid-training side-effect echoed
    # in the artifact's training_config.
    default_use_hard_example_mining: bool = False

    # P4.6: curriculum learning (easy -> hard). When True, the model is first
    # trained on the lowest-50% TMJOBCTV rows for ceil(max_epochs*0.3)
    # epochs, then on the full training set for the remaining epochs. The
    # caller must pass a TMJOBCTV-like array via `flow_for_curriculum`;
    # otherwise the flag is silently disabled with a warning.
    default_use_curriculum: bool = False

    # --- HPM / HPS extension (additive; safe defaults for TV / PL) ----------
    # All fields below were introduced when HPM (Heure de Pointe Matin) and
    # HPS (Heure de Pointe Soir) were added as additional model kinds. They
    # are filled with sensible defaults for the historical TV / PL configs so
    # that no behavioural change occurs for legacy callers.

    # Canonical model kind. Defaults to ``name`` cast at construction (set
    # explicitly for HPM / HPS configs). Use this rather than ``name`` when
    # narrowing types via :data:`ModelKind`.
    kind: ModelKind | None = None

    # Human-readable label suitable for UI display. When None, callers
    # should fall back to ``name``.
    label: str | None = None

    # Direct FCD column for this kind (alias of ``target_numerator_fcd``
    # exposed under a uniform name across TV/PL/HPM/HPS). Optional — None
    # means "use target_numerator_fcd".
    fcd_col: str | None = None

    # Direct sensor/counter column for this kind (alias of
    # ``target_denominator_bc`` / ``eval_reference_col``). Optional.
    counter_col: str | None = None

    # Unit label for the predicted output column (``v/j`` for TV/PL daily,
    # ``v/h`` for HPM/HPS hourly).
    unit_label: str = "v/j"

    # Hour window (start_hour_inclusive, end_hour_exclusive) for peak-hour
    # kinds. None for non-peak kinds (TV/PL daily). HPM = (8, 9), HPS = (17, 18).
    hour_window: tuple[int, int] | None = None


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

    # HPM/HPS-extension metadata (kept here for uniformity across kinds).
    kind="TV",
    label="Tous Véhicules",
    fcd_col="TMJOFCDTV",
    counter_col="TMJOBCTV",
    unit_label="v/j",
    hour_window=None,
)


# ── PL configuration ────────────────────────────────────────────────────────
# Aligned with E3_09_all3_plus_after (Batch_MDL_PL_Compact4 winner) — tol 94,00 %
# / 658/700 capteurs, R² 0,9722, MAE 0,1657, GEH<5 99,86 % sur 700 lignes Grand
# Lyon (BCFCDREF_AllYears_PL_enriched, seed 1752). Voir
# documentation interne calibration_modele_PL §3.4. Les 3 features derivees
# (fcd_log, tv_pl_ratio, dist_to_lyon_center) sont calculees par
# scripts/enrich_fcdrefglobal.py et doivent etre presentes dans le DataFrame
# d'entree avant le training (sinon le router rejette le combo en silence).

PL_CONFIG = ModelTypeConfig(
    name="PL",

    input_cols=[
        "TMJOFCDPL",
        "functional_class",
        "truck_avg_distance_m",
        "truck_avg_min_distance_m",
        "truck_avg_distance_before_m",
        "truck_avg_distance_after_m",
        "fcd_log",
        "tv_pl_ratio",
        "dist_to_lyon_center",
    ],
    output_cols=["TxPenPL"],
    # functional_class est categoriel int 1-5 -> norm OFF ; les 8 autres
    # features sont continues z-scorees (mask [True, False, True*7]).
    on_off_norm=[True, False, True, True, True, True, True, True, True],

    column_aliases={
        "TMJAPL":    "TMJOFCDPL",
        "TMJAFCDPL": "TMJOFCDPL",
        "TMJABCPL":  "TMJOBCPL",
        "TxPenPLRef": "TxPenPL",
        "car_average_speed_kmh":   "avg_speed_kmh",
        "truck_average_speed_kmh": "truck_avg_speed_kmh",
        "car_average_distance_km":       "avg_distance_m",
        "truck_min_average_distance_km": "truck_avg_min_distance_m",
        "truck_average_distance_km":     "truck_avg_distance_m",
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
    # Recipe figee Compact4 : 5 couches deep, bs=64, ep=1500, lr=0.01, drp=0.015.
    default_min_nb_epochs=[1500],
    default_max_epochs=1500,
    default_batch_size=64,
    default_dropout=0.015,
    default_test_size=0.0,

    # HPM/HPS-extension metadata (kept here for uniformity across kinds).
    kind="PL",
    label="Poids Lourds",
    fcd_col="TMJOFCDPL",
    counter_col="TMJOBCPL",
    unit_label="v/j",
    hour_window=None,
)


# ── HPM configuration (Heure de Pointe Matin — 8h00-8h59) ───────────────────
# Single-hour TV-flavoured target. Reuses the TV feature stack since the
# upstream HERE network features (avg_speed_kmh, distances, functional_class)
# don't have an hourly variant in BCFCDREF_2025_HPM_HPS.geojson. Only the
# FCD/counter/target columns swap to their hourly siblings.

HPM_CONFIG = ModelTypeConfig(
    name="HPM",

    input_cols=[
        "FCD_HPM_TV",
        "TMJOFCDPL",
        "avg_distance_m",
        "avg_speed_kmh",
        "truck_avg_min_distance_m",
        "truck_avg_speed_kmh",
        "functional_class",
    ],
    output_cols=["TxPen_HPM"],
    on_off_norm=[True, True, True, True, True, True, False],

    column_aliases={
        # Hourly FCD aliases — accept legacy / shorthand names.
        "FCDTV_h08":      "FCD_HPM_TV",
        "FCDTV_HPM":      "FCD_HPM_TV",
        "FCD_HPM":        "FCD_HPM_TV",
        # TV daily aliases still useful for the shared inputs.
        "TMJAPL":         "TMJOFCDPL",
        "TMJAFCDPL":      "TMJOFCDPL",
        "TMJFCDPL":       "TMJOFCDPL",
        # Hourly counter aliases.
        "BCTV_HPM":       "TMJOBCTV_HPM",
        "TMJOBCTV_h08":   "TMJOBCTV_HPM",
        # Speeds / distances (shared with TV).
        "car_average_speed_kmh":         "avg_speed_kmh",
        "truck_average_speed_kmh":       "truck_avg_speed_kmh",
        "car_average_distance_km":       "avg_distance_m",
        "truck_min_average_distance_km": "truck_avg_min_distance_m",
        "truck_average_distance_km":     "truck_avg_distance_m",
        "linkFC": "functional_class",
        "FC":     "functional_class",
    },

    target_col="TxPen_HPM",
    target_numerator_fcd="FCD_HPM_TV",
    target_denominator_bc="TMJOBCTV_HPM",
    target_alias="TxPen_HPM",

    # Predicted column at evaluation time: HPM_FCDr (NEVER TVr — critical to
    # avoid downstream confusion with the daily TV pipeline).
    eval_predicted_col="HPM_FCDr",
    eval_reference_col="TMJOBCTV_HPM",
    eval_numerator_fcd="FCD_HPM_TV",

    mandatory_input_cols=["FCD_HPM_TV"],
    min_input_count=2,
    default_high_flow_threshold=80.0,  # ~ TV/12, peak-hour scale (v/h)

    # HPM/HPS-extension metadata.
    kind="HPM",
    label="Heure de Pointe Matin",
    fcd_col="FCD_HPM_TV",
    counter_col="TMJOBCTV_HPM",
    unit_label="v/h",
    hour_window=(8, 9),  # h08-h09 (8h00-8h59)
)


# ── HPS configuration (Heure de Pointe Soir — 17h00-17h59) ──────────────────

HPS_CONFIG = ModelTypeConfig(
    name="HPS",

    input_cols=[
        "FCD_HPS_TV",
        "TMJOFCDPL",
        "avg_distance_m",
        "avg_speed_kmh",
        "truck_avg_min_distance_m",
        "truck_avg_speed_kmh",
        "functional_class",
    ],
    output_cols=["TxPen_HPS"],
    on_off_norm=[True, True, True, True, True, True, False],

    column_aliases={
        # Hourly FCD aliases — accept legacy / shorthand names.
        "FCDTV_h17":      "FCD_HPS_TV",
        "FCDTV_HPS":      "FCD_HPS_TV",
        "FCD_HPS":        "FCD_HPS_TV",
        # TV daily aliases still useful for the shared inputs.
        "TMJAPL":         "TMJOFCDPL",
        "TMJAFCDPL":      "TMJOFCDPL",
        "TMJFCDPL":       "TMJOFCDPL",
        # Hourly counter aliases.
        "BCTV_HPS":       "TMJOBCTV_HPS",
        "TMJOBCTV_h17":   "TMJOBCTV_HPS",
        # Speeds / distances (shared with TV).
        "car_average_speed_kmh":         "avg_speed_kmh",
        "truck_average_speed_kmh":       "truck_avg_speed_kmh",
        "car_average_distance_km":       "avg_distance_m",
        "truck_min_average_distance_km": "truck_avg_min_distance_m",
        "truck_average_distance_km":     "truck_avg_distance_m",
        "linkFC": "functional_class",
        "FC":     "functional_class",
    },

    target_col="TxPen_HPS",
    target_numerator_fcd="FCD_HPS_TV",
    target_denominator_bc="TMJOBCTV_HPS",
    target_alias="TxPen_HPS",

    # Predicted column at evaluation time: HPS_FCDr (NEVER TVr — critical to
    # avoid downstream confusion with the daily TV pipeline).
    eval_predicted_col="HPS_FCDr",
    eval_reference_col="TMJOBCTV_HPS",
    eval_numerator_fcd="FCD_HPS_TV",

    mandatory_input_cols=["FCD_HPS_TV"],
    min_input_count=2,
    default_high_flow_threshold=80.0,

    # HPM/HPS-extension metadata.
    kind="HPS",
    label="Heure de Pointe Soir",
    fcd_col="FCD_HPS_TV",
    counter_col="TMJOBCTV_HPS",
    unit_label="v/h",
    hour_window=(17, 18),  # h17-h18 (17h00-17h59)
)


# ── Public registry ─────────────────────────────────────────────────────────

"""Config par mode ML.

Les modes HPM/HPS modélisent la pointe horaire (1h) du trafic VL :
- HPM = 8h00-8h59 (FCDTV_h08)
- HPS = 17h00-17h59 (FCDTV_h17)

Pas de variante PL pour HPM/HPS (couverture insuffisante des flottes PL en
pointe). Les configs partagent la stack de features de TV (vitesses /
distances HERE) car celles-ci ne disposent pas de variante horaire dans
``BCFCDREF_2025_HPM_HPS.geojson``.
"""
CONFIGS: dict[ModelKind, ModelTypeConfig] = {
    "TV":  TV_CONFIG,
    "PL":  PL_CONFIG,
    "HPM": HPM_CONFIG,
    "HPS": HPS_CONFIG,
}
