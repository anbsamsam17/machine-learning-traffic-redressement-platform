"""Aggregate A6 run metrics into A6_summary.md and _index_A6.json.

Reads every metrics.json under .playwright-mcp/Batch_MDL_Phase05/A6_*/ and
builds a ranked Markdown table sorted by tol_inclus / tol_total (then by
err_rel_p80 ascending). TTA configs are listed in their own section.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05"


def _safe(v, fmt: str = "{:.3f}") -> str:
    if v is None or v != v:
        return "-"
    try:
        return fmt.format(v)
    except (TypeError, ValueError):
        return str(v)


def main() -> int:
    train_rows: list[dict] = []
    tta_rows: list[dict] = []
    for d in sorted(BATCH_DIR.glob("A6_*")):
        if not d.is_dir():
            continue
        f = d / "metrics.json"
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if data.get("mode") == "tta_reeval":
            tta_rows.append(data)
        else:
            train_rows.append(data)

    # Sort training rows by tol_pct desc then p80 asc.
    def _tol_pct(r: dict) -> float:
        tot = r.get("tol_total") or 0
        if tot == 0:
            return 0.0
        return 100.0 * (r.get("tol_inclus") or 0) / tot

    def _p80(r: dict) -> float:
        v = r.get("err_p80_pct")
        if v is None or v != v:
            return float("inf")
        return float(v)

    train_rows.sort(key=lambda r: (-_tol_pct(r), _p80(r)))

    lines: list[str] = []
    lines.append("# A6 — winning combinations + TTA (14 configs)")
    lines.append("")
    lines.append("Worker A6 of the 6-agent Phase 0-5 grid search. Port 7006.")
    lines.append("Baseline: Full 11 features, drp=0.025, ep=1000, neurons_factors=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05.")
    lines.append("Dataset: BCFCDREF_AllYears_TV.geojson (Grand Lyon, 3632 capteurs, 2019-2025).")
    lines.append("")

    lines.append("## Training configs (1-10) — ranked by tolerance %")
    lines.append("")
    lines.append("| # | run_name | loss | optimizer | skip | weighting | tol_in/total (%) | p80 (%) | R2 | RMSE | MAE | train (s) | broken |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in train_rows:
        m = r.get("metrics") or {}
        tol_pct = _tol_pct(r)
        weight_str = []
        if r.get("use_flag_permanent_weighting"):
            weight_str.append(f"permX{r.get('flag_priority_weight', 1)}")
        if r.get("use_flag_recent_year_weighting"):
            weight_str.append(f"recX{r.get('recent_year_priority_weight', 1)}")
        wstr = "+".join(weight_str) or "-"
        opt = r.get("optimizer") or "-"
        skip = "yes" if r.get("use_skip_connection") else "-"
        broken = ",".join(r.get("broken_reasons") or []) or "-"
        lines.append(
            f"| {r.get('config_id')} | `{r['run_name']}` | "
            f"{r.get('loss', 'mse')} | {opt} | {skip} | {wstr} | "
            f"{r.get('tol_inclus')}/{r.get('tol_total')} ({tol_pct:.1f}%) | "
            f"{_safe(r.get('err_p80_pct'), '{:.2f}')} | "
            f"{_safe(m.get('r_squared'))} | "
            f"{_safe(m.get('rmse'))} | "
            f"{_safe(m.get('mae'))} | "
            f"{r.get('train_seconds')} | {broken} |"
        )

    lines.append("")
    lines.append("## TTA re-evaluations (11-14) — parent vs TTA")
    lines.append("")
    lines.append("| # | run_name | parent | tta_iter | tta_noise_std | tol_in/total (%) | p80 (%) | R2 | RMSE | broken |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in tta_rows:
        m = r.get("metrics") or {}
        tol_pct = (
            100.0 * (r.get("tol_inclus") or 0) / (r.get("tol_total") or 1)
            if r.get("tol_total") else 0.0
        )
        broken = ",".join(r.get("broken_reasons") or []) or "-"
        lines.append(
            f"| {r.get('config_id')} | `{r['run_name']}` | "
            f"{r.get('parent_run_name')} | "
            f"{r.get('tta_iter')} | {r.get('tta_noise_std')} | "
            f"{r.get('tol_inclus')}/{r.get('tol_total')} ({tol_pct:.1f}%) | "
            f"{_safe(r.get('err_p80_pct'), '{:.2f}')} | "
            f"{_safe(m.get('r_squared'))} | "
            f"{_safe(m.get('rmse'))} | {broken} |"
        )

    # Best line
    if train_rows:
        best = train_rows[0]
        lines.append("")
        lines.append("## Winner (training)")
        bm = best.get("metrics") or {}
        lines.append(f"- **{best['run_name']}** — tol={_tol_pct(best):.1f}% p80={best.get('err_p80_pct')}% R2={_safe(bm.get('r_squared'))}")
        if best.get("broken"):
            lines.append(f"- quality gates failed: {','.join(best.get('broken_reasons') or [])}")

    out = BATCH_DIR / "A6_summary.md"
    out.write_text("\n".join(lines), encoding="utf-8")

    index = {
        "train": [
            {
                "config_id": r.get("config_id"),
                "run_name": r["run_name"],
                "tol_inclus": r.get("tol_inclus"),
                "tol_total": r.get("tol_total"),
                "err_p80_pct": r.get("err_p80_pct"),
                "metrics": r.get("metrics"),
                "metrics_ci95": r.get("metrics_ci95"),
                "broken": r.get("broken"),
                "broken_reasons": r.get("broken_reasons"),
                "train_seconds": r.get("train_seconds"),
            }
            for r in train_rows
        ],
        "tta": [
            {
                "config_id": r.get("config_id"),
                "run_name": r["run_name"],
                "parent_run_name": r.get("parent_run_name"),
                "tta_iter": r.get("tta_iter"),
                "tta_noise_std": r.get("tta_noise_std"),
                "tol_inclus": r.get("tol_inclus"),
                "tol_total": r.get("tol_total"),
                "err_p80_pct": r.get("err_p80_pct"),
                "metrics": r.get("metrics"),
                "metrics_ci95": r.get("metrics_ci95"),
                "broken": r.get("broken"),
            }
            for r in tta_rows
        ],
    }
    (BATCH_DIR / "_index_A6.json").write_text(
        json.dumps(index, indent=2), encoding="utf-8"
    )
    print(f"[A6] aggregated {len(train_rows)} train + {len(tta_rows)} tta -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
