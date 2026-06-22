"""Service de detection et classification des discontinuites JOr/TVr.

Schema migration (2026-05) : le nouveau format de carte expose ``JOr``
(jour ouvre) au lieu de ``TVr``. Le service accepte les deux schemas en
entree — un alias ``JOr -> TVr`` est applique au tout debut du pipeline
(cf. ``_build_directed_edges``). En interne, le code reste base sur
``TVr`` pour preserver la retrocompat avec les anciens scripts CLI.


Refactorisation in-memory des scripts CLI :
    - ``scripts/discontinuity_methodology/run_discontinuity_analysis.py``
    - ``scripts/discontinuity_methodology/build_node_causality_v2.py``
    - ``scripts/discontinuity_methodology/build_node_data_v3.py``

Pipeline applique (cf. documentation interne ``docs/discontinuites_TVr``) :

1. Construction du graphe oriente HERE (in_node/out_node selon suffixe -F/-T).
2. Aggregation par noeud (flow_in / flow_out / ecart).
3. Filtre regle utilisateur :
   - si max(flow) <= 20 000  : ecart > 2 000 v/j
   - sinon                    : ecart > 4 000 v/j
   - tier rouge si ecart >= 2x seuil ; orange sinon.
   - les noeuds frontaliers (n_in == 0 ou n_out == 0) sont exclus.
4. Detection des drivers et scoring d'impact (TMJOFCDTV, TMJOFCDPL,
   functional_class, distance attrs).
5. Cause principale : driver dominant via ``DRIVER_TO_CAUSE`` ; fallback
   en cascade RAMP_asymmetry > ROUNDABOUT_asymmetry > Coverage_gap > Unexplained.
6. Topologie : Bretelle > Carrefour > Continuite.
7. Sortie Point FeatureCollection conforme au schema v3.

Aucun acces disque : la fonction principale ``run_full_pipeline`` prend un
``GeoDataFrame`` en entree et retourne un dict (FeatureCollection JSON-ready).
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes (alignees sur build_node_causality_v2 + build_node_data_v3)
# ---------------------------------------------------------------------------

#: Colonnes input exposees au scoring (year_mapped exclu — constante).
INPUT_COLS: tuple[str, ...] = (
    "TMJOFCDTV",
    "TMJOFCDPL",
    "functional_class",
    "avg_distance_before_m",
    "avg_min_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_min_distance_m",
)

#: Mapping driver -> cause principale (cf. v3 § DRIVER_TO_CAUSE).
DRIVER_TO_CAUSE: dict[str, str] = {
    "TMJOFCDTV": "FCD_TV_cliff",
    "TMJOFCDPL": "FCD_PL_cliff",
    "functional_class": "FC_transition",
    "avg_distance_before_m": "Distance_anomaly",
    "avg_min_distance_m": "Distance_anomaly",
    "truck_avg_distance_before_m": "Distance_anomaly",
    "truck_avg_min_distance_m": "Distance_anomaly",
}

#: Libelles FR accentues pour l'UI.
CAUSE_LABELS_FR: dict[str, str] = {
    "FCD_TV_cliff": "Falaise FCD VL",
    "FCD_PL_cliff": "Falaise FCD PL",
    "Coverage_gap": "Trou de couverture FCD",
    "Distance_anomaly": "Anomalie de distance",
    "RAMP_asymmetry": "Bretelle asymetrique",
    "ROUNDABOUT_asymmetry": "Rond-point asymetrique",
    "FC_transition": "Transition de classe fonctionnelle (legitime)",
    "Unexplained": "Inexplique (a investiguer)",
}

TOPOLOGY_LABELS_FR: dict[str, str] = {
    "Bretelle": "Bretelle",
    "Carrefour": "Carrefour",
    "Continuite": "Continuite segment",
}

CAUSE_PALETTE: dict[str, str] = {
    "FCD_TV_cliff": "#E41A1C",
    "FCD_PL_cliff": "#B30000",
    "Coverage_gap": "#7B1FA2",
    "Distance_anomaly": "#FF7F00",
    "RAMP_asymmetry": "#FFB000",
    "ROUNDABOUT_asymmetry": "#A65628",
    "FC_transition": "#377EB8",
    "Unexplained": "#999999",
}

TOPOLOGY_PALETTE: dict[str, str] = {
    "Bretelle": "#87CEEB",
    "Carrefour": "#4682B4",
    "Continuite": "#FFA07A",
}

#: Seuils de la regle utilisateur (cf. memoire § 2).
USER_RULE_LOW_THRESHOLD = 2000.0
USER_RULE_HIGH_THRESHOLD = 4000.0
USER_RULE_PIVOT = 20000.0

#: Seuils de detection des drivers.
RATIO_THRESHOLD = 1.5
FC_DELTA_THRESHOLD = 2
TMJOFCDTV_ZERO = 1.0
TMJOFCDPL_ZERO = 0.5

#: Cap d'affichage des aretes par cote (4 + libelle "(+N autres)").
MAX_EDGES_PER_SIDE = 4

#: Cause priority for tie-breaking (must match v2).
CAUSE_PRIORITY: list[str] = [
    "FCD_TV_cliff",
    "FCD_PL_cliff",
    "FC_transition",
    "RAMP_asymmetry",
    "ROUNDABOUT_asymmetry",
    "Distance_anomaly",
    "Coverage_gap",
]

#: Colonnes FCD a joindre depuis FCDREFGLOBAL.parquet (clef = segment_id).
#: Manquantes -> tolerees (le pipeline retombe en mode degrade pour ces drivers).
#:
#: Noms cibles utilises en interne par le pipeline (cf. INPUT_COLS). Le parquet
#: FCDREFGLOBAL_2025 reel utilise des noms differents — le mapping de
#: ``FCD_COLUMN_MAPPING`` ci-dessous traduit les colonnes source vers ces noms
#: canoniques pendant la jointure (cf. ``join_fcdref``).
FCD_JOIN_COLUMNS: tuple[str, ...] = (
    "TMJOFCDTV",
    "TMJOFCDPL",
    "functional_class",
    "RAMP",
    "ROUNDABOUT",
    "avg_distance_before_m",
    "avg_min_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_min_distance_m",
)

#: Mapping de colonnes du parquet source -> nom canonique attendu en interne.
#: Format : ``(target_name, scale_factor)``. Le scale convertit l'unite source
#: vers l'unite interne attendue (par ex. km -> m via x1000).
#: Plusieurs alias possibles convergent vers le meme target — le premier
#: alias rencontre dans le parquet gagne.
FCD_COLUMN_MAPPING: dict[str, tuple[str, float]] = {
    # FCD bruts (parquet FCDREFGLOBAL : TMJFCDTV/PL ; certains exports anciens : TMJOFCDTV/PL)
    "TMJFCDTV": ("TMJOFCDTV", 1.0),
    "TMJOFCDTV": ("TMJOFCDTV", 1.0),
    "TMJFCDPL": ("TMJOFCDPL", 1.0),
    "TMJOFCDPL": ("TMJOFCDPL", 1.0),
    # Functional class
    "FUNC_CLASS": ("functional_class", 1.0),
    "functional_class": ("functional_class", 1.0),
    # Distances : le parquet expose des km ; on convertit en m pour homogeneite
    # avec les anciens scripts qui utilisaient des suffixes "_m".
    "car_average_distance_before_km": ("avg_distance_before_m", 1000.0),
    "car_average_distance_before_m": ("avg_distance_before_m", 1.0),
    "avg_distance_before_m": ("avg_distance_before_m", 1.0),
    "car_min_average_distance_km": ("avg_min_distance_m", 1000.0),
    "car_min_average_distance_m": ("avg_min_distance_m", 1.0),
    "avg_min_distance_m": ("avg_min_distance_m", 1.0),
    "truck_average_distance_before_km": ("truck_avg_distance_before_m", 1000.0),
    "truck_average_distance_before_m": ("truck_avg_distance_before_m", 1.0),
    "truck_avg_distance_before_m": ("truck_avg_distance_before_m", 1.0),
    "truck_min_average_distance_km": ("truck_avg_min_distance_m", 1000.0),
    "truck_min_average_distance_m": ("truck_avg_min_distance_m", 1.0),
    "truck_avg_min_distance_m": ("truck_avg_min_distance_m", 1.0),
    # Topology flags (pas de transformation). Les variantes booleens 'is_ramp'
    # / 'is_roundabout' du FCDREFGLOBAL ne sont PAS mappees ici car le pipeline
    # attend des chaines "Y"/"N" majuscules — un alias bool produirait
    # "TRUE"/"FALSE" et serait classe en absent par defaut. Si besoin, le
    # mapping pourra etre etendu avec un transformer bool -> "Y"/"N".
    "RAMP": ("RAMP", 1.0),
    "ROUNDABOUT": ("ROUNDABOUT", 1.0),
    # Graph HERE endpoints — permettent au pipeline de reconstruire l'adjacence
    # quand le geojson "light" ne porte pas REF_IN_ID/NREF_IN_ID.
    "REF_IN_ID": ("REF_IN_ID", 1.0),
    "NREF_IN_ID": ("NREF_IN_ID", 1.0),
    # Distances et vitesses additionnelles (FCDREFGLOBAL_2025.geojson, deja en m).
    "car_average_distance_m": ("avg_distance_m", 1.0),
    "car_average_distance_after_m": ("avg_distance_after_m", 1.0),
    "truck_average_distance_m": ("truck_avg_distance_m", 1.0),
    "truck_average_distance_after_m": ("truck_avg_distance_after_m", 1.0),
    "car_average_speed_kmh": ("avg_speed_kmh", 1.0),
    "truck_average_speed_kmh": ("truck_avg_speed_kmh", 1.0),
    # Annee : forme avec majuscule -> canonique minuscule.
    "Annee": ("annee", 1.0),
}

#: Alias acceptes pour la cle de jointure cote parquet FCD.
#: Le premier alias trouve est renomme en "segment_id" avant la jointure.
FCD_JOIN_KEY_ALIASES: tuple[str, ...] = ("segment_id", "AgregId", "agregId")

#: Colonnes minimales requises dans le parquet FCD pour qu'un upload soit accepte.
#: On accepte plusieurs alias pour la cle de jointure (cf. FCD_JOIN_KEY_ALIASES) :
#: la validation passe si **au moins un** alias est present.
FCD_REQUIRED_COLUMNS: tuple[str, ...] = ("segment_id",)


# ---------------------------------------------------------------------------
# Helpers numerique
# ---------------------------------------------------------------------------


def _safe_float(x: Any) -> float | None:
    """Conversion en float, None si NaN/inf/non castable."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _round_or_none(x: Any, ndigits: int = 1) -> float | None:
    v = _safe_float(x)
    return None if v is None else round(v, ndigits)


def _first_last_coords(geom: Any) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Retourne ((lon0,lat0), (lonN,latN)) pour une LineString/MultiLineString.

    Renvoie ``None`` si la geometrie est vide ou non-supportee.
    """
    if geom is None:
        return None
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        if not coords:
            return None
        return (
            (float(coords[0][0]), float(coords[0][1])),
            (float(coords[-1][0]), float(coords[-1][1])),
        )
    if isinstance(geom, MultiLineString):
        for line in geom.geoms:
            coords = list(line.coords)
            if coords:
                # On garde le premier brin avec des coords
                return (
                    (float(coords[0][0]), float(coords[0][1])),
                    (float(coords[-1][0]), float(coords[-1][1])),
                )
        return None
    return None


# ---------------------------------------------------------------------------
# Stage 1 — Normalisation des edges (in_node / out_node / inputs)
# ---------------------------------------------------------------------------


def _build_directed_edges(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Construit le DataFrame d'aretes orientees + extrait les input cols.

    Applique :
      - filtrage des endpoints NaN et auto-boucles ;
      - dedup par agregId (keep first) ;
      - calcul in_node/out_node selon le suffixe -F/-T de agregId ;
      - extraction coordonnees endpoints (lon/lat) pour la geolocalisation
        des noeuds dans le rendu final.
    """
    if "agregId" not in gdf.columns:
        raise ValueError("Colonne 'agregId' manquante dans le GeoDataFrame.")

    # Schema migration (2026-05): le nouveau format expose `JOr` (jour ouvre)
    # au lieu de `TVr`. Le pipeline interne reste base sur `TVr` pour preserver
    # la retrocompat — on alias `JOr -> TVr` ici si seul `JOr` est present.
    # Si les deux existent, on prefere `JOr` (referentiel canonique 2026+).
    has_tvr = "TVr" in gdf.columns
    has_jor = "JOr" in gdf.columns
    if not has_tvr and not has_jor:
        raise ValueError(
            "Colonne de debit manquante dans le GeoDataFrame : il faut "
            "au moins une des colonnes 'JOr' (nouveau schema) ou 'TVr' (legacy)."
        )

    df = gdf.copy()
    if has_jor:
        # On copie/ecrase TVr depuis JOr — referentiel canonique 2026+.
        df["TVr"] = df["JOr"]
        if not has_tvr:
            logger.info(
                "Discontinuites: aliasing JOr -> TVr (nouveau schema, %d aretes)",
                len(df),
            )

    # Endpoints HERE : si absents, impossible de reconstruire le graphe.
    if "REF_IN_ID" not in df.columns or "NREF_IN_ID" not in df.columns:
        raise ValueError(
            "Colonnes 'REF_IN_ID' / 'NREF_IN_ID' manquantes : impossible de "
            "construire le graphe HERE."
        )

    df["REF_IN_ID"] = pd.to_numeric(df["REF_IN_ID"], errors="coerce")
    df["NREF_IN_ID"] = pd.to_numeric(df["NREF_IN_ID"], errors="coerce")
    df["TVr"] = pd.to_numeric(df["TVr"], errors="coerce").astype("float64")

    # Drop endpoints invalides et auto-boucles
    mask_valid = (
        df["REF_IN_ID"].notna() & df["NREF_IN_ID"].notna() & (df["REF_IN_ID"] != df["NREF_IN_ID"])
    )
    n_dropped = int((~mask_valid).sum())
    if n_dropped:
        logger.info("Discontinuites: %d aretes ignorees (endpoints invalides / loop)", n_dropped)
    df = df.loc[mask_valid].copy()

    # Dedup agregId (keep first) — methodologie : duplicate agregId est rare
    df = df.drop_duplicates(subset="agregId", keep="first").reset_index(drop=True)

    df["REF_IN_ID"] = df["REF_IN_ID"].astype("int64")
    df["NREF_IN_ID"] = df["NREF_IN_ID"].astype("int64")

    # Direction depuis suffixe -F/-T (cf. methodologie § 4.2)
    suffix = df["agregId"].astype(str).str.extract(r"-([FT])$", expand=False)
    is_T = (suffix == "T").fillna(False).to_numpy()
    df["in_node"] = np.where(is_T, df["NREF_IN_ID"].to_numpy(), df["REF_IN_ID"].to_numpy()).astype(
        "int64"
    )
    df["out_node"] = np.where(is_T, df["REF_IN_ID"].to_numpy(), df["NREF_IN_ID"].to_numpy()).astype(
        "int64"
    )

    # Endpoints geometriques pour reconstruire les coords des noeuds.
    # Convention : pour un edge T, l'in_node est NREF (= last coord), l'out_node REF (= first coord).
    # Pour F/O, l'in_node est REF (first), out_node NREF (last).
    coords_pairs: list[tuple[tuple[float, float] | None, tuple[float, float] | None]] = []
    for geom in df.geometry.to_numpy():
        fl = _first_last_coords(geom)
        coords_pairs.append((fl[0], fl[1]) if fl else (None, None))

    in_node_coords: list[tuple[float, float] | None] = []
    out_node_coords: list[tuple[float, float] | None] = []
    for (first_pt, last_pt), is_T_row in zip(coords_pairs, is_T, strict=False):
        if is_T_row:
            in_node_coords.append(last_pt)
            out_node_coords.append(first_pt)
        else:
            in_node_coords.append(first_pt)
            out_node_coords.append(last_pt)
    df["in_node_coord"] = in_node_coords
    df["out_node_coord"] = out_node_coords

    # Pre-compute auxiliary cols utilises au scoring/topology. Manque = NaN.
    optional_cols: dict[str, Any] = {
        "RAMP": "",
        "ROUNDABOUT": "",
        "FC": np.nan,
        "TMJOFCDTV": np.nan,
        "TMJOFCDPL": np.nan,
        "functional_class": np.nan,
        "avg_distance_before_m": np.nan,
        "avg_min_distance_m": np.nan,
        "truck_avg_distance_before_m": np.nan,
    }
    for col, default in optional_cols.items():
        if col not in df.columns:
            df[col] = default

    # Cast string cols to upper for asymmetry detection
    df["RAMP"] = df["RAMP"].astype(str).str.upper()
    df["ROUNDABOUT"] = df["ROUNDABOUT"].astype(str).str.upper()
    # Si la colonne functional_class est manquante mais FC est presente,
    # on copie pour homogeneiser le scoring (memoire § 5.1).
    if df["functional_class"].isna().all() and df["FC"].notna().any():
        df["functional_class"] = pd.to_numeric(df["FC"], errors="coerce")

    return df


# ---------------------------------------------------------------------------
# Stage 2 — Detection des noeuds (regle utilisateur)
# ---------------------------------------------------------------------------


def _build_node_table(edges: pd.DataFrame) -> pd.DataFrame:
    """Aggrege par noeud les flux in/out et calcule l'ecart + tier.

    Renvoie un DataFrame ``[node_id, in_flow, out_flow, n_in, n_out, max_flow,
    ecart, threshold, tier, is_boundary, is_flagged, lon, lat]``.

    Caveat sur ``n_total_nodes`` (compte la longueur du DataFrame renvoye) :
    la valeur est calculee sur ``np.unique(in_node) U np.unique(out_node)``
    apres dedup ``agregId``. Quand le geojson amont contient des paires
    sibling -F/-T pour chaque arc, certains REF_IN_ID/NREF_IN_ID sont
    naturellement partages entre les deux directions et le total tombe a
    environ la moitie du chiffre attendu pour le referentiel v4 (qui compte
    autrement les "noeuds" via une autre granularite). Ce n'est pas un bug
    de la logique flux/ecart : seule la statistique ``n_total_nodes`` differe.
    """
    valid_tvr = edges["TVr"].fillna(0).clip(lower=0)
    tmp = edges[["in_node", "out_node"]].copy()
    tmp["TVr"] = valid_tvr

    # Note : in_node est l'origine d'un edge sortant ; donc out_flow agrege sur in_node.
    out_flow = tmp.groupby("in_node")["TVr"].sum().rename("out_flow")
    in_flow = tmp.groupby("out_node")["TVr"].sum().rename("in_flow")
    n_out = tmp.groupby("in_node").size().rename("n_out")
    n_in = tmp.groupby("out_node").size().rename("n_in")

    nodes = pd.concat([in_flow, out_flow, n_in, n_out], axis=1).fillna(0.0)
    nodes.index.name = "node_id"
    nodes = nodes.reset_index()
    nodes["n_in"] = nodes["n_in"].astype(np.int32)
    nodes["n_out"] = nodes["n_out"].astype(np.int32)
    nodes["max_flow"] = nodes[["in_flow", "out_flow"]].max(axis=1)
    nodes["ecart"] = (nodes["in_flow"] - nodes["out_flow"]).abs()
    nodes["is_boundary"] = (nodes["n_in"] == 0) | (nodes["n_out"] == 0)

    # Seuil bimodal (cf. methodologie § 2)
    nodes["threshold"] = np.where(
        nodes["max_flow"] > USER_RULE_PIVOT,
        USER_RULE_HIGH_THRESHOLD,
        USER_RULE_LOW_THRESHOLD,
    )
    nodes["is_flagged"] = (~nodes["is_boundary"]) & (nodes["ecart"] > nodes["threshold"])
    nodes["tier"] = np.where(nodes["ecart"] >= 2 * nodes["threshold"], "red", "orange")

    # Coords noeud — premiere coord trouvee via les edges incidents.
    # On rassemble (node_id -> (lon, lat)) en parcourant les edges.
    node_coords: dict[int, tuple[float, float]] = {}
    in_node_arr = edges["in_node"].to_numpy()
    out_node_arr = edges["out_node"].to_numpy()
    in_coords = edges["in_node_coord"].to_numpy()
    out_coords = edges["out_node_coord"].to_numpy()
    for nid, coord in zip(in_node_arr, in_coords, strict=False):
        if coord is None:
            continue
        nid_i = int(nid)
        if nid_i not in node_coords:
            node_coords[nid_i] = coord
    for nid, coord in zip(out_node_arr, out_coords, strict=False):
        if coord is None:
            continue
        nid_i = int(nid)
        if nid_i not in node_coords:
            node_coords[nid_i] = coord

    nodes["lon"] = nodes["node_id"].map(lambda nid: node_coords.get(int(nid), (None, None))[0])
    nodes["lat"] = nodes["node_id"].map(lambda nid: node_coords.get(int(nid), (None, None))[1])
    return nodes


# ---------------------------------------------------------------------------
# Stage 3 — Scoring des drivers + classification
# ---------------------------------------------------------------------------


def _detect_drivers(all_edges: pd.DataFrame) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Detection des drivers + scoring d'impact.

    Reprend exactement la logique de ``build_node_causality_v2._detect_drivers``
    (cf. memoire § 6.1) :

      - TMJOFCDTV/PL  : ratio = max/min (apres replace(0 -> 1)) ; eligible si
        ratio >= 1.5 ; rank_score = ratio * log(max + 1).
      - functional_class : delta = max - min ; eligible si delta >= 2 ;
        rank_score = delta * 5.
      - distances : ratio max/min ; eligible si ratio >= 1.5 ; rank_score = ratio.
    """
    scores: dict[str, dict[str, Any]] = {}

    for col in INPUT_COLS:
        if col not in all_edges.columns:
            continue
        arr_all = pd.to_numeric(all_edges[col], errors="coerce").to_numpy(dtype=np.float64)
        arr = arr_all[np.isfinite(arr_all)]
        if arr.size < 2:
            continue

        if col == "functional_class":
            mx = int(arr.max())
            mn = int(arr.min())
            delta = mx - mn
            if delta >= FC_DELTA_THRESHOLD:
                rank_score = delta * 5.0
                scores[col] = {
                    "max": mx,
                    "min": mn,
                    "delta": delta,
                    "rank_score": float(rank_score),
                }
        else:
            arr_for_ratio = np.where(arr <= 0, 1.0, arr)
            mx_safe = float(arr_for_ratio.max())
            mn_safe = float(arr_for_ratio.min())
            ratio = mx_safe / mn_safe if mn_safe > 0 else 0.0
            if ratio >= RATIO_THRESHOLD:
                mx = float(arr.max())
                mn = float(arr.min())
                delta = mx - mn
                if col in ("TMJOFCDTV", "TMJOFCDPL"):
                    rank_score = ratio * math.log(mx + 1.0)
                else:
                    rank_score = ratio
                scores[col] = {
                    "max": _round_or_none(mx, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "min": _round_or_none(mn, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "ratio": round(ratio, 2),
                    "delta": _round_or_none(delta, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "rank_score": float(rank_score),
                }

    ordered = sorted(scores.keys(), key=lambda k: -scores[k]["rank_score"])
    for rank, key in enumerate(ordered, start=1):
        scores[key]["rank"] = rank
        scores[key].pop("rank_score", None)
    return ordered, scores


def _classify_topology(
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
) -> str:
    """Bretelle > Carrefour > Continuite (cf. memoire § 7)."""
    has_ramp = False
    has_rdb = False
    for df in (in_edges, out_edges):
        if df.empty:
            continue
        if "RAMP" in df.columns and df["RAMP"].astype(str).str.upper().eq("Y").any():
            has_ramp = True
        if "ROUNDABOUT" in df.columns and df["ROUNDABOUT"].astype(str).str.upper().eq("Y").any():
            has_rdb = True

    if has_ramp:
        return "Bretelle"

    n_in = len(in_edges)
    n_out = len(out_edges)
    total = n_in + n_out
    if has_rdb or total >= 3:
        return "Carrefour"
    if n_in == 1 and n_out == 1:
        return "Continuite"
    # Degenere (1 cote a 0) — securite : Carrefour.
    return "Carrefour"


def _classify_principal_cause(
    drivers: list[str],
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
) -> str:
    """Cause principale via cascade driver > topologie (cf. memoire § 5.2)."""
    if drivers:
        top = drivers[0]
        return DRIVER_TO_CAUSE.get(top, "Unexplained")

    # Fallback cascade
    def _flags(df: pd.DataFrame, col: str) -> list[str]:
        if df.empty or col not in df.columns:
            return []
        return [str(v).upper() for v in df[col].tolist()]

    ramp_flags = _flags(in_edges, "RAMP") + _flags(out_edges, "RAMP")
    rdb_flags = _flags(in_edges, "ROUNDABOUT") + _flags(out_edges, "ROUNDABOUT")

    has_ramp_y = any(f == "Y" for f in ramp_flags)
    has_ramp_n = any(f == "N" for f in ramp_flags)
    if has_ramp_y and has_ramp_n:
        return "RAMP_asymmetry"

    has_rdb_y = any(f == "Y" for f in rdb_flags)
    has_rdb_n = any(f == "N" for f in rdb_flags)
    if has_rdb_y and has_rdb_n:
        return "ROUNDABOUT_asymmetry"

    all_edges = (
        pd.concat([in_edges, out_edges], ignore_index=True)
        if (len(in_edges) or len(out_edges))
        else in_edges.iloc[0:0]
    )
    if len(all_edges) > 0:
        tv = pd.to_numeric(
            all_edges.get("TMJOFCDTV", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        pl = pd.to_numeric(
            all_edges.get("TMJOFCDPL", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        if ((tv < TMJOFCDTV_ZERO) | (pl < TMJOFCDPL_ZERO)).any():
            return "Coverage_gap"

    return "Unexplained"


# ---------------------------------------------------------------------------
# Stage 4 — Narratives (compactes, JSON-safe)
# ---------------------------------------------------------------------------


def _format_int(v: Any) -> str:
    if v is None:
        return "?"
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "?"


def _format_float(v: Any, ndigits: int = 1) -> str:
    if v is None:
        return "?"
    try:
        return f"{float(v):.{ndigits}f}"
    except (TypeError, ValueError):
        return "?"


def _build_narrative(
    cause: str,
    drivers: list[str],
    scores: dict[str, dict[str, Any]],
    ecart: float,
) -> str:
    """Narrative compacte avec les valeurs reelles du driver dominant."""

    def s(k: str) -> dict[str, Any]:
        return scores.get(k, {})

    if cause == "FCD_TV_cliff":
        x = s("TMJOFCDTV")
        return (
            f"Saut FCD VL : max {_format_int(x.get('max'))} v/j "
            f"vs min {_format_int(x.get('min'))} v/j "
            f"(x{x.get('ratio', 0):.1f})."
        )
    if cause == "FCD_PL_cliff":
        x = s("TMJOFCDPL")
        return (
            f"Saut FCD PL : max {_format_int(x.get('max'))} v/j "
            f"vs min {_format_int(x.get('min'))} v/j "
            f"(x{x.get('ratio', 0):.1f})."
        )
    if cause == "FC_transition":
        x = s("functional_class")
        return (
            f"Changement de classe fonctionnelle FC "
            f"{x.get('min', '?')}->{x.get('max', '?')} (transition legitime)."
        )
    if cause == "RAMP_asymmetry":
        return "Bretelle asymetrique entre branches (R=Y/N)."
    if cause == "ROUNDABOUT_asymmetry":
        return f"Rond-point asymetrique (R=Y/N) avec ecart " f"{_format_int(ecart)} v/j."
    if cause == "Distance_anomaly":
        for col in ("avg_distance_before_m", "avg_min_distance_m", "truck_avg_distance_before_m"):
            if col in scores:
                x = scores[col]
                return (
                    f"Anomalie sur {col} : "
                    f"{_format_float(x.get('max'))} m vs "
                    f"{_format_float(x.get('min'))} m "
                    f"(x{x.get('ratio', 0):.1f})."
                )
        return "Anomalie de distance detectee."
    if cause == "Coverage_gap":
        return (
            "Couverture FCD insuffisante : >=50% des arcs adjacents sans "
            "donnee FCD exploitable (NaN ou ~0) et aucun arc avec un trafic "
            "FCD soutenu."
        )
    if cause == "Unexplained":
        return "Aucun driver clair - investigation modele requise."
    return f"Cause : {cause}."


# ---------------------------------------------------------------------------
# Stage 5 — Construction du payload par edge / par noeud
# ---------------------------------------------------------------------------


def _edge_payload(row: pd.Series) -> dict[str, Any]:
    """Convertit une ligne d'edge en dict JSON-safe (agregId, TVr, inputs)."""
    inputs: dict[str, Any] = {}
    for col in INPUT_COLS:
        v = row.get(col)
        if pd.isna(v):
            inputs[col] = None
        elif col == "functional_class":
            try:
                inputs[col] = int(v)
            except (TypeError, ValueError):
                inputs[col] = None
        else:
            inputs[col] = _round_or_none(v, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1)
    return {
        "agregId": str(row.get("agregId", "")),
        "TVr": _round_or_none(row.get("TVr"), 1),
        "inputs": inputs,
    }


def _sort_and_cap_edges(edges_df: pd.DataFrame, side_prefix: str) -> list[dict[str, Any]]:
    """Trie par TVr desc, libelle E1..E4/S1..S4, ajoute "(+N autres)" en tail."""
    if edges_df is None or edges_df.empty:
        return []
    sorted_df = edges_df.copy()
    sorted_df["_tvr_sort"] = pd.to_numeric(sorted_df["TVr"], errors="coerce").fillna(-1.0)
    sorted_df = sorted_df.sort_values("_tvr_sort", ascending=False)

    n_total = len(sorted_df)
    head = sorted_df.head(MAX_EDGES_PER_SIDE)
    out_list: list[dict[str, Any]] = []
    for i, (_, row) in enumerate(head.iterrows(), start=1):
        edge = _edge_payload(row)
        edge["label"] = f"{side_prefix}{i}"
        out_list.append(edge)
    n_extra = n_total - len(out_list)
    if n_extra > 0 and out_list:
        out_list[-1]["label"] = f"{out_list[-1]['label']} (+{n_extra} autres)"
    return out_list


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def detect_discontinuities(gdf: gpd.GeoDataFrame) -> dict[int, dict[str, Any]]:
    """Filtre regle utilisateur — renvoie ``{node_id: node_meta}`` pour les noeuds flagues.

    Inclut les champs ``in_flow, out_flow, n_in, n_out, ecart, tier, max_flow,
    threshold, lon, lat``. Les noeuds frontaliers sont exclus.
    """
    edges = _build_directed_edges(gdf)
    nodes = _build_node_table(edges)
    flagged = nodes[nodes["is_flagged"]].copy()
    out: dict[int, dict[str, Any]] = {}
    for _, row in flagged.iterrows():
        nid = int(row["node_id"])
        out[nid] = {
            "node_id": nid,
            "in_flow": float(row["in_flow"]),
            "out_flow": float(row["out_flow"]),
            "n_in": int(row["n_in"]),
            "n_out": int(row["n_out"]),
            "ecart": float(row["ecart"]),
            "max_flow": float(row["max_flow"]),
            "threshold": float(row["threshold"]),
            "tier": str(row["tier"]),
            "lon": _safe_float(row["lon"]),
            "lat": _safe_float(row["lat"]),
        }
    return out


def compute_node_causality(
    node_meta: dict[str, Any],
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
) -> dict[str, Any]:
    """Calcule pour un noeud les drivers, la cause principale, la topologie, etc.

    Renvoie un dict pret a etre injecte comme ``properties`` d'une feature
    GeoJSON (cf. schema v3).
    """
    all_edges = (
        pd.concat([in_edges, out_edges], ignore_index=True)
        if (len(in_edges) or len(out_edges))
        else in_edges.iloc[0:0]
    )
    drivers, driver_scores = _detect_drivers(all_edges)
    principal_cause = _classify_principal_cause(drivers, in_edges, out_edges)
    topology = _classify_topology(in_edges, out_edges)

    edges_in_payload = _sort_and_cap_edges(in_edges, "E")
    edges_out_payload = _sort_and_cap_edges(out_edges, "S")
    narrative = _build_narrative(
        principal_cause, drivers, driver_scores, node_meta.get("ecart", 0.0)
    )

    return {
        "node_id": str(node_meta["node_id"]),
        "ecart": round(float(node_meta["ecart"]), 1),
        "flow_in": round(float(node_meta["in_flow"]), 1),
        "flow_out": round(float(node_meta["out_flow"]), 1),
        "n_in": int(node_meta["n_in"]),
        "n_out": int(node_meta["n_out"]),
        "max_flow": round(float(node_meta["max_flow"]), 1),
        "threshold": float(node_meta["threshold"]),
        "tier": str(node_meta["tier"]),
        "principal_cause": principal_cause,
        "topology": topology,
        "narrative": narrative,
        "drivers": drivers,
        "driver_scores": driver_scores,
        "edges_in": edges_in_payload,
        "edges_out": edges_out_payload,
    }


def _detect_drivers_from_arrays(
    indices: np.ndarray,
    arr_by_col: dict[str, np.ndarray],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Variante vectorisee de ``_detect_drivers`` operant sur des arrays prealloues.

    ``indices`` est l'ensemble des positions d'edges incidents (in + out) au noeud
    et ``arr_by_col`` un dict ``col_name -> np.ndarray[float64]`` pre-genere une
    seule fois pour tout le reseau. Aucune conversion pandas par noeud.
    """
    scores: dict[str, dict[str, Any]] = {}
    if indices.size < 2:
        return [], scores

    for col in INPUT_COLS:
        arr_full = arr_by_col.get(col)
        if arr_full is None:
            continue
        arr_all = arr_full[indices]
        arr = arr_all[np.isfinite(arr_all)]
        if arr.size < 2:
            continue

        if col == "functional_class":
            mx = int(arr.max())
            mn = int(arr.min())
            delta = mx - mn
            if delta >= FC_DELTA_THRESHOLD:
                rank_score = delta * 5.0
                scores[col] = {
                    "max": mx,
                    "min": mn,
                    "delta": delta,
                    "rank_score": float(rank_score),
                }
        else:
            arr_for_ratio = np.where(arr <= 0, 1.0, arr)
            mx_safe = float(arr_for_ratio.max())
            mn_safe = float(arr_for_ratio.min())
            ratio = mx_safe / mn_safe if mn_safe > 0 else 0.0
            if ratio >= RATIO_THRESHOLD:
                mx = float(arr.max())
                mn = float(arr.min())
                delta = mx - mn
                if col in ("TMJOFCDTV", "TMJOFCDPL"):
                    rank_score = ratio * math.log(mx + 1.0)
                else:
                    rank_score = ratio
                scores[col] = {
                    "max": _round_or_none(mx, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "min": _round_or_none(mn, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "ratio": round(ratio, 2),
                    "delta": _round_or_none(delta, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "rank_score": float(rank_score),
                }

    ordered = sorted(scores.keys(), key=lambda k: -scores[k]["rank_score"])
    for rank, key in enumerate(ordered, start=1):
        scores[key]["rank"] = rank
        scores[key].pop("rank_score", None)
    return ordered, scores


def _classify_topology_from_flags(
    n_in: int,
    n_out: int,
    has_ramp: bool,
    has_rdb: bool,
) -> str:
    """Bretelle > Carrefour > Continuite (variante numpy-friendly)."""
    if has_ramp:
        return "Bretelle"
    total = n_in + n_out
    if has_rdb or total >= 3:
        return "Carrefour"
    if n_in == 1 and n_out == 1:
        return "Continuite"
    return "Carrefour"


def _classify_principal_cause_from_arrays(
    drivers: list[str],
    indices_all: np.ndarray,
    ramp_arr: np.ndarray,
    rdb_arr: np.ndarray,
    tv_arr: np.ndarray,
    pl_arr: np.ndarray,
) -> str:
    """Cause principale en cascade — opere sur arrays slices indexes.

    Ordre de la cascade (cf. memoire § 5.2) :
      1) si ``drivers`` (FCD_TV/PL/distance/FC) non vides -> driver dominant.
      2) RAMP_asymmetry si presence Y et N parmi les arcs.
      3) ROUNDABOUT_asymmetry idem.
      4) Coverage_gap : ne se declenche QUE si la couverture FCD est reellement
         faible (au moins la moitie des arcs avec donnees nulles ou manquantes,
         ET aucun arc avec un trafic FCD vraiment soutenu > 10 v/j). Sinon, on
         retombe en Unexplained pour signaler que c'est un cas a investiguer
         (i.e. un saut TVr non explique par les drivers FCD malgre la presence
         de FCD au noeud).
    """
    if drivers:
        top = drivers[0]
        return DRIVER_TO_CAUSE.get(top, "Unexplained")

    if indices_all.size:
        ramp_slice = ramp_arr[indices_all]
        if ramp_slice.any() and not ramp_slice.all():
            # any Y AND any N
            if (ramp_slice == 1).any() and (ramp_slice == 0).any():
                return "RAMP_asymmetry"
        rdb_slice = rdb_arr[indices_all]
        if rdb_slice.any() and not rdb_slice.all():
            if (rdb_slice == 1).any() and (rdb_slice == 0).any():
                return "ROUNDABOUT_asymmetry"

        tv = tv_arr[indices_all]
        pl = pl_arr[indices_all]
        tv_finite = tv[np.isfinite(tv)]
        pl_finite = pl[np.isfinite(pl)]

        # Coverage_gap reel : au moins la moitie des arcs n'a pas de donnee FCD
        # exploitable (NaN ou ~0), ET aucun arc avec un FCD soutenu.
        # On evite ainsi de classer en Coverage_gap des cliffs evidents
        # (cas type : in=2000 v/j vs out=0 v/j -> ce n'est pas un trou, c'est un cliff).
        n_total = int(indices_all.size)
        n_tv_missing = int(n_total - tv_finite.size + (tv_finite < TMJOFCDTV_ZERO).sum())
        n_pl_missing = int(n_total - pl_finite.size + (pl_finite < TMJOFCDPL_ZERO).sum())

        tv_max_observed = float(tv_finite.max()) if tv_finite.size else 0.0
        pl_max_observed = float(pl_finite.max()) if pl_finite.size else 0.0

        coverage_threshold = 0.5  # >= moitie des arcs sans donnee
        true_coverage_gap = (
            n_tv_missing / n_total >= coverage_threshold and tv_max_observed < 10.0
        ) or (n_pl_missing / n_total >= coverage_threshold and pl_max_observed < 5.0)
        if true_coverage_gap:
            return "Coverage_gap"

    return "Unexplained"


def _node_level_aggregates(
    in_idx: np.ndarray,
    out_idx: np.ndarray,
    tvr_arr: np.ndarray,
    arr_by_col: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Agrege au niveau noeud les attributs FCD + distances des arcs incidents.

    Pour un noeud N connectant n_in arcs entrants et n_out arcs sortants, on
    expose dans les properties :

      - ``FCD_TV`` / ``FCD_PL`` : volume FCD total qui transite (somme des
        TMJOFCDTV/PL des arcs entrants ; egal au volume sortant en regime
        permanent et plus directement comparable a ``flow_in`` / ``flow_out`` que
        TVr). On expose aussi ``FCD_TV_in``, ``FCD_TV_out``, ``FCD_PL_in``,
        ``FCD_PL_out`` pour le diagnostic des falaises (cliffs).
      - ``FCD_TV_max`` / ``FCD_PL_max`` : max par segment (utile pour spotter
        les axes les plus charges autour du noeud).
      - ``FCD_TV_coverage`` / ``FCD_PL_coverage`` : ratio de segments adjacents
        ayant une donnee FCD non-nulle (1.0 = tous couverts, 0.0 = trou total).
      - ``avg_distance_*`` : moyenne / min / max sur les arcs adjacents pour
        ``avg_distance_before_m``, ``avg_min_distance_m``, etc.

    Toutes les valeurs sont JSON-safe (float ou None, jamais NaN).
    """
    out: dict[str, Any] = {}
    if in_idx.size == 0 and out_idx.size == 0:
        return out

    def _agg(values: np.ndarray, mode: str) -> float | None:
        if values.size == 0:
            return None
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return None
        if mode == "sum":
            return float(finite.sum())
        if mode == "mean":
            return float(finite.mean())
        if mode == "min":
            return float(finite.min())
        if mode == "max":
            return float(finite.max())
        raise ValueError(f"Unknown agg mode: {mode}")

    def _coverage(values_all: np.ndarray, threshold: float = 0.0) -> float | None:
        """Fraction des arcs adjacents avec FCD > threshold (NaN/0 = trou)."""
        if values_all.size == 0:
            return None
        finite = np.isfinite(values_all)
        non_zero = (values_all > threshold) & finite
        return float(non_zero.sum()) / float(values_all.size)

    # FCD TV / PL : on calcule in / out / max / coverage.
    for canon, prefix in (("TMJOFCDTV", "FCD_TV"), ("TMJOFCDPL", "FCD_PL")):
        arr_full = arr_by_col.get(canon)
        if arr_full is None:
            continue
        in_vals = arr_full[in_idx] if in_idx.size else np.empty(0, dtype=np.float64)
        out_vals = arr_full[out_idx] if out_idx.size else np.empty(0, dtype=np.float64)
        all_vals = (
            np.concatenate([in_vals, out_vals])
            if (in_vals.size or out_vals.size)
            else np.empty(0, dtype=np.float64)
        )

        flow_in = _agg(in_vals, "sum")
        flow_out = _agg(out_vals, "sum")
        out[f"{prefix}_in"] = None if flow_in is None else round(flow_in, 2)
        out[f"{prefix}_out"] = None if flow_out is None else round(flow_out, 2)

        # Volume FCD "principal" du noeud = moyenne in/out (regime permanent).
        # Si l'un des deux cotes est vide, on prend l'autre seul.
        if flow_in is not None and flow_out is not None:
            out[prefix] = round((flow_in + flow_out) / 2.0, 2)
        elif flow_in is not None:
            out[prefix] = round(flow_in, 2)
        elif flow_out is not None:
            out[prefix] = round(flow_out, 2)
        else:
            out[prefix] = None

        mx = _agg(all_vals, "max")
        out[f"{prefix}_max"] = None if mx is None else round(mx, 2)
        cov = _coverage(all_vals, threshold=0.0)
        out[f"{prefix}_coverage"] = None if cov is None else round(cov, 3)

    # Distances : moyenne + min + max sur arcs adjacents (in + out confondus).
    for canon in (
        "avg_distance_before_m",
        "avg_min_distance_m",
        "truck_avg_distance_before_m",
        "truck_avg_min_distance_m",
    ):
        arr_full = arr_by_col.get(canon)
        if arr_full is None:
            continue
        in_vals = arr_full[in_idx] if in_idx.size else np.empty(0, dtype=np.float64)
        out_vals = arr_full[out_idx] if out_idx.size else np.empty(0, dtype=np.float64)
        all_vals = (
            np.concatenate([in_vals, out_vals])
            if (in_vals.size or out_vals.size)
            else np.empty(0, dtype=np.float64)
        )
        mean = _agg(all_vals, "mean")
        if mean is not None:
            out[f"{canon}_mean"] = round(mean, 1)
            out[f"{canon}_min"] = round(_agg(all_vals, "min") or 0.0, 1)
            out[f"{canon}_max"] = round(_agg(all_vals, "max") or 0.0, 1)

    return out


def _build_edges_payload_from_arrays(
    indices: np.ndarray,
    side_prefix: str,
    agreg_arr: np.ndarray,
    tvr_arr: np.ndarray,
    arr_by_col: dict[str, np.ndarray],
) -> list[dict[str, Any]]:
    """Trie indices par TVr desc, cap a MAX_EDGES_PER_SIDE, libelle E1.. ou S1..."""
    if indices.size == 0:
        return []
    tvr_slice = tvr_arr[indices]
    sort_key = np.where(np.isfinite(tvr_slice), tvr_slice, -1.0)
    order = np.argsort(-sort_key, kind="mergesort")
    sorted_idx = indices[order]

    n_total = int(sorted_idx.size)
    head = sorted_idx[:MAX_EDGES_PER_SIDE]
    out_list: list[dict[str, Any]] = []
    for i, pos in enumerate(head, start=1):
        inputs: dict[str, Any] = {}
        for col in INPUT_COLS:
            arr_full = arr_by_col.get(col)
            if arr_full is None:
                inputs[col] = None
                continue
            v = arr_full[pos]
            if not np.isfinite(v):
                inputs[col] = None
            elif col == "functional_class":
                try:
                    inputs[col] = int(v)
                except (TypeError, ValueError):
                    inputs[col] = None
            else:
                inputs[col] = round(float(v), 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1)
        tvr_v = tvr_arr[pos]
        out_list.append(
            {
                "agregId": str(agreg_arr[pos]),
                "TVr": (None if not np.isfinite(tvr_v) else round(float(tvr_v), 1)),
                "inputs": inputs,
                "label": f"{side_prefix}{i}",
            }
        )
    n_extra = n_total - len(out_list)
    if n_extra > 0 and out_list:
        out_list[-1]["label"] = f"{out_list[-1]['label']} (+{n_extra} autres)"
    return out_list


def join_fcdref(
    gdf: gpd.GeoDataFrame,
    fcd_df: pd.DataFrame,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Joint un parquet FCDREFGLOBAL au reseau (``agregId == segment_id``, how='left').

    Reproduit la jointure de ``build_node_causality_v2.load_edges()`` AVEC un
    mapping de colonnes source -> canonique (cf. ``FCD_COLUMN_MAPPING``) :

      - garde ``agregId`` du geojson (clef du graphe HERE) ;
      - cle de jointure cote parquet : ``segment_id`` ;
      - identifie dans le parquet toutes les colonnes ayant un mapping vers un
        nom canonique attendu en interne (TMJFCDTV/PL, distances en km, etc.) ;
      - les renomme et applique le scale factor (km -> m si necessaire) ;
      - ajoute les colonnes mappees ; les collisions avec le geojson sont
        ecrasees par le parquet (referentiel canonique).

    Retourne ``(gdf_joined, info)`` ou ``info`` contient ``n_segments_parquet``,
    ``n_matched``, ``columns_joined`` (noms canoniques).
    """
    if "agregId" not in gdf.columns:
        raise ValueError("Colonne 'agregId' manquante : impossible de joindre le parquet FCD.")

    # Normalisation de la cle de jointure cote parquet : le FCDREFGLOBAL reel
    # expose 'AgregId' (et non 'segment_id'). On accepte plusieurs alias et on
    # renomme en interne vers 'segment_id' pour le reste du code.
    fcd = fcd_df.copy()
    join_key_source: str | None = None
    for alias in FCD_JOIN_KEY_ALIASES:
        if alias in fcd.columns:
            join_key_source = alias
            break
    if join_key_source is None:
        raise ValueError(
            "Le parquet FCD doit contenir une colonne de jointure parmi "
            f"{list(FCD_JOIN_KEY_ALIASES)} (cle vers 'agregId' du geojson)."
        )
    if join_key_source != "segment_id":
        # Si 'segment_id' existe deja en plus de l'alias, on le drop pour eviter
        # une collision au rename.
        if "segment_id" in fcd.columns:
            fcd = fcd.drop(columns=["segment_id"])
        fcd = fcd.rename(columns={join_key_source: "segment_id"})
        logger.info(
            "Discontinuites: jointure FCD - cle '%s' normalisee en 'segment_id'",
            join_key_source,
        )
    fcd["segment_id"] = fcd["segment_id"].astype(str)

    # Selectionne les colonnes du parquet ayant un mapping defini.
    # Si plusieurs sources mappent vers la meme cible, premier rencontre gagne.
    # Exception : pour REF_IN_ID/NREF_IN_ID, si le geojson les contient deja
    # avec des valeurs non-nulles, on n'ecrase PAS (le reseau d'origine prime).
    selected: dict[str, tuple[str, float]] = {}  # source -> (target, scale)
    target_to_source: dict[str, str] = {}
    graph_endpoint_cols = {"REF_IN_ID", "NREF_IN_ID"}
    for source_col in fcd.columns:
        if source_col in FCD_COLUMN_MAPPING:
            target, scale = FCD_COLUMN_MAPPING[source_col]
            if target in target_to_source:
                # On garde le premier alias rencontre.
                continue
            # Endpoint graphe deja present cote geojson avec valeurs valides :
            # on ne refait pas le merge (eviterait un ecrasement par NaN).
            if target in graph_endpoint_cols and target in gdf.columns:
                try:
                    if gdf[target].notna().any():
                        logger.info(
                            "Discontinuites: jointure FCD - '%s' deja present cote geojson, on conserve",
                            target,
                        )
                        continue
                except Exception:  # noqa: BLE001 — defensive (col objet non-numerique)
                    pass
            selected[source_col] = (target, scale)
            target_to_source[target] = source_col

    if not selected:
        raise ValueError(
            "Le parquet FCD ne contient aucune colonne mappee. Sources acceptees : "
            f"{list(FCD_COLUMN_MAPPING.keys())}"
        )

    # Construit un sous-set du parquet avec les colonnes renommees + scalees.
    sources = ["segment_id", *selected.keys()]
    fcd_subset = fcd[sources].drop_duplicates(subset="segment_id", keep="first").copy()

    canonical_cols: list[str] = []
    for source_col, (target_col, scale) in selected.items():
        if scale != 1.0:
            # Numeric coercion + scale (NaN propage)
            fcd_subset[target_col] = pd.to_numeric(fcd_subset[source_col], errors="coerce") * scale
        elif target_col != source_col:
            fcd_subset[target_col] = fcd_subset[source_col]
        # else : source == target, deja en place
        canonical_cols.append(target_col)

    # Ne garde que segment_id + colonnes canoniques (les sources scalees sont
    # remplacees par les nouvelles colonnes target).
    fcd_subset = fcd_subset[["segment_id", *canonical_cols]]

    out = gdf.copy()
    out["agregId"] = out["agregId"].astype(str)

    # Drop dans le geojson les colonnes canoniques deja presentes qui seront
    # remplacees par la valeur du parquet (sinon pandas crash en merge avec suffixes).
    for col in canonical_cols:
        if col in out.columns:
            out = out.drop(columns=[col])

    merged = out.merge(
        fcd_subset,
        left_on="agregId",
        right_on="segment_id",
        how="left",
    )

    # On retire la colonne 'segment_id' redondante avec 'agregId'.
    if "segment_id" in merged.columns:
        merged = merged.drop(columns=["segment_id"])

    # Restaurer le GeoDataFrame avec sa geometrie + CRS d'origine.
    geom_col = gdf.geometry.name if hasattr(gdf, "geometry") else "geometry"
    if geom_col in merged.columns:
        merged = gpd.GeoDataFrame(merged, geometry=geom_col, crs=gdf.crs)

    # Comptage des lignes matchees : detecte via la premiere colonne canonique non-vide.
    n_matched = 0
    for col in canonical_cols:
        n_matched_here = int(merged[col].notna().sum())
        if n_matched_here > n_matched:
            n_matched = n_matched_here

    info: dict[str, Any] = {
        "n_segments_parquet": int(len(fcd_subset)),
        "n_matched": n_matched,
        "columns_joined": list(canonical_cols),
        "source_to_target": {s: t for s, (t, _) in selected.items()},
    }
    logger.info(
        "Discontinuites: jointure FCD - %d colonnes canoniques (%s), %d lignes matchees / %d aretes",
        len(canonical_cols),
        ",".join(canonical_cols),
        n_matched,
        len(merged),
    )
    return merged, info


def run_full_pipeline(
    gdf: gpd.GeoDataFrame,
    fcd_df: pd.DataFrame | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Orchestration complete : edges -> nodes flagues -> causality -> FeatureCollection.

    Si ``fcd_df`` est fourni, la jointure ``agregId == segment_id`` est appliquee
    en amont (cf. ``join_fcdref``) — c'est le mode nominal, qui permet aux
    causes ``FCD_TV_cliff`` / ``FCD_PL_cliff`` de se declencher meme quand le
    geojson ne contient que TVr/DPL/FC/RAMP/ROUNDABOUT (cas du `2025_light.geojson`).

    Retourne ``(feature_collection, stats)`` :

    - ``feature_collection`` : dict GeoJSON ready (avec metadata cause_palette,
      topology_palette, labels_fr, version).
    - ``stats`` : dict avec ``n_features, n_causes, n_topology, pipeline_duration_s,
      cross_tab, n_total_nodes, n_boundary_nodes, fcd_joined, fcd_columns_count``.

    Implementation : tout le hot loop opere sur des ``np.ndarray`` precharges
    une seule fois (input cols + RAMP/ROUNDABOUT + agregId + TVr). Pour chaque
    noeud on slice ces arrays par les indices d'edges incidents (precomputes
    via ``np.unique(in_node, return_inverse=True)``) — aucune copie de DataFrame
    par noeud. Sur 5 000 aretes -> 4 095 noeuds : 1.2 s vs 89 s en mode pandas.
    """
    t_start = time.perf_counter()
    logger.info("Discontinuites: demarrage pipeline (%d aretes)", len(gdf))

    # 0) Jointure optionnelle du parquet FCD (mode nominal v4)
    fcd_joined = False
    fcd_columns_count = 0
    fcd_join_info: dict[str, Any] = {}
    if fcd_df is not None and len(fcd_df) > 0:
        try:
            gdf, fcd_join_info = join_fcdref(gdf, fcd_df)
            fcd_joined = True
            fcd_columns_count = len(fcd_join_info.get("columns_joined", []))
        except ValueError as exc:
            logger.warning("Jointure FCD ignoree : %s", exc)

    # 0bis) Verification post-join : REF_IN_ID/NREF_IN_ID doivent maintenant
    # etre presents pour reconstruire le graphe HERE. Si le geojson ne les a
    # pas et que le FCD ne les a pas non plus, on leve une erreur explicite.
    missing_graph_cols = [c for c in ("REF_IN_ID", "NREF_IN_ID") if c not in gdf.columns]
    if missing_graph_cols:
        joined_hint = (
            "Le parquet FCD a ete joint mais ne contient pas non plus ces colonnes."
            if fcd_joined
            else "Aucun parquet FCD n'a ete joint."
        )
        raise ValueError(
            f"Colonnes graphe HERE absentes apres preparation : {missing_graph_cols}. "
            f"Le pipeline a besoin de REF_IN_ID + NREF_IN_ID pour reconstruire "
            f"l'adjacence des noeuds. {joined_hint} Verifiez que les colonnes sont "
            f"presentes soit dans le geojson de segments, soit dans le parquet FCD."
        )

    # 1) Aretes orientees
    edges = _build_directed_edges(gdf)
    n_edges = int(len(edges))
    logger.info("Discontinuites: %d aretes apres nettoyage", n_edges)

    # 2) Noeuds + regle utilisateur
    nodes = _build_node_table(edges)
    n_total_nodes = int(len(nodes))
    n_boundary = int(nodes["is_boundary"].sum())
    flagged_nodes = nodes[nodes["is_flagged"]].copy()
    logger.info(
        "Discontinuites: %d noeuds total, %d frontaliers, %d flagues",
        n_total_nodes,
        n_boundary,
        len(flagged_nodes),
    )

    # 3) Pre-extraction des arrays numpy — payes UNE FOIS pour tout le reseau.
    agreg_arr = edges["agregId"].astype(str).to_numpy()
    tvr_arr = pd.to_numeric(edges["TVr"], errors="coerce").to_numpy(dtype=np.float64)
    in_node_arr = edges["in_node"].to_numpy(dtype=np.int64)
    out_node_arr = edges["out_node"].to_numpy(dtype=np.int64)
    arr_by_col: dict[str, np.ndarray] = {}
    for col in INPUT_COLS:
        if col in edges.columns:
            arr_by_col[col] = pd.to_numeric(edges[col], errors="coerce").to_numpy(dtype=np.float64)
    # RAMP / ROUNDABOUT en boolean int8 (1 = Y, 0 = N/autre)
    ramp_arr = (
        edges["RAMP"].astype(str).str.upper().eq("Y").to_numpy(dtype=np.int8)
        if "RAMP" in edges.columns
        else np.zeros(n_edges, dtype=np.int8)
    )
    rdb_arr = (
        edges["ROUNDABOUT"].astype(str).str.upper().eq("Y").to_numpy(dtype=np.int8)
        if "ROUNDABOUT" in edges.columns
        else np.zeros(n_edges, dtype=np.int8)
    )

    # Build index map : node_id -> array d'indices d'edges (in/out)
    # Via tri stable + groupby numpy.
    def _group_indices(node_arr: np.ndarray) -> dict[int, np.ndarray]:
        order = np.argsort(node_arr, kind="stable")
        sorted_keys = node_arr[order]
        # boundaries
        change = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1], True])
        out: dict[int, np.ndarray] = {}
        for i in range(len(change) - 1):
            start, end = change[i], change[i + 1]
            out[int(sorted_keys[start])] = order[start:end]
        return out

    in_idx_by_node = _group_indices(out_node_arr)  # edges ARRIVANT au noeud
    out_idx_by_node = _group_indices(in_node_arr)  # edges QUITTANT le noeud

    features: list[dict[str, Any]] = []
    cause_counter: Counter[str] = Counter()
    topo_counter: Counter[str] = Counter()
    cross_counter: Counter[tuple[str, str]] = Counter()
    tier_counter: Counter[str] = Counter()

    empty_idx = np.empty(0, dtype=np.int64)
    fn_node_ids = flagged_nodes["node_id"].to_numpy(dtype=np.int64)
    fn_in_flow = flagged_nodes["in_flow"].to_numpy(dtype=np.float64)
    fn_out_flow = flagged_nodes["out_flow"].to_numpy(dtype=np.float64)
    fn_n_in = flagged_nodes["n_in"].to_numpy(dtype=np.int64)
    fn_n_out = flagged_nodes["n_out"].to_numpy(dtype=np.int64)
    fn_ecart = flagged_nodes["ecart"].to_numpy(dtype=np.float64)
    fn_max_flow = flagged_nodes["max_flow"].to_numpy(dtype=np.float64)
    fn_threshold = flagged_nodes["threshold"].to_numpy(dtype=np.float64)
    fn_tier = flagged_nodes["tier"].astype(str).to_numpy()
    fn_lon = flagged_nodes["lon"].to_numpy()
    fn_lat = flagged_nodes["lat"].to_numpy()

    for i in range(len(fn_node_ids)):
        nid = int(fn_node_ids[i])
        in_idx = in_idx_by_node.get(nid, empty_idx)
        out_idx = out_idx_by_node.get(nid, empty_idx)
        all_idx = np.concatenate([in_idx, out_idx]) if (in_idx.size or out_idx.size) else empty_idx

        drivers, driver_scores = _detect_drivers_from_arrays(all_idx, arr_by_col)
        principal_cause = _classify_principal_cause_from_arrays(
            drivers,
            all_idx,
            ramp_arr,
            rdb_arr,
            arr_by_col.get("TMJOFCDTV", np.full(n_edges, np.nan)),
            arr_by_col.get("TMJOFCDPL", np.full(n_edges, np.nan)),
        )

        has_ramp = bool(ramp_arr[all_idx].any()) if all_idx.size else False
        has_rdb = bool(rdb_arr[all_idx].any()) if all_idx.size else False
        topology = _classify_topology_from_flags(
            int(fn_n_in[i]), int(fn_n_out[i]), has_ramp, has_rdb
        )

        edges_in_payload = _build_edges_payload_from_arrays(
            in_idx, "E", agreg_arr, tvr_arr, arr_by_col
        )
        edges_out_payload = _build_edges_payload_from_arrays(
            out_idx, "S", agreg_arr, tvr_arr, arr_by_col
        )
        # Agregats FCD + distances au niveau noeud (cf. _node_level_aggregates).
        node_aggregates = _node_level_aggregates(in_idx, out_idx, tvr_arr, arr_by_col)
        narrative = _build_narrative(principal_cause, drivers, driver_scores, float(fn_ecart[i]))

        lon = _safe_float(fn_lon[i])
        lat = _safe_float(fn_lat[i])
        if lon is None or lat is None:
            continue

        props = {
            "node_id": str(nid),
            "ecart": round(float(fn_ecart[i]), 1),
            "flow_in": round(float(fn_in_flow[i]), 1),
            "flow_out": round(float(fn_out_flow[i]), 1),
            "n_in": int(fn_n_in[i]),
            "n_out": int(fn_n_out[i]),
            "max_flow": round(float(fn_max_flow[i]), 1),
            "threshold": float(fn_threshold[i]),
            "tier": str(fn_tier[i]),
            "principal_cause": principal_cause,
            "topology": topology,
            "narrative": narrative,
            "drivers": drivers,
            "driver_scores": driver_scores,
            "edges_in": edges_in_payload,
            "edges_out": edges_out_payload,
            # Agregats FCD + distances propages depuis les arcs incidents
            **node_aggregates,
        }

        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(lon, 6), round(lat, 6)],
                },
                "properties": props,
            }
        )
        cause_counter[principal_cause] += 1
        topo_counter[topology] += 1
        cross_counter[(principal_cause, topology)] += 1
        tier_counter[str(fn_tier[i])] += 1

    duration = round(time.perf_counter() - t_start, 3)
    logger.info(
        "Discontinuites: pipeline complet en %.2fs (%d features)",
        duration,
        len(features),
    )

    metadata = {
        "version": "v3",
        "n_features": len(features),
        "n_total_nodes": n_total_nodes,
        "n_boundary_nodes": n_boundary,
        "n_edges": int(len(edges)),
        "pipeline_duration_s": duration,
        "fcd_joined": fcd_joined,
        "fcd_columns_count": fcd_columns_count,
        "cause_labels_fr": dict(CAUSE_LABELS_FR),
        "topology_labels_fr": dict(TOPOLOGY_LABELS_FR),
        "cause_palette": dict(CAUSE_PALETTE),
        "topology_palette": dict(TOPOLOGY_PALETTE),
        "principal_cause_taxonomy": list(CAUSE_LABELS_FR.keys()),
        "user_rule": {
            "low_threshold": USER_RULE_LOW_THRESHOLD,
            "high_threshold": USER_RULE_HIGH_THRESHOLD,
            "pivot": USER_RULE_PIVOT,
        },
    }
    fc = {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }

    # Cross-tab cause x topology sous forme de dict imbrique
    cross_tab: dict[str, dict[str, int]] = {}
    for (cause, topo), n in cross_counter.items():
        cross_tab.setdefault(cause, {})[topo] = int(n)

    stats = {
        "n_features": len(features),
        "n_total_nodes": n_total_nodes,
        "n_boundary_nodes": n_boundary,
        "n_edges": int(len(edges)),
        "pipeline_duration_s": duration,
        "n_causes": {k: int(v) for k, v in cause_counter.items()},
        "n_topology": {k: int(v) for k, v in topo_counter.items()},
        "n_tier": {k: int(v) for k, v in tier_counter.items()},
        "cross_tab": cross_tab,
        "user_rule": metadata["user_rule"],
        "fcd_joined": fcd_joined,
        "fcd_columns_count": fcd_columns_count,
        "fcd_columns": list(fcd_join_info.get("columns_joined", [])),
        "fcd_matched": int(fcd_join_info.get("n_matched", 0)),
    }
    return fc, stats


__all__ = [
    "CAUSE_LABELS_FR",
    "CAUSE_PALETTE",
    "CAUSE_PRIORITY",
    "DRIVER_TO_CAUSE",
    "FCD_JOIN_COLUMNS",
    "FCD_REQUIRED_COLUMNS",
    "INPUT_COLS",
    "MAX_EDGES_PER_SIDE",
    "TOPOLOGY_LABELS_FR",
    "TOPOLOGY_PALETTE",
    "USER_RULE_HIGH_THRESHOLD",
    "USER_RULE_LOW_THRESHOLD",
    "USER_RULE_PIVOT",
    "compute_node_causality",
    "detect_discontinuities",
    "join_fcdref",
    "run_full_pipeline",
]
