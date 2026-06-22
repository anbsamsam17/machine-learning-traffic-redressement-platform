"""Helpers geometriques pour la generation de cartes (GeoJSON LineString).

Module extrait depuis ``app.routers.carte`` (refonte pre-execution). Factorise
les fonctions de parsing/heading/round que carte.py redefinissait localement
plusieurs fois.

Sommaire :

* ``_calculate_heading(geom)``     : heading (cap geographique) depuis une
                                      LineString GeoJSON, base sur l'orthodromie
                                      des extremites.
* ``_parse_geom_dict(g)``           : parse defensif (str JSON ou dict) -> dict.
* ``_parse_and_heading(g)``         : pipeline (parse + heading) — utilise dans
                                      generate_carte pour fallback HD.
* ``_parse_geom_shapely(g)``        : parse defensif -> shapely geometry (ou None).
* ``_round_coords(geom, decimals)`` : arrondi coordonnees LineString / Point.
"""

from __future__ import annotations

import json
import math
from typing import Any

# Precision coordonnees par defaut : 5 decimales (~= 1 m) suffit pour
# l'affichage cartographique trafic.
DEFAULT_COORD_DECIMALS = 5


def _calculate_heading(geom: dict | None) -> float:
    """Compute heading (cap geographique) from a GeoJSON LineString geometry.

    Convention : degres (-180, 180], 0 = Nord, mesure entre 1er et dernier point
    de la LineString. Retourne 0.0 si la geometrie est invalide / vide /
    monopoint (cf appelants downstream qui castent en int et appliquent mod 360).
    """
    if geom is None:
        return 0.0
    coords = geom.get("coordinates", [])
    if not coords or len(coords) < 2:
        return 0.0
    lat1, lon1 = math.radians(coords[0][1]), math.radians(coords[0][0])
    lat2, lon2 = math.radians(coords[-1][1]), math.radians(coords[-1][0])
    delta_long = lon2 - lon1
    X = math.cos(lat2) * math.sin(delta_long)
    Y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_long)
    return math.degrees(math.atan2(Y, X))


def _parse_geom_dict(g: Any) -> dict | None:
    """Parse defensif d'une geometrie GeoJSON (str JSON ou dict) -> dict.

    Retourne None si parsing impossible.
    """
    if g is None:
        return None
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except Exception:  # noqa: BLE001 — defensive parse only
            return None
    if isinstance(g, dict):
        return g
    return None


def _parse_and_heading(g: Any) -> float:
    """Parse + compute heading — pipeline factorise pour le fallback HD.

    Utilise dans ``generate_carte`` quand la colonne ``HD`` est absente / vide
    dans la source FCD : on calcule le heading depuis la geometrie.
    """
    geom = _parse_geom_dict(g)
    if geom is None:
        return 0.0
    return _calculate_heading(geom)


def _parse_geom_shapely(g: Any):
    """Parse defensif d'une geometrie GeoJSON -> shapely geometry (ou None).

    Utilise dans la detection des zones critiques v3 (besoin d'objets shapely
    pour reconstruire le GeoDataFrame des segments). Import shapely lazy
    (depend de la dispo de shapely runtime ; cf upload.py pattern).
    """
    geom = _parse_geom_dict(g)
    if geom is None:
        return None
    try:
        from shapely.geometry import shape as _shapely_shape

        return _shapely_shape(geom)
    except Exception:  # noqa: BLE001 — defensive parse only
        return None


def _round_coords(geom_in: Any, decimals: int = DEFAULT_COORD_DECIMALS):
    """Arrondit les coordonnees d'une geometrie GeoJSON.

    Supporte LineString / MultiLineString / Point. Retourne la geometrie
    telle quelle si type non geometrique ou inconnu (defensive).
    """
    if not isinstance(geom_in, dict):
        return geom_in
    gt = geom_in.get("type")
    coords = geom_in.get("coordinates")
    if coords is None:
        return geom_in
    if gt == "LineString":
        rc = [[round(x, decimals), round(y, decimals)] for x, y in coords]
    elif gt == "MultiLineString":
        rc = [[[round(x, decimals), round(y, decimals)] for x, y in ls] for ls in coords]
    elif gt == "Point":
        rc = [round(coords[0], decimals), round(coords[1], decimals)]
    else:
        rc = coords
    return {"type": gt, "coordinates": rc}


__all__ = [
    "DEFAULT_COORD_DECIMALS",
    "_calculate_heading",
    "_parse_geom_dict",
    "_parse_and_heading",
    "_parse_geom_shapely",
    "_round_coords",
]
