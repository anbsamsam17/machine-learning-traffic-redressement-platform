"""Construction du GeoJSON d'evolution par troncon (base = T2).

Consomme la table d'appariement (``matching.match_segments``) et les deux cartes
normalisees pour produire UN FeatureCollection LineString (geometrie = base T2)
avec, par troncon :

* metrique JOr UNIQUEMENT (volume v/j de chaque annee -> % d'evolution) ;
* garde-fous (jamais d'inf/NaN dans le JSON) : plancher emergent, T1<=0/null ;
* significativite ``sig`` (IC disjoints) ;
* categorie metier ; tracabilite (match_level / match_score / ban_concordance).

Format ancre sur la reference ``2023Vs2024.geojson`` (9 props : agregId, FC, HD,
DD, T2, T1, JO_T2, JO_T1, JOr) + champs de decision (dJOr, sig, categorie,
match_level, match_score, ban_concordance, FC_change).

Mapping de la reference (verifie) :
* ``T1`` / ``T2`` = ``JOr`` (volume redresse) de l'annee 1 / 2 ;
* ``JO_T1`` / ``JO_T2`` = ``JO`` (volume observe FCD brut) de l'annee 1 / 2 ;
* ``JOr`` (sortie) = round((T2 - T1) / T1 * 100, 2)  -> POURCENTAGE.
"""

from __future__ import annotations

import math
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

# Categories metier.
CAT_EVOLUTIF = "evolutif"
CAT_NOUVEAU = "nouveau"
CAT_DISPARU = "disparu"
CAT_TOPO = "topologie_modifiee"
CAT_NON_REDRESSE = "non_redresse"
CAT_EMERGENT = "emergent"


def _num(value: Any) -> float | None:
    """Convertir en float fini, ``None`` si NaN/inf/null/non numerique."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _geom_to_coords(geom) -> list[list[float]]:
    """Coordonnees [lon, lat] d'une LineString WGS84 (5 decimales ~1 m)."""
    return [[round(x, 5), round(y, 5)] for x, y in geom.coords]


def _compute_sig(
    jmin1: float | None,
    jmax1: float | None,
    jmin2: float | None,
    jmax2: float | None,
) -> int:
    """sig=1 si les IC JOr des deux annees sont DISJOINTS, sinon 0.

    Degrade sur : si un IC manque ou est incoherent (min>max), sig=0.
    """
    if None in (jmin1, jmax1, jmin2, jmax2):
        return 0
    if jmin1 > jmax1 or jmin2 > jmax2:
        return 0
    if jmax1 < jmin2 or jmin1 > jmax2:
        return 1
    return 0


def build_evolution_geojson(
    gdf_t1: gpd.GeoDataFrame,
    gdf_t2: gpd.GeoDataFrame,
    matches_df: pd.DataFrame,
    *,
    plancher_t1: float = 50.0,
    clamp_pct: float = 100.0,
    with_sig: bool = True,
) -> dict:
    """Construire le FeatureCollection d'evolution (geometrie = base T2).

    Parameters
    ----------
    gdf_t1, gdf_t2 : geopandas.GeoDataFrame
        Cartes normalisees (cf ``io.load_carte_geojson``). ``gdf_t2`` est la BASE.
    matches_df : pandas.DataFrame
        Sortie de ``matching.match_segments`` (id_t2, id_t1, match_level,
        match_score, ban_concordance), une ligne par troncon base T2 (meme ordre
        que gdf_t2).
    plancher_t1 : float
        Plancher emergent (v/j) : si T1 < plancher (et > 0), pas de % -> emergent.
    clamp_pct : float
        Borne d'AFFICHAGE de la couleur (JOr_display clampe a +/-clamp_pct). La
        valeur JOr brute reste dans la data.
    with_sig : bool
        Calculer la significativite (IC disjoints).

    Returns
    -------
    dict
        FeatureCollection GeoJSON CRS84, sans NaN/Infinity. JOr=null si non
        calculable (T1<plancher ou T1<=0).
    """
    n = len(gdf_t2)
    if len(matches_df) != n:
        raise ValueError(f"matches_df ({len(matches_df)}) doit couvrir la base T2 ({n}).")

    # Index T1 par agregId pour recuperer les valeurs de l'annee 1.
    t1_rows: dict[str, dict[str, Any]] = {}
    for _, row in gdf_t1.iterrows():
        aid = row.get("agregId")
        if aid is not None and aid not in t1_rows:
            t1_rows[aid] = {
                "JOr": _num(row.get("JOr")),
                "JO": _num(row.get("JO")),
                "FC": row.get("FC"),
                "JOrmin": _num(row.get("JOrmin")),
                "JOrmax": _num(row.get("JOrmax")),
            }

    m = matches_df.reset_index(drop=True)
    base = gdf_t2.reset_index(drop=True)

    features: list[dict[str, Any]] = []
    for i in range(n):
        brow = base.iloc[i]
        mrow = m.iloc[i]
        geom = brow.geometry

        agreg_id = mrow["id_t2"]
        match_level = mrow["match_level"]
        match_score = _num(mrow.get("match_score"))
        ban_conc = mrow.get("ban_concordance")
        if ban_conc is not None and (isinstance(ban_conc, float) and pd.isna(ban_conc)):
            ban_conc = None

        fc_t2 = brow.get("FC")
        t2 = _num(brow.get("JOr"))  # volume redresse annee 2
        jo_t2 = _num(brow.get("JO"))  # volume observe FCD annee 2
        jmin2 = _num(brow.get("JOrmin"))
        jmax2 = _num(brow.get("JOrmax"))

        id_t1 = mrow.get("id_t1")
        # Robustesse pandas 3.x : une colonne objet de str avec valeurs
        # manquantes peut etre inferee en dtype str (None -> NaN). On neutralise.
        if id_t1 is not None:
            try:
                if pd.isna(id_t1):
                    id_t1 = None
            except (TypeError, ValueError):
                pass
        if id_t1 is not None and not isinstance(id_t1, str):
            id_t1 = str(id_t1)
        t1 = jo_t1 = jmin1 = jmax1 = None
        fc_t1 = None
        if id_t1 is not None and id_t1 in t1_rows:
            tr = t1_rows[id_t1]
            t1 = tr["JOr"]
            jo_t1 = tr["JO"]
            jmin1, jmax1 = tr["JOrmin"], tr["JOrmax"]
            fc_t1 = tr["FC"]

        # --- dJOr (delta absolu) : TOUJOURS calcule si les 2 volumes existent --
        d_jor: float | None = None
        if t2 is not None and t1 is not None:
            d_jor = round(t2 - t1, 2)

        # --- JOr (% evolution) + garde-fous ---------------------------------- #
        jor_pct: float | None = None
        categorie: str

        fc_change = fc_t1 is not None and fc_t2 is not None and str(fc_t1) != str(fc_t2)

        if id_t1 is None or t1 is None:
            # Pas d'annee 1 appariee / non redressee en T1 -> nouveau.
            categorie = CAT_NOUVEAU if id_t1 is None else CAT_NON_REDRESSE
            jor_pct = None
            d_jor = round(t2, 2) if (t2 is not None and t1 is None and id_t1 is not None) else d_jor
        elif t1 <= 0:
            # Division par zero impossible -> JOr null, dJOr conserve.
            jor_pct = None
            categorie = CAT_NON_REDRESSE
            if t2 is not None:
                d_jor = round(t2 - t1, 2)
        elif t1 < plancher_t1:
            # Base trop faible : % aberrant -> emergent, pas de %.
            jor_pct = None
            categorie = CAT_EMERGENT
        elif t2 is None:
            jor_pct = None
            categorie = CAT_NON_REDRESSE
        else:
            jor_pct = round((t2 - t1) / t1 * 100.0, 2)
            categorie = CAT_TOPO if fc_change else CAT_EVOLUTIF

        # --- sig --------------------------------------------------------------
        if with_sig and jor_pct is not None:
            sig = _compute_sig(jmin1, jmax1, jmin2, jmax2)
        else:
            sig = 0

        # --- JOr_display (clamp d'affichage, valeur brute conservee dans JOr) --
        jor_display: float | None = None
        if jor_pct is not None:
            jor_display = round(max(-clamp_pct, min(clamp_pct, jor_pct)), 2)

        props: dict[str, Any] = {
            "agregId": agreg_id,
            "FC": str(fc_t2) if fc_t2 is not None else None,
            "HD": _num(brow.get("HD")),
            "DD": (
                bool(brow.get("DD"))
                if brow.get("DD") is not None
                and not (isinstance(brow.get("DD"), float) and pd.isna(brow.get("DD")))
                else None
            ),
            "T2": t2,
            "T1": t1,
            "JO_T2": jo_t2,
            "JO_T1": jo_t1,
            "JOr": jor_pct,  # null si non calculable (jamais inf/NaN)
            "dJOr": d_jor,
            "JOr_display": jor_display,
            "sig": int(sig),
            "categorie": categorie,
            "FC_change": bool(fc_change),
            "match_level": match_level,
            "match_score": match_score,
            "ban_concordance": ban_conc,
        }

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": _geom_to_coords(geom)},
                "properties": props,
            }
        )

    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }


def compute_stats(geojson: dict) -> dict:
    """Calculer les statistiques de synthese du FeatureCollection d'evolution."""
    feats = geojson.get("features", [])
    levels = {"CLE": 0, "GEOM_AUTO": 0, "GEOM_VERIF": 0, "NON_MATCH": 0}
    n_emergent = 0
    n_sig = 0
    n_ban_indisponible = 0
    jors: list[float] = []
    for ft in feats:
        p = ft["properties"]
        lvl = p.get("match_level")
        if lvl in levels:
            levels[lvl] += 1
        if p.get("categorie") == CAT_EMERGENT:
            n_emergent += 1
        if p.get("sig") == 1:
            n_sig += 1
        if p.get("ban_concordance") == "INDISPONIBLE":
            n_ban_indisponible += 1
        jv = p.get("JOr")
        if jv is not None and math.isfinite(jv):
            jors.append(jv)
    arr = np.array(jors, dtype="float64") if jors else np.array([])
    return {
        "n_total": len(feats),
        "n_cle": levels["CLE"],
        "n_geom_auto": levels["GEOM_AUTO"],
        "n_geom_verif": levels["GEOM_VERIF"],
        "n_non_match": levels["NON_MATCH"],
        "n_emergent": n_emergent,
        "n_sig": n_sig,
        "n_ban_indisponible": n_ban_indisponible,
        "jor_min": round(float(arr.min()), 2) if arr.size else None,
        "jor_median": round(float(np.median(arr)), 2) if arr.size else None,
        "jor_max": round(float(arr.max()), 2) if arr.size else None,
    }
