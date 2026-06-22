"""Orchestration du service de carte d'evolution des debits.

Enchaine : chargement (io) -> appariement (matching) -> construction GeoJSON +
stats (compute). Point d'entree unique consomme par le backend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd

from . import compute, io, matching


@dataclass
class EvolutionOptions:
    """Options de generation de la carte d'evolution.

    Attributes
    ----------
    use_ban : bool
        Activer la verification BAN (N3).
    plancher_t1 : float
        Plancher emergent (v/j).
    clamp_pct : float
        Borne d'affichage couleur (+/-clamp_pct).
    score_auto, score_min, margin, dtheta_reject : float
        Seuils calibres du map-matching.
    with_sig : bool
        Calculer la significativite (IC disjoints).
    progress : callable(pct, stage), optional
        Reporter d'avancement.
    ban_cache : dict, optional
        Cache BAN (reprise idempotente).
    """

    use_ban: bool = True
    plancher_t1: float = 50.0
    clamp_pct: float = 100.0
    score_auto: float = matching.THR_AUTO
    score_min: float = matching.THR_REVIEW
    margin: float = matching.MARGIN_MIN
    dtheta_reject: float = matching.GATE_HARD_REJECT_DEG
    with_sig: bool = True
    progress: Callable[[float, str], None] | None = None
    ban_cache: dict[int, dict] | None = field(default=None)


def _as_gdf(src: Any) -> gpd.GeoDataFrame:
    """Accepter un GeoDataFrame deja charge ou un chemin / octets a charger."""
    if isinstance(src, gpd.GeoDataFrame):
        return src
    if isinstance(src, (str, Path, bytes, bytearray)):
        return io.load_carte_geojson(src)
    raise TypeError(f"Type d'entree non supporte pour la carte: {type(src)!r}")


def generate_evolution(
    t1: Any,
    t2: Any,
    *,
    options: EvolutionOptions | None = None,
) -> tuple[dict, dict]:
    """Generer la carte d'evolution (geojson) et ses statistiques.

    Parameters
    ----------
    t1, t2 : geopandas.GeoDataFrame | str | pathlib.Path | bytes
        Carte annee 1 (T1) et carte annee 2 (T2 = base). Soit deja chargees,
        soit un chemin / contenu GeoJSON.
    options : EvolutionOptions, optional
        Parametres de generation (defauts metier valides).

    Returns
    -------
    (geojson, stats) : tuple[dict, dict]
        ``geojson`` : FeatureCollection d'evolution (sans NaN/inf).
        ``stats`` : n_total, n_cle, n_geom_auto, n_geom_verif, n_non_match,
        n_emergent, n_sig, jor_min/median/max.
    """
    opts = options or EvolutionOptions()
    progress = opts.progress or matching._noop_progress

    progress(0.0, "load")
    gdf_t1 = _as_gdf(t1)
    gdf_t2 = _as_gdf(t2)

    matches = matching.match_segments(
        gdf_t1,
        gdf_t2,
        use_ban=opts.use_ban,
        score_auto=opts.score_auto,
        score_min=opts.score_min,
        margin=opts.margin,
        dtheta_reject=opts.dtheta_reject,
        progress=progress,
        ban_cache=opts.ban_cache,
    )

    progress(0.95, "build")
    geojson = compute.build_evolution_geojson(
        gdf_t1,
        gdf_t2,
        matches,
        plancher_t1=opts.plancher_t1,
        clamp_pct=opts.clamp_pct,
        with_sig=opts.with_sig,
    )
    stats = compute.compute_stats(geojson)
    progress(1.0, "done")
    return geojson, stats
