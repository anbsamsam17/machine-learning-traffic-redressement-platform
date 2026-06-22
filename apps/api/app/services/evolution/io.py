"""Chargement / normalisation des cartes de debits (GeoJSON LineString).

Module d'entree du service ``evolution`` (carte d'evolution des debits). Lit une
carte de debits redressee (FeatureCollection LineString, ex ``2023.geojson`` /
``2024.geojson``) en ``geopandas.GeoDataFrame`` normalise :

* ``agregId`` force en ``str`` (suffixe de sens -F/-T conserve) ;
* ``FC`` force en ``str`` (le T1 fournit FC en number, le T2 en string : on
  normalise PARTOUT en string pour eviter toute comparaison topologique 3 vs '3') ;
* geometrie restreinte aux LineString valides (les autres geometries sont
  ecartees, pas de logique metier ailleurs qu'ici / dans compute) ;
* CRS WGS84 (EPSG:4326) par defaut si absent.

Aucune reprojection ici : le calcul geometrique (EPSG:2154) est fait a la demande
dans ``matching`` ; la geometrie WGS84 d'origine est conservee pour la sortie.
"""

from __future__ import annotations

import io as _io
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

CRS_WGS84 = "EPSG:4326"

# Proprietes potentiellement utiles, conservees si presentes (les autres sont
# ignorees : seule la metrique JOr entre dans l'evolution).
_KEEP_PROPS = [
    "agregId",
    "JO",
    "JOr",
    "DD",
    "FC",
    "HD",
    "TP",
    "JOrmin",
    "JOrmax",
]


def _coerce_str(value: Any) -> str | None:
    """Forcer une valeur en str non vide, ``None`` si manquante."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip()
    return s if s else None


def _load_featurecollection(path_or_bytes: str | Path | bytes | bytearray) -> dict:
    """Lire un GeoJSON FeatureCollection depuis un chemin ou des octets."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return json.loads(bytes(path_or_bytes).decode("utf-8"))
    p = Path(path_or_bytes)
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_carte_geojson(
    path_or_bytes: str | Path | bytes | bytearray,
) -> gpd.GeoDataFrame:
    """Charger une carte de debits en GeoDataFrame normalise.

    Parameters
    ----------
    path_or_bytes : str | pathlib.Path | bytes
        Chemin du GeoJSON ou contenu brut (octets) du FeatureCollection.

    Returns
    -------
    geopandas.GeoDataFrame
        Colonnes normalisees : ``agregId`` (str), ``FC`` (str), geometrie
        LineString valide, CRS EPSG:4326. Conserve ``JO, JOr, DD, HD, JOrmin,
        JOrmax, TP`` quand presents. Index reinitialise (0..n-1).

    Notes
    -----
    Les features sans geometrie LineString valide (Point, longueur ~0, geometrie
    nulle) sont ecartees : elles ne peuvent pas etre matchees geometriquement.
    """
    gj = _load_featurecollection(path_or_bytes)
    feats = gj.get("features", []) if isinstance(gj, dict) else []

    records: list[dict[str, Any]] = []
    geoms: list[BaseGeometry] = []
    for ft in feats:
        geom_raw = ft.get("geometry")
        if not geom_raw:
            continue
        try:
            geom = shape(geom_raw)
        except Exception:  # noqa: BLE001 - geometrie illisible -> ecartee
            continue
        if geom.is_empty or geom.geom_type != "LineString":
            continue
        if len(geom.coords) < 2:
            continue

        props = ft.get("properties") or {}
        rec: dict[str, Any] = {}
        for key in _KEEP_PROPS:
            rec[key] = props.get(key)
        rec["agregId"] = _coerce_str(rec.get("agregId"))
        rec["FC"] = _coerce_str(rec.get("FC"))
        records.append(rec)
        geoms.append(geom)

    gdf = gpd.GeoDataFrame(records, geometry=geoms, crs=CRS_WGS84)
    # Numerique propre pour les colonnes de debit / IC (jamais d'objet melange).
    for col in ("JO", "JOr", "HD", "TP", "JOrmin", "JOrmax"):
        if col in gdf.columns:
            gdf[col] = pd.to_numeric(gdf[col], errors="coerce")
    if "DD" in gdf.columns:
        gdf["DD"] = gdf["DD"].astype("object")
    return gdf.reset_index(drop=True)


def featurecollection_to_bytes(fc: dict) -> bytes:
    """Serialiser un FeatureCollection en octets UTF-8 (JSON strict, sans NaN)."""
    buf = _io.StringIO()
    json.dump(fc, buf, ensure_ascii=False, allow_nan=False)
    return buf.getvalue().encode("utf-8")
