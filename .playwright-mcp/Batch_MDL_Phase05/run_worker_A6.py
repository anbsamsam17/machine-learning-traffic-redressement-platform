"""Worker A6 Phase 0-5 — winning-combinations grid + TTA (14 configs).

Baseline: Full 11 features, drp=0.025, ep=1000, neurons_factors=[3,2,1],
lr=0.01, batch=256, elu, test_size=0.05.

Configs 1-10: train new models with different weighting / optimizer /
architecture / scaler / feature-engineering flags.

Configs 11-14: re-evaluate existing models (from configs 1, 3, 4, 9) with
tta_iter=5, tta_noise_std=0.01 (no re-training).

Naming: A6_<descriptor> (one folder per config under Batch_MDL_Phase05/).
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

# Full 11 features (Phase 0-5 baseline)
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
# year_mapped + functional_class are categorical -> not z-scored.
# Derived features: ratio_PLTV (continuous, normalized), log_<col> (continuous, normalized).
RAW_FEATURES = {"year_mapped", "functional_class"}

# Seed user already created at API boot (see app/main.py)
EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"

EXTRA_COLS = [
    "flag_permanent",
    "flag_recent_year",
    "year_mapped",
    "Type Compteur",
    "Annee",
    # Kept available so feature-engineering can pick them up later:
    "TMJOFCDTV",
    "TMJOFCDPL",
]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _api(port: int, path: str) -> str:
    return f"http://localhost:{port}{path}"


def _on_off_for(cols: list[str]) -> list[bool]:
    """True (normalize) for every column NOT in RAW_FEATURES."""
    return [c not in RAW_FEATURES for c in cols]


# ---------------------------------------------------------------------------
# Setup phase: login -> upload -> auto-map -> validate -> upload validation
# ---------------------------------------------------------------------------

def setup_session(port: int) -> tuple[str, str]:
    """Login + upload + auto-map + validate. Returns (token, sid)."""
    r = requests.post(
        _api(port, "/api/auth/login"),
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

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

    r = requests.post(
        _api(port, "/api/mapping/auto"),
        json={"session_id": sid},
        headers={**headers, "Content-Type": "application/json"},
        timeout=60,
    )
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}

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

    # Validation file (in-sample evaluation: same data as training)
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


# ---------------------------------------------------------------------------
# Training body builder
# ---------------------------------------------------------------------------

def _build_inputs(cfg_entry: dict) -> tuple[list[str], list[bool]]:
    """Return (input_cols, on_off_norm) — Full 11 + optional derived features."""
    extras = list(cfg_entry.get("extra_input_cols") or [])
    inputs = list(FULL_11_INPUT_COLS)
    for e in extras:
        if e not in inputs:
            inputs.append(e)
    return inputs, _on_off_for(inputs)


def build_training_body(cfg_entry: dict, sid: str, server_short_dir: str) -> dict:
    """Build the JSON body POSTed to /api/training/start for a TRAIN config."""
    inputs, on_off = _build_inputs(cfg_entry)

    feature_engineering: dict[str, Any] = {}
    if cfg_entry.get("add_pl_tv_ratio"):
        feature_engineering["add_pl_tv_ratio"] = True
    if cfg_entry.get("log_transform_cols"):
        feature_engineering["log_transform_cols"] = list(cfg_entry["log_transform_cols"])

    body: dict[str, Any] = {
        "session_id": sid,
        "output_dir": server_short_dir,
        "model_type": "TV",
        "input_cols": inputs,
        "output_cols": ["TxPen"],
        "on_off_norm": on_off,
        "activations": ["elu"],
        "learning_rates": [0.01],
        "losses": [cfg_entry.get("loss", "mse")],
        "min_nb_epochs_list": [1000],
        "max_epochs": 1250,
        "test_size": 0.05,
        "neurons_factors_list": [[3.0, 2.0, 1.0]],
        "use_batch_norm": False,
        "dropouts": [0.025],
        "batch_sizes": [256],
        "mandatory_input_cols": [],
        "min_input_count": 0,
        "feature_subset_grid": False,
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
        # weighting flags (default OFF; per-config overrides below)
        "use_flag_permanent_weighting": bool(cfg_entry.get("use_flag_permanent_weighting", False)),
        "flag_priority_weight": float(cfg_entry.get("flag_priority_weight", 4.0)),
        "use_flag_recent_year_weighting": bool(cfg_entry.get("use_flag_recent_year_weighting", False)),
        "recent_year_priority_weight": float(cfg_entry.get("recent_year_priority_weight", 2.0)),
        # Backward-compat alias
        "use_flag_comptage_weighting": bool(cfg_entry.get("use_flag_permanent_weighting", False)),
        "target_log_transform": False,
    }

    # Optimizer / architecture flags (P3)
    if cfg_entry.get("optimizer"):
        body["optimizer"] = cfg_entry["optimizer"]
    if cfg_entry.get("weight_decay") is not None:
        body["weight_decay"] = float(cfg_entry["weight_decay"])
    if cfg_entry.get("use_skip_connection"):
        body["use_skip_connection"] = True
    if cfg_entry.get("norm_layer"):
        body["norm_layer"] = cfg_entry["norm_layer"]

    # Year embedding (Config 8)
    if cfg_entry.get("year_embedding"):
        body["year_embedding"] = True
        if cfg_entry.get("year_embedding_dim"):
            body["year_embedding_dim"] = int(cfg_entry["year_embedding_dim"])

    # Scaler (Config 7) — passed both at top level and inside feature_engineering
    # so any future plumbing picks it up. Currently no-op in training_pipeline.
    if cfg_entry.get("scaler"):
        body["scaler"] = cfg_entry["scaler"]
        feature_engineering["scaler"] = cfg_entry["scaler"]

    # Multi-seed (Config 10)
    if cfg_entry.get("n_seeds"):
        body["n_seeds"] = int(cfg_entry["n_seeds"])

    if feature_engineering:
        body["feature_engineering"] = feature_engineering
        # Also mirror the flags at top-level so data_prep.py picks them up
        # regardless of which key path it inspects.
        for k, v in feature_engineering.items():
            body[k] = v

    return body


# ---------------------------------------------------------------------------
# Train + evaluate one config
# ---------------------------------------------------------------------------

def run_train(
    port: int,
    token: str,
    sid: str,
    cfg_entry: dict,
    bootstrap_iter: int = 1000,
) -> dict:
    """Train a single model + run evaluation + persist artifacts."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = cfg_entry["name"]
    short = hashlib.md5(run_name.encode()).hexdigest()[:8]
    server_short_dir = f"r_{short}"
    body = build_training_body(cfg_entry, sid, server_short_dir)

    print(
        f"[{run_name}] start train (loss={cfg_entry.get('loss')} "
        f"perm={cfg_entry.get('use_flag_permanent_weighting')}x{cfg_entry.get('flag_priority_weight')} "
        f"rec={cfg_entry.get('use_flag_recent_year_weighting')}x{cfg_entry.get('recent_year_priority_weight')} "
        f"opt={cfg_entry.get('optimizer')} skip={cfg_entry.get('use_skip_connection')})",
        flush=True,
    )
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
    timeout_s = 5400  # 90 min/run (n_seeds=3 + skip/AdamW take longer)
    last_heartbeat = 0
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
        elapsed = time.time() - t0
        if elapsed - last_heartbeat >= 60:
            last_heartbeat = elapsed
            print(
                f"[{run_name}] heartbeat t={elapsed:.0f}s "
                f"m={s.get('current_model')}/{s.get('total_models')} "
                f"ep={s.get('current_epoch')} loss={s.get('loss')}",
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

    # Locate produced model subdir. The API output_dir is session-scoped, so
    # the directory accumulates models from EVERY config in this batch. We must
    # only evaluate / persist the model(s) produced by THIS config's training,
    # identified by mtime > train_start (model.keras and training_config.json
    # are written at the END of training, so their mtime > t0).
    server_models = Path(model_dir_server)
    all_dirs = [p for p in server_models.iterdir() if p.is_dir()] if server_models.exists() else []
    # Filter: keep only model dirs whose model.keras (or training_metrics.json)
    # was modified within the train window. We use the START time t0 (epoch
    # seconds) and a slack of 5s so any pre-existing dir is excluded reliably.
    fresh_threshold = t0 - 5
    sub_dirs: list[Path] = []
    for p in all_dirs:
        marker = p / "training_metrics.json"
        try:
            if marker.exists() and marker.stat().st_mtime >= fresh_threshold:
                sub_dirs.append(p)
        except OSError:
            continue
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no fresh model at {server_models}"}

    actual_models = sorted(p.name for p in sub_dirs)
    actual = actual_models[0]
    target = BATCH_DIR / run_name
    target.mkdir(parents=True, exist_ok=True)

    # Evaluate every saved model. We average tol/p80/R² over seeds and keep
    # the FIRST seed's metrics for the README header.
    eval_per_seed: list[dict] = []
    for sub in sub_dirs:
        eval_body = {
            "session_id": sid,
            "model_name": sub.name,
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
            eval_per_seed.append({"model_name": sub.name, "error": f"eval exception: {exc}"})
            continue
        if r.status_code != 200:
            eval_per_seed.append({"model_name": sub.name, "error": f"eval failed {r.status_code}: {r.text[:300]}"})
            continue
        eval_per_seed.append({"model_name": sub.name, "response": r.json()})

    # Report HTML from the most recent /api/evaluation/run call (session-scoped).
    r = requests.get(
        _api(port, f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed {r.status_code}: {r.text[:300]}"}
    html = r.json()["report_html"]
    (target / "report.html").write_text(html, encoding="utf-8")

    # Parse report counts
    tol_in, tol_total, p80_val, barplot_broken = _parse_report_counts(html)

    # Persist EVERY model directory and write its own metrics file.
    # We also keep a server-side BACKUP under a config-unique path so the TTA
    # re-eval (configs 11-14) can find the parent's model even after a later
    # config with the same hyperparam signature overwrites the original.
    server_backup = server_models.parent / f"models_backup_{run_name}"
    if server_backup.exists():
        shutil.rmtree(server_backup)
    server_backup.mkdir(parents=True, exist_ok=True)

    summary_seeds: list[dict] = []
    for ev in eval_per_seed:
        sub_name = ev["model_name"]
        src_model = server_models / sub_name
        dst_model = target / "model" if len(sub_dirs) == 1 else target / sub_name
        if dst_model.exists():
            shutil.rmtree(dst_model)
        try:
            shutil.copytree(src_model, dst_model)
        except shutil.Error as exc:  # noqa: PERF203 — defensive
            # File missing mid-copy (race) — copy what we can and move on so
            # the rest of the config's bookkeeping still completes.
            logger_print = lambda *a, **k: print(*a, **k)
            logger_print(f"[{run_name}] copytree warning: {exc}", flush=True)
        # Backup copy in the API-side workspace so TTA configs can locate the
        # exact model even after a later config overwrites the API-side dir.
        backup_dst = server_backup / sub_name
        try:
            shutil.copytree(src_model, backup_dst, dirs_exist_ok=True)
        except (shutil.Error, OSError) as exc:
            print(f"[{run_name}] backup copy warning: {exc}", flush=True)
        if "response" in ev:
            metrics = ev["response"]["metrics"]
            summary_seeds.append({
                "model_name": sub_name,
                "metrics": metrics,
                "metrics_ci95": ev["response"].get("metrics_ci95"),
            })
        else:
            summary_seeds.append({"model_name": sub_name, "error": ev.get("error")})

    # Pick the "primary" metrics: first seed by name, falling back to any
    # successful evaluation.
    primary = next((s for s in summary_seeds if "metrics" in s), summary_seeds[0])
    metrics = primary.get("metrics") or {}
    metrics_ci95 = primary.get("metrics_ci95")

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
        mean_tol = (lo + hi) / 2 if (lo + hi) else 0
        if mean_tol > 0 and width / mean_tol > 0.5:
            broken_reasons.append(f"CI95_width_too_large({width:.1f}/{mean_tol:.1f})")

    summary = {
        "run_name": run_name,
        "config_id": cfg_entry.get("id"),
        "actual_model_names": actual_models,
        "input_cols": _build_inputs(cfg_entry)[0],
        "n_inputs": len(_build_inputs(cfg_entry)[0]),
        "on_off_norm": _build_inputs(cfg_entry)[1],
        "neurons_factors": [3.0, 2.0, 1.0],
        "dropout": 0.025,
        "min_epochs": 1000,
        "max_epochs": 1250,
        "batch_size": 256,
        "learning_rate": 0.01,
        "activation": "elu",
        "loss": cfg_entry.get("loss", "mse"),
        "test_size": 0.05,
        "use_batch_norm": False,
        # Per-config flags echoed for the index
        "optimizer": cfg_entry.get("optimizer"),
        "weight_decay": cfg_entry.get("weight_decay"),
        "use_skip_connection": bool(cfg_entry.get("use_skip_connection", False)),
        "norm_layer": cfg_entry.get("norm_layer"),
        "scaler": cfg_entry.get("scaler"),
        "use_year_embedding": bool(cfg_entry.get("year_embedding", False)),
        "use_flag_permanent_weighting": bool(cfg_entry.get("use_flag_permanent_weighting", False)),
        "flag_priority_weight": float(cfg_entry.get("flag_priority_weight", 4.0)),
        "use_flag_recent_year_weighting": bool(cfg_entry.get("use_flag_recent_year_weighting", False)),
        "recent_year_priority_weight": float(cfg_entry.get("recent_year_priority_weight", 2.0)),
        "add_pl_tv_ratio": bool(cfg_entry.get("add_pl_tv_ratio", False)),
        "log_transform_cols": list(cfg_entry.get("log_transform_cols") or []),
        "n_seeds": int(cfg_entry.get("n_seeds", 1)),
        # Metrics (primary seed)
        "metrics": metrics,
        "metrics_ci95": metrics_ci95,
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "broken": bool(broken_reasons),
        "broken_reasons": broken_reasons,
        "train_seconds": round(train_elapsed, 1),
        # Per-seed detail (n_seeds>1 only)
        "per_seed_metrics": summary_seeds if len(summary_seeds) > 1 else None,
        # Server path so TTA reruns can find the model later. We prefer the
        # backup dir (config-unique) over the session-scoped one (which a
        # later config can overwrite).
        "server_model_dir": str(server_models),
        "server_backup_dir": str(server_backup),
        "produced_model_names": actual_models,
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


# ---------------------------------------------------------------------------
# TTA re-evaluation (configs 11-14)
# ---------------------------------------------------------------------------

def run_tta_reeval(
    port: int,
    token: str,
    sid: str,
    cfg_entry: dict,
    parent_summary: dict,
    bootstrap_iter: int = 1000,
) -> dict:
    """Re-run /api/evaluation/run on the EXISTING parent model with TTA params."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = cfg_entry["name"]
    tta_iter = int(cfg_entry.get("tta_iter", 5))
    tta_noise_std = float(cfg_entry.get("tta_noise_std", 0.01))
    # Prefer the config-unique backup dir; fall back to the session-scoped
    # dir if the backup is missing (e.g. when re-running TTA on an old
    # batch where the worker did not yet maintain backups).
    backup_str = parent_summary.get("server_backup_dir")
    server_models = Path(backup_str) if backup_str else Path(parent_summary["server_model_dir"])
    if not server_models.exists():
        # Fall back to session-scoped dir if backup missing.
        server_models = Path(parent_summary["server_model_dir"])
    if not server_models.exists():
        return {"run_name": run_name, "error": f"parent server_model_dir missing: {server_models}"}

    # Pick the model produced by THIS parent — first by produced_model_names
    # if available, otherwise the alphabetically-first dir.
    produced = parent_summary.get("produced_model_names") or []
    sub_dirs: list[Path] = []
    for name in produced:
        candidate = server_models / name
        if candidate.is_dir():
            sub_dirs.append(candidate)
    if not sub_dirs:
        sub_dirs = [p for p in server_models.iterdir() if p.is_dir()]
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no model under {server_models}"}

    # Evaluate first subdir only (TTA on a single model is sufficient for the comparison).
    actual = sub_dirs[0].name
    eval_body = {
        "session_id": sid,
        "model_name": actual,
        "model_dir": str(server_models),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    print(
        f"[{run_name}] TTA re-eval parent={parent_summary['run_name']} "
        f"tta_iter={tta_iter} tta_noise_std={tta_noise_std}",
        flush=True,
    )
    t0 = time.time()
    url = (
        f"/api/evaluation/run?bootstrap_iter={bootstrap_iter}"
        f"&tta_iter={tta_iter}&tta_noise_std={tta_noise_std}"
    )
    try:
        r = requests.post(_api(port, url), json=eval_body, headers=headers, timeout=900)
    except Exception as exc:
        return {"run_name": run_name, "error": f"tta eval exception: {exc}"}
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"tta eval failed {r.status_code}: {r.text[:300]}"}
    eval_resp = r.json()
    metrics = eval_resp["metrics"]
    metrics_ci95 = eval_resp.get("metrics_ci95")

    # Pull the report (TTA flavored)
    r = requests.get(
        _api(port, f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed {r.status_code}: {r.text[:300]}"}
    html = r.json()["report_html"]

    target = BATCH_DIR / run_name
    target.mkdir(parents=True, exist_ok=True)
    (target / "report.html").write_text(html, encoding="utf-8")

    tol_in, tol_total, p80_val, barplot_broken = _parse_report_counts(html)
    eval_elapsed = time.time() - t0

    broken_reasons: list[str] = []
    if tol_total == 0:
        broken_reasons.append("tol_total==0")
    if p80_val != p80_val:
        broken_reasons.append("p80=NaN")
    if barplot_broken:
        broken_reasons.append("barplot_broken")

    summary = {
        "run_name": run_name,
        "config_id": cfg_entry.get("id"),
        "mode": "tta_reeval",
        "parent_run_name": parent_summary["run_name"],
        "parent_config_id": parent_summary.get("config_id"),
        "tta_iter": tta_iter,
        "tta_noise_std": tta_noise_std,
        "actual_model_name": actual,
        "metrics": metrics,
        "metrics_ci95": metrics_ci95,
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "broken": bool(broken_reasons),
        "broken_reasons": broken_reasons,
        "eval_seconds": round(eval_elapsed, 1),
        "parent_metrics": parent_summary.get("metrics"),
        "parent_tol_inclus": parent_summary.get("tol_inclus"),
        "parent_tol_total": parent_summary.get("tol_total"),
        "parent_err_p80_pct": parent_summary.get("err_p80_pct"),
    }
    (target / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _write_readme_tta(target, cfg_entry, summary)

    health = "OK" if not broken_reasons else f"REPORT-BROKEN({','.join(broken_reasons)})"
    r2 = metrics.get("r_squared")
    r2_str = f"{r2:.3f}" if isinstance(r2, (int, float)) else "?"
    print(
        f"[{run_name}] DONE [{health}] tol={tol_in}/{tol_total} p80={p80_val} "
        f"R2={r2_str} eval={eval_elapsed:.0f}s",
        flush=True,
    )
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_report_counts(html: str) -> tuple[int, int, float, bool]:
    # The report wraps the value in <div class="v">N/total <small>...</small></div>
    # so we extract just the "N/total" pair, tolerant to CI95 / pct annotations.
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)',
        html,
    )
    # Err. rel. p80 can be "32.46%", "32.46% <small>...</small>", or "-"
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([\-\d.]+)\s*%?',
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
    return tol_in, tol_total, p80_val, barplot_broken


def _write_readme(target: Path, cfg_entry: dict, summary: dict) -> None:
    m = summary["metrics"] or {}
    inputs = summary["input_cols"]
    on_off = summary["on_off_norm"]

    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append(f"Dataset: `{DATASET_PATH.name}` (Grand Lyon, 3632 capteurs, 2019-2025)")
    lines.append(f"Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)")
    lines.append("")
    lines.append("## Stack")
    lines.append(f"- loss: `{summary['loss']}`")
    if summary.get("optimizer"):
        lines.append(
            f"- optimizer: `{summary['optimizer']}` (weight_decay={summary.get('weight_decay')})"
        )
    if summary.get("use_skip_connection"):
        lines.append("- skip_connection: ON")
    if summary.get("norm_layer"):
        lines.append(f"- norm_layer: `{summary['norm_layer']}`")
    if summary.get("scaler"):
        lines.append(f"- scaler: `{summary['scaler']}` (note: API plumbing best-effort)")
    if summary.get("use_year_embedding"):
        lines.append("- year_embedding: ON (note: API plumbing best-effort)")
    if summary.get("add_pl_tv_ratio"):
        lines.append("- feature_engineering.add_pl_tv_ratio: ON (ratio_PLTV)")
    if summary.get("log_transform_cols"):
        lines.append(f"- feature_engineering.log_transform_cols: {summary['log_transform_cols']}")
    if summary.get("n_seeds", 1) > 1:
        lines.append(f"- n_seeds: {summary['n_seeds']}")
    lines.append("")
    lines.append("## Weighting")
    lines.append(
        f"- flag_permanent: {summary['use_flag_permanent_weighting']} "
        f"(x{summary['flag_priority_weight']})"
    )
    lines.append(
        f"- flag_recent_year: {summary['use_flag_recent_year_weighting']} "
        f"(x{summary['recent_year_priority_weight']})"
    )
    lines.append("")
    lines.append(f"## Entrees ({len(inputs)} features)")
    lines.append("| Feature | Normalise | Type |")
    lines.append("|---|---|---|")
    for col, norm in zip(inputs, on_off):
        if col == "year_mapped":
            lines.append("| year_mapped | NON | Annee 2019..2025 -> 1..7 |")
        elif col == "functional_class":
            lines.append("| functional_class | NON | categoriel int 1-5 |")
        elif col.startswith("log_"):
            lines.append(f"| {col} | OUI | derive log1p |")
        elif col == "ratio_PLTV":
            lines.append("| ratio_PLTV | OUI | derive TMJOFCDPL/max(TMJOFCDTV,1) |")
        else:
            lines.append(f"| {col} | {'OUI' if norm else 'NON'} | numerique continu |")
    lines.append("")
    lines.append("## Hyperparametres")
    lines.append("- activation: `elu`  |  learning_rate: `0.01`")
    lines.append("- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`")
    lines.append("- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`")
    lines.append("- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`")
    lines.append("")
    lines.append("## Metriques validation (in-sample)")
    tol_pct = 100 * summary["tol_inclus"] / max(summary["tol_total"], 1)
    lines.append(
        f"- Capteurs tolerance inclus: **{summary['tol_inclus']}/{summary['tol_total']}** ({tol_pct:.1f}%)"
    )
    lines.append(f"- Erreur relative p80: **{summary['err_p80_pct']}%**")
    lines.append(f"- Erreur relative mediane: {m.get('median_relative_error')}%")
    r2v = m.get("r_squared")
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
    if summary.get("per_seed_metrics"):
        lines.append("")
        lines.append("## Per-seed (n_seeds > 1)")
        for s in summary["per_seed_metrics"]:
            if "metrics" in s:
                mm = s["metrics"]
                lines.append(
                    f"- {s['model_name']}: R2={mm.get('r_squared')} RMSE={mm.get('rmse')} "
                    f"MAE={mm.get('mae')} p80={mm.get('median_relative_error')}"
                )
            else:
                lines.append(f"- {s['model_name']}: ERROR {s.get('error')}")
    lines.append("")
    lines.append(f"- Train: {summary['train_seconds']}s")
    if summary.get("broken"):
        lines.append("")
        lines.append(f"### Quality gates failed: {', '.join(summary['broken_reasons'])}")
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_readme_tta(target: Path, cfg_entry: dict, summary: dict) -> None:
    m = summary["metrics"] or {}
    pm = summary.get("parent_metrics") or {}
    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append(f"TTA re-evaluation of config {summary['parent_config_id']} "
                 f"(`{summary['parent_run_name']}`).")
    lines.append("")
    lines.append("## TTA parameters")
    lines.append(f"- tta_iter: `{summary['tta_iter']}`")
    lines.append(f"- tta_noise_std: `{summary['tta_noise_std']}`")
    lines.append("")
    lines.append("## Comparison (parent vs TTA)")
    lines.append("| Metric | Parent | TTA |")
    lines.append("|---|---|---|")
    tol_parent = (
        f"{summary['parent_tol_inclus']}/{summary['parent_tol_total']} "
        f"({100 * (summary['parent_tol_inclus'] or 0) / max(summary['parent_tol_total'] or 1, 1):.1f}%)"
    )
    tol_tta = (
        f"{summary['tol_inclus']}/{summary['tol_total']} "
        f"({100 * (summary['tol_inclus'] or 0) / max(summary['tol_total'] or 1, 1):.1f}%)"
    )
    lines.append(f"| tol_in | {tol_parent} | {tol_tta} |")
    lines.append(f"| err_rel_p80 (%) | {summary.get('parent_err_p80_pct')} | {summary.get('err_p80_pct')} |")
    lines.append(f"| R2 | {pm.get('r_squared')} | {m.get('r_squared')} |")
    lines.append(f"| RMSE | {pm.get('rmse')} | {m.get('rmse')} |")
    lines.append(f"| MAE | {pm.get('mae')} | {m.get('mae')} |")
    lines.append(f"| GEH<5 (%) | {pm.get('geh_pct_below_5')} | {m.get('geh_pct_below_5')} |")
    if summary.get("metrics_ci95"):
        ci = summary["metrics_ci95"]
        lines.append("")
        lines.append("## CI95 (TTA, bootstrap 1000 iter)")
        for k in ("tol_in_pct", "p80", "r2"):
            if ci.get(k):
                lines.append(f"- {k}: [{ci[k][0]}, {ci[k][1]}]")
    lines.append("")
    lines.append(f"- eval_seconds: {summary['eval_seconds']}")
    if summary.get("broken"):
        lines.append("")
        lines.append(f"### Quality gates failed: {', '.join(summary['broken_reasons'])}")
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=7006)
    p.add_argument("--configs", default=str(BATCH_DIR / "configs_A6.json"))
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--only", type=int, default=None, help="run only one config id (1-14)")
    p.add_argument("--skip-train", action="store_true", help="only run TTA re-evals (11-14)")
    args = p.parse_args()

    cfgs_all = json.loads(Path(args.configs).read_text(encoding="utf-8"))
    if args.only is not None:
        cfgs = [c for c in cfgs_all if c["id"] == args.only]
    elif args.skip_train:
        cfgs = [c for c in cfgs_all if c.get("mode") == "tta_reeval"]
    else:
        cfgs = cfgs_all

    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[A6] starting batch of {len(cfgs)} configs on port {args.port}", flush=True)
    wall_t0 = time.time()
    token, sid = setup_session(args.port)
    print(f"[A6] session ready sid={sid}", flush=True)

    # Track summaries by config id so TTA configs can fetch their parent.
    summaries_by_id: dict[int, dict[str, Any]] = {}

    # When only running TTA configs, we still need to load parent summaries
    # that already exist on disk.
    def _load_existing(cid: int) -> dict[str, Any] | None:
        for c in cfgs_all:
            if c["id"] == cid:
                metrics_file = BATCH_DIR / c["name"] / "metrics.json"
                if metrics_file.exists():
                    return json.loads(metrics_file.read_text(encoding="utf-8"))
        return None

    runs: list[dict[str, Any]] = []
    for cfg in cfgs:
        run_name = cfg.get("name", f"id{cfg.get('id')}")
        try:
            if cfg.get("mode") == "tta_reeval":
                parent_id = cfg.get("depends_on")
                parent = summaries_by_id.get(parent_id) or _load_existing(parent_id)
                if not parent:
                    print(f"[{run_name}] SKIP — parent config {parent_id} unavailable", flush=True)
                    runs.append({"run_name": run_name, "error": f"parent {parent_id} unavailable"})
                    continue
                res = run_tta_reeval(args.port, token, sid, cfg, parent, args.bootstrap)
            else:
                res = run_train(args.port, token, sid, cfg, args.bootstrap)
                if "error" not in res:
                    summaries_by_id[cfg["id"]] = res
            runs.append(res)
        except Exception as exc:
            print(f"[{run_name}] EXCEPTION: {exc}", flush=True)
            traceback.print_exc()
            runs.append({"run_name": run_name, "error": str(exc)})

    wall_elapsed = time.time() - wall_t0
    (BATCH_DIR / "_summary_A6.json").write_text(
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
        f"[A6] DONE n_runs={len(runs)} wall={wall_elapsed:.0f}s ({wall_elapsed/60:.1f}min)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
