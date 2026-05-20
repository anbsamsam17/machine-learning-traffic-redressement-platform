"""Build A1_summary.md from per-run metrics.json files in Batch_MDL_Phase05/."""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

BATCH_DIR = Path(__file__).parent

RUN_PREFIX = "A1_"


def _safe_float(v):
    if v is None:
        return float("nan")
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return float("nan")


def main() -> int:
    rows: list[dict] = []
    for sub in sorted(BATCH_DIR.iterdir()):
        if not sub.is_dir() or not sub.name.startswith(RUN_PREFIX):
            continue
        mpath = sub / "metrics.json"
        if not mpath.exists():
            continue
        raw = mpath.read_text(encoding="utf-8")
        # tolerate NaN literal that python json doesn't accept
        try:
            m = json.loads(raw)
        except json.JSONDecodeError:
            m = json.loads(raw.replace("NaN", "null").replace("Infinity", "null"))
        metrics = m.get("metrics") or {}
        rows.append({
            "name": m.get("run_name", sub.name),
            "loss": m.get("loss", "?"),
            "drp": m.get("dropout"),
            "ep": m.get("min_epochs"),
            "tlog": m.get("target_log_transform", False),
            "tol_in": m.get("tol_inclus", 0),
            "tol_total": m.get("tol_total", 0),
            "p80": _safe_float(m.get("err_p80_pct")),
            "r2": _safe_float(metrics.get("r_squared")),
            "rmse": _safe_float(metrics.get("rmse")),
            "mae": _safe_float(metrics.get("mae")),
            "geh5": _safe_float(metrics.get("geh_pct_below_5")),
            "n": metrics.get("n_samples"),
            "broken": m.get("broken", False),
            "broken_reasons": m.get("broken_reasons", []),
            "train_s": _safe_float(m.get("train_seconds")),
            "ci95": m.get("metrics_ci95") or {},
        })

    # Sort by tolerance % descending
    def sort_key(r):
        if r["tol_total"]:
            return r["tol_in"] / r["tol_total"]
        return -1.0
    rows_sorted = sorted(rows, key=sort_key, reverse=True)

    lines: list[str] = []
    lines.append("# Worker A1 Phase 0-5 — loss + target ablation (12 configs)")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)")
    lines.append("Baseline: Full 11 features, ep=1000, drp=0.025, neurons_factors=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05, no weighting")
    lines.append("")
    lines.append("## Results (sorted by tol_in %)")
    lines.append("")
    lines.append(
        "| Run | Loss | Drp | Ep | TLog | Tol in | Tol % | p80% | R2 | RMSE | MAE | GEH<5 | Train(s) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows_sorted:
        tol_pct = (
            f"{100*r['tol_in']/r['tol_total']:.1f}%" if r["tol_total"] else "—"
        )
        p80_s = f"{r['p80']:.2f}" if not math.isnan(r["p80"]) else "—"
        r2_s = f"{r['r2']:.4f}" if not math.isnan(r["r2"]) else "—"
        rmse_s = f"{r['rmse']:.4f}" if not math.isnan(r["rmse"]) else "—"
        mae_s = f"{r['mae']:.4f}" if not math.isnan(r["mae"]) else "—"
        geh_s = f"{r['geh5']:.1f}%" if not math.isnan(r["geh5"]) else "—"
        tlog_s = "Y" if r["tlog"] else "—"
        broken_marker = " [BROKEN]" if r["broken"] else ""
        train_s = f"{r['train_s']:.0f}" if not math.isnan(r["train_s"]) else "?"
        lines.append(
            f"| {r['name']}{broken_marker} | {r['loss']} | {r['drp']} | {r['ep']} | {tlog_s} | "
            f"{r['tol_in']}/{r['tol_total']} | {tol_pct} | {p80_s} | {r2_s} | {rmse_s} | {mae_s} | {geh_s} | {train_s} |"
        )

    # Best
    valid = [r for r in rows_sorted if r["tol_total"]]
    if valid:
        best = valid[0]
        lines.append("")
        lines.append("## Best of batch (highest tol_in %)")
        lines.append(
            f"- **{best['name']}** — tol={best['tol_in']}/{best['tol_total']} "
            f"({100*best['tol_in']/best['tol_total']:.1f}%) | p80={best['p80']:.2f}% | "
            f"R2={best['r2']:.4f} | RMSE={best['rmse']:.4f} | GEH<5={best['geh5']:.1f}% | "
            f"train={best['train_s']:.0f}s"
        )
        # Also best by p80 (smaller is better)
        by_p80 = sorted(
            (r for r in valid if not math.isnan(r["p80"])),
            key=lambda r: r["p80"],
        )
        if by_p80:
            b = by_p80[0]
            lines.append(
                f"- Lowest p80: **{b['name']}** — p80={b['p80']:.2f}% | "
                f"tol={b['tol_in']}/{b['tol_total']} | R2={b['r2']:.4f}"
            )
        by_r2 = sorted(
            (r for r in valid if not math.isnan(r["r2"])),
            key=lambda r: r["r2"],
            reverse=True,
        )
        if by_r2:
            b = by_r2[0]
            lines.append(
                f"- Highest R2: **{b['name']}** — R2={b['r2']:.4f} | "
                f"tol={b['tol_in']}/{b['tol_total']} | p80={b['p80']:.2f}%"
            )

    # Issues
    broken = [r for r in rows_sorted if r["broken"]]
    if broken:
        lines.append("")
        lines.append("## Issues encountered")
        for r in broken:
            lines.append(f"- {r['name']}: {', '.join(r['broken_reasons'])}")

    # Wall-clock
    sjson = BATCH_DIR / "_summary_A1.json"
    if sjson.exists():
        s = json.loads(sjson.read_text(encoding="utf-8"))
        wc = s.get("wall_clock_seconds")
        if wc:
            # The actual end-to-end run for the orchestrator includes the
            # smoke test (124s) + the aborted-then-restarted batch (388s for
            # the lost mse_drp0.03 attempt) + the successful 2415s batch.
            total = 124 + 388 + wc
            lines.append("")
            lines.append("## Wall-clock")
            lines.append(f"- Restart batch (configs 3-12): **{wc:.0f}s** ({wc/60:.1f} min)")
            lines.append(f"- Smoke test config 1: ~124s (~2 min)")
            lines.append(f"- Aborted batch (config 3 first attempt): ~388s training time wasted")
            lines.append(f"- **Total wall-clock (incl. retries): ~{total:.0f}s ({total/60:.1f} min)**")

    # Issues / API bugs
    lines.append("")
    lines.append("## Notes & issues")
    lines.append("- **API bug detected**: `apps/api/app/services/ml/training_pipeline.py:584` does NOT pass `target_log_transform` to `split_train_valid`. Configs 9 (mse_tlog) and 10 (huber_tlog) produced metrics identical to their non-tlog counterparts. Flag persisted via `warning_target_log_transform_no_op` in their metrics.json.")
    lines.append("- **Worker bug detected & fixed mid-batch**: the API serializes all run models into the same session-level `models/` dir. The original `sub_dirs[0]` heuristic picked the wrong model when multiple existed. Fixed to match by expected `loss + drp + ep` pattern; configs 2-12 re-ran cleanly after the fix.")
    lines.append("- **pinball_p80 is not a good fit** for tol_in optimisation (tol=46.6% vs 60-65% for other losses). Expected — pinball@0.8 targets the 80th percentile, not the median.")
    lines.append("- **`target_log_transform` had no effect** (see API bug above) — once the bug is fixed, configs 9 & 10 should be re-run.")

    (BATCH_DIR / "A1_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {BATCH_DIR / 'A1_summary.md'} with {len(rows)} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
