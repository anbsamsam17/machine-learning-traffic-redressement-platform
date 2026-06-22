"""Carte router — generate carte de debits (apply TV+PL models on FCD data).

Reproduces the full logic from the Streamlit page 8_Generation_Carte_Debits.py:
  load TV model + PL model + FCD data -> map columns -> predict TxPen ->
  compute JOr, DPL, confidence intervals -> filter -> round -> GeoJSON.

Naming note: la grandeur "TV redresse journalier" est exposee sous le nom
``JOr`` (= Journalier Ouvre redresse, cf ARRONDI_PROGRESSIF_specs.md et
LIVRABLE_2025_specs.md). Les anciennes versions du code utilisaient ``TVr``;
la migration est faite ici (cf changelog 2026-05).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from pydantic import BaseModel, Field, model_validator

from ..auth import UserRecord, get_current_user, require_owned_session
from ..config import get_settings
from ..rate_limit import limit_carte_generate
from ..security import validate_path

from ..session import session_manager

# Helpers extracted into dedicated service modules (cf refonte pre-execution).
# Re-exported as module-level names below to preserve the public surface of
# carte.py for any code that might import these helpers directly.
from ..services.geo import (
    _calculate_heading,
    _parse_and_heading as _parse_and_heading_helper,
    _parse_geom_shapely,
    _round_coords as _round_coords_helper,
)
from ..services.ml.saturation import (
    DEFAULT_ALPHA_FC,
    DEFAULT_ALPHA_FC_MIN,
    DEFAULT_ALPHA_HPM_FC,
    DEFAULT_ALPHA_HPS_FC,
    DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
    DEFAULT_ALPHA_PHYSIQUE_MAX,
    DEFAULT_ANNEE_CAPTEURS,
    DEFAULT_BORNE_HPM_FC,
    DEFAULT_BORNE_HPS_FC,
    DEFAULT_BORNES_FC,
    DEFAULT_BORNES_FC_ABS,
    DEFAULT_BUFFER_ZONE_CRITIQUE_M,
    DEFAULT_RATIO_CAPTEUR_CRITIQUE,
    DEFAULT_RATIO_MACRO_PEN,
    DEFAULT_SEUIL_VOL_FCD_TV,
    _alpha_adaptatif,
    _alpha_v3,
    _detecter_zones_critiques,
    _saturer_hierarchique,
    _saturer_horaire_hierarchique,
    _saturer_pl_hierarchique,
)
from ..services.ml.rounding import (
    _appliquer_arrondi_avec_coherence,
    _calculer_DPLmax,
    _calculer_DPLmin,
    _round_progressive,
)
from ..services.ml.inference import (
    _apply_year_mapping,
    _ensure_hourly_fcd_column,
    _load_model,
    _my_denorm,
    _my_norm,
    _normalize_input_cols,
    _peak_hour_err_pct,
    _predict_peak_hour as _predict_peak_hour_impl,
    release_tf_model,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/carte", tags=["carte"])


# ---------------------------------------------------------------------------
# Re-exports : les fonctions ML / arrondi / geo vivent desormais dans des
# services dedies (cf imports ci-dessus). Les definitions sont preservees
# sous forme d'imports pour ne pas casser un eventuel client externe qui
# referencerait ``app.routers.carte._foo`` directement (et pour permettre le
# remplacement en monkey-patch dans les tests).
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ErrorThresholds(BaseModel):
    # IC JOr par defaut (tranches de debit JOr v/j) : 20 / 15 / 15 / 10 %.
    err_0_1000: float = 0.20
    err_1000_2000: float = 0.15
    err_2000_4000: float = 0.15
    err_4000_plus: float = 0.10


class PeakHourErrorThresholds(BaseModel):
    """Confidence-interval thresholds for HPM/HPS peak-hour predictions.

    Unit is **v/h** (vehicules par heure), distinct from the daily v/j ranges
    used by ``ErrorThresholds`` (TV / PL). Tranches recalibrated per the D2
    validation: 0-100 = 25%, 100-300 = 18%, 300-600 = 18%, >600 = 14%.
    """

    err_0_100: float = 25.0
    err_100_300: float = 18.0
    err_300_600: float = 18.0
    err_600_plus: float = 14.0


class CarteGenerateRequest(BaseModel):
    session_id: str
    model_tv_dir: str
    # Modele PL OPTIONNEL (comme HPM/HPS). Quand falsy (None/""/whitespace),
    # le modele PL n'est PAS charge et aucune colonne derivee du PL n'est
    # produite (DPL/DPLmin/DPLmax/PLr*/PLred/VLred). Le frontend envoie null
    # quand pas de modele PL. None => pipeline TV-seul (+HPM/HPS si fournis).
    model_pl_dir: str | None = None
    # Optional peak-hour models (D3): each is independent. When None, the
    # corresponding PM / PS columns are not produced (zero behavioural change
    # vs. the legacy TV+PL-only pipeline).
    model_hpm_dir: str | None = None
    model_hps_dir: str | None = None
    column_mapping: dict[str, str | None] = Field(
        default_factory=dict,
        description="Mapping: target_col -> source_col in data (None = skip)",
    )
    filter_tvr_enabled: bool = True
    filter_tvr_value: int = 100
    filter_fc_enabled: bool = True
    error_thresholds: ErrorThresholds = Field(default_factory=ErrorThresholds)
    # IC tranches v/h pour les modeles HPM/HPS (D2). Independent from
    # ``error_thresholds`` (which stays in v/j for TV/PL).
    err_pm_thresholds: PeakHourErrorThresholds = Field(default_factory=PeakHourErrorThresholds)
    err_ps_thresholds: PeakHourErrorThresholds = Field(default_factory=PeakHourErrorThresholds)

    # Overrides annee fournis par le body (UI). Quand non-None, ils PRIMENT sur
    # le training_config du modele (priorite body > config) :
    #   - year_column_name   override config["year_column_name"] (defaut "Annee")
    #   - year_value_mapping override config["year_value_mapping"]
    # La resolution finale est faite dans services.ml.inference._apply_year_mapping
    # (qui prend ces overrides en kwargs). Memes overrides pour TV / PL / HPM /
    # HPS : une seule source annee cote UI. None => comportement legacy (config).
    year_column_name: str | None = None
    year_value_mapping: dict[str, float] | None = None

    # PL saturation hierarchique v2 hybride adaptative (cf SATURATION_PL_specs.md
    # v2.0). Active par defaut — pour reproduire l'ancien comportement
    # non-sature, passer ``pl_saturation_enabled=False``. La v2 utilise un
    # ratio adaptatif base sur TMJOFCDPL/TMJOFCDTV ; si ces colonnes ne sont
    # pas disponibles, fallback gracieux sur le plancher FC (= v1).
    pl_saturation_enabled: bool = Field(
        default=True,
        description=(
            "Activer la saturation PL v2 hybride (cap absolu FC + ratio "
            "adaptatif base FCD)."
        ),
    )
    bornes_fc_abs: dict[int, float] = Field(
        default_factory=lambda: {1: 15000, 2: 5000, 3: 3000, 4: 1500, 5: 800},
        description="Cap absolu PL/j par classe fonctionnelle HERE (1-5) — v2.",
    )
    alpha_fc_min: dict[int, float] = Field(
        default_factory=lambda: {1: 0.35, 2: 0.25, 3: 0.18, 4: 0.15, 5: 0.12},
        description=(
            "Plancher du ratio PL/TV par classe FC HERE (1-5) — v2 hybride. "
            "Jamais en dessous de ces valeurs (= bornes v1)."
        ),
    )
    # Hyperparametres v2 (cf SATURATION_PL_specs.md section "Parametres valides").
    ratio_macro_pen: float = Field(
        default=1.137,
        gt=0,
        description=(
            "Ratio macro penetration mean(TxPenTV)/mean(TxPenPL) — corrige le "
            "biais de penetration global entre flottes FCD (cal 991 capteurs "
            "Lyon 2025)."
        ),
    )
    alpha_physique_max: float = Field(
        default=0.55,
        gt=0,
        le=1.0,
        description=(
            "Plafond biomecanique du ratio PL/TV (au-dela = aberration ; cap "
            "CEREMA). Les carrieres 99 % sont traitees par override metier."
        ),
    )
    seuil_vol_fcd_tv: float = Field(
        default=50.0,
        ge=0,
        description=(
            "Seuil minimum TMJFCDTV (v/j) en dessous duquel on bascule sur le "
            "plancher FC (fallback : evite l'explosion numerique sur faibles "
            "volumes FCD)."
        ),
    )

    # Hyperparametres v3 — override zones critiques (cf SATURATION_PL_specs.md
    # v3.0 section "Hyperparametres v3"). Active par defaut (D2). Si capteurs
    # SIREDO absents et FCD present -> fallback silencieux v2 + log INFO (D3).
    zone_critique_enabled: bool = Field(
        default=True,
        description=(
            "Activer l'override v3 zones critiques (buffer 1 km autour des "
            "capteurs SIREDO PL avec ratio observe > 15 %)."
        ),
    )
    capteurs_pl_session_id: str | None = Field(
        default=None,
        description=(
            "Session ID de l'upload des capteurs SIREDO PL "
            "(BCFCDREF_AllYears_PL.geojson). Si fourni et fichier present, "
            "active la branche v3 ; sinon fallback silencieux v2 (cf D3)."
        ),
    )
    annee_capteurs: int = Field(
        default=2025,
        ge=1900,
        le=2100,
        description="Annee de reference pour filtrer les capteurs SIREDO.",
    )
    ratio_capteur_critique: float = Field(
        default=0.15,
        ge=0,
        le=1.0,
        description=(
            "Seuil de ratio observe (TMJOBCPL/TMJOBCTV) au-dela duquel un "
            "capteur est considere critique (typiquement 0.15 = bien au-dela "
            "de la mediane 7 %)."
        ),
    )
    buffer_zone_critique_m: float = Field(
        default=1000.0,
        ge=0,
        description=(
            "Rayon du buffer en metres (EPSG:2154) autour des capteurs "
            "critiques. Typiquement 1 km (zone d'influence physique)."
        ),
    )
    alpha_min_zone_critique: float = Field(
        default=0.30,
        ge=0,
        le=1.0,
        description=(
            "Plancher local du ratio PL/TV dans les zones critiques (vs "
            "0.12-0.18 selon FC en v2)."
        ),
    )

    # Alias retro-compat v1 (deprecated) — si un ancien client envoie ces
    # noms, ils sont mappes silencieusement sur les noms v2 via le
    # ``model_validator`` ci-dessous. Garde la compatibilite ascendante des
    # appels HTTP existants (eviter les 422 inutiles).
    bornes_fc: dict[int, float] | None = Field(
        default=None,
        description="(deprecated v1, utiliser bornes_fc_abs)",
    )
    alpha_fc: dict[int, float] | None = Field(
        default=None,
        description="(deprecated v1, utiliser alpha_fc_min)",
    )

    @model_validator(mode="after")
    def _map_v1_to_v2(self) -> "CarteGenerateRequest":  # noqa: D401
        """Bridge v1 field names (bornes_fc / alpha_fc) -> v2 (bornes_fc_abs /
        alpha_fc_min) silencieusement. Les valeurs v2 explicites gardent la
        priorite si elles different des defaults.
        """
        # On ne remplace les v2 par les v1 que si les v2 sont aux defaults
        # (sinon l'appelant a explicitement fixe les v2 et on respecte).
        _default_bornes = {1: 15000, 2: 5000, 3: 3000, 4: 1500, 5: 800}
        _default_alpha = {1: 0.35, 2: 0.25, 3: 0.18, 4: 0.15, 5: 0.12}
        if self.bornes_fc is not None and self.bornes_fc_abs == _default_bornes:
            object.__setattr__(self, "bornes_fc_abs", dict(self.bornes_fc))
        if self.alpha_fc is not None and self.alpha_fc_min == _default_alpha:
            object.__setattr__(self, "alpha_fc_min", dict(self.alpha_fc))
        return self

    # HPM saturation hierarchique (cf SATURATION_HPM_HPS_specs.md). Active par
    # defaut quand un modele HPM est fourni — sinon no-op silencieux. Pour
    # reproduire l'ancien comportement non-sature, passer hpm_saturation_enabled=False.
    hpm_saturation_enabled: bool = Field(
        default=True,
        description="Activer la saturation hierarchique du HPM (PM/PMmin/PMmax).",
    )
    borne_hpm_fc: dict[int, float] = Field(
        default_factory=lambda: {1: 5000, 2: 7000, 3: 4000, 4: 1500, 5: 700},
        description="Cap dur PM (val/h) par classe fonctionnelle HERE (1-5).",
    )
    alpha_hpm_fc: dict[int, float] = Field(
        default_factory=lambda: {1: 0.10, 2: 0.18, 3: 0.16, 4: 0.18, 5: 0.18},
        description="Ratio max PM/JOr par classe fonctionnelle HERE (1-5).",
    )

    # HPS saturation hierarchique (cf SATURATION_HPM_HPS_specs.md). Symetrique
    # de HPM ; alpha_HPS_FC4=0.20 plus eleve pour preserver les segments a
    # pointe soir tres marquee (retours scolaires / livraisons).
    hps_saturation_enabled: bool = Field(
        default=True,
        description="Activer la saturation hierarchique du HPS (PS/PSmin/PSmax).",
    )
    borne_hps_fc: dict[int, float] = Field(
        default_factory=lambda: {1: 5000, 2: 7000, 3: 4000, 4: 1500, 5: 800},
        description="Cap dur PS (val/h) par classe fonctionnelle HERE (1-5).",
    )
    alpha_hps_fc: dict[int, float] = Field(
        default_factory=lambda: {1: 0.12, 2: 0.15, 3: 0.15, 4: 0.20, 5: 0.15},
        description="Ratio max PS/JOr par classe fonctionnelle HERE (1-5).",
    )

    # Arrondi progressif Option B (cf ARRONDI_PROGRESSIF_specs.md). Applique
    # POST-saturation sur (JOr, DPL, PM, PS) et leurs min/max ; preserve la
    # coherence ordinale. Active par defaut : pour l'ancien comportement
    # (arrondi multiple-de-10 systematique), passer False.
    arrondi_progressif_enabled: bool = Field(
        default=True,
        description=(
            "Arrondi progressif des valeurs trafic "
            "(Option B : <100->x5, <1000->x10, >=1000->x100)."
        ),
    )


class CarteStats(BaseModel):
    total_segments: int
    filtered_segments: int
    # Renames internes TVr -> JOr (cf module docstring) ; le champ API conserve
    # son nom historique ``mean_tvr`` pour compat front-end (le label UI parle
    # deja de "JOr moyen"). On l'alimente desormais a partir de prod["JOr"].
    mean_tvr: float | None = None
    mean_dpl: float | None = None


class CarteGenerateResponse(BaseModel):
    session_id: str
    stats: CarteStats
    geojson_feature_count: int


class ModelValidateRequest(BaseModel):
    model_dir: str
    # A5/SECURITY : confiner ``model_dir`` a un workspace autorise. Le flux UI
    # normal passe un model_dir situe sous WORKSPACE_ROOT/{session_id}/
    # (cf upload-model). Quand ``session_id`` est fourni, on verifie la
    # propriete de la session puis on refuse tout chemin qui sort de ce
    # workspace (path traversal / lecture FS arbitraire). Sans session_id
    # (legacy), on confine au WORKSPACE_ROOT global via validate_path.
    session_id: str | None = None


class ModelValidateResponse(BaseModel):
    valid: bool
    missing_files: list[str]
    training_config: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Helpers — IC dynamique JOr (specifique au routeur carte)
# ---------------------------------------------------------------------------
#
# _my_norm / _my_denorm / _apply_year_mapping / _calculate_heading sont
# desormais importes depuis ``services.ml.inference`` et ``services.geo``
# (cf imports en tete de module).

def _erreur_pourcentage(jor: float, thresholds: ErrorThresholds) -> float:
    """Dynamic error % based on JOr (TV redresse journalier) thresholds."""
    if jor > 4000:
        return thresholds.err_4000_plus
    elif jor > 2000:
        return thresholds.err_2000_4000
    elif jor > 1000:
        return thresholds.err_1000_2000
    else:
        return thresholds.err_0_1000


# _calculer_DPLmin / _calculer_DPLmax / _load_model sont importes depuis
# ``services.ml.rounding`` et ``services.ml.inference`` (cf imports en tete
# de module). Voir saturation.py / rounding.py / inference.py.


def _verify_model_structure(model_path: str) -> tuple[bool, list[str], dict | None]:
    """Verify model directory has all required files. Returns (valid, missing, config).

    C4: accept either the new model.keras artefact or the legacy
    NNarchitecture.json + NNweights{.weights}.h5 pair.
    """
    p = Path(model_path)
    has_native = (p / "model.keras").exists()

    missing: list[str] = []
    if not (p / "NNnormCoefficients.json").exists():
        missing.append("NNnormCoefficients.json")

    if not has_native:
        if not (p / "NNarchitecture.json").exists():
            missing.append("NNarchitecture.json")
        if not any((p / w).exists() for w in ("NNweights.h5", "NNweights.weights.h5")):
            missing.append("NNweights.h5")

    config = None
    config_file = p / "training_config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load training_config.json at %s: %s", config_file, exc)

    return len(missing) == 0, missing, config


# Source-side -> canonical mapping.
#
# Renames columns coming from FCDREFGLOBAL parquet (and other source formats)
# to the official compteur reference names. No unit conversion is applied —
# distances are expected in meters in the source parquet directly.
SOURCE_TO_CANONICAL = {
    # FCDREFGLOBAL parquet → noms canoniques officiels
    "TMJFCDTV": "TMJOFCDTV",  # the O was missing
    "TMJFCDPL": "TMJOFCDPL",
    "FUNC_CLASS": "functional_class",
    "Annee": "annee",
    "car_average_speed_kmh": "avg_speed_kmh",
    "truck_average_speed_kmh": "truck_avg_speed_kmh",
    "car_average_distance_km": "avg_distance_m",
    "car_min_average_distance_km": "avg_min_distance_m",
    "car_average_distance_before_km": "avg_distance_before_m",
    "car_average_distance_after_km": "avg_distance_after_m",
    "truck_average_distance_km": "truck_avg_distance_m",
    "truck_min_average_distance_km": "truck_avg_min_distance_m",
    "truck_average_distance_before_km": "truck_avg_distance_before_m",
    "truck_average_distance_after_km": "truck_avg_distance_after_m",
    # FCDREFGLOBAL livre les distances en METRES (suffixe _m) — pas _km. On
    # mappe donc aussi les noms _m natifs vers les noms canoniques attendus par
    # les modeles (evite un mapping manuel systematique cote UI).
    "car_average_distance_m": "avg_distance_m",
    "car_min_average_distance_m": "avg_min_distance_m",
    "car_average_distance_before_m": "avg_distance_before_m",
    "car_average_distance_after_m": "avg_distance_after_m",
    "truck_average_distance_m": "truck_avg_distance_m",
    "truck_min_average_distance_m": "truck_avg_min_distance_m",
    "truck_average_distance_before_m": "truck_avg_distance_before_m",
    "truck_average_distance_after_m": "truck_avg_distance_after_m",
    # AgregId variants
    "agregId": "AgregId",
}


# Legacy column names (used by older training_config.json or hand-mapped data)
# that need to be silently bridged to the official canonical names.
LEGACY_RETROCOMPAT = {
    "TMJATV": "TMJOFCDTV",
    "TMJAPL": "TMJOFCDPL",
    "TMJAFCDTV": "TMJOFCDTV",
    "TMJAFCDPL": "TMJOFCDPL",
    "linkFC": "functional_class",
}


def _normalize_source_columns(data: pd.DataFrame) -> pd.DataFrame:
    """Rename source-side columns (FCDREFGLOBAL parquet etc.) to canonical names.

    Only renames columns that are present in the DataFrame. No unit conversion
    is performed — the source parquet is expected to already be in meters for
    distance columns.
    """
    present_renames = {src: dst for src, dst in SOURCE_TO_CANONICAL.items() if src in data.columns}
    if present_renames:
        data = data.rename(columns=present_renames)
    return data


def _apply_column_aliases(data: pd.DataFrame) -> pd.DataFrame:
    """Bridge legacy column names to canonical ones (silent retrocompat).

    If a legacy column (e.g. ``TMJATV``, ``linkFC``) is present but the
    canonical name (e.g. ``TMJOFCDTV``, ``functional_class``) is missing,
    the canonical column is materialised by copying the legacy one. Both
    columns are kept so that downstream code referencing either naming
    keeps working.
    """
    found_legacy = []
    for legacy_name, canonical_name in LEGACY_RETROCOMPAT.items():
        if legacy_name in data.columns and canonical_name not in data.columns:
            data[canonical_name] = data[legacy_name]
            found_legacy.append(f"{legacy_name}->{canonical_name}")
    if found_legacy:
        logger.info("Legacy column aliases applied: %s", ", ".join(found_legacy))
    return data


# _normalize_input_cols, _peak_hour_err_pct, _ensure_hourly_fcd_column,
# _predict_peak_hour (impl) sont importes depuis ``services.ml.inference``
# (cf imports en tete de module). On expose ici un mince wrapper qui injecte
# les helpers ``_normalize_source_columns`` / ``_apply_column_aliases`` —
# ces deux derniers restent locaux a carte.py car ils dependent des tables
# SOURCE_TO_CANONICAL / LEGACY_RETROCOMPAT specifiques au routeur.


async def _predict_peak_hour(
    *,
    raw_df: pd.DataFrame,
    rename_dict: dict[str, str],
    model_dir: str,
    kind: str,
    canonical_fcd: str,
    fcd_aliases: tuple[str, ...],
    fallback_input_cols: list[str],
    year_column_override: str | None = None,
    year_mapping_override: dict | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Run a peak-hour model (HPM/HPS) and return (TxPen_pred, debit_v_per_h).

    Thin wrapper that delegates to
    :func:`app.services.ml.inference._predict_peak_hour_impl`, injecting the
    router-specific column-normalisation helpers.

    ``year_column_override`` / ``year_mapping_override`` (None par defaut =>
    comportement legacy) sont propages a ``_apply_year_mapping`` cote impl,
    pour aligner HPM/HPS sur les memes overrides annee que TV/PL.
    """
    return await _predict_peak_hour_impl(
        raw_df=raw_df,
        rename_dict=rename_dict,
        model_dir=model_dir,
        kind=kind,
        canonical_fcd=canonical_fcd,
        fcd_aliases=fcd_aliases,
        fallback_input_cols=fallback_input_cols,
        normalize_source_columns=_normalize_source_columns,
        apply_column_aliases=_apply_column_aliases,
        year_column_override=year_column_override,
        year_mapping_override=year_mapping_override,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/validate-model", response_model=ModelValidateResponse)
async def validate_model(
    body: ModelValidateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> ModelValidateResponse:
    """Validate that a model directory contains all required files.

    A5/SECURITY : ``model_dir`` est confine au workspace autorise. Quand
    ``session_id`` est fourni, le chemin doit vivre sous
    WORKSPACE_ROOT/{session_id}/ (et la session doit appartenir au caller) ;
    sinon on confine au WORKSPACE_ROOT global. Un chemin qui sort du root
    autorise leve une 403 (cf validate_path) — empeche la lecture FS
    arbitraire (ex: model_dir=/etc).
    """
    settings = get_settings()
    if body.session_id:
        # Verifie la propriete de la session AVANT de toucher au FS.
        require_owned_session(body.session_id, current_user)
        allowed_root = Path(settings.WORKSPACE_ROOT) / body.session_id
    else:
        allowed_root = Path(settings.WORKSPACE_ROOT)

    # Leve 400 (chemin malforme) / 403 (sort du root autorise).
    resolved = validate_path(body.model_dir, allowed_root=allowed_root)

    if not resolved.exists() or not resolved.is_dir():
        return ModelValidateResponse(valid=False, missing_files=["(dossier introuvable)"])

    valid, missing, config = _verify_model_structure(str(resolved))
    return ModelValidateResponse(valid=valid, missing_files=missing, training_config=config)


class CarteModelUploadResponse(BaseModel):
    model_dir: str
    valid: bool
    missing_files: list[str]
    training_config: dict[str, Any] | None = None


# Accepted carte model types (TV / PL daily + HPM / HPS peak-hour). HPM and
# HPS are additive: legacy callers that only pass "tv" / "pl" keep working.
_CARTE_MODEL_TYPES = ("tv", "pl", "hpm", "hps")


@router.post("/upload-model", response_model=CarteModelUploadResponse)
async def upload_carte_model(
    file: UploadFile = File(..., description="Fichier ZIP contenant le dossier du modele"),
    session_id: str = Form(..., description="Session ID"),
    model_type: str = Form(..., description="Type de modele: tv, pl, hpm ou hps"),
    current_user: UserRecord = Depends(get_current_user),
) -> CarteModelUploadResponse:
    """Upload a model ZIP for carte generation (TV, PL, HPM or HPS).

    Extracts into WORKSPACE_ROOT/{session_id}/carte_models/{model_type}/ and validates.
    """
    require_owned_session(session_id, current_user)

    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Le fichier doit etre un .zip")

    if model_type.lower() not in _CARTE_MODEL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"model_type doit etre dans {_CARTE_MODEL_TYPES}",
        )

    settings = get_settings()
    dest_dir = Path(settings.WORKSPACE_ROOT) / session_id / "carte_models" / model_type.lower()
    # Clean existing content
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    buf = io.BytesIO(contents)
    if not zipfile.is_zipfile(buf):
        raise HTTPException(status_code=400, detail="Le fichier n'est pas un ZIP valide.")

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        for name in zf.namelist():
            if ".." in name or name.startswith("/") or name.startswith("\\"):
                raise HTTPException(status_code=400, detail=f"Chemin invalide dans le ZIP: {name}")
        zf.extractall(dest_dir)

    # Remove __MACOSX
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Find the actual model directory — could be dest_dir itself, or a subfolder
    model_dir = dest_dir
    if not (model_dir / "NNarchitecture.json").exists():
        # Check one level deeper
        for child in model_dir.iterdir():
            if child.is_dir() and (child / "NNarchitecture.json").exists():
                model_dir = child
                break

    valid, missing, config = _verify_model_structure(str(model_dir))

    # Cross-check the declared model_type against the artefact's
    # training_config.json:model_kind (when present). Mismatch is a soft
    # warning — the upload still succeeds — because the user can deliberately
    # repurpose a model (e.g. retrain TV slot with an HPM artefact).
    if config:
        declared_kind = (config.get("model_kind") or "").upper()
        expected_kind = model_type.upper()
        if declared_kind and declared_kind != expected_kind:
            logger.warning(
                "Carte model upload kind mismatch: slot=%s, training_config model_kind=%s",
                expected_kind, declared_kind,
            )

    logger.info("Carte model upload (%s): valid=%s, dir=%s", model_type, valid, model_dir)

    return CarteModelUploadResponse(
        model_dir=str(model_dir),
        valid=valid,
        missing_files=missing,
        training_config=config,
    )


@router.post("/upload-model-folder", response_model=CarteModelUploadResponse)
async def upload_carte_model_folder(
    files: list[UploadFile] = File(..., description="Fichiers du dossier de modele (via webkitdirectory)"),
    session_id: str = Form(..., description="Session ID"),
    model_type: str = Form(..., description="Type de modele: tv, pl, hpm ou hps"),
    current_user: UserRecord = Depends(get_current_user),
) -> CarteModelUploadResponse:
    """Upload model files from a folder selection (webkitdirectory) for carte generation.

    Each file's ``filename`` contains its relative path. The endpoint reconstructs
    the tree under WORKSPACE_ROOT/{session_id}/carte_models/{model_type}/ and
    validates the model structure.
    """
    require_owned_session(session_id, current_user)

    if model_type.lower() not in _CARTE_MODEL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"model_type doit etre dans {_CARTE_MODEL_TYPES}",
        )

    settings = get_settings()
    dest_dir = Path(settings.WORKSPACE_ROOT) / session_id / "carte_models" / model_type.lower()
    # Clean existing content
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for upload_file in files:
        if not upload_file.filename:
            continue
        rel = upload_file.filename.replace("\\", "/").lstrip("/")
        if ".." in rel:
            raise HTTPException(status_code=400, detail=f"Chemin invalide: {rel}")

        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        contents = await upload_file.read()
        target.write_bytes(contents)

    logger.info("Carte model folder upload (%s): wrote %d files to %s", model_type, len(files), dest_dir)

    # Remove macOS artefacts
    macosx = dest_dir / "__MACOSX"
    if macosx.exists():
        shutil.rmtree(macosx, ignore_errors=True)

    # Find the actual model directory
    model_dir = dest_dir
    if not (model_dir / "NNarchitecture.json").exists():
        # Check one level deeper
        for child in model_dir.iterdir():
            if child.is_dir() and (child / "NNarchitecture.json").exists():
                model_dir = child
                break
        else:
            # Check two levels deep
            for child in dest_dir.iterdir():
                if child.is_dir():
                    for grandchild in child.iterdir():
                        if grandchild.is_dir() and (grandchild / "NNarchitecture.json").exists():
                            model_dir = grandchild
                            break
                    if (model_dir / "NNarchitecture.json").exists():
                        break

    valid, missing, config = _verify_model_structure(str(model_dir))

    # Soft model_kind sanity-check (cf. upload-model). Mismatch -> warning only.
    if config:
        declared_kind = (config.get("model_kind") or "").upper()
        expected_kind = model_type.upper()
        if declared_kind and declared_kind != expected_kind:
            logger.warning(
                "Carte model folder upload kind mismatch: slot=%s, training_config model_kind=%s",
                expected_kind, declared_kind,
            )

    logger.info("Carte model folder upload (%s): valid=%s, dir=%s", model_type, valid, model_dir)

    return CarteModelUploadResponse(
        model_dir=str(model_dir),
        valid=valid,
        missing_files=missing,
        training_config=config,
    )


class CapteursPLUploadResponse(BaseModel):
    """Reponse de l'upload des capteurs SIREDO PL pour la saturation v3."""

    session_id: str
    n_capteurs: int
    annees_disponibles: list[int]
    path: str


@router.post("/upload-capteurs-pl", response_model=CapteursPLUploadResponse)
async def upload_capteurs_pl(
    session_id: str = Form(..., description="Session ID"),
    file: UploadFile = File(..., description="GeoJSON BCFCDREF_AllYears_PL"),
    current_user: UserRecord = Depends(get_current_user),
) -> CapteursPLUploadResponse:
    """Upload des capteurs SIREDO PL pour la saturation v3 (override zones critiques).

    Cf SATURATION_PL_specs.md v3.0 + D1 (dropzone optionnelle dans /carte).

    Format attendu : GeoJSON Point en WGS84 (EPSG:4326), avec au moins les
    colonnes ``TMJOBCPL``, ``TMJOBCTV`` et ``annee``. Le fichier reference
    canonique est ``BCFCDREF_AllYears_PL.geojson`` (709 capteurs Lyon 2020-2025).

    Stockage : WORKSPACE_ROOT/{session_id}/capteurs_pl/capteurs_pl.geojson.
    Reutilise par /api/carte/generate quand ``capteurs_pl_session_id`` est
    fourni dans le body de la requete (active la branche v3).
    """
    require_owned_session(session_id, current_user)

    if not file.filename or not file.filename.lower().endswith((".geojson", ".json")):
        raise HTTPException(
            status_code=400,
            detail="Le fichier doit etre un .geojson ou .json",
        )

    settings = get_settings()
    dest_dir = Path(settings.WORKSPACE_ROOT) / session_id / "capteurs_pl"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / "capteurs_pl.geojson"

    content = await file.read()
    dest_path.write_bytes(content)

    # Validation rapide via geopandas (lazy import comme upload.py).
    try:
        import geopandas as gpd
        gdf = gpd.read_file(dest_path)
    except Exception as exc:  # noqa: BLE001
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"GeoJSON invalide : {exc}")

    required_cols = {"TMJOBCPL", "TMJOBCTV", "annee"}
    missing = required_cols - set(gdf.columns)
    if missing:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes : {sorted(missing)}",
        )

    # Verification geometrique : capteurs = Points.
    if len(gdf) == 0 or not all(gdf.geometry.geom_type == "Point"):
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="Geometrie attendue : Point WGS84 (capteurs SIREDO ponctuels).",
        )

    annees_dispo = sorted(
        pd.to_numeric(gdf["annee"], errors="coerce")
        .dropna().astype(int).unique().tolist()
    )

    logger.info(
        "Capteurs PL uploades : session=%s n=%d annees=%s path=%s",
        session_id, len(gdf), annees_dispo, dest_path,
    )

    return CapteursPLUploadResponse(
        session_id=session_id,
        n_capteurs=len(gdf),
        annees_disponibles=annees_dispo,
        path=str(dest_path),
    )


@router.post("/generate", response_model=CarteGenerateResponse)
@limit_carte_generate()
async def generate_carte(
    request: Request,
    body: CarteGenerateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> CarteGenerateResponse:
    """Apply TV + PL models on FCD data to produce a carte de debits GeoJSON.

    A6/P1-3 : 10/minute par utilisateur (rendu carte SIG lourd). La suite de
    tests desactive le limiter (DISABLE_RATE_LIMIT / pytest auto-detect).
    """

    # 1. Validate session ownership
    session = require_owned_session(body.session_id, current_user)

    # 2. Load raw data from session
    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        raise HTTPException(status_code=400, detail="Aucune donnee FCD dans la session. Uploadez un fichier d'abord.")

    # 3. Load TV model (toujours requis). Le modele PL est OPTIONNEL : il n'est
    #    charge que si ``model_pl_dir`` est non-vide (None/""/whitespace = pas
    #    de PL). Tout le bloc de prediction PL et les colonnes derivees du PL
    #    (DPL*/PLr*/PLred/VLred) sont conditionnes par ce flag.
    try:
        model_tv, coeff_tv, config_tv = await asyncio.to_thread(_load_model, body.model_tv_dir)
    except (FileNotFoundError, Exception) as e:
        raise HTTPException(status_code=400, detail=f"Erreur chargement modele TV: {e}")

    pl_enabled = bool(body.model_pl_dir and body.model_pl_dir.strip())

    model_pl = coeff_pl = config_pl = None
    if pl_enabled:
        try:
            model_pl, coeff_pl, config_pl = await asyncio.to_thread(_load_model, body.model_pl_dir)
        except (FileNotFoundError, Exception) as e:
            raise HTTPException(status_code=400, detail=f"Erreur chargement modele PL: {e}")

    # 4. Extract norm coefficients
    muY_tv = coeff_tv["muY"][0]
    SY_tv = coeff_tv["SY"][0]
    SX_tv = coeff_tv["SX"][0]
    muX_tv = coeff_tv["muX"][0]

    muY_pl = SY_pl = SX_pl = muX_pl = None
    if pl_enabled:
        muY_pl = coeff_pl["muY"][0]
        SY_pl = coeff_pl["SY"][0]
        SX_pl = coeff_pl["SX"][0]
        muX_pl = coeff_pl["muX"][0]

    # 5. Prepare data — apply column mapping
    data = raw_df.copy()

    # Build rename dict: source_col -> target_col (skip None mappings)
    rename_dict = {v: k for k, v in body.column_mapping.items() if v is not None}
    data = data.rename(columns=rename_dict)

    # Normalise source-side columns (FCDREFGLOBAL parquet, etc.) to canonical names
    data = _normalize_source_columns(data)

    # Apply legacy column aliases (silent retrocompat)
    data = _apply_column_aliases(data)

    # Apply year mapping for TV (overrides body > training_config si fournis)
    data = _apply_year_mapping(
        data, config_tv,
        year_column_override=body.year_column_name,
        year_mapping_override=body.year_value_mapping,
    )

    # 6. TV prediction
    if config_tv and "input_cols" in config_tv:
        input_cols_tv = _normalize_input_cols(config_tv["input_cols"])
    else:
        input_cols_tv = [
            "TMJOFCDTV", "TMJOFCDPL", "avg_distance_m", "avg_speed_kmh",
            "truck_avg_min_distance_m", "truck_avg_speed_kmh",
        ]

    missing_tv = [c for c in input_cols_tv if c not in data.columns]
    if missing_tv:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes pour le modele TV: {missing_tv}",
        )

    x1_tv = data[input_cols_tv]
    # Respect the training-time on_off_norm mask (some inputs like year_mapped
    # or functional_class are kept raw). When absent, default to all-on for
    # back-compat with legacy configs.
    onOffNorm_tv = config_tv.get("on_off_norm") if config_tv else None
    if not onOffNorm_tv or len(onOffNorm_tv) != len(input_cols_tv):
        onOffNorm_tv = [1] * len(input_cols_tv)
    xNorm_tv = _my_norm(x1_tv, onOffNorm_tv, muX_tv, SX_tv)
    x_tv = np.array(xNorm_tv).astype(np.float32)
    # B4: TF predict can take several seconds - offload to worker thread
    yestTNorm_tv = await asyncio.to_thread(model_tv.predict, x_tv, verbose=0)
    yestT_tv = _my_denorm(yestTNorm_tv, muY_tv, SY_tv)

    data["TxPenpred"] = yestT_tv[:, 0]
    # JOr = TV redresse journalier (anciennement TVr — cf module docstring).
    data["JOrpred"] = data["TMJOFCDTV"] / np.abs(yestT_tv[:, 0]) * 100

    # C7: release TV model resources before loading the PL model.
    # Factorise via ``release_tf_model`` (cf services.ml.inference) qui fait
    # del + gc.collect() + tf.keras.backend.clear_session() en un appel.
    del model_tv, x_tv, yestTNorm_tv
    release_tf_model()

    # Format intermediates. PL FCD brute kept here for VLred derivation only —
    # n'est PLUS expose en sortie (cf changement 2 : suppression PL).
    data["TMJOFCDPL"] = pd.to_numeric(data["TMJOFCDPL"], errors="coerce").round(1)
    data["JOrpred"] = data["JOrpred"].round(0)

    # Rename intermediate canonical columns to the SHORT output names used by
    # the carte GeoJSON output. JOr remplace TVr (rename interne complet,
    # cf module docstring). PL FCD brute renomme PL_brute_interne pour signaler
    # qu'elle n'est plus exposee en sortie.
    data = data.rename(columns={
        "TMJOFCDPL": "PL_brute_interne",
        "JOrpred": "JOr",
        "functional_class": "FC",
    })

    # Handle AgregId (already normalised from agregId by _normalize_source_columns)
    if "AgregId" not in data.columns and "id" in data.columns:
        data = data.rename(columns={"id": "AgregId"})
    elif "AgregId" not in data.columns:
        data["AgregId"] = range(len(data))

    # ── DD (boolean direction depuis DIR_TRAVEL si fourni par FCDREFGLOBAL) ───
    # DIR_TRAVEL = "B" (Both / bidirectionnel) -> DD=True ; sinon False.
    if "DIR_TRAVEL" in data.columns:
        data["DD"] = (data["DIR_TRAVEL"] == "B").astype(bool)
    else:
        data["DD"] = False

    # ── HD (heading) ──────────────────────────────────────────────────────────
    # Si HD est fourni par la source (FCDREFGLOBAL) on l'utilise tel quel ;
    # sinon fallback sur calcul geometrique depuis la LineString. Convention :
    # entier en degres (0..359, 0 = Nord).
    geom_col = "geometry" if "geometry" in data.columns else "__geometry_json"

    if "HD" in data.columns and pd.to_numeric(data["HD"], errors="coerce").notna().sum() > 0:
        # HD fourni par la source (FCDREFGLOBAL ou colonne mappee) — on l'utilise tel quel.
        data["HD"] = pd.to_numeric(data["HD"], errors="coerce").fillna(0).round().astype(int).mod(360)
    elif geom_col in data.columns:
        # Fallback : derive HD from LineString geometry via the geo service helper
        # (factorise ; cf ``services.geo._parse_and_heading``).
        data["HD"] = data[geom_col].apply(_parse_and_heading_helper).round().astype(int).mod(360)
    else:
        data["HD"] = 0
    # HD borne sur [0, 359] : 360 degres reboucle vers 0 (cap geographique).

    # Select columns for intermediate result (using canonical names).
    # PL FCD brute n'est PLUS exposee (cf changement 2) ; VL/TP supprimes.
    selected_columns = [
        "AgregId", "FC", "JOr", "DD", "HD",
        "car_count", "avg_speed_kmh", "avg_distance_m",
        "truck_count", "truck_avg_speed_kmh", "truck_avg_min_distance_m",
        "geometry", "__geometry_json",
    ]
    available_cols = [c for c in selected_columns if c in data.columns]
    prod = data[available_cols].copy()

    # 7. PL prediction (OPTIONNEL) — use a fresh copy from raw with mapping.
    #    Tout ce bloc est saute quand ``pl_enabled`` est False : aucune colonne
    #    derivee du PL (DPL/DPLmin/DPLmax/PLr*/PLred/VLred) n'est produite.
    #    ``data_pl`` reste None en mode TV-seul ; les references downstream sont
    #    gardees par ``pl_enabled`` / ``"DPL" in prod.columns``.
    data_pl = None
    if pl_enabled:
        data_pl = raw_df.copy()
        data_pl = data_pl.rename(columns=rename_dict)
        data_pl = _normalize_source_columns(data_pl)
        data_pl = _apply_column_aliases(data_pl)
        data_pl = _apply_year_mapping(
            data_pl, config_pl,
            year_column_override=body.year_column_name,
            year_mapping_override=body.year_value_mapping,
        )

        if config_pl and "input_cols" in config_pl:
            input_cols_pl = _normalize_input_cols(config_pl["input_cols"])
        else:
            input_cols_pl = [
                "TMJOFCDPL", "avg_distance_m", "avg_speed_kmh",
                "truck_avg_min_distance_m", "truck_avg_speed_kmh",
            ]

        missing_pl = [c for c in input_cols_pl if c not in data_pl.columns]
        if missing_pl:
            raise HTTPException(
                status_code=400,
                detail=f"Colonnes manquantes pour le modele PL: {missing_pl}",
            )

        x1_pl = data_pl[input_cols_pl]
        onOffNorm_pl = config_pl.get("on_off_norm") if config_pl else None
        if not onOffNorm_pl or len(onOffNorm_pl) != len(input_cols_pl):
            onOffNorm_pl = [1] * len(input_cols_pl)
        xNorm_pl = _my_norm(x1_pl, onOffNorm_pl, muX_pl, SX_pl)
        x_pl = np.array(xNorm_pl).astype(np.float32)
        # B4: TF predict can take several seconds - offload to worker thread
        yestTNorm_pl = await asyncio.to_thread(model_pl.predict, x_pl, verbose=0)
        yestT_pl = _my_denorm(yestTNorm_pl, muY_pl, SY_pl)

        data_pl["TxPenPL"] = yestT_pl[:, 0]
        data_pl["DPLpred"] = data_pl["TMJOFCDPL"] / yestT_pl[:, 0] * 100

        # C7: release PL model resources after predict (factorise — cf TV ci-dessus).
        del model_pl, x_pl, yestTNorm_pl
        release_tf_model()

        # Add PL results — DPL (debit PL/j redresse). PLr (ratio PL/TV) n'est plus
        # produit en sortie (cf changement 2 : nettoyage schema).
        prod["DPL"] = data_pl["DPLpred"].round(0).values

    # ── HPM (optionnel) — produit PM/PMmin/PMmax en v/h (Heure de Pointe Matin)
    # cf CONFIGS["HPM"] / FCD_HPM_TV = FCDTV_h08 / TxPen_HPM hourly target.
    # Unite differente de JOr/DPL (qui sont en v/j) : tranches IC en v/h dans
    # PeakHourErrorThresholds. Si le modele est fourni mais echoue ou si une
    # colonne horaire est absente, on leve une 400/500 explicite (pas de
    # fallback silencieux — l'utilisateur doit savoir).
    if body.model_hpm_dir:
        _hpm_fallback_inputs = [
            "FCD_HPM_TV", "TMJOFCDPL", "avg_distance_m", "avg_speed_kmh",
            "truck_avg_min_distance_m", "truck_avg_speed_kmh", "functional_class",
        ]
        _hpm_aliases = ("FCDTV_h08", "FCDTV_HPM", "FCD_HPM")
        _, debit_pm = await _predict_peak_hour(
            raw_df=raw_df,
            rename_dict=rename_dict,
            model_dir=body.model_hpm_dir,
            kind="HPM",
            canonical_fcd="FCD_HPM_TV",
            fcd_aliases=_hpm_aliases,
            fallback_input_cols=_hpm_fallback_inputs,
            year_column_override=body.year_column_name,
            year_mapping_override=body.year_value_mapping,
        )
        # debit_pm is index-aligned with raw_df. Reindex to ``prod`` (which has
        # been filtered/renamed; "agregId" rename happens later so we use the
        # positional index — both DataFrames are derived from raw_df without
        # row reordering until the filter step below).
        pm_series = pd.Series(debit_pm, index=raw_df.index).reindex(prod.index)
        pm_series = pm_series.replace([np.inf, -np.inf], np.nan).round(0)
        prod["PM"] = pm_series
        # IC tranches v/h (D2).
        pm_err = pm_series.fillna(0).apply(
            lambda v: _peak_hour_err_pct(float(v), body.err_pm_thresholds)
        )
        prod["PMmin"] = (pm_series * (1 - pm_err / 100.0)).round(0)
        prod["PMmax"] = (pm_series * (1 + pm_err / 100.0)).round(0)

    # ── HPS (optionnel) — produit PS/PSmin/PSmax en v/h (Heure de Pointe Soir)
    # cf CONFIGS["HPS"] / FCD_HPS_TV = FCDTV_h17. Symetrique de HPM ci-dessus.
    if body.model_hps_dir:
        _hps_fallback_inputs = [
            "FCD_HPS_TV", "TMJOFCDPL", "avg_distance_m", "avg_speed_kmh",
            "truck_avg_min_distance_m", "truck_avg_speed_kmh", "functional_class",
        ]
        _hps_aliases = ("FCDTV_h17", "FCDTV_HPS", "FCD_HPS")
        _, debit_ps = await _predict_peak_hour(
            raw_df=raw_df,
            rename_dict=rename_dict,
            model_dir=body.model_hps_dir,
            kind="HPS",
            canonical_fcd="FCD_HPS_TV",
            fcd_aliases=_hps_aliases,
            fallback_input_cols=_hps_fallback_inputs,
            year_column_override=body.year_column_name,
            year_mapping_override=body.year_value_mapping,
        )
        ps_series = pd.Series(debit_ps, index=raw_df.index).reindex(prod.index)
        ps_series = ps_series.replace([np.inf, -np.inf], np.nan).round(0)
        prod["PS"] = ps_series
        ps_err = ps_series.fillna(0).apply(
            lambda v: _peak_hour_err_pct(float(v), body.err_ps_thresholds)
        )
        prod["PSmin"] = (ps_series * (1 - ps_err / 100.0)).round(0)
        prod["PSmax"] = (ps_series * (1 + ps_err / 100.0)).round(0)

    # 8. Confidence intervals — JOr (anciennement TVr, cf module docstring)
    thresholds = body.error_thresholds
    prod["Erreur_dyn"] = prod["JOr"].apply(lambda x: _erreur_pourcentage(x, thresholds))
    prod["JOrmin"] = (prod["JOr"] * (1 - prod["Erreur_dyn"])).round(0)
    prod["JOrmax"] = (prod["JOr"] * (1 + prod["Erreur_dyn"])).round(0)

    # Pre-rounding JOr bounds (sera ecrase par l'arrondi progressif Option B
    # si arrondi_progressif_enabled=True ; on garde les regles legacy pour le
    # mode toggle OFF).
    mask10 = prod["JOr"] > 10000
    prod.loc[mask10, "JOrmin"] = np.round(prod.loc[mask10, "JOrmin"], -2)
    prod.loc[mask10, "JOrmax"] = np.round(prod.loc[mask10, "JOrmax"], -2)

    mask500 = prod["JOr"] < 500
    prod.loc[mask500, "JOrmin"] = 10 * np.floor(prod.loc[mask500, "JOrmin"] / 10)
    prod.loc[mask500, "JOrmax"] = 10 * np.ceil(prod.loc[mask500, "JOrmax"] / 10)

    mask_middle = prod["JOr"] >= 500
    prod.loc[mask_middle, "JOrmin"] = 100 * np.floor(prod.loc[mask_middle, "JOrmin"] / 100)
    prod.loc[mask_middle, "JOrmax"] = 100 * np.ceil(prod.loc[mask_middle, "JOrmax"] / 100)

    mask_min = prod["JOrmin"].notna() & (prod["JOrmin"] < 100)
    mask_max = prod["JOrmax"].notna() & (prod["JOrmax"] < 100)
    prod.loc[mask_min, "JOrmin"] = 0
    prod.loc[mask_max, "JOrmax"] = 100

    # 9. Confidence intervals — DPL (uniquement si PL present).
    if pl_enabled and "DPL" in prod.columns:
        prod["DPLmin"] = prod["DPL"].apply(_calculer_DPLmin)
        prod.loc[prod["DPLmin"] > 1e4, "DPLmin"] = np.round(
            prod.loc[prod["DPLmin"] > 1e4, "DPLmin"], -3
        )
        prod["DPLmax"] = prod["DPL"].apply(_calculer_DPLmax)
        prod.loc[prod["DPLmax"] > 1e4, "DPLmax"] = np.round(
            prod.loc[prod["DPLmax"] > 1e4, "DPLmax"], -3
        )
        prod.loc[prod["DPLmin"] > 50, "DPLmin"] = 10 * np.floor(
            prod.loc[prod["DPLmin"] > 50, "DPLmin"] / 10
        )
        prod.loc[prod["DPLmax"] > 50, "DPLmax"] = 10 * np.ceil(
            prod.loc[prod["DPLmax"] > 50, "DPLmax"] / 10
        )

    # 10. (PLr/PLrmin/PLrmax supprimes — cf changement 2 : nettoyage schema.
    # Le ratio PL/JOr est trivialement re-derivable downstream si besoin.)

    # 10.b — Saturation hierarchique PL v3 hybride + override zones critiques.
    #        cf SATURATION_PL_specs.md v3.0 — NE PAS MODIFIER SANS RELIRE LA SPEC.
    #
    # Post-traitement POST-prediction : n'affecte PAS le modele ni les sorties
    # brutes du reseau. Dispatch automatique v1/v2/v3 selon les inputs :
    #
    #     +---------------------------------+-----------------------+
    #     | capteurs SIREDO + FCD presents  | -> v3 (override)      |
    #     | FCD seul                        | -> v2 (hybride)       |
    #     | ni capteurs ni FCD              | -> v1 (cap fixe FC)   |
    #     +---------------------------------+-----------------------+
    #
    # ETAPES v3 :
    #   0) Detection zones critiques (buffer 1 km autour capteurs > 15 %)
    #   1) alpha_FCD = (TMJFCDPL / TMJFCDTV) * RATIO_MACRO_PEN
    #   2) alpha     = max(alpha_FCD, alpha_min_local)
    #      ou alpha_min_local = ALPHA_MIN_ZONE_CRITIQUE si zone critique,
    #                           sinon ALPHA_FC_MIN[FC]
    #   3) alpha_eff = min(alpha, ALPHA_PHYSIQUE_MAX)
    #   4) DPL_sat   = min(DPL_brut, BORNES_FC_ABS[FC], alpha_eff * JOr)
    #
    # Fallback : si TMJFCDTV < SEUIL_VOL_FCD_TV (v/j), on retombe sur le
    # plancher local (= 0.30 si zone critique, sinon ALPHA_FC_MIN[FC]).
    #
    # Sorties diagnostiques (exposees dans le GeoJSON) :
    #   - alpha_eff         : ratio applique par segment, [0, alpha_physique_max]
    #   - alpha_source      : 5 valeurs ("plancher_fallback" / "plancher_FC" /
    #                         "plancher_zone_critique" / "fcd" / "plafond")
    #   - is_critical_zone  : bool, uniquement si v3 actif
    #
    # No-op si pl_saturation_enabled=False, ou si DPL/FC absents (backward compat).
    if body.pl_saturation_enabled and "DPL" in prod.columns and "FC" in prod.columns:
        jor_series = pd.to_numeric(prod["JOr"], errors="coerce") if "JOr" in prod.columns else pd.Series(0.0, index=prod.index)
        jormin_series = pd.to_numeric(prod["JOrmin"], errors="coerce") if "JOrmin" in prod.columns else jor_series
        jormax_series = pd.to_numeric(prod["JOrmax"], errors="coerce") if "JOrmax" in prod.columns else jor_series
        fc_series = pd.to_numeric(prod["FC"], errors="coerce")

        # ── Dispatch v1/v2/v3 selon les inputs disponibles ─────────────────
        _has_fcd_inputs = (
            "TMJOFCDPL" in data_pl.columns and "TMJOFCDTV" in data_pl.columns
        )

        # Capteurs SIREDO : present uniquement si l'utilisateur a uploade
        # un fichier capteurs_pl.geojson via /upload-capteurs-pl ET active
        # l'override (D2 ON par defaut).
        _settings = get_settings()
        capteurs_path: Path | None = None
        if body.zone_critique_enabled and body.capteurs_pl_session_id:
            _candidate = (
                Path(_settings.WORKSPACE_ROOT)
                / body.capteurs_pl_session_id
                / "capteurs_pl"
                / "capteurs_pl.geojson"
            )
            if _candidate.exists():
                capteurs_path = _candidate

        _has_capteurs = capteurs_path is not None

        if _has_fcd_inputs and _has_capteurs:
            version = "v3"
        elif _has_fcd_inputs:
            version = "v2"
            # D3 : fallback silencieux (INFO, pas WARNING) si user a active la
            # detection mais n'a pas (encore) fourni les capteurs.
            if body.zone_critique_enabled:
                logger.info(
                    "PL saturation : zone_critique_enabled=True mais "
                    "capteurs SIREDO absents -> fallback v2 (hybride sans override).",
                )
        else:
            version = "v1"
            logger.info(
                "PL saturation : TMJOFCDPL/TMJOFCDTV absent -> fallback v1 "
                "(cap fixe par FC sans ratio FCD adaptatif).",
            )

        # ── ETAPE 0 (v3 uniquement) : detection zones critiques ────────────
        is_critical = pd.Series(False, index=prod.index)
        if version == "v3":
            try:
                import geopandas as gpd

                capteurs_gdf = gpd.read_file(capteurs_path)
                if capteurs_gdf.crs is None:
                    capteurs_gdf = capteurs_gdf.set_crs("EPSG:4326")

                # Reconstruire le GeoDataFrame des segments (LineString WGS84)
                # a partir de la colonne geometry stockee dans prod. Le parsing
                # defensif (str JSON / dict / None) est factorise dans
                # ``services.geo._parse_geom_shapely``.
                _geom_key = "geometry" if "geometry" in prod.columns else "__geometry_json"
                if _geom_key in prod.columns:
                    seg_geoms = prod[_geom_key].apply(_parse_geom_shapely)
                    valid_mask = seg_geoms.notna()
                    segs_gdf = gpd.GeoDataFrame(
                        prod[["FC"]].copy(),
                        geometry=seg_geoms,
                        crs="EPSG:4326",
                    )
                    # Limiter le calcul aux geometries valides ; les autres
                    # restent False par defaut (segments sans geometrie -> hors zone).
                    if valid_mask.any():
                        is_critical_valid = _detecter_zones_critiques(
                            capteurs_gdf,
                            segs_gdf.loc[valid_mask],
                            body.annee_capteurs,
                            body.ratio_capteur_critique,
                            body.buffer_zone_critique_m,
                        )
                        is_critical = pd.Series(False, index=prod.index)
                        is_critical.loc[valid_mask] = is_critical_valid
                    else:
                        logger.warning(
                            "PL saturation v3 : aucune geometrie valide -> fallback v2.",
                        )
                        version = "v2"
                else:
                    logger.warning(
                        "PL saturation v3 : pas de colonne geometry -> fallback v2.",
                    )
                    version = "v2"

                if version == "v3":
                    n_crit = int(is_critical.sum())
                    pct_crit = (100.0 * n_crit / len(prod)) if len(prod) > 0 else 0.0
                    logger.info(
                        "PL saturation v3 : %d segments en zone critique (%.2f%%)",
                        n_crit, pct_crit,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PL saturation v3 : echec detection zones critiques (%s) "
                    "-> fallback v2.",
                    exc,
                )
                version = "v2"
                is_critical = pd.Series(False, index=prod.index)

        # ── ETAPES 1/2/3 : calcul alpha_eff (v2/v3 = adaptatif ; v1 = plancher FC) ──
        if version in ("v2", "v3"):
            fcd_pl_series = pd.to_numeric(
                data_pl["TMJOFCDPL"], errors="coerce",
            ).reindex(prod.index)
            fcd_tv_series = pd.to_numeric(
                data_pl["TMJOFCDTV"], errors="coerce",
            ).reindex(prod.index)
            alpha_eff, alpha_source = _alpha_v3(
                fcd_pl_series,
                fcd_tv_series,
                fc_series,
                is_critical,
                body.alpha_fc_min,
                body.ratio_macro_pen,
                body.alpha_physique_max,
                body.seuil_vol_fcd_tv,
                body.alpha_min_zone_critique,
            )
        else:
            # v1 : alpha = plancher FC par segment (= ALPHA_FC[FC]). Le cap dur
            # cap_abs reste BORNES_FC_ABS comme v2/v3 (defense en profondeur).
            fc_c_v1 = fc_series.fillna(5).clip(1, 5).astype(int)
            alpha_eff = fc_c_v1.map(body.alpha_fc_min).astype(float)
            alpha_source = pd.Series(["v1_plancher_FC"] * len(prod), index=prod.index)

        # ── ETAPE 4 : saturation finale ────────────────────────────────────
        fc_c = fc_series.fillna(5).clip(1, 5).astype(int)
        cap_abs = fc_c.map(body.bornes_fc_abs).astype(float).to_numpy()
        alpha_arr = pd.to_numeric(alpha_eff, errors="coerce").fillna(0).astype(float).to_numpy()

        def _saturer_avec_alpha(pl_pred: pd.Series, tv_ref: pd.Series) -> pd.Series:
            """Sature PL = max(min(PL_brut, cap_abs, alpha_eff * TV), 0)."""
            pl_f = pd.to_numeric(pl_pred, errors="coerce").fillna(0).astype(float).to_numpy()
            tv_f = pd.to_numeric(tv_ref, errors="coerce").fillna(0).astype(float).to_numpy()
            cap_ratio = alpha_arr * tv_f
            pl_sat = np.minimum.reduce([pl_f, cap_abs, cap_ratio])
            pl_sat = np.maximum(pl_sat, 0)
            return pd.Series(np.round(pl_sat).astype("int32"), index=pl_pred.index)

        dpl_orig_int = pd.to_numeric(prod["DPL"], errors="coerce").fillna(0).round().astype("int32")
        dpl_sat = _saturer_avec_alpha(prod["DPL"], jor_series)
        dplmin_sat = _saturer_avec_alpha(prod["DPLmin"], jormin_series)
        dplmax_sat = _saturer_avec_alpha(prod["DPLmax"], jormax_series)
        mask_dpl = pd.Series(
            dpl_sat.to_numpy() != dpl_orig_int.to_numpy(), index=prod.index,
        )

        # Coherence DPLmin <= DPL <= DPLmax post-saturation (cf spec § cas limites §5).
        dplmin_sat = pd.Series(
            np.minimum(dplmin_sat.to_numpy(), dpl_sat.to_numpy()),
            index=dpl_sat.index,
        )
        dplmax_sat = pd.Series(
            np.maximum(dplmax_sat.to_numpy(), dpl_sat.to_numpy()),
            index=dpl_sat.index,
        )

        prod["DPL"] = dpl_sat
        prod["DPLmin"] = dplmin_sat
        prod["DPLmax"] = dplmax_sat
        # Colonnes diagnostic — exposees dans le GeoJSON output.
        prod["alpha_eff"] = pd.to_numeric(alpha_eff, errors="coerce").round(4)
        prod["alpha_source"] = alpha_source.astype(str)
        if version == "v3":
            prod["is_critical_zone"] = is_critical.astype(bool)

        # ── Audit stats : log global + par FC + par source ─────────────────
        n_total = len(prod)
        n_sat = int(mask_dpl.sum())
        pct_sat = float(100 * mask_dpl.mean()) if n_total > 0 else 0.0
        logger.info(
            "PL saturation %s: %d segments satures sur %d (%.2f%%)",
            version, n_sat, n_total, pct_sat,
        )

        # Repartition par source d'alpha (5 valeurs en v3, 4 en v2, 1 en v1).
        for src_name in alpha_source.unique():
            count = int((alpha_source == src_name).sum())
            pct = (100.0 * count / n_total) if n_total > 0 else 0.0
            logger.info(
                "PL saturation %s source=%s: %d (%.2f%%)",
                version, src_name, count, pct,
            )

        for fc_class in (1, 2, 3, 4, 5):
            mask_fc = (fc_series == fc_class)
            n_fc = int(mask_fc.sum())
            if n_fc == 0:
                continue
            sat_fc = mask_dpl[mask_fc]
            n_sat_fc = int(sat_fc.sum())
            pct_fc = float(100 * sat_fc.mean())
            # Seuils d'alerte cf spec section "Metriques de monitoring" :
            #   FC1 > 5%   -> modele PL probablement defaillant sur autoroutes
            #   FC5 > 35%  -> saturation excessive (bornes trop strictes ?)
            is_warn = (fc_class == 1 and pct_fc > 5) or (fc_class == 5 and pct_fc > 35)
            level = logging.WARNING if is_warn else logging.INFO
            logger.log(
                level,
                "PL saturation %s FC%d: %d/%d (%.2f%%)",
                version, fc_class, n_sat_fc, n_fc, pct_fc,
            )

    # 10.c — Saturation hierarchique du HPM (cf SATURATION_HPM_HPS_specs.md).
    #
    # POST-prediction : n'affecte pas le modele HPM ni les sorties brutes.
    # Cape PM/PMmin/PMmax (v/h) selon :
    #   - BORNE_HPM_FC (cap dur val/h par classe fonctionnelle HERE) :
    #       FC1 autoroute (profil lisse)       -> 5 000 (marge x1.4 / max obs 3 584)
    #       FC2 voie rapide urbaine            -> 7 000 (marge x1.3 / max obs 5 405)
    #       FC3 axe urbain structurant         -> 4 000 (marge x1.1 / max obs 3 606)
    #       FC4 rue principale                 -> 1 500 (marge x1.3 / max obs 1 172)
    #       FC5 rue locale                     ->   700 (marge x1.3 / max obs   521)
    #   - ALPHA_HPM_FC (ratio max PM/JOr) : 0.10/0.18/0.16/0.18/0.18 par FC.
    #
    # NB: rename interne TVr -> JOr (cf module docstring). Le cap alpha*JOr
    # utilise le TV journalier redresse comme reference, coherent avec la spec.
    # No-op si hpm_saturation_enabled=False ou si PM/FC absents (backward
    # compat avec les generations sans modele HPM).
    if body.hpm_saturation_enabled and "PM" in prod.columns and "FC" in prod.columns:
        jor_h_series = pd.to_numeric(prod["JOr"], errors="coerce") if "JOr" in prod.columns else pd.Series(0.0, index=prod.index)
        jormin_h_series = pd.to_numeric(prod["JOrmin"], errors="coerce") if "JOrmin" in prod.columns else jor_h_series
        jormax_h_series = pd.to_numeric(prod["JOrmax"], errors="coerce") if "JOrmax" in prod.columns else jor_h_series
        fc_h_series = pd.to_numeric(prod["FC"], errors="coerce")

        pm_sat, mask_pm = _saturer_horaire_hierarchique(
            prod["PM"], jor_h_series, fc_h_series, body.borne_hpm_fc, body.alpha_hpm_fc,
        )
        pmmin_sat, _ = _saturer_horaire_hierarchique(
            prod["PMmin"], jormin_h_series, fc_h_series, body.borne_hpm_fc, body.alpha_hpm_fc,
        )
        pmmax_sat, _ = _saturer_horaire_hierarchique(
            prod["PMmax"], jormax_h_series, fc_h_series, body.borne_hpm_fc, body.alpha_hpm_fc,
        )

        # Coherence PMmin <= PM <= PMmax (cf spec section "cas limites" §4).
        pmmin_sat = pd.Series(
            np.minimum(pmmin_sat.to_numpy(), pm_sat.to_numpy()),
            index=pm_sat.index,
        )
        pmmax_sat = pd.Series(
            np.maximum(pmmax_sat.to_numpy(), pm_sat.to_numpy()),
            index=pm_sat.index,
        )

        prod["PM"] = pm_sat
        prod["PMmin"] = pmmin_sat
        prod["PMmax"] = pmmax_sat

        # Audit stats : log global + par FC (warning si seuils suspects).
        n_total_hpm = len(prod)
        n_sat_hpm = int(mask_pm.sum())
        pct_sat_hpm = float(100 * mask_pm.mean()) if n_total_hpm > 0 else 0.0
        logger.info(
            "HPM saturation: %d segments satures sur %d (%.2f%%)",
            n_sat_hpm, n_total_hpm, pct_sat_hpm,
        )
        for fc_class in (1, 2, 3, 4, 5):
            mask_fc_hpm = (fc_h_series == fc_class)
            n_fc_hpm = int(mask_fc_hpm.sum())
            if n_fc_hpm == 0:
                continue
            sat_fc_hpm = mask_pm[mask_fc_hpm]
            n_sat_fc_hpm = int(sat_fc_hpm.sum())
            pct_fc_hpm = float(100 * sat_fc_hpm.mean())
            # Seuils d'alerte cf spec section "Metriques de monitoring" :
            #   FC1 > 5%   -> calibration FC1 a revoir
            #   FC5 > 30%  -> modele local instable (extrapolation)
            is_warn_hpm = (fc_class == 1 and pct_fc_hpm > 5) or (
                fc_class == 5 and pct_fc_hpm > 30
            )
            level_hpm = logging.WARNING if is_warn_hpm else logging.INFO
            logger.log(
                level_hpm,
                "HPM saturation FC%d: %d/%d (%.2f%%)",
                fc_class, n_sat_fc_hpm, n_fc_hpm, pct_fc_hpm,
            )

    # 10.d — Saturation hierarchique du HPS (cf SATURATION_HPM_HPS_specs.md).
    #
    # Symetrique de HPM ci-dessus, sur PS/PSmin/PSmax (v/h). Bornes et alpha
    # distincts car la pointe soir est plus etalee (retours echelonnes 16h-19h)
    # mais plus variable sur FC4 (sorties d'ecoles / livraisons, d'ou
    # alpha_HPS_FC4=0.20 plus genereux que HPM).
    #
    # No-op si hps_saturation_enabled=False ou si PS/FC absents.
    if body.hps_saturation_enabled and "PS" in prod.columns and "FC" in prod.columns:
        jor_h_series = pd.to_numeric(prod["JOr"], errors="coerce") if "JOr" in prod.columns else pd.Series(0.0, index=prod.index)
        jormin_h_series = pd.to_numeric(prod["JOrmin"], errors="coerce") if "JOrmin" in prod.columns else jor_h_series
        jormax_h_series = pd.to_numeric(prod["JOrmax"], errors="coerce") if "JOrmax" in prod.columns else jor_h_series
        fc_h_series = pd.to_numeric(prod["FC"], errors="coerce")

        ps_sat, mask_ps = _saturer_horaire_hierarchique(
            prod["PS"], jor_h_series, fc_h_series, body.borne_hps_fc, body.alpha_hps_fc,
        )
        psmin_sat, _ = _saturer_horaire_hierarchique(
            prod["PSmin"], jormin_h_series, fc_h_series, body.borne_hps_fc, body.alpha_hps_fc,
        )
        psmax_sat, _ = _saturer_horaire_hierarchique(
            prod["PSmax"], jormax_h_series, fc_h_series, body.borne_hps_fc, body.alpha_hps_fc,
        )

        # Coherence PSmin <= PS <= PSmax (cf spec section "cas limites" §4).
        psmin_sat = pd.Series(
            np.minimum(psmin_sat.to_numpy(), ps_sat.to_numpy()),
            index=ps_sat.index,
        )
        psmax_sat = pd.Series(
            np.maximum(psmax_sat.to_numpy(), ps_sat.to_numpy()),
            index=ps_sat.index,
        )

        prod["PS"] = ps_sat
        prod["PSmin"] = psmin_sat
        prod["PSmax"] = psmax_sat

        # Audit stats : log global + par FC (warning si seuils suspects).
        n_total_hps = len(prod)
        n_sat_hps = int(mask_ps.sum())
        pct_sat_hps = float(100 * mask_ps.mean()) if n_total_hps > 0 else 0.0
        logger.info(
            "HPS saturation: %d segments satures sur %d (%.2f%%)",
            n_sat_hps, n_total_hps, pct_sat_hps,
        )
        for fc_class in (1, 2, 3, 4, 5):
            mask_fc_hps = (fc_h_series == fc_class)
            n_fc_hps = int(mask_fc_hps.sum())
            if n_fc_hps == 0:
                continue
            sat_fc_hps = mask_ps[mask_fc_hps]
            n_sat_fc_hps = int(sat_fc_hps.sum())
            pct_fc_hps = float(100 * sat_fc_hps.mean())
            is_warn_hps = (fc_class == 1 and pct_fc_hps > 5) or (
                fc_class == 5 and pct_fc_hps > 30
            )
            level_hps = logging.WARNING if is_warn_hps else logging.INFO
            logger.log(
                level_hps,
                "HPS saturation FC%d: %d/%d (%.2f%%)",
                fc_class, n_sat_fc_hps, n_fc_hps, pct_fc_hps,
            )

    # 11. Cleanup pre-arrondi : non-finite + clamps >=0 (cf changement 4 spec).
    # Doit etre fait AVANT l'arrondi progressif sinon NaN/inf cassent les casts
    # int32 en aval. Apres saturation, les valeurs sont deja non-negatives par
    # construction ; on re-clampe defensivement pour les colonnes non-saturees
    # (DPL/DPLmin/DPLmax si pl_saturation_enabled=False).
    prod = prod.replace([np.inf, -np.inf], np.nan)
    prod = prod.fillna(0)

    for _pl_col in ("DPL", "DPLmin", "DPLmax"):
        if _pl_col in prod.columns:
            prod[_pl_col] = prod[_pl_col].clip(lower=0)

    # PM/PS values en v/h — clamp defensif (cf legacy comment : modeles peuvent
    # sortir <0 en extrapolation rare).
    for _hp_col in ("PM", "PMmin", "PMmax", "PS", "PSmin", "PSmax"):
        if _hp_col in prod.columns:
            prod[_hp_col] = prod[_hp_col].clip(lower=0)

    # 11.b — Arrondi progressif Option B (cf ARRONDI_PROGRESSIF_specs.md).
    #
    # ORDRE CRITIQUE (cf spec § Pipeline complet) :
    #   1) Saturations PL/HPM/HPS (deja faites en 10.b/10.c/10.d).
    #   2) Arrondi progressif sur triplets (JOr, DPL, PM, PS) -- ici.
    #   3) PLred = DPL (apres arrondi DPL) -- ici.
    #   4) VLred = round_progressive(max(JOr - DPL, 0)) -- ici.
    #
    # Toggle OFF -> on saute l'arrondi mais on calcule PLred/VLred pour
    # garantir un schema de sortie stable.
    if body.arrondi_progressif_enabled:
        triplets_a_arrondir: list[tuple[str, str, str]] = [
            ("JOrmin", "JOr", "JOrmax"),
        ]
        # Triplet DPL uniquement si PL present (DPL absent => pas d'arrondi PL).
        if "DPL" in prod.columns:
            triplets_a_arrondir.append(("DPLmin", "DPL", "DPLmax"))
        if "PM" in prod.columns:
            triplets_a_arrondir.append(("PMmin", "PM", "PMmax"))
        if "PS" in prod.columns:
            triplets_a_arrondir.append(("PSmin", "PS", "PSmax"))

        prod = _appliquer_arrondi_avec_coherence(prod, triplets_a_arrondir)

        # Recomposition POST-arrondi (cf spec etapes 3 et 4). PLred/VLred ne sont
        # derivables que si DPL existe ; sans modele PL on les omet (cf changement
        # PL optionnel) — le schema de sortie n'inclut alors aucune colonne PL.
        if "DPL" in prod.columns:
            #   PLred = DPL arrondi (deja arrondi par le triplet ci-dessus)
            #   VLred = round_progressive(max(JOr_arrondi - DPL_arrondi, 0))
            prod["PLred"] = prod["DPL"].astype("int32")
            prod["VLred"] = _round_progressive(
                np.maximum(
                    prod["JOr"].astype("int64") - prod["DPL"].astype("int64"),
                    0,
                )
            ).astype("int32")

        # Audit logs (max/median pour detection regression).
        for triplet in triplets_a_arrondir:
            for c in triplet:
                if c in prod.columns:
                    col_max = int(pd.to_numeric(prod[c], errors="coerce").fillna(0).max())
                    col_med = int(pd.to_numeric(prod[c], errors="coerce").fillna(0).median())
                    logger.info(
                        "Arrondi progressif applique sur %s (max=%d, median=%d)",
                        c, col_max, col_med,
                    )
        logger.info(
            "Recomposition post-arrondi : PLred=DPL, VLred=round(max(JOr-DPL,0))",
        )
    else:
        # Toggle OFF : on garde PLred/VLred coherents avec le schema mais sans
        # l'arrondi progressif (les regles legacy d'arrondi conditional 10/100
        # sont appliquees ci-dessous a la place).
        cols_conditional = [c for c in ("JOr", "JOrmin", "JOrmax") if c in prod.columns]
        for col in cols_conditional:
            s = pd.to_numeric(prod[col], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
            prod[col] = np.where(
                s < 10_000,
                np.round(s / 10) * 10,
                np.round(s / 100) * 100,
            ).astype(int)

        cols_round_10 = [c for c in ("DPL", "DPLmin", "DPLmax") if c in prod.columns]
        for col in cols_round_10:
            s = pd.to_numeric(prod[col], errors="coerce").replace([np.inf, -np.inf], 0).fillna(0)
            prod[col] = (np.round(s / 10) * 10).astype(int)

        for col in ("JOrmax", "DPLmax"):
            if col in prod.columns:
                prod.loc[prod[col] == 0, col] = 10

        # PLred/VLred uniquement si DPL present (PL optionnel — cf supra).
        if "DPL" in prod.columns:
            prod["PLred"] = prod["DPL"].astype("int32")
            prod["VLred"] = np.maximum(
                prod["JOr"].astype("int64") - prod["DPL"].astype("int64"), 0,
            ).astype("int32")

    # Integer-cast residuel pour HD, PM/PS (au cas ou).
    int_cols = ["HD"]
    for _hp_col in ("PM", "PMmin", "PMmax", "PS", "PSmin", "PSmax"):
        if _hp_col in prod.columns:
            int_cols.append(_hp_col)
    existing_int_cols = [c for c in int_cols if c in prod.columns]
    prod[existing_int_cols] = prod[existing_int_cols].round(0).astype(int)

    if "FC" in prod.columns:
        prod["FC"] = pd.to_numeric(prod["FC"], errors="coerce").fillna(0).astype(int)

    # HD : si calcule sur geometrie en aval (fallback), garantir int. Si HD
    # provient deja de la source (ou du fallback geometrique pose plus haut),
    # le cast est idempotent.
    if "HD" in prod.columns:
        # Modulo 360 : 360 degres reboucle vers 0 (cap geographique borne sur [0, 359]).
        prod["HD"] = pd.to_numeric(prod["HD"], errors="coerce").fillna(0).round().astype(int).mod(360)

    prod = prod.rename(columns={"AgregId": "agregId"})

    if "DD" in prod.columns:
        prod["DD"] = prod["DD"].astype(bool)
    else:
        prod["DD"] = False

    # 12. Apply filters
    count_before = len(prod)

    if body.filter_tvr_enabled:
        # ``filter_tvr_*`` field names conserves (compat front), filtre sur JOr.
        prod = prod[prod["JOr"] > body.filter_tvr_value]

    if body.filter_fc_enabled and "FC" in prod.columns:
        prod = prod[prod["FC"] != 1]

    # 14. Build GeoJSON output
    # Determine geometry column
    geom_key = "geometry" if "geometry" in prod.columns else "__geometry_json"

    # Output schema (cf changements 1+2+3 cumulatifs) :
    #   - agregId, FC : identification.
    #   - JOr/JOrmin/JOrmax : TV redresse journalier (anciennement TVr).
    #   - DPL/DPLmin/DPLmax : debit PL journalier redresse.
    #   - PLred, VLred : recomposition apres arrondi (PLred=DPL, VLred=JOr-DPL).
    #   - DD, HD : direction (bool) et heading (int, degres).
    #   - PM/PMmin/PMmax, PS/PSmin/PSmax : conditionnels (HPM/HPS, v/h).
    #
    # Supprimes par rapport a l'ancien schema : PL (FCD brute), VL, TP, PLr,
    # PLrmin, PLrmax (cf changements 1+2).
    # Colonnes PL (DPL*/PLred/VLred) omises quand le modele PL est absent
    # (pl_enabled=False) — elles n'ont pas de sens sans prediction PL.
    output_columns = [
        "agregId",
        "JOr", "JOrmin", "JOrmax",
    ]
    if "DPL" in prod.columns:
        output_columns.extend(["DPL", "DPLmin", "DPLmax", "PLred", "VLred"])
    output_columns.extend([
        "FC",
        "DD", "HD",
    ])
    if "PM" in prod.columns:
        output_columns.extend(["PM", "PMmin", "PMmax"])
    if "PS" in prod.columns:
        output_columns.extend(["PS", "PSmin", "PSmax"])
    # Diagnostics saturation PL v3 (cf SATURATION_PL_specs.md v3.0). Exposes
    # uniquement si la saturation a effectivement tourne ; sinon les colonnes
    # n'existent pas dans prod (backward compat avec generations sans v3).
    if "alpha_eff" in prod.columns:
        output_columns.append("alpha_eff")
    if "alpha_source" in prod.columns:
        output_columns.append("alpha_source")
    # ``is_critical_zone`` est exposee uniquement en v3 (override actif).
    if "is_critical_zone" in prod.columns:
        output_columns.append("is_critical_zone")
    # Popup hint for front-end MapLibre viewer (MapView.tsx):
    #   PM (v/h) — max PMmax / min PMmin (heure de pointe matin)
    #   PS (v/h) — max PSmax / min PSmin (heure de pointe soir)
    # Display these lines conditionally when the corresponding properties are
    # present in feature.properties — same pattern as JOr/DPL but with v/h unit.
    # Coord precision : 5 decimals = ~1 m, plenty for traffic display
    # (cf ``services.geo.DEFAULT_COORD_DECIMALS`` / ``_round_coords_helper``).

    # Performance : on bascule de ``iterrows()`` (slow, > 100 ms / 10k rows) vers
    # ``to_dict(orient='records')`` qui materialise un seul fois la liste de
    # dicts puis itere en pur Python. Comportement identique a iterrows() pour
    # les types numpy (ils restent dans le dict) ; le traitement defensif
    # int/float/bool/NaN ci-dessous gere la conversion JSON-safe.
    records = prod.to_dict(orient="records")

    features = []
    for row in records:
        # Parse geometry
        geom = row.get(geom_key)
        if isinstance(geom, str):
            try:
                geom = json.loads(geom)
            except Exception:
                geom = None
        elif not isinstance(geom, dict):
            geom = None
        if geom is not None:
            geom = _round_coords_helper(geom)

        props = {}
        for col in output_columns:
            if col in row:
                v = row[col]
                if isinstance(v, (np.integer, np.floating)):
                    v = v.item()
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    v = None
                if isinstance(v, (np.bool_,)):
                    v = bool(v)
                props[col] = v

        features.append({"type": "Feature", "geometry": geom, "properties": props})

    geojson = {"type": "FeatureCollection", "features": features}

    # Store in session for later download
    session_manager.store_data(body.session_id, "carte_geojson", geojson)

    # Compute stats (le champ API ``mean_tvr`` est alimente avec la moyenne
    # de JOr — la grandeur a ete renommee mais le nom du champ est conserve
    # pour compat front-end, cf CarteStats docstring).
    mean_jor = None
    mean_dpl = None
    if len(prod) > 0:
        mean_jor = round(float(prod["JOr"].mean()), 1)
        if "DPL" in prod.columns:
            mean_dpl = round(float(prod["DPL"].mean()), 1)

    stats = CarteStats(
        total_segments=count_before,
        filtered_segments=len(prod),
        mean_tvr=mean_jor,
        mean_dpl=mean_dpl,
    )

    logger.info(
        "Carte generated: session=%s total=%d filtered=%d mean_jor=%s mean_dpl=%s",
        body.session_id, count_before, len(prod), mean_jor, mean_dpl,
    )

    return CarteGenerateResponse(
        session_id=body.session_id,
        stats=stats,
        geojson_feature_count=len(features),
    )


@router.get("/download/{session_id}")
async def download_carte(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Download the generated carte GeoJSON."""
    from fastapi.responses import JSONResponse

    session = require_owned_session(session_id, current_user)

    geojson = session.data.get("carte_geojson")
    if geojson is None:
        raise HTTPException(status_code=400, detail="Aucune carte generee. Lancez la generation d'abord.")

    return JSONResponse(
        content=geojson,
        headers={
            "Content-Disposition": f'attachment; filename="carte_debits_{session_id[:8]}.geojson"',
            "Content-Type": "application/geo+json",
        },
    )


# ---------------------------------------------------------------------------
# Inline viewer endpoints — feed the /carte/visualiser/[id] page
# ---------------------------------------------------------------------------
#
# Two flavours :
#   - /api/carte/result/{session_id}     -> live carte generated in the user
#                                            session (auth required, IDOR-safe).
#   - /api/carte/result-dev/light        -> dev fallback that streams the
#                                            static 2025_light.geojson from
#                                            disk (no session needed). Lets
#                                            front devs preview the viewer
#                                            without re-running a full
#                                            generation each time.
#
# Both serve ``application/geo+json`` inline (no Content-Disposition: attachment)
# so the browser hands the bytes to the MapLibre source instead of opening
# the save-as dialog.

def _find_light_geojson() -> Path | None:
    """Return the first existing light geojson candidate, or None.

    Candidats recherches dans l'ordre :

      1. Override via setting ``LIGHT_GEOJSON_PATH`` si configure (optionnel).
      2. ``WORKSPACE_ROOT/light_geojson/2025_light.geojson`` (deploiement standard).
      3. Repo: ``scripts/map_2025_light/2025_light.min.geojson`` (dev / CI).

    Le chemin absolu d'origine (poste de travail operateur) a ete retire
    (TODO: remove hardcoded path) — desormais on s'appuie sur la
    configuration ou le repo.
    """
    candidates: list[Path] = []

    settings = get_settings()
    # 1. Override explicite via settings (sera ajoute dans config.py si besoin).
    override = getattr(settings, "LIGHT_GEOJSON_PATH", None)
    if override:
        candidates.append(Path(override))

    # 2. Recherche dans le workspace root standard.
    try:
        ws_root = Path(settings.WORKSPACE_ROOT)
        candidates.append(ws_root / "light_geojson" / "2025_light.geojson")
        candidates.append(ws_root / "light_geojson" / "2025_light.min.geojson")
    except Exception:  # noqa: BLE001
        pass

    # 3. Repo (scripts/map_2025_light/) — fallback dev / CI.
    candidates.append(
        Path(__file__).resolve().parents[3] / "scripts" / "map_2025_light" / "2025_light.min.geojson",
    )

    for cand in candidates:
        try:
            if cand.exists() and cand.is_file():
                return cand
        except OSError:
            continue
    return None


@router.get("/result/{session_id}")
async def get_carte_result(
    session_id: str,
    current_user: UserRecord = Depends(get_current_user),
):
    """Serve the generated carte GeoJSON inline for the map viewer.

    Same payload as ``/api/carte/download/{session_id}`` but with cache-friendly
    headers and no attachment disposition (the front-end MapLibre source
    consumes the URL directly).
    """
    from fastapi.responses import JSONResponse

    session = require_owned_session(session_id, current_user)

    geojson = session.data.get("carte_geojson")
    if geojson is None:
        raise HTTPException(
            status_code=404,
            detail="Aucune carte generee pour cette session. Lancez la generation d'abord.",
        )

    feature_count = 0
    try:
        feats = geojson.get("features") if isinstance(geojson, dict) else None
        if isinstance(feats, list):
            feature_count = len(feats)
    except Exception:  # noqa: BLE001 — defensive only
        feature_count = 0

    return JSONResponse(
        content=geojson,
        headers={
            "Content-Type": "application/geo+json",
            # Carte is regenerated on-demand; cache per session for an hour
            # so the viewer can be panned/zoomed without refetching.
            "Cache-Control": "private, max-age=3600",
            "X-Carte-Features": str(feature_count),
        },
    )


@router.get("/result-dev/light")
async def get_carte_result_dev_light(
    current_user: UserRecord = Depends(get_current_user),
):
    """Dev-mode endpoint that streams the static 2025_light.geojson from disk.

    Avoids the need to regenerate a full carte every time the front-end map
    viewer is iterated on. Auth still required (any logged-in user can pull
    the public Lyon sample; the file ships ~30-85 MB).
    """
    from fastapi.responses import FileResponse

    path = _find_light_geojson()
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Echantillon 2025_light.geojson introuvable. "
                "Verifiez que le fichier existe dans le dossier Livrables ou "
                "sous scripts/map_2025_light/."
            ),
        )

    return FileResponse(
        path=str(path),
        media_type="application/geo+json",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Carte-Source": "2025_light.geojson",
        },
    )
