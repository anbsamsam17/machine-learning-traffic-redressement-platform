"""
prepare_data.py - Optimise 2025_light.geojson for the standalone MapLibre map.

Pipeline:
    1. Read source GeoJSON (~81 MB, 98 129 LineStrings, 31 props/feature).
    2. Keep only the 15 properties needed for display + popup.
    3. Round coords to 5 decimals (~1.1 m at this latitude) and traffic values
       to integers (PLr / length_m to 1 decimal).
    4. Emit a single-line minified GeoJSON and a gzipped twin.
    5. Report sizes.

Usage:
    python prepare_data.py
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from pathlib import Path

# ---- I/O paths --------------------------------------------------------------
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
SRC = DATA_ROOT / "Travaux_donnees_Lyon" / "Livrables" / "2025_light.geojson"
OUT_DIR = Path(__file__).parent
OUT_JSON = OUT_DIR / "2025_light.min.geojson"
OUT_GZ = OUT_DIR / "2025_light.min.geojson.gz"

# ---- Schema -----------------------------------------------------------------
# 15 properties consumed by the standalone HTML (style + popup).
KEEP_PROPS = (
    "agregId",
    "TVr", "TVrmin", "TVrmax",
    "DPL", "DPLmin", "DPLmax",
    "PL", "PLr",
    "FC", "FUNC_CLASS",
    "RAMP", "ROUNDABOUT",
    "n_merged", "length_m",
)
INT_PROPS = {
    "TVr", "TVrmin", "TVrmax",
    "DPL", "DPLmin", "DPLmax",
    "PL", "FC", "n_merged",
}
FLOAT_1DEC_PROPS = {"PLr", "length_m"}
COORD_DECIMALS = 5  # ~1.1 m at lat 45 - sufficient for city-scale flow map


def prune_properties(props: dict) -> dict:
    """Return a small dict with only KEEP_PROPS, type-coerced and rounded.

    Aggressive size reductions:
      - RAMP / ROUNDABOUT 'Y'/'N' -> 1/0 (int), omit when 0.
      - FUNC_CLASS coerced to int when possible.
      - n_merged omitted when == 1 (the most common value).
      - PL omitted when == 0 (very common for low-traffic links).
      - PLr omitted when == 0.
    The HTML popup defaults missing values to '-' / 0 / 'non'.
    """
    out: dict = {}
    for k in KEEP_PROPS:
        if k not in props:
            continue
        v = props[k]
        if v is None:
            continue

        if k in INT_PROPS:
            try:
                v = int(round(float(v)))
            except (TypeError, ValueError):
                continue
            # Drop high-default values that the front-end can recover from.
            if k == "n_merged" and v == 1:
                continue
            if k == "PL" and v == 0:
                continue

        elif k in FLOAT_1DEC_PROPS:
            try:
                v = round(float(v), 1)
            except (TypeError, ValueError):
                continue
            if k == "PLr" and v == 0:
                continue

        elif k == "FUNC_CLASS":
            # Source is sometimes str, sometimes int - normalise to int.
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = str(v)

        elif k in ("RAMP", "ROUNDABOUT"):
            # 'Y' / 'N' -> 1 / 0; omit zeros (the vast majority).
            yn = str(v).strip().upper()
            v = 1 if yn == "Y" else 0
            if v == 0:
                continue

        # agregId stays as-is
        out[k] = v
    return out


def round_coords(coords: list) -> list:
    """Round (lon, lat) pairs to COORD_DECIMALS."""
    d = COORD_DECIMALS
    return [[round(x, d), round(y, d)] for x, y in coords]


def main() -> None:
    t0 = time.perf_counter()
    print(f"[prepare] reading {SRC.name} ({SRC.stat().st_size / 1e6:.1f} MB)")
    with SRC.open("r", encoding="utf-8") as fh:
        gj = json.load(fh)

    feats = gj["features"]
    print(f"[prepare] {len(feats):,} features in")

    out_feats = []
    for ft in feats:
        geom = ft.get("geometry") or {}
        if geom.get("type") != "LineString":
            continue
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        out_feats.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": round_coords(coords),
            },
            "properties": prune_properties(ft.get("properties") or {}),
        })

    out_gj = {"type": "FeatureCollection", "features": out_feats}

    print(f"[prepare] writing minified JSON -> {OUT_JSON.name}")
    with OUT_JSON.open("w", encoding="utf-8") as fh:
        json.dump(out_gj, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"[prepare] gzip -> {OUT_GZ.name}")
    with OUT_JSON.open("rb") as src, gzip.open(OUT_GZ, "wb", compresslevel=9) as dst:
        shutil.copyfileobj(src, dst)

    raw_mb = OUT_JSON.stat().st_size / 1e6
    gz_mb = OUT_GZ.stat().st_size / 1e6
    print("-" * 60)
    print(f"[prepare] kept {len(out_feats):,} features, "
          f"{len(KEEP_PROPS)} props each")
    print(f"[prepare] minified : {raw_mb:6.2f} MB")
    print(f"[prepare] gzipped  : {gz_mb:6.2f} MB  "
          f"(ratio {gz_mb / raw_mb:.2%})")
    print(f"[prepare] done in {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
