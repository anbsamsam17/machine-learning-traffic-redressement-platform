"""Generate preview GeoJSON samples for /visualisation and /discontinuites.

One-shot utility (NOT a runtime endpoint) intended to be run by the SIG agent
to populate ``apps/web/public/preview/`` with two lightweight FeatureCollections
served as static assets by Next.js (no auth, cache-friendly).

Outputs (WGS84 EPSG:4326, [lon, lat]):
    apps/web/public/preview/visualisation-lyon.geojson   (~500 LineStrings)
    apps/web/public/preview/discontinuites-lyon.geojson  (~200 Points)

Source for visualisation: real Lyon network (2025_light.geojson, ~98k features),
filtered by Grand Lyon bbox and stratified-sampled by FC bucket.

Source for discontinuites: synthetic nodes anchored on visualisation segment
endpoints (so hot-spots correlate with the real network), with cause/topology/
tier distributions matching observed Lyon batch outputs.

Usage:
    python apps/api/scripts/prepare_preview_data.py
    python apps/api/scripts/prepare_preview_data.py --segments <path> --seed 42
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

logger = logging.getLogger("prepare_preview_data")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_BBOX: tuple[float, float, float, float] = (4.78, 45.72, 4.90, 45.80)
DEFAULT_MAX_SEGMENTS = 500
DEFAULT_MAX_NODES = 200
DEFAULT_SEED = 1750

# Default source : Lyon canonical light GeoJSON.
DEFAULT_SEGMENTS = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/Travaux_Python/"
    r"Travaux_donnees_Lyon/Livrables/2025_light.geojson"
)

# FC stratification weights for visualisation sample.
# Note: FC=1 is usually absent on Grand Lyon urban network — weights are
# auto-redistributed across present buckets in build_visualisation().
FC_WEIGHTS: dict[int, float] = {1: 0.05, 2: 0.20, 3: 0.25, 4: 0.25, 5: 0.25}

# TVr stratification (per FC bucket) — pick segments across the full TVr
# spectrum so the step-color palette uses ALL 7 paliers (visual diversity).
# Each tuple is (quantile_lo, quantile_hi, share_within_bucket).
# Distribution rationale:
#   - 30% high-TVr (q75+)  -> dark reds, hot corridors visible
#   - 35% mid-TVr (q40-q75) -> orange/red transitions
#   - 25% low-mid (q15-q40) -> orange (visual contrast)
#   - 10% low-TVr (q00-q15) -> yellow/sand (rest of palette)
TVR_STRATA: list[tuple[float, float, float]] = [
    (0.75, 1.00, 0.30),
    (0.40, 0.75, 0.35),
    (0.15, 0.40, 0.25),
    (0.00, 0.15, 0.10),
]

# Discontinuity property distributions (target Lyon-observed mix).
CAUSE_DIST: list[tuple[str, float]] = [
    ("FCD_TV_cliff", 0.540),
    ("FCD_PL_cliff", 0.240),
    ("Distance_anomaly", 0.085),
    ("Coverage_gap", 0.060),
    ("FC_transition", 0.030),
    ("RAMP_asymmetry", 0.020),
    ("ROUNDABOUT_asymmetry", 0.015),
    ("Unexplained", 0.010),
]
TOPOLOGY_DIST: list[tuple[str, float]] = [
    ("Carrefour", 0.72),
    ("Continuite", 0.20),
    ("Bretelle", 0.08),
]
TIER_DIST: list[tuple[str, float]] = [("orange", 0.67), ("red", 0.33)]

# Hard cap on TVr (per spec: stay in normal gamme 500-20000 v/j).
TVR_CAP = 20000.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _weighted_pick(items_weights: list[tuple[str, float]], rng: random.Random) -> str:
    items, weights = zip(*items_weights)
    return rng.choices(items, weights=weights, k=1)[0]


def _round_coords(coords, ndigits: int = 5):
    return [[round(c[0], ndigits), round(c[1], ndigits)] for c in coords]


def _cap_tvr(tvr) -> float:
    try:
        v = float(tvr)
    except (TypeError, ValueError):
        return 0.0
    if v < 0 or v != v:  # NaN check
        return 0.0
    return min(v, TVR_CAP)


# ---------------------------------------------------------------------------
# Step 1 : visualisation-lyon.geojson
# ---------------------------------------------------------------------------
def build_visualisation(
    src: Path,
    bbox: tuple[float, float, float, float],
    max_count: int,
    seed: int,
) -> tuple[gpd.GeoDataFrame, dict]:
    logger.info("[VIS] Reading source: %s", src.name)
    gdf = gpd.read_file(src, bbox=bbox, engine="pyogrio")
    logger.info("[VIS] Loaded %d features in bbox", len(gdf))

    # Ensure WGS84
    if gdf.crs is None:
        gdf.set_crs(epsg=4326, inplace=True)
    elif gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Keep only LineString
    gdf = gdf[gdf.geometry.geom_type == "LineString"].copy()

    # Drop directional duplicates -F/-T (keep one direction per base id)
    def _base(a):
        s = str(a)
        return s[:-2] if (s.endswith("-F") or s.endswith("-T")) else s

    gdf["_base"] = gdf["agregId"].apply(_base)
    gdf = gdf.drop_duplicates(subset="_base", keep="first").copy()
    logger.info("[VIS] After dedup directional pairs: %d", len(gdf))

    # Coerce FC
    gdf["FC"] = pd.to_numeric(gdf["FC"], errors="coerce").fillna(5).astype(int)
    gdf = gdf[gdf["FC"].between(1, 5)].copy()

    # Filter strictly inside bbox using representative_point (centroid on a
    # geographic CRS is mathematically ill-defined; representative_point is
    # cheap and lies inside the geometry, sufficient here).
    lo_min, la_min, lo_max, la_max = bbox
    rep = gdf.geometry.representative_point()
    inside = (
        (rep.x >= lo_min) & (rep.x <= lo_max)
        & (rep.y >= la_min) & (rep.y <= la_max)
    )
    n_before = len(gdf)
    gdf = gdf[inside].copy()
    logger.info("[VIS] Inside-bbox filter: %d -> %d", n_before, len(gdf))

    # Redistribute FC weights across buckets actually present in the source.
    rng_np = np.random.default_rng(seed)
    present_fc = sorted(int(fc) for fc in gdf["FC"].unique())
    if not present_fc:
        raise RuntimeError("No FC bucket present in source after filtering")
    fc_weights_eff: dict[int, float] = {fc: FC_WEIGHTS.get(fc, 0.0) for fc in present_fc}
    total_w = sum(fc_weights_eff.values())
    if total_w <= 0:
        # Degenerate fallback: uniform across present buckets.
        fc_weights_eff = {fc: 1.0 / len(present_fc) for fc in present_fc}
    else:
        fc_weights_eff = {fc: w / total_w for fc, w in fc_weights_eff.items()}
    logger.info("[VIS] FC weights (effective): %s", {
        fc: round(w, 3) for fc, w in fc_weights_eff.items()
    })

    # Stratified sample by FC bucket, then by TVr-quantile strata WITHIN each
    # bucket so the resulting TVr distribution covers all palette paliers.
    picks: list[gpd.GeoDataFrame] = []
    for fc, w in fc_weights_eff.items():
        bucket = gdf[gdf["FC"] == fc]
        if len(bucket) == 0:
            continue
        n_target = int(round(max_count * w))
        if n_target <= 0:
            continue
        # Build TVr quantile thresholds for the bucket.
        tvr_arr = bucket["TVr"].fillna(0).astype(float).to_numpy()
        if len(tvr_arr) <= 1 or float(np.ptp(tvr_arr)) < 1e-6:
            # Degenerate bucket: random sample.
            n = min(n_target, len(bucket))
            sampled = bucket.sample(
                n=n, random_state=int(rng_np.integers(0, 1_000_000))
            )
            picks.append(sampled)
            continue

        # Sort once for quantile slicing.
        bucket_sorted = bucket.sort_values("TVr", ascending=True).reset_index(drop=True)
        n_in_bucket = len(bucket_sorted)
        bucket_picks: list[pd.DataFrame] = []
        for q_lo, q_hi, share in TVR_STRATA:
            i_lo = int(round(q_lo * (n_in_bucket - 1)))
            i_hi = int(round(q_hi * (n_in_bucket - 1)))
            if i_hi <= i_lo:
                i_hi = min(i_lo + 1, n_in_bucket)
            slab = bucket_sorted.iloc[i_lo:i_hi]
            if len(slab) == 0:
                continue
            n_strata = max(1, int(round(n_target * share)))
            n_strata = min(n_strata, len(slab))
            sampled = slab.sample(
                n=n_strata, random_state=int(rng_np.integers(0, 1_000_000))
            )
            bucket_picks.append(sampled)
        if bucket_picks:
            picks.append(
                gpd.GeoDataFrame(pd.concat(bucket_picks, ignore_index=True), crs=bucket.crs)
            )

    sample = gpd.GeoDataFrame(pd.concat(picks, ignore_index=True), crs="EPSG:4326")
    logger.info("[VIS] Stratified sample size: %d", len(sample))

    # Build target schema per feature
    features: list[dict] = []
    for _, row in sample.iterrows():
        tvr = _cap_tvr(row.get("TVr"))
        # DPL : clamp >= 0 (some rows have negative residuals from redressement)
        try:
            dpl = float(row.get("DPL") or 0)
            if dpl != dpl:  # NaN
                dpl = 0.0
        except (TypeError, ValueError):
            dpl = 0.0
        dpl = max(0.0, dpl)

        # Use original IC bounds when meaningful, else +/-15% synthetic
        tvr_min_raw = row.get("TVrmin")
        tvr_max_raw = row.get("TVrmax")
        try:
            tvr_min = float(tvr_min_raw) if tvr_min_raw is not None else 0.0
            tvr_max = float(tvr_max_raw) if tvr_max_raw is not None else 0.0
        except (TypeError, ValueError):
            tvr_min, tvr_max = 0.0, 0.0
        if tvr_min <= 0 or tvr_max <= 0 or tvr_min >= tvr_max:
            tvr_min = round(tvr * 0.85, 1)
            tvr_max = round(tvr * 1.15, 1)
        else:
            tvr_min = min(tvr_min, tvr)
            tvr_max = min(max(tvr_max, tvr), TVR_CAP)

        dpl_min_raw = row.get("DPLmin")
        dpl_max_raw = row.get("DPLmax")
        try:
            dpl_min = float(dpl_min_raw) if dpl_min_raw is not None else 0.0
            dpl_max = float(dpl_max_raw) if dpl_max_raw is not None else 0.0
        except (TypeError, ValueError):
            dpl_min, dpl_max = 0.0, 0.0
        if dpl_min < 0 or dpl_max < 0 or dpl_min >= dpl_max:
            dpl_min = round(max(0.0, dpl * 0.85), 1)
            dpl_max = round(max(0.0, dpl * 1.15), 1)
        else:
            dpl_min = max(0.0, min(dpl_min, dpl))
            dpl_max = max(dpl_max, dpl)

        props = {
            "agregId": str(row["agregId"]),
            "TVr": round(tvr, 1),
            "DPL": round(dpl, 1),
            "fc": int(row["FC"]),
            "TVr_min": round(tvr_min, 1),
            "TVr_max": round(tvr_max, 1),
            "DPL_min": round(dpl_min, 1),
            "DPL_max": round(dpl_max, 1),
        }
        coords = _round_coords(list(row.geometry.coords), 5)
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "LineString", "coordinates": coords},
        })

    fc_dict = {"type": "FeatureCollection", "features": features}
    return sample, fc_dict


# ---------------------------------------------------------------------------
# Step 2 : discontinuites-lyon.geojson
# ---------------------------------------------------------------------------
def build_discontinuites(
    vis_sample: gpd.GeoDataFrame,
    max_count: int,
    seed: int,
    bbox: tuple[float, float, float, float] = DEFAULT_BBOX,
) -> dict:
    logger.info("[DIS] Building up to %d synthetic discontinuity nodes", max_count)

    # Anchor candidates : both endpoints of every sampled visualisation segment,
    # weighted by capped TVr so hot-spots cluster near busy corridors.
    candidates_coords: list[tuple[float, float]] = []
    candidates_weights: list[float] = []
    for _, row in vis_sample.iterrows():
        tvr = _cap_tvr(row.get("TVr"))
        weight = max(tvr, 50.0)
        coords = list(row.geometry.coords)
        if not coords:
            continue
        candidates_coords.append((coords[0][0], coords[0][1]))
        candidates_weights.append(weight)
        candidates_coords.append((coords[-1][0], coords[-1][1]))
        candidates_weights.append(weight)

    if not candidates_coords:
        raise RuntimeError("No candidate node positions; visualisation sample empty")

    coords_arr = np.array(candidates_coords)
    w = np.array(candidates_weights, dtype=float)
    w /= w.sum()

    rng_np = np.random.default_rng(seed + 1)
    py_rng = random.Random(seed + 2)

    # Sample with replacement, then dedup by 4-decimal snap (~11 m)
    idx = rng_np.choice(len(candidates_coords), size=max_count * 3, replace=True, p=w)
    selected: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for i in idx:
        lon, lat = coords_arr[i]
        key = (round(float(lon), 4), round(float(lat), 4))
        if key in seen:
            continue
        seen.add(key)
        selected.append((float(lon), float(lat)))
        if len(selected) >= max_count:
            break
    logger.info("[DIS] Selected %d unique node positions", len(selected))

    features: list[dict] = []
    lo_min, la_min, lo_max, la_max = bbox
    for i, (lon, lat) in enumerate(selected):
        # tiny jitter so overlapping endpoints from F/T pairs don't pile up
        jlon = lon + (rng_np.random() - 0.5) * 0.0002
        jlat = lat + (rng_np.random() - 0.5) * 0.0002
        # clamp inside bbox (jitter may push 1-2 features 100 m outside)
        jlon = min(max(jlon, lo_min), lo_max)
        jlat = min(max(jlat, la_min), la_max)

        cause = _weighted_pick(CAUSE_DIST, py_rng)
        topology = _weighted_pick(TOPOLOGY_DIST, py_rng)
        tier = _weighted_pick(TIER_DIST, py_rng)

        # Convention alignee sur le backend reel (apps/api/app/services/
        # discontinuites.py) :
        #   ecart = |flow_in - flow_out|   (v/j, absolu, bidirectionnel)
        #   tier=red    si ecart >= 2 * threshold (typiquement >= 4000 v/j)
        #   tier=orange si threshold < ecart < 2*threshold (typ. 2000-4000 v/j)
        #   threshold = 2000 si max_flow <= 20000, sinon 4000.
        # On reste dans le regime "low" (max_flow <= 20000) pour le preview.
        #
        # Pour les causes a connotation "falaise" (FCD_TV_cliff, FCD_PL_cliff,
        # Coverage_gap), on biaise legerement vers flow_in > flow_out (baisse
        # de flux) — mais les deux sens restent legitimes : un carrefour reel
        # peut tres bien avoir flux_sortant > flux_entrant (fusion d'axes).
        FLOW_CAP = 20000.0
        FLOOR = 500.0
        if tier == "red":
            ecart_vj = float(rng_np.uniform(4000.0, 9000.0))
        else:
            ecart_vj = float(rng_np.uniform(2100.0, 3900.0))

        # Choisir le sens : biais "baisse" pour les causes cliff/coverage.
        cliff_like = cause in ("FCD_TV_cliff", "FCD_PL_cliff", "Coverage_gap")
        p_drop = 0.80 if cliff_like else 0.55
        drop = rng_np.random() < p_drop

        # Borne haute pour le membre dominant : on garde max(flow) bien en
        # dessous du pivot 20000 v/j pour ne pas basculer dans le regime
        # high-threshold (qui doublerait les seuils tier).
        hi = float(rng_np.uniform(ecart_vj + FLOOR, FLOW_CAP))
        lo = hi - ecart_vj
        if lo < FLOOR:
            lo = FLOOR
            hi = lo + ecart_vj
        if drop:
            flow_in, flow_out = hi, lo
        else:
            flow_in, flow_out = lo, hi

        features.append({
            "type": "Feature",
            "properties": {
                "node_id": f"node_{i+1:04d}",
                "principal_cause": cause,
                "topology": topology,
                "tier": tier,
                "ecart": round(abs(flow_in - flow_out), 1),
                "flow_in": round(flow_in, 1),
                "flow_out": round(flow_out, 1),
            },
            "geometry": {
                "type": "Point",
                "coordinates": [round(jlon, 5), round(jlat, 5)],
            },
        })

    return {"type": "FeatureCollection", "features": features}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--segments", type=Path, default=DEFAULT_SEGMENTS,
        help="Source segments GeoJSON (LineStrings).",
    )
    parser.add_argument(
        "--bbox", type=float, nargs=4,
        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
        default=DEFAULT_BBOX,
    )
    parser.add_argument("--max-segments", type=int, default=DEFAULT_MAX_SEGMENTS)
    parser.add_argument("--max-nodes", type=int, default=DEFAULT_MAX_NODES)
    parser.add_argument(
        "--out-dir", type=Path,
        default=_repo_root() / "apps" / "web" / "public" / "preview",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    if not args.segments.exists():
        logger.error("Segments file not found: %s", args.segments)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    bbox = tuple(args.bbox)  # type: ignore[assignment]

    # ---- visualisation ----
    vis_sample, vis_fc = build_visualisation(
        args.segments, bbox, args.max_segments, args.seed,
    )
    out_vis = args.out_dir / "visualisation-lyon.geojson"
    out_vis.write_text(json.dumps(vis_fc, ensure_ascii=False), encoding="utf-8")
    size_kb_vis = out_vis.stat().st_size / 1024
    logger.info(
        "[OK] %s: %d features, %.1f KB",
        out_vis.name, len(vis_fc["features"]), size_kb_vis,
    )

    # ---- discontinuites ----
    dis_fc = build_discontinuites(vis_sample, args.max_nodes, args.seed, bbox)
    out_dis = args.out_dir / "discontinuites-lyon.geojson"
    out_dis.write_text(json.dumps(dis_fc, ensure_ascii=False), encoding="utf-8")
    size_kb_dis = out_dis.stat().st_size / 1024
    logger.info(
        "[OK] %s: %d features, %.1f KB",
        out_dis.name, len(dis_fc["features"]), size_kb_dis,
    )

    # ---- sanity stats ----
    n = len(dis_fc["features"])
    causes = Counter(f["properties"]["principal_cause"] for f in dis_fc["features"])
    topos = Counter(f["properties"]["topology"] for f in dis_fc["features"])
    tiers = Counter(f["properties"]["tier"] for f in dis_fc["features"])
    fc_counts = Counter(f["properties"]["fc"] for f in vis_fc["features"])
    tvr_vals = sorted(f["properties"]["TVr"] for f in vis_fc["features"])
    dpl_vals = sorted(f["properties"]["DPL"] for f in vis_fc["features"])

    logger.info("[STATS] Discontinuites distribution (n=%d):", n)
    for k, v in causes.most_common():
        logger.info("  cause %-25s %4d  (%5.1f%%)", k, v, 100 * v / n)
    for k, v in topos.most_common():
        logger.info("  topo  %-25s %4d  (%5.1f%%)", k, v, 100 * v / n)
    for k, v in tiers.most_common():
        logger.info("  tier  %-25s %4d  (%5.1f%%)", k, v, 100 * v / n)

    logger.info("[STATS] Visualisation FC distribution:")
    for fc_val in sorted(fc_counts):
        logger.info("  fc=%d : %d", fc_val, fc_counts[fc_val])
    if tvr_vals:
        logger.info(
            "  TVr min/med/max = %.0f / %.0f / %.0f",
            tvr_vals[0], tvr_vals[len(tvr_vals) // 2], tvr_vals[-1],
        )
    if dpl_vals:
        logger.info(
            "  DPL min/med/max = %.0f / %.0f / %.0f",
            dpl_vals[0], dpl_vals[len(dpl_vals) // 2], dpl_vals[-1],
        )

    logger.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
