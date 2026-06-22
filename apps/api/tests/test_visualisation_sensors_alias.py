"""Tests for the counting-loops alias bug fix in visualisation.py.

Regression: the frontend circle layers (apps/web/lib/map/setup.ts) filter on
the EXACT property keys "TMJA Tous Vehicules (veh/jour)" / "TMJA Poids Lourds
(veh/jour)". counting-loops files name the debit column differently
("Moyenne jours ouvrable (veh/jour)" for TV, "Moyenne Poids Lourds jours
ouvrable (veh/jour)" for PL), so the canonical keys were absent and no circle
was drawn. The fix detects the source column via aliases and emits the
canonical keys. These tests assert the canonical emission + n_tv/n_pl counts
through BOTH the dataframe path and the geojson path.
"""

from __future__ import annotations

import pandas as pd

from app.routers.visualisation import (
    CANONICAL_PL_KEY,
    CANONICAL_TV_KEY,
    _build_point_fc_from_geojson,
    _build_sensors_geojson,
    _detect_debit_columns,
)

SEED = 1750


# ---------------------------------------------------------------------------
# Alias detection unit tests
# ---------------------------------------------------------------------------


def test_detect_counting_loops_tv_column():
    cols = ["Identifiant ptm", "Moyenne jours ouvrable (veh/jour)", "Nom"]
    tv, pl = _detect_debit_columns(cols)
    assert tv == "Moyenne jours ouvrable (veh/jour)"
    assert pl is None


def test_detect_counting_loops_pl_column():
    cols = ["Identifiant ptm", "Moyenne Poids Lourds jours ouvrable (veh/jour)"]
    tv, pl = _detect_debit_columns(cols)
    assert tv is None
    assert pl == "Moyenne Poids Lourds jours ouvrable (veh/jour)"


def test_detect_canonical_columns():
    cols = ["TMJA Tous Vehicules (veh/jour)", "TMJA Poids Lourds (veh/jour)"]
    tv, pl = _detect_debit_columns(cols)
    assert tv == "TMJA Tous Vehicules (veh/jour)"
    assert pl == "TMJA Poids Lourds (veh/jour)"


def test_tv_alias_does_not_match_poids_lourds():
    # A "poids lourds" column must never be picked as the TV column.
    cols = ["Moyenne Poids Lourds jours ouvrable (veh/jour)"]
    tv, pl = _detect_debit_columns(cols)
    assert tv is None
    assert pl == "Moyenne Poids Lourds jours ouvrable (veh/jour)"


# ---------------------------------------------------------------------------
# DataFrame path (csv/xlsx) — _build_sensors_geojson
# ---------------------------------------------------------------------------


def test_dataframe_tv_emits_canonical_key():
    df = pd.DataFrame(
        {
            "lon": [4.85, 4.86, 4.87],
            "lat": [45.75, 45.76, 45.77],
            "Moyenne jours ouvrable (veh/jour)": ["17805", "0", None],
        }
    )
    fc, n, n_tv, n_pl, bbox = _build_sensors_geojson(df, "lon", "lat")
    assert n == 3
    # 17805 > 0 and 0 (not >0) and None (skipped) -> 1 counted.
    assert n_tv == 1
    assert n_pl == 0
    p0 = fc["features"][0]["properties"]
    assert p0[CANONICAL_TV_KEY] == 17805.0
    # Original column kept for the popup.
    assert p0["Moyenne jours ouvrable (veh/jour)"] == "17805"
    # Null debit -> canonical key not emitted (no spurious circle).
    assert CANONICAL_TV_KEY not in fc["features"][2]["properties"]


def test_dataframe_pl_only_file():
    df = pd.DataFrame(
        {
            "x": [4.85, 4.86],
            "y": [45.75, 45.76],
            "Moyenne Poids Lourds jours ouvrable (veh/jour)": [183, 12],
        }
    )
    fc, n, n_tv, n_pl, bbox = _build_sensors_geojson(df, "x", "y")
    assert n == 2
    assert n_tv == 0
    assert n_pl == 2
    for feat in fc["features"]:
        assert CANONICAL_PL_KEY in feat["properties"]
        assert CANONICAL_TV_KEY not in feat["properties"]


def test_dataframe_french_decimal_comma():
    df = pd.DataFrame(
        {
            "lon": [4.85],
            "lat": [45.75],
            "Moyenne jours ouvrable (veh/jour)": ["1234,5"],
        }
    )
    fc, n, n_tv, n_pl, _ = _build_sensors_geojson(df, "lon", "lat")
    assert n_tv == 1
    assert fc["features"][0]["properties"][CANONICAL_TV_KEY] == 1234.5


def test_dataframe_canonical_not_clobbered():
    # If the file already has the canonical key, keep its value.
    df = pd.DataFrame(
        {
            "lon": [4.85],
            "lat": [45.75],
            "TMJA Tous Vehicules (veh/jour)": [999],
        }
    )
    fc, n, n_tv, n_pl, _ = _build_sensors_geojson(df, "lon", "lat")
    assert n_tv == 1
    assert fc["features"][0]["properties"][CANONICAL_TV_KEY] == 999


# ---------------------------------------------------------------------------
# GeoJSON path — _build_point_fc_from_geojson
# ---------------------------------------------------------------------------


def _point(lon, lat, props):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": props,
    }


def test_geojson_tv_emits_canonical_key():
    parsed = {
        "type": "FeatureCollection",
        "features": [
            _point(
                4.85, 45.75, {"Identifiant ptm": "1", "Moyenne jours ouvrable (veh/jour)": 17805}
            ),
            _point(4.86, 45.76, {"Identifiant ptm": "2", "Moyenne jours ouvrable (veh/jour)": 0}),
        ],
    }
    fc, n, n_tv, n_pl, bbox = _build_point_fc_from_geojson(parsed)
    assert n == 2
    assert n_tv == 1  # only 17805 > 0
    assert n_pl == 0
    p0 = fc["features"][0]["properties"]
    assert p0[CANONICAL_TV_KEY] == 17805
    assert p0["Moyenne jours ouvrable (veh/jour)"] == 17805


def test_geojson_pl_only_emits_canonical_key():
    parsed = {
        "type": "FeatureCollection",
        "features": [
            _point(4.85, 45.75, {"Moyenne Poids Lourds jours ouvrable (veh/jour)": 183}),
            _point(4.86, 45.76, {"Moyenne Poids Lourds jours ouvrable (veh/jour)": 12}),
        ],
    }
    fc, n, n_tv, n_pl, bbox = _build_point_fc_from_geojson(parsed)
    assert n == 2
    assert n_tv == 0
    assert n_pl == 2
    for feat in fc["features"]:
        assert CANONICAL_PL_KEY in feat["properties"]
        assert CANONICAL_TV_KEY not in feat["properties"]
