"""Tests du service ``evolution`` (carte d'evolution des debits, metrique JOr).

Couvre, sur DataFrames synthetiques (seed 1750) et un petit echantillon reel :

* normalisation io (agregId/FC en str, LineString valides) ;
* appariement N1 cle exacte + N2 geometrique (STRtree + score + hongrois) ;
* formule JOr = round((T2-T1)/T1*100, 2) verifiee a 0.01 ;
* garde-fous (plancher emergent, T1<=0/null -> JOr null, jamais inf/NaN) ;
* significativite sig (IC disjoints) ;
* tracabilite (match_level / match_score / ban_concordance) ;
* JSON strict (aucun NaN/Infinity) + clamp d'affichage.

Aucun GPU, aucun reseau requis (BAN desactive sauf test integration ~quelques
points, marque ``network`` et saute par defaut).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from app.services.evolution import compute, io, matching, service

SEED = 1750

REAL_T1 = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\Travaux_Python"
    r"\Travaux_donnees_Lyon\Livrables\xOut\xOld\2023.geojson"
)
REAL_T2 = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\Travaux_Python"
    r"\Travaux_donnees_Lyon\Livrables\xOut\xOld\2024.geojson"
)


# --------------------------------------------------------------------------- #
# Helpers synthetiques
# --------------------------------------------------------------------------- #
def _line(x0: float, y0: float, x1: float, y1: float) -> LineString:
    return LineString([(x0, y0), (x1, y1)])


def _gdf(rows: list[dict]) -> gpd.GeoDataFrame:
    geoms = [r.pop("geometry") for r in rows]
    return gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")


def _make_pair() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Construire un petit couple T1 / T2 deterministe autour de Lyon."""
    # base offset Lyon ~ (4.83, 45.74). ~1e-4 deg ~ 8-11 m.
    base_lon, base_lat = 4.83, 45.74

    def seg(i, dl=0.0010):
        return _line(base_lon + i * 0.002, base_lat, base_lon + i * 0.002 + dl, base_lat)

    t1_rows = [
        # A : appariable par cle exacte (agregId 'A-F'), T1=4000
        {
            "agregId": "A-F",
            "JOr": 4000,
            "JO": 90,
            "FC": 3,
            "HD": 90,
            "JOrmin": 3800,
            "JOrmax": 4200,
            "geometry": seg(0),
        },
        # B : geometriquement matchable (agregId different), T1=8000
        {
            "agregId": "B1",
            "JOr": 8000,
            "JO": 120,
            "FC": 2,
            "HD": 90,
            "JOrmin": 7800,
            "JOrmax": 8200,
            "geometry": seg(1),
        },
        # C : emergent (T1 sous plancher), T1=30
        {
            "agregId": "C-T",
            "JOr": 30,
            "JO": 5,
            "FC": 4,
            "HD": 90,
            "JOrmin": 20,
            "JOrmax": 40,
            "geometry": seg(2),
        },
        # D : T1 nul -> non_redresse
        {
            "agregId": "D1",
            "JOr": 0,
            "JO": 0,
            "FC": 5,
            "HD": 90,
            "JOrmin": None,
            "JOrmax": None,
            "geometry": seg(3),
        },
        # E : IC disjoints pour sig=1 (T1=1000 [950,1050])
        {
            "agregId": "E-F",
            "JOr": 1000,
            "JO": 60,
            "FC": 3,
            "HD": 90,
            "JOrmin": 950,
            "JOrmax": 1050,
            "geometry": seg(4),
        },
    ]
    t2_rows = [
        # A : cle exacte, T2=4400 -> +10.0%
        {
            "agregId": "A-F",
            "JOr": 4400,
            "JO": 88,
            "FC": "3",
            "HD": 90,
            "JOrmin": 4200,
            "JOrmax": 4600,
            "geometry": seg(0),
        },
        # B : meme geometrie que B1 mais agregId different 'B2' -> geo match
        {
            "agregId": "B2",
            "JOr": 6800,
            "JO": 110,
            "FC": "2",
            "HD": 90,
            "JOrmin": 6600,
            "JOrmax": 7000,
            "geometry": seg(1),
        },
        # C : emergent, T2=300
        {
            "agregId": "C-T",
            "JOr": 300,
            "JO": 40,
            "FC": "4",
            "HD": 90,
            "JOrmin": 250,
            "JOrmax": 350,
            "geometry": seg(2),
        },
        # D : T1 nul -> non_redresse, T2=500
        {
            "agregId": "D1",
            "JOr": 500,
            "JO": 50,
            "FC": "5",
            "HD": 90,
            "JOrmin": 450,
            "JOrmax": 550,
            "geometry": seg(3),
        },
        # E : IC disjoints, T2=1500 [1450,1550] -> +50%
        {
            "agregId": "E-F",
            "JOr": 1500,
            "JO": 80,
            "FC": "3",
            "HD": 90,
            "JOrmin": 1450,
            "JOrmax": 1550,
            "geometry": seg(4),
        },
        # F : nouveau (aucun T1)
        {
            "agregId": "F-new",
            "JOr": 2000,
            "JO": 70,
            "FC": "3",
            "HD": 90,
            "JOrmin": 1900,
            "JOrmax": 2100,
            "geometry": seg(5),
        },
    ]
    return _gdf(t1_rows), _gdf(t2_rows)


@pytest.fixture(autouse=True)
def _seed():
    np.random.seed(SEED)


# --------------------------------------------------------------------------- #
# io
# --------------------------------------------------------------------------- #
def test_io_normalizes_types(tmp_path):
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[4.83, 45.74], [4.84, 45.75]]},
                "properties": {"agregId": 12345, "FC": 3, "JOr": 4000},
            },
            # geometrie Point -> ecartee
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [4.8, 45.7]},
                "properties": {"agregId": "x", "FC": "3"},
            },
        ],
    }
    p = tmp_path / "c.geojson"
    p.write_text(json.dumps(fc), encoding="utf-8")
    gdf = io.load_carte_geojson(p)
    assert len(gdf) == 1
    assert gdf.iloc[0]["agregId"] == "12345"
    assert isinstance(gdf.iloc[0]["FC"], str) and gdf.iloc[0]["FC"] == "3"
    # bytes input
    gdf2 = io.load_carte_geojson(json.dumps(fc).encode("utf-8"))
    assert len(gdf2) == 1


# --------------------------------------------------------------------------- #
# matching
# --------------------------------------------------------------------------- #
def test_match_cle_and_geom():
    t1, t2 = _make_pair()
    res = matching.match_segments(t1, t2, use_ban=False)
    assert list(res.columns) == matching.RESULT_COLS
    assert len(res) == len(t2)
    by_id = res.set_index("id_t2")

    # A : cle exacte
    assert by_id.loc["A-F", "match_level"] == "CLE"
    assert by_id.loc["A-F", "match_score"] is None
    assert by_id.loc["A-F", "id_t1"] == "A-F"

    # B2 : pas de cle, mais geometrie identique a B1 -> GEOM_*
    assert by_id.loc["B2", "match_level"] in ("GEOM_AUTO", "GEOM_VERIF")
    assert by_id.loc["B2", "id_t1"] == "B1"
    assert by_id.loc["B2", "match_score"] is not None

    # F-new : aucun homologue -> NON_MATCH
    assert by_id.loc["F-new", "match_level"] == "NON_MATCH"
    assert pd.isna(by_id.loc["F-new", "id_t1"])

    # tracabilite : 100% des features ont un match_level valide
    assert set(res["match_level"]).issubset({"CLE", "GEOM_AUTO", "GEOM_VERIF", "NON_MATCH"})
    # match_score float pour GEOM_*, None pour CLE/NON_MATCH (acces colonne
    # direct : iterrows() homogeneiserait la Series objet en float).
    levels = res["match_level"].tolist()
    scores = res["match_score"].tolist()
    for lvl, sc in zip(levels, scores, strict=False):
        if lvl in ("GEOM_AUTO", "GEOM_VERIF"):
            assert isinstance(sc, float)
        else:
            assert sc is None


def test_match_uniqueness():
    """Aucun troncon T1 affecte a plus d'un troncon base T2."""
    t1, t2 = _make_pair()
    res = matching.match_segments(t1, t2, use_ban=False)
    linked = [x for x in res["id_t1"].tolist() if x is not None]
    assert len(linked) == len(set(linked)), "doublon d'appariement T1"


def test_seuils_calibres():
    t1, t2 = _make_pair()
    res = matching.match_segments(t1, t2, use_ban=False)
    for lvl, sc in zip(res["match_level"].tolist(), res["match_score"].tolist(), strict=False):
        if lvl == "GEOM_AUTO":
            assert sc >= matching.THR_AUTO - 1e-9
        if lvl in ("GEOM_AUTO", "GEOM_VERIF"):
            assert sc >= matching.THR_REVIEW - 1e-9


# --------------------------------------------------------------------------- #
# compute
# --------------------------------------------------------------------------- #
def test_build_geojson_formula_and_guards():
    t1, t2 = _make_pair()
    res = matching.match_segments(t1, t2, use_ban=False)
    gj = compute.build_evolution_geojson(t1, t2, res, plancher_t1=50.0)

    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == len(t2)
    props = {ft["properties"]["agregId"]: ft["properties"] for ft in gj["features"]}

    required = {
        "agregId",
        "FC",
        "HD",
        "DD",
        "T2",
        "T1",
        "JO_T2",
        "JO_T1",
        "JOr",
        "dJOr",
        "sig",
        "categorie",
        "match_level",
        "match_score",
        "ban_concordance",
        "FC_change",
    }
    for p in props.values():
        assert required.issubset(p.keys())
        assert isinstance(p["FC"], (str, type(None)))

    # A : +10.0% exact, evolutif
    a = props["A-F"]
    assert a["categorie"] == "evolutif"
    assert abs(a["JOr"] - round((4400 - 4000) / 4000 * 100, 2)) <= 0.01
    assert a["JOr"] == 10.0
    assert a["dJOr"] == 400.0

    # B2 : -15.0% via geo match (T1=8000 -> T2=6800)
    b = props["B2"]
    assert abs(b["JOr"] - round((6800 - 8000) / 8000 * 100, 2)) <= 0.01
    assert b["JOr"] == -15.0

    # C : emergent (T1=30 < 50) -> JOr null, dJOr conserve
    c = props["C-T"]
    assert c["categorie"] == "emergent"
    assert c["JOr"] is None
    assert c["dJOr"] == round(300 - 30, 2)

    # D : T1=0 -> non_redresse, JOr null, dJOr=T2-T1
    d = props["D1"]
    assert d["JOr"] is None
    assert d["categorie"] == "non_redresse"
    assert d["dJOr"] == 500.0

    # E : +50% et IC disjoints -> sig=1
    e = props["E-F"]
    assert e["JOr"] == 50.0
    assert e["sig"] == 1

    # F : nouveau
    f = props["F-new"]
    assert f["categorie"] == "nouveau"
    assert f["JOr"] is None
    assert f["T1"] is None


def test_no_nan_infinity_strict_json():
    t1, t2 = _make_pair()
    res = matching.match_segments(t1, t2, use_ban=False)
    gj = compute.build_evolution_geojson(t1, t2, res)
    # parse_constant leve si NaN/Infinity present
    s = json.dumps(gj, allow_nan=False)

    def _reject(_):
        raise ValueError("NaN/Infinity present")

    json.loads(s, parse_constant=_reject)
    for ft in gj["features"]:
        for v in ft["properties"].values():
            if isinstance(v, float):
                assert math.isfinite(v)


def test_clamp_display_preserves_raw():
    # T1=50 (>= plancher), T2=15000 -> +29900% : brut conserve, display clampe.
    t1 = _gdf(
        [
            {
                "agregId": "X1",
                "JOr": 50,
                "JO": 5,
                "FC": 3,
                "HD": 0,
                "JOrmin": 40,
                "JOrmax": 60,
                "geometry": _line(4.83, 45.74, 4.831, 45.74),
            }
        ]
    )
    t2 = _gdf(
        [
            {
                "agregId": "X1",
                "JOr": 15000,
                "JO": 200,
                "FC": "3",
                "HD": 0,
                "JOrmin": 14000,
                "JOrmax": 16000,
                "geometry": _line(4.83, 45.74, 4.831, 45.74),
            }
        ]
    )
    res = matching.match_segments(t1, t2, use_ban=False)
    gj = compute.build_evolution_geojson(t1, t2, res, plancher_t1=50.0, clamp_pct=100.0)
    p = gj["features"][0]["properties"]
    assert p["JOr"] == round((15000 - 50) / 50 * 100, 2)  # 29900.0 brut
    assert p["JOr"] > 100
    assert p["JOr_display"] == 100.0


def test_sig_default_when_ic_missing():
    # IC manquant cote T1 -> sig=0 (prudence)
    t1 = _gdf(
        [
            {
                "agregId": "Z1",
                "JOr": 1000,
                "JO": 50,
                "FC": 3,
                "HD": 0,
                "JOrmin": None,
                "JOrmax": None,
                "geometry": _line(4.83, 45.74, 4.831, 45.74),
            }
        ]
    )
    t2 = _gdf(
        [
            {
                "agregId": "Z1",
                "JOr": 2000,
                "JO": 60,
                "FC": "3",
                "HD": 0,
                "JOrmin": 1900,
                "JOrmax": 2100,
                "geometry": _line(4.83, 45.74, 4.831, 45.74),
            }
        ]
    )
    res = matching.match_segments(t1, t2, use_ban=False)
    gj = compute.build_evolution_geojson(t1, t2, res)
    assert gj["features"][0]["properties"]["sig"] == 0


# --------------------------------------------------------------------------- #
# service orchestration + stats
# --------------------------------------------------------------------------- #
def test_generate_evolution_stats():
    t1, t2 = _make_pair()
    gj, stats = service.generate_evolution(t1, t2, options=service.EvolutionOptions(use_ban=False))
    assert stats["n_total"] == len(t2)
    assert stats["n_cle"] >= 1
    assert stats["n_emergent"] >= 1
    assert stats["n_sig"] >= 1
    assert stats["jor_min"] is not None and stats["jor_max"] is not None


# Contrat de stats consomme par le front (/status) : tout ajout/retrait de clef
# casserait le mapping. Les clefs de comptage attendues sont figees ici.
EXPECTED_STATS_KEYS = {
    "n_total",
    "n_cle",
    "n_geom_auto",
    "n_geom_verif",
    "n_non_match",
    "n_emergent",
    "n_sig",
    "n_ban_indisponible",
    "jor_min",
    "jor_median",
    "jor_max",
}


def test_stats_contract_keys():
    """Le dict de stats expose EXACTEMENT les clefs du contrat front/back."""
    t1, t2 = _make_pair()
    gj, stats = service.generate_evolution(t1, t2, options=service.EvolutionOptions(use_ban=False))
    assert set(stats.keys()) == EXPECTED_STATS_KEYS
    # compute_stats seul doit produire le meme jeu de clefs.
    assert set(compute.compute_stats(gj).keys()) == EXPECTED_STATS_KEYS


def test_match_segments_does_not_mutate_module_globals():
    """match_segments ne doit JAMAIS muter les constantes de module (thread-safe).

    Garantit qu'une generation avec des seuils non-defaut laisse les globals
    intacts pour les generations concurrentes (asyncio.to_thread).
    """
    before = (
        matching.THR_AUTO,
        matching.THR_REVIEW,
        matching.MARGIN_MIN,
        matching.GATE_HARD_REJECT_DEG,
        matching.DIR_PENALTY_SCALE_DEG,
    )
    t1, t2 = _make_pair()
    # Seuils volontairement differents des defauts pour exposer toute mutation.
    matching.match_segments(
        t1,
        t2,
        use_ban=False,
        score_auto=0.80,
        score_min=0.40,
        margin=0.20,
        dtheta_reject=90.0,
    )
    after = (
        matching.THR_AUTO,
        matching.THR_REVIEW,
        matching.MARGIN_MIN,
        matching.GATE_HARD_REJECT_DEG,
        matching.DIR_PENALTY_SCALE_DEG,
    )
    assert before == after


def test_ban_noop_without_street_name_column():
    """Sans colonne de nom de voie, BAN est court-circuite (no-op reseau).

    Aucun appel reseau ne doit etre tente : on remplace _ban_call par un sentinel
    qui leverait s'il etait appele. Toutes les concordances GEOM_* valent
    INDISPONIBLE et le compteur n_ban_indisponible reflete ce comptage.
    """

    def _boom(*a, **k):  # pragma: no cover - ne doit jamais etre appele
        raise AssertionError("validate_ban a tente un appel reseau BAN")

    t1, t2 = _make_pair()  # ni T1 ni T2 n'ont de colonne de nom de voie
    assert matching.detect_street_name_col(t2, t1) is None

    orig = matching._ban_call
    matching._ban_call = _boom
    try:
        res = matching.match_segments(t1, t2, use_ban=True)
    finally:
        matching._ban_call = orig

    geom_mask = res["match_level"].isin(["GEOM_AUTO", "GEOM_VERIF"])
    geom_conc = res.loc[geom_mask, "ban_concordance"].tolist()
    assert geom_conc, "le couple synthetique doit produire au moins un GEOM_*"
    assert all(c == "INDISPONIBLE" for c in geom_conc)

    gj = compute.build_evolution_geojson(t1, t2, res, plancher_t1=50.0)
    stats = compute.compute_stats(gj)
    assert stats["n_ban_indisponible"] == len(geom_conc)


def test_ban_detects_street_name_column():
    """Avec une colonne de nom (ex. ST_NAME), la detection la retourne."""
    t1, t2 = _make_pair()
    t1 = t1.assign(nom=["Rue A"] * len(t1))
    t2 = t2.assign(nom=["Rue A"] * len(t2))
    assert matching.detect_street_name_col(t2, t1) == "nom"


# --------------------------------------------------------------------------- #
# helpers unitaires
# --------------------------------------------------------------------------- #
def test_jaccard_and_road_code():
    assert matching.is_road_code("D7") is True
    assert matching.is_road_code("RD383") is True
    assert matching.is_road_code("Rue de la Paix") is False
    a = matching.normalize_name("Avenue Jean Jaures")
    b = matching.normalize_name("avenue jean jaures")
    assert matching.jaccard(a, b) == 1.0


def test_circular_diff():
    d = matching.circular_diff_deg(np.array([10.0, 350.0]), np.array([350.0, 10.0]))
    assert np.allclose(d, [20.0, 20.0])


# --------------------------------------------------------------------------- #
# Echantillon reel (saute si fichiers absents)
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    not (REAL_T1.exists() and REAL_T2.exists()),
    reason="fichiers reels indisponibles",
)
def test_real_sample():
    rng = np.random.default_rng(SEED)
    g1 = io.load_carte_geojson(REAL_T1)
    g2 = io.load_carte_geojson(REAL_T2)
    # sous-echantillon base T2 + T1 par cle correspondante pour garantir des CLE.
    n = min(800, len(g2))
    idx2 = rng.choice(len(g2), size=n, replace=False)
    sub2 = g2.iloc[idx2].reset_index(drop=True)
    keys = set(sub2["agregId"].dropna().tolist())
    sub1 = g1[g1["agregId"].isin(keys)].reset_index(drop=True)

    res = matching.match_segments(sub1, sub2, use_ban=False)
    assert len(res) == len(sub2)
    assert (res["match_level"] == "CLE").sum() > 0

    gj = compute.build_evolution_geojson(sub1, sub2, res, plancher_t1=50.0)
    json.dumps(gj, allow_nan=False)  # JSON strict

    # Formule JOr verifiee sur les evolutifs.
    for ft in gj["features"]:
        p = ft["properties"]
        if p["categorie"] in ("evolutif", "topologie_modifiee") and p["JOr"] is not None:
            t1v, t2v = p["T1"], p["T2"]
            assert abs(p["JOr"] - round((t2v - t1v) / t1v * 100, 2)) <= 0.01


def test_ban_integration_small(monkeypatch):
    """Integration BAN sur ~quelques points (saute si RUN_NETWORK!=1)."""
    if os.environ.get("RUN_NETWORK") != "1":
        pytest.skip("reseau desactive (RUN_NETWORK!=1)")
    t1, t2 = _make_pair()
    # Ajoute ST_NAME cote base pour exercer la concordance.
    t2 = t2.assign(ST_NAME=["Rue de la Republique"] * len(t2))
    res = matching.match_segments(t1, t2, use_ban=True)
    assert set(res["ban_concordance"].dropna().unique()).issubset(
        {"MATCH", "MISMATCH", "INDISPONIBLE"}
    )
