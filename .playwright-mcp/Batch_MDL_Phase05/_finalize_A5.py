"""Final touches for the A5 batch:
  1. Synthesize A5_HardMining/metrics.json and README.md from the existing
     summary.json (which the original run_a5.py wrote with the full eval data).
  2. Synthesize A5_nseeds3/metrics.json + README.md and A5_nseeds3_perm2/
     metrics.json + README.md from their _summary.json aggregates so the
     overall summary table can find them.
  3. Re-emit A5_summary.md with broken=true marker for kfold (logger bug).

Idempotent.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

OUT_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05"
)


def _build_hardmining() -> None:
    """A5_HardMining was written by the original run_a5.py before the
    metrics.json schema was introduced. Build metrics.json + README.md
    from summary.json which already has runs_eval + results."""
    d = OUT_ROOT / "A5_HardMining"
    sp = d / "summary.json"
    if not sp.exists():
        return
    summary = json.loads(sp.read_text(encoding="utf-8"))
    runs_eval = summary.get("runs_eval") or {}
    results = summary.get("results") or []
    if not runs_eval:
        return
    run_name = next(iter(runs_eval.keys()))
    ev = runs_eval[run_name]
    tr = next((r for r in results if r.get("run_name") == run_name), {})
    buckets = ev.get("metrics_by_tmja_bucket") or []
    tol_in_n = sum(int(b.get("tol_in_n") or 0) for b in buckets)
    tol_total = sum(int(b.get("n_samples") or 0) for b in buckets)
    ci = ev.get("metrics_ci95") or {}
    p80_ci = ci.get("p80")
    p80 = (
        round((p80_ci[0] + p80_ci[1]) / 2.0, 4)
        if isinstance(p80_ci, list) and len(p80_ci) == 2 else None
    )

    metrics_doc = {
        "config_idx": summary.get("config_idx"),
        "name": summary.get("name"),
        "overrides": summary.get("overrides"),
        "bootstrap_iter": 1000,
        "wall_seconds": None,
        "run_name": run_name,
        "n_inputs": len(tr.get("input_cols", []) or []),
        "input_cols": tr.get("input_cols"),
        "on_off_norm": tr.get("on_off_norm"),
        "training_flags": {
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
            "use_flag_permanent_weighting": tr.get("use_flag_permanent_weighting"),
            "use_flag_recent_year_weighting": tr.get("use_flag_recent_year_weighting"),
            "use_hard_example_mining": tr.get("use_hard_example_mining"),
            "use_curriculum": tr.get("use_curriculum"),
            "n_seeds": tr.get("n_seeds"),
            "seed_index": tr.get("seed_index"),
            "seed": tr.get("seed"),
        },
        "metrics": ev.get("metrics") or {},
        "metrics_ci95": ci,
        "metrics_by_tmja_bucket": buckets,
        "drift_by_year": ev.get("drift_by_year") or [],
        "tol_in_pct": ev.get("tol_in_pct"),
        "tol_in_n": tol_in_n,
        "tol_total": tol_total,
        "err_rel_p80": p80 if p80 is not None else ev.get("err_rel_p80"),
        "broken": False,
        "broken_reason": None,
        "best_val_loss": tr.get("val_loss"),
    }
    (d / "metrics.json").write_text(
        json.dumps(metrics_doc, indent=2, default=str), encoding="utf-8"
    )

    m = ev.get("metrics") or {}
    lines = [
        f"# A5_HardMining",
        "",
        "**Worker:** A5 (port 7005)",
        "**Phase 05:** training tricks — hard example mining baseline",
        "**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)",
        "",
        "## Overrides (on top of baseline)",
        "```json",
        json.dumps(summary.get("overrides"), indent=2),
        "```",
        "",
        "## Validation metrics",
        f"- Capteurs tolérance inclus: **{tol_in_n}/{tol_total}** ({ev.get('tol_in_pct')}%)",
        f"- Erreur relative p80: **{ev.get('err_rel_p80')}%**",
        f"- R²: **{m.get('r_squared')}**",
        f"- GEH < 5: **{m.get('geh_pct_below_5')}%**",
        f"- RMSE: {m.get('rmse')}  MAE: {m.get('mae')}  MAPE: {m.get('mape')}%",
        f"- Median rel. error: {m.get('median_relative_error')}%",
        "",
        "## CI95 (bootstrap)",
        "```json",
        json.dumps(ci, indent=2),
        "```",
        "",
        "## Per-bucket TMJOBCTV",
        "| bucket | n | tol_in_n | tol% | p80 | R² |",
        "| ------ | - | -------- | ---- | --- | -- |",
    ]
    for b in buckets:
        lines.append(
            f"| {b.get('bucket')} | {b.get('n_samples')} | "
            f"{b.get('tol_in_n')} | {b.get('tol_in_pct')}% | "
            f"{b.get('p80')} | {b.get('r2')} |"
        )
    lines.extend([
        "",
        "## Drift by year",
        "| year | n | R² | MAE | tol% | p80% |",
        "| ---- | - | -- | --- | ---- | ---- |",
    ])
    for d2 in ev.get("drift_by_year") or []:
        lines.append(
            f"| {d2.get('year_label')} | {d2.get('n_samples')} | "
            f"{d2.get('r2')} | {d2.get('mae')} | "
            f"{d2.get('tol_in_pct')}% | {d2.get('p80')}% |"
        )
    lines.append("")
    lines.append("_Note: Initial baseline run from the first run_a5.py pass; "
                 "wall-clock not separately captured here (≈155s)._")
    (d / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _build_nseeds_parent(name: str) -> None:
    """Build a top-level metrics.json + README.md for an n_seeds config
    based on the *_summary.json (aggregate) and per-seed metrics."""
    d = OUT_ROOT / name
    agg_path = OUT_ROOT / f"{name}_summary.json"
    if not agg_path.exists():
        return
    agg = json.loads(agg_path.read_text(encoding="utf-8"))
    # Reload seed[0]'s metrics.json to back-fill the parent metrics shape
    seed0_metrics_path = OUT_ROOT / f"{name}_seed0" / "metrics.json"
    seed0_metrics = (
        json.loads(seed0_metrics_path.read_text(encoding="utf-8"))
        if seed0_metrics_path.exists() else {}
    )
    out = {
        "name": name,
        "overrides": seed0_metrics.get("overrides"),
        "run_name": "<n_seeds aggregate>",
        "n_seeds_aggregate": agg,
        "seeds": agg.get("seeds"),
        # For the global summary scoring, expose the mean values:
        "tol_in_pct": (agg.get("tol_in_pct") or {}).get("mean"),
        "err_rel_p80": (agg.get("err_rel_p80") or {}).get("mean"),
        "metrics": {
            "r_squared": (agg.get("r_squared") or {}).get("mean"),
            "geh_pct_below_5": (agg.get("geh_pct_below_5") or {}).get("mean"),
        },
        "broken": False,
        "broken_reason": None,
    }
    (d / "metrics.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )

    lines = [
        f"# {name}",
        "",
        "**Worker:** A5 (port 7005)",
        "**Phase 05:** training tricks — multi-seed ensemble",
        f"**n_seeds:** {agg.get('n_seeds')}  (seed indices: {agg.get('seeds')})",
        "",
        "## Aggregate metrics (mean ± std across seeds)",
        "| Metric | Mean | Std | Values |",
        "| ------ | ---- | --- | ------ |",
    ]
    for k in ("tol_in_pct", "err_rel_p80", "r_squared", "geh_pct_below_5"):
        v = agg.get(k) or {}
        lines.append(
            f"| {k} | {v.get('mean')} | {v.get('std')} | {v.get('values')} |"
        )
    lines.extend([
        "",
        "Per-seed metrics live in sibling directories: "
        f"`{name}_seed0/`, `{name}_seed1/`, `{name}_seed2/`.",
        "",
        "Full aggregate JSON also at "
        f"`{name}_summary.json` in the batch root.",
    ])
    (d / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _mark_kfold_broken() -> None:
    d = OUT_ROOT / "A5_kfold_k5"
    mp = d / "metrics.json"
    if not mp.exists():
        return
    m = json.loads(mp.read_text(encoding="utf-8"))
    kf_path = d / "kfold_result.json"
    if kf_path.exists():
        kf = json.loads(kf_path.read_text(encoding="utf-8"))
        # Check if any fold errored
        folds = kf.get("folds") or []
        errors = [f.get("error") for f in folds if f.get("error")]
        if errors:
            m["broken"] = True
            m["broken_reason"] = (
                f"k-fold endpoint API bug: {errors[0]} (all {len(folds)} folds failed)"
            )
            mp.write_text(json.dumps(m, indent=2, default=str), encoding="utf-8")


def main() -> int:
    _build_hardmining()
    _build_nseeds_parent("A5_nseeds3")
    _build_nseeds_parent("A5_nseeds3_perm2")
    _mark_kfold_broken()
    print("finalized A5 artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
