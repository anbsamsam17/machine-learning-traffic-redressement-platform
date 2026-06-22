"""Build nodes_with_cause_v3.json from v2 + 2025.geojson.

v3 additions per feature:
- `principal_cause` : ONE dominant cause (replaces the v2 `Multi_factor` composite).
- `topology`        : Bretelle / Carrefour / Continuite (priority cascade).

The v2 data does NOT carry RAMP/ROUNDABOUT/FC at the edge level for every node — we
rejoin from `2025.geojson` using `agregId` to populate a lookup, then attach the
flags so we can compute both `principal_cause` (when drivers are empty) and
`topology` (always).

Top-level metadata updated:
- `cause_labels_fr`     : accented French labels (Multi_factor removed).
- `topology_labels_fr`  : Bretelle / Carrefour / Continuite labels.
- `cause_palette`       : 8 colors.
- `topology_palette`    : 3 colors (continuity stands out — most suspicious).

Run:
    python build_node_data_v3.py
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs"
SRC_V2 = OUT / "nodes_with_cause_v2.json"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
NETWORK = DATA_ROOT / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables" / "2025.geojson"
DST = OUT / "nodes_with_cause_v3.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CAUSE_LABELS_FR = {
    "FCD_TV_cliff":         "Falaise FCD VL",
    "FCD_PL_cliff":         "Falaise FCD PL",
    "Coverage_gap":         "Trou de couverture FCD",
    "Distance_anomaly":     "Anomalie de distance",
    "RAMP_asymmetry":       "Bretelle asymétrique",
    "ROUNDABOUT_asymmetry": "Rond-point asymétrique",
    "FC_transition":        "Transition de classe fonctionnelle (légitime)",
    "Unexplained":          "Inexpliqué (à investiguer)",
}

TOPOLOGY_LABELS_FR = {
    "Bretelle":   "Bretelle",
    "Carrefour":  "Carrefour",
    "Continuite": "Continuité segment",
}

CAUSE_PALETTE = {
    "FCD_TV_cliff":         "#E41A1C",
    "FCD_PL_cliff":         "#B30000",
    "Coverage_gap":         "#7B1FA2",
    "Distance_anomaly":     "#FF7F00",
    "RAMP_asymmetry":       "#FFB000",
    "ROUNDABOUT_asymmetry": "#A65628",
    "FC_transition":        "#377EB8",
    "Unexplained":          "#999999",
}

TOPOLOGY_PALETTE = {
    "Bretelle":   "#87CEEB",   # light steel blue
    "Carrefour":  "#4682B4",   # steel blue
    "Continuite": "#FFA07A",   # light salmon — suspicious (no physical intersection)
}

DRIVER_TO_CAUSE = {
    "TMJOFCDTV":                   "FCD_TV_cliff",
    "TMJOFCDPL":                   "FCD_PL_cliff",
    "functional_class":            "FC_transition",
    "avg_distance_before_m":       "Distance_anomaly",
    "avg_min_distance_m":          "Distance_anomaly",
    "truck_avg_distance_before_m": "Distance_anomaly",
}


# ---------------------------------------------------------------------------
# Step 1 — build agregId -> (RAMP, ROUNDABOUT, FC) lookup
# ---------------------------------------------------------------------------
def build_edge_lookup(network_path: Path) -> dict[str, tuple[str, str, str]]:
    """Stream-parse 2025.geojson and return {agregId: (RAMP, ROUNDABOUT, FC)}.

    `2025.geojson` ships as a pretty-printed FeatureCollection with one feature
    per line for the body — we exploit that to avoid loading the whole 178 MB
    blob into a single json.loads. If that ever changes, we fall back to a full
    parse.
    """
    lookup: dict[str, tuple[str, str, str]] = {}
    with network_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{ \"type\": \"Feature\""):
                continue
            # Trim trailing comma (and possible whitespace) so json.loads is happy.
            if line.endswith(","):
                line = line[:-1]
            try:
                feat = json.loads(line)
            except json.JSONDecodeError:
                continue
            props = feat.get("properties") or {}
            aid = props.get("agregId")
            if not aid:
                continue
            lookup[str(aid)] = (
                str(props.get("RAMP", "")).upper(),
                str(props.get("ROUNDABOUT", "")).upper(),
                str(props.get("FUNC_CLASS", "")),
            )
    if not lookup:
        # Fallback : maybe single-line geojson. Load the whole file.
        data = json.loads(network_path.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            props = feat.get("properties") or {}
            aid = props.get("agregId")
            if not aid:
                continue
            lookup[str(aid)] = (
                str(props.get("RAMP", "")).upper(),
                str(props.get("ROUNDABOUT", "")).upper(),
                str(props.get("FUNC_CLASS", "")),
            )
    return lookup


# ---------------------------------------------------------------------------
# Step 2 — classification helpers
# ---------------------------------------------------------------------------
def classify_topology(
    edges_in: list[dict],
    edges_out: list[dict],
    n_in: int,
    n_out: int,
    edge_lookup: dict[str, tuple[str, str, str]],
) -> str:
    """Bretelle > Carrefour > Continuite."""
    has_ramp = False
    has_rdb = False
    for e in edges_in + edges_out:
        aid = str(e.get("agregId", ""))
        if not aid:
            continue
        flags = edge_lookup.get(aid)
        if not flags:
            continue
        ramp, rdb, _ = flags
        if ramp == "Y":
            has_ramp = True
        if rdb == "Y":
            has_rdb = True

    if has_ramp:
        return "Bretelle"

    total = (n_in or 0) + (n_out or 0)
    if has_rdb or total >= 3:
        return "Carrefour"

    if (n_in or 0) == 1 and (n_out or 0) == 1:
        return "Continuite"

    # Degenerate (n_in=0 or n_out=0, no RDB, total < 3) — treat as Carrefour by safety.
    return "Carrefour"


def classify_principal_cause(
    drivers: list[str],
    edges_in: list[dict],
    edges_out: list[dict],
    edge_lookup: dict[str, tuple[str, str, str]],
) -> str:
    """One dominant cause — no more Multi_factor."""
    if drivers:
        top = drivers[0]
        return DRIVER_TO_CAUSE.get(top, "Unexplained")

    # drivers=[] -> topology-based fallback
    has_ramp = False
    has_rdb = False
    ramp_flags: list[str] = []
    rdb_flags: list[str] = []
    for e in edges_in + edges_out:
        aid = str(e.get("agregId", ""))
        flags = edge_lookup.get(aid, ("", "", ""))
        ramp, rdb, _ = flags
        ramp_flags.append(ramp)
        rdb_flags.append(rdb)
        if ramp == "Y":
            has_ramp = True
        if rdb == "Y":
            has_rdb = True

    # RAMP asymmetry : at least one Y AND at least one N (across all incident edges).
    has_ramp_n = any(f == "N" for f in ramp_flags)
    if has_ramp and has_ramp_n:
        return "RAMP_asymmetry"

    has_rdb_n = any(f == "N" for f in rdb_flags)
    if has_rdb and has_rdb_n:
        return "ROUNDABOUT_asymmetry"

    # Coverage gap : at least one edge with TMJOFCDTV<1 or TMJOFCDPL<0.5
    for e in edges_in + edges_out:
        inp = e.get("inputs") or {}
        tv = inp.get("TMJOFCDTV")
        pl = inp.get("TMJOFCDPL")
        if (isinstance(tv, (int, float)) and tv < 1) or (
            isinstance(pl, (int, float)) and pl < 0.5
        ):
            return "Coverage_gap"

    return "Unexplained"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"Reading v2 source : {SRC_V2}")
    v2 = json.loads(SRC_V2.read_text(encoding="utf-8"))
    features = v2.get("features", [])
    print(f"  -> {len(features)} features")

    print(f"Reading network : {NETWORK}")
    edge_lookup = build_edge_lookup(NETWORK)
    print(f"  -> {len(edge_lookup)} edges indexed")

    # Stats accumulators
    cross = Counter()
    cause_dist = Counter()
    topo_dist = Counter()
    missing_lookup = Counter()

    for feat in features:
        props = feat["properties"]
        edges_in = props.get("edges_in") or []
        edges_out = props.get("edges_out") or []
        n_in = int(props.get("n_in") or len(edges_in))
        n_out = int(props.get("n_out") or len(edges_out))
        drivers = props.get("drivers") or []

        # Sanity: track which edges are missing RAMP/RDB info
        for e in edges_in + edges_out:
            aid = str(e.get("agregId", ""))
            if aid and aid not in edge_lookup:
                missing_lookup[aid] += 1

        topology = classify_topology(edges_in, edges_out, n_in, n_out, edge_lookup)
        principal = classify_principal_cause(drivers, edges_in, edges_out, edge_lookup)

        props["principal_cause"] = principal
        props["topology"] = topology

        cross[(principal, topology)] += 1
        cause_dist[principal] += 1
        topo_dist[topology] += 1

    # Update top-level metadata
    meta = v2.get("metadata") or {}
    meta["version"] = "v3"
    meta["cause_labels_fr"] = dict(CAUSE_LABELS_FR)
    meta["topology_labels_fr"] = dict(TOPOLOGY_LABELS_FR)
    meta["cause_palette"] = dict(CAUSE_PALETTE)
    meta["topology_palette"] = dict(TOPOLOGY_PALETTE)
    meta["principal_cause_taxonomy"] = list(CAUSE_LABELS_FR.keys())

    out = {
        "type": "FeatureCollection",
        "metadata": meta,
        "features": features,
    }
    DST.write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    size_mb = DST.stat().st_size / (1024 * 1024)
    print(f"WROTE: {DST} ({size_mb:.2f} MB)")

    # -----------------------------------------------------------------------
    # Report
    # -----------------------------------------------------------------------
    print("\nPrincipal cause distribution:")
    for c in CAUSE_LABELS_FR:
        n = cause_dist.get(c, 0)
        pct = (n / len(features) * 100) if features else 0
        print(f"  {c:<22s} : {n:>5d}  ({pct:5.1f}%)")

    print("\nTopology distribution:")
    for t in TOPOLOGY_LABELS_FR:
        n = topo_dist.get(t, 0)
        pct = (n / len(features) * 100) if features else 0
        print(f"  {t:<12s} : {n:>5d}  ({pct:5.1f}%)")

    print("\nCross-tab (cause x topology):")
    header = ["Cause \\ Topo"] + list(TOPOLOGY_LABELS_FR.keys()) + ["Total"]
    print("  " + " | ".join(f"{h:>22s}" for h in header))
    for c in CAUSE_LABELS_FR:
        row = [c]
        for t in TOPOLOGY_LABELS_FR:
            row.append(str(cross.get((c, t), 0)))
        row.append(str(cause_dist.get(c, 0)))
        print("  " + " | ".join(f"{x:>22s}" for x in row))
    # Total row
    row = ["TOTAL"]
    for t in TOPOLOGY_LABELS_FR:
        row.append(str(topo_dist.get(t, 0)))
    row.append(str(len(features)))
    print("  " + " | ".join(f"{x:>22s}" for x in row))

    if missing_lookup:
        # report only the count of unique missing agregIds
        print(
            f"\nWARNING: {len(missing_lookup)} unique agregIds not found in 2025.geojson "
            f"(total {sum(missing_lookup.values())} edge references)."
        )
    else:
        print("\nAll edge agregIds resolved against 2025.geojson.")

    print("\nDone.")


if __name__ == "__main__":
    main()
