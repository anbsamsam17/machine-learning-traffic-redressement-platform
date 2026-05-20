"""Worker A3 — Phase 5 architecture ablation grid.

Each `cfg` already specifies a fully-instantiated training config — there is
no Cartesian expansion. Phase 3 fields (optimizer / weight_decay / clipnorm
/ use_skip_connection / norm_layer / dropout_schedule / activation) are
embedded directly in the request body and consumed by the patched training
pipeline (services/ml/training_pipeline.py:_train_single + generate_all_combinations).

Usage:
    python run_phase05_worker.py --port 7003 --agent-id A3 --configs configs_A3.json

Outputs to .playwright-mcp/MDL_Lyon_TV_Final/<run_name>/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4, "2023": 5, "2024": 6, "2025": 7}
PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
DEFAULT_DATASET = PROJECT_ROOT / ".playwright-mcp/DataApprentissage/GrandLyon/BCFCDREF_AllYears_TV.geojson"
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp/MDL_Lyon_TV_Final"

RAW_FEATURES = {"year_mapped", "functional_class", "flag_permanent", "flag_recent_year",
                "fc_1", "fc_2", "fc_3", "fc_4", "fc_5"}


def _api(port: int, path: str) -> str:
    return f"http://localhost:{port}{path}"


def _on_off_for(cols: list[str]) -> list[bool]:
    return [c not in RAW_FEATURES for c in cols]


def _preprocess_geojson(src: Path, recent_year: int = 2025) -> Path:
    """Inject flag_permanent, flag_recent_year, year_mapped columns."""
    import geopandas as gpd
    import pandas as pd

    out_dir = BATCH_DIR / "_data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{src.stem}_final.geojson"
    if out_path.exists():
        return out_path

    gdf = gpd.read_file(src)
    year_col = next(
        (c for c in ("annee", "Annee", "Year", "year") if c in gdf.columns), None
    )
    if year_col is None:
        raise ValueError(f"No annee column in {src}")
    perm_col = next(
        (c for c in ("Permanent", "permanent", "is_permanent") if c in gdf.columns),
        None,
    )

    gdf["year_mapped"] = pd.to_numeric(gdf[year_col], errors="coerce").map(
        {2019: 1, 2020: 2, 2021: 3, 2022: 4, 2023: 5, 2024: 6, 2025: 7}
    )
    gdf["flag_recent_year"] = (
        (pd.to_numeric(gdf[year_col], errors="coerce") == recent_year).astype(int)
    )

    # Bug 8 — `flag_permanent` lookup must check the categorical "Type Compteur"
    # column first (the Lyon dataset has no binary `Permanent` column at all,
    # so the previous fallback always returned all-zeros for A4 configs).
    # Order matches the data_prep._derive_flag_permanent rule on the API side
    # — permanent / siredo sensors get flag=1.
    type_col = next(
        (c for c in ("Type Compteur", "type compteur", "type_compteur", "TypeCompteur", "Type") if c in gdf.columns),
        None,
    )
    if type_col is not None:
        vals = gdf[type_col].astype(str).str.strip().str.lower()
        gdf["flag_permanent"] = vals.isin({"permanent", "siredo", "per", "tou"}).astype(int)
    elif perm_col is not None:
        # legacy fallback (binary Permanent column)
        gdf["flag_permanent"] = (
            pd.to_numeric(gdf[perm_col], errors="coerce").fillna(0).astype(int).clip(0, 1)
        )
    else:
        gdf["flag_permanent"] = 0

    # Phase 06 — derive one-hot encoded functional_class columns (fc_1..fc_5)
    # so configs that opt into one-hot FC encoding can resolve their input_cols.
    if "functional_class" in gdf.columns:
        fc = pd.to_numeric(gdf["functional_class"], errors="coerce").fillna(0).astype(int)
        for k in range(1, 6):
            gdf[f"fc_{k}"] = (fc == k).astype(int)

    gdf.to_file(out_path, driver="GeoJSON")
    return out_path


def setup_session(port: int, email: str, dataset_path: Path) -> tuple[str, str]:
    pw = "TestPass123!"
    requests.post(
        _api(port, "/api/auth/register"),
        json={"email": email, "password": pw},
        timeout=30,
    )
    r = requests.post(
        _api(port, "/api/auth/login"),
        json={"email": email, "password": pw},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    with open(dataset_path, "rb") as f:
        r = requests.post(
            _api(port, "/api/upload"),
            files={"file": (dataset_path.name, f)},
            data={"mode": "tv"},
            headers=headers,
            timeout=180,
        )
    r.raise_for_status()
    sid = r.json()["session_id"]

    r = requests.post(
        _api(port, "/api/mapping/auto"),
        json={"session_id": sid},
        headers={**headers, "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}

    extras = ["flag_permanent", "flag_recent_year", "year_mapped",
              "fc_1", "fc_2", "fc_3", "fc_4", "fc_5"]
    r = requests.put(
        _api(port, "/api/mapping/validate"),
        json={
            "session_id": sid,
            "mapping": mapping,
            "territory": "default",
            "extra_cols": extras,
        },
        headers={**headers, "Content-Type": "application/json"},
        timeout=120,
    )
    r.raise_for_status()

    with open(dataset_path, "rb") as f:
        r = requests.post(
            _api(port, "/api/evaluation/upload-validation"),
            files={"file": (dataset_path.name, f)},
            data={"session_id": sid, "column_mapping": "{}"},
            headers=headers,
            timeout=180,
        )
    r.raise_for_status()
    return token, sid


def run_one(
    port: int,
    token: str,
    sid: str,
    cfg: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = cfg["run_name"]
    short = hashlib.md5(run_name.encode()).hexdigest()[:8]
    print(f"[{run_name}] start train (server dir=r_{short})", flush=True)

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
    }
    # Forward seed for multi-seed comparisons (default 1750 if absent).
    if "seed" in cfg:
        body["seed"] = int(cfg["seed"])
    # Phase 0-5 — forward EVERY user-configurable flag from cfg to the body.
    # Without this loop the worker silently overrides advanced flags (perm /
    # recent_year weighting, log_flow, target_log_transform, scaler, embedding,
    # quantile head, hard mining, curriculum, n_seeds, etc.).
    forwarded_flags = (
        "use_flag_permanent_weighting", "flag_priority_weight",
        "use_flag_recent_year_weighting", "recent_year_priority_weight",
        "use_log_flow_weighting", "log_flow_weighting_col",
        "target_log_transform",
        "scaler",
        "use_year_embedding", "year_embedding_dim",
        "use_quantile_head",
        "use_hard_example_mining",
        "use_curriculum",
        "n_seeds",
        "tta_iter", "tta_noise_std",
    )
    for key in forwarded_flags:
        if key in cfg and cfg[key] is not None:
            body[key] = cfg[key]
    # Phase 3 architecture axes (single-valued).
    if "optimizer" in cfg:
        body["optimizer"] = cfg["optimizer"]
    if "weight_decay" in cfg:
        body["weight_decay"] = float(cfg["weight_decay"])
    if "clipnorm" in cfg and cfg["clipnorm"] is not None:
        body["clipnorm"] = float(cfg["clipnorm"])
    if cfg.get("use_skip_connection"):
        body["use_skip_connection"] = True
    if "norm_layer" in cfg and cfg["norm_layer"]:
        body["norm_layer"] = cfg["norm_layer"]
    if "dropout_schedule" in cfg:
        body["dropout_schedule"] = cfg["dropout_schedule"]

    r = requests.post(_api(port, "/api/training/start"), json=body, headers=headers, timeout=60)
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"start failed: {r.text[:300]}"}
    payload = r.json()
    task_id = payload["task_id"]
    model_dir_server = payload["output_dir"]

    t0 = time.time()
    last_status = None
    while True:
        time.sleep(3)
        try:
            r = requests.get(
                _api(port, f"/api/training/status/{task_id}"),
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except requests.RequestException:
            continue
        if r.status_code != 200:
            continue
        s = r.json()
        if s["status"] != last_status:
            last_status = s["status"]
            print(
                f"[{run_name}] {s['status']} m={s.get('current_model')}/{s.get('total_models')} ep={s.get('current_epoch')}/{s.get('total_epochs')}",
                flush=True,
            )
        if s["status"] in ("completed", "failed"):
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
        if server_models.exists()
        else []
    )
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no model at {server_models}"}
    # Pick the model with the most recent mtime. The session's models dir is
    # shared across all training calls, so sub_dirs accumulates one folder
    # per config; picking [0] alphabetically returned the wrong (first-trained)
    # model for every config after the first, producing byte-identical metrics
    # across distinct architectures (R²=0.665 for everything regardless).
    sub_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    actual = sub_dirs[0].name

    eval_body = {
        "session_id": sid,
        "model_name": actual,
        "model_dir": str(server_models),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
        "bootstrap_iter": 1000,
    }
    r = requests.post(
        _api(port, "/api/evaluation/run?bootstrap_iter=1000"),
        json=eval_body,
        headers=headers,
        timeout=900,
    )
    if r.status_code != 200:
        # fallback w/o query param
        r = requests.post(
            _api(port, "/api/evaluation/run"),
            json=eval_body,
            headers=headers,
            timeout=900,
        )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"eval failed: {r.text[:300]}"}
    metrics = r.json()["metrics"]

    r = requests.get(
        _api(port, f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed: {r.text[:200]}"}
    html = r.json()["report_html"]

    # Robust to inline <small> annotations introduced by CI95 enhancement.
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)',
        html,
    )
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([\d.]+)\s*%',
        html,
    )
    if m_inclus:
        tol_in = int(m_inclus.group(1))
        tol_total = int(m_inclus.group(2))
    else:
        tol_in, tol_total = 0, 0
    try:
        p80_val = float(m_p80.group(1)) if m_p80 else float("nan")
    except ValueError:
        p80_val = float("nan")
    barplot_broken = "Aucune donnee disponible" in html

    target = output_dir / run_name
    target.mkdir(parents=True, exist_ok=True)
    src_model = server_models / actual
    dst_model = target / "model"
    if dst_model.exists():
        shutil.rmtree(dst_model)
    shutil.copytree(src_model, dst_model)
    (target / "report.html").write_text(html, encoding="utf-8")

    summary = {
        "run_name": run_name,
        "actual_model_name": actual,
        "config": cfg,
        "input_cols": inputs,
        "metrics": metrics,
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "train_seconds": round(train_elapsed, 1),
    }
    (target / "metrics.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    _write_readme(target, cfg, summary)

    health = (
        "OK" if (tol_total > 0 and not barplot_broken and p80_val == p80_val) else "REPORT-BROKEN"
    )
    print(
        f"[{run_name}] DONE [{health}] tol={tol_in}/{tol_total} p80={p80_val} R2={metrics.get('r_squared'):.3f}",
        flush=True,
    )
    return summary


def _write_readme(target: Path, cfg: dict, summary: dict) -> None:
    m = summary["metrics"]
    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append(f"Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)")
    lines.append(f"Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV")
    lines.append("")
    lines.append("## Phase 5 — Architecture ablation")
    lines.append("| Champ | Valeur |")
    lines.append("|---|---|")
    lines.append(f"| activation | `{cfg.get('activation', 'elu')}` |")
    lines.append(f"| optimizer | `{cfg.get('optimizer', 'adam')}` |")
    lines.append(f"| weight_decay | `{cfg.get('weight_decay', 0.0)}` |")
    lines.append(f"| clipnorm | `{cfg.get('clipnorm')}` |")
    lines.append(f"| use_skip_connection | `{cfg.get('use_skip_connection', False)}` |")
    lines.append(f"| norm_layer | `{cfg.get('norm_layer')}` |")
    lines.append(f"| dropout_schedule | `{cfg.get('dropout_schedule', 'uniform')}` |")
    lines.append(f"| dropout | `{cfg.get('dropout', 0.025)}` |")
    lines.append(f"| min_nb_epochs | `{cfg.get('min_nb_epochs', 1000)}` |")
    lines.append(f"| max_epochs | `{cfg.get('max_epochs', 1250)}` |")
    lines.append(f"| neurons_factors | `{cfg.get('neurons_factors', [3, 2, 1])}` |")
    lines.append(f"| batch_size | `{cfg.get('batch_size', 256)}` |")
    lines.append(f"| learning_rate | `{cfg.get('learning_rate', 0.01)}` |")
    lines.append(f"| test_size | `{cfg.get('test_size', 0.05)}` |")
    lines.append("")
    lines.append("## Entrées (11 features)")
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
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--agent-id", required=True)
    p.add_argument("--configs", required=True)
    p.add_argument("--dataset", default=str(DEFAULT_DATASET))
    args = p.parse_args()

    src_dataset = Path(args.dataset)
    dataset_path = _preprocess_geojson(src_dataset, recent_year=2025)

    base_configs = json.loads(Path(args.configs).read_text(encoding="utf-8"))

    email = f"agent{args.agent_id.lower()}@example.com"
    token, sid = setup_session(args.port, email, dataset_path)
    print(f"[{args.agent_id}] session ready port={args.port} sid={sid}", flush=True)

    runs: list[dict[str, Any]] = []
    for cfg in base_configs:
        try:
            runs.append(run_one(args.port, token, sid, cfg, BATCH_DIR))
        except Exception as exc:  # noqa: BLE001
            runs.append({"run_name": cfg.get("run_name", "?"), "error": str(exc)})

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = BATCH_DIR / f"_summary_{args.agent_id}.json"
    summary_path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
    print(
        json.dumps({"agent": args.agent_id, "n_runs": len(runs), "summary": str(summary_path)}, indent=2),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
