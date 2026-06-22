"""Mapping router — auto-detect columns + validate/build learning DataFrame.

Schema cible : 26 colonnes standardisees pour le pipeline TV/PL (FCD HERE +
compteurs locaux). Voir Etape1_MDL_TV.txt pour le breakdown par categorie.

Retrocompat : les datasets historiques (Bordeaux : TMJATV/TMJAFCDTV/car_*/km)
sont auto-mappes vers le nouveau schema via SYNONYMS. Les distances en km
restent en km a ce niveau ; la conversion m<->km est geree au niveau du
service ML si necessaire pour les modeles deja entraines sur les anciens
noms.

L'utilisateur peut ajouter des colonnes additionnelles libres de sa table
source via `ValidateRequest.extra_cols` — elles sont copiees telles quelles
dans le learning_df, en plus des 26 colonnes cibles.
"""

from __future__ import annotations

import json
import logging
from difflib import get_close_matches

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import UserRecord, get_current_user, require_owned_session
from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/mapping", tags=["mapping"])


# ---------------------------------------------------------------------------
# Cible : 26 colonnes standardisees (refonte Etape1_MDL_TV)
# ---------------------------------------------------------------------------

TARGET_COLUMNS: list[str] = [
    # Identification (4)
    "Identifiant",
    "Annee",
    "Adresse",
    "Type Compteur",
    # Comptage capteur (BC = Boucle Comptage) (4)
    "TMJOBCTV",
    "TMJOBCPL",
    "TMJOBCTV_HPM",
    "TMJOBCTV_HPS",
    # FCD HERE (4) — TV/PL journalier + HPM/HPS horaires
    "TMJOFCDTV",
    "TMJOFCDPL",
    "FCD_HPM_TV",
    "FCD_HPS_TV",
    # Taux de penetration (4) — TV/PL journalier + HPM/HPS horaires
    "TxPen",
    "TxPenPL",
    "TxPen_HPM",
    "TxPen_HPS",
    # Mapping & qualite (2)
    "segment_id_match",
    "mapmatch_status",
    # Reseau HERE (1)
    "functional_class",
    # Vitesses FCD lissees (2)
    "avg_speed_kmh",
    "truck_avg_speed_kmh",
    # Distances VL (4)
    "avg_distance_m",
    "avg_distance_before_m",
    "avg_distance_after_m",
    "avg_min_distance_m",
    # Distances PL (4)
    "truck_avg_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_distance_after_m",
    "truck_avg_min_distance_m",
    # Geometrie (3) : geometry + HD (heading FCDREFGLOBAL) + DIR_TRAVEL (direction)
    "geometry",
    "HD",
    "DIR_TRAVEL",
]


# Categories utilisees par le frontend pour grouper l'affichage des targets.
TARGET_GROUPS: dict[str, list[str]] = {
    "Identification": ["Identifiant", "Annee", "Adresse", "Type Compteur"],
    "Comptage capteur": ["TMJOBCTV", "TMJOBCPL", "TMJOBCTV_HPM", "TMJOBCTV_HPS"],
    "FCD HERE": ["TMJOFCDTV", "TMJOFCDPL", "FCD_HPM_TV", "FCD_HPS_TV"],
    "Taux de penetration": ["TxPen", "TxPenPL", "TxPen_HPM", "TxPen_HPS"],
    "Mapping & qualite": ["segment_id_match", "mapmatch_status"],
    "Reseau HERE": ["functional_class"],
    "Vitesses FCD": ["avg_speed_kmh", "truck_avg_speed_kmh"],
    "Distances VL": [
        "avg_distance_m",
        "avg_distance_before_m",
        "avg_distance_after_m",
        "avg_min_distance_m",
    ],
    "Distances PL": [
        "truck_avg_distance_m",
        "truck_avg_distance_before_m",
        "truck_avg_distance_after_m",
        "truck_avg_min_distance_m",
    ],
    "Geometrie": ["geometry", "HD", "DIR_TRAVEL"],
}


# Synonymes : pour chaque cible, liste de noms source acceptes (auto-mapping).
# Inclut la retro-compatibilite des datasets Bordeaux (TMJATV, car_*, etc.).
SYNONYMS: dict[str, list[str]] = {
    # Identification
    "Identifiant": ["NO_DU_POSTE", "no_du_poste", "id_poste", "ID", "id", "Poste"],
    "Annee": ["annee", "ANNEE", "year", "Year", "an"],
    "Adresse": ["adresse compteur", "Adresse compteur", "ADRESSE", "adresse", "Route", "route"],
    "Type Compteur": ["type compteur", "TypeCompteur", "type_compteur", "Type"],
    # Comptage (TMJO = TMJ Ouvre, BC = Boucle Comptage)
    "TMJOBCTV": ["TMJABCTV", "tmjabctv", "TMJOBCTV", "TMJABCTOTAL"],
    "TMJOBCPL": ["TMJABCPL", "tmjabcpl", "TMJOBCPL"],
    "TMJOBCTV_HPM": [
        "TMJABCTV_HPM",
        "tmjabctv_hpm",
        "tmjobctv_hpm",
        "BCTV_HPM",
        "BCTV_h08",
        "BC_HPM_TV",
    ],
    "TMJOBCTV_HPS": [
        "TMJABCTV_HPS",
        "tmjabctv_hps",
        "tmjobctv_hps",
        "BCTV_HPS",
        "BCTV_h17",
        "BC_HPS_TV",
    ],
    # FCD HERE (TMJO = TMJ Ouvre, FCD = Floating Car Data)
    "TMJOFCDTV": ["TMJAFCDTV", "TMJFCDTV", "TMJATV", "tmjafcdtv", "tmjatv"],
    "TMJOFCDPL": ["TMJAFCDPL", "TMJFCDPL", "TMJAPL", "tmjafcdpl", "tmjapl"],
    # FCD HERE horaires (HPM = 8h-9h, HPS = 17h-18h)
    "FCD_HPM_TV": [
        "FCDTV_h08",
        "FCDTV_HPM",
        "FCDTV_hpm",
        "fcdtv_h08",
        "fcd_hpm_tv",
        "FCD_HPM",
        "FCDHPMTV",
        "TMJOFCDTV_HPM",
        "tmjofcdtv_hpm",
    ],
    "FCD_HPS_TV": [
        "FCDTV_h17",
        "FCDTV_HPS",
        "FCDTV_hps",
        "fcdtv_h17",
        "fcd_hps_tv",
        "FCD_HPS",
        "FCDHPSTV",
        "TMJOFCDTV_HPS",
        "tmjofcdtv_hps",
    ],
    # Taux de penetration
    "TxPen": ["TxPen_brut", "TxPenTVRef", "TxPenRef", "TXPENTV", "TXPENTVREF", "txpen"],
    "TxPenPL": ["TxPenPLRef", "TXPENPL", "TXPENPLREF", "txpenpl"],
    # Taux de penetration horaires (HPM = 8h-9h, HPS = 17h-18h)
    "TxPen_HPM": [
        "txpen_hpm",
        "TXPEN_HPM",
        "TxPenHPM",
        "TxPen_HPM_brut",
        "TxPenHPMRef",
        "TXPENHPM",
    ],
    "TxPen_HPS": [
        "txpen_hps",
        "TXPEN_HPS",
        "TxPenHPS",
        "TxPen_HPS_brut",
        "TxPenHPSRef",
        "TXPENHPS",
    ],
    # Mapping HERE
    "segment_id_match": ["LINK_ID", "link_id", "segmentId", "segmentid", "ref_in_id", "REF_IN_ID"],
    "mapmatch_status": ["match_status", "mapmatch", "mapmatch_state", "status"],
    # Reseau
    "functional_class": ["linkFC", "FC", "fc", "FUNCTIONAL_CLASS"],
    # Vitesses FCD
    "avg_speed_kmh": ["car_average_speed_kmh", "avg_speed", "car_speed", "vitesse_voitures_kmh"],
    "truck_avg_speed_kmh": ["truck_average_speed_kmh", "truck_speed", "vitesse_camions_kmh"],
    # Distances VL (m). Note : les anciens datasets Bordeaux sont en km, le
    # synonyme est conserve pour le matching mais l'unite doit etre verifiee.
    "avg_distance_m": ["car_average_distance_km", "car_avg_distance", "avg_distance"],
    "avg_distance_before_m": ["car_distance_before", "avg_dist_before"],
    "avg_distance_after_m": ["car_distance_after", "avg_dist_after"],
    "avg_min_distance_m": ["car_min_average_distance_km", "avg_min_dist", "car_min_distance"],
    # Distances PL (m)
    "truck_avg_distance_m": ["truck_average_distance_km", "truck_avg_distance"],
    "truck_avg_distance_before_m": ["truck_distance_before"],
    "truck_avg_distance_after_m": ["truck_distance_after"],
    "truck_avg_min_distance_m": ["truck_min_average_distance_km", "truck_min_avg_distance"],
    # Geometrie
    "geometry": ["__geometry_json", "geom", "the_geom", "shape", "SHAPE"],
    # Heading (FCDREFGLOBAL : entier degres 0..359) — fallback geometrique
    # cote carte si HD absent (cf carte.py changement 3).
    "HD": ["HD", "heading", "Heading", "Hd", "hd"],
    # Direction de circulation (FCDREFGLOBAL) : "B" = bidirectionnel.
    # Mappe DD (bool) cote carte.
    "DIR_TRAVEL": ["DIR_TRAVEL", "dir_travel", "direction", "Direction"],
}


# Colonnes critiques pour le training TV (features + target principale).
# Si l'une de ces colonnes est manquante apres validation, on warn fort.
CRITICAL_COLS: list[str] = [
    "TMJOBCTV",  # target principale TV
    "TMJOFCDTV",  # feature principale FCD TV
    "TMJOFCDPL",  # feature FCD PL (pour le mix)
    "TxPen",  # cible derivable
    "avg_distance_m",
    "avg_speed_kmh",
    "truck_avg_min_distance_m",
    "truck_avg_speed_kmh",
    "functional_class",
]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AutoMapRequest(BaseModel):
    session_id: str


class ColumnMapping(BaseModel):
    target: str
    source: str | None
    confidence: str  # "exact" | "synonym" | "fuzzy" | "missing"


class AutoMapResponse(BaseModel):
    session_id: str
    mappings: list[ColumnMapping]
    source_columns: list[str]
    unmapped_count: int
    groups: dict[str, list[str]] = {}  # categories d'affichage frontend
    extra_candidates: list[str] = (
        []
    )  # colonnes source non mappees (proposees comme variables additionnelles)


class ValidateRequest(BaseModel):
    session_id: str
    mapping: dict[str, str | None]  # target -> source (user-confirmed)
    extra_cols: list[str] = []  # colonnes additionnelles libres a inclure dans le learning_df
    territory: str = "default"


class ValidateResponse(BaseModel):
    session_id: str
    rows: int
    columns: list[str]
    missing_critical: list[str]
    warnings: list[str]
    preview: list[dict]
    extra_cols: list[str] = []


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _auto_map(source_cols: list[str]) -> tuple[list[ColumnMapping], list[str]]:
    """Auto-detect a source column for each TARGET_COLUMN.

    Returns (mappings, extra_candidates) where extra_candidates are source
    columns that were not chosen by any target — proposed to the user as
    free additional variables.
    """
    source_lower = {c.lower(): c for c in source_cols}
    result: list[ColumnMapping] = []
    used_sources: set[str] = set()

    for target in TARGET_COLUMNS:
        # 1. Exact match (case-insensitive)
        if target.lower() in source_lower:
            src = source_lower[target.lower()]
            result.append(ColumnMapping(target=target, source=src, confidence="exact"))
            used_sources.add(src)
            continue

        # 2. Synonym match (exact, case-insensitive)
        found = None
        for alias in SYNONYMS.get(target, []):
            if alias.lower() in source_lower:
                found = source_lower[alias.lower()]
                break
        if found:
            result.append(ColumnMapping(target=target, source=found, confidence="synonym"))
            used_sources.add(found)
            continue

        # 3. Fuzzy match
        candidates = [c for c in source_lower.keys()]
        matches = get_close_matches(target.lower(), candidates, n=1, cutoff=0.75)
        if matches:
            src = source_lower[matches[0]]
            result.append(ColumnMapping(target=target, source=src, confidence="fuzzy"))
            used_sources.add(src)
            continue

        # 4. Not found
        result.append(ColumnMapping(target=target, source=None, confidence="missing"))

    extra_candidates = [c for c in source_cols if c not in used_sources]
    return result, extra_candidates


def _build_learning_df(
    raw_df: pd.DataFrame,
    mapping: dict[str, str | None],
    extra_cols: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Build the 26-column standardised DataFrame + optional extra columns.

    Returns (df, missing_critical, warnings).
    """
    cols: dict[str, pd.Series] = {}
    warnings: list[str] = []
    n = len(raw_df)

    for target in TARGET_COLUMNS:
        source = mapping.get(target)
        if source is not None and source in raw_df.columns:
            cols[target] = raw_df[source].reset_index(drop=True)
        else:
            cols[target] = pd.Series([np.nan] * n)
            if source is None and target in CRITICAL_COLS:
                warnings.append(f"Colonne critique '{target}' non trouvee dans les donnees source.")

    # Extra columns (libres : ajoutees telles quelles)
    if extra_cols:
        for col in extra_cols:
            if col in raw_df.columns and col not in cols:
                cols[col] = raw_df[col].reset_index(drop=True)

    df = pd.DataFrame(cols)

    # ── Derivations ──────────────────────────────────────────────────────────

    # Derive TxPen if absent : TxPen = TMJOFCDTV / TMJOBCTV * 100
    if "TxPen" in df.columns and df["TxPen"].isna().all():
        tmjofcd = pd.to_numeric(df.get("TMJOFCDTV"), errors="coerce")
        tmjobc = pd.to_numeric(df.get("TMJOBCTV"), errors="coerce")
        mask = tmjobc > 0
        df.loc[mask, "TxPen"] = (tmjofcd[mask] / tmjobc[mask] * 100.0).round(4)

    # Derive TxPenPL if absent : TxPenPL = TMJOFCDPL / TMJOBCPL * 100
    if "TxPenPL" in df.columns and df["TxPenPL"].isna().all():
        tmjofcd_pl = pd.to_numeric(df.get("TMJOFCDPL"), errors="coerce")
        tmjobc_pl = pd.to_numeric(df.get("TMJOBCPL"), errors="coerce")
        mask = tmjobc_pl > 0
        df.loc[mask, "TxPenPL"] = (tmjofcd_pl[mask] / tmjobc_pl[mask] * 100.0).round(4)

    # Derive flag_comptage from "Type Compteur" (Permanent → 1, Temporaire → 0)
    # This column is always added (not in TARGET_COLUMNS to avoid forcing it
    # through the mapping UI), it's used downstream for sample weighting.
    if "Type Compteur" in df.columns:
        types = df["Type Compteur"].astype(str).str.strip().str.lower()
        df["flag_comptage"] = types.str.startswith("perman").astype(int)
        # Fallback to "Per"/"Tou" prefixes used by historical Bordeaux dataset
        legacy_mask = types.isin(["per", "tou"])
        if legacy_mask.any() and df["flag_comptage"].sum() == 0:
            df.loc[legacy_mask, "flag_comptage"] = 1
    else:
        df["flag_comptage"] = 0

    missing_critical = [c for c in CRITICAL_COLS if c in df.columns and df[c].isna().all()]
    if missing_critical:
        warnings.append(
            f"Colonnes critiques manquantes apres mapping : {missing_critical}. "
            "L'entrainement risque d'echouer."
        )

    return df, missing_critical, warnings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auto", response_model=AutoMapResponse)
async def auto_map(
    body: AutoMapRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> AutoMapResponse:
    """Run fuzzy auto-mapping of source columns to the 26 target columns."""
    # P0-2: enforce ownership.
    session = require_owned_session(body.session_id, current_user)

    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        raise HTTPException(status_code=400, detail="Aucun fichier uploade dans cette session.")

    source_cols = list(raw_df.columns)
    mappings, extra_candidates = _auto_map(source_cols)

    # Store proposed mapping
    proposed = {m.target: m.source for m in mappings}
    session_manager.store_data(body.session_id, "proposed_mapping", proposed)

    unmapped = sum(1 for m in mappings if m.source is None)

    logger.info(
        "Auto-map: session=%s mapped=%d/%d extras=%d",
        body.session_id,
        len(mappings) - unmapped,
        len(mappings),
        len(extra_candidates),
    )

    return AutoMapResponse(
        session_id=body.session_id,
        mappings=mappings,
        source_columns=source_cols,
        unmapped_count=unmapped,
        groups=TARGET_GROUPS,
        extra_candidates=extra_candidates,
    )


@router.put("/validate", response_model=ValidateResponse)
async def validate_mapping(
    body: ValidateRequest,
    current_user: UserRecord = Depends(get_current_user),
) -> ValidateResponse:
    """Accept the user-confirmed mapping and build the learning DataFrame."""
    logger.info(
        "validate_mapping: start session=%s territory=%s extras=%d",
        body.session_id,
        body.territory,
        len(body.extra_cols),
    )
    # P0-2: enforce ownership before reading any session data.
    session = require_owned_session(body.session_id, current_user)

    raw_df: pd.DataFrame | None = session.data.get("raw_df")
    if raw_df is None:
        logger.warning("validate_mapping: raw_df missing for session %s", body.session_id)
        raise HTTPException(status_code=400, detail="Aucun fichier uploade dans cette session.")

    # --- Validate mapping payload BEFORE building the DataFrame ---
    # Empty body.mapping or all-None entries cause a confusing 500 deeper in
    # the pipeline. Surface a clear 422 with an actionable message instead.
    if not body.mapping:
        logger.warning("validate_mapping: empty mapping for session %s", body.session_id)
        raise HTTPException(
            status_code=422,
            detail="Mapping vide: aucune colonne mappee. Lancez d'abord /api/mapping/auto puis confirmez les colonnes.",
        )

    mapped_sources = {
        tgt: src for tgt, src in body.mapping.items() if src is not None and str(src).strip() != ""
    }
    if not mapped_sources:
        logger.warning(
            "validate_mapping: no source column mapped for session %s",
            body.session_id,
        )
        raise HTTPException(
            status_code=422,
            detail="Mapping vide: aucune colonne source assignee aux colonnes cibles.",
        )

    # Verify that at least one critical column is mapped to a real source column
    # in raw_df. Without this, training silently produces NaN-only inputs.
    raw_cols = set(raw_df.columns)
    mapped_critical = [
        c for c in CRITICAL_COLS if mapped_sources.get(c) and mapped_sources[c] in raw_cols
    ]
    if not mapped_critical:
        logger.warning(
            "validate_mapping: no critical column mapped (session=%s)",
            body.session_id,
        )
        raise HTTPException(
            status_code=422,
            detail=(
                "Aucune colonne critique mappee parmi: "
                + ", ".join(CRITICAL_COLS)
                + ". Mappez au moins une colonne critique avant de valider."
            ),
        )

    logger.info("validate_mapping: raw_df shape=%s", raw_df.shape)
    df, missing_critical, warnings = _build_learning_df(raw_df, body.mapping, body.extra_cols)
    logger.info(
        "validate_mapping: learning_df built shape=%s missing=%s",
        df.shape,
        missing_critical,
    )

    def _plain(v):
        if v is None or isinstance(v, (str, bool, int)):
            return v
        if isinstance(v, float):
            if v != v or v in (float("inf"), float("-inf")):
                return None
            return v
        if isinstance(v, dict):
            return {str(k): _plain(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_plain(x) for x in v]
        if hasattr(v, "tolist"):
            return _plain(v.tolist())
        return str(v)

    # Coerce geometry -> JSON string so pyarrow doesn't produce nested ndarrays on round-trip
    if "geometry" in df.columns:
        df["geometry"] = df["geometry"].apply(
            lambda v: json.dumps(_plain(v)) if v is not None and not isinstance(v, str) else v
        )

    session_manager.store_data(body.session_id, "learning_df", df)
    session_manager.store_data(body.session_id, "confirmed_mapping", body.mapping)
    session_manager.store_data(body.session_id, "extra_cols", list(body.extra_cols))
    session_manager.store_data(body.session_id, "territory", body.territory)
    logger.info("validate_mapping: session data stored")

    preview_df = df.head(10).copy()
    preview = [
        {col: _plain(row[col]) for col in preview_df.columns} for _, row in preview_df.iterrows()
    ]
    for row in preview:
        for k, v in list(row.items()):
            if v is None:
                row[k] = ""

    logger.info(
        "Mapping validated: session=%s rows=%d missing_critical=%s",
        body.session_id,
        len(df),
        missing_critical,
    )

    return ValidateResponse(
        session_id=body.session_id,
        rows=len(df),
        columns=list(df.columns),
        missing_critical=missing_critical,
        warnings=warnings,
        preview=preview,
        extra_cols=list(body.extra_cols),
    )
