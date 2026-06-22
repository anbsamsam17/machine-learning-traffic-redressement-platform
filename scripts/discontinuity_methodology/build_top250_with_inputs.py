"""Build top-250 TVr discontinuity dataset with TV model inputs on BOTH sides.

For each of the worst 250 inter-segment jumps (top_issue in jump_up/jump_down),
look up the 7 TV model inputs for both the central edge (E) and the worst
neighbor (N), so analysts can identify which input drives the predicted TVr
discontinuity.
"""
from __future__ import annotations
import os
import time
import re
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd

ROOT = Path(__file__).resolve().parent / "outputs"
EDGES = ROOT / "discontinuity_edges.geojson"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
FCD = (
    DATA_ROOT
    / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables"
    / "FCDREFGLOBAL" / "FCDREFGLOBAL_2025.parquet"
)
OUT = ROOT / "top250_discontinuities_with_inputs.csv"

INPUT_COLS = [
    "TMJOFCDTV", "TMJOFCDPL", "functional_class",
    "avg_distance_before_m", "avg_min_distance_m", "truck_avg_distance_before_m",
]


def main() -> int:
    t0 = time.time()

    print("[1/5] Loading discontinuity_edges.geojson ...")
    edges = gpd.read_file(EDGES)
    print(f"  {len(edges):,} flagged edges")
    print(f"  cols: {list(edges.columns)[:15]}...")

    # Filter top 250 by composite_severity, only inter-segment jumps
    is_jump = edges["top_issue"].isin(["jump_up", "jump_down"])
    sub = edges[is_jump].sort_values("composite_severity", ascending=False).head(250).reset_index(drop=True)
    print(f"  top 250 inter-segment jumps : severity range {sub['composite_severity'].min():.0f} .. {sub['composite_severity'].max():.0f}")

    print("[2/5] Loading 2025.geojson (for adjacency + TVr) ...")
    full_geo = DATA_ROOT / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables" / "2025.geojson"
    fcd = gpd.read_file(full_geo, columns=["agregId", "REF_IN_ID", "NREF_IN_ID", "TVr", "FC"])
    fcd["segment_id"] = fcd["agregId"].astype(str)
    print(f"  {len(fcd):,} segments")

    # Build dir_class + in_node/out_node + base_id
    print("[3/5] Building directed adjacency ...")
    fcd["dir_class"] = np.where(fcd["segment_id"].str.endswith("-F"), "F",
                       np.where(fcd["segment_id"].str.endswith("-T"), "T", "O"))
    fcd["base_id"] = fcd["segment_id"].str.replace(r"-[FT]$", "", regex=True)
    fcd["in_node"]  = np.where(fcd["dir_class"] == "T", fcd["NREF_IN_ID"], fcd["REF_IN_ID"]).astype("int64")
    fcd["out_node"] = np.where(fcd["dir_class"] == "T", fcd["REF_IN_ID"], fcd["NREF_IN_ID"]).astype("int64")

    # Join TV model inputs from FCDREFGLOBAL_2025.parquet
    print("[4/5] Loading TV model inputs from FCDREFGLOBAL_2025.parquet ...")
    inputs = pd.read_parquet(FCD, columns=["segment_id", "TMJOFCDTV", "TMJOFCDPL", "functional_class",
                                            "avg_distance_before_m", "avg_min_distance_m", "truck_avg_distance_before_m"])
    inputs["segment_id"] = inputs["segment_id"].astype(str)
    print(f"  {len(inputs):,} input rows")
    fcd = fcd.merge(inputs, on="segment_id", how="left")
    print(f"  joined : {len(fcd):,} (NaN on TMJOFCDTV : {fcd['TMJOFCDTV'].isna().sum()})")

    # Build neighbor lookups: for any node n in direction d:
    #   leaving[n,d] = list of segment_ids whose in_node == n
    #   arriving[n,d] = list of segment_ids whose out_node == n
    leaving: dict[tuple[int, str], list[str]] = {}
    arriving: dict[tuple[int, str], list[str]] = {}
    for sid, dc, in_n, out_n in zip(fcd["segment_id"], fcd["dir_class"], fcd["in_node"], fcd["out_node"]):
        leaving.setdefault((int(in_n), dc), []).append(sid)
        arriving.setdefault((int(out_n), dc), []).append(sid)
    print(f"  adjacency built (in_node entries: {len(leaving):,}, out_node entries: {len(arriving):,})")

    # Quick lookup by segment_id (use to_dict for speed instead of geopandas slicing)
    fcd_dict = fcd.drop(columns="geometry", errors="ignore").set_index("segment_id").to_dict("index")

    # Geometry lookup for centroids (separate to avoid dict bloat)
    geom_by_sid = dict(zip(fcd["segment_id"], fcd.geometry))

    print("[5/5] Processing 250 cases ...")
    rows = []
    for i, r in enumerate(sub.itertuples(), 1):
        e_sid = str(r.agregId)
        e = fcd_dict.get(e_sid)
        if e is None:
            continue
        dc = e["dir_class"]
        base_e = e["base_id"]
        # Find worst neighbor on the side indicated by top_issue
        if r.top_issue == "jump_up":
            candidates = arriving.get((int(e["in_node"]), dc), [])
        else:
            candidates = leaving.get((int(e["out_node"]), dc), [])
        candidates = [c for c in candidates if c != e_sid and fcd_dict[c]["base_id"] != base_e]
        if not candidates:
            continue
        tvr_e = float(e["TVr"])
        worst_sid = max(candidates, key=lambda c: abs(tvr_e - float(fcd_dict[c]["TVr"])))
        n = fcd_dict[worst_sid]
        tvr_n = float(n["TVr"])

        geom = geom_by_sid.get(e_sid)
        if geom is not None and hasattr(geom, "centroid"):
            c = geom.centroid
            lat, lon = c.y, c.x
        else:
            lat, lon = None, None

        row = {
            "rank": i,
            "composite_severity": float(r.composite_severity),
            "top_issue": r.top_issue,
            "agregId_E": e_sid,
            "agregId_N": worst_sid,
            "dir_class": dc,
            "TVr_E": tvr_e,
            "TVr_N": tvr_n,
            "delta_TVr": tvr_e - tvr_n,
            "delta_TVr_abs": abs(tvr_e - tvr_n),
            "delta_TVr_pct": 100 * abs(tvr_e - tvr_n) / max(tvr_e, tvr_n, 1),
            "lat": lat,
            "lon": lon,
        }
        deltas = {}
        for ic in INPUT_COLS:
            v_e = float(e[ic]) if pd.notna(e[ic]) else np.nan
            v_n = float(n[ic]) if pd.notna(n[ic]) else np.nan
            row[f"{ic}_E"] = v_e
            row[f"{ic}_N"] = v_n
            d = v_e - v_n
            row[f"delta_{ic}"] = d
            denom = max(abs(v_e), abs(v_n), 1)
            d_pct = 100.0 * d / denom
            row[f"delta_{ic}_pct"] = d_pct
            deltas[ic] = abs(d_pct)

        # Determine dominant input (largest |delta_<input>_pct| if >5%, else "none_significant")
        if max(deltas.values()) >= 5.0:
            row["dominant_input"] = max(deltas, key=deltas.get)
        else:
            row["dominant_input"] = "none_significant"
        rows.append(row)

    df = pd.DataFrame(rows)
    print(f"\n  Built {len(df)} rows.")
    df.to_csv(OUT, index=False)
    print(f"  -> {OUT.name}")

    # Quick stats
    print("\n=== Dominant input distribution ===")
    print(df["dominant_input"].value_counts().to_string())

    print("\n=== Top 5 cases ===")
    cols_show = ["rank", "agregId_E", "agregId_N", "TVr_E", "TVr_N", "delta_TVr", "composite_severity", "dominant_input"]
    print(df[cols_show].head(5).to_string(index=False))

    print(f"\n=== Stats delta_TVr_abs ===")
    print(f"  mean   : {df['delta_TVr_abs'].mean():.1f}")
    print(f"  median : {df['delta_TVr_abs'].median():.1f}")
    print(f"  max    : {df['delta_TVr_abs'].max():.0f}")

    print(f"\nDone in {time.time()-t0:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
