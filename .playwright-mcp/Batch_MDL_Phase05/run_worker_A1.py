"""Worker A1 Phase 0-5 — loss + target ablation grid (12 configs).

Trains + evaluates 12 TV models on the Full 11 features baseline, no
weighting, on the GrandLyon BCFCDREF_AllYears_TV.geojson dataset.

Naming: A1_<loss>_<drp>_ep<ep>[_tlog]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import requests

YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4, "2023": 5, "2024": 6, "2025": 7}
PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
DATASET_PATH = (
    PROJECT_ROOT
    / ".playwright-mcp/DataApprentissage/GrandLyon/BCFCDREF_AllYears_TV.geojson"
)
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05"

# Full 11 features per the validated plan
FULL_11_INPUT_COLS = [
    "year_mapped",
    "TMJOFCDTV",
    "TMJOFCDPL",
    "functional_class",
    "avg_distance_before_m",
    "avg_distance_after_m",
    "avg_min_distance_m",
    "truck_avg_distance_m",
    "truck_avg_distance_before_m",
    "truck_avg_distance_after_m",
    "truck_avg_min_distance_m",
]
# year_mapped + functional_class are categorical -> not z-scored
RAW_FEATURES = {"year_mapped", "functional_class"}

EMAIL = "agenta1.phase05@example.com"
PASSWORD = "TestPass123!"

# Extra cols requested by the orchestrator (flag_permanent + flag_recent_year
# are derived inside data_prep.py from Type Compteur / year_mapped, but we
# still pass them through extra_cols so the user-asked fields land in the
# learning_df verbatim if available).
EXTRA_COLS = ["flag_permanent", "flag_recent_year", "year_mapped", "Type Compteur", "Annee"]


def _api(port: int, path: str) -> str:
    return f"http://localhost:{port}{path}"


def _on_off_for(cols: list[str]) -> list[bool]:
    return [c not in RAW_FEATURES for c in cols]


def setup_session(port: int) -> tuple[str, str]:
    """Login + upload + auto-map + validate. Returns (token, sid)."""
    # Login (user already registered)
    r = requests.post(
        _api(port, "/api/auth/login"),
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Upload
    with open(DATASET_PATH, "rb") as f:
        r = requests.post(
            _api(port, "/api/upload"),
            files={"file": (DATASET_PATH.name, f)},
            data={"mode": "tv"},
            headers=headers,
            timeout=300,
        )
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"[setup] session_id={sid}", flush=True)

    # Auto-map
    r = requests.post(
        _api(port, "/api/mapping/auto"),
        json={"session_id": sid},
        headers={**headers, "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}

    # Validate (with extras)
    r = requests.put(
        _api(port, "/api/mapping/validate"),
        json={
            "session_id": sid,
            "mapping": mapping,
            "territory": "default",
            "extra_cols": EXTRA_COLS,
        },
        headers={**headers, "Content-Type": "application/json"},
        timeout=120,
    )
    r.raise_for_status()
    print(f"[setup] mapping validated rows={r.json()['rows']}", flush=True)

    # Upload validation copy (in-sample evaluation)
    with open(DATASET_PATH, "rb") as f:
        r = requests.post(
            _api(port, "/api/evaluation/upload-validation"),
            files={"file": (DATASET_PATH.name, f)},
            data={"session_id": sid, "column_mapping": "{}"},
            headers=headers,
            timeout=300,
        )
    r.raise_for_status()
    print(f"[setup] validation file uploaded", flush=True)
    return token, sid


def make_run_name(cfg_entry: dict) -> str:
    drp_str = str(cfg_entry["dropout"]).replace("0.", "").rstrip("0") or "0"
    suffix = "_tlog" if cfg_entry.get("target_log_transform") else ""
    return f"A1_{cfg_entry['loss']}_{drp_str}_ep{cfg_entry['min_epochs']}{suffix}"


def build_training_body(cfg_entry: dict, sid: str, server_short_dir: str) -> dict:
    run_name = make_run_name(cfg_entry)
    inputs = FULL_11_INPUT_COLS
    on_off = _on_off_for(inputs)
    body = {
        "session_id": sid,
        "output_dir": server_short_dir,
        "model_type": "TV",
        "input_cols": inputs,
        "output_cols": ["TxPen"],
        "on_off_norm": on_off,
        "activations": ["elu"],
        "learning_rates": [0.01],
        "losses": [cfg_entry["loss"]],
        "min_nb_epochs_list": [int(cfg_entry["min_epochs"])],
        # Max epochs = min + 250 patience headroom
        "max_epochs": int(cfg_entry["min_epochs"]) + 250,
        "test_size": 0.05,
        "neurons_factors_list": [[3.0, 2.0, 1.0]],
        "use_batch_norm": False,
        "dropouts": [float(cfg_entry["dropout"])],
        "batch_sizes": [256],
        "mandatory_input_cols": [],
        "min_input_count": 0,
        "feature_subset_grid": False,
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
        # No weighting
        "use_flag_permanent_weighting": False,
        "use_flag_recent_year_weighting": False,
        "use_flag_comptage_weighting": False,
        # Phase 0-5 target transform
        "target_log_transform": bool(cfg_entry.get("target_log_transform", False)),
    }
    return body, run_name


def run_one(
    port: int,
    token: str,
    sid: str,
    cfg_entry: dict,
    bootstrap_iter: int = 1000,
) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = make_run_name(cfg_entry)
    short = hashlib.md5(run_name.encode()).hexdigest()[:8]
    server_short_dir = f"r_{short}"
    body, _ = build_training_body(cfg_entry, sid, server_short_dir)

    print(f"[{run_name}] start train (loss={cfg_entry['loss']} drp={cfg_entry['dropout']} ep={cfg_entry['min_epochs']} tlog={cfg_entry.get('target_log_transform')})", flush=True)
    try:
        r = requests.post(_api(port, "/api/training/start"), json=body, headers=headers, timeout=60)
    except Exception as exc:
        return {"run_name": run_name, "error": f"start exception: {exc}"}
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"start failed {r.status_code}: {r.text[:300]}"}
    payload = r.json()
    task_id = payload["task_id"]
    model_dir_server = payload["output_dir"]

    t0 = time.time()
    last_status = None
    timeout_s = 3600  # 60 min/model — pinball/tolerance_aware can run long
    while True:
        time.sleep(5)
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
                f"[{run_name}] {s['status']} "
                f"m={s.get('current_model')}/{s.get('total_models')} "
                f"ep={s.get('current_epoch')}/{s.get('total_epochs')}",
                flush=True,
            )
        # periodic heartbeat
        elapsed = time.time() - t0
        if int(elapsed) % 60 == 0 and elapsed > 30:
            print(
                f"[{run_name}] heartbeat t={elapsed:.0f}s ep={s.get('current_epoch')} loss={s.get('loss')}",
                flush=True,
            )
        if s["status"] in ("completed", "failed", "cancelled"):
            break
        if elapsed > timeout_s:
            print(f"[{run_name}] TIMEOUT after {timeout_s}s", flush=True)
            return {"run_name": run_name, "error": "timeout"}
    if s["status"] != "completed":
        return {"run_name": run_name, "error": s.get("error") or s["status"]}
    train_elapsed = time.time() - t0
    print(f"[{run_name}] trained in {train_elapsed:.0f}s", flush=True)

    # Find the produced model subdir. Since multiple configs share the same
    # session-level models/ dir, we must match THIS config's expected pattern.
    server_models = Path(model_dir_server)
    sub_dirs = [p for p in server_models.iterdir() if p.is_dir()] if server_models.exists() else []
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no model at {server_models}"}
    loss = cfg_entry["loss"]
    drp = cfg_entry["dropout"]
    ep = int(cfg_entry["min_epochs"])
    expected = (
        f"elu_lr0.01_ep{ep}_{loss}_drp{drp}_nf3.0x2.0x1.0_bs256_fmask_11111111111"
    )
    actual = None
    for d in sub_dirs:
        if d.name == expected:
            actual = d.name
            break
    if actual is None:
        # Fallback: prefer the most recent matching prefix
        candidates = [d for d in sub_dirs if d.name.startswith(f"elu_lr0.01_ep{ep}_{loss}_drp{drp}_")]
        if candidates:
            actual = max(candidates, key=lambda d: d.stat().st_mtime).name
        else:
            # Last-resort fallback: pick newest by mtime
            actual = max(sub_dirs, key=lambda d: d.stat().st_mtime).name
            print(
                f"[{run_name}] WARN expected '{expected}' not found among {[d.name for d in sub_dirs]}; "
                f"falling back to newest '{actual}'",
                flush=True,
            )

    # Eval
    eval_body = {
        "session_id": sid,
        "model_name": actual,
        "model_dir": str(server_models),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    try:
        r = requests.post(
            _api(port, f"/api/evaluation/run?bootstrap_iter={bootstrap_iter}"),
            json=eval_body,
            headers=headers,
            timeout=900,
        )
    except Exception as exc:
        return {"run_name": run_name, "error": f"eval exception: {exc}"}
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"eval failed {r.status_code}: {r.text[:300]}"}
    eval_resp = r.json()
    metrics = eval_resp["metrics"]
    metrics_ci95 = eval_resp.get("metrics_ci95")
    metrics_by_bucket = eval_resp.get("metrics_by_tmja_bucket") or []

    # Report HTML
    r = requests.get(
        _api(port, f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed {r.status_code}: {r.text[:300]}"}
    html = r.json()["report_html"]

    # Parse report counts. The "Capteurs tolerance inclus" value uses a
    # backslash separator (Windows-rendered HTML) and may include a "(pct%)"
    # and CI95 chip; we only need the leading "<int>\<int>" / "<int>/<int>".
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*[\\/]\s*(\d+)',
        html,
    )
    # err.rel.p80 line: "<float>%"
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([0-9.\-]+)\s*%',
        html,
    )
    if m_inclus:
        tol_in = int(m_inclus.group(1))
        tol_total = int(m_inclus.group(2))
    else:
        tol_in, tol_total = 0, 0
    if m_p80:
        try:
            p80_val = float(m_p80.group(1))
        except ValueError:
            p80_val = float("nan")
    else:
        p80_val = float("nan")
    barplot_broken = "Aucune donnee disponible" in html

    # Quality gates
    broken_reasons: list[str] = []
    if tol_total == 0:
        broken_reasons.append("tol_total==0")
    if p80_val != p80_val:  # NaN
        broken_reasons.append("p80=NaN")
    if barplot_broken:
        broken_reasons.append("barplot_broken")
    if metrics_ci95 and metrics_ci95.get("tol_in_pct"):
        lo, hi = metrics_ci95["tol_in_pct"]
        width = hi - lo
        mean_tol = (lo + hi) / 2
        if mean_tol > 0 and width / mean_tol > 0.5:
            broken_reasons.append(f"CI95_width_too_large({width:.1f}/{mean_tol:.1f})")

    # Persist
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
        "actual_model_name": actual,
        "input_cols": FULL_11_INPUT_COLS,
        "n_inputs": len(FULL_11_INPUT_COLS),
        "on_off_norm": _on_off_for(FULL_11_INPUT_COLS),
        "neurons_factors": [3.0, 2.0, 1.0],
        "dropout": float(cfg_entry["dropout"]),
        "min_epochs": int(cfg_entry["min_epochs"]),
        "batch_size": 256,
        "learning_rate": 0.01,
        "activation": "elu",
        "loss": cfg_entry["loss"],
        "test_size": 0.05,
        "use_batch_norm": False,
        # Phase 0-5 flags
        "target_log_transform": bool(cfg_entry.get("target_log_transform", False)),
        "use_flag_permanent_weighting": False,
        "use_flag_recent_year_weighting": False,
        "use_hard_example_mining": False,
        "use_curriculum": False,
        # Metrics
        "metrics": metrics,
        "metrics_ci95": metrics_ci95,
        "metrics_by_tmja_bucket": metrics_by_bucket,
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "broken": bool(broken_reasons),
        "broken_reasons": broken_reasons,
        "train_seconds": round(train_elapsed, 1),
    }
    (target / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_readme(target, cfg_entry, summary)

    health = "OK" if not broken_reasons else f"REPORT-BROKEN({','.join(broken_reasons)})"
    r2 = metrics.get("r_squared")
    r2_str = f"{r2:.3f}" if isinstance(r2, (int, float)) else "?"
    print(
        f"[{run_name}] DONE [{health}] tol={tol_in}/{tol_total} p80={p80_val} R2={r2_str} train={train_elapsed:.0f}s",
        flush=True,
    )
    return summary


def _write_readme(target: Path, cfg_entry: dict, summary: dict) -> None:
    inputs = FULL_11_INPUT_COLS
    on_off = _on_off_for(inputs)
    m = summary["metrics"]
    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append(f"Dataset: `{DATASET_PATH.name}` (Grand Lyon, 3632 capteurs, 2019-2025)")
    lines.append(f"Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)")
    lines.append("")
    lines.append("## Tables")
    lines.append(f"- Apprentissage : `{DATASET_PATH}`")
    lines.append(f"- Validation   : `{DATASET_PATH}` (in-sample)")
    lines.append("")
    lines.append("## Entrees (11 features)")
    lines.append("| Feature | Normalise | Type |")
    lines.append("|---|---|---|")
    for col, norm in zip(inputs, on_off):
        if col == "year_mapped":
            lines.append("| year_mapped | NON | Annee 2019..2025 -> 1..7 |")
        elif col == "functional_class":
            lines.append("| functional_class | NON | categoriel int 1-5 |")
        else:
            lines.append(f"| {col} | OUI (z-score) | numerique continu |")
    lines.append("")
    lines.append("## Hyperparametres")
    lines.append(f"- activation: `elu`  |  learning_rate: `0.01`  |  loss: `{cfg_entry['loss']}`")
    lines.append(
        f"- dropout: `{cfg_entry['dropout']}`  |  neurons_factors: `[3.0, 2.0, 1.0]`"
    )
    lines.append(
        f"- batch_size: `256`  |  min_nb_epochs: `{cfg_entry['min_epochs']}`  |  max_epochs: `{cfg_entry['min_epochs'] + 250}`"
    )
    lines.append(
        f"- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`"
    )
    lines.append(
        f"- target_log_transform: `{cfg_entry.get('target_log_transform', False)}`"
    )
    lines.append("")
    lines.append("## Sample weighting")
    lines.append("- INACTIF (poids = 1 partout, pas de flag_permanent / flag_recent_year)")
    lines.append("")
    lines.append("## Metriques validation")
    tol_pct = 100 * summary["tol_inclus"] / max(summary["tol_total"], 1)
    lines.append(
        f"- Capteurs tolerance inclus: **{summary['tol_inclus']}/{summary['tol_total']}** ({tol_pct:.1f}%)"
    )
    lines.append(f"- Erreur relative p80: **{summary['err_p80_pct']}%**")
    lines.append(f"- Erreur relative mediane: {m.get('median_relative_error')}%")
    r2v = m.get('r_squared')
    if isinstance(r2v, (int, float)):
        lines.append(f"- R2: {r2v:.4f}")
    else:
        lines.append(f"- R2: {r2v}")
    lines.append(f"- RMSE: {m.get('rmse')}  |  MAE: {m.get('mae')}")
    lines.append(f"- GEH < 5: {m.get('geh_pct_below_5')}%")
    lines.append(f"- N validation: {m.get('n_samples')}")
    if summary.get("metrics_ci95"):
        ci = summary["metrics_ci95"]
        lines.append("")
        lines.append("## CI95 (bootstrap 1000 iter)")
        for k in ("tol_in_pct", "p80", "r2"):
            if ci.get(k):
                lines.append(f"- {k}: [{ci[k][0]}, {ci[k][1]}]")
    lines.append("")
    lines.append(f"- Train: {summary['train_seconds']}s")
    if summary.get("broken"):
        lines.append("")
        lines.append(f"### Quality gates failed: {', '.join(summary['broken_reasons'])}")
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7001)
    p.add_argument("--configs", default=str(BATCH_DIR / "configs_A1.json"))
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--only", type=int, default=None, help="run only one config id (1-12)")
    p.add_argument("--skip-existing", action="store_true", help="skip configs whose run dir already has metrics.json")
    p.add_argument("--from", dest="from_id", type=int, default=None, help="start from config id N (inclusive)")
    args = p.parse_args()

    cfgs = json.loads(Path(args.configs).read_text(encoding="utf-8"))
    if args.only is not None:
        cfgs = [c for c in cfgs if c["id"] == args.only]
    if args.from_id is not None:
        cfgs = [c for c in cfgs if c["id"] >= args.from_id]
    if args.skip_existing:
        keep: list[dict] = []
        for c in cfgs:
            run_name = make_run_name(c)
            mpath = BATCH_DIR / run_name / "metrics.json"
            if mpath.exists():
                print(f"[{run_name}] SKIP (already exists)", flush=True)
            else:
                keep.append(c)
        cfgs = keep

    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[A1] starting batch of {len(cfgs)} configs on port {args.port}", flush=True)
    wall_t0 = time.time()
    token, sid = setup_session(args.port)
    print(f"[A1] session ready sid={sid}", flush=True)

    runs: list[dict[str, Any]] = []
    for cfg in cfgs:
        try:
            runs.append(run_one(args.port, token, sid, cfg, args.bootstrap))
        except Exception as exc:
            run_name = make_run_name(cfg)
            print(f"[{run_name}] EXCEPTION: {exc}", flush=True)
            traceback.print_exc()
            runs.append({"run_name": run_name, "error": str(exc)})

    wall_elapsed = time.time() - wall_t0
    (BATCH_DIR / "_summary_A1.json").write_text(
        json.dumps(
            {
                "wall_clock_seconds": round(wall_elapsed, 1),
                "n_runs": len(runs),
                "runs": runs,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"[A1] DONE n_runs={len(runs)} wall={wall_elapsed:.0f}s ({wall_elapsed/60:.1f}min)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
