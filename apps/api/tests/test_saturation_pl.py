"""Tests for PL saturation v3 hybride adaptative + override zones critiques.

Cf SATURATION_PL_specs.md v3.0 + audit T2 § "Tests critiques manquants".

Imports : new path `app.services.ml.saturation` if it exists (autre agent en
cours de refactor), sinon fallback sur `app.routers.carte` ou les constantes/
fonctions vivent encore aujourd'hui.
"""

from __future__ import annotations

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Imports compatibles 2 chemins (refactor en cours par autre agent)
# ---------------------------------------------------------------------------

try:
    # Chemin cible apres refactor (autre agent)
    from app.services.ml.saturation import (
        DEFAULT_ALPHA_FC_MIN,
        DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        DEFAULT_ALPHA_PHYSIQUE_MAX,
        DEFAULT_BORNES_FC_ABS,
        DEFAULT_RATIO_MACRO_PEN,
        DEFAULT_SEUIL_VOL_FCD_TV,
        _alpha_v3,
        _detecter_zones_critiques,
        _saturer_hierarchique,
    )

    _IMPORT_SOURCE = "services.ml.saturation"
except ImportError:
    # Chemin actuel (avant refactor) - constantes et fonctions vivent dans routers/carte.py
    from app.routers.carte import (
        DEFAULT_ALPHA_FC_MIN,
        DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        DEFAULT_ALPHA_PHYSIQUE_MAX,
        DEFAULT_BORNES_FC_ABS,
        DEFAULT_RATIO_MACRO_PEN,
        DEFAULT_SEUIL_VOL_FCD_TV,
        _alpha_v3,
        _detecter_zones_critiques,
        _saturer_hierarchique,
    )

    _IMPORT_SOURCE = "routers.carte"


# ---------------------------------------------------------------------------
# _alpha_v3 - branche par branche
# ---------------------------------------------------------------------------


class TestAlphaV3:
    """Tests unitaires de la fonction _alpha_v3 (v3 = v2 + override zone critique)."""

    def test_alpha_v3_zone_critique(self):
        """Dans une zone critique, le plancher local DOIT etre 0.30 (vs 0.12-0.18 selon FC)."""
        # FC5 (alpha_fc_min = 0.12) avec FCD trop faible pour deduire alpha_FCD
        # (TMJOFCDPL = 0, TMJOFCDTV > seuil) -> alpha_FCD = 0
        # Sans zone critique : plancher = 0.12 ; avec zone critique : plancher = 0.30.
        fcd_pl = pd.Series([0.0])
        fcd_tv = pd.Series([1000.0])
        fc = pd.Series([5])
        is_crit = pd.Series([True])

        alpha_eff, _ = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # Plancher zone critique = 0.30 (vs 0.12 du FC5)
        assert alpha_eff.iloc[0] == pytest.approx(DEFAULT_ALPHA_MIN_ZONE_CRITIQUE, abs=1e-6)

    def test_alpha_v3_zone_non_critique(self):
        """Hors zone critique, plancher = ALPHA_FC_MIN[FC]."""
        # FC5 (plancher 0.12) hors zone critique
        fcd_pl = pd.Series([0.0])
        fcd_tv = pd.Series([1000.0])  # TMJFCDTV > seuil -> alpha_FCD = 0
        fc = pd.Series([5])
        is_crit = pd.Series([False])

        alpha_eff, source = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # Plancher FC5 = 0.12
        assert alpha_eff.iloc[0] == pytest.approx(DEFAULT_ALPHA_FC_MIN[5], abs=1e-6)
        assert source.iloc[0] == "plancher_FC"

    def test_alpha_v3_fallback_no_fcd(self):
        """TMJFCDTV < 50 -> NaN dans alpha_FCD -> fallback plancher local."""
        fcd_pl = pd.Series([10.0])
        fcd_tv = pd.Series([20.0])  # < SEUIL_VOL_FCD_TV (50)
        fc = pd.Series([3])
        is_crit = pd.Series([False])

        alpha_eff, source = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # Fallback plancher FC3 = 0.18 (hors zone critique)
        assert alpha_eff.iloc[0] == pytest.approx(DEFAULT_ALPHA_FC_MIN[3], abs=1e-6)
        assert source.iloc[0] == "plancher_fallback"

    def test_alpha_v3_plafond(self):
        """Ratio FCD enorme (> 0.55) -> cap a ALPHA_PHYSIQUE_MAX = 0.55."""
        # Ratio brut 80% (avant correction) -> apres x1.137 -> ~0.91 -> cap a 0.55
        fcd_pl = pd.Series([800.0])
        fcd_tv = pd.Series([1000.0])
        fc = pd.Series([3])
        is_crit = pd.Series([False])

        alpha_eff, source = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # Cap a 0.55
        assert alpha_eff.iloc[0] == pytest.approx(DEFAULT_ALPHA_PHYSIQUE_MAX, abs=1e-6)
        assert source.iloc[0] == "plafond"

    def test_alpha_v3_fcd_adaptatif(self):
        """Ratio FCD entre plancher et plafond -> branche nominale 'fcd'."""
        # Cas nominal : alpha_FCD = (PL/TV)*1.137 = (200/1000)*1.137 = 0.2274
        # Plancher FC3 = 0.18 < 0.2274 < 0.55, donc on garde 0.2274 (source = fcd).
        fcd_pl = pd.Series([200.0])
        fcd_tv = pd.Series([1000.0])
        fc = pd.Series([3])
        is_crit = pd.Series([False])

        alpha_eff, source = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        expected = 0.2 * DEFAULT_RATIO_MACRO_PEN
        assert alpha_eff.iloc[0] == pytest.approx(expected, abs=1e-6)
        assert source.iloc[0] == "fcd"


# ---------------------------------------------------------------------------
# _detecter_zones_critiques
# ---------------------------------------------------------------------------


class TestDetecterZonesCritiques:
    """Tests pour _detecter_zones_critiques (override v3 ETAPE 0)."""

    def _make_capteurs(
        self,
        ratios: list[float],
        coords: list[tuple[float, float]],
        annee: int = 2025,
    ):
        """Construit un GeoDataFrame de capteurs SIREDO PL synthetiques."""
        import geopandas as gpd
        from shapely.geometry import Point

        rows = []
        for (lon, lat), ratio in zip(coords, ratios, strict=False):
            tv = 1000.0
            pl = ratio * tv
            rows.append(
                {
                    "annee": annee,
                    "TMJOBCTV": tv,
                    "TMJOBCPL": pl,
                    "geometry": Point(lon, lat),
                }
            )
        return gpd.GeoDataFrame(rows, crs="EPSG:4326")

    def _make_segments(self, coords_pairs: list[tuple[tuple[float, float], tuple[float, float]]]):
        """Construit un GeoDataFrame de segments (LineString) synthetiques."""
        import geopandas as gpd
        from shapely.geometry import LineString

        return gpd.GeoDataFrame(
            {"geometry": [LineString([a, b]) for a, b in coords_pairs]},
            crs="EPSG:4326",
        )

    def test_detecter_zones_critiques_capteurs_seuil(self):
        """Capteurs avec ratio > 15 % -> critiques ; sinon non.

        Deux capteurs :
          - capteur A : ratio 20 % (critique)
          - capteur B : ratio 8 % (non critique)
        Segments places a proximite du capteur A -> True ; au coin B -> False.
        """
        # Capteurs au memes coordonnees : (2.30, 45.75) = A, (2.50, 45.95) = B
        capteurs = self._make_capteurs(
            ratios=[0.20, 0.08],
            coords=[(2.30, 45.75), (2.50, 45.95)],
            annee=2025,
        )

        # Segments : seg0 a cote de A (critique), seg1 a cote de B (non critique),
        # seg2 loin des deux (non critique)
        segments = self._make_segments(
            [
                ((2.30, 45.75), (2.3001, 45.7501)),  # ~ capteur A
                ((2.50, 45.95), (2.5001, 45.9501)),  # ~ capteur B
                ((3.00, 46.50), (3.0001, 46.5001)),  # loin
            ]
        )

        mask = _detecter_zones_critiques(
            capteurs,
            segments,
            annee=2025,
            ratio_seuil=0.15,
            buffer_m=1000.0,
        )

        # Seul le segment 0 (proche du capteur critique A) doit etre True
        assert mask.iloc[0] == True  # noqa: E712
        assert mask.iloc[1] == False  # noqa: E712
        assert mask.iloc[2] == False  # noqa: E712

    def test_detecter_zones_critiques_buffer(self):
        """Buffer EPSG:2154 = 1000 m bien applique : segments dans/hors buffer."""
        # Un seul capteur critique a (2.30, 45.75)
        capteurs = self._make_capteurs(
            ratios=[0.25],
            coords=[(2.30, 45.75)],
            annee=2025,
        )

        # A 45.75 N : 0.01 degre lon ~ 778 m, 0.01 degre lat ~ 1112 m.
        # On place :
        #   - seg0 a ~50 m du capteur -> doit etre dans le buffer 1000 m
        #   - seg1 a ~5 km du capteur -> doit etre HORS du buffer
        segments = self._make_segments(
            [
                ((2.3005, 45.75), (2.3006, 45.7501)),  # ~50 m
                ((2.40, 45.80), (2.4001, 45.8001)),  # ~ 9 km
            ]
        )

        mask = _detecter_zones_critiques(
            capteurs,
            segments,
            annee=2025,
            ratio_seuil=0.15,
            buffer_m=1000.0,  # 1 km
        )

        assert mask.iloc[0] == True  # noqa: E712
        assert mask.iloc[1] == False  # noqa: E712

    def test_detecter_zones_critiques_no_capteur_annee(self):
        """Aucun capteur sur l'annee demandee -> all-False (fallback gracieux)."""
        capteurs = self._make_capteurs(
            ratios=[0.25],
            coords=[(2.30, 45.75)],
            annee=2024,
        )
        segments = self._make_segments(
            [
                ((2.30, 45.75), (2.3001, 45.7501)),
            ]
        )

        mask = _detecter_zones_critiques(
            capteurs,
            segments,
            annee=2025,  # autre annee
            ratio_seuil=0.15,
            buffer_m=1000.0,
        )
        # Aucun capteur 2025 -> tout False
        assert mask.iloc[0] == False  # noqa: E712


# ---------------------------------------------------------------------------
# Dispatch v1/v2/v3 selon les inputs disponibles
# ---------------------------------------------------------------------------


class TestSaturationDispatch:
    """Verifie que la saturation complete fait v1 / v2 / v3 selon les inputs.

    NOTE: la fonction de dispatch en elle-meme est inline dans
    routers/carte.py. Ici on teste les COMPOSANTS independamment, et on simule
    le dispatch pour valider les sorties attendues a chaque branche.
    """

    def test_saturation_v1_cap_fixe_par_fc(self):
        """v1 = cap fixe par FC (pas de FCD adaptatif).

        Sans TMJFCDPL/TMJFCDTV : alpha = ALPHA_FC_MIN[FC] (plancher = bornes v1).
        """
        # FC3 -> alpha 0.18, borne 3000.
        # PL_brut=2000, TV=1000 -> cap alpha = 0.18 * 1000 = 180 -> satured a 180.
        value_pred = pd.Series([2000.0])
        tv_pred = pd.Series([1000.0])
        fc = pd.Series([3])

        v_sat, mask = _saturer_hierarchique(
            value_pred,
            tv_pred,
            fc,
            DEFAULT_BORNES_FC_ABS,
            DEFAULT_ALPHA_FC_MIN,
        )
        # min(2000, 3000, 0.18*1000) = 180
        assert v_sat.iloc[0] == 180
        assert mask.iloc[0] == True  # noqa: E712

    def test_saturation_v2_hybride_avec_fcd(self):
        """v2 = avec FCD, plancher = max(alpha_FCD, plancher_FC), pas d'override.

        On simule v2 en passant is_critical=False et FCD presents.
        """
        # FC3, FCD nominal -> alpha_FCD = 0.2 * 1.137 = 0.2274
        fcd_pl = pd.Series([200.0])
        fcd_tv = pd.Series([1000.0])
        fc = pd.Series([3])
        is_crit = pd.Series([False])

        alpha_eff, source = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # 0.2274 > plancher FC3 (0.18) -> source = "fcd"
        assert source.iloc[0] == "fcd"
        assert alpha_eff.iloc[0] > DEFAULT_ALPHA_FC_MIN[3]

    def test_saturation_v3_hybride_avec_override_critique(self):
        """v3 = v2 + override zones critiques (plancher 0.30 quand critique)."""
        # FC5 hors zone critique -> plancher 0.12 ; dans zone critique -> 0.30
        fcd_pl = pd.Series([0.0, 0.0])
        fcd_tv = pd.Series([1000.0, 1000.0])
        fc = pd.Series([5, 5])
        is_crit = pd.Series([False, True])

        alpha_eff, _ = _alpha_v3(
            fcd_pl,
            fcd_tv,
            fc,
            is_crit,
            DEFAULT_ALPHA_FC_MIN,
            DEFAULT_RATIO_MACRO_PEN,
            DEFAULT_ALPHA_PHYSIQUE_MAX,
            DEFAULT_SEUIL_VOL_FCD_TV,
            DEFAULT_ALPHA_MIN_ZONE_CRITIQUE,
        )
        # seg0 hors zone : plancher 0.12 (FC5)
        # seg1 zone critique : plancher 0.30
        assert alpha_eff.iloc[0] == pytest.approx(DEFAULT_ALPHA_FC_MIN[5])
        assert alpha_eff.iloc[1] == pytest.approx(DEFAULT_ALPHA_MIN_ZONE_CRITIQUE)


# ---------------------------------------------------------------------------
# _saturer_hierarchique (cap dur FC + cap valeur <= alpha * TV)
# ---------------------------------------------------------------------------


class TestSaturerHierarchique:
    """La fonction generique partagee par PL/HPM/HPS."""

    def test_clip_negative_to_zero(self):
        """Valeurs negatives -> 0."""
        value_pred = pd.Series([-50.0, -10.0])
        tv_pred = pd.Series([1000.0, 1000.0])
        fc = pd.Series([3, 3])
        v_sat, _ = _saturer_hierarchique(
            value_pred,
            tv_pred,
            fc,
            DEFAULT_BORNES_FC_ABS,
            DEFAULT_ALPHA_FC_MIN,
        )
        assert (v_sat >= 0).all()
        assert v_sat.iloc[0] == 0
        assert v_sat.iloc[1] == 0

    def test_no_saturation_when_below_caps(self):
        """Pas de saturation si valeur < min(cap_FC, alpha*TV)."""
        # FC3 -> borne 3000, alpha 0.18 ; PL=100, TV=10000 -> cap alpha=1800
        # 100 < min(3000, 1800) -> pas de saturation, mask = False.
        value_pred = pd.Series([100.0])
        tv_pred = pd.Series([10000.0])
        fc = pd.Series([3])
        v_sat, mask = _saturer_hierarchique(
            value_pred,
            tv_pred,
            fc,
            DEFAULT_BORNES_FC_ABS,
            DEFAULT_ALPHA_FC_MIN,
        )
        assert v_sat.iloc[0] == 100
        assert mask.iloc[0] == False  # noqa: E712

    def test_borne_fc_dominates_when_strictest(self):
        """Cap FC l'emporte quand alpha*TV > borne_fc."""
        # FC4 -> borne 1500, alpha 0.15 ; TV = 100_000 -> cap alpha = 15000 (vs 1500)
        # PL_brut = 50000 -> sature a 1500 (cap FC).
        value_pred = pd.Series([50000.0])
        tv_pred = pd.Series([100000.0])
        fc = pd.Series([4])
        v_sat, mask = _saturer_hierarchique(
            value_pred,
            tv_pred,
            fc,
            DEFAULT_BORNES_FC_ABS,
            DEFAULT_ALPHA_FC_MIN,
        )
        assert v_sat.iloc[0] == DEFAULT_BORNES_FC_ABS[4]
        assert mask.iloc[0] == True  # noqa: E712


# ---------------------------------------------------------------------------
# Source de l'import (logged dans les rapports d'audit)
# ---------------------------------------------------------------------------


def test_import_source_visible():
    """Note l'origine des imports pour audit (pas un check fonctionnel)."""
    assert _IMPORT_SOURCE in ("services.ml.saturation", "routers.carte")
