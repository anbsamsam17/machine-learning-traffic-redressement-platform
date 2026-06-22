"""Build FCDREFGLOBAL_2025 ready for MDL_Lyon_TV_Final + MDL_Lyon_PL_Final.

Steps:
  1) Read FCDREFGLOBAL_2025_GrandLyon_imputed.parquet (241857 segments).
  2) Rename 9 columns (3 simple + 6 with km->m conversion).
  3) Add 4 new columns: Annee, fcd_log, tv_pl_ratio, dist_to_lyon_center.
  4) Export to FCDREFGLOBAL_2025.parquet (and .geojson) in the Livrables folder.

TMJFCD definition (confirmed by user and verified empirically) :
    TMJFCDTV = (M01 + M09 + M10) / 3  (TV)
    TMJFCDPL = (M01 + M09 + M10) / 3  (Truck)
Same convention used at training time -> simple rename to TMJOFCDTV / TMJOFCDPL.

Distances converted km -> m to match the m-suffixed training columns.

dist_to_lyon_center : Haversine in km from the LINESTRING centroid to
Place Bellecour (45.7578° N, 4.8320° E).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
SRC_DIR = DATA_ROOT / "Travaux_donnees_Lyon" / "Livrables" / "FCDREFGLOBAL"
SRC_PARQUET = SRC_DIR / "FCDREFGLOBAL_2025_GrandLyon_imputed.parquet"
DST_PARQUET = SRC_DIR / "FCDREFGLOBAL_2025.parquet"
DST_GEOJSON = SRC_DIR / "FCDREFGLOBAL_2025.geojson"

# Lyon centre = Place Bellecour
LYON_LAT = 45.7578
LYON_LON = 4.8320
R_EARTH_KM = 6371.0

# 3 simple renames (no value change)
RENAME_SIMPLE = {
    "TMJFCDTV": "TMJOFCDTV",
    "TMJFCDPL": "TMJOFCDPL",
    "FUNC_CLASS": "functional_class",
}

# 6 renames + km->m conversion
RENAME_KM_TO_M = {
    "car_average_distance_before_km": "avg_distance_before_m",
    "car_min_average_distance_km":    "avg_min_distance_m",
    "truck_average_distance_km":      "truck_avg_distance_m",
    "truck_min_average_distance_km":  "truck_avg_min_distance_m",
    "truck_average_distance_before_km": "truck_avg_distance_before_m",
    "truck_average_distance_after_km":  "truck_avg_distance_after_m",
}


def haversine_km(lat1, lon1, lat2, lon2):
    p1 = np.radians(lat1)
    p2 = np.radians(lat2)
    dp = np.radians(lat2 - lat1)
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * R_EARTH_KM * np.arcsin(np.sqrt(a))


def main() -> int:
    t0 = time.time()
    print(f"Reading {SRC_PARQUET.name} ...", flush=True)
    gdf = gpd.read_parquet(SRC_PARQUET)
    print(f"  -> {len(gdf):,} rows, {len(gdf.columns)} cols, CRS={gdf.crs}", flush=True)

    # 1) simple renames
    print("Applying simple renames (3 cols)...", flush=True)
    gdf = gdf.rename(columns=RENAME_SIMPLE)

    # 2) km -> m renames + conversion
    print("Applying km -> m renames (6 cols)...", flush=True)
    for src, dst in RENAME_KM_TO_M.items():
        if src not in gdf.columns:
            raise ValueError(f"Source column missing: {src}")
        gdf[dst] = gdf[src] * 1000.0
        # drop the original km column to keep the schema clean
        gdf = gdf.drop(columns=[src])

    # 3) Add Annee = 2025
    gdf["Annee"] = 2025

    # 4) fcd_log = ln(1 + TMJOFCDPL)
    gdf["fcd_log"] = np.log1p(gdf["TMJOFCDPL"].astype(float))

    # 5) tv_pl_ratio = TMJOFCDTV / (TMJOFCDPL + 0.1)
    gdf["tv_pl_ratio"] = gdf["TMJOFCDTV"].astype(float) / (gdf["TMJOFCDPL"].astype(float) + 0.1)

    # 6) dist_to_lyon_center — Haversine from LINESTRING centroid -> Bellecour
    print("Computing dist_to_lyon_center (Haversine from centroid)...", flush=True)
    # Ensure WGS84 for lat/lon extraction
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    elif gdf.crs.to_string() != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")
    centroids = gdf.geometry.centroid
    lats = centroids.y.values
    lons = centroids.x.values
    gdf["dist_to_lyon_center"] = haversine_km(LYON_LAT, LYON_LON, lats, lons).round(4)

    # Sanity checks
    new_cols = list(RENAME_SIMPLE.values()) + list(RENAME_KM_TO_M.values()) + [
        "Annee", "fcd_log", "tv_pl_ratio", "dist_to_lyon_center",
    ]
    print(f"\nSanity check ({len(new_cols)} new/renamed cols):")
    for c in new_cols:
        if c not in gdf.columns:
            print(f"  MISSING: {c}")
            continue
        s = gdf[c]
        if c == "Annee":
            print(f"  {c:<32} = {int(s.iloc[0])}  (constant for {len(s):,} rows)")
        else:
            try:
                nn = pd.to_numeric(s, errors="coerce").notna().sum()
                vals = pd.to_numeric(s, errors="coerce")
                print(f"  {c:<32} non-null={nn:>8} ({100*nn/len(s):5.1f}%)  min={vals.min():.4f}  med={vals.median():.4f}  max={vals.max():.4f}")
            except Exception as exc:
                print(f"  {c:<32} (could not summarize: {exc})")

    # Write parquet (preserve full schema + geometry)
    print(f"\nWriting {DST_PARQUET.name} (parquet)...", flush=True)
    gdf.to_parquet(DST_PARQUET, index=False)
    sz_p = DST_PARQUET.stat().st_size / 1024 / 1024
    print(f"  -> {sz_p:.1f} MB", flush=True)

    # Skip geojson for now (1.4 GB previously) - parquet is what /api/upload accepts
    # If geojson is required, uncomment:
    # print(f"Writing {DST_GEOJSON.name} (geojson)...", flush=True)
    # gdf.to_file(DST_GEOJSON, driver="GeoJSON")

    print(f"\nTotal cols in output: {len(gdf.columns)}")
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
