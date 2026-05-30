"""Arrondi progressif + IC DPL (Option B, cf ARRONDI_PROGRESSIF_specs.md).

Reference: ARRONDI_PROGRESSIF_specs.md (Travaux_donnees_Lyon/Livrables/xOut/).

Module extrait depuis ``app.routers.carte`` (refonte pre-execution). La regle
3 paliers (multiples de 5/10/100 selon ordre de grandeur) est appliquee
POST-saturation et POST-IC sur les triplets (min, central, max), avec
preservation de la coherence ordinale.

Sommaire :

* ``_round_progressive``                 : noyau (3 paliers).
* ``_appliquer_arrondi_avec_coherence``  : arrondi + force min <= central <= max.
* ``_calculer_DPLmin`` / ``_calculer_DPLmax`` : bandes de confiance DPL par
  tranches JOr (calees sur incertitude observee CEREMA/SIREDO).

Les magic numbers des bornes DPL min/max sont nommes via les tables
``_DPL_MIN_BANDS`` / ``_DPL_MAX_BANDS`` — NE PAS modifier sans relire la spec.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constantes IC DPL — bandes de confiance par tranches JOr
# ---------------------------------------------------------------------------
#
# Cf ARRONDI_PROGRESSIF_specs.md + ETUDE_INCERTITUDE_PL (Lyon 2025) :
# les ratios PLmin/JOr et PLmax/JOr decroissent quand JOr augmente (modele
# plus stable sur fort volume). Tables `(seuil_jor, coefficient)` triees par
# seuil croissant ; on prend la 1re entree dont JOr < seuil. La derniere
# entree est la branche default (seuil = +inf).
#
# Borne inferieure : DPLmin = coef_min(JOr) * JOr
_DPL_MIN_COEFS = {
    "lt_500": 0.75,        # JOr < 500       -> 0.75 * JOr (ratio mediane CEREMA)
    "lt_1000": 0.85,       # 500 <= JOr < 1000
    "lt_2000": 0.85,       # 1000 <= JOr < 2000
    "lt_4000": 0.88,       # 2000 <= JOr < 4000
    "lt_6000": 0.88,       # 4000 <= JOr < 6000
    "lt_10000": 0.88,      # 6000 <= JOr < 10000
    "ge_10000": 0.88,      # JOr >= 10000 — branche speciale avec marge -1500
}
# Marge soustractive (en v/j) appliquee sur la branche JOr >= 10000.
# Capage final : max(JOr - 1500, round(coef * JOr, -2)).
_DPL_MIN_HIGH_MARGIN = 1500

# Borne superieure : DPLmax = coef_max(JOr) * JOr, avec un floor de +10 (cf
# spec § "Cas limites" : eviter DPLmax = DPL exactement).
_DPL_MAX_COEFS = {
    "lt_500": 1.25,        # JOr < 500       -> 1.25 * JOr (marge max obs.)
    "lt_1000": 1.25,
    "lt_2000": 1.15,
    "lt_4000": 1.12,
    "lt_6000": 1.12,
    "lt_10000": 1.12,
    "ge_10000": 1.12,      # branche speciale avec plafond +1500
}
_DPL_MAX_FLOOR_OFFSET = 10
# Marge additive (en v/j) appliquee comme plafond de la branche JOr >= 10000.
# Capage final : min(round(max(coef * JOr, JOr + 10), -2), JOr + 1500), -2).
_DPL_MAX_HIGH_MARGIN = 1500


# ---------------------------------------------------------------------------
# Arrondi progressif (Option B, cf ARRONDI_PROGRESSIF_specs.md)
# ---------------------------------------------------------------------------
#
# Regle 3 paliers — cale sur lisibilite operationnelle (rapports cartographiques) :
#       v < 100         -> multiple de 5
#       100 <= v < 1000 -> multiple de 10
#       v >= 1000       -> multiple de 100
#
# Appliquee POST-saturation et POST-IC sur les triplets (min, central, max) :
#       (JOrmin, JOr, JOrmax), (DPLmin, DPL, DPLmax), (PMmin, PM, PMmax), (PSmin, PS, PSmax)
# La coherence ordinale (min <= central <= max) est imposee en post-traitement :
# un arrondi independant peut casser l'ordre (ex : 145, 148, 152 -> 145, 150, 150).

def _round_progressive(s: pd.Series) -> pd.Series:
    """Arrondi 3 paliers (Option B, cf ARRONDI_PROGRESSIF_specs.md):
       v < 100         -> multiple de 5
       100 <= v < 1000 -> multiple de 10
       v >= 1000       -> multiple de 100
    """
    arr = pd.to_numeric(s, errors="coerce").fillna(0).astype(float).to_numpy()
    out = np.where(
        arr < 100,
        np.round(arr / 5) * 5,
        np.where(
            arr < 1000,
            np.round(arr / 10) * 10,
            np.round(arr / 100) * 100,
        ),
    )
    return pd.Series(out.astype("int32"), index=s.index)


def _appliquer_arrondi_avec_coherence(
    df: pd.DataFrame,
    triplets: list[tuple[str, str, str]],
) -> pd.DataFrame:
    """Arrondi progressif + preservation min <= central <= max.

    L'arrondi independant des 3 series peut violer l'ordre ; on force la
    coherence numerique a posteriori (cf ARRONDI_PROGRESSIF_specs.md
    section "Cas limites").
    """
    for col_min, col_central, col_max in triplets:
        for c in (col_min, col_central, col_max):
            if c in df.columns:
                df[c] = _round_progressive(df[c])
        # Coherence ordinale (arrondi independant peut casser min <= central).
        if col_min in df.columns and col_central in df.columns:
            df[col_min] = np.minimum(df[col_min], df[col_central]).astype("int32")
        if col_max in df.columns and col_central in df.columns:
            df[col_max] = np.maximum(df[col_max], df[col_central]).astype("int32")
    return df


def _calculer_DPLmin(JOr: float) -> float:
    """Borne inferieure IC DPL (cf ``_DPL_MIN_COEFS``).

    Bandes calees par tranches JOr : coef decroissant pour JOr < 500 (0.75)
    -> 0.88 au-dela de 2000. Branche speciale JOr >= 10000 :
    ``max(JOr - 1500, round(0.88 * JOr, -2))`` (rounding aux 100 v/j).
    """
    if JOr < 500:
        return max(0.0, _DPL_MIN_COEFS["lt_500"] * JOr)
    elif JOr < 1000:
        return max(0.0, _DPL_MIN_COEFS["lt_1000"] * JOr)
    elif JOr < 2000:
        return max(0.0, _DPL_MIN_COEFS["lt_2000"] * JOr)
    elif JOr < 4000:
        return max(0.0, _DPL_MIN_COEFS["lt_4000"] * JOr)
    elif JOr < 6000:
        return max(0.0, _DPL_MIN_COEFS["lt_6000"] * JOr)
    elif JOr < 10000:
        return max(0.0, _DPL_MIN_COEFS["lt_10000"] * JOr)
    else:
        return round(
            max(
                JOr - _DPL_MIN_HIGH_MARGIN,
                round(_DPL_MIN_COEFS["ge_10000"] * JOr, -2),
            ),
            -2,
        )


def _calculer_DPLmax(JOr: float) -> float:
    """Borne superieure IC DPL (cf ``_DPL_MAX_COEFS``).

    Bandes calees par tranches JOr : coef decroissant 1.25 -> 1.12.
    Floor systematique : DPLmax >= JOr + 10 (cf spec § "Cas limites"
    pour eviter DPLmax = DPL). Branche speciale JOr >= 10000 avec plafond
    JOr + 1500.
    """
    if JOr < 500:
        return max(_DPL_MAX_COEFS["lt_500"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET)
    elif JOr < 1000:
        return round(
            max(_DPL_MAX_COEFS["lt_1000"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET), -2,
        )
    elif JOr < 2000:
        return round(
            max(_DPL_MAX_COEFS["lt_2000"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET), -2,
        )
    elif JOr < 4000:
        return round(
            max(_DPL_MAX_COEFS["lt_4000"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET), -2,
        )
    elif JOr < 6000:
        return round(
            max(_DPL_MAX_COEFS["lt_6000"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET), -2,
        )
    elif JOr < 10000:
        return round(
            max(_DPL_MAX_COEFS["lt_10000"] * JOr, JOr + _DPL_MAX_FLOOR_OFFSET), -2,
        )
    else:
        return round(
            min(
                round(
                    max(
                        _DPL_MAX_COEFS["ge_10000"] * JOr,
                        JOr + _DPL_MAX_FLOOR_OFFSET,
                    ),
                    -2,
                ),
                JOr + _DPL_MAX_HIGH_MARGIN,
            ),
            -2,
        )


__all__ = [
    "_round_progressive",
    "_appliquer_arrondi_avec_coherence",
    "_calculer_DPLmin",
    "_calculer_DPLmax",
]
