"""Worker A2 — pre-processing of GrandLyon TV geojson for the 12 feature-engineering ablations.

Produces a new geojson at .playwright-mcp/Batch_MDL_Phase05/A2_TV_features.geojson
that contains, for every feature:

  * The original 30 columns (no rename).
  * Derived columns required by configs 1..12:
      - year_mapped        : Annee mapped 2019..2025 -> 1..7
      - flag_permanent     : 1 if Type Compteur == "Permanent" else 0
      - flag_recent_year   : 1 if Annee == max(Annee) else 0
      - ratio_PLTV         : TMJOFCDPL / max(TMJOFCDTV, 1)
      - log_TMJOFCDTV      : log1p(clip(TMJOFCDTV, 0))
      - log_TMJOFCDPL      : log1p(clip(TMJOFCDPL, 0))
      - fc_1, fc_2, fc_3, fc_4, fc_5  : one-hot(functional_class)
      - rs_*               : RobustScaler-normalised copies of the 9 numeric
                              features used in config #7 (year_mapped is left
                              untouched — it's categorical-ish).
      - yemb1, yemb2, yemb3 : sinusoidal positional encoding of year_mapped
                              (emulates config #8 year_embedding dim=3).

All derived columns are added as properties on each Feature.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
SRC = PROJECT_ROOT / ".playwright-mcp/DataApprentissage/GrandLyon/BCFCDREF_AllYears_TV.geojson"
OUT = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05/A2_TV_features.geojson"

YEAR_MAPPING = {2019: 1, 2020: 2, 2021: 3, 2022: 4, 2023: 5, 2024: 6, 2025: 7}

# Numeric continuous features that get RobustScaler treatment for config #7.
ROBUST_FEATURES = [
    "TMJOFCDTV",
    "TMJOFCDPL",
    "avg_distance_before_m",
    "avg_distance_after_m",
    "avg_min_distance_m",
    "truck_avg_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_distance_after_m",
    "truck_avg_min_distance_m",
]


def _robust_scale_stats(values: np.ndarray) -> tuple[float, float]:
    """median, IQR/1.349 — matches normalize.py 'robust' scaler."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return 0.0, 1.0
    median = float(np.median(finite))
    q75 = float(np.percentile(finite, 75))
    q25 = float(np.percentile(finite, 25))
    iqr = q75 - q25
    scale = iqr / 1.349 if iqr > 1e-9 else 1.0
    return median, scale


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    features = data["features"]
    n = len(features)
    print(f"Loaded {n} features from {SRC.name}")

    # First pass: collect numeric arrays for RobustScaler stats.
    cols: dict[str, np.ndarray] = {}
    for col in ROBUST_FEATURES:
        arr = np.array(
            [_to_float(f["properties"].get(col)) for f in features], dtype=float
        )
        cols[col] = arr

    rs_stats: dict[str, tuple[float, float]] = {}
    for col, arr in cols.items():
        rs_stats[col] = _robust_scale_stats(arr)
        print(f"  rs[{col}] median={rs_stats[col][0]:.3f} scale={rs_stats[col][1]:.3f}")

    # Sinusoidal year embedding (period covers 1..7 cleanly).
    # Three orthogonal-ish components from sin/cos at different frequencies.
    def _year_embedding(y_mapped: float) -> tuple[float, float, float]:
        if not math.isfinite(y_mapped):
            return 0.0, 0.0, 0.0
        # Two pairs of sin/cos — use sin1, cos1, sin2 to keep dim=3.
        # Frequency tuned so 7 years span ~one period for the low-frequency.
        f1 = 2 * math.pi / 7.0
        f2 = 2 * math.pi / 3.5
        return (
            math.sin(f1 * y_mapped),
            math.cos(f1 * y_mapped),
            math.sin(f2 * y_mapped),
        )

    # Second pass: write derived columns onto each feature.
    n_perm = 0
    n_recent = 0
    max_annee = max(
        int(f["properties"].get("annee", 0) or 0) for f in features
    )
    print(f"  max(annee) = {max_annee}")

    for f in features:
        p = f["properties"]
        annee = int(p.get("annee", 0) or 0)
        p["Annee"] = annee  # alias for the mapping target column 'Annee'
        p["year_mapped"] = YEAR_MAPPING.get(annee, 0)
        p["flag_permanent"] = 1 if str(p.get("Type Compteur", "")).strip().lower() == "permanent" else 0
        n_perm += p["flag_permanent"]
        p["flag_recent_year"] = 1 if annee == max_annee else 0
        n_recent += p["flag_recent_year"]

        # ratio_PLTV
        tv = _to_float(p.get("TMJOFCDTV"))
        pl = _to_float(p.get("TMJOFCDPL"))
        denom = tv if tv >= 1.0 else 1.0
        p["ratio_PLTV"] = float(pl / denom) if math.isfinite(pl) else 0.0

        # log_*
        p["log_TMJOFCDTV"] = math.log1p(max(0.0, tv)) if math.isfinite(tv) else 0.0
        p["log_TMJOFCDPL"] = math.log1p(max(0.0, pl)) if math.isfinite(pl) else 0.0

        # one-hot functional_class
        fc = int(p.get("functional_class", 0) or 0)
        for level in (1, 2, 3, 4, 5):
            p[f"fc_{level}"] = 1 if fc == level else 0

        # RobustScaler-encoded copies (config #7)
        for col in ROBUST_FEATURES:
            v = _to_float(p.get(col))
            mu, sc = rs_stats[col]
            p[f"rs_{col}"] = (v - mu) / sc if math.isfinite(v) and sc > 0 else 0.0

        # year embedding (config #8 emulation)
        ye1, ye2, ye3 = _year_embedding(float(p["year_mapped"]))
        p["yemb1"] = ye1
        p["yemb2"] = ye2
        p["yemb3"] = ye3

    print(f"  flag_permanent=1 : {n_perm}/{n}")
    print(f"  flag_recent_year=1: {n_recent}/{n}")

    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    sz = OUT.stat().st_size / (1024 * 1024)
    print(f"Wrote {OUT} ({sz:.1f} MB)")

    # Sanity: also write a one-line schema summary so the orchestrator can
    # double-check the available columns before uploading.
    sample = features[0]["properties"]
    schema = sorted(sample.keys())
    (OUT.parent / "A2_schema.txt").write_text("\n".join(schema), encoding="utf-8")
    print(f"Schema: {len(schema)} columns")


def _to_float(v) -> float:
    if v is None:
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


if __name__ == "__main__":
    main()
