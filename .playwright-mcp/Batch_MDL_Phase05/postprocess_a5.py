"""Post-processor for Worker A5 (Phase 05).

Walks every A5_* config directory produced by run_a5.py and:
  - normalizes/copies the per-config summary.json into metrics.json
    with the full schema (n_inputs, all Phase 0-5 flags, all metrics
    including CI95 and per-bucket TMJOBCTV, broken flag with reason)
  - writes a per-config README.md
  - re-fetches a fresh report.html via /api/evaluation/run + /report/<sid>
    so each config gets its own report (the API session keeps only the
    most-recent report otherwise)
  - downloads the model bundle via /api/evaluation/download-model and
    saves to <config>/model.zip
  - for n_seeds runs, splits the multi-seed folder layout into
    A5_nseeds3_seed{0,1,2}/ and writes A5_nseeds3_summary.json
  - emits a global A5_summary.md / A5_summary.json with tol/p80/r²/GEH<5
    per config + the best/issues table.

Idempotent — safe to re-run.

Usage:
    python postprocess_a5.py
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
EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"
OUT_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05"
)
WORKSPACE_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/tmp_workdir"
)
YEAR_MAPPING = {
    "2019": 1, "2020": 2, "2021": 3, "2022": 4,
    "2023": 5, "2024": 6, "2025": 7,
}

# All config names produced by run_a5.py (matches CONFIGS in run_a5.py).
EXPECTED_CONFIGS = [
    "A5_HardMining",
    "A5_Curriculum",
    "A5_HardMining_Curriculum",
    "A5_QuantileHead",
    "A5_PinballP80_LogTarget",
    "A5_nseeds3",
    "A5_nseeds3_perm2",
    "A5_BootstrapCI95",
    "A5_kfold_k5",
    "A5_HardMining_perm2",
    "A5_Curriculum_perm2",
    "A5_Curriculum_recent2",
]


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def login() -> str:
    r = requests.post(
        f"{API}/api/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _find_session_id() -> str | None:
    """Recover the session id used by run_a5.py from the log."""
    log = OUT_ROOT / "run_a5.log"
    if not log.exists():
        return None
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "session_id=" in line:
            return line.split("session_id=")[-1].strip()
    return None


def _ci_width_ratio(ci: list[float] | None, mean: float | None) -> float | None:
    if not (isinstance(ci, list) and len(ci) == 2 and mean):
        return None
    try:
        return abs(ci[1] - ci[0]) / abs(mean) if mean else None
    except (TypeError, ZeroDivisionError):
        return None


def _detect_broken(run_eval: dict[str, Any]) -> tuple[bool, str]:
    reasons: list[str] = []
    tol_in = run_eval.get("tol_in_n")
    tol_total = run_eval.get("tol_total")
    p80 = run_eval.get("err_rel_p80")
    metrics = run_eval.get("metrics") or {}
    buckets = run_eval.get("metrics_by_tmja_bucket") or []
    ci = run_eval.get("metrics_ci95") or {}

    if tol_in == 0 and tol_total == 0:
        reasons.append("tolerance counts 0/0")
    if p80 in (None, "-%", "-"):
        reasons.append("p80 missing")
    if not buckets:
        reasons.append("barplot missing")
    for axis in ("r2", "p80", "tol_in_pct"):
        means = {
            "r2": metrics.get("r_squared"),
            "p80": p80,
            "tol_in_pct": run_eval.get("tol_in_pct"),
        }
        ratio = _ci_width_ratio(ci.get(axis), means.get(axis))
        if ratio is not None and ratio > 0.5:
            reasons.append(f"CI95[{axis}] width > 50% of mean ({ratio:.2f})")
    return (bool(reasons), "; ".join(reasons))


def build_metrics_json(
    config_dir: Path,
    overall_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read summary.json and project into the full metrics.json schema."""
    summary_path = config_dir / "summary.json"
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    runs_eval = summary.get("runs_eval") or {}
    results = summary.get("results") or []

    per_run_metrics: dict[str, Any] = {}
    for run_name, ev in runs_eval.items():
        broken, reason = _detect_broken(ev)
        # Lookup matching training result for full Phase 0-5 flags.
        tr = next((r for r in results if r.get("run_name") == run_name), {})
        per_run_metrics[run_name] = {
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
                "use_curriculum": tr.get("use_curriculum"),
                "curriculum_phase_a_epochs": tr.get("curriculum_phase_a_epochs"),
                "use_quantile_head": tr.get("use_quantile_head"),
                "target_log_transform": tr.get("target_log_transform"),
                "n_seeds": tr.get("n_seeds"),
                "seed_index": tr.get("seed_index"),
                "seed": tr.get("seed"),
            },
            "metrics": ev.get("metrics") or {},
            "metrics_ci95": ev.get("metrics_ci95") or {},
            "metrics_by_tmja_bucket": ev.get("metrics_by_tmja_bucket") or [],
            "drift_by_year": ev.get("drift_by_year") or [],
            "tol_in_pct": ev.get("tol_in_pct"),
            "tol_in_n": ev.get("tol_in_n"),
            "tol_total": ev.get("tol_total"),
            "err_rel_p80": ev.get("err_rel_p80"),
            "broken": broken,
            "broken_reason": reason if broken else None,
        }

    out = {
        "config_idx": summary.get("config_idx"),
        "name": summary.get("name"),
        "overrides": summary.get("overrides"),
        "started_at": summary.get("started_at"),
        "ended_at": summary.get("ended_at"),
        "wall_seconds": summary.get("wall_seconds")
            or (overall_summary or {}).get("wall_seconds"),
        "status": summary.get("status"),
        "best_model": summary.get("best_model"),
        "best_val_loss": summary.get("best_val_loss"),
        "total_models": summary.get("total_models"),
        "copied_models": summary.get("copied_models") or [],
        "n_seeds_aggregate": summary.get("n_seeds_aggregate"),
        "kfold_summary": summary.get("kfold_summary"),
        "kfold_error": summary.get("kfold_error"),
        "runs": per_run_metrics,
    }
    (config_dir / "metrics.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return out


def write_readme(config_dir: Path, metrics: dict[str, Any]) -> None:
    name = metrics.get("name") or config_dir.name
    overrides = metrics.get("overrides") or {}
    runs = metrics.get("runs") or {}
    lines: list[str] = []
    lines.append(f"# {name}")
    lines.append("")
    lines.append("**Worker:** A5 (port 7005)  ")
    lines.append("**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)  ")
    lines.append("**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)")
    lines.append("")
    lines.append("## Overrides (on top of baseline)")
    lines.append("```json")
    lines.append(json.dumps(overrides, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Baseline")
    lines.append("- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)")
    lines.append("- loss=`mse`, dropout=0.025, neurons_factors=[3,2,1], lr=0.01, batch=256, elu")
    lines.append("- min_epochs=1000, max_epochs=1250, test_size=0.05, no weighting")
    lines.append("")
    lines.append("## Models trained")
    for rn, rd in runs.items():
        m = rd.get("metrics") or {}
        broken = rd.get("broken")
        flag = "[BROKEN]" if broken else "[OK]"
        lines.append(
            f"- `{rn}` {flag}  "
            f"tol={rd.get('tol_in_pct')}% ({rd.get('tol_in_n')}/{rd.get('tol_total')})  "
            f"p80={rd.get('err_rel_p80')}%  "
            f"R²={m.get('r_squared')}  GEH<5={m.get('geh_pct_below_5')}%  "
            f"RMSE={m.get('rmse')}  MAE={m.get('mae')}"
        )
        if broken:
            lines.append(f"  - reason: `{rd.get('broken_reason')}`")
    lines.append("")
    if metrics.get("n_seeds_aggregate"):
        lines.append("## n_seeds aggregate (mean/std)")
        lines.append("```json")
        lines.append(json.dumps(metrics["n_seeds_aggregate"], indent=2))
        lines.append("```")
        lines.append("")
    if metrics.get("kfold_summary"):
        lines.append("## k-fold summary")
        lines.append("```json")
        lines.append(json.dumps(metrics["kfold_summary"], indent=2))
        lines.append("```")
        lines.append("")
    lines.append(f"_Wall-clock: {metrics.get('wall_seconds')}s  "
                 f"Status: `{metrics.get('status')}`_")
    (config_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def fetch_report_and_model(
    token: str,
    sid: str,
    config_dir: Path,
    metrics: dict[str, Any],
) -> None:
    """Re-evaluate one model so the session's report.html reflects this run,
    then GET /report and /download-model.

    We do this for the single 'best' run of each config (or the first copied
    one) — for n_seeds folders that's the seed[0]. Skip if there are no
    copied models or the API session no longer exists.
    """
    copied = metrics.get("copied_models") or []
    if not copied:
        _log(f"  {config_dir.name}: no models to re-eval (skipping report)")
        return
    target_run = metrics.get("best_model") or copied[0]
    server_dir = WORKSPACE_ROOT / sid / "models"
    if not server_dir.exists():
        _log(f"  {config_dir.name}: server dir {server_dir} missing")
        return
    headers = {"Authorization": f"Bearer {token}"}
    eval_body = {
        "session_id": sid,
        "model_name": target_run,
        "model_dir": str(server_dir),
        "year_column_name": "annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    try:
        r = requests.post(
            f"{API}/api/evaluation/run?bootstrap_iter=200",
            json=eval_body,
            headers=headers,
            timeout=600,
        )
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _log(f"  {config_dir.name}: re-eval failed ({exc})")
        return

    # 1) report.html
    try:
        r = requests.get(
            f"{API}/api/evaluation/report/{sid}",
            headers=headers,
            timeout=120,
        )
        r.raise_for_status()
        html = r.json().get("report_html") or ""
        (config_dir / "report.html").write_text(html, encoding="utf-8")
        _log(f"  {config_dir.name}: report.html saved ({len(html)} bytes)")
    except Exception as exc:  # noqa: BLE001
        _log(f"  {config_dir.name}: /report failed ({exc})")

    # 2) model zip
    try:
        params = {
            "model_name": target_run,
            "model_dir": str(server_dir),
            "session_id": sid,
        }
        r = requests.get(
            f"{API}/api/evaluation/download-model",
            params=params,
            headers=headers,
            timeout=180,
        )
        if r.status_code == 200:
            (config_dir / "model.zip").write_bytes(r.content)
            _log(f"  {config_dir.name}: model.zip saved ({len(r.content)} bytes)")
        else:
            _log(f"  {config_dir.name}: download-model HTTP {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        _log(f"  {config_dir.name}: download-model failed ({exc})")


def split_nseeds_dir(config_dir: Path) -> dict[str, Any] | None:
    """For A5_nseeds3 / A5_nseeds3_perm2, split the single config dir
    into A5_<name>_seed{0,1,2}/ folders + an aggregate JSON.

    With n_seeds=3, the orchestrator copies the 3 sibling model dirs
    (suffixed _seed0/_seed1/_seed2) under models/. We mirror them out so
    downstream tools can treat them as independent runs.
    """
    summary_path = config_dir / "summary.json"
    if not summary_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    copied = summary.get("copied_models") or []
    runs_eval = summary.get("runs_eval") or {}
    results = summary.get("results") or []
    if not (copied and any("seed" in r.lower() for r in copied)):
        return None

    base_name = config_dir.name
    seed_runs = []
    for run_name in copied:
        # Identify seed_index from suffix or results entry
        seed_match = next((r for r in results if r.get("run_name") == run_name), {})
        seed_idx = seed_match.get("seed_index")
        if seed_idx is None:
            # fall back to filename suffix
            for cand in ("seed0", "seed1", "seed2"):
                if cand in run_name:
                    seed_idx = int(cand[-1])
                    break
        seed_idx = seed_idx if seed_idx is not None else len(seed_runs)
        seed_dir = OUT_ROOT / f"{base_name}_seed{seed_idx}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        # Copy that single model subfolder + eval
        src_model = config_dir / "models" / run_name
        dst_model = seed_dir / "model"
        if src_model.exists():
            if dst_model.exists():
                shutil.rmtree(dst_model)
            shutil.copytree(src_model, dst_model)
        # Per-seed metrics.json (subset of parent)
        ev = runs_eval.get(run_name, {})
        broken, reason = _detect_broken(ev)
        per_seed_metrics = {
            "config_name": base_name,
            "seed_index": seed_idx,
            "run_name": run_name,
            "training": seed_match,
            "metrics": ev.get("metrics") or {},
            "metrics_ci95": ev.get("metrics_ci95") or {},
            "metrics_by_tmja_bucket": ev.get("metrics_by_tmja_bucket") or [],
            "drift_by_year": ev.get("drift_by_year") or [],
            "tol_in_pct": ev.get("tol_in_pct"),
            "tol_in_n": ev.get("tol_in_n"),
            "tol_total": ev.get("tol_total"),
            "err_rel_p80": ev.get("err_rel_p80"),
            "broken": broken,
            "broken_reason": reason if broken else None,
        }
        (seed_dir / "metrics.json").write_text(
            json.dumps(per_seed_metrics, indent=2, default=str), encoding="utf-8"
        )
        # README for the seed
        (seed_dir / "README.md").write_text(
            f"# {base_name} — seed {seed_idx}\n\n"
            f"Run: `{run_name}`\n\n"
            f"tol={per_seed_metrics['tol_in_pct']}% "
            f"({per_seed_metrics['tol_in_n']}/{per_seed_metrics['tol_total']})  "
            f"p80={per_seed_metrics['err_rel_p80']}%  "
            f"R²={(per_seed_metrics['metrics'] or {}).get('r_squared')}\n",
            encoding="utf-8",
        )
        seed_runs.append(per_seed_metrics)

    # Aggregate
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
        "config_name": base_name,
        "n_seeds": len(seed_runs),
        "seeds": [r["seed_index"] for r in seed_runs],
        "tol_in_pct": _stats([r["tol_in_pct"] for r in seed_runs]),
        "err_rel_p80": _stats([r["err_rel_p80"] for r in seed_runs]),
        "r_squared": _stats([(r["metrics"] or {}).get("r_squared") for r in seed_runs]),
    }
    (OUT_ROOT / f"{base_name}_summary.json").write_text(
        json.dumps(agg, indent=2, default=str), encoding="utf-8"
    )
    return agg


def write_md_summary(all_metrics: list[dict[str, Any]]) -> None:
    total_wall = sum(int(m.get("wall_seconds") or 0) for m in all_metrics)
    lines: list[str] = []
    lines.append("# A5 — Phase 05 batch summary (training tricks)")
    lines.append("")
    lines.append("Worker A5, port 7005. Baseline: Full 11 features, mse, drp=0.025,")
    lines.append("ep=1000, no weighting, neurons=[3,2,1], lr=0.01, batch=256, elu, test=0.05.")
    lines.append("")
    lines.append(f"Total wall-clock: {total_wall}s ({total_wall // 60}m {total_wall % 60}s).")
    lines.append("")
    lines.append("| # | Name | Status | Best model | tol% | p80% | R² | GEH<5% | broken? |")
    lines.append("| - | ---- | ------ | ---------- | ---- | ---- | -- | ------ | ------- |")

    best_score = -1.0
    best_name = "-"
    issues: list[str] = []
    for m in all_metrics:
        runs = m.get("runs") or {}
        best = m.get("best_model") or (next(iter(runs.keys())) if runs else "")
        ev = runs.get(best) or {}
        metrics = ev.get("metrics") or {}
        tol = ev.get("tol_in_pct")
        p80 = ev.get("err_rel_p80")
        r2 = metrics.get("r_squared")
        geh = metrics.get("geh_pct_below_5")
        broken = ev.get("broken")
        broken_flag = "yes" if broken else ""
        lines.append(
            f"| {m.get('config_idx')} | {m.get('name')} | {m.get('status')} | "
            f"{best} | {tol} | {p80} | {r2} | {geh} | {broken_flag} |"
        )
        # Score: combination of tol% and R² (higher is better), minus broken penalty
        try:
            score = float(tol or 0) + 100.0 * float(r2 or 0)
            if not broken and score > best_score:
                best_score = score
                best_name = m.get("name") or "-"
        except (TypeError, ValueError):
            pass
        if broken:
            issues.append(f"- {m.get('name')}: {ev.get('broken_reason')}")
        if m.get("status") and m.get("status") != "ok":
            issues.append(f"- {m.get('name')}: status={m.get('status')}")

    lines.append("")
    lines.append(f"## Best config: `{best_name}` (score={best_score:.2f})")
    if issues:
        lines.append("")
        lines.append("## Issues")
        lines.extend(issues)

    lines.append("")
    lines.append("## Per-config details")
    for m in all_metrics:
        lines.append("")
        lines.append(f"### {m.get('config_idx')}. {m.get('name')}")
        lines.append(f"- status: `{m.get('status')}`  wall={m.get('wall_seconds')}s")
        ov = m.get("overrides") or {}
        if ov:
            lines.append(f"- overrides: `{ov}`")
        agg = m.get("n_seeds_aggregate")
        if agg:
            lines.append(f"- n_seeds aggregate: `{agg}`")
        kf = m.get("kfold_summary")
        if kf:
            lines.append(f"- kfold summary: `{kf}`")
        for rn, ev in (m.get("runs") or {}).items():
            metrics = ev.get("metrics") or {}
            lines.append(
                f"  - `{rn}` tol={ev.get('tol_in_pct')}% "
                f"p80={ev.get('err_rel_p80')}%  R²={metrics.get('r_squared')}  "
                f"GEH<5={metrics.get('geh_pct_below_5')}%  "
                f"CI95={ev.get('metrics_ci95')}"
            )

    (OUT_ROOT / "A5_summary.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_ROOT / "A5_summary.json").write_text(
        json.dumps(all_metrics, indent=2, default=str), encoding="utf-8"
    )


def main() -> int:
    sid = _find_session_id()
    _log(f"recovered session_id={sid}")
    token = None
    if sid:
        try:
            token = login()
            _log("login OK")
        except Exception as exc:  # noqa: BLE001
            _log(f"login failed: {exc} (will skip report/model fetches)")

    all_metrics: list[dict[str, Any]] = []
    for name in EXPECTED_CONFIGS:
        d = OUT_ROOT / name
        if not d.exists():
            _log(f"SKIP {name}: dir missing")
            continue
        _log(f"--- {name} ---")
        m = build_metrics_json(d)
        if m is None:
            _log(f"  no summary.json yet for {name}")
            continue
        # If n_seeds run, split into per-seed dirs
        if "nseeds" in name.lower():
            split_nseeds_dir(d)
        write_readme(d, m)
        if token and sid:
            fetch_report_and_model(token, sid, d, m)
        all_metrics.append(m)

    write_md_summary(all_metrics)
    _log(f"wrote A5_summary.md ({len(all_metrics)} configs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
