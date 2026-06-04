"""Service ``evolution`` - carte d'evolution des debits (metrique JOr).

A partir de deux cartes de debits redressees (annee1=T1, annee2=T2, base=T2),
produit une carte d'evolution par troncon (% JOr), avec appariement 3 niveaux
(cle exacte, map-matching geometrique, verification BAN) et tracabilite complete.

Interface publique :

* :func:`matching.match_segments` -> table d'appariement par troncon base T2.
* :func:`compute.build_evolution_geojson` -> FeatureCollection d'evolution.
* :func:`io.load_carte_geojson` -> chargement / normalisation d'une carte.
* :func:`service.generate_evolution` -> orchestration (geojson, stats).
"""

from __future__ import annotations

from .compute import build_evolution_geojson, compute_stats
from .io import load_carte_geojson
from .matching import match_segments
from .service import EvolutionOptions, generate_evolution

__all__ = [
    "load_carte_geojson",
    "match_segments",
    "build_evolution_geojson",
    "compute_stats",
    "generate_evolution",
    "EvolutionOptions",
]
