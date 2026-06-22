"""
build_node_causality.py
=======================

For each node flagged by the user rule in ``discontinuity_nodes_simple.csv``,
attribute a dominant cause category by joining HERE 2025 edges (`2025.geojson`)
with the TV-model FCD inputs (`FCDREFGLOBAL_2025.parquet`).

Inputs
------
- outputs/discontinuity_nodes_simple.csv
- Travaux_donnees_Lyon/Livrables/2025.geojson
- Travaux_donnees_Lyon/Livrables/FCDREFGLOBAL/FCDREFGLOBAL_2025.parquet

Cause categories (priority order):
1. FCD_TV_cliff       - TMJOFCDTV jumps >=50 % across the node's edges
2. FCD_PL_cliff       - same for TMJOFCDPL
3. FC_transition      - FUNC_CLASS spans >=2 levels between in/out sets
4. RAMP_asymmetry     - RAMP flag differs between in and out
5. ROUNDABOUT_asymmetry - ROUNDABOUT flag differs between in and out
6. Distance_anomaly   - one of (avg_distance_before_m, avg_min_distance_m,
                        truck_avg_*) varies by >50 % across the node's edges
7. Coverage_gap       - any edge has TMJOFCDTV<1 OR TMJOFCDPL<0.5
8. Multi_factor       - >=2 of the above apply
9. Unexplained        - none of the above triggered

Outputs
-------
- outputs/nodes_with_cause.csv
- outputs/nodes_with_cause.json  (FeatureCollection of node points)

Run
---
    python scripts/discontinuity_methodology/build_node_causality.py
"""

from __future__ import annotations

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
# Paths / constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "outputs"

NODES_CSV = OUT_DIR / "discontinuity_nodes_simple.csv"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
GEOJSON_SRC = (
    DATA_ROOT / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables" / "2025.geojson"
)
PARQUET_SRC = (
    DATA_ROOT
    / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables"
    / "FCDREFGLOBAL" / "FCDREFGLOBAL_2025.parquet"
)

CSV_OUT = OUT_DIR / "nodes_with_cause.csv"
JSON_OUT = OUT_DIR / "nodes_with_cause.json"

# Thresholds (per spec)
FCD_TV_JUMP_RATIO = 1.50         # >=50 % cliff
FCD_PL_JUMP_RATIO = 1.50
DISTANCE_JUMP_RATIO = 1.50       # >50 %
FC_GAP_DELTA = 2                 # FC apart >=2 levels
TMJOFCDTV_ZERO_THRESHOLD = 1.0   # essentially zero
TMJOFCDPL_ZERO_THRESHOLD = 0.5

DISTANCE_COLS = [
    "avg_distance_before_m",
    "avg_min_distance_m",
    "truck_avg_distance_m",
    "truck_avg_min_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_distance_after_m",
]

CAUSE_PRIORITY = [
    "FCD_TV_cliff",
    "FCD_PL_cliff",
    "FC_transition",
    "RAMP_asymmetry",
    "ROUNDABOUT_asymmetry",
    "Distance_anomaly",
    "Coverage_gap",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("node_causality")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_ratio(arr: np.ndarray) -> float:
    """Return max/min where min>0; otherwise +inf if some max>0; else 0."""
    valid = arr[np.isfinite(arr) & (arr > 0)]
    if valid.size == 0:
        return 0.0
    mx = float(valid.max())
    mn = float(valid.min())
    if mn <= 0:
        return float("inf") if mx > 0 else 0.0
    return mx / mn


def _has_any(arr: np.ndarray) -> bool:
    return bool(arr.size > 0 and np.isfinite(arr).any())


# ---------------------------------------------------------------------------
# Stage 1 - Load edges with directed adjacency + parquet inputs
# ---------------------------------------------------------------------------

def load_edges() -> pd.DataFrame:
    """Load 2025.geojson, derive in_node/out_node per FINAL methodology,
    then enrich with FCD/model inputs from the parquet via segment_id == agregId.
    """
    t0 = time.perf_counter()
    log.info("S1. Loading edges from %s", GEOJSON_SRC.name)
    gdf = gpd.read_file(GEOJSON_SRC, engine="pyogrio")
    log.info("    %d features loaded", len(gdf))

    # Clean endpoints
    gdf["REF_IN_ID"] = pd.to_numeric(gdf["REF_IN_ID"], errors="coerce")
    gdf["NREF_IN_ID"] = pd.to_numeric(gdf["NREF_IN_ID"], errors="coerce")
    mask = gdf["REF_IN_ID"].notna() & gdf["NREF_IN_ID"].notna() & \
        (gdf["REF_IN_ID"] != gdf["NREF_IN_ID"])
    gdf = gdf.loc[mask].drop_duplicates(subset="agregId", keep="first").copy()
    gdf["REF_IN_ID"] = gdf["REF_IN_ID"].astype("int64")
    gdf["NREF_IN_ID"] = gdf["NREF_IN_ID"].astype("int64")

    # dir_class from agregId suffix
    suffix = gdf["agregId"].str.extract(r"-([FT])$", expand=False)
    is_T = (suffix == "T").fillna(False).to_numpy()
    gdf["in_node"] = np.where(is_T,
                              gdf["NREF_IN_ID"].to_numpy(),
                              gdf["REF_IN_ID"].to_numpy()).astype("int64")
    gdf["out_node"] = np.where(is_T,
                               gdf["REF_IN_ID"].to_numpy(),
                               gdf["NREF_IN_ID"].to_numpy()).astype("int64")

    # Keep just the columns we'll need + segment_id key
    edges = pd.DataFrame({
        "segment_id": gdf["agregId"].astype(str).to_numpy(),
        "in_node": gdf["in_node"].to_numpy(),
        "out_node": gdf["out_node"].to_numpy(),
        "TVr": pd.to_numeric(gdf["TVr"], errors="coerce").to_numpy(),
        "FC_geo": pd.to_numeric(gdf["FC"], errors="coerce").to_numpy(),
        "RAMP_geo": gdf["RAMP"].astype(str).str.upper().to_numpy(),
        "ROUNDABOUT_geo": gdf["ROUNDABOUT"].astype(str).str.upper().to_numpy(),
    })

    log.info("    %d edges after dedup/clean", len(edges))

    # ---- Enrich with parquet (TV-model inputs) ----
    log.info("S1b. Loading parquet inputs ...")
    par_cols = [
        "segment_id",
        "TMJOFCDTV", "TMJOFCDPL",
        "functional_class", "RAMP", "ROUNDABOUT",
    ] + DISTANCE_COLS
    par = pd.read_parquet(PARQUET_SRC, columns=par_cols)
    par["segment_id"] = par["segment_id"].astype(str)
    log.info("    %d parquet rows", len(par))

    edges = edges.merge(par, on="segment_id", how="left")
    log.info("    merged: %d rows; missing TMJOFCDTV=%d",
             len(edges), int(edges["TMJOFCDTV"].isna().sum()))

    log.info("    S1 done in %.2fs", time.perf_counter() - t0)
    return edges


# ---------------------------------------------------------------------------
# Stage 2 - For each node, find incoming + outgoing edges, classify cause
# ---------------------------------------------------------------------------

def classify_node(
    node_id: int,
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
) -> Dict:
    """Return cause + KPI summary + edge lists for one node."""
    all_edges = pd.concat([in_edges, out_edges], ignore_index=True) \
        if (len(in_edges) or len(out_edges)) else in_edges.iloc[0:0]

    triggered: List[str] = []
    kpi: Dict[str, float] = {}

    # --- 1) FCD_TV_cliff -----------------------------------------------------
    tv_arr = all_edges["TMJOFCDTV"].to_numpy(dtype=np.float64)
    tv_arr = tv_arr[np.isfinite(tv_arr)]
    if tv_arr.size >= 2:
        tv_ratio = _safe_ratio(tv_arr)
        if tv_ratio >= FCD_TV_JUMP_RATIO + 1e-9 and tv_arr.max() >= 1.0:
            triggered.append("FCD_TV_cliff")
            kpi["TMJOFCDTV_min"] = round(float(tv_arr.min()), 3)
            kpi["TMJOFCDTV_max"] = round(float(tv_arr.max()), 3)
            kpi["TMJOFCDTV_ratio"] = round(tv_ratio, 2) if np.isfinite(tv_ratio) else None

    # --- 2) FCD_PL_cliff -----------------------------------------------------
    pl_arr = all_edges["TMJOFCDPL"].to_numpy(dtype=np.float64)
    pl_arr = pl_arr[np.isfinite(pl_arr)]
    if pl_arr.size >= 2:
        pl_ratio = _safe_ratio(pl_arr)
        if pl_ratio >= FCD_PL_JUMP_RATIO + 1e-9 and pl_arr.max() >= 0.5:
            triggered.append("FCD_PL_cliff")
            kpi["TMJOFCDPL_min"] = round(float(pl_arr.min()), 3)
            kpi["TMJOFCDPL_max"] = round(float(pl_arr.max()), 3)
            kpi["TMJOFCDPL_ratio"] = round(pl_ratio, 2) if np.isfinite(pl_ratio) else None

    # --- 3) FC_transition ----------------------------------------------------
    # Use functional_class from parquet (canonical); fallback on FC from geojson.
    fc_in = pd.to_numeric(in_edges["functional_class"], errors="coerce").dropna()
    fc_out = pd.to_numeric(out_edges["functional_class"], errors="coerce").dropna()
    if fc_in.empty:
        fc_in = pd.to_numeric(in_edges["FC_geo"], errors="coerce").dropna()
    if fc_out.empty:
        fc_out = pd.to_numeric(out_edges["FC_geo"], errors="coerce").dropna()
    if len(fc_in) and len(fc_out):
        fc_set = pd.concat([fc_in, fc_out])
        fc_min = int(fc_set.min())
        fc_max = int(fc_set.max())
        if (fc_max - fc_min) >= FC_GAP_DELTA:
            triggered.append("FC_transition")
            kpi["FC_min"] = fc_min
            kpi["FC_max"] = fc_max
            kpi["FC_delta"] = fc_max - fc_min

    # --- 4) RAMP_asymmetry ---------------------------------------------------
    def _has_y(s: pd.Series) -> bool:
        if s.empty:
            return False
        return bool(s.astype(str).str.upper().eq("Y").any())

    in_ramp = _has_y(in_edges["RAMP_geo"]) if not in_edges.empty else False
    out_ramp = _has_y(out_edges["RAMP_geo"]) if not out_edges.empty else False
    if in_edges.empty is False and out_edges.empty is False and (in_ramp != out_ramp):
        triggered.append("RAMP_asymmetry")
        kpi["RAMP_in"] = "Y" if in_ramp else "N"
        kpi["RAMP_out"] = "Y" if out_ramp else "N"

    # --- 5) ROUNDABOUT_asymmetry --------------------------------------------
    in_rb = _has_y(in_edges["ROUNDABOUT_geo"]) if not in_edges.empty else False
    out_rb = _has_y(out_edges["ROUNDABOUT_geo"]) if not out_edges.empty else False
    if in_edges.empty is False and out_edges.empty is False and (in_rb != out_rb):
        triggered.append("ROUNDABOUT_asymmetry")
        kpi["ROUNDABOUT_in"] = "Y" if in_rb else "N"
        kpi["ROUNDABOUT_out"] = "Y" if out_rb else "N"

    # --- 6) Distance_anomaly -------------------------------------------------
    dist_anomaly_col = None
    dist_ratio_val = 0.0
    dist_min = dist_max = None
    for col in DISTANCE_COLS:
        if col not in all_edges.columns:
            continue
        arr = all_edges[col].to_numpy(dtype=np.float64)
        arr = arr[np.isfinite(arr) & (arr > 0)]
        if arr.size < 2:
            continue
        r = arr.max() / arr.min()
        if r > (DISTANCE_JUMP_RATIO + 1e-9) and r > dist_ratio_val:
            dist_ratio_val = r
            dist_anomaly_col = col
            dist_min = float(arr.min())
            dist_max = float(arr.max())
    if dist_anomaly_col is not None:
        triggered.append("Distance_anomaly")
        kpi["distance_col"] = dist_anomaly_col
        kpi["distance_min"] = round(dist_min, 1)
        kpi["distance_max"] = round(dist_max, 1)
        kpi["distance_ratio"] = round(dist_ratio_val, 2)

    # --- 7) Coverage_gap -----------------------------------------------------
    n_zero_tv = int(
        ((all_edges["TMJOFCDTV"].fillna(0.0) < TMJOFCDTV_ZERO_THRESHOLD)).sum()
    )
    n_zero_pl = int(
        ((all_edges["TMJOFCDPL"].fillna(0.0) < TMJOFCDPL_ZERO_THRESHOLD)).sum()
    )
    n_zero = int(
        (
            (all_edges["TMJOFCDTV"].fillna(0.0) < TMJOFCDTV_ZERO_THRESHOLD)
            | (all_edges["TMJOFCDPL"].fillna(0.0) < TMJOFCDPL_ZERO_THRESHOLD)
        ).sum()
    )
    if n_zero >= 1 and len(all_edges) > 0:
        triggered.append("Coverage_gap")
        kpi["edges_with_fcd_zero"] = n_zero
        kpi["edges_with_tv_zero"] = n_zero_tv
        kpi["edges_with_pl_zero"] = n_zero_pl

    # --- Reduce to dominant cause -------------------------------------------
    if len(triggered) == 0:
        cause = "Unexplained"
    elif len(triggered) >= 2:
        cause = "Multi_factor"
        kpi["factors"] = ",".join(sorted(triggered, key=CAUSE_PRIORITY.index))
    else:
        cause = triggered[0]

    return {
        "cause": cause,
        "kpi": kpi,
        "triggered_count": len(triggered),
        "triggered_list": triggered,
    }


def build_cause_rows(nodes_df: pd.DataFrame,
                     edges: pd.DataFrame) -> pd.DataFrame:
    """Iterate the 5314 nodes and build one row per node."""
    t0 = time.perf_counter()
    log.info("S2. Classifying %d nodes ...", len(nodes_df))

    # Pre-group edges by node side for O(1) lookup
    by_in = dict(tuple(edges.groupby("in_node")))   # edges LEAVING this node
    by_out = dict(tuple(edges.groupby("out_node")))  # edges ARRIVING at this node

    empty = edges.iloc[0:0]
    out_rows: List[Dict] = []
    node_ids = nodes_df["node_id"].to_numpy()
    lats = nodes_df["lat"].to_numpy()
    lons = nodes_df["lon"].to_numpy()
    n_in_orig = nodes_df["n_in"].to_numpy()
    n_out_orig = nodes_df["n_out"].to_numpy()
    in_flow_orig = nodes_df["in_flow"].to_numpy()
    out_flow_orig = nodes_df["out_flow"].to_numpy()
    ecart_orig = nodes_df["ecart"].to_numpy()

    for i, node_id in enumerate(node_ids):
        in_edges = by_out.get(int(node_id), empty)   # edges that END here -> incoming
        out_edges = by_in.get(int(node_id), empty)   # edges that START here -> outgoing

        # Build edge id lists for the row
        in_list = [
            {"agregId": s, "TVr": (float(v) if pd.notna(v) else None)}
            for s, v in zip(in_edges["segment_id"], in_edges["TVr"])
        ]
        out_list = [
            {"agregId": s, "TVr": (float(v) if pd.notna(v) else None)}
            for s, v in zip(out_edges["segment_id"], out_edges["TVr"])
        ]

        cls = classify_node(int(node_id), in_edges, out_edges)
        row = {
            "node_id": int(node_id),
            "lat": float(lats[i]),
            "lon": float(lons[i]),
            "n_in": int(n_in_orig[i]),
            "n_out": int(n_out_orig[i]),
            "in_flow": float(in_flow_orig[i]),
            "out_flow": float(out_flow_orig[i]),
            "ecart": float(ecart_orig[i]),
            "cause": cls["cause"],
            "triggered_count": cls["triggered_count"],
            "triggered_list": "|".join(cls["triggered_list"]),
            "kpi_summary": json.dumps(cls["kpi"], ensure_ascii=False),
            "in_edges": json.dumps(in_list, ensure_ascii=False),
            "out_edges": json.dumps(out_list, ensure_ascii=False),
        }
        out_rows.append(row)

        if (i + 1) % 1000 == 0:
            log.info("    %d / %d nodes processed", i + 1, len(node_ids))

    df = pd.DataFrame(out_rows)
    log.info("    S2 done in %.2fs", time.perf_counter() - t0)
    return df


# ---------------------------------------------------------------------------
# Stage 3 - Exports
# ---------------------------------------------------------------------------

def write_outputs(df: pd.DataFrame) -> Tuple[Path, Path]:
    t0 = time.perf_counter()
    log.info("S3. Writing outputs ...")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_OUT, index=False)
    log.info("    wrote %s (%d rows, %.1f KB)",
             CSV_OUT.name, len(df), CSV_OUT.stat().st_size / 1024)

    features = []
    for _, r in df.iterrows():
        try:
            kpi = json.loads(r["kpi_summary"]) if r["kpi_summary"] else {}
        except json.JSONDecodeError:
            kpi = {}
        kpi_str = "; ".join(f"{k}={v}" for k, v in kpi.items())
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(float(r["lon"]), 5),
                                round(float(r["lat"]), 5)],
            },
            "properties": {
                "node_id": int(r["node_id"]),
                "cause": r["cause"],
                "triggered_count": int(r["triggered_count"]),
                "triggered_list": r["triggered_list"],
                "n_in": int(r["n_in"]),
                "n_out": int(r["n_out"]),
                "in_flow": float(r["in_flow"]),
                "out_flow": float(r["out_flow"]),
                "ecart": float(r["ecart"]),
                "kpi_summary": kpi_str,
            },
        })
    fc = {"type": "FeatureCollection", "features": features}
    JSON_OUT.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    log.info("    wrote %s (%d features, %.1f KB)",
             JSON_OUT.name, len(features), JSON_OUT.stat().st_size / 1024)

    log.info("    S3 done in %.2fs", time.perf_counter() - t0)
    return CSV_OUT, JSON_OUT


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t_start = time.perf_counter()
    log.info("Reading nodes from %s", NODES_CSV)
    nodes_df = pd.read_csv(NODES_CSV)
    log.info("    %d nodes to classify", len(nodes_df))

    edges = load_edges()
    df = build_cause_rows(nodes_df, edges)
    csv_path, json_path = write_outputs(df)

    # ---- QC report -----------------------------------------------------------
    total = len(df)
    dist = df["cause"].value_counts(dropna=False)
    log.info("")
    log.info("CAUSE DISTRIBUTION")
    log.info("=" * 60)
    for cause, n in dist.items():
        log.info("    %-22s %5d (%5.1f %%)", cause, int(n), 100.0 * n / total)
    log.info("=" * 60)

    # Top 10 worst (by ecart) with cause + kpi
    top10 = df.sort_values("ecart", ascending=False).head(10)
    log.info("")
    log.info("TOP 10 WORST NODES (by |ecart|)")
    log.info("=" * 80)
    for _, r in top10.iterrows():
        log.info("  node=%-12d ecart=%8.0f cause=%-20s kpi=%s",
                 int(r["node_id"]), float(r["ecart"]),
                 r["cause"], r["kpi_summary"][:120])
    log.info("=" * 80)

    runtime = time.perf_counter() - t_start
    log.info("DONE in %.2fs", runtime)
    log.info("CSV  -> %s", csv_path)
    log.info("JSON -> %s", json_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
