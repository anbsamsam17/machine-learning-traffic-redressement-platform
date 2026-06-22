"""
build_node_causality_v2.py
==========================

V2 of the node-cause builder.

For each of the 5 314 flagged nodes (from ``discontinuity_nodes_simple.csv``)
this script now exposes **per-edge input values** so the analyst can see, for
every input variable, the value on EACH incoming/outgoing road segment
(E1/E2/E3, S1/S2/S3) instead of just an aggregated ratio.

The 6 input variables that are exposed (year_mapped is excluded — constant=7):

    TMJOFCDTV                     Trafic VL (TMJO FCD VL)            v/j
    TMJOFCDPL                     Trafic PL (TMJO FCD PL)            v/j
    functional_class              Classe fonctionnelle (FC, 1-5)     -
    avg_distance_before_m         Distance moyenne avant             m
    avg_min_distance_m            Distance minimale                  m
    truck_avg_distance_before_m   Distance moyenne PL avant          m

Outputs
-------
- outputs/nodes_with_cause_v2.json   FeatureCollection of 5314 points + metadata
- outputs/nodes_with_cause_v2.csv    Flat one-row-per-node QA companion

Run
---
    python scripts/discontinuity_methodology/build_node_causality_v2.py
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

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

CSV_OUT = OUT_DIR / "nodes_with_cause_v2.csv"
JSON_OUT = OUT_DIR / "nodes_with_cause_v2.json"

VERSION = "v2"
GENERATED_AT = "2026-05-22"

# ---------------------------------------------------------------------------
# Input dictionary (the 6 variables surfaced to the analyst)
# ---------------------------------------------------------------------------

# Order matters: this is the canonical column order in edge.inputs
INPUT_COLS: Tuple[str, ...] = (
    "TMJOFCDTV",
    "TMJOFCDPL",
    "functional_class",
    "avg_distance_before_m",
    "avg_min_distance_m",
    "truck_avg_distance_before_m",
)

INPUT_LABELS = {
    "TMJOFCDTV":                   "Trafic VL (TMJO FCD VL)",
    "TMJOFCDPL":                   "Trafic PL (TMJO FCD PL)",
    "functional_class":            "Classe fonctionnelle (FC)",
    "avg_distance_before_m":       "Distance moyenne avant (m)",
    "avg_min_distance_m":          "Distance minimale (m)",
    "truck_avg_distance_before_m": "Distance moyenne PL avant (m)",
}

INPUT_UNITS = {
    "TMJOFCDTV":                   "v/j",
    "TMJOFCDPL":                   "v/j",
    "functional_class":            "",
    "avg_distance_before_m":       "m",
    "avg_min_distance_m":          "m",
    "truck_avg_distance_before_m": "m",
}

CAUSE_LABELS_FR = {
    "FCD_TV_cliff":         "Falaise FCD VL",
    "FCD_PL_cliff":         "Falaise FCD PL",
    "Coverage_gap":         "Trou de couverture FCD",
    "Distance_anomaly":     "Anomalie de distance",
    "RAMP_asymmetry":       "Bretelle asymetrique",
    "ROUNDABOUT_asymmetry": "Rond-point asymetrique",
    "FC_transition":        "Transition de classe fonctionnelle (legitime)",
    "Multi_factor":         "Causes multiples",
    "Unexplained":          "Inexplique (a investiguer)",
}

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

RATIO_THRESHOLD = 1.5            # for TV / PL / distances
FC_DELTA_THRESHOLD = 2           # FC jump of >=2 levels = strong signal
TMJOFCDTV_ZERO = 1.0
TMJOFCDPL_ZERO = 0.5

CAUSE_PRIORITY = [
    "FCD_TV_cliff",
    "FCD_PL_cliff",
    "FC_transition",
    "RAMP_asymmetry",
    "ROUNDABOUT_asymmetry",
    "Distance_anomaly",
    "Coverage_gap",
]

MAX_EDGES_PER_SIDE = 4           # cap displayed edges, append "(+N autres)"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("node_causality_v2")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(x: Any) -> Any:
    """JSON-safe float (None for NaN/inf)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _round(x: Any, ndigits: int = 1) -> Any:
    v = _f(x)
    return None if v is None else round(v, ndigits)


def _ratio(vals: np.ndarray) -> Tuple[float, float, float]:
    """Return (max, min_for_ratio, ratio). min is clamped to 1.0 to avoid div-by-0
    only for ratio computation (the reported min stays the true min)."""
    if vals.size == 0:
        return 0.0, 0.0, 0.0
    mx = float(vals.max())
    mn = float(vals.min())
    mn_safe = mn if mn > 0 else 1.0
    return mx, mn, mx / mn_safe


# ---------------------------------------------------------------------------
# Stage 1 - Load edges + parquet inputs
# ---------------------------------------------------------------------------

def load_edges() -> pd.DataFrame:
    t0 = time.perf_counter()
    log.info("S1. Loading edges from %s", GEOJSON_SRC.name)
    gdf = gpd.read_file(GEOJSON_SRC, engine="pyogrio")
    log.info("    %d features loaded", len(gdf))

    # Clean endpoints + dedup by agregId
    gdf["REF_IN_ID"] = pd.to_numeric(gdf["REF_IN_ID"], errors="coerce")
    gdf["NREF_IN_ID"] = pd.to_numeric(gdf["NREF_IN_ID"], errors="coerce")
    mask = (gdf["REF_IN_ID"].notna()
            & gdf["NREF_IN_ID"].notna()
            & (gdf["REF_IN_ID"] != gdf["NREF_IN_ID"]))
    gdf = gdf.loc[mask].drop_duplicates(subset="agregId", keep="first").copy()
    gdf["REF_IN_ID"] = gdf["REF_IN_ID"].astype("int64")
    gdf["NREF_IN_ID"] = gdf["NREF_IN_ID"].astype("int64")

    # Direction class from agregId suffix -F or -T
    suffix = gdf["agregId"].str.extract(r"-([FT])$", expand=False)
    is_T = (suffix == "T").fillna(False).to_numpy()
    gdf["in_node"] = np.where(is_T,
                              gdf["NREF_IN_ID"].to_numpy(),
                              gdf["REF_IN_ID"].to_numpy()).astype("int64")
    gdf["out_node"] = np.where(is_T,
                               gdf["REF_IN_ID"].to_numpy(),
                               gdf["NREF_IN_ID"].to_numpy()).astype("int64")

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

    # ---- Parquet inputs ----
    log.info("S1b. Loading parquet inputs ...")
    par_cols = ["segment_id", "RAMP", "ROUNDABOUT"] + list(INPUT_COLS)
    par = pd.read_parquet(PARQUET_SRC, columns=par_cols)
    par["segment_id"] = par["segment_id"].astype(str)
    log.info("    %d parquet rows", len(par))

    edges = edges.merge(par, on="segment_id", how="left")
    n_missing = int(edges["TMJOFCDTV"].isna().sum())
    log.info("    merged: %d rows; missing TMJOFCDTV=%d", len(edges), n_missing)
    log.info("    S1 done in %.2fs", time.perf_counter() - t0)
    return edges


# ---------------------------------------------------------------------------
# Stage 2 - Per-node classification with per-edge input values
# ---------------------------------------------------------------------------

def _edge_dict(row: pd.Series) -> Dict[str, Any]:
    """Build the per-edge JSON payload."""
    inputs: Dict[str, Any] = {}
    for col in INPUT_COLS:
        v = row.get(col)
        if pd.isna(v):
            inputs[col] = None
        elif col == "functional_class":
            try:
                inputs[col] = int(v)
            except (TypeError, ValueError):
                inputs[col] = None
        else:
            inputs[col] = _round(v, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1)
    return {
        "agregId": str(row["segment_id"]),
        "TVr": _round(row["TVr"], 1),
        "inputs": inputs,
    }


def _sort_and_label(edges_df: pd.DataFrame, side_prefix: str) -> Tuple[List[Dict[str, Any]], int]:
    """Sort edges by TVr desc, label E1..En or S1..Sn, cap to MAX_EDGES_PER_SIDE.

    Returns (list_of_edge_dicts, n_truncated).
    """
    if edges_df is None or len(edges_df) == 0:
        return [], 0
    sorted_df = edges_df.copy()
    # NaN TVr should sort last
    sorted_df["_tvr_sort"] = pd.to_numeric(sorted_df["TVr"], errors="coerce").fillna(-1.0)
    sorted_df = sorted_df.sort_values("_tvr_sort", ascending=False)

    n_total = len(sorted_df)
    head = sorted_df.head(MAX_EDGES_PER_SIDE)
    out_list: List[Dict[str, Any]] = []
    for i, (_, row) in enumerate(head.iterrows(), start=1):
        edge = _edge_dict(row)
        edge["label"] = f"{side_prefix}{i}"
        out_list.append(edge)
    n_extra = n_total - len(out_list)
    if n_extra > 0 and out_list:
        out_list[-1]["label"] = f"{out_list[-1]['label']} (+{n_extra} autres)"
    return out_list, n_extra


def _detect_drivers(
    all_edges: pd.DataFrame,
) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    """Run the 6-input driver detection rules. Returns (sorted_driver_keys, scores)."""
    scores: Dict[str, Dict[str, Any]] = {}

    for col in INPUT_COLS:
        arr_all = pd.to_numeric(all_edges[col], errors="coerce").to_numpy(dtype=np.float64)
        arr = arr_all[np.isfinite(arr_all)]
        if arr.size < 2:
            continue

        if col == "functional_class":
            mx = int(arr.max())
            mn = int(arr.min())
            delta = mx - mn
            if delta >= FC_DELTA_THRESHOLD:
                rank_score = delta * 5.0      # boost FC because it's categorical
                scores[col] = {
                    "max": mx,
                    "min": mn,
                    "delta": delta,
                    "rank_score": float(rank_score),
                }
        else:
            # Replace 0 with 1 for ratio math (spec: "after replacing 0 with 1 to avoid div by 0")
            arr_for_ratio = np.where(arr <= 0, 1.0, arr)
            mx_safe = float(arr_for_ratio.max())
            mn_safe = float(arr_for_ratio.min())
            ratio = mx_safe / mn_safe if mn_safe > 0 else 0.0
            if ratio >= RATIO_THRESHOLD:
                mx = float(arr.max())
                mn = float(arr.min())
                delta = mx - mn
                if col in ("TMJOFCDTV", "TMJOFCDPL"):
                    rank_score = ratio * math.log(mx + 1.0)
                else:
                    rank_score = ratio
                scores[col] = {
                    "max": _round(mx, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "min": _round(mn, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "ratio": round(ratio, 2),
                    "delta": _round(delta, 3 if col in ("TMJOFCDTV", "TMJOFCDPL") else 1),
                    "rank_score": float(rank_score),
                }

    ordered = sorted(scores.keys(), key=lambda k: -scores[k]["rank_score"])
    for rank, k in enumerate(ordered, start=1):
        scores[k]["rank"] = rank
        # rank_score is internal; expose only via "rank" + ratio/delta
        scores[k].pop("rank_score", None)

    return ordered, scores


def _detect_cause(
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
    drivers: List[str],
    scores: Dict[str, Dict[str, Any]],
) -> Tuple[str, List[str]]:
    """Map drivers + topology asymmetries to a cause label."""
    triggered: List[str] = []

    if "TMJOFCDTV" in drivers:
        triggered.append("FCD_TV_cliff")
    if "TMJOFCDPL" in drivers:
        triggered.append("FCD_PL_cliff")
    if "functional_class" in drivers:
        triggered.append("FC_transition")
    if any(k in drivers for k in (
            "avg_distance_before_m",
            "avg_min_distance_m",
            "truck_avg_distance_before_m")):
        triggered.append("Distance_anomaly")

    # Topology asymmetries (independent of drivers)
    def _has_y(s: pd.Series) -> bool:
        if s is None or s.empty:
            return False
        return bool(s.astype(str).str.upper().eq("Y").any())

    if (not in_edges.empty) and (not out_edges.empty):
        # RAMP - prefer parquet RAMP if available, fallback on geojson
        ramp_in = _has_y(in_edges["RAMP"]) if "RAMP" in in_edges else False
        ramp_out = _has_y(out_edges["RAMP"]) if "RAMP" in out_edges else False
        if not (ramp_in or ramp_out):
            ramp_in = _has_y(in_edges["RAMP_geo"])
            ramp_out = _has_y(out_edges["RAMP_geo"])
        if ramp_in != ramp_out:
            triggered.append("RAMP_asymmetry")

        rb_in = _has_y(in_edges["ROUNDABOUT"]) if "ROUNDABOUT" in in_edges else False
        rb_out = _has_y(out_edges["ROUNDABOUT"]) if "ROUNDABOUT" in out_edges else False
        if not (rb_in or rb_out):
            rb_in = _has_y(in_edges["ROUNDABOUT_geo"])
            rb_out = _has_y(out_edges["ROUNDABOUT_geo"])
        if rb_in != rb_out:
            triggered.append("ROUNDABOUT_asymmetry")

    # Coverage_gap
    all_edges = pd.concat([in_edges, out_edges], ignore_index=True) \
        if (len(in_edges) or len(out_edges)) else in_edges.iloc[0:0]
    if len(all_edges) > 0:
        tv = pd.to_numeric(all_edges["TMJOFCDTV"], errors="coerce").fillna(0.0)
        pl = pd.to_numeric(all_edges["TMJOFCDPL"], errors="coerce").fillna(0.0)
        if ((tv < TMJOFCDTV_ZERO) | (pl < TMJOFCDPL_ZERO)).any():
            triggered.append("Coverage_gap")

    # Reduce
    if len(triggered) == 0:
        cause = "Unexplained"
    elif len(triggered) >= 2:
        cause = "Multi_factor"
    else:
        cause = triggered[0]

    triggered_sorted = sorted(set(triggered), key=lambda c: CAUSE_PRIORITY.index(c)
                              if c in CAUSE_PRIORITY else 99)
    return cause, triggered_sorted


def _format_int(v: Any) -> str:
    if v is None:
        return "?"
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "?"


def _format_float1(v: Any) -> str:
    if v is None:
        return "?"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "?"


def _build_narrative(
    cause: str,
    drivers: List[str],
    scores: Dict[str, Dict[str, Any]],
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
    ecart: float,
) -> str:
    """Per-cause narrative using the actual driver values, never generic boilerplate."""
    if cause == "Unexplained":
        return "Aucun driver clair - investigation modele requise."

    # Common helpers
    def s(k: str) -> Dict[str, Any]:
        return scores.get(k, {})

    if cause == "FCD_TV_cliff":
        x = s("TMJOFCDTV")
        return (f"Saut FCD VL : max {_format_int(x.get('max'))} v/j "
                f"vs min {_format_int(x.get('min'))} v/j "
                f"(x{x.get('ratio', 0):.1f}).")

    if cause == "FCD_PL_cliff":
        x = s("TMJOFCDPL")
        return (f"Saut FCD PL : max {_format_int(x.get('max'))} v/j "
                f"vs min {_format_int(x.get('min'))} v/j "
                f"(x{x.get('ratio', 0):.1f}).")

    if cause == "FC_transition":
        x = s("functional_class")
        return (f"Changement de classe fonctionnelle FC "
                f"{x.get('min','?')}->{x.get('max','?')} (transition legitime).")

    if cause == "RAMP_asymmetry":
        return "Bretelle asymetrique entre branches (R=Y/N)."

    if cause == "ROUNDABOUT_asymmetry":
        return (f"Rond-point asymetrique (R=Y/N) avec ecart "
                f"{_format_int(ecart)} v/j.")

    if cause == "Distance_anomaly":
        # pick highest-ranked distance driver among the 3 distance cols
        for col in ("avg_distance_before_m", "avg_min_distance_m",
                    "truck_avg_distance_before_m"):
            if col in scores:
                x = scores[col]
                return (f"Anomalie sur {INPUT_LABELS[col]} : "
                        f"{_format_float1(x.get('max'))} m vs "
                        f"{_format_float1(x.get('min'))} m "
                        f"(x{x.get('ratio', 0):.1f}).")
        return "Anomalie de distance detectee."

    if cause == "Coverage_gap":
        return ("Couverture FCD insuffisante (>=1 segment avec "
                "TMJOFCDTV<1 ou TMJOFCDPL<0.5).")

    if cause == "Multi_factor":
        # use top 2-3 drivers with values
        parts: List[str] = []
        for k in drivers[:3]:
            x = scores[k]
            if k == "TMJOFCDTV":
                parts.append(f"{INPUT_LABELS[k]} (x{x.get('ratio', 0):.1f})")
            elif k == "TMJOFCDPL":
                parts.append(f"{INPUT_LABELS[k]} (x{x.get('ratio', 0):.1f})")
            elif k == "functional_class":
                parts.append(f"{INPUT_LABELS[k]} ({x.get('min')}->{x.get('max')})")
            else:
                parts.append(f"{INPUT_LABELS[k]} (x{x.get('ratio', 0):.1f})")
        if not parts:
            return f"Causes multiples avec ecart {_format_int(ecart)} v/j."
        return "Causes dominantes : " + " + ".join(parts) + "."

    return f"Cause : {cause}."


def classify_node(
    node_meta: Dict[str, Any],
    in_edges: pd.DataFrame,
    out_edges: pd.DataFrame,
) -> Dict[str, Any]:
    """Build the full v2 payload for one node."""
    all_edges = pd.concat([in_edges, out_edges], ignore_index=True) \
        if (len(in_edges) or len(out_edges)) else in_edges.iloc[0:0]

    drivers, driver_scores = _detect_drivers(all_edges)
    cause, _triggered = _detect_cause(in_edges, out_edges, drivers, driver_scores)

    edges_in_list, _ = _sort_and_label(in_edges, "E")
    edges_out_list, _ = _sort_and_label(out_edges, "S")

    narrative = _build_narrative(
        cause, drivers, driver_scores, in_edges, out_edges,
        float(node_meta.get("ecart", 0.0)),
    )

    return {
        "edges_in": edges_in_list,
        "edges_out": edges_out_list,
        "drivers": drivers,
        "driver_scores": driver_scores,
        "cause": cause,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# Stage 3 - Build the FeatureCollection
# ---------------------------------------------------------------------------

def _edges_summary(edges_list: List[Dict[str, Any]]) -> str:
    """Flat string for CSV: 'E1[TV=8100,PL=520,FC=1] | E2[...]'."""
    parts: List[str] = []
    for e in edges_list:
        tv = e["inputs"].get("TMJOFCDTV")
        pl = e["inputs"].get("TMJOFCDPL")
        fc = e["inputs"].get("functional_class")
        bits = []
        if tv is not None:
            bits.append(f"TV={int(round(tv))}" if isinstance(tv, (int, float)) else f"TV={tv}")
        if pl is not None:
            bits.append(f"PL={int(round(pl))}" if isinstance(pl, (int, float)) else f"PL={pl}")
        if fc is not None:
            bits.append(f"FC={fc}")
        parts.append(f"{e['label']}[{','.join(bits)}]")
    return " | ".join(parts)


def build_features(nodes_df: pd.DataFrame, edges: pd.DataFrame) -> Tuple[List[Dict[str, Any]], pd.DataFrame, Dict[str, Any]]:
    t0 = time.perf_counter()
    log.info("S2. Classifying %d nodes ...", len(nodes_df))

    # Pre-group edges (edges_starting_here = outgoing; edges_ending_here = incoming)
    by_in = dict(tuple(edges.groupby("in_node")))     # edges leaving each node
    by_out = dict(tuple(edges.groupby("out_node")))   # edges arriving at each node
    empty = edges.iloc[0:0]

    features: List[Dict[str, Any]] = []
    csv_rows: List[Dict[str, Any]] = []
    unmapped_nodes: List[int] = []  # nodes with no input data found

    node_ids = nodes_df["node_id"].to_numpy()

    for i, node_id in enumerate(node_ids):
        nid = int(node_id)
        row = nodes_df.iloc[i]

        in_edges = by_out.get(nid, empty)
        out_edges = by_in.get(nid, empty)

        node_meta = {
            "node_id": nid,
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "n_in": int(row["n_in"]),
            "n_out": int(row["n_out"]),
            "flow_in": float(row["in_flow"]),
            "flow_out": float(row["out_flow"]),
            "ecart": float(row["ecart"]),
            "tier": str(row["tier"]),
        }
        # Detect nodes that have edges but no parquet input at all
        n_inputs_present = 0
        if len(in_edges) + len(out_edges) > 0:
            all_e = pd.concat([in_edges, out_edges], ignore_index=True)
            n_inputs_present = int(
                pd.to_numeric(all_e["TMJOFCDTV"], errors="coerce").notna().sum()
                + pd.to_numeric(all_e["TMJOFCDPL"], errors="coerce").notna().sum()
            )
        if n_inputs_present == 0 and len(in_edges) + len(out_edges) > 0:
            unmapped_nodes.append(nid)

        cls = classify_node(node_meta, in_edges, out_edges)

        properties = {
            "node_id": str(nid),
            "lat": round(node_meta["lat"], 5),
            "lon": round(node_meta["lon"], 5),
            "ecart": round(node_meta["ecart"], 1),
            "flow_in": round(node_meta["flow_in"], 1),
            "flow_out": round(node_meta["flow_out"], 1),
            "cause": cls["cause"],
            "tier": node_meta["tier"],
            "narrative": cls["narrative"],
            "n_in": node_meta["n_in"],
            "n_out": node_meta["n_out"],
            "edges_in": cls["edges_in"],
            "edges_out": cls["edges_out"],
            "drivers": cls["drivers"],
            "driver_scores": cls["driver_scores"],
        }

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [round(node_meta["lon"], 5),
                                round(node_meta["lat"], 5)],
            },
            "properties": properties,
        })

        # CSV companion row
        csv_rows.append({
            "node_id": nid,
            "lat": node_meta["lat"],
            "lon": node_meta["lon"],
            "cause": cls["cause"],
            "tier": node_meta["tier"],
            "ecart": node_meta["ecart"],
            "n_in": node_meta["n_in"],
            "n_out": node_meta["n_out"],
            "drivers_top": ",".join(cls["drivers"]),
            "narrative": cls["narrative"],
            "edges_in_summary": _edges_summary(cls["edges_in"]),
            "edges_out_summary": _edges_summary(cls["edges_out"]),
        })

        if (i + 1) % 1000 == 0:
            log.info("    %d / %d nodes processed", i + 1, len(node_ids))

    csv_df = pd.DataFrame(csv_rows)

    diagnostics = {
        "unmapped_nodes": unmapped_nodes,
        "n_unmapped": len(unmapped_nodes),
    }

    log.info("    S2 done in %.2fs", time.perf_counter() - t0)
    return features, csv_df, diagnostics


# ---------------------------------------------------------------------------
# Stage 4 - Writers + QC
# ---------------------------------------------------------------------------

def write_outputs(
    features: List[Dict[str, Any]],
    csv_df: pd.DataFrame,
) -> Tuple[Path, Path, float, float]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    metadata = {
        "version": VERSION,
        "generated_at": GENERATED_AT,
        "n_nodes": len(features),
        "input_labels": INPUT_LABELS,
        "input_units": INPUT_UNITS,
        "cause_labels_fr": CAUSE_LABELS_FR,
    }
    fc = {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features,
    }
    JSON_OUT.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    csv_df.to_csv(CSV_OUT, index=False, encoding="utf-8")

    json_mb = JSON_OUT.stat().st_size / (1024 * 1024)
    csv_mb = CSV_OUT.stat().st_size / (1024 * 1024)
    log.info("    wrote %s (%.2f MB)", JSON_OUT.name, json_mb)
    log.info("    wrote %s (%.2f MB)", CSV_OUT.name, csv_mb)
    return JSON_OUT, CSV_OUT, json_mb, csv_mb


def qc_report(
    features: List[Dict[str, Any]],
    csv_df: pd.DataFrame,
    diagnostics: Dict[str, Any],
) -> None:
    log.info("")
    log.info("=" * 70)
    log.info("VALIDATION REPORT")
    log.info("=" * 70)
    log.info("Total nodes processed: %d", len(features))

    # Cause distribution
    causes = Counter(f["properties"]["cause"] for f in features)
    log.info("")
    log.info("Cause distribution:")
    for c, n in causes.most_common():
        log.info("    %-22s %5d (%5.1f %%)", c, n, 100.0 * n / len(features))

    # Driver-count distribution
    drv_count = Counter(len(f["properties"]["drivers"]) for f in features)
    log.info("")
    log.info("Driver-count distribution (len(drivers)):")
    for k in sorted(drv_count):
        log.info("    %d driver(s): %5d nodes (%5.1f %%)",
                 k, drv_count[k], 100.0 * drv_count[k] / len(features))

    # Top-10 worst nodes by ecart
    feats_sorted = sorted(features,
                          key=lambda f: f["properties"]["ecart"],
                          reverse=True)[:10]
    log.info("")
    log.info("Top-10 worst nodes (by ecart):")
    log.info("    %-12s %-10s %-22s %-50s",
             "node_id", "ecart", "cause", "drivers")
    for f in feats_sorted:
        p = f["properties"]
        log.info("    %-12s %-10.0f %-22s %s",
                 p["node_id"], p["ecart"], p["cause"],
                 ",".join(p["drivers"]) or "(none)")

    # Sanity checks
    log.info("")
    log.info("Sanity checks:")
    by_id = {f["properties"]["node_id"]: f for f in features}

    for nid_str, expected_cause in [
        ("611034076", "ROUNDABOUT"),
        ("82624234", "Multi_factor"),
    ]:
        if nid_str in by_id:
            p = by_id[nid_str]["properties"]
            log.info("    node %s -> n_in=%d n_out=%d cause=%s drivers=%s",
                     nid_str, p["n_in"], p["n_out"], p["cause"],
                     ",".join(p["drivers"]) or "(none)")
            if "driver_scores" in p:
                for k, sc in p["driver_scores"].items():
                    log.info("        %-25s -> %s", k, json.dumps(sc, ensure_ascii=False))
        else:
            log.info("    node %s NOT FOUND in output", nid_str)

    # Specific checks per spec
    log.info("")
    log.info("Spec verifications:")

    if "611034076" in by_id:
        p = by_id["611034076"]["properties"]
        ok_topo = (p["n_in"] == 3 and p["n_out"] == 1)
        ok_fc = "functional_class" in p["drivers"]
        log.info("    611034076: n_in=3 & n_out=1 -> %s", "OK" if ok_topo else "FAIL")
        log.info("    611034076: functional_class in drivers -> %s",
                 "OK" if ok_fc else "FAIL (drivers=%s)" % ",".join(p["drivers"]))

    if "82624234" in by_id:
        p = by_id["82624234"]["properties"]
        sc = p.get("driver_scores", {})
        tv_ratio = sc.get("TMJOFCDTV", {}).get("ratio")
        pl_ratio = sc.get("TMJOFCDPL", {}).get("ratio")
        fc = sc.get("functional_class", {})
        log.info("    82624234: TMJOFCDTV ratio=%s (expected ~25.5) -> %s",
                 tv_ratio, "OK" if (tv_ratio and tv_ratio >= 20.0) else "CHECK")
        log.info("    82624234: TMJOFCDPL ratio=%s (expected ~204) -> %s",
                 pl_ratio, "OK" if (pl_ratio and pl_ratio >= 150.0) else "CHECK")
        log.info("    82624234: FC %s->%s (expected 1->4) -> %s",
                 fc.get("min"), fc.get("max"),
                 "OK" if (fc.get("min") == 1 and fc.get("max") == 4) else "CHECK")

    # Unmapped nodes
    log.info("")
    log.info("Nodes with no parquet input found: %d",
             diagnostics["n_unmapped"])
    if diagnostics["n_unmapped"] > 0:
        sample = diagnostics["unmapped_nodes"][:10]
        log.info("    first 10: %s", sample)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t_start = time.perf_counter()

    log.info("Reading nodes from %s", NODES_CSV)
    nodes_df = pd.read_csv(NODES_CSV)
    log.info("    %d nodes to classify", len(nodes_df))

    edges = load_edges()
    features, csv_df, diagnostics = build_features(nodes_df, edges)
    json_path, csv_path, json_mb, csv_mb = write_outputs(features, csv_df)
    qc_report(features, csv_df, diagnostics)

    runtime = time.perf_counter() - t_start
    log.info("")
    log.info("=" * 70)
    log.info("DONE in %.2fs", runtime)
    log.info("JSON -> %s (%.2f MB)", json_path, json_mb)
    log.info("CSV  -> %s (%.2f MB)", csv_path, csv_mb)
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
