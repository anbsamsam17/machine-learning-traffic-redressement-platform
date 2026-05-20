"""Continuation worker A5 — port 7005.

Picks up where the first run_a5.py left off:
  - A5_HardMining (config 1) is already complete and is NOT re-run.
  - Configs 2-12 are executed end-to-end, each in isolation:
      * Open a FRESH session per config (own upload + mapping) so the
        server-side model dir is per-config and never overwritten by
        the next iteration. Cost: ~0.5s of upload per config.
      * Train, then IMMEDIATELY copy the server model dir into the
        local config folder before any next training overwrites it.
      * Evaluate (bootstrap_iter=1000 default, 2000 for #8).
      * Fetch /api/evaluation/report -> save report.html.
      * Fetch /api/evaluation/download-model -> save model.zip.
      * Write metrics.json (full schema) + README.md.
  - n_seeds=3 configs: split into A5_<name>_seed{0,1,2}/ folders + a
    parent _summary.json with mean/std of tol/p80/R².
  - kfold_k5: also POST /api/evaluation/kfold -> save kfold_result.json.
  - Finally writes A5_summary.md / A5_summary.json.

Runs SEQUENTIALLY. ~3-5 min per config, ~45-60 min total.
"""

from __future__ import annotations

import json
import shutil
import statistics
import sys
import time
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import requests

API = "http://127.0.0.1:7005"
# Dedicated A5 worker account so other agents' cancel calls (which require
# session ownership) cannot target our training. Mirrors run_a5.py.
EMAIL = "a5.worker.phase05@example.com"
PASSWORD = "A5WorkerPhase05!"
GEOJSON = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/DataApprentissage/GrandLyon/BCFCDREF_AllYears_TV.geojson"
)
OUT_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05"
)
WORKSPACE_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/tmp_workdir"
)

FULL_11 = [
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
ON_OFF_NORM = [False, True, True, False, True, True, True, True, True, True, True]
YEAR_MAPPING = {
    "2019": 1, "2020": 2, "2021": 3, "2022": 4,
    "2023": 5, "2024": 6, "2025": 7,
}

BASELINE: dict[str, Any] = {
    "model_type": "TV",
    "input_cols": FULL_11,
    "output_cols": ["TxPen"],
    "on_off_norm": ON_OFF_NORM,
    "activations": ["elu"],
    "learning_rates": [0.01],
    "losses": ["mse"],
    "min_nb_epochs_list": [1000],
    "max_epochs": 1250,
    "test_size": 0.05,
    "neurons_factors_list": [[3.0, 2.0, 1.0]],
    "use_batch_norm": False,
    "dropouts": [0.025],
    "batch_sizes": [256],
    "seed": 1750,
    "feature_subset_grid": False,
    "use_flag_comptage_weighting": False,
    "use_flag_permanent_weighting": False,
    "flag_priority_weight": 4.0,
    "use_flag_recent_year_weighting": False,
    "recent_year_priority_weight": 2.0,
    "year_column_name": "annee",
    "year_value_mapping": YEAR_MAPPING,
}

# Configs 2-12. config_idx matches the task description.
CONFIGS: list[dict[str, Any]] = [
    {"idx": 2, "name": "A5_Curriculum",
     "overrides": {"use_curriculum": True}},
    {"idx": 3, "name": "A5_HardMining_Curriculum",
     "overrides": {"use_hard_example_mining": True, "use_curriculum": True}},
    {"idx": 4, "name": "A5_QuantileHead",
     "overrides": {"use_quantile_head": True}},
    {"idx": 5, "name": "A5_PinballP80_LogTarget",
     "overrides": {"losses": ["pinball_p80"], "target_log_transform": True}},
    {"idx": 6, "name": "A5_nseeds3",
     "overrides": {"n_seeds": 3}},
    {"idx": 7, "name": "A5_nseeds3_perm2",
     "overrides": {
         "n_seeds": 3,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"idx": 8, "name": "A5_BootstrapCI95",
     "overrides": {}, "bootstrap_iter": 2000},
    {"idx": 9, "name": "A5_kfold_k5",
     "overrides": {}, "_kfold": 5},
    {"idx": 10, "name": "A5_HardMining_perm2",
     "overrides": {
         "use_hard_example_mining": True,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"idx": 11, "name": "A5_Curriculum_perm2",
     "overrides": {
         "use_curriculum": True,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"idx": 12, "name": "A5_Curriculum_recent2",
     "overrides": {
         "use_curriculum": True,
         "use_flag_recent_year_weighting": True,
         "recent_year_priority_weight": 2.0,
     }},
]

EXPECTED_NAMES = ["A5_HardMining"] + [c["name"] for c in CONFIGS]


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def login() -> str:
    # Best-effort register (200 OK if account already exists from earlier run_a5)
    try:
        requests.post(
            f"{API}/api/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=30,
        )
    except Exception:
        pass
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def setup_session(token: str) -> str:
    files = {"file": (GEOJSON.name, GEOJSON.read_bytes(), "application/geo+json")}
    data = {"mode": "TV"}
    r = requests.post(
        f"{API}/api/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
    )
    r.raise_for_status()
    sid = r.json()["session_id"]

    r = requests.post(
        f"{API}/api/mapping/auto",
        json={"session_id": sid},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"] if m["source"]}

    extras = [
        "annee", "Type Compteur",
        "avg_distance_before_m", "avg_distance_after_m", "avg_min_distance_m",
        "truck_avg_distance_m", "truck_avg_distance_before_m",
        "truck_avg_distance_after_m", "truck_avg_min_distance_m",
        "TMJOFCDTV", "TMJOFCDPL", "TMJOBCTV", "TMJOBCPL",
        "functional_class", "TxPen", "TxPenPL",
    ]
    r = requests.put(
        f"{API}/api/mapping/validate",
        json={
            "session_id": sid,
            "mapping": mapping,
            "territory": "GrandLyon",
            "extra_cols": extras,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
    )
    r.raise_for_status()
    return sid


def start_training(token: str, sid: str, overrides: dict[str, Any], label: str) -> dict[str, Any]:
    payload = {**BASELINE, **overrides}
    payload["session_id"] = sid
    payload["output_dir"] = label
    r = requests.post(
        f"{API}/api/training/start",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    if r.status_code != 200:
        _log(f"  start_training FAILED HTTP {r.status_code}: {r.text[:500]}")
        r.raise_for_status()
    return r.json()


def wait_training(token: str, task_id: str, poll: float = 8.0, max_wait: float = 1800) -> dict[str, Any]:
    t0 = time.time()
    last_pct = -1.0
    last_status = ""
    while True:
        r = requests.get(
            f"{API}/api/training/status/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        r.raise_for_status()
        s = r.json()
        pct = float(s.get("progress_pct", 0))
        status = s.get("status", "")
        if pct != last_pct or status != last_status:
            _log(
                f"    {task_id} status={status} "
                f"epoch={s.get('current_epoch')}/{s.get('total_epochs')} "
                f"pct={pct:.1f} best_val={s.get('best_val_loss')}"
            )
            last_pct = pct
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return s
        if time.time() - t0 > max_wait:
            _log(f"    {task_id} TIMEOUT after {max_wait}s")
            return s
        time.sleep(poll)


def fetch_training_result(token: str, task_id: str) -> dict[str, Any] | None:
    r = requests.get(
        f"{API}/api/training/stream/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=600,
    )
    final = None
    for line in r.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if line.startswith("data: "):
            payload = json.loads(line[6:])
            if payload.get("type") == "complete":
                final = payload
                break
    r.close()
    return final


def call_evaluation(
    token: str, sid: str, model_name: str, model_dir: str, bootstrap_iter: int = 1000
) -> dict[str, Any]:
    r = requests.post(
        f"{API}/api/evaluation/run?bootstrap_iter={bootstrap_iter}",
        json={
            "session_id": sid,
            "model_name": model_name,
            "model_dir": model_dir,
            "year_column_name": "annee",
            "year_value_mapping": YEAR_MAPPING,
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=900,
    )
    r.raise_for_status()
    return r.json()


def fetch_report(token: str, sid: str) -> str:
    r = requests.get(
        f"{API}/api/evaluation/report/{sid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    r.raise_for_status()
    return r.json().get("report_html") or ""


def download_model_zip(
    token: str, sid: str, model_name: str, model_dir: str
) -> bytes | None:
    params = {
        "model_name": model_name,
        "model_dir": model_dir,
        "session_id": sid,
    }
    r = requests.get(
        f"{API}/api/evaluation/download-model",
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        _log(f"  download-model HTTP {r.status_code}: {r.text[:200]}")
        return None
    return r.content


def call_kfold(token: str, sid: str, run_name: str, k: int = 5) -> dict[str, Any]:
    r = requests.post(
        f"{API}/api/evaluation/kfold",
        json={"session_id": sid, "run_name": run_name, "k": k},
        headers={"Authorization": f"Bearer {token}"},
        timeout=3600,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Per-config artifacts
# ---------------------------------------------------------------------------

def copy_models_all(server_dir: Path, dest_dir: Path) -> list[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    if not server_dir.exists():
        return copied
    for sub in sorted(server_dir.iterdir()):
        if not sub.is_dir():
            continue
        target = dest_dir / sub.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(sub, target)
        copied.append(sub.name)
    return copied


def _ci_width_ratio(ci: list[float] | None, mean: float | None) -> float | None:
    if not (isinstance(ci, list) and len(ci) == 2 and mean):
        return None
    try:
        return abs(ci[1] - ci[0]) / abs(mean) if mean else None
    except (TypeError, ZeroDivisionError):
        return None


def _detect_broken(eval_out: dict[str, Any]) -> tuple[bool, str]:
    reasons: list[str] = []
    metrics = eval_out.get("metrics") or {}
    buckets = eval_out.get("metrics_by_tmja_bucket") or []
    ci = eval_out.get("metrics_ci95") or {}

    tol_in_n = sum(int(b.get("tol_in_n") or 0) for b in buckets)
    tol_total = sum(int(b.get("n_samples") or 0) for b in buckets)
    if tol_in_n == 0 and tol_total == 0:
        reasons.append("tolerance counts 0/0")

    p80_ci = ci.get("p80")
    p80 = (
        (p80_ci[0] + p80_ci[1]) / 2.0
        if isinstance(p80_ci, list) and len(p80_ci) == 2 else None
    )
    if p80 is None:
        reasons.append("p80 missing")
    if not buckets:
        reasons.append("barplot missing (no buckets)")

    means_for_ci = {
        "r2": metrics.get("r_squared"),
        "p80": p80,
        "tol_in_pct": 100.0 * tol_in_n / tol_total if tol_total else None,
    }
    for axis, mean in means_for_ci.items():
        ratio = _ci_width_ratio(ci.get(axis), mean)
        if ratio is not None and ratio > 0.5:
            reasons.append(f"CI95[{axis}] width > 50% of mean ({ratio:.2f})")
    return (bool(reasons), "; ".join(reasons))


def write_metrics_json(
    config_dir: Path,
    config: dict[str, Any],
    server_dir: Path,
    run_name: str,
    training_result_entry: dict[str, Any],
    eval_out: dict[str, Any],
    bootstrap_iter: int,
    wall_seconds: float,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    buckets = eval_out.get("metrics_by_tmja_bucket") or []
    tol_in_n = sum(int(b.get("tol_in_n") or 0) for b in buckets)
    tol_total = sum(int(b.get("n_samples") or 0) for b in buckets)
    tol_in_pct = round(100.0 * tol_in_n / tol_total, 2) if tol_total else None
    ci = eval_out.get("metrics_ci95") or {}
    p80_ci = ci.get("p80")
    p80 = (
        round((p80_ci[0] + p80_ci[1]) / 2.0, 4)
        if isinstance(p80_ci, list) and len(p80_ci) == 2 else None
    )
    broken, broken_reason = _detect_broken(eval_out)
    tr = training_result_entry or {}

    out = {
        "config_idx": config.get("idx"),
        "name": config.get("name"),
        "overrides": config.get("overrides"),
        "bootstrap_iter": bootstrap_iter,
        "wall_seconds": round(wall_seconds, 1),
        "run_name": run_name,
        "n_inputs": len(tr.get("input_cols", []) or []),
        "input_cols": tr.get("input_cols"),
        "on_off_norm": tr.get("on_off_norm"),
        "training_flags": {
            # Phase 0 (baseline)
            "activation": tr.get("activation"),
            "loss": tr.get("loss"),
            "dropout": tr.get("dropout"),
            "neurons_factors": tr.get("neurons_factors"),
            "learning_rate": tr.get("learning_rate"),
            "batch_size": tr.get("batch_size"),
            "use_batch_norm": tr.get("use_batch_norm"),
            "epochs_requested": tr.get("epochs_requested"),
            "epochs_trained": tr.get("epochs_trained"),
            "test_size": tr.get("test_size"),
            "patience": tr.get("patience"),
            "reduce_lr_factor": tr.get("reduce_lr_factor"),
            "reduce_lr_patience": tr.get("reduce_lr_patience"),
            # Phase 1 (weighting)
            "use_flag_permanent_weighting": tr.get("use_flag_permanent_weighting"),
            "flag_priority_weight": tr.get("flag_priority_weight"),
            "use_flag_recent_year_weighting": tr.get("use_flag_recent_year_weighting"),
            "recent_year_priority_weight": tr.get("recent_year_priority_weight"),
            "use_flag_comptage_weighting": tr.get("use_flag_comptage_weighting"),
            # Phase 4-5 (training tricks)
            "use_hard_example_mining": tr.get("use_hard_example_mining"),
            "hard_example_mining_note": tr.get("hard_example_mining_note"),
            "use_curriculum": tr.get("use_curriculum"),
            "curriculum_phase_a_epochs": tr.get("curriculum_phase_a_epochs"),
            "use_quantile_head": tr.get("use_quantile_head"),
            "target_log_transform": tr.get("target_log_transform"),
            "n_seeds": tr.get("n_seeds"),
            "seed_index": tr.get("seed_index"),
            "seed": tr.get("seed"),
        },
        "metrics": eval_out.get("metrics") or {},
        "metrics_ci95": ci,
        "metrics_by_tmja_bucket": buckets,
        "drift_by_year": eval_out.get("drift_by_year") or [],
        "tol_in_pct": tol_in_pct,
        "tol_in_n": tol_in_n,
        "tol_total": tol_total,
        "err_rel_p80": p80,
        "broken": broken,
        "broken_reason": broken_reason if broken else None,
        "best_val_loss": tr.get("val_loss"),
        "server_model_dir": str(server_dir),
    }
    if extra:
        out.update(extra)
    (config_dir / "metrics.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return out


def write_readme(config_dir: Path, metrics: dict[str, Any]) -> None:
    name = metrics.get("name") or config_dir.name
    ov = metrics.get("overrides") or {}
    m = metrics.get("metrics") or {}
    flags = metrics.get("training_flags") or {}
    broken = metrics.get("broken")
    lines: list[str] = []
    lines.append(f"# {name}")
    lines.append("")
    lines.append("**Worker:** A5 (port 7005)")
    lines.append("**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)")
    lines.append("**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)")
    lines.append("")
    lines.append("## Overrides (on top of baseline)")
    lines.append("```json")
    lines.append(json.dumps(ov, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Baseline")
    lines.append("- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)")
    lines.append(f"- loss=`{flags.get('loss')}`, dropout={flags.get('dropout')}, "
                 f"neurons_factors={flags.get('neurons_factors')}, "
                 f"lr={flags.get('learning_rate')}, batch={flags.get('batch_size')}, "
                 f"activation={flags.get('activation')}")
    lines.append(f"- epochs_requested={flags.get('epochs_requested')}, "
                 f"epochs_trained={flags.get('epochs_trained')}, "
                 f"test_size={flags.get('test_size')}")
    lines.append("")
    lines.append("## Training tricks enabled")
    for k in ("use_hard_example_mining", "use_curriculum", "use_quantile_head",
              "target_log_transform", "use_flag_permanent_weighting",
              "use_flag_recent_year_weighting", "n_seeds"):
        lines.append(f"- {k}: `{flags.get(k)}`")
    lines.append("")
    lines.append(f"## Validation metrics (n={m.get('n_samples')})")
    lines.append(f"- Capteurs tolérance inclus: **{metrics.get('tol_in_n')}/{metrics.get('tol_total')}** "
                 f"({metrics.get('tol_in_pct')}%)")
    lines.append(f"- Erreur relative p80: **{metrics.get('err_rel_p80')}%**")
    lines.append(f"- R²: **{m.get('r_squared')}**")
    lines.append(f"- GEH < 5: **{m.get('geh_pct_below_5')}%**")
    lines.append(f"- RMSE: {m.get('rmse')}  MAE: {m.get('mae')}  MAPE: {m.get('mape')}%")
    lines.append(f"- Median rel. error: {m.get('median_relative_error')}%")
    lines.append("")
    ci = metrics.get("metrics_ci95") or {}
    if ci:
        lines.append("## CI95 (bootstrap)")
        lines.append("```json")
        lines.append(json.dumps(ci, indent=2))
        lines.append("```")
        lines.append("")
    buckets = metrics.get("metrics_by_tmja_bucket") or []
    if buckets:
        lines.append("## Per-bucket TMJOBCTV")
        lines.append("| bucket | n | tol_in_n | tol% | p80 | R² |")
        lines.append("| ------ | - | -------- | ---- | --- | -- |")
        for b in buckets:
            lines.append(
                f"| {b.get('bucket')} | {b.get('n_samples')} | "
                f"{b.get('tol_in_n')} | {b.get('tol_in_pct')}% | "
                f"{b.get('p80')} | {b.get('r2')} |"
            )
        lines.append("")
    drift = metrics.get("drift_by_year") or []
    if drift:
        lines.append("## Drift by year")
        lines.append("| year | n | R² | MAE | tol% | p80% |")
        lines.append("| ---- | - | -- | --- | ---- | ---- |")
        for d in drift:
            lines.append(
                f"| {d.get('year_label')} | {d.get('n_samples')} | "
                f"{d.get('r2')} | {d.get('mae')} | "
                f"{d.get('tol_in_pct')}% | {d.get('p80')}% |"
            )
        lines.append("")
    if metrics.get("kfold_summary"):
        lines.append("## k-fold (k=5) summary")
        lines.append("```json")
        lines.append(json.dumps(metrics["kfold_summary"], indent=2))
        lines.append("```")
        lines.append("")
    if broken:
        lines.append(f"### Quality gate: BROKEN  \nReason: `{metrics.get('broken_reason')}`")
        lines.append("")
    lines.append(f"_Wall-clock: {metrics.get('wall_seconds')}s  "
                 f"bootstrap_iter={metrics.get('bootstrap_iter')}_")
    (config_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-config driver
# ---------------------------------------------------------------------------

def run_one_config(
    token: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    name = config["name"]
    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    summary_row: dict[str, Any] = {
        "config_idx": config["idx"],
        "name": name,
        "overrides": config["overrides"],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",
    }
    try:
        # 1) FRESH SESSION (so server_dir is isolated)
        sid = setup_session(token)
        summary_row["session_id"] = sid
        server_dir = WORKSPACE_ROOT / sid / "models"
        _log(f"  session={sid}  server_dir={server_dir}")

        overrides = dict(config["overrides"])
        bootstrap_iter = int(config.get("bootstrap_iter", 1000))
        is_kfold = bool(config.get("_kfold", 0))

        # 2) START TRAINING
        start = start_training(token, sid, overrides, label=name)
        task_id = start["task_id"]
        _log(f"  task_id={task_id} combos={start['total_combinations']}")

        # 3) WAIT
        status = wait_training(token, task_id, poll=8.0, max_wait=1800)
        if status["status"] != "completed":
            summary_row["status"] = status["status"]
            summary_row["error"] = status.get("error")
            (out_dir / "metrics.json").write_text(
                json.dumps(summary_row, indent=2, default=str), encoding="utf-8"
            )
            return summary_row

        # 4) FETCH FULL TRAINING RESULT
        complete = fetch_training_result(token, task_id)
        result = (complete or {}).get("result") or {}
        results_list = result.get("results") or []
        # 5) COPY MODELS IMMEDIATELY (before anything else can overwrite)
        models_dest = out_dir / "models"
        copied = copy_models_all(server_dir, models_dest)
        summary_row["copied_models"] = copied
        _log(f"  copied {len(copied)} model(s) to {models_dest}")

        # 6) EVAL EACH MODEL
        runs_eval: dict[str, dict[str, Any]] = {}
        per_seed_metrics: list[dict[str, Any]] = []
        first_metrics: dict[str, Any] | None = None
        for run_name in copied:
            try:
                ev = call_evaluation(
                    token, sid, run_name, str(server_dir),
                    bootstrap_iter=bootstrap_iter,
                )
                runs_eval[run_name] = ev
            except Exception as exc:  # noqa: BLE001
                _log(f"  eval failed for {run_name}: {exc}")
                runs_eval[run_name] = {"error": str(exc)}
                continue
            # Match training result entry by run_name
            tr_entry = next(
                (r for r in results_list if r.get("run_name") == run_name), {}
            ) or (results_list[0] if results_list else {})
            # Save per-run evaluation under config/models/<run_name>/evaluation.json
            (models_dest / run_name / "evaluation.json").write_text(
                json.dumps(ev, indent=2, default=str), encoding="utf-8"
            )
            # 7) FETCH REPORT (overwritten on session by each eval — fetch NOW)
            try:
                html = fetch_report(token, sid)
                target = out_dir if first_metrics is None else (
                    OUT_ROOT / f"{name}_seed{tr_entry.get('seed_index', len(per_seed_metrics))}"
                )
                target.mkdir(parents=True, exist_ok=True)
                (target / "report.html").write_text(html, encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                _log(f"  report fetch failed: {exc}")
            # 8) DOWNLOAD MODEL ZIP (one per run)
            try:
                zip_bytes = download_model_zip(token, sid, run_name, str(server_dir))
                if zip_bytes:
                    target = (
                        out_dir if first_metrics is None else
                        (OUT_ROOT / f"{name}_seed{tr_entry.get('seed_index', len(per_seed_metrics))}")
                    )
                    target.mkdir(parents=True, exist_ok=True)
                    (target / "model.zip").write_bytes(zip_bytes)
            except Exception as exc:  # noqa: BLE001
                _log(f"  download-model failed: {exc}")
            # 9) WRITE per-config metrics + README
            extra = {}
            if is_kfold and first_metrics is None:
                # k-fold runs AFTER training the baseline
                try:
                    _log(f"  k-fold k=5 on {run_name} ...")
                    kf = call_kfold(token, sid, run_name, k=5)
                    (out_dir / "kfold_result.json").write_text(
                        json.dumps(kf, indent=2, default=str), encoding="utf-8"
                    )
                    extra["kfold_summary"] = kf.get("summary")
                except Exception as exc:  # noqa: BLE001
                    _log(f"  kfold failed: {exc}")
                    extra["kfold_error"] = str(exc)
            wall = time.time() - t0
            if "n_seeds" in (config.get("overrides") or {}) and (config["overrides"].get("n_seeds") or 1) > 1:
                # Per-seed dir
                seed_idx = tr_entry.get("seed_index", len(per_seed_metrics))
                seed_dir = OUT_ROOT / f"{name}_seed{seed_idx}"
                seed_dir.mkdir(parents=True, exist_ok=True)
                # Copy model dir into seed dir
                src_model = models_dest / run_name
                dst_model = seed_dir / "model"
                if src_model.exists():
                    if dst_model.exists():
                        shutil.rmtree(dst_model)
                    shutil.copytree(src_model, dst_model)
                m = write_metrics_json(
                    seed_dir, config, server_dir, run_name, tr_entry,
                    ev, bootstrap_iter, wall, extra=extra,
                )
                write_readme(seed_dir, m)
                per_seed_metrics.append(m)
                if first_metrics is None:
                    first_metrics = m
            else:
                m = write_metrics_json(
                    out_dir, config, server_dir, run_name, tr_entry,
                    ev, bootstrap_iter, wall, extra=extra,
                )
                write_readme(out_dir, m)
                if first_metrics is None:
                    first_metrics = m

        # 10) n_seeds aggregate
        if per_seed_metrics:
            def _stats(vals: list[float]) -> dict[str, Any]:
                vals = [v for v in vals if isinstance(v, (int, float))]
                if not vals:
                    return {"mean": None, "std": None, "n": 0}
                return {
                    "mean": round(statistics.mean(vals), 4),
                    "std": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
                    "n": len(vals),
                    "values": [round(v, 4) for v in vals],
                }
            agg = {
                "config_name": name,
                "n_seeds": len(per_seed_metrics),
                "seeds": [m.get("training_flags", {}).get("seed_index") for m in per_seed_metrics],
                "tol_in_pct": _stats([m.get("tol_in_pct") for m in per_seed_metrics]),
                "err_rel_p80": _stats([m.get("err_rel_p80") for m in per_seed_metrics]),
                "r_squared": _stats([
                    (m.get("metrics") or {}).get("r_squared")
                    for m in per_seed_metrics
                ]),
                "geh_pct_below_5": _stats([
                    (m.get("metrics") or {}).get("geh_pct_below_5")
                    for m in per_seed_metrics
                ]),
            }
            (OUT_ROOT / f"{name}_summary.json").write_text(
                json.dumps(agg, indent=2, default=str), encoding="utf-8"
            )
            summary_row["n_seeds_aggregate"] = agg
            # Top-level metrics.json for the parent stays as the FIRST seed's
            # entry (already written), so the global summary can read it.

        # 11) Save raw training result + status
        summary_row["status"] = "ok"
        summary_row["best_model"] = result.get("best_model")
        summary_row["best_val_loss"] = result.get("best_val_loss")
        summary_row["results"] = results_list
        (out_dir / "training_result.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

        # Update first_metrics with wall time
        summary_row["wall_seconds"] = round(time.time() - t0, 1)
        if first_metrics is not None:
            summary_row["tol_in_pct"] = first_metrics.get("tol_in_pct")
            summary_row["err_rel_p80"] = first_metrics.get("err_rel_p80")
            summary_row["r_squared"] = (first_metrics.get("metrics") or {}).get("r_squared")
            summary_row["geh_pct_below_5"] = (first_metrics.get("metrics") or {}).get("geh_pct_below_5")
            summary_row["broken"] = first_metrics.get("broken")
            summary_row["broken_reason"] = first_metrics.get("broken_reason")

    except Exception as exc:  # noqa: BLE001
        summary_row["status"] = "error"
        summary_row["error"] = str(exc)
        summary_row["wall_seconds"] = round(time.time() - t0, 1)
        _log(f"  ERROR: {exc}")
        import traceback
        _log(traceback.format_exc())

    summary_row["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return summary_row


# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------

def _load_hardmining_summary() -> dict[str, Any]:
    p = OUT_ROOT / "A5_HardMining" / "summary.json"
    if not p.exists():
        return {}
    s = json.loads(p.read_text(encoding="utf-8"))
    runs_eval = s.get("runs_eval") or {}
    best = s.get("best_model") or next(iter(runs_eval.keys()), "")
    ev = runs_eval.get(best, {})
    metrics = ev.get("metrics") or {}
    row = {
        "config_idx": s.get("config_idx", 1),
        "name": s.get("name", "A5_HardMining"),
        "overrides": s.get("overrides"),
        "status": s.get("status"),
        "best_model": best,
        "tol_in_pct": ev.get("tol_in_pct"),
        "err_rel_p80": ev.get("err_rel_p80"),
        "r_squared": metrics.get("r_squared"),
        "geh_pct_below_5": metrics.get("geh_pct_below_5"),
        "wall_seconds": None,
        "broken": False,
        "broken_reason": None,
        "metrics_ci95": ev.get("metrics_ci95"),
    }
    return row


def write_global_summary(rows: list[dict[str, Any]]) -> None:
    total_wall = sum(int(r.get("wall_seconds") or 0) for r in rows)
    lines: list[str] = []
    lines.append("# A5 - Phase 05 batch summary (training tricks)")
    lines.append("")
    lines.append("Worker A5, port 7005. Baseline: Full 11 features, mse, drp=0.025,")
    lines.append("ep=1000, no weighting, neurons=[3,2,1], lr=0.01, batch=256, elu, test=0.05.")
    lines.append("")
    lines.append(f"Total wall-clock: **{total_wall}s** ({total_wall // 60}m {total_wall % 60}s).")
    lines.append("")
    lines.append("| # | Name | Status | tol% | p80% | R² | GEH<5% | broken? | wall(s) |")
    lines.append("| - | ---- | ------ | ---- | ---- | -- | ------ | ------- | ------- |")
    best_score = -1.0
    best_name = "-"
    issues: list[str] = []
    for r in rows:
        broken = r.get("broken")
        bf = "yes" if broken else ""
        lines.append(
            f"| {r.get('config_idx')} | {r.get('name')} | {r.get('status')} | "
            f"{r.get('tol_in_pct')} | {r.get('err_rel_p80')} | "
            f"{r.get('r_squared')} | {r.get('geh_pct_below_5')} | "
            f"{bf} | {r.get('wall_seconds')} |"
        )
        try:
            score = float(r.get("tol_in_pct") or 0) + 100.0 * float(r.get("r_squared") or 0)
            if not broken and r.get("status") == "ok" and score > best_score:
                best_score = score
                best_name = r.get("name") or "-"
        except (TypeError, ValueError):
            pass
        if broken and r.get("broken_reason"):
            issues.append(f"- {r.get('name')}: {r.get('broken_reason')}")
        if r.get("status") and r.get("status") not in ("ok", "completed"):
            issues.append(f"- {r.get('name')}: status={r.get('status')} {r.get('error') or ''}")
    lines.append("")
    lines.append(f"## Best config: `{best_name}` (composite score = {best_score:.2f})")
    if issues:
        lines.append("")
        lines.append("## Issues")
        lines.extend(issues)
    (OUT_ROOT / "A5_summary.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_ROOT / "A5_summary.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8"
    )


def main() -> int:
    _log("Login")
    token = login()
    _log("Token OK")

    # Load existing config 1 row from previous run
    hm_row = _load_hardmining_summary()

    rows: list[dict[str, Any]] = []
    if hm_row:
        rows.append(hm_row)
        _log(f"Loaded existing A5_HardMining row (tol={hm_row.get('tol_in_pct')}% "
             f"p80={hm_row.get('err_rel_p80')}%)")

    for idx, cfg in enumerate(CONFIGS, start=2):
        _log("")
        _log(f"==== CONFIG {cfg['idx']}/12 : {cfg['name']} ====")
        row = run_one_config(token, cfg)
        rows.append(row)
        _log(f"  done in {row.get('wall_seconds')}s — status={row.get('status')}  "
             f"tol={row.get('tol_in_pct')}%  p80={row.get('err_rel_p80')}%  "
             f"R²={row.get('r_squared')}")
        # Persist after each config
        write_global_summary(rows)

    write_global_summary(rows)
    _log("All done — A5_summary.md written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
