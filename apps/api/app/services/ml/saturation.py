"""Saturation hierarchique (post-prediction) — PL journalier + HPM/HPS horaire.

References:
    - SATURATION_PL_specs.md v3.0 (Travaux_donnees_Lyon/Livrables/xOut/)
    - SATURATION_HPM_HPS_specs.md (Travaux_donnees_Lyon/Livrables/xOut/)

Module extrait depuis ``app.routers.carte`` (refonte pre-execution). Les
fonctions et constantes exposees ici sont importees telles quelles par le
routeur ; aucun comportement n'est modifie par l'extraction.

Sommaire :

* Constantes ``DEFAULT_*`` : bornes par classe fonctionnelle HERE (FC 1..5)
  et hyperparametres v2/v3 — calees sur capteurs SIREDO Lyon 2025 + CEREMA.
* ``_alpha_adaptatif`` : v2 hybride (ratio FCD + plancher FC + plafond physique).
* ``_alpha_v3``        : v3 = v2 + override zones critiques.
* ``_detecter_zones_critiques`` : ETAPE 0 v3 (buffer 1 km capteurs > 15 %).
* ``_saturer_hierarchique`` : noyau generique partage PL/HPM/HPS (cap FC + alpha*TV).
* Alias rétro-compat : ``_saturer_pl_hierarchique`` / ``_saturer_horaire_hierarchique``
  et ``DEFAULT_BORNES_FC`` / ``DEFAULT_ALPHA_FC`` (v1).

Cf. les commentaires inline dans chaque fonction pour la spec detaillee —
NE PAS MODIFIER LES CONSTANTES SANS RELIRE LA SPEC.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    import geopandas as gpd  # noqa: F401

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Saturations hierarchiques — defaults Lyon (PL journalier + HPM/HPS horaire)
# ---------------------------------------------------------------------------
#
# Cf. SATURATION_PL_specs.md et SATURATION_HPM_HPS_specs.md
# (Travaux_donnees_Lyon/Livrables/xOut/) : les modeles peuvent produire des
# aberrations sur certains segments — notamment FC5 (rues locales) avec faible
# TV (exemple PL observe : 17 200 PL/j sur un segment avec JOr=810 v/j).
#
# Le post-traitement hierarchique cape en 2 etapes (puis force la coherence
# min/max) :
#   1) par classe fonctionnelle HERE (cap dur valeur/temps)
#   2) par ratio valeur/TV physiquement plausible (alpha)
#
# Bornes calees sur :
#   - capteurs SIREDO Lyon (PL : max urbain 1 947 PL/j ; HPM/HPS : 991 capteurs)
#   - open data DIRCE / Vinci sur autoroutes A6/A7/A43/A46 (FC1 extrapole)
#   - guide CEREMA *Trafic* (2019) pour les ratios PL/TV par typologie
#   - SETRA *Guide TMJA autoroutier* (2011) pour les profils HPM/HPS FC1
#
# Saturation = POST-prediction ; n'affecte PAS l'entrainement ni les sorties
# brutes des reseaux. Symetrique entre PL/HPM/HPS — meme algorithme generique
# applique sur des triplets (valeur, TV_ref, dict_FC) distincts.

# === Saturation PL v3 hybride adaptative + override zones critiques ========
# Cf SATURATION_PL_specs.md v3.0 (Travaux_donnees_Lyon/Livrables/xOut/) —
# NE PAS MODIFIER LES CONSTANTES SANS RELIRE LA SPEC.
#
# Evolution v1 -> v2 -> v3 :
#
#   v1 (cap rigide)    : PL_sat = min(PL_brut, BORNES_FC_ABS[FC], ALPHA_FC[FC]*TV)
#   v2 (hybride FCD)   : PL_sat = min(PL_brut, BORNES_FC_ABS[FC], alpha_eff*TV)
#                        ou alpha_eff = max(alpha_FCD, ALPHA_FC_MIN[FC])
#                        avec alpha_FCD = (TMJFCDPL/TMJFCDTV) * RATIO_MACRO_PEN
#   v3 (+ override)    : pareil que v2 MAIS dans les zones critiques (buffer
#                        1 km autour des capteurs SIREDO avec ratio observe
#                        > 15 %), le plancher local passe de ALPHA_FC_MIN[FC]
#                        (12-18 % en FC4/FC5) a ALPHA_MIN_ZONE_CRITIQUE = 30 %.
#                        Permet de liberer 3 cas reels :
#                          - Chemin Rouettes (FC5, ratio 40 %)
#                          - Saint-Priest R.Semard (FC5, ratio 16 %)
#                          - Quai R.Rolland (FC3, ratio 31 %)
#
# Dispatch automatique selon les inputs disponibles dans le bloc generate_carte :
#
#         capteurs SIREDO + FCD ----> v3 (hybride + override)
#         FCD seul              ----> v2 (hybride adaptatif)
#         ni capteurs ni FCD    ----> v1 (cap fixe par FC)
#
# Fallback dans v2/v3 : si TMJFCDTV < SEUIL_VOL_FCD_TV (segment degenere),
# alpha_FCD = NaN -> on retombe sur le plancher local (FC ou zone critique).

# Plancher du ratio max PL/TV par FC (= bornes v1 = plancher v2/v3).
DEFAULT_ALPHA_FC_MIN = {1: 0.35, 2: 0.25, 3: 0.18, 4: 0.15, 5: 0.12}

# Cap absolu PL/jour par FC (inchange v1 -> v2 -> v3 ; defense en profondeur).
DEFAULT_BORNES_FC_ABS = {1: 15000, 2: 5000, 3: 3000, 4: 1500, 5: 800}

# Hyperparametres v2 (cf SATURATION_PL_specs.md section "Parametres valides").
DEFAULT_RATIO_MACRO_PEN = 1.137     # mean(TxPenTV)/mean(TxPenPL), 991 capteurs Lyon 2025
DEFAULT_ALPHA_PHYSIQUE_MAX = 0.55   # plafond biomecanique CEREMA (au-dela = aberration)
DEFAULT_SEUIL_VOL_FCD_TV = 50.0     # fallback si TMJFCDTV < seuil (v/j)

# Hyperparametres v3 (override zones critiques) — cf SATURATION_PL_specs.md
# section "Hyperparametres v3".
DEFAULT_RATIO_CAPTEUR_CRITIQUE = 0.15    # capteur critique si TMJOBCPL/TMJOBCTV > 15 %
DEFAULT_BUFFER_ZONE_CRITIQUE_M = 1000.0  # buffer 1 km en EPSG:2154 (Lambert-93)
DEFAULT_ALPHA_MIN_ZONE_CRITIQUE = 0.30   # plancher local eleve dans zones critiques
DEFAULT_ANNEE_CAPTEURS = 2025            # annee de reference pour les capteurs SIREDO

# Alias retro-compat v1 — preserve les imports existants et les anciens
# clients API qui referencaient DEFAULT_BORNES_FC / DEFAULT_ALPHA_FC.
DEFAULT_BORNES_FC = DEFAULT_BORNES_FC_ABS
DEFAULT_ALPHA_FC = DEFAULT_ALPHA_FC_MIN

# === Saturation HPM horaire (PM/PMmin/PMmax) ===
# Cf. SATURATION_HPM_HPS_specs.md — HPM = Heure de Pointe Matin 8h-9h.
# Profil pointe domicile-travail le plus marque (cf section "Differences HPM
# vs HPS"). Bornes : cap absolu val/h base sur max observe + marge ; alpha :
# ratio PM/JOr (= part max HPM journee) cale sur 991 capteurs SIREDO Lyon
# (median ratio_HPM = 7.06%, p99 = 13.46%, max FC2 = 20.21%).
DEFAULT_BORNE_HPM_FC = {1: 5000, 2: 7000, 3: 4000, 4: 1500, 5: 700}
DEFAULT_ALPHA_HPM_FC = {1: 0.10, 2: 0.18, 3: 0.16, 4: 0.18, 5: 0.18}

# === Saturation HPS horaire (PS/PSmin/PSmax) ===
# Cf. SATURATION_HPM_HPS_specs.md — HPS = Heure de Pointe Soir 17h-18h.
# Pointe plus etalee que HPM (retours echelonnes 16h-19h), MAIS plus de
# variabilite sur FC4 (sorties ecoles / livraisons) — d'ou alpha_HPS_FC4=0.20
# cale sur le max observe (capteur 1973 = 19.73%) plutot que sur p99*marge.
DEFAULT_BORNE_HPS_FC = {1: 5000, 2: 7000, 3: 4000, 4: 1500, 5: 800}
DEFAULT_ALPHA_HPS_FC = {1: 0.12, 2: 0.15, 3: 0.15, 4: 0.20, 5: 0.15}


def _alpha_adaptatif(
    fcd_pl: pd.Series,
    fcd_tv: pd.Series,
    fc: pd.Series,
    alpha_fc_min: dict[int, float],
    ratio_macro_pen: float,
    alpha_physique_max: float,
    seuil_vol_fcd_tv: float,
) -> tuple[pd.Series, pd.Series]:
    """Calcule ``alpha_eff`` (ratio PL/TV adaptatif) par segment — v2 hybride.

    Strategie 3 etapes (cf SATURATION_PL_specs.md v2.0 section "Strategie") :

        1) alpha_FCD = (TMJFCDPL / TMJFCDTV) * RATIO_MACRO_PEN
        2) alpha     = max(alpha_FCD, ALPHA_FC_MIN[FC])
        3) alpha_eff = min(alpha, ALPHA_PHYSIQUE_MAX)

    Fallback : si TMJFCDTV < SEUIL_VOL_FCD_TV (segment degenere/bruite), on
    retombe sur le plancher FC (ALPHA_FC_MIN). Evite l'explosion numerique
    sur les segments a tres faible volume FCD.

    **Ne pas modifier sans relire la spec** (SATURATION_PL_specs.md v2.0).

    Args:
        fcd_pl : TMJOFCDPL (FCD brut PL journalier, v/j).
        fcd_tv : TMJOFCDTV (FCD brut TV journalier, v/j).
        fc     : functional class HERE (1..5). NaN -> 5 (le plus restrictif).
        alpha_fc_min       : plancher du ratio PL/TV par FC (= bornes v1).
        ratio_macro_pen    : ratio mean(TxPenTV)/mean(TxPenPL) — correction
                             biais de penetration global flotte.
        alpha_physique_max : plafond biomecanique (au-dela = aberration).
        seuil_vol_fcd_tv   : seuil v/j en dessous duquel on bascule sur le
                             plancher FC (fallback).

    Returns:
        (alpha_eff, source) :
            - ``alpha_eff`` : Serie float (ratio applique par segment, [0, alpha_physique_max]).
            - ``source`` : Serie string parmi {"plancher_fallback", "plancher_FC",
              "fcd", "plafond"} — diagnostic de la branche retenue.
    """
    # FC: clip [1, 5], NaN -> 5 (cap le plus strict pour garantir securite).
    fc_c = fc.fillna(5).clip(1, 5).astype(int)
    alpha_min_arr = fc_c.map(alpha_fc_min).astype(float).to_numpy()

    fcd_pl_arr = pd.to_numeric(fcd_pl, errors="coerce").fillna(0).astype(float).to_numpy()
    fcd_tv_arr = pd.to_numeric(fcd_tv, errors="coerce").fillna(0).astype(float).to_numpy()

    # Garde-fou : si TMJFCDTV < seuil, NaN -> fallback plancher.
    # np.errstate evite les RuntimeWarning divide/invalid sur les valeurs NaN.
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha_fcd_raw = np.where(
            fcd_tv_arr >= seuil_vol_fcd_tv,
            (fcd_pl_arr / np.maximum(fcd_tv_arr, 1e-6)) * ratio_macro_pen,
            np.nan,
        )

    # Hybride : max(plancher_FC, alpha_FCD), avec fallback plancher si NaN.
    alpha = np.where(
        np.isnan(alpha_fcd_raw),
        alpha_min_arr,
        np.maximum(alpha_min_arr, alpha_fcd_raw),
    )

    # Plafond physique (biomecanique CEREMA).
    alpha_eff = np.minimum(alpha, alpha_physique_max)

    # Diagnostic source de la branche retenue (4 valeurs possibles) :
    #   - "plancher_fallback" : FCD_TV < seuil -> fallback plancher FC.
    #   - "plafond"           : alpha_FCD > ALPHA_PHYSIQUE_MAX -> cape.
    #   - "plancher_FC"       : alpha_FCD <= plancher FC -> plancher applique.
    #   - "fcd"               : alpha_FCD pris tel quel (cas nominal).
    # Ordre des np.where = priorite : fallback > plafond > plancher_FC > fcd.
    source = np.where(
        np.isnan(alpha_fcd_raw),
        "plancher_fallback",
        np.where(
            np.isclose(alpha_eff, alpha_physique_max),
            "plafond",
            np.where(
                np.isclose(alpha_eff, alpha_min_arr),
                "plancher_FC",
                "fcd",
            ),
        ),
    )

    return (
        pd.Series(alpha_eff, index=fcd_pl.index),
        pd.Series(source, index=fcd_pl.index),
    )


def _detecter_zones_critiques(
    capteurs_pl: "gpd.GeoDataFrame",
    segments: "gpd.GeoDataFrame",
    annee: int,
    ratio_seuil: float,
    buffer_m: float,
) -> pd.Series:
    """Detecte les segments dans une zone critique (override v3).

    Cf SATURATION_PL_specs.md v3.0 section "Hyperparametres v3" / "ETAPE 0".

    Logique :
        1. Filtrer les capteurs SIREDO PL sur l'annee de reference.
        2. Calculer ratio_obs = TMJOBCPL / TMJOBCTV (proxy ratio reel PL/TV).
        3. Marquer comme "critiques" les capteurs avec ratio_obs > ratio_seuil
           (typiquement 15 % = bien au-dela de la mediane 7 %).
        4. Buffer geometrique de buffer_m metres (typiquement 1 km) en EPSG:2154
           autour de ces capteurs (= zone d'influence physique du capteur).
        5. Un segment est "en zone critique" s'il intersecte ce buffer.

    Si aucun capteur n'est trouve pour l'annee, ou si aucun capteur n'est
    critique, retourne un mask all-False (fallback gracieux vers v2).

    Args:
        capteurs_pl : GeoDataFrame des capteurs SIREDO PL — colonnes requises :
                      ``TMJOBCPL``, ``TMJOBCTV``, ``annee``, ``geometry`` (Point WGS84).
        segments    : GeoDataFrame des segments cible (LineString WGS84).
        annee       : annee de reference pour filtrer ``capteurs_pl["annee"]``.
        ratio_seuil : seuil sur ratio_obs (typiquement 0.15).
        buffer_m    : rayon du buffer en metres (typiquement 1000.0).

    Returns:
        pd.Series bool indexee comme ``segments`` (True = zone critique).
    """
    import geopandas as gpd  # noqa: F401 — lazy import (cf upload.py pattern)

    cap_annee = capteurs_pl[capteurs_pl["annee"] == annee].copy()
    if len(cap_annee) == 0:
        logger.info(
            "Detection zones critiques : aucun capteur SIREDO trouve pour annee=%d",
            annee,
        )
        return pd.Series(False, index=segments.index)

    cap_annee = cap_annee.dropna(subset=["TMJOBCPL", "TMJOBCTV"])
    cap_annee["ratio_obs"] = (
        cap_annee["TMJOBCPL"] / cap_annee["TMJOBCTV"].replace(0, np.nan)
    )
    crit = cap_annee[cap_annee["ratio_obs"] > ratio_seuil]

    if len(crit) == 0:
        logger.info(
            "Detection zones critiques : 0 capteur > seuil %.2f (sur %d capteurs %d)",
            ratio_seuil, len(cap_annee), annee,
        )
        return pd.Series(False, index=segments.index)

    logger.info(
        "Detection zones critiques : %d capteurs > seuil %.2f (sur %d capteurs %d)",
        len(crit), ratio_seuil, len(cap_annee), annee,
    )

    # Buffer en EPSG:2154 (Lambert-93, metrique). Echec geometrique -> all-False.
    try:
        crit_m = crit.to_crs("EPSG:2154")
        # union_all() = nouveau nom (>= shapely 2). Fallback unary_union si besoin.
        try:
            buffer_union = crit_m.geometry.buffer(buffer_m).union_all()
        except AttributeError:
            buffer_union = crit_m.geometry.buffer(buffer_m).unary_union
        seg_m = segments.to_crs("EPSG:2154")
        mask = seg_m.geometry.intersects(buffer_union)
        return pd.Series(mask.values, index=segments.index)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Detection zones critiques : echec geometrique (%s) -> fallback no critical",
            exc,
        )
        return pd.Series(False, index=segments.index)


def _alpha_v3(
    fcd_pl: pd.Series,
    fcd_tv: pd.Series,
    fc: pd.Series,
    is_critical: pd.Series,
    alpha_fc_min: dict[int, float],
    ratio_macro_pen: float,
    alpha_physique_max: float,
    seuil_vol_fcd_tv: float,
    alpha_min_zone_critique: float,
) -> tuple[pd.Series, pd.Series]:
    """Calcule ``alpha_eff`` v3 = v2 hybride + override zones critiques.

    Cf SATURATION_PL_specs.md v3.0 sections "ETAPE 1/2/3" / "alpha_v3".

    Strategie hierarchique :

        ETAPE 1 : alpha_FCD = (TMJFCDPL / TMJFCDTV) * RATIO_MACRO_PEN
                  (NaN si TMJFCDTV < seuil_vol_fcd_tv -> fallback plancher)

        ETAPE 2 : plancher_local = ALPHA_MIN_ZONE_CRITIQUE si is_critical,
                                   sinon ALPHA_FC_MIN[FC]
                  alpha = max(alpha_FCD, plancher_local)

        ETAPE 3 : alpha_eff = min(alpha, ALPHA_PHYSIQUE_MAX)

    Diagnostic ``source`` :
        - ``plancher_fallback``      : TMJFCDTV < seuil, plancher FC (hors crit).
        - ``plancher_zone_critique`` : segment dans zone critique (NaN ou plancher).
        - ``plancher_FC``            : alpha_FCD <= plancher FC, plancher applique.
        - ``fcd``                    : alpha_FCD pris tel quel (cas nominal).
        - ``plafond``                : alpha_FCD > ALPHA_PHYSIQUE_MAX, cap.

    Args:
        fcd_pl                   : TMJOFCDPL (FCD brut PL journalier, v/j).
        fcd_tv                   : TMJOFCDTV (FCD brut TV journalier, v/j).
        fc                       : functional class HERE (1..5). NaN -> 5.
        is_critical              : bool Series, True = segment en zone critique.
        alpha_fc_min             : plancher du ratio PL/TV par FC (= bornes v1).
        ratio_macro_pen          : correction biais de penetration global flotte.
        alpha_physique_max       : plafond biomecanique CEREMA (au-dela = aberration).
        seuil_vol_fcd_tv         : seuil v/j en dessous duquel on bascule sur le
                                   plancher local (fallback).
        alpha_min_zone_critique  : plancher dans zones critiques (typiquement 0.30).

    Returns:
        (alpha_eff, source) — deux Series alignees sur ``fcd_pl.index``.
    """
    # FC: clip [1, 5], NaN -> 5 (cap le plus strict pour garantir securite).
    fc_c = fc.fillna(5).clip(1, 5).astype(int)
    alpha_min_fc_arr = fc_c.map(alpha_fc_min).astype(float).to_numpy()
    is_crit_arr = is_critical.astype(bool).to_numpy()

    # Plancher LOCAL v3 : 0.30 dans zones critiques, sinon plancher FC (v2).
    alpha_min_local = np.where(
        is_crit_arr, alpha_min_zone_critique, alpha_min_fc_arr,
    )

    fcd_pl_arr = pd.to_numeric(fcd_pl, errors="coerce").fillna(0).astype(float).to_numpy()
    fcd_tv_arr = pd.to_numeric(fcd_tv, errors="coerce").fillna(0).astype(float).to_numpy()

    # ETAPE 1 : alpha_FCD avec garde-fou seuil_vol_fcd_tv.
    # np.errstate evite les RuntimeWarning divide/invalid sur les valeurs NaN.
    with np.errstate(divide="ignore", invalid="ignore"):
        alpha_fcd_raw = np.where(
            fcd_tv_arr >= seuil_vol_fcd_tv,
            (fcd_pl_arr / np.maximum(fcd_tv_arr, 1e-6)) * ratio_macro_pen,
            np.nan,
        )

    # ETAPE 2 : alpha = max(alpha_FCD, plancher_local) ; fallback plancher si NaN.
    alpha = np.where(
        np.isnan(alpha_fcd_raw),
        alpha_min_local,
        np.maximum(alpha_min_local, alpha_fcd_raw),
    )

    # ETAPE 3 : plafond physique (biomecanique CEREMA).
    alpha_eff = np.minimum(alpha, alpha_physique_max)

    # Diagnostic source (5 valeurs possibles). Priorite :
    #   fallback (NaN FCD) > plafond > plancher_local > fcd nominal.
    source = np.where(
        np.isnan(alpha_fcd_raw),
        np.where(is_crit_arr, "plancher_zone_critique", "plancher_fallback"),
        np.where(
            np.isclose(alpha_eff, alpha_physique_max),
            "plafond",
            np.where(
                np.isclose(alpha_eff, alpha_min_local),
                np.where(is_crit_arr, "plancher_zone_critique", "plancher_FC"),
                "fcd",
            ),
        ),
    )

    return (
        pd.Series(alpha_eff, index=fcd_pl.index),
        pd.Series(source, index=fcd_pl.index),
    )


def _saturer_hierarchique(
    value_pred: pd.Series,
    tv_pred: pd.Series,
    fc: pd.Series,
    borne_fc: dict[int, float],
    alpha_fc: dict[int, float],
) -> tuple[pd.Series, pd.Series]:
    """Sature une valeur (PL/PM/PS) avec cap FC + cap valeur <= alpha * TV.

    Fonction generique partagee par les saturations PL (journaliere, v/j) et
    HPM/HPS (horaires, v/h) — cf SATURATION_PL_specs.md et
    SATURATION_HPM_HPS_specs.md. Saturation hierarchique 2 etapes :

        1) value = min(value_brut, borne_fc[FC])
        2) value = min(value, alpha_fc[FC] * tv_pred)

    Suivi d'un clip a 0 (>= 0) et d'un cast int32. La coherence min/max
    (PLmin <= PL <= PLmax, etc.) est imposee a l'appelant via np.minimum /
    np.maximum apres saturation independante des 3 series.

    Args:
        value_pred : prediction brute (DPL / PM / PS / leurs min/max).
        tv_pred    : TV de reference associe :
                       - PL  : JOr / JOrmin / JOrmax (journalier, v/j)
                       - HPM/HPS : JOr / JOrmin / JOrmax (v/j de reference pour
                         le cap alpha*JOr).
        fc         : functional class HERE (1..5). NaN -> 5 (le plus restrictif).
        borne_fc   : cap dur valeur par FC (val/j pour PL, val/h pour HPM/HPS).
        alpha_fc   : ratio max valeur/TV par FC (0..1).

    Returns:
        (value_sat, mask_saturated)
            - value_sat : Serie int32 saturee (index aligne sur value_pred).
            - mask_saturated : Serie bool — True si la valeur a ete capee.
    """
    # FC: clip [1, 5], NaN -> 5 (cap le plus strict pour garantir securite).
    fc_clip = fc.fillna(5).clip(1, 5).astype(int)
    cap_fc = fc_clip.map(borne_fc).astype(float).to_numpy()
    # TV : NaN -> 0 (cf spec section "Cas limites" §2). 0 forcera value=0
    # via le cap alpha*TV (jamais NaN propage).
    tv_clean = pd.to_numeric(tv_pred, errors="coerce").fillna(0).astype(float)
    cap_tv = fc_clip.map(alpha_fc).astype(float).to_numpy() * tv_clean.to_numpy()

    v_f = pd.to_numeric(value_pred, errors="coerce").fillna(0).astype(float).to_numpy()
    v_sat_arr = np.minimum.reduce([v_f, cap_fc, cap_tv])
    # Clip valeur >= 0 (les modeles peuvent sortir <0 en extrapolation rare).
    v_sat_arr = np.maximum(v_sat_arr, 0)
    v_sat_arr = np.round(v_sat_arr).astype("int32")

    v_orig_int = np.round(v_f).astype("int32")
    mask_arr = v_sat_arr != v_orig_int

    return (
        pd.Series(v_sat_arr, index=value_pred.index),
        pd.Series(mask_arr, index=value_pred.index),
    )


# Alias retrocompat — preserve l'import explicite ``_saturer_pl_hierarchique``
# par les tests et le code en place (cf test_routers_carte.py baseline).
_saturer_pl_hierarchique = _saturer_hierarchique
_saturer_horaire_hierarchique = _saturer_hierarchique


__all__ = [
    # Constantes PL v1/v2/v3
    "DEFAULT_ALPHA_FC_MIN",
    "DEFAULT_BORNES_FC_ABS",
    "DEFAULT_RATIO_MACRO_PEN",
    "DEFAULT_ALPHA_PHYSIQUE_MAX",
    "DEFAULT_SEUIL_VOL_FCD_TV",
    "DEFAULT_RATIO_CAPTEUR_CRITIQUE",
    "DEFAULT_BUFFER_ZONE_CRITIQUE_M",
    "DEFAULT_ALPHA_MIN_ZONE_CRITIQUE",
    "DEFAULT_ANNEE_CAPTEURS",
    # Alias retro-compat v1
    "DEFAULT_BORNES_FC",
    "DEFAULT_ALPHA_FC",
    # Constantes HPM / HPS
    "DEFAULT_BORNE_HPM_FC",
    "DEFAULT_ALPHA_HPM_FC",
    "DEFAULT_BORNE_HPS_FC",
    "DEFAULT_ALPHA_HPS_FC",
    # Fonctions
    "_alpha_adaptatif",
    "_detecter_zones_critiques",
    "_alpha_v3",
    "_saturer_hierarchique",
    "_saturer_pl_hierarchique",
    "_saturer_horaire_hierarchique",
]
