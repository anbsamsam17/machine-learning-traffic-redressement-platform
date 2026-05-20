"""Worker A4 — Phase 5 weighting axis (14 configs).

Runs the full pipeline:
- preprocess geojson (flag_permanent, flag_recent_year, year_mapped)
- login, upload, auto-map, validate (extras: flag_permanent, flag_recent_year, year_mapped)
- upload validation dataset (same geojson)
- for each of 14 configs in configs_A4.json:
    - POST /api/training/start with weighting flags injected
    - poll /api/training/status
    - POST /api/evaluation/run?bootstrap_iter=1000
    - GET /api/evaluation/report
    - copy model dir + write metrics.json + README.md
- write _summary_A4.json + A4_summary.md

Usage: python A4_orchestrator.py
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

PORT = 7004
AGENT = "A4"
EMAIL = "agent.a4@example.com"
PW = "TestPass123!"

PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
RAW_DATASET = PROJECT_ROOT / "apps" / "web" / "public" / "test" / "lyon_allyears.geojson"
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp" / "Batch_MDL_Phase05"
CONFIGS_PATH = BATCH_DIR / "configs_A4.json"

YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4,
                "2023": 5, "2024": 6, "2025": 7}
RAW_FEATURES = {"year_mapped", "functional_class",
                "flag_permanent", "flag_recent_year"}


def _api(path: str) -> str:
    return f"http://localhost:{PORT}{path}"


def _on_off_for(cols: list[str]) -> list[bool]:
    return [c not in RAW_FEATURES for c in cols]


def _preprocess_geojson(src: Path, recent_year: int = 2025) -> Path:
    """Inject flag_permanent, flag_recent_year, year_mapped — reuse cache."""
    import geopandas as gpd
    import pandas as pd

    out_dir = BATCH_DIR / "_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{src.stem}_phase05.geojson"
    if out_path.exists():
        return out_path

    gdf = gpd.read_file(src)
    year_col = next(
        (c for c in ("annee", "Annee", "Year", "year") if c in gdf.columns), None,
    )
    if year_col is None:
        raise ValueError(f"No annee column in {src}")
    perm_col = next(
        (c for c in ("Permanent", "permanent", "is_permanent") if c in gdf.columns),
        None,
    )

    year_num = pd.to_numeric(gdf[year_col], errors="coerce")
    gdf["year_mapped"] = year_num.map(
        {2019: 1, 2020: 2, 2021: 3, 2022: 4, 2023: 5, 2024: 6, 2025: 7}
    )
    gdf["flag_recent_year"] = (year_num == recent_year).astype(int)
    if perm_col is not None:
        gdf["flag_permanent"] = (
            pd.to_numeric(gdf[perm_col], errors="coerce")
            .fillna(0).astype(int).clip(0, 1)
        )
    else:
        # Derive from "Type Compteur" if available (Permanent / Siredo → 1).
        type_col = next(
            (c for c in gdf.columns if c.strip().lower() == "type compteur"),
            None,
        )
        if type_col is not None:
            types = gdf[type_col].astype(str).str.strip().str.lower()
            mask = types.str.startswith("perman") | types.isin(["per"])
            gdf["flag_permanent"] = mask.astype(int)
        else:
            gdf["flag_permanent"] = 0

    gdf.to_file(out_path, driver="GeoJSON")
    return out_path


def setup_session(dataset_path: Path) -> tuple[str, str]:
    requests.post(
        _api("/api/auth/register"),
        json={"email": EMAIL, "password": PW},
        timeout=30,
    )
    r = requests.post(
        _api("/api/auth/login"),
        json={"email": EMAIL, "password": PW},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    with open(dataset_path, "rb") as f:
        r = requests.post(
            _api("/api/upload"),
            files={"file": (dataset_path.name, f)},
            data={"mode": "tv"},
            headers=h,
            timeout=180,
        )
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"[{AGENT}] upload OK session={sid} rows={r.json()['rows']}", flush=True)

    r = requests.post(
        _api("/api/mapping/auto"),
        json={"session_id": sid},
        headers={**h, "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}

    extras = ["flag_permanent", "flag_recent_year", "year_mapped"]
    r = requests.put(
        _api("/api/mapping/validate"),
        json={
            "session_id": sid,
            "mapping": mapping,
            "territory": "default",
            "extra_cols": extras,
        },
        headers={**h, "Content-Type": "application/json"},
        timeout=120,
    )
    r.raise_for_status()
    print(f"[{AGENT}] validate OK rows={r.json()['rows']} missing={r.json()['missing_critical']}", flush=True)

    with open(dataset_path, "rb") as f:
        r = requests.post(
            _api("/api/evaluation/upload-validation"),
            files={"file": (dataset_path.name, f)},
            data={"session_id": sid, "column_mapping": "{}"},
            headers=h,
            timeout=180,
        )
    r.raise_for_status()
    return token, sid


def run_one(token: str, sid: str, cfg: dict[str, Any]) -> dict[str, Any]:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = cfg["run_name"]
    short = hashlib.md5(run_name.encode()).hexdigest()[:8]
    print(f"\n[{run_name}] start (server dir=r_{short})", flush=True)

    inputs = cfg["input_cols"]
    body: dict[str, Any] = {
        "session_id": sid,
        "output_dir": f"r_{short}",
        "model_type": "TV",
        "input_cols": inputs,
        "output_cols": ["TxPen"],
        "on_off_norm": _on_off_for(inputs),
        "activations": [cfg.get("activation", "elu")],
        "learning_rates": [float(cfg.get("learning_rate", 0.01))],
        "losses": [cfg.get("loss", "mse")],
        "min_nb_epochs_list": [int(cfg.get("min_nb_epochs", 1000))],
        "max_epochs": int(cfg.get("max_epochs", 1250)),
        "neurons_factors_list": [cfg.get("neurons_factors", [3.0, 2.0, 1.0])],
        "use_batch_norm": False,
        "dropouts": [float(cfg.get("dropout", 0.025))],
        "batch_sizes": [int(cfg.get("batch_size", 256))],
        "mandatory_input_cols": [],
        "min_input_count": 0,
        "feature_subset_grid": False,
        "test_size": float(cfg.get("test_size", 0.05)),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
        # ---- weighting axis (core of A4) ----
        "use_flag_comptage_weighting": False,
        "use_flag_permanent_weighting": bool(cfg.get("use_flag_permanent_weighting", False)),
        "flag_priority_weight": float(cfg.get("flag_priority_weight", 1.0)),
        "use_flag_recent_year_weighting": bool(cfg.get("use_flag_recent_year_weighting", False)),
        "recent_year_priority_weight": float(cfg.get("recent_year_priority_weight", 1.0)),
        "use_log_flow_weighting": bool(cfg.get("use_log_flow_weighting", False)),
    }

    r = requests.post(_api("/api/training/start"), json=body, headers=h, timeout=60)
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"start failed: {r.text[:300]}"}
    payload = r.json()
    task_id = payload["task_id"]
    model_dir_server = payload["output_dir"]

    t0 = time.time()
    last_status = None
    last_pct = -1
    while True:
        time.sleep(3)
        try:
            r = requests.get(
                _api(f"/api/training/status/{task_id}"),
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        s = r.json()
        pct = int(s.get("progress_pct") or 0)
        if s["status"] != last_status or pct >= last_pct + 25:
            last_status = s["status"]
            last_pct = pct
            print(
                f"[{run_name}] {s['status']} {pct}% m={s.get('current_model')}/{s.get('total_models')} "
                f"ep={s.get('current_epoch')}/{s.get('total_epochs')} loss={s.get('loss')}",
                flush=True,
            )
        if s["status"] in ("completed", "failed", "cancelled"):
            break
        if time.time() - t0 > 3000:
            print(f"[{run_name}] TIMEOUT after 50min", flush=True)
            return {"run_name": run_name, "error": "timeout"}
    if s["status"] != "completed":
        return {"run_name": run_name, "error": s.get("error") or "failed"}
    train_elapsed = time.time() - t0
    print(f"[{run_name}] trained in {train_elapsed:.0f}s", flush=True)

    server_models = Path(model_dir_server)
    sub_dirs = (
        [p for p in server_models.iterdir() if p.is_dir()]
        if server_models.exists() else []
    )
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no model at {server_models}"}
    actual = sub_dirs[0].name

    eval_body = {
        "session_id": sid,
        "model_name": actual,
        "model_dir": str(server_models),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    r = requests.post(
        _api("/api/evaluation/run?bootstrap_iter=1000"),
        json=eval_body, headers=h, timeout=900,
    )
    if r.status_code != 200:
        # fallback w/o query param
        r = requests.post(
            _api("/api/evaluation/run"),
            json=eval_body, headers=h, timeout=900,
        )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"eval failed: {r.text[:300]}"}
    eval_resp = r.json()
    metrics = eval_resp.get("metrics", {})
    ci95 = eval_resp.get("metrics_ci95")

    r = requests.get(
        _api(f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed: {r.text[:200]}"}
    html = r.json()["report_html"]

    # Parse Capteurs tolerance inclus / Err. rel. p80 from HTML report.
    # Robust to <small> annotations after the metric: capture only the
    # text up to the first '<' (which may be '<small>' or '</div>').
    tol_in, tol_total = 0, 0
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*([0-9]+)\s*/\s*([0-9]+)',
        html,
    )
    if m_inclus:
        tol_in = int(m_inclus.group(1))
        tol_total = int(m_inclus.group(2))

    p80_val = float("nan")
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([0-9]+(?:\.[0-9]+)?)\s*%?',
        html,
    )
    if m_p80:
        try:
            p80_val = float(m_p80.group(1))
        except ValueError:
            p80_val = float("nan")
    barplot_broken = "Aucune donnee disponible" in html

    target = BATCH_DIR / run_name
    target.mkdir(parents=True, exist_ok=True)
    src_model = server_models / actual
    dst_model = target / "model"
    if dst_model.exists():
        shutil.rmtree(dst_model)
    shutil.copytree(src_model, dst_model)
    (target / "report.html").write_text(html, encoding="utf-8")

    summary = {
        "run_name": run_name,
        "weighting_summary": cfg.get("weighting_summary"),
        "actual_model_name": actual,
        "config": cfg,
        "input_cols": inputs,
        "metrics": metrics,
        "metrics_ci95": ci95,
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "train_seconds": round(train_elapsed, 1),
    }
    (target / "metrics.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8",
    )
    _write_readme(target, cfg, summary)

    health = (
        "OK" if (tol_total > 0 and not barplot_broken and p80_val == p80_val)
        else "REPORT-BROKEN"
    )
    print(
        f"[{run_name}] DONE [{health}] tol={tol_in}/{tol_total} p80={p80_val} "
        f"R2={metrics.get('r_squared'):.3f} RMSE={metrics.get('rmse'):.3f}",
        flush=True,
    )
    return summary


def _write_readme(target: Path, cfg: dict, summary: dict) -> None:
    m = summary["metrics"]
    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append("Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)")
    lines.append("Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV")
    lines.append("")
    lines.append("## Phase 5 — Worker A4 pondération axis")
    lines.append("| Champ | Valeur |")
    lines.append("|---|---|")
    lines.append(f"| weighting | `{cfg.get('weighting_summary','-')}` |")
    lines.append(f"| use_flag_permanent_weighting | `{cfg.get('use_flag_permanent_weighting', False)}` |")
    lines.append(f"| flag_priority_weight | `{cfg.get('flag_priority_weight', 1.0)}` |")
    lines.append(f"| use_flag_recent_year_weighting | `{cfg.get('use_flag_recent_year_weighting', False)}` |")
    lines.append(f"| recent_year_priority_weight | `{cfg.get('recent_year_priority_weight', 1.0)}` |")
    lines.append(f"| use_log_flow_weighting | `{cfg.get('use_log_flow_weighting', False)}` |")
    lines.append(f"| activation | `{cfg.get('activation', 'elu')}` |")
    lines.append(f"| dropout | `{cfg.get('dropout', 0.025)}` |")
    lines.append(f"| min_nb_epochs | `{cfg.get('min_nb_epochs', 1000)}` |")
    lines.append(f"| max_epochs | `{cfg.get('max_epochs', 1250)}` |")
    lines.append(f"| neurons_factors | `{cfg.get('neurons_factors', [3, 2, 1])}` |")
    lines.append(f"| batch_size | `{cfg.get('batch_size', 256)}` |")
    lines.append(f"| learning_rate | `{cfg.get('learning_rate', 0.01)}` |")
    lines.append(f"| test_size | `{cfg.get('test_size', 0.05)}` |")
    lines.append("")
    lines.append(f"## Entrées ({len(cfg['input_cols'])} features)")
    lines.append("```")
    for c in cfg["input_cols"]:
        lines.append(f"- {c}")
    lines.append("```")
    lines.append("")
    lines.append("## Métriques de validation (sur 3671 capteurs)")
    tt = max(summary["tol_total"], 1)
    lines.append(
        f"- Capteurs tolérance inclus: **{summary['tol_inclus']}/{summary['tol_total']}** "
        f"({100 * summary['tol_inclus'] / tt:.1f}%)"
    )
    lines.append(f"- Erreur relative p80: **{summary['err_p80_pct']}%**")
    if m.get("median_relative_error") is not None:
        lines.append(f"- Erreur relative médiane: {m['median_relative_error']}%")
    if m.get("r_squared") is not None:
        lines.append(f"- R²: {m['r_squared']:.4f}")
    if m.get("rmse") is not None:
        lines.append(f"- RMSE: {m['rmse']}")
    if m.get("mae") is not None:
        lines.append(f"- MAE: {m['mae']}")
    if m.get("geh_pct_below_5") is not None:
        lines.append(f"- GEH < 5: {m['geh_pct_below_5']}%")
    if m.get("n_samples") is not None:
        lines.append(f"- N validation rows: {m['n_samples']}")
    lines.append(f"- Durée d'entraînement: {summary['train_seconds']}s")
    if summary.get("metrics_ci95"):
        lines.append("")
        lines.append("## CI95 (bootstrap=1000)")
        for k, v in summary["metrics_ci95"].items():
            if v is None:
                continue
            lo, hi = v
            lines.append(f"- {k}: [{lo:.4f}, {hi:.4f}]")
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_agent_summary(rows: list[dict]) -> None:
    p = BATCH_DIR / f"_summary_{AGENT}.json"
    p.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    md = BATCH_DIR / f"{AGENT}_summary.md"
    cols = [
        ("run_name", "Config"),
        ("weighting_summary", "Pondération"),
        ("r_squared", "R²"),
        ("rmse", "RMSE"),
        ("mae", "MAE"),
        ("median_relative_error", "MedRelErr%"),
        ("err_p80_pct", "p80%"),
        ("tol_pct", "Tol%"),
        ("geh_pct_below_5", "GEH<5"),
        ("n_samples", "N"),
        ("train_seconds", "TrainSec"),
        ("status", "Status"),
    ]
    lines = [
        f"# Worker {AGENT} — 14 weighting axis configs (port {PORT})",
        "",
        "Dataset: `lyon_allyears.geojson` (3671 capteurs, années 2019-2025)",
        "Baseline: mse, drp=0.025, ep=1000, neurons=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05",
        "",
        "Quality gates: tol_total>0, barplot not broken, p80 finite, R² > 0.",
        "",
        "| " + " | ".join(c[1] for c in cols) + " |",
        "|" + "|".join(["---"] * len(cols)) + "|",
    ]
    for r in rows:
        m = r.get("metrics", {}) or {}
        tol_pct = (
            100.0 * r.get("tol_inclus", 0) / max(r.get("tol_total", 0), 1)
            if r.get("tol_total") else float("nan")
        )
        status = "FAIL" if r.get("error") else (
            "OK" if (r.get("tol_total", 0) > 0
                     and not r.get("barplot_broken", False)
                     and r.get("err_p80_pct") == r.get("err_p80_pct")
                     and (m.get("r_squared") or 0) > 0) else "REPORT-BROKEN"
        )
        row = {
            "run_name": r.get("run_name"),
            "weighting_summary": r.get("weighting_summary", ""),
            "r_squared": m.get("r_squared"),
            "rmse": m.get("rmse"),
            "mae": m.get("mae"),
            "median_relative_error": m.get("median_relative_error"),
            "err_p80_pct": r.get("err_p80_pct"),
            "tol_pct": tol_pct,
            "geh_pct_below_5": m.get("geh_pct_below_5"),
            "n_samples": m.get("n_samples"),
            "train_seconds": r.get("train_seconds"),
            "status": status if not r.get("error") else f"FAIL: {r.get('error')[:40]}",
        }
        cells = []
        for key, _ in cols:
            v = row.get(key, "")
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
    md.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    print(f"[{AGENT}] port={PORT} batch_dir={BATCH_DIR}", flush=True)
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    dataset_path = _preprocess_geojson(RAW_DATASET, recent_year=2025)
    print(f"[{AGENT}] dataset={dataset_path}", flush=True)

    configs = json.loads(CONFIGS_PATH.read_text(encoding="utf-8"))
    print(f"[{AGENT}] {len(configs)} configs to run", flush=True)

    token, sid = setup_session(dataset_path)
    print(f"[{AGENT}] session ready sid={sid}", flush=True)

    runs: list[dict[str, Any]] = []
    for idx, cfg in enumerate(configs, start=1):
        run_name = cfg["run_name"]
        target = BATCH_DIR / run_name
        if (target / "metrics.json").exists():
            print(f"[{idx}/{len(configs)}] SKIP {run_name} (already done)", flush=True)
            try:
                runs.append(json.loads((target / "metrics.json").read_text(encoding="utf-8")))
            except Exception:
                pass
            _write_agent_summary(runs)
            continue
        print(f"\n[{idx}/{len(configs)}] >>> {run_name}", flush=True)
        try:
            res = run_one(token, sid, cfg)
        except Exception as exc:  # noqa: BLE001
            res = {"run_name": run_name, "error": str(exc)}
        runs.append(res)
        _write_agent_summary(runs)

    print(json.dumps(
        {"agent": AGENT, "n_runs": len(runs), "out": str(BATCH_DIR)},
        indent=2,
    ), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
