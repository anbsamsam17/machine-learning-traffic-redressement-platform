"""Worker A5 — Phase 05 grid search orchestrator.

Runs 12 training configs in series against an already-running API on
http://127.0.0.1:7005, then writes artifacts and a summary to
.playwright-mcp/Batch_MDL_Phase05/.

Configs target Phase-4 "training tricks":
  1  Hard example mining
  2  Curriculum learning
  3  Hard mining + curriculum
  4  Quantile head (p20/p50/p80)
  5  Pinball p80 + target_log_transform
  6  n_seeds=3 baseline
  7  n_seeds=3 + perm×2
  8  Bootstrap CI95 only (extra resolution)
  9  K-fold k=5  (extra POST /api/evaluation/kfold)
 10  Hard mining + perm×2
 11  Curriculum + perm×2
 12  Curriculum + recent_year×2

Baseline: full 11 features, mse, drp=0.025, ep=1000, no weighting,
neurons_factors=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import requests

API = "http://127.0.0.1:7005"
# Dedicated A5-worker account so other agents (or stray sessions reusing the
# seed `samir.anbri@gmail.com` user) cannot cancel our trainings via
# `/api/training/cancel`. The endpoint enforces session ownership, so a
# distinct owner makes the worker bullet-proof against cross-talk.
EMAIL = "a5_worker_phase05@mdl.local"
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

# Baseline 11 features (Lyon GeoJSON columns) - matches existing A5_FullNoFC layout
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

BASELINE = {
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

# 12 configs as a list of (descriptor, extra_overrides). The first entry's
# `extra_overrides` is merged on top of BASELINE.
CONFIGS: list[dict[str, Any]] = [
    {"name": "A5_HardMining",
     "overrides": {"use_hard_example_mining": True}},
    {"name": "A5_Curriculum",
     "overrides": {"use_curriculum": True}},
    {"name": "A5_HardMining_Curriculum",
     "overrides": {"use_hard_example_mining": True, "use_curriculum": True}},
    {"name": "A5_QuantileHead",
     "overrides": {"use_quantile_head": True}},
    {"name": "A5_PinballP80_LogTarget",
     "overrides": {"losses": ["pinball_p80"], "target_log_transform": True}},
    {"name": "A5_nseeds3",
     "overrides": {"n_seeds": 3}},
    {"name": "A5_nseeds3_perm2",
     "overrides": {
         "n_seeds": 3,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"name": "A5_BootstrapCI95",
     "overrides": {"bootstrap_iter": 2000}},
    {"name": "A5_kfold_k5",
     "overrides": {"_kfold": 5}},
    {"name": "A5_HardMining_perm2",
     "overrides": {
         "use_hard_example_mining": True,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"name": "A5_Curriculum_perm2",
     "overrides": {
         "use_curriculum": True,
         "use_flag_permanent_weighting": True,
         "flag_priority_weight": 2.0,
     }},
    {"name": "A5_Curriculum_recent2",
     "overrides": {
         "use_curriculum": True,
         "use_flag_recent_year_weighting": True,
         "recent_year_priority_weight": 2.0,
     }},
]


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def login() -> str:
    # Register first (idempotent: returns 409 if already exists, which is fine).
    try:
        requests.post(
            f"{API}/api/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=30,
        )
    except Exception:  # noqa: BLE001 — registration is best-effort
        pass
    r = requests.post(
        f"{API}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=30
    )
    r.raise_for_status()
    return r.json()["access_token"]


def upload(token: str) -> str:
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
    return r.json()["session_id"]


def auto_map(token: str, sid: str) -> dict[str, str]:
    r = requests.post(
        f"{API}/api/mapping/auto",
        json={"session_id": sid},
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    return {m["target"]: m["source"] for m in r.json()["mappings"] if m["source"]}


def validate_mapping(token: str, sid: str, mapping: dict[str, str]) -> dict[str, Any]:
    # Make sure "annee" is exposed via extra_cols so year_mapped can be derived
    # downstream. The 11-feature list does not include "annee" directly; it is
    # consumed by year_value_mapping in the training config.
    extras = ["annee", "Type Compteur"]
    # Inject avg_distance / truck_avg_distance variants through extra_cols too -
    # mapping/auto will not catch the Lyon-specific names so we need to add
    # them manually so they survive into learning_df.
    extras += [
        "avg_distance_before_m",
        "avg_distance_after_m",
        "avg_min_distance_m",
        "truck_avg_distance_m",
        "truck_avg_distance_before_m",
        "truck_avg_distance_after_m",
        "truck_avg_min_distance_m",
        "TMJOFCDTV",
        "TMJOFCDPL",
        "TMJOBCTV",
        "TMJOBCPL",
        "functional_class",
        "TxPen",
        "TxPenPL",
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
    return r.json()


def start_training(
    token: str, sid: str, cfg_overrides: dict[str, Any], output_label: str
) -> dict[str, Any]:
    payload = {**BASELINE, **cfg_overrides}
    payload["session_id"] = sid
    payload["output_dir"] = output_label
    # Strip our sentinel key (used for k-fold dispatch only).
    payload.pop("_kfold", None)
    r = requests.post(
        f"{API}/api/training/start",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    if r.status_code != 200:
        _log(f"  start_training FAILED: HTTP {r.status_code}: {r.text[:500]}")
        r.raise_for_status()
    return r.json()


def wait_training(token: str, task_id: str, poll_s: float = 5.0) -> dict[str, Any]:
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
                f"    task={task_id} status={status} "
                f"model={s.get('current_model_name', '')} "
                f"epoch={s.get('current_epoch')}/{s.get('total_epochs')} "
                f"pct={pct} best_val={s.get('best_val_loss')}"
            )
            last_pct = pct
            last_status = status
        if status in ("completed", "failed", "cancelled"):
            return s
        time.sleep(poll_s)


def fetch_training_result(token: str, task_id: str) -> dict[str, Any] | None:
    """Stream events to get the final 'complete' message which contains result."""
    # Use the stream endpoint with a 2-second cutoff after `complete` event.
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


def call_kfold(token: str, sid: str, run_name: str, k: int = 5) -> dict[str, Any]:
    r = requests.post(
        f"{API}/api/evaluation/kfold",
        json={"session_id": sid, "run_name": run_name, "k": k},
        headers={"Authorization": f"Bearer {token}"},
        timeout=1800,
    )
    r.raise_for_status()
    return r.json()


def call_evaluation(
    token: str,
    sid: str,
    model_name: str,
    model_dir: str,
    bootstrap_iter: int = 1000,
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
        timeout=600,
    )
    r.raise_for_status()
    return r.json()


def copy_models(
    server_dir: Path,
    dest_dir: Path,
    only_new: set[str] | None = None,
    snapshot_mtimes: dict[str, float] | None = None,
) -> list[str]:
    """Copy trained model subfolders from server_dir into dest_dir.

    The server overwrites a single model subdir (named from training
    hyperparameters) on each training run, so two configs with the same
    hyperparameters but different "trick" flags (hard_mining vs curriculum)
    produce IDENTICALLY-NAMED model dirs. The previous `only_new` filter
    therefore incorrectly skipped configs 2+. We now compare mtimes when
    `snapshot_mtimes` is provided: a subdir is considered "new" if it is
    absent from the snapshot OR its mtime is newer than the snapshot value.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    if not server_dir.exists():
        return copied
    snapshot_mtimes = snapshot_mtimes or {}
    for sub in sorted(server_dir.iterdir()):
        if not sub.is_dir():
            continue
        # Decide whether this subdir was produced by the current config:
        # - new name -> yes
        # - same name but newer mtime than the snapshot -> yes (overwritten)
        # - same name + same mtime -> no (carry-over from prior config)
        if snapshot_mtimes:
            prev_mtime = snapshot_mtimes.get(sub.name)
            cur_mtime = sub.stat().st_mtime
            if prev_mtime is not None and cur_mtime <= prev_mtime + 0.5:
                continue
        elif only_new is not None and sub.name in only_new:
            continue
        target = dest_dir / sub.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(sub, target)
        copied.append(sub.name)
    return copied


def snapshot_server_dir(server_dir: Path) -> set[str]:
    if not server_dir.exists():
        return set()
    return {p.name for p in server_dir.iterdir() if p.is_dir()}


def snapshot_server_dir_with_mtimes(server_dir: Path) -> dict[str, float]:
    """Capture {subdir_name: mtime} so copy_models can detect overwrites
    when the model name collides across configs (same hyperparams)."""
    if not server_dir.exists():
        return {}
    return {p.name: p.stat().st_mtime for p in server_dir.iterdir() if p.is_dir()}


def aggregate_seeds(seed_dirs: list[Path]) -> dict[str, Any]:
    """Aggregate per-seed evaluations (tol/p80/r2) -> mean/std."""
    import statistics

    tol = []
    p80 = []
    r2 = []
    for d in seed_dirs:
        ev = d / "evaluation.json"
        if not ev.exists():
            continue
        data = json.loads(ev.read_text(encoding="utf-8"))
        if "tol_in_pct" in data:
            tol.append(float(data["tol_in_pct"]))
        if "err_rel_p80" in data:
            p80.append(float(data["err_rel_p80"]))
        m = data.get("metrics") or {}
        if "r_squared" in m:
            r2.append(float(m["r_squared"]))

    def _agg(vals: list[float]) -> dict[str, float | None]:
        if not vals:
            return {"mean": None, "std": None, "n": 0}
        return {
            "mean": round(statistics.mean(vals), 4),
            "std": (round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0),
            "n": len(vals),
            "values": [round(v, 4) for v in vals],
        }

    return {
        "tol_in_pct": _agg(tol),
        "err_rel_p80": _agg(p80),
        "r_squared": _agg(r2),
    }


def run_config(
    token: str,
    sid: str,
    idx: int,
    cfg: dict[str, Any],
    pre_snapshot: set[str] | None = None,
    pre_snapshot_mtimes: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Execute one of the 12 configs, return a summary row."""
    name = cfg["name"]
    out_dir = OUT_ROOT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    pre_snapshot = pre_snapshot or set()

    summary = {
        "config_idx": idx,
        "name": name,
        "overrides": cfg["overrides"],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending",
    }
    try:
        overrides = dict(cfg["overrides"])
        is_kfold = bool(overrides.pop("_kfold", 0))
        bootstrap_iter = int(overrides.pop("bootstrap_iter", 1000))

        # --- start training ---
        start = start_training(token, sid, overrides, output_label=name)
        task_id = start["task_id"]
        server_dir = Path(start["output_dir"])
        _log(f"  task_id={task_id} combos={start['total_combinations']} server_dir={server_dir}")

        # --- wait for completion ---
        status = wait_training(token, task_id, poll_s=10.0)
        if status["status"] != "completed":
            summary["status"] = status["status"]
            summary["error"] = status.get("error")
            (out_dir / "summary.json").write_text(
                json.dumps(summary, indent=2), encoding="utf-8"
            )
            return summary

        # --- fetch final result (with full results_list) via stream ---
        complete = fetch_training_result(token, task_id)
        result = (complete or {}).get("result") or {}

        # --- copy trained model dirs from workspace to .playwright-mcp ---
        # Restrict to entries added during this config (server_dir is shared
        # across the 12 configs because we reuse a single session).
        models_dest = out_dir / "models"
        copied = copy_models(
            server_dir,
            models_dest,
            only_new=pre_snapshot,
            snapshot_mtimes=pre_snapshot_mtimes,
        )
        summary["copied_models"] = copied

        # --- per-model evaluation (gives tol_in_pct / p80 / r2 with CI95) ---
        runs_eval = {}
        for run_name in copied:
            try:
                ev = call_evaluation(
                    token, sid, run_name, str(server_dir),
                    bootstrap_iter=bootstrap_iter,
                )
                # Derive global tol_in_pct/p80 from per-bucket data + CI95.
                buckets = ev.get("metrics_by_tmja_bucket") or []
                tol_in_n = sum(int(b.get("tol_in_n") or 0) for b in buckets)
                n_total = sum(int(b.get("n_samples") or 0) for b in buckets)
                tol_in_pct = round(100.0 * tol_in_n / n_total, 2) if n_total else None
                ci = ev.get("metrics_ci95") or {}
                p80_ci = ci.get("p80")
                err_rel_p80 = (
                    round((p80_ci[0] + p80_ci[1]) / 2.0, 4)
                    if isinstance(p80_ci, list) and len(p80_ci) == 2
                    else None
                )
                metrics = ev.get("metrics") or {}
                eval_subset = {
                    "tol_in_pct": tol_in_pct,
                    "tol_in_n": tol_in_n,
                    "tol_total": n_total,
                    "err_rel_p80": err_rel_p80,
                    "metrics": metrics,
                    "metrics_ci95": ci,
                    "metrics_by_tmja_bucket": buckets,
                    "drift_by_year": ev.get("drift_by_year"),
                }
                runs_eval[run_name] = eval_subset
                model_out = models_dest / run_name
                (model_out / "evaluation.json").write_text(
                    json.dumps(eval_subset, indent=2), encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001
                _log(f"    eval failed for {run_name}: {exc}")
                runs_eval[run_name] = {"error": str(exc)}

        summary["runs_eval"] = runs_eval
        summary["best_model"] = result.get("best_model")
        summary["best_val_loss"] = result.get("best_val_loss")
        summary["total_models"] = result.get("total_models")
        summary["results"] = result.get("results")

        # --- aggregate per-seed metrics for n_seeds > 1 ---
        n_seeds = overrides.get("n_seeds", 1)
        if n_seeds and int(n_seeds) > 1 and copied:
            seed_dirs = [models_dest / r for r in copied]
            agg = aggregate_seeds(seed_dirs)
            (out_dir / "n_seeds_summary.json").write_text(
                json.dumps(
                    {
                        "n_seeds": int(n_seeds),
                        "runs": copied,
                        "aggregate": agg,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            summary["n_seeds_aggregate"] = agg

        # --- k-fold (config 9) ---
        if is_kfold and copied:
            target_run = result.get("best_model") or copied[0]
            _log(f"  running k-fold k=5 on {target_run}")
            try:
                kf = call_kfold(token, sid, target_run, k=5)
                (out_dir / "kfold_result.json").write_text(
                    json.dumps(kf, indent=2), encoding="utf-8"
                )
                summary["kfold_summary"] = kf.get("summary")
            except Exception as exc:  # noqa: BLE001
                _log(f"    k-fold failed: {exc}")
                summary["kfold_error"] = str(exc)

        summary["status"] = "ok"

    except Exception as exc:  # noqa: BLE001
        summary["status"] = "error"
        summary["error"] = str(exc)
        _log(f"  ERROR: {exc}")

    summary["ended_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _log("Login")
    token = login()
    _log("Upload geojson")
    sid = upload(token)
    _log(f"  session_id={sid}")
    _log("Auto-map")
    proposed = auto_map(token, sid)
    _log(f"  auto-mapped {len(proposed)} columns")
    _log("Validate mapping")
    vm = validate_mapping(token, sid, proposed)
    _log(f"  learning_df rows={vm.get('rows')} cols={len(vm.get('columns', []))}")

    server_models_root = WORKSPACE_ROOT / sid / "models"
    summaries: list[dict[str, Any]] = []
    for idx, cfg in enumerate(CONFIGS, start=1):
        _log("")
        _log(f"==== CONFIG {idx}/{len(CONFIGS)} : {cfg['name']} ====")
        pre_snapshot = snapshot_server_dir(server_models_root)
        pre_snapshot_mtimes = snapshot_server_dir_with_mtimes(server_models_root)
        _log(
            f"  pre-snapshot has {len(pre_snapshot)} existing model dir(s) "
            f"(mtimes captured for {len(pre_snapshot_mtimes)})"
        )
        t0 = time.time()
        s = run_config(
            token, sid, idx, cfg,
            pre_snapshot=pre_snapshot,
            pre_snapshot_mtimes=pre_snapshot_mtimes,
        )
        elapsed = round(time.time() - t0, 1)
        s["wall_seconds"] = elapsed
        summaries.append(s)
        _log(f"  done in {elapsed}s — status={s['status']}")
        # Persist running summary after every config so we never lose data
        (OUT_ROOT / "A5_summary.json").write_text(
            json.dumps(summaries, indent=2, default=str), encoding="utf-8"
        )

    _log("")
    _log("All configs done — writing A5_summary.md")
    write_md_summary(summaries)
    return 0


def write_md_summary(summaries: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    lines.append("# A5 — Phase 05 batch summary (training tricks)")
    lines.append("")
    lines.append("Worker A5, port 7005. Baseline: Full 11 features, mse, drp=0.025,")
    lines.append("ep=1000, no weighting, neurons=[3,2,1], lr=0.01, batch=256, elu, test=0.05.")
    lines.append("")
    lines.append("| # | Name | Status | Best model | tol% | p80% | R² | seconds |")
    lines.append("| - | ---- | ------ | ---------- | ---- | ---- | -- | ------- |")
    for s in summaries:
        runs_eval = s.get("runs_eval") or {}
        best = s.get("best_model") or (sorted(runs_eval.keys())[0] if runs_eval else "")
        ev = runs_eval.get(best) or {}
        tol = ev.get("tol_in_pct")
        p80 = ev.get("err_rel_p80")
        r2 = (ev.get("metrics") or {}).get("r_squared")
        lines.append(
            f"| {s.get('config_idx')} | {s.get('name')} | {s.get('status')} | "
            f"{best} | {tol} | {p80} | {r2} | {s.get('wall_seconds')} |"
        )
    lines.append("")
    lines.append("## Per-config notes")
    for s in summaries:
        lines.append("")
        lines.append(f"### {s.get('config_idx')}. {s.get('name')}")
        lines.append(f"- status: `{s.get('status')}`")
        if s.get("error"):
            lines.append(f"- error: `{s['error']}`")
        ov = s.get("overrides") or {}
        if ov:
            lines.append(f"- overrides: `{ov}`")
        lines.append(f"- wall_seconds: `{s.get('wall_seconds')}`")
        agg = s.get("n_seeds_aggregate")
        if agg:
            lines.append(f"- n_seeds aggregate: `{agg}`")
        kf = s.get("kfold_summary")
        if kf:
            lines.append(f"- kfold summary: `{kf}`")
        runs_eval = s.get("runs_eval") or {}
        for rn, ev in runs_eval.items():
            tol = ev.get("tol_in_pct")
            p80 = ev.get("err_rel_p80")
            ci = ev.get("metrics_ci95") or {}
            r2 = (ev.get("metrics") or {}).get("r_squared")
            lines.append(
                f"  - `{rn}` tol={tol}% p80={p80}% R²={r2} CI95={ci}"
            )

    (OUT_ROOT / "A5_summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
