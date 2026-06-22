"""Tests for arrondi progressif (cf ARRONDI_PROGRESSIF_specs.md, Option B).

Couvre :
  - `_round_progressive` : 3 paliers (<100/x5, <1000/x10, >=1000/x100).
  - `_appliquer_arrondi_avec_coherence` : preserve min <= central <= max.
  - Cas limites : negatifs, NaN, zero, valeur exacte d'un multiple.

Imports : nouveau chemin `app.services.ml.rounding` si dispo (autre agent),
sinon fallback `app.routers.carte`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Imports avec fallback (refactor en cours par autre agent)
# ---------------------------------------------------------------------------

try:
    from app.services.ml.rounding import (
        _appliquer_arrondi_avec_coherence,
        _round_progressive,
    )

    _IMPORT_SOURCE = "services.ml.rounding"
except ImportError:
    from app.routers.carte import (
        _appliquer_arrondi_avec_coherence,
        _round_progressive,
    )

    _IMPORT_SOURCE = "routers.carte"


# ---------------------------------------------------------------------------
# _round_progressive — paliers
# ---------------------------------------------------------------------------


class TestRoundProgressivePaliers:
    """Verifie l'arrondi 3 paliers <100/x5, <1000/x10, >=1000/x100."""

    def test_round_progressive_paliers(self):
        """[12, 47, 173, 583, 2847, 5807] -> [10, 45, 170, 580, 2800, 5800].

        - 12  < 100  -> 12/5 = 2.4 -> 2  -> 10
        - 47  < 100  -> 47/5 = 9.4 -> 9  -> 45
        - 173 < 1000 -> 173/10 = 17.3 -> 17 -> 170
        - 583 < 1000 -> 583/10 = 58.3 -> 58 -> 580
        - 2847 >= 1000 -> 2847/100 = 28.47 -> 28 -> 2800
        - 5807 >= 1000 -> 5807/100 = 58.07 -> 58 -> 5800
        """
        s = pd.Series([12, 47, 173, 583, 2847, 5807])
        out = _round_progressive(s)
        expected = [10, 45, 170, 580, 2800, 5800]
        assert list(out) == expected

    def test_round_progressive_negatives(self):
        """Valeurs negatives : casting `int32` est ok mais on attend que
        l'arrondi independant clip implicitement vers 0. Pas de plancher
        explicite dans `_round_progressive` (cf spec : le clamp >= 0 est
        applique par l'appelant). Ce test verifie juste qu'il ne crashe pas
        et qu'on obtient un int32 propre.

        Au passage : -23 < 100 -> palier x5 -> round(-23/5)*5 = -25.
        """
        s = pd.Series([-23.0, -2.0])
        out = _round_progressive(s)
        # Pas d'exception levee + cast int32
        assert out.dtype == np.int32
        # -23/5 = -4.6 -> round to -5 -> -25
        assert out.iloc[0] == -25
        # -2/5 = -0.4 -> round to 0 -> 0 (banker's rounding in numpy)
        assert out.iloc[1] == 0

    def test_round_progressive_nan(self):
        """NaN -> fillna(0) en interne -> 0 (cf implementation)."""
        s = pd.Series([np.nan, 50.0, np.nan])
        out = _round_progressive(s)
        # NaN -> 0 ; 50 < 100 -> round(50/5)*5 = 50
        assert out.iloc[0] == 0
        assert out.iloc[1] == 50
        assert out.iloc[2] == 0

    def test_round_progressive_zero(self):
        """0 -> 0 (cas trivial)."""
        s = pd.Series([0.0, 0])
        out = _round_progressive(s)
        assert list(out) == [0, 0]

    def test_round_progressive_1000_exact(self):
        """1000 -> 1000 (frontiere palier 10 / palier 100, exact)."""
        s = pd.Series([1000.0])
        out = _round_progressive(s)
        # 1000 >= 1000 -> round(1000/100)*100 = 1000 (exact)
        assert out.iloc[0] == 1000

    def test_round_progressive_100_exact(self):
        """100 -> 100 (frontiere palier 5 / palier 10, exact)."""
        s = pd.Series([100.0])
        out = _round_progressive(s)
        # 100 >= 100 et 100 < 1000 -> round(100/10)*10 = 100 (exact)
        assert out.iloc[0] == 100

    def test_round_progressive_99_under_100(self):
        """99 < 100 -> palier x5 -> round(99/5)*5 = 100 (oui, depasse la borne)."""
        s = pd.Series([99.0])
        out = _round_progressive(s)
        # round(99/5)*5 = round(19.8)*5 = 20*5 = 100
        assert out.iloc[0] == 100

    def test_round_progressive_999_under_1000(self):
        """999 < 1000 -> palier x10 -> round(999/10)*10 = 1000."""
        s = pd.Series([999.0])
        out = _round_progressive(s)
        # round(999/10)*10 = 100*10 = 1000
        assert out.iloc[0] == 1000


# ---------------------------------------------------------------------------
# _appliquer_arrondi_avec_coherence — preserve l'ordre min<=central<=max
# ---------------------------------------------------------------------------


class TestAppliquerArrondiAvecCoherence:
    """Tests le wrapper qui force min <= central <= max apres arrondi
    independant des trois series."""

    def test_appliquer_arrondi_avec_coherence_min_max(self):
        """Apres arrondi independant, force min <= central <= max.

        Exemple force ou l'arrondi casserait l'ordre :
          - JOrmin=145, JOr=148, JOrmax=152
          - arrondi independant : 145, 150, 150
          - le min (145) reste < central (150) -> OK,
          - mais on doit s'assurer que le code n'inverse pas l'ordre.
        """
        df = pd.DataFrame(
            {
                "JOrmin": [145.0, 80.0, 110.0],
                "JOr": [148.0, 95.0, 130.0],
                "JOrmax": [152.0, 105.0, 175.0],
            }
        )
        out = _appliquer_arrondi_avec_coherence(
            df.copy(),
            [("JOrmin", "JOr", "JOrmax")],
        )
        # Coherence : min <= central <= max sur toutes les lignes
        assert (out["JOrmin"] <= out["JOr"]).all()
        assert (out["JOr"] <= out["JOrmax"]).all()

    def test_appliquer_arrondi_avec_coherence_multiple_triplets(self):
        """Plusieurs triplets traites en un appel (JOr, DPL, PM, PS)."""
        df = pd.DataFrame(
            {
                "JOrmin": [145.0],
                "JOr": [148.0],
                "JOrmax": [152.0],
                "DPLmin": [40.0],
                "DPL": [42.0],
                "DPLmax": [45.0],
            }
        )
        out = _appliquer_arrondi_avec_coherence(
            df.copy(),
            [("JOrmin", "JOr", "JOrmax"), ("DPLmin", "DPL", "DPLmax")],
        )
        assert out["JOrmin"].iloc[0] <= out["JOr"].iloc[0] <= out["JOrmax"].iloc[0]
        assert out["DPLmin"].iloc[0] <= out["DPL"].iloc[0] <= out["DPLmax"].iloc[0]

    def test_appliquer_arrondi_missing_columns_skipped(self):
        """Si une colonne du triplet n'est pas la, on skip silencieusement (no crash)."""
        df = pd.DataFrame({"JOrmin": [10.0], "JOr": [20.0]})  # pas de JOrmax
        out = _appliquer_arrondi_avec_coherence(
            df.copy(),
            [("JOrmin", "JOr", "JOrmax")],
        )
        # JOrmin et JOr sont arrondis ; JOrmax n'est pas cree.
        assert "JOrmax" not in out.columns or pd.api.types.is_numeric_dtype(out.get("JOrmax"))


# ---------------------------------------------------------------------------
# Source de l'import (audit)
# ---------------------------------------------------------------------------


def test_import_source_visible():
    """Note l'origine des imports (audit, pas check fonctionnel)."""
    assert _IMPORT_SOURCE in ("services.ml.rounding", "routers.carte")
