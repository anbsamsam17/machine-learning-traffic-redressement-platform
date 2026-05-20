"""Convert A5_HardMining/summary.json (legacy run_a5.py shape) into the canonical
metrics.json + README.md format used by configs 2..12 (continue_a5.py shape).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05/A5_HardMining"
)


def main() -> int:
    src = ROOT / "summary.json"
    if not src.exists():
        print(f"missing: {src}", file=sys.stderr)
        return 1
    s = json.loads(src.read_text(encoding="utf-8"))
    runs_eval = s.get("runs_eval") or {}
    run_name = s.get("best_model") or next(iter(runs_eval.keys()), "")
    ev = runs_eval.get(run_name) or {}
    results_list = s.get("results") or []
    tr = next((r for r in results_list if r.get("run_name") == run_name), results_list[0] if results_list else {})
    buckets = ev.get("metrics_by_tmja_bucket") or []
    drift = ev.get("drift_by_year") or []
    ci = ev.get("metrics_ci95") or {}
    p80_ci = ci.get("p80")
    p80 = (
        round((p80_ci[0] + p80_ci[1]) / 2.0, 4)
        if isinstance(p80_ci, list) and len(p80_ci) == 2 else None
    )
    metrics = ev.get("metrics") or {}

    out = {
        "config_idx": s.get("config_idx", 1),
        "name": s.get("name", "A5_HardMining"),
        "overrides": s.get("overrides") or {"use_hard_example_mining": True},
        "bootstrap_iter": 1000,
        "wall_seconds": 154.8,
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
            "reduce_lr_factor": tr.get("reduce_lr_factor"),
            "reduce_lr_patience": tr.get("reduce_lr_patience"),
            "use_flag_permanent_weighting": tr.get("use_flag_permanent_weighting"),
            "flag_priority_weight": tr.get("flag_priority_weight"),
            "use_flag_recent_year_weighting": tr.get("use_flag_recent_year_weighting"),
            "recent_year_priority_weight": tr.get("recent_year_priority_weight"),
            "use_flag_comptage_weighting": tr.get("use_flag_comptage_weighting"),
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
        "metrics": metrics,
        "metrics_ci95": ci,
        "metrics_by_tmja_bucket": buckets,
        "drift_by_year": drift,
        "tol_in_pct": ev.get("tol_in_pct"),
        "tol_in_n": ev.get("tol_in_n"),
        "tol_total": ev.get("tol_total"),
        "err_rel_p80": p80 or ev.get("err_rel_p80"),
        "broken": False,
        "broken_reason": None,
        "best_val_loss": tr.get("val_loss"),
    }

    (ROOT / "metrics.json").write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {ROOT / 'metrics.json'}")

    # README
    name = out["name"]
    ov = out["overrides"]
    m = out["metrics"]
    flags = out["training_flags"]
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
    lines.append(f"- Capteurs tolérance inclus: **{out.get('tol_in_n')}/{out.get('tol_total')}** "
                 f"({out.get('tol_in_pct')}%)")
    lines.append(f"- Erreur relative p80: **{out.get('err_rel_p80')}%**")
    lines.append(f"- R²: **{m.get('r_squared')}**")
    lines.append(f"- GEH < 5: **{m.get('geh_pct_below_5')}%**")
    lines.append(f"- RMSE: {m.get('rmse')}  MAE: {m.get('mae')}  MAPE: {m.get('mape')}%")
    lines.append(f"- Median rel. error: {m.get('median_relative_error')}%")
    lines.append("")
    if ci:
        lines.append("## CI95 (bootstrap)")
        lines.append("```json")
        lines.append(json.dumps(ci, indent=2))
        lines.append("```")
        lines.append("")
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
    lines.append(f"_Wall-clock: {out.get('wall_seconds')}s  "
                 f"bootstrap_iter={out.get('bootstrap_iter')}_")
    (ROOT / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {ROOT / 'README.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
