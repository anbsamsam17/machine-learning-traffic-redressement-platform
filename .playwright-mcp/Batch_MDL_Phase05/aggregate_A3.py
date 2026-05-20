"""Aggregate A3 metrics.json into A3_summary.md."""

from __future__ import annotations

import json
from pathlib import Path

BATCH = Path(__file__).parent


def main() -> None:
    runs = []
    for d in sorted(BATCH.iterdir()):
        if not d.is_dir() or not d.name.startswith("A3_"):
            continue
        mf = d / "metrics.json"
        if not mf.exists():
            continue
        try:
            runs.append(json.loads(mf.read_text(encoding="utf-8")))
        except Exception as exc:  # noqa: BLE001
            print(f"skip {d.name}: {exc}")

    rows: list[str] = []
    rows.append(
        "| Run | Config | tol_in / total (%) | p80 (%) | R² | RMSE | MAE | GEH<5 % | Train s |"
    )
    rows.append("|---|---|---|---|---|---|---|---|---|")
    for r in runs:
        cfg = r.get("config", {})
        cfg_bits = []
        if cfg.get("activation", "elu") != "elu":
            cfg_bits.append(f"act={cfg['activation']}")
        if cfg.get("optimizer", "adam") != "adam":
            cfg_bits.append(f"opt={cfg['optimizer']}")
        if cfg.get("weight_decay", 0.0):
            cfg_bits.append(f"wd={cfg['weight_decay']}")
        if cfg.get("clipnorm"):
            cfg_bits.append(f"cn={cfg['clipnorm']}")
        if cfg.get("use_skip_connection"):
            cfg_bits.append("skip")
        if cfg.get("norm_layer"):
            cfg_bits.append(f"norm={cfg['norm_layer']}")
        if cfg.get("dropout_schedule", "uniform") != "uniform":
            cfg_bits.append(f"drp_sched={cfg['dropout_schedule']}")
        cfg_str = ", ".join(cfg_bits) or "baseline"
        m = r.get("metrics") or {}
        tol_in = r.get("tol_inclus", 0)
        tol_tot = r.get("tol_total", 0)
        tol_pct = 100 * tol_in / max(tol_tot, 1)
        rows.append(
            f"| {r['run_name']} | {cfg_str} | {tol_in}/{tol_tot} ({tol_pct:.1f}%) | "
            f"{r.get('err_p80_pct', '-')} | {m.get('r_squared', 0):.4f} | "
            f"{m.get('rmse', '-')} | {m.get('mae', '-')} | {m.get('geh_pct_below_5', '-')} | "
            f"{r.get('train_seconds', '-')} |"
        )

    # Best by p80 and by tol%
    valid = [
        r for r in runs
        if isinstance(r.get("err_p80_pct"), (int, float))
        and r["err_p80_pct"] == r["err_p80_pct"]  # not NaN
    ]
    valid_by_p80 = sorted(valid, key=lambda r: r["err_p80_pct"])
    valid_by_tol = sorted(
        valid,
        key=lambda r: -r["tol_inclus"] / max(r["tol_total"], 1),
    )

    lines = []
    lines.append("# Worker A3 — Phase 5 architecture ablation (12 configs)")
    lines.append("")
    lines.append(
        f"Baseline reference (A5_Full_drp025, Batch_MDL): R²=0.805, p80≈24.6%, tol≈?"
    )
    lines.append("")
    lines.append("## Top 3 par p80 (err_p80_pct)")
    for r in valid_by_p80[:3]:
        lines.append(
            f"- **{r['run_name']}** — p80={r['err_p80_pct']}%, "
            f"R²={r['metrics'].get('r_squared', 0):.4f}, "
            f"tol={r['tol_inclus']}/{r['tol_total']}"
        )
    lines.append("")
    lines.append("## Top 3 par tol_inclus%")
    for r in valid_by_tol[:3]:
        pct = 100 * r["tol_inclus"] / max(r["tol_total"], 1)
        lines.append(
            f"- **{r['run_name']}** — tol={r['tol_inclus']}/{r['tol_total']} ({pct:.1f}%), "
            f"p80={r['err_p80_pct']}%, R²={r['metrics'].get('r_squared', 0):.4f}"
        )
    lines.append("")
    lines.append("## Table complète")
    lines.extend(rows)

    out = BATCH / "A3_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out}")
    print(f"n_runs={len(runs)} valid={len(valid)}")


if __name__ == "__main__":
    main()
