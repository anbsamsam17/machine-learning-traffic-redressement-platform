"""
run_discontinuity_analysis.py
=============================

Discontinuity detection pipeline for HERE-style directed road network
(`2025.geojson`, ~241 857 edges, EPSG:4326).

Implements the FINAL methodology consolidated in `00_METHODOLOGY.md` plus
the accepted changes from expert reviews 01/02/03/05:

    * No DSU (HERE REF/NREF already encode the physical junction).
    * No geometry reversal for `-T` rows (source already in flow order).
    * 6-band flow-tiered grid for inter-segment continuity, with AND-of-3 below
      5 000 veh/j and 2-of-3 above.
    * Degree-scaled `min_flow_required` for node conservation, with relaxed
      `rel_imb` threshold on multi-leg junctions.
    * Boundary nodes split out to `coverage_gaps.csv` (not flagged).
    * Anti-double-count masks the pair score only if BOTH endpoints are bad.

Outputs (in `scripts/discontinuity_methodology/outputs/`):
    discontinuity_edges.geojson    discontinuity_nodes.csv
    discontinuity_nodes_full.csv   coverage_gaps.csv
    qc_summary.json                discontinuity_map.html
    top_findings.html              README.md

Run from anywhere:
    python scripts/discontinuity_methodology/run_discontinuity_analysis.py

Sampling mode (smoke test):
    python ... --sample 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import geopandas as gpd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
DEFAULT_SRC = (
    DATA_ROOT / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables" / "2025.geojson"
)

# ----- Flow-tiered grid for inter-segment continuity (Phase 2A) -----
# (max_flow_upper_bound, rel_cut, abs_cut, geh_cut, two_of_three)
TIERS: List[Tuple[float, float, float, float, bool]] = [
    (500.0,     0.40, 150.0,   9.0, False),
    (2000.0,    0.20, 250.0,   7.0, False),
    (5000.0,    0.18, 500.0,   8.0, False),
    (10000.0,   0.15, 800.0,  10.0, True),
    (25000.0,   0.14, 1200.0, 12.0, True),
    (np.inf,    0.12, 2000.0, 14.0, True),
]

# Multiplier on rel_cut / abs_cut / geh_cut when one (and only one) of the two
# edges in the pair is a roundabout ring brin (entry/exit). Review A.
ROUNDABOUT_ADJ_LOOSEN = 2.0

# Node conservation thresholds (Phase 2B)
MIN_FLOW_BASE = 3000.0      # veh/day baseline
MIN_FLOW_PER_DEGREE = 600.0  # extra threshold per attached edge
GEH_NODE_CUT = 15.0
REL_IMB_CUT_SIMPLE = 0.18    # |n_in - n_out| < 2
REL_IMB_CUT_ASYM = 0.22      # multi-leg asymmetric junctions

# Composite severity weights
W_NODE = 0.6
W_PAIR = 0.4

RNG_SEED = 1750

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("discontinuity")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_div(a: np.ndarray, b: np.ndarray, default: float = 0.0) -> np.ndarray:
    """Element-wise a / b, with `default` where b == 0 (avoids div-by-zero)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    out = np.full_like(a, default, dtype=np.float64)
    mask = b != 0
    out[mask] = a[mask] / b[mask]
    return out


def compute_geh(observed: np.ndarray, modelled: np.ndarray) -> np.ndarray:
    """GEH statistic = sqrt(2*(M-C)^2 / (M+C)).

    Returns 0 where both flows are zero (no signal). Inputs in veh/day are
    accepted directly per methodology — the GEH formula is unit-agnostic;
    its calibration in our grid was tuned on daily flows.
    """
    o = np.asarray(observed, dtype=np.float64)
    m = np.asarray(modelled, dtype=np.float64)
    num = 2.0 * (m - o) ** 2
    den = m + o
    geh = np.zeros_like(num)
    mask = den > 0
    geh[mask] = np.sqrt(num[mask] / den[mask])
    return geh


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Discontinuity detection pipeline.")
    p.add_argument("--src", type=Path, default=DEFAULT_SRC,
                   help="Input GeoJSON path.")
    p.add_argument("--out", type=Path, default=OUT_DIR,
                   help="Output directory.")
    p.add_argument("--sample", type=int, default=0,
                   help="If > 0, run on a deterministic sample of N edges (smoke test).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Stage 1 — Load + sanity
# ---------------------------------------------------------------------------

def stage1_load(src: Path, sample: int = 0) -> Tuple[gpd.GeoDataFrame, Dict]:
    t0 = time.perf_counter()
    log.info("S1. Loading %s ...", src)
    gdf = gpd.read_file(src, engine="pyogrio")
    qc: Dict[str, object] = {"n_rows_in": int(len(gdf)), "crs": str(gdf.crs)}

    # Normalise dtypes used downstream
    gdf["REF_IN_ID"] = pd.to_numeric(gdf["REF_IN_ID"], errors="coerce")
    gdf["NREF_IN_ID"] = pd.to_numeric(gdf["NREF_IN_ID"], errors="coerce")
    gdf["TVr"] = pd.to_numeric(gdf["TVr"], errors="coerce").astype("float64")

    bad = gdf["REF_IN_ID"].isna() | gdf["NREF_IN_ID"].isna()
    qc["dropped_missing_endpoints"] = int(bad.sum())
    gdf = gdf.loc[~bad].copy()

    sl = gdf["REF_IN_ID"] == gdf["NREF_IN_ID"]
    qc["dropped_self_loops"] = int(sl.sum())
    gdf = gdf.loc[~sl].copy()

    dup = gdf["agregId"].duplicated(keep=False)
    if dup.any():
        # Methodology says fatal, but a duplicate agregId after the load is so
        # rare on Lyon 2025 that we log loudly and keep only the first.
        log.error("Duplicate agregId detected (%d rows). Keeping first.", int(dup.sum()))
        qc["duplicate_agregId"] = int(dup.sum())
        gdf = gdf.drop_duplicates(subset="agregId", keep="first").copy()

    # Cast endpoints to int64 now that NaNs are gone
    gdf["REF_IN_ID"] = gdf["REF_IN_ID"].astype("int64")
    gdf["NREF_IN_ID"] = gdf["NREF_IN_ID"].astype("int64")

    if sample > 0 and sample < len(gdf):
        gdf = gdf.sample(n=sample, random_state=RNG_SEED).reset_index(drop=True)
        log.info("    sampled to %d rows (smoke test)", len(gdf))

    qc["n_rows_kept"] = int(len(gdf))
    qc["stage1_seconds"] = round(time.perf_counter() - t0, 3)
    log.info("    kept %d / %d rows in %.2fs",
             qc["n_rows_kept"], qc["n_rows_in"], qc["stage1_seconds"])
    return gdf, qc


# ---------------------------------------------------------------------------
# Stage 2 — Build directed edges (in_node / out_node)
# ---------------------------------------------------------------------------

def stage2_build_edges(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    t0 = time.perf_counter()
    log.info("S2. Building directed edges ...")

    agreg = gdf["agregId"].to_numpy(dtype=object)
    suffix = pd.Series(agreg).str.extract(r"-([FT])$", expand=False)
    has_suffix = suffix.notna()
    is_T = (suffix == "T").fillna(False).to_numpy()
    is_F = (suffix == "F").fillna(False).to_numpy()
    # base_id = agregId without trailing -F/-T
    base = np.where(has_suffix.to_numpy(),
                    pd.Series(agreg).str.replace(r"-[FT]$", "", regex=True),
                    agreg)
    gdf["base_id"] = base

    # dir_class: F, T, or O (one-way no-suffix)
    dir_class = np.where(is_T, "T", np.where(is_F, "F", "O"))
    gdf["dir_class"] = pd.Categorical(dir_class, categories=["F", "T", "O"])

    # in_node / out_node depending on dir_class (per FINAL spec)
    ref = gdf["REF_IN_ID"].to_numpy()
    nref = gdf["NREF_IN_ID"].to_numpy()
    gdf["in_node"] = np.where(is_T, nref, ref).astype("int64")
    gdf["out_node"] = np.where(is_T, ref, nref).astype("int64")

    # No geometry reversal (final methodology decision).
    qc_dir = pd.Series(dir_class).value_counts().to_dict()
    log.info("    dir_class counts: %s", qc_dir)
    log.info("    S2 done in %.2fs", time.perf_counter() - t0)
    return gdf


# ---------------------------------------------------------------------------
# Stage 3 — Adjacency, categories, boundaries
# ---------------------------------------------------------------------------

def stage3_adjacency(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    t0 = time.perf_counter()
    log.info("S3. Building adjacency ...")

    # Map base_id keyed by agregId for U-turn sibling suppression.
    base_of = dict(zip(edges["agregId"].to_numpy(), edges["base_id"].to_numpy()))

    # Group agregId lists by physical node.
    # out_links of edge u = edges leaving u.out_node  -> downstream candidates
    # in_links  of edge u = edges arriving at u.in_node -> upstream candidates
    out_by_node = (
        edges.groupby("in_node", sort=False)["agregId"].agg(list)
    )  # edges whose origin is this node
    in_by_node = (
        edges.groupby("out_node", sort=False)["agregId"].agg(list)
    )  # edges whose terminus is this node

    def _siblings_at(node_id, base, lookup):
        lst = lookup.get(node_id)
        if lst is None:
            return []
        return [a for a in lst if base_of.get(a) != base]

    out_lookup = out_by_node.to_dict()
    in_lookup = in_by_node.to_dict()

    # For each edge:
    #   out_links = edges starting at edge.out_node (with same-base-id removed)
    #   in_links  = edges ending   at edge.in_node  (with same-base-id removed)
    out_links: List[List[str]] = []
    in_links: List[List[str]] = []
    out_node_arr = edges["out_node"].to_numpy()
    in_node_arr = edges["in_node"].to_numpy()
    base_arr = edges["base_id"].to_numpy()
    for o_n, i_n, b in zip(out_node_arr, in_node_arr, base_arr):
        out_links.append(_siblings_at(o_n, b, out_lookup))
        in_links.append(_siblings_at(i_n, b, in_lookup))

    edges["out_links"] = out_links
    edges["in_links"] = in_links
    edges["out_deg"] = np.array([len(x) for x in out_links], dtype=np.int32)
    edges["in_deg"] = np.array([len(x) for x in in_links], dtype=np.int32)
    edges["is_source"] = edges["in_deg"].eq(0)
    edges["is_sink"] = edges["out_deg"].eq(0)
    edges["is_isolated"] = edges["is_source"] & edges["is_sink"]

    # Categorise
    roundabout = edges["ROUNDABOUT"].astype(str).str.upper().eq("Y")
    ramp = edges["RAMP"].astype(str).str.upper().eq("Y")
    is_oneway = edges["dir_class"].astype(str).eq("O")

    cat = np.where(
        roundabout, "roundabout",
        np.where(ramp, "ramp",
                 np.where(is_oneway, "oneway", "bidir"))
    )
    edges["edge_category"] = pd.Categorical(
        cat, categories=["roundabout", "ramp", "oneway", "bidir"]
    )

    log.info("    out_deg: mean=%.2f  max=%d  | in_deg: mean=%.2f  max=%d",
             edges["out_deg"].mean(), int(edges["out_deg"].max()),
             edges["in_deg"].mean(), int(edges["in_deg"].max()))
    log.info("    categories: %s",
             edges["edge_category"].value_counts().to_dict())
    log.info("    S3 done in %.2fs", time.perf_counter() - t0)
    return edges


# ---------------------------------------------------------------------------
# Stage 4 — Inter-segment continuity (Phase 2A)
# ---------------------------------------------------------------------------

def stage4_pairs(edges: gpd.GeoDataFrame) -> pd.DataFrame:
    t0 = time.perf_counter()
    log.info("S4. Building pair table ...")

    # Project to the columns we need then explode out_links.
    base = edges[[
        "agregId", "TVr", "FC", "in_deg", "out_deg",
        "edge_category", "is_sink",
    ]].copy()

    expl = base.assign(v_id=edges["out_links"]).explode("v_id", ignore_index=True)
    expl = expl.dropna(subset=["v_id"])

    # Merge downstream edge metrics
    rhs = edges[["agregId", "TVr", "FC", "in_deg", "edge_category"]].rename(
        columns={
            "agregId": "v_id",
            "TVr": "TVr_v",
            "FC": "FC_v",
            "in_deg": "in_deg_v",
            "edge_category": "ec_v",
        }
    )
    pairs = expl.merge(rhs, on="v_id", how="inner")

    # NaN / negative flow filter (applied BEFORE max_flow per review B)
    nan_neg = (
        pairs["TVr"].isna() | (pairs["TVr"] < 0)
        | pairs["TVr_v"].isna() | (pairs["TVr_v"] < 0)
    )
    pairs = pairs.loc[~nan_neg].copy()

    # Skip rules
    is_diverg = pairs["out_deg"] >= 2
    is_converg = pairs["in_deg_v"] >= 2
    is_sink_u = pairs["is_sink"]
    both_ring = (pairs["edge_category"].astype(str) == "roundabout") & \
                (pairs["ec_v"].astype(str) == "roundabout")
    skip = is_diverg | is_converg | is_sink_u | both_ring
    pairs = pairs.loc[~skip].copy()

    if pairs.empty:
        log.info("    no analysable pair survived (sample?) — returning empty")
        return pairs.assign(
            max_flow=pd.Series(dtype=float),
            delta_abs=pd.Series(dtype=float),
            delta_rel=pd.Series(dtype=float),
            GEH_pair=pd.Series(dtype=float),
            flag=pd.Series(dtype=bool),
            severity_pair=pd.Series(dtype=float),
        )

    tvr = pairs["TVr"].to_numpy(dtype=np.float64)
    tvr_v = pairs["TVr_v"].to_numpy(dtype=np.float64)
    max_flow = np.maximum(tvr, tvr_v)
    delta_abs = tvr_v - tvr
    delta_rel = np.abs(delta_abs) / np.maximum(max_flow, 1.0)
    geh_pair = compute_geh(tvr, tvr_v)

    pairs["max_flow"] = max_flow
    pairs["delta_abs"] = delta_abs
    pairs["delta_rel"] = delta_rel
    pairs["GEH_pair"] = geh_pair

    # Tier classification via np.select
    n = len(pairs)
    rel_cut = np.empty(n, dtype=np.float64)
    abs_cut = np.empty(n, dtype=np.float64)
    geh_cut = np.empty(n, dtype=np.float64)
    two_of_three = np.empty(n, dtype=bool)
    # We iterate the 6 tiers in order, last-write-wins on increasing bound.
    # Equivalent to a np.select that respects ordering.
    assigned = np.zeros(n, dtype=bool)
    for upper, rc, ac, gc, t23 in TIERS:
        mask = (~assigned) & (max_flow < upper)
        rel_cut[mask] = rc
        abs_cut[mask] = ac
        geh_cut[mask] = gc
        two_of_three[mask] = t23
        assigned |= mask
    # Anything not assigned (e.g. inf max_flow on empty) → last tier defaults
    if (~assigned).any():
        upper, rc, ac, gc, t23 = TIERS[-1]
        rel_cut[~assigned] = rc
        abs_cut[~assigned] = ac
        geh_cut[~assigned] = gc
        two_of_three[~assigned] = t23

    # Roundabout adjacency loosening: one side ring but not both (both-ring skipped)
    one_ring = (
        (pairs["edge_category"].astype(str).to_numpy() == "roundabout")
        ^ (pairs["ec_v"].astype(str).to_numpy() == "roundabout")
    )
    rel_cut[one_ring] *= ROUNDABOUT_ADJ_LOOSEN
    abs_cut[one_ring] *= ROUNDABOUT_ADJ_LOOSEN
    geh_cut[one_ring] *= ROUNDABOUT_ADJ_LOOSEN

    # Test the 3 metrics
    c_rel = delta_rel > rel_cut
    c_abs = np.abs(delta_abs) > abs_cut
    c_geh = geh_pair > geh_cut

    cnt = c_rel.astype(np.int8) + c_abs.astype(np.int8) + c_geh.astype(np.int8)
    flag = np.where(two_of_three, cnt >= 2, cnt >= 3)
    pairs["flag"] = flag
    pairs["severity_pair"] = geh_pair * np.sqrt(np.maximum(max_flow, 0.0))
    # Mark whether jump is up (downstream higher) or down (downstream lower)
    pairs["jump_dir"] = np.where(delta_abs >= 0, "up", "down")

    n_flag = int(flag.sum())
    log.info("    pairs analysable: %d  | flagged: %d (%.1f%%)",
             n, n_flag, 100.0 * n_flag / max(n, 1))
    log.info("    S4 done in %.2fs", time.perf_counter() - t0)
    return pairs


# ---------------------------------------------------------------------------
# Stage 5 — Node conservation (Phase 2B)
# ---------------------------------------------------------------------------

def stage5_nodes(edges: gpd.GeoDataFrame) -> pd.DataFrame:
    t0 = time.perf_counter()
    log.info("S5. Building node table ...")

    # Drop NaN/neg TVr for aggregation only
    valid = edges["TVr"].fillna(0).clip(lower=0)
    tmp = edges[["in_node", "out_node"]].copy()
    tmp["TVr"] = valid

    out_flow = tmp.groupby("in_node")["TVr"].sum().rename("out_flow")
    in_flow = tmp.groupby("out_node")["TVr"].sum().rename("in_flow")
    n_out = tmp.groupby("in_node").size().rename("n_out")
    n_in = tmp.groupby("out_node").size().rename("n_in")

    # Outer-merge the four series on node_id
    nodes = pd.concat(
        [in_flow, out_flow, n_in, n_out], axis=1
    ).fillna(0.0)
    nodes.index.name = "node_id"
    nodes = nodes.reset_index()
    nodes["n_in"] = nodes["n_in"].astype(np.int32)
    nodes["n_out"] = nodes["n_out"].astype(np.int32)

    nodes["max_flow"] = nodes[["in_flow", "out_flow"]].max(axis=1)
    nodes["abs_imbalance"] = (nodes["in_flow"] - nodes["out_flow"]).abs()
    nodes["rel_imbalance"] = _safe_div(
        nodes["abs_imbalance"].to_numpy(), nodes["max_flow"].to_numpy(), default=0.0
    )
    nodes["GEH_node"] = compute_geh(
        nodes["in_flow"].to_numpy(), nodes["out_flow"].to_numpy()
    )
    nodes["is_boundary"] = (nodes["in_flow"] == 0) | (nodes["out_flow"] == 0)

    n_in_arr = nodes["n_in"].to_numpy()
    n_out_arr = nodes["n_out"].to_numpy()
    min_flow_required = np.maximum(
        MIN_FLOW_BASE, MIN_FLOW_PER_DEGREE * (n_in_arr + n_out_arr).astype(np.float64)
    )
    nodes["min_flow_required"] = min_flow_required

    rel_cut = np.where(
        np.abs(n_in_arr - n_out_arr) >= 2,
        REL_IMB_CUT_ASYM,
        REL_IMB_CUT_SIMPLE,
    )
    nodes["rel_imb_threshold"] = rel_cut

    nodes["is_bad"] = (
        ~nodes["is_boundary"]
        & (nodes["max_flow"] >= min_flow_required)
        & ((nodes["GEH_node"] > GEH_NODE_CUT) | (nodes["rel_imbalance"] > rel_cut))
    )

    nodes["severity_node"] = nodes["GEH_node"].to_numpy() * np.sqrt(
        np.maximum(nodes["max_flow"].to_numpy(), 0.0)
    )
    # Rank flagged nodes descending
    nodes["rank"] = (
        nodes["severity_node"]
        .where(nodes["is_bad"], np.nan)
        .rank(method="first", ascending=False)
    )

    log.info("    nodes: %d total | boundary: %d | flagged bad: %d",
             len(nodes),
             int(nodes["is_boundary"].sum()),
             int(nodes["is_bad"].sum()))
    log.info("    S5 done in %.2fs", time.perf_counter() - t0)
    return nodes


# ---------------------------------------------------------------------------
# Stage 6 — Composite severity per edge
# ---------------------------------------------------------------------------

def stage6_composite(
    edges: gpd.GeoDataFrame,
    pairs: pd.DataFrame,
    nodes: pd.DataFrame,
) -> gpd.GeoDataFrame:
    t0 = time.perf_counter()
    log.info("S6. Composite severity ...")

    node_lite = nodes[["node_id", "is_bad", "severity_node",
                       "rel_imbalance", "GEH_node"]]

    edges = edges.merge(
        node_lite.rename(columns={
            "node_id": "in_node",
            "is_bad": "in_bad",
            "severity_node": "sev_node_in",
            "rel_imbalance": "node_imbalance_in",
            "GEH_node": "GEH_node_in",
        }),
        on="in_node", how="left",
    )
    edges = edges.merge(
        node_lite.rename(columns={
            "node_id": "out_node",
            "is_bad": "out_bad",
            "severity_node": "sev_node_out",
            "rel_imbalance": "node_imbalance_out",
            "GEH_node": "GEH_node_out",
        }),
        on="out_node", how="left",
    )

    # Severities by edge
    edges["sev_node_in"] = edges["sev_node_in"].fillna(0.0).where(
        edges["in_bad"].fillna(False), 0.0
    )
    edges["sev_node_out"] = edges["sev_node_out"].fillna(0.0).where(
        edges["out_bad"].fillna(False), 0.0
    )

    # Pair severities
    if not pairs.empty and pairs["flag"].any():
        flagged = pairs.loc[pairs["flag"]]
        # Downstream flag: u flagged because of v ahead
        worst_down = flagged.groupby("agregId")["severity_pair"].max()
        # Upstream flag: v flagged because of u behind
        worst_up = flagged.groupby("v_id")["severity_pair"].max()
        # The direction of the jump: up means flow rose downstream (TVr_v > TVr)
        worst_down_dir = flagged.sort_values(
            "severity_pair", ascending=False, kind="mergesort"
        ).drop_duplicates("agregId").set_index("agregId")["jump_dir"]
        worst_up_dir = flagged.sort_values(
            "severity_pair", ascending=False, kind="mergesort"
        ).drop_duplicates("v_id").set_index("v_id")["jump_dir"]
    else:
        worst_down = pd.Series(dtype=float)
        worst_up = pd.Series(dtype=float)
        worst_down_dir = pd.Series(dtype=object)
        worst_up_dir = pd.Series(dtype=object)

    edges["sev_pair_down"] = edges["agregId"].map(worst_down).fillna(0.0)
    edges["sev_pair_up"] = edges["agregId"].map(worst_up).fillna(0.0)
    edges["pair_down_dir"] = edges["agregId"].map(worst_down_dir)
    edges["pair_up_dir"] = edges["agregId"].map(worst_up_dir)

    # Anti-double-count: mask pair score ONLY if BOTH endpoints are bad nodes.
    both_bad = edges["in_bad"].fillna(False) & edges["out_bad"].fillna(False)
    sev_pair_eff_down = np.where(both_bad, 0.0, edges["sev_pair_down"].to_numpy())
    sev_pair_eff_up = np.where(both_bad, 0.0, edges["sev_pair_up"].to_numpy())

    score_node = np.maximum(
        edges["sev_node_in"].to_numpy(), edges["sev_node_out"].to_numpy()
    )
    score_pair = np.maximum(sev_pair_eff_down, sev_pair_eff_up)

    edges["composite_severity"] = W_NODE * score_node + W_PAIR * score_pair

    # top_issue: argmax over the four sources
    sources = np.stack([
        sev_pair_eff_up,      # jump_up   (this edge is the v in u→v)
        sev_pair_eff_down,    # jump_down (this edge is the u in u→v)
        edges["sev_node_in"].to_numpy(),
        edges["sev_node_out"].to_numpy(),
    ], axis=1)
    names = np.array(["jump_up", "jump_down",
                      "node_in_imbalance", "node_out_imbalance"])
    # Mask zero rows to "none"
    row_max = sources.max(axis=1)
    idx = sources.argmax(axis=1)
    top_issue = np.where(row_max > 0, names[idx], None)
    edges["top_issue"] = top_issue

    # Severity tier by percentile of composite_severity AMONG flagged edges
    flagged_mask = edges["composite_severity"] > 0
    if flagged_mask.any():
        flagged_vals = edges.loc[flagged_mask, "composite_severity"].to_numpy()
        p25, p75 = np.percentile(flagged_vals, [25.0, 75.0])
    else:
        p25 = p75 = 0.0

    def _tier(v: float) -> str:
        if v <= 0:
            return "none"
        if v < p25:
            return "green"
        if v < p75:
            return "orange"
        return "red"

    edges["severity_tier"] = pd.Categorical(
        np.array([_tier(v) for v in edges["composite_severity"].to_numpy()]),
        categories=["none", "green", "orange", "red"],
    )

    log.info("    flagged edges (composite_severity>0): %d",
             int((edges["composite_severity"] > 0).sum()))
    log.info("    percentiles (p25/p75 of flagged): %.2f / %.2f", p25, p75)
    log.info("    S6 done in %.2fs", time.perf_counter() - t0)
    return edges, float(p25), float(p75)


# ---------------------------------------------------------------------------
# Stage 7 — Export
# ---------------------------------------------------------------------------

def stage7_export(
    edges: gpd.GeoDataFrame,
    nodes: pd.DataFrame,
    qc: Dict,
    out_dir: Path,
    p25: float,
    p75: float,
) -> Dict[str, Path]:
    t0 = time.perf_counter()
    log.info("S7. Exporting ...")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}

    # ---- 1. discontinuity_edges.geojson (flagged only) ----
    flagged = edges.loc[edges["composite_severity"] > 0].copy()
    flagged = flagged.sort_values(
        "composite_severity", ascending=False, kind="mergesort"
    )
    keep = [
        "agregId", "in_node", "out_node", "base_id", "dir_class",
        "TVr", "DPL", "FC", "FUNC_CLASS", "RAMP", "ROUNDABOUT",
        "edge_category", "in_deg", "out_deg",
        "sev_pair_up", "sev_pair_down", "sev_node_in", "sev_node_out",
        "composite_severity", "severity_tier", "top_issue",
        "node_imbalance_in", "node_imbalance_out",
        "GEH_node_in", "GEH_node_out",
        "geometry",
    ]
    keep = [c for c in keep if c in flagged.columns]
    flagged_out = flagged[keep].rename(columns={
        "in_deg": "n_in_links",
        "out_deg": "n_out_links",
    })
    # Cast for GeoJSON friendliness
    for c in ["dir_class", "edge_category", "severity_tier"]:
        if c in flagged_out.columns:
            flagged_out[c] = flagged_out[c].astype(str)
    # geometry must be set
    flagged_gdf = gpd.GeoDataFrame(flagged_out, geometry="geometry", crs=edges.crs)
    p_edges = out_dir / "discontinuity_edges.geojson"
    if p_edges.exists():
        p_edges.unlink()
    flagged_gdf.to_file(p_edges, driver="GeoJSON", engine="pyogrio")
    paths["edges_geojson"] = p_edges
    log.info("    wrote %s (%d features)", p_edges.name, len(flagged_gdf))

    # ---- 2. discontinuity_nodes.csv (bad only) ----
    bad_nodes = nodes.loc[nodes["is_bad"]].copy()
    bad_nodes = bad_nodes.sort_values(
        "severity_node", ascending=False, kind="mergesort"
    )
    bad_cols = [
        "node_id", "in_flow", "out_flow", "abs_imbalance", "rel_imbalance",
        "GEH_node", "n_in", "n_out", "min_flow_required",
        "rel_imb_threshold", "severity_node", "rank",
    ]
    bad_cols = [c for c in bad_cols if c in bad_nodes.columns]
    p_nodes = out_dir / "discontinuity_nodes.csv"
    bad_nodes[bad_cols].to_csv(p_nodes, index=False)
    paths["nodes_csv"] = p_nodes
    log.info("    wrote %s (%d rows)", p_nodes.name, len(bad_nodes))

    # ---- 3. discontinuity_nodes_full.csv ----
    p_nodes_full = out_dir / "discontinuity_nodes_full.csv"
    full_cols = [
        "node_id", "in_flow", "out_flow", "abs_imbalance", "rel_imbalance",
        "GEH_node", "n_in", "n_out", "max_flow", "min_flow_required",
        "rel_imb_threshold", "is_boundary", "is_bad", "severity_node",
    ]
    full_cols = [c for c in full_cols if c in nodes.columns]
    nodes.sort_values("severity_node", ascending=False, kind="mergesort")[
        full_cols
    ].to_csv(p_nodes_full, index=False)
    paths["nodes_full_csv"] = p_nodes_full
    log.info("    wrote %s (%d rows)", p_nodes_full.name, len(nodes))

    # ---- 4. coverage_gaps.csv ----
    gaps = nodes.loc[nodes["is_boundary"]].copy()
    gap_cols = [
        "node_id", "in_flow", "out_flow", "n_in", "n_out",
        "abs_imbalance", "rel_imbalance",
    ]
    gap_cols = [c for c in gap_cols if c in gaps.columns]
    p_gaps = out_dir / "coverage_gaps.csv"
    gaps[gap_cols].to_csv(p_gaps, index=False)
    paths["coverage_gaps"] = p_gaps
    log.info("    wrote %s (%d rows)", p_gaps.name, len(gaps))

    # ---- 5. qc_summary.json ----
    tier_counts = flagged_gdf["severity_tier"].value_counts().to_dict() if len(flagged_gdf) else {}
    top_issue_counts = (
        flagged_gdf["top_issue"].value_counts().to_dict() if len(flagged_gdf) else {}
    )
    qc_out = dict(qc)
    qc_out.update({
        "total_edges": int(len(edges)),
        "flagged_edges": int(len(flagged_gdf)),
        "tier_counts": {str(k): int(v) for k, v in tier_counts.items()},
        "top_issue_counts": {str(k): int(v) for k, v in top_issue_counts.items()},
        "total_nodes": int(len(nodes)),
        "boundary_nodes": int(nodes["is_boundary"].sum()),
        "flagged_nodes": int(nodes["is_bad"].sum()),
        "severity_p25_flagged": p25,
        "severity_p75_flagged": p75,
        "thresholds": {
            "tiers": [
                {"max_flow_upper": (None if np.isinf(u) else u),
                 "rel_cut": rc, "abs_cut": ac, "geh_cut": gc,
                 "two_of_three": t23}
                for u, rc, ac, gc, t23 in TIERS
            ],
            "node_min_flow_base": MIN_FLOW_BASE,
            "node_min_flow_per_degree": MIN_FLOW_PER_DEGREE,
            "node_geh_cut": GEH_NODE_CUT,
            "node_rel_imb_simple": REL_IMB_CUT_SIMPLE,
            "node_rel_imb_asym": REL_IMB_CUT_ASYM,
            "weight_node": W_NODE,
            "weight_pair": W_PAIR,
        },
    })
    p_qc = out_dir / "qc_summary.json"
    p_qc.write_text(json.dumps(qc_out, indent=2, default=str), encoding="utf-8")
    paths["qc_summary"] = p_qc
    log.info("    wrote %s", p_qc.name)

    log.info("    S7 done in %.2fs", time.perf_counter() - t0)
    return paths, flagged_gdf, qc_out


# ---------------------------------------------------------------------------
# Stage 8 — HTML map & top-findings
# ---------------------------------------------------------------------------

def stage8_html(
    flagged_gdf: gpd.GeoDataFrame,
    bad_nodes: pd.DataFrame,
    p25: float,
    p75: float,
    out_dir: Path,
) -> Dict[str, Path]:
    t0 = time.perf_counter()
    log.info("S8. Rendering HTML map ...")

    paths: Dict[str, Path] = {}

    # Build a slim GeoJSON dict (avoid letting json reformat all coords).
    # Cap inlined edges to keep map file < 8 MB; the FULL set is always in
    # `discontinuity_edges.geojson` for QGIS.
    MAX_INLINE_EDGES = 8000
    if len(flagged_gdf):
        if len(flagged_gdf) > MAX_INLINE_EDGES:
            map_flagged = flagged_gdf.head(MAX_INLINE_EDGES).copy()
            log.info(
                "    map: inlining top %d edges (out of %d flagged) for size budget",
                MAX_INLINE_EDGES, len(flagged_gdf),
            )
        else:
            map_flagged = flagged_gdf
        # Coerce numeric columns to native python so json.dumps works fine
        slim_cols = [
            "agregId", "in_node", "out_node", "TVr", "DPL", "FC",
            "FUNC_CLASS", "RAMP", "ROUNDABOUT", "edge_category",
            "n_in_links", "n_out_links", "composite_severity",
            "severity_tier", "top_issue",
            "sev_pair_up", "sev_pair_down", "sev_node_in", "sev_node_out",
        ]
        slim_cols = [c for c in slim_cols if c in map_flagged.columns]
        slim = map_flagged[slim_cols + ["geometry"]].copy()
        # cast numpy types to python natives
        for c in slim_cols:
            if pd.api.types.is_float_dtype(slim[c]):
                slim[c] = slim[c].astype(float)
            elif pd.api.types.is_integer_dtype(slim[c]):
                slim[c] = slim[c].astype("Int64").astype(object).where(slim[c].notna(), None)
        edges_geojson = json.loads(slim.to_json())
        # Trim coordinate precision to 5 decimals (~1.1m) to keep file size sane
        for ft in edges_geojson.get("features", []):
            geom = ft.get("geometry")
            if not geom:
                continue
            coords = geom.get("coordinates")
            if not coords:
                continue
            geom["coordinates"] = [
                [round(c[0], 5), round(c[1], 5)] for c in coords
            ]
    else:
        edges_geojson = {"type": "FeatureCollection", "features": []}

    # Bad node markers
    if len(bad_nodes):
        bad_nodes_payload = []
        for _, r in bad_nodes.head(5000).iterrows():
            # We need node coords — but we don't have a node geometry table here.
            # We'll skip nodes layer if we don't have coords.
            continue
        # We'll attach coords below from the edges layer (use endpoints).
    bad_node_ids = set(bad_nodes["node_id"].tolist()) if len(bad_nodes) else set()

    # Derive node coordinates from edge geometries (cheap once).
    node_coords: Dict[int, Tuple[float, float]] = {}
    if len(flagged_gdf):
        # Use the FULL flagged set (not the capped map subset) to maximise
        # node-coord coverage for the cluster layer.
        for in_n, out_n, geom in zip(
            flagged_gdf["in_node"].to_numpy(),
            flagged_gdf["out_node"].to_numpy(),
            flagged_gdf.geometry.to_numpy(),
        ):
            if geom is None:
                continue
            coords = list(geom.coords)
            if not coords:
                continue
            if in_n in bad_node_ids and in_n not in node_coords:
                node_coords[int(in_n)] = (float(coords[0][0]), float(coords[0][1]))
            if out_n in bad_node_ids and out_n not in node_coords:
                node_coords[int(out_n)] = (float(coords[-1][0]), float(coords[-1][1]))

    # Build a {agregId: bad_node_lookup} for popups
    node_lookup = {}
    if len(bad_nodes):
        for _, r in bad_nodes.iterrows():
            nid = int(r["node_id"])
            node_lookup[nid] = {
                "severity_node": float(r["severity_node"]),
                "in_flow": float(r["in_flow"]),
                "out_flow": float(r["out_flow"]),
                "rel_imbalance": float(r["rel_imbalance"]),
                "GEH_node": float(r["GEH_node"]),
                "n_in": int(r["n_in"]),
                "n_out": int(r["n_out"]),
            }

    nodes_features = []
    for nid, (lon, lat) in node_coords.items():
        info = node_lookup.get(nid, {})
        nodes_features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"node_id": nid, **info},
        })
    nodes_geojson = {"type": "FeatureCollection", "features": nodes_features}

    # Bounds for "Fit to flagged"
    bounds = None
    if len(flagged_gdf):
        b = flagged_gdf.total_bounds  # [minx, miny, maxx, maxy]
        bounds = [[float(b[1]), float(b[0])], [float(b[3]), float(b[2])]]

    # Build top findings (top 20 by composite_severity)
    top20 = flagged_gdf.head(20).copy() if len(flagged_gdf) else flagged_gdf

    # Inject into template
    html = _render_map_html(
        edges_geojson=edges_geojson,
        nodes_geojson=nodes_geojson,
        bounds=bounds,
        p25=p25, p75=p75,
        total_flagged=int(len(flagged_gdf)),
        total_bad_nodes=int(len(bad_nodes)),
    )
    p_map = out_dir / "discontinuity_map.html"
    p_map.write_text(html, encoding="utf-8")
    paths["map_html"] = p_map
    log.info("    wrote %s (%.1f KB)", p_map.name, p_map.stat().st_size / 1024)

    # Top findings page
    rows_html = ""
    for i, (_, r) in enumerate(top20.iterrows(), 1):
        coords = list(r.geometry.coords) if r.geometry is not None else []
        lon, lat = (coords[0] if coords else (0.0, 0.0))
        rows_html += (
            f"<tr><td>{i}</td>"
            f"<td><a href='discontinuity_map.html#agregId={r['agregId']}'>"
            f"{r['agregId']}</a></td>"
            f"<td>{r['composite_severity']:.1f}</td>"
            f"<td>{r['severity_tier']}</td>"
            f"<td>{r['top_issue']}</td>"
            f"<td>{r['TVr']:.0f}</td>"
            f"<td>{r['FC']}</td>"
            f"<td>{r['edge_category']}</td>"
            f"<td>{lat:.5f}, {lon:.5f}</td>"
            f"</tr>"
        )
    top_html = _render_top_findings_html(rows_html, len(top20))
    p_top = out_dir / "top_findings.html"
    p_top.write_text(top_html, encoding="utf-8")
    paths["top_findings"] = p_top
    log.info("    wrote %s", p_top.name)

    log.info("    S8 done in %.2fs", time.perf_counter() - t0)
    return paths


def _render_map_html(
    edges_geojson: dict,
    nodes_geojson: dict,
    bounds,
    p25: float,
    p75: float,
    total_flagged: int,
    total_bad_nodes: int,
) -> str:
    edges_json = json.dumps(edges_geojson, ensure_ascii=False, default=str)
    nodes_json = json.dumps(nodes_geojson, ensure_ascii=False, default=str)
    bounds_json = json.dumps(bounds)

    # Standalone Leaflet 1.9 + MarkerCluster. Inlined GeoJSON.
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<title>Discontinuites TVr - Lyon Metropole 2025</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="" />
<link rel="stylesheet"
      href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet"
      href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
html, body {{ margin: 0; height: 100%; font-family: -apple-system, "Segoe UI", Roboto, sans-serif; }}
#map {{ position: absolute; top: 0; left: 320px; right: 0; bottom: 0; }}
#sidebar {{
  position: absolute; top: 0; left: 0; bottom: 0; width: 320px;
  background: #fafafa; border-right: 1px solid #ddd;
  overflow-y: auto; padding: 12px 16px; box-sizing: border-box; z-index: 1000;
}}
#sidebar h1 {{ font-size: 16px; margin: 0 0 6px 0; }}
#sidebar h2 {{ font-size: 13px; margin: 18px 0 6px 0; color: #555; text-transform: uppercase; }}
.stat {{ font-size: 12px; color: #444; margin: 2px 0; }}
.legend-line {{ display: inline-block; width: 30px; height: 4px; vertical-align: middle; margin-right: 8px; }}
.legend-row {{ font-size: 12px; margin: 4px 0; }}
label {{ font-size: 12px; display: block; margin: 6px 0 2px 0; }}
select, input[type=range] {{ width: 100%; box-sizing: border-box; }}
button {{
  padding: 6px 10px; margin-top: 8px;
  background: #1976d2; color: #fff; border: 0; border-radius: 4px;
  cursor: pointer; font-size: 12px;
}}
button:hover {{ background: #135aa8; }}
.tier-red    {{ stroke: #d32f2f; }}
.tier-orange {{ stroke: #f57c00; }}
.tier-green  {{ stroke: #388e3c; }}
.popup-table td {{ padding: 2px 8px 2px 0; font-size: 12px; vertical-align: top; }}
.popup-table th {{ text-align: left; color: #888; font-weight: normal; font-size: 11px; padding-right: 8px; }}
</style>
</head>
<body>
<div id="sidebar">
  <h1>Discontinuites TVr - Lyon 2025</h1>
  <div class="stat"><b>{total_flagged}</b> aretes flaggees</div>
  <div class="stat"><b>{total_bad_nodes}</b> noeuds flagges</div>
  <div class="stat">p25 / p75 severite = <b>{p25:.1f}</b> / <b>{p75:.1f}</b></div>

  <h2>Legende</h2>
  <div class="legend-row"><span class="legend-line" style="background:#d32f2f"></span>Rouge (severite &gt; p75)</div>
  <div class="legend-row"><span class="legend-line" style="background:#f57c00"></span>Orange (p25-p75)</div>
  <div class="legend-row"><span class="legend-line" style="background:#388e3c"></span>Vert (&lt; p25)</div>
  <div class="legend-row" style="margin-top:6px">
    Trait plein = jump &nbsp; · &nbsp; Pointille = noeud
  </div>

  <h2>Filtres</h2>
  <label>Tier de severite</label>
  <select id="filterTier">
    <option value="">Tous</option>
    <option value="red">Rouge</option>
    <option value="orange">Orange</option>
    <option value="green">Vert</option>
  </select>

  <label>FUNC_CLASS</label>
  <select id="filterFC">
    <option value="">Toutes</option>
    <option value="1">1</option><option value="2">2</option>
    <option value="3">3</option><option value="4">4</option>
    <option value="5">5</option>
  </select>

  <label>top_issue</label>
  <select id="filterIssue">
    <option value="">Tous</option>
    <option value="jump_up">jump_up</option>
    <option value="jump_down">jump_down</option>
    <option value="node_in_imbalance">node_in_imbalance</option>
    <option value="node_out_imbalance">node_out_imbalance</option>
  </select>

  <label>Severite minimale: <span id="minSevVal">0</span></label>
  <input type="range" id="minSevSlider" min="0" max="2000" step="10" value="0" />

  <h2>Affichage</h2>
  <label><input type="checkbox" id="layerEdges" checked /> Couche aretes</label>
  <label><input type="checkbox" id="layerNodes" checked /> Couche noeuds</label>

  <button id="fitFlagged">Recentrer sur flagges</button>
  <button id="resetFilters">Reset filtres</button>

  <h2>Liens</h2>
  <div class="stat"><a href="top_findings.html" target="_blank">Top 20 discontinuites</a></div>
  <div class="stat"><a href="README.md" target="_blank">README</a></div>
</div>
<div id="map"></div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
const EDGES = {edges_json};
const NODES = {nodes_json};
const BOUNDS = {bounds_json};

const map = L.map('map').setView([45.75, 4.85], 11);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
  attribution: '(c) OpenStreetMap (c) CartoDB',
  subdomains: 'abcd', maxZoom: 19
}}).addTo(map);

if (BOUNDS) map.fitBounds(BOUNDS);

const TIER_STYLES = {{
  red:    {{color: '#d32f2f', weight: 4, opacity: 0.9, dashArray: null}},
  orange: {{color: '#f57c00', weight: 3, opacity: 0.85, dashArray: null}},
  green:  {{color: '#388e3c', weight: 2, opacity: 0.8,  dashArray: null}},
  none:   {{color: '#888',    weight: 1, opacity: 0.4,  dashArray: '2,4'}}
}};

function styleEdge(f) {{
  const tier = f.properties.severity_tier || 'green';
  const base = TIER_STYLES[tier] || TIER_STYLES.green;
  const issue = f.properties.top_issue || '';
  // Dash pattern variant by issue type (WCAG accessibility cue)
  const style = Object.assign({{}}, base);
  if (issue.startsWith('node_')) {{
    style.dashArray = '6,4';
  }} else if (issue === 'jump_up') {{
    style.dashArray = null;
  }} else if (issue === 'jump_down') {{
    style.dashArray = '10,4,2,4';
  }}
  return style;
}}

function popupEdge(f) {{
  const p = f.properties;
  const html = `
    <table class="popup-table">
      <tr><th>agregId</th><td><b>${{p.agregId}}</b>
        <button onclick="navigator.clipboard.writeText('${{p.agregId}}')" style="margin-left:6px;padding:1px 6px;font-size:10px;">Copier</button>
      </td></tr>
      <tr><th>severity</th><td>${{Number(p.composite_severity).toFixed(1)}} (${{p.severity_tier}})</td></tr>
      <tr><th>top_issue</th><td>${{p.top_issue || '-'}}</td></tr>
      <tr><th>TVr</th><td>${{p.TVr}} veh/j</td></tr>
      <tr><th>FC / FUNC_CLASS</th><td>${{p.FC}} / ${{p.FUNC_CLASS}}</td></tr>
      <tr><th>edge_category</th><td>${{p.edge_category}}</td></tr>
      <tr><th>RAMP / ROUNDABOUT</th><td>${{p.RAMP}} / ${{p.ROUNDABOUT}}</td></tr>
      <tr><th>in_node -> out_node</th><td>${{p.in_node}} -> ${{p.out_node}}</td></tr>
      <tr><th>n_in / n_out links</th><td>${{p.n_in_links}} / ${{p.n_out_links}}</td></tr>
      <tr><th>sev pair up/down</th><td>${{Number(p.sev_pair_up).toFixed(1)}} / ${{Number(p.sev_pair_down).toFixed(1)}}</td></tr>
      <tr><th>sev node in/out</th><td>${{Number(p.sev_node_in).toFixed(1)}} / ${{Number(p.sev_node_out).toFixed(1)}}</td></tr>
    </table>`;
  return html;
}}

let edgesLayer = null;
let nodesLayer = null;
let nodesCluster = null;

function buildEdges() {{
  if (edgesLayer) map.removeLayer(edgesLayer);
  const filterTier  = document.getElementById('filterTier').value;
  const filterFC    = document.getElementById('filterFC').value;
  const filterIssue = document.getElementById('filterIssue').value;
  const minSev      = Number(document.getElementById('minSevSlider').value);
  edgesLayer = L.geoJSON(EDGES, {{
    style: styleEdge,
    filter: f => {{
      const p = f.properties;
      if (filterTier && p.severity_tier !== filterTier) return false;
      if (filterFC && String(p.FC) !== filterFC) return false;
      if (filterIssue && p.top_issue !== filterIssue) return false;
      if (Number(p.composite_severity) < minSev) return false;
      return true;
    }},
    onEachFeature: (f, layer) => {{
      layer.bindPopup(popupEdge(f));
      layer.on('click', () => {{ window.location.hash = 'agregId=' + f.properties.agregId; }});
    }}
  }});
  if (document.getElementById('layerEdges').checked) edgesLayer.addTo(map);
}}

function buildNodes() {{
  if (nodesCluster) map.removeLayer(nodesCluster);
  nodesCluster = L.markerClusterGroup({{ maxClusterRadius: 40 }});
  L.geoJSON(NODES, {{
    pointToLayer: (f, latlng) => L.circleMarker(latlng, {{
      radius: 6, color: '#5d2c8c', weight: 1, fillColor: '#7e57c2', fillOpacity: 0.7
    }}),
    onEachFeature: (f, layer) => {{
      const p = f.properties;
      const html = `<table class="popup-table">
        <tr><th>node_id</th><td>${{p.node_id}}</td></tr>
        <tr><th>severity</th><td>${{Number(p.severity_node || 0).toFixed(1)}}</td></tr>
        <tr><th>in / out flow</th><td>${{Number(p.in_flow || 0).toFixed(0)}} / ${{Number(p.out_flow || 0).toFixed(0)}}</td></tr>
        <tr><th>rel_imbalance</th><td>${{Number((p.rel_imbalance || 0) * 100).toFixed(1)}}%</td></tr>
        <tr><th>GEH_node</th><td>${{Number(p.GEH_node || 0).toFixed(1)}}</td></tr>
        <tr><th>n_in / n_out</th><td>${{p.n_in}} / ${{p.n_out}}</td></tr>
      </table>`;
      layer.bindPopup(html);
      nodesCluster.addLayer(layer);
    }}
  }});
  if (document.getElementById('layerNodes').checked) nodesCluster.addTo(map);
}}

function refreshAll() {{
  buildEdges();
  buildNodes();
  applyHashHighlight();
}}

function applyHashHighlight() {{
  if (!edgesLayer) return;
  const m = (window.location.hash || '').match(/agregId=([^&]+)/);
  if (!m) return;
  const target = decodeURIComponent(m[1]);
  edgesLayer.eachLayer(layer => {{
    if (layer.feature && layer.feature.properties.agregId === target) {{
      layer.setStyle({{weight: 8, opacity: 1.0}});
      map.fitBounds(layer.getBounds(), {{maxZoom: 17}});
      layer.openPopup();
    }}
  }});
}}

// Wire controls
['filterTier','filterFC','filterIssue'].forEach(id => {{
  document.getElementById(id).addEventListener('change', buildEdges);
}});
document.getElementById('minSevSlider').addEventListener('input', e => {{
  document.getElementById('minSevVal').textContent = e.target.value;
}});
document.getElementById('minSevSlider').addEventListener('change', buildEdges);
document.getElementById('layerEdges').addEventListener('change', e => {{
  if (e.target.checked) edgesLayer.addTo(map); else map.removeLayer(edgesLayer);
}});
document.getElementById('layerNodes').addEventListener('change', e => {{
  if (e.target.checked) nodesCluster.addTo(map); else map.removeLayer(nodesCluster);
}});
document.getElementById('fitFlagged').addEventListener('click', () => {{
  if (BOUNDS) map.fitBounds(BOUNDS);
}});
document.getElementById('resetFilters').addEventListener('click', () => {{
  document.getElementById('filterTier').value = '';
  document.getElementById('filterFC').value = '';
  document.getElementById('filterIssue').value = '';
  document.getElementById('minSevSlider').value = 0;
  document.getElementById('minSevVal').textContent = '0';
  buildEdges();
}});
window.addEventListener('hashchange', applyHashHighlight);

refreshAll();
</script>
</body>
</html>
"""


def _render_top_findings_html(rows_html: str, n: int) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr"><head>
<meta charset="UTF-8" />
<title>Top discontinuites TVr</title>
<style>
body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; padding: 24px; }}
h1 {{ font-size: 18px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #eee; }}
th {{ background: #f5f5f5; }}
tr:hover td {{ background: #fafafa; }}
a {{ color: #1976d2; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
</style></head><body>
<h1>Top {n} discontinuites par severite composite</h1>
<p><a href="discontinuity_map.html">&laquo; Retour a la carte</a></p>
<table>
<thead><tr>
<th>#</th><th>agregId</th><th>Severite</th><th>Tier</th>
<th>top_issue</th><th>TVr</th><th>FC</th><th>Category</th><th>lat, lon (origine)</th>
</tr></thead>
<tbody>
{rows_html}
</tbody></table>
</body></html>
"""


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def write_readme(out_dir: Path, qc_out: Dict) -> Path:
    readme = f"""# Discontinuity Detection Outputs

Generated by `run_discontinuity_analysis.py` from
`Travaux_donnees_Lyon/Livrables/2025.geojson`
({qc_out.get('n_rows_in', '?')} input edges, {qc_out.get('n_rows_kept', '?')} kept).

## Files

| File | Description |
|---|---|
| `discontinuity_edges.geojson` | Every edge with `composite_severity > 0`, sorted descending. EPSG:4326. Properties include `agregId`, `composite_severity`, `severity_tier`, `top_issue`, `TVr`, `FC`, `FUNC_CLASS`, `RAMP`, `ROUNDABOUT`, plus per-source severities. |
| `discontinuity_nodes.csv` | Flagged physical junctions (`is_bad = True`): in/out flow, GEH, rel_imbalance, degrees, `severity_node`, rank. |
| `discontinuity_nodes_full.csv` | All {qc_out.get('total_nodes', '?')} junctions (diagnostic, includes boundary + non-flagged). |
| `coverage_gaps.csv` | Boundary nodes (in_flow=0 OR out_flow=0). These signal possible missing FCD coverage rather than model errors. |
| `qc_summary.json` | Run stats: thresholds, counts per tier and per `top_issue`, percentiles. |
| `discontinuity_map.html` | Standalone Leaflet 1.9 map. Edges + bad-node markers (MarkerCluster). Filters by tier/FC/issue/min-severity. Deeplink via `#agregId=...`. |
| `top_findings.html` | Top 20 worst discontinuities with deeplinks back into the main map. |

## Quick stats

- Flagged edges: **{qc_out.get('flagged_edges', '?')}**
- Tier distribution: {qc_out.get('tier_counts', {})}
- Top issue distribution: {qc_out.get('top_issue_counts', {})}
- Flagged nodes: **{qc_out.get('flagged_nodes', '?')}**
- Boundary nodes (coverage gaps): **{qc_out.get('boundary_nodes', '?')}**
- p25 / p75 severity (flagged): {qc_out.get('severity_p25_flagged', '?')} / {qc_out.get('severity_p75_flagged', '?')}

## Severity tiers

Computed from percentiles **of flagged edges only**:

- **green**  : composite_severity < p25
- **orange** : p25 <= composite_severity < p75
- **red**    : composite_severity >= p75

## Top issue codes

- `jump_up`             - this edge has an upstream pair flag (predecessor has very different TVr)
- `jump_down`           - this edge has a downstream pair flag (successor has very different TVr)
- `node_in_imbalance`   - this edge's origin junction is unbalanced
- `node_out_imbalance`  - this edge's terminus junction is unbalanced

## How to use

1. Open `discontinuity_map.html` in any modern browser.
2. Use sidebar filters to narrow down by tier, FC, top_issue, or minimum severity.
3. Click an edge to see all properties; "Copier" copies the `agregId` to clipboard.
4. For tabular review, open `discontinuity_edges.geojson` in QGIS and `discontinuity_nodes.csv` in Excel.

## Methodology

See `../00_METHODOLOGY.md` for the full specification. Pipeline applies the
6-band flow-tiered grid, degree-scaled node thresholds, and the anti-double-count
rule from the expert reviews 01/02/03/05.
"""
    p = out_dir / "README.md"
    p.write_text(readme, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    t_start = time.perf_counter()

    gdf, qc = stage1_load(args.src, sample=args.sample)
    edges = stage2_build_edges(gdf)
    edges = stage3_adjacency(edges)
    pairs = stage4_pairs(edges)
    nodes = stage5_nodes(edges)
    edges, p25, p75 = stage6_composite(edges, pairs, nodes)
    paths, flagged_gdf, qc_out = stage7_export(edges, nodes, qc, args.out, p25, p75)
    bad_nodes_df = nodes.loc[nodes["is_bad"]].copy()
    html_paths = stage8_html(flagged_gdf, bad_nodes_df, p25, p75, args.out)
    paths.update(html_paths)
    readme = write_readme(args.out, qc_out)
    paths["readme"] = readme

    total = time.perf_counter() - t_start
    log.info("=== DONE in %.2fs ===", total)
    log.info("Outputs in: %s", args.out)
    for k, p in paths.items():
        log.info("  %-18s %s", k, p)

    # Final summary table
    print()
    print("=" * 72)
    print("QC SUMMARY")
    print("=" * 72)
    print(f"  Input rows               : {qc_out['n_rows_in']:>10}")
    print(f"  Rows kept                : {qc_out['n_rows_kept']:>10}")
    print(f"  Total edges (post graph) : {qc_out['total_edges']:>10}")
    print(f"  Flagged edges            : {qc_out['flagged_edges']:>10}")
    print(f"  Tier counts              : {qc_out['tier_counts']}")
    print(f"  Top issue counts         : {qc_out['top_issue_counts']}")
    print(f"  Total nodes              : {qc_out['total_nodes']:>10}")
    print(f"  Boundary nodes           : {qc_out['boundary_nodes']:>10}")
    print(f"  Flagged nodes            : {qc_out['flagged_nodes']:>10}")
    print(f"  p25 / p75 severity       : {qc_out['severity_p25_flagged']:.2f} / "
          f"{qc_out['severity_p75_flagged']:.2f}")
    print(f"  Runtime                  : {total:.2f}s")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
