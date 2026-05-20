"""Post-process: re-parse Capteurs tolerance / p80 / CI95 from each report.html
and patch the corresponding metrics.json + README.md.

Idempotent — safe to re-run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

BATCH_DIR = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
    r"\.playwright-mcp\Batch_MDL_Phase05"
)

REGEX_TOL = re.compile(
    r'Capteurs tolerance inclus</div>\s*<div class="v">\s*([0-9]+)\s*/\s*([0-9]+)'
)
REGEX_TOL_CI = re.compile(
    r'Capteurs tolerance inclus</div>\s*<div class="v">\s*[0-9]+/[0-9]+\s*<small[^>]*>\(([0-9.]+)%\)</small>'
    r'(?:\s*<small[^>]*>\(CI95\s*\[([0-9.]+)%\s*,\s*([0-9.]+)%\]\))?'
)
REGEX_P80 = re.compile(
    r'Err\. rel\. p80</div>\s*<div class="v">\s*([0-9]+(?:\.[0-9]+)?)'
)
REGEX_P80_CI = re.compile(
    r'Err\. rel\. p80</div>\s*<div class="v">\s*[0-9.]+%?\s*<small[^>]*>\(CI95\s*\[([0-9.]+)%?\s*,\s*([0-9.]+)%?\]\)'
)


def patch_one(run_dir: Path) -> dict | None:
    report = run_dir / "report.html"
    mfile = run_dir / "metrics.json"
    if not report.exists() or not mfile.exists():
        return None

    html = report.read_text(encoding="utf-8", errors="replace")
    metrics = json.loads(mfile.read_text(encoding="utf-8"))

    m_tol = REGEX_TOL.search(html)
    if m_tol:
        metrics["tol_inclus"] = int(m_tol.group(1))
        metrics["tol_total"] = int(m_tol.group(2))

    m_ci = REGEX_TOL_CI.search(html)
    if m_ci:
        if m_ci.group(1):
            metrics["tol_pct"] = float(m_ci.group(1))
        if m_ci.group(2) and m_ci.group(3):
            metrics["tol_in_pct_ci95"] = [float(m_ci.group(2)), float(m_ci.group(3))]

    m_p80 = REGEX_P80.search(html)
    if m_p80:
        try:
            metrics["err_p80_pct"] = float(m_p80.group(1))
        except ValueError:
            pass

    m_p80_ci = REGEX_P80_CI.search(html)
    if m_p80_ci:
        metrics["err_p80_pct_ci95"] = [float(m_p80_ci.group(1)), float(m_p80_ci.group(2))]

    metrics["barplot_broken"] = "Aucune donnee disponible" in html

    mfile.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    return metrics


def main() -> None:
    cfg_names = [d["run_name"] for d in json.loads(
        (BATCH_DIR / "configs_A4.json").read_text(encoding="utf-8"))]
    patched = []
    for name in cfg_names:
        run_dir = BATCH_DIR / name
        m = patch_one(run_dir)
        if m is not None:
            print(f"[patched] {name}: tol={m.get('tol_inclus')}/{m.get('tol_total')} "
                  f"p80={m.get('err_p80_pct')} R2={m.get('metrics',{}).get('r_squared')}")
            patched.append((name, m))
        else:
            print(f"[skip] {name}: missing report or metrics")

    # Regenerate A4_summary.md from patched metrics
    cols = [
        ("run_name", "Config"),
        ("weighting_summary", "Pondération"),
        ("r2", "R²"),
        ("rmse", "RMSE"),
        ("mae", "MAE"),
        ("medrel", "MedRelErr%"),
        ("err_p80_pct", "p80%"),
        ("tol_pct", "Tol%"),
        ("geh", "GEH<5"),
        ("n", "N"),
        ("train_seconds", "TrainSec"),
        ("status", "Status"),
    ]
    lines = [
        "# Worker A4 — 14 weighting axis configs (port 7004)",
        "",
        "Dataset: `lyon_allyears.geojson` (3671 capteurs, années 2019-2025)",
        "Baseline: mse, drp=0.025, ep=1000, neurons=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05",
        "",
        "Quality gates: tol_total>0, barplot not broken, p80 finite, R²>0.",
        "",
        "| " + " | ".join(c[1] for c in cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for name, m in patched:
        mm = m.get("metrics", {}) or {}
        tol_pct = (
            100.0 * m.get("tol_inclus", 0) / max(m.get("tol_total", 0), 1)
            if m.get("tol_total") else float("nan")
        )
        status = (
            "OK" if (m.get("tol_total", 0) > 0
                     and not m.get("barplot_broken", False)
                     and m.get("err_p80_pct") == m.get("err_p80_pct")
                     and (mm.get("r_squared") or 0) > 0)
            else "REPORT-BROKEN"
        )
        cells_data = {
            "run_name": name,
            "weighting_summary": m.get("weighting_summary") or m.get("config", {}).get("weighting_summary", ""),
            "r2": mm.get("r_squared"),
            "rmse": mm.get("rmse"),
            "mae": mm.get("mae"),
            "medrel": mm.get("median_relative_error"),
            "err_p80_pct": m.get("err_p80_pct"),
            "tol_pct": tol_pct,
            "geh": mm.get("geh_pct_below_5"),
            "n": mm.get("n_samples"),
            "train_seconds": m.get("train_seconds"),
            "status": status,
        }
        cells = []
        for key, _ in cols:
            v = cells_data.get(key, "")
            if isinstance(v, float):
                if v != v:
                    cells.append("nan")
                elif key in ("train_seconds",):
                    cells.append(f"{v:.0f}")
                else:
                    cells.append(f"{v:.4f}")
            else:
                cells.append(str(v) if v is not None else "")
        lines.append("| " + " | ".join(cells) + " |")

    (BATCH_DIR / "A4_summary.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] patched {len(patched)} runs; summary at {BATCH_DIR / 'A4_summary.md'}")


if __name__ == "__main__":
    main()
