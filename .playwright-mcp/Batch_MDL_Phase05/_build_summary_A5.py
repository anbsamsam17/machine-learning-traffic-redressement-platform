"""Re-emit A5_summary.md from the metrics.json files of every A5_* config,
including kfold-broken marker and n_seeds aggregates."""

from __future__ import annotations

import json
from pathlib import Path

OUT_ROOT = Path(
    r"C:/Users/SamirANBRI/Desktop/AppRedressement/mdl-redressement-portfolio/"
    r".playwright-mcp/Batch_MDL_Phase05"
)
ORDER = [
    "A5_HardMining", "A5_Curriculum", "A5_HardMining_Curriculum",
    "A5_QuantileHead", "A5_PinballP80_LogTarget",
    "A5_nseeds3", "A5_nseeds3_perm2",
    "A5_BootstrapCI95", "A5_kfold_k5",
    "A5_HardMining_perm2", "A5_Curriculum_perm2", "A5_Curriculum_recent2",
]


def _row(name: str, idx: int) -> dict:
    p = OUT_ROOT / name / "metrics.json"
    if not p.exists():
        return {"config_idx": idx, "name": name, "status": "missing"}
    m = json.loads(p.read_text(encoding="utf-8"))
    metrics = m.get("metrics") or {}
    return {
        "config_idx": idx,
        "name": name,
        "overrides": m.get("overrides"),
        "tol_in_pct": m.get("tol_in_pct"),
        "err_rel_p80": m.get("err_rel_p80"),
        "r_squared": metrics.get("r_squared"),
        "geh_pct_below_5": metrics.get("geh_pct_below_5"),
        "broken": m.get("broken"),
        "broken_reason": m.get("broken_reason"),
        "wall_seconds": m.get("wall_seconds"),
        "metrics_ci95": m.get("metrics_ci95"),
        "n_seeds_aggregate": m.get("n_seeds_aggregate"),
    }


def main() -> int:
    rows = [_row(name, idx + 1) for idx, name in enumerate(ORDER)]
    total_wall = sum(int(r.get("wall_seconds") or 0) for r in rows)

    lines: list[str] = []
    lines.append("# A5 — Phase 05 batch summary (training tricks)")
    lines.append("")
    lines.append("Worker A5, port 7005. Baseline: Full 11 features, mse, drp=0.025,")
    lines.append("ep=1000, no weighting, neurons=[3,2,1], lr=0.01, batch=256, elu, test=0.05.")
    lines.append("")
    lines.append(f"Total wall-clock: **{total_wall}s** ({total_wall // 60}m {total_wall % 60}s).")
    lines.append("")
    lines.append("| # | Name | tol% | p80% | R² | GEH<5% | broken? | wall(s) |")
    lines.append("| - | ---- | ---- | ---- | -- | ------ | ------- | ------- |")

    best_score = -1.0
    best_name = "-"
    issues: list[str] = []
    for r in rows:
        broken = bool(r.get("broken"))
        bf = "yes" if broken else ""
        lines.append(
            f"| {r.get('config_idx')} | {r.get('name')} | "
            f"{r.get('tol_in_pct')} | {r.get('err_rel_p80')} | "
            f"{r.get('r_squared')} | {r.get('geh_pct_below_5')} | "
            f"{bf} | {r.get('wall_seconds')} |"
        )
        try:
            score = float(r.get("tol_in_pct") or 0) + 100.0 * float(r.get("r_squared") or 0)
            if not broken and score > best_score:
                best_score = score
                best_name = r.get("name") or "-"
        except (TypeError, ValueError):
            pass
        if broken:
            issues.append(f"- **{r.get('name')}**: {r.get('broken_reason')}")

    lines.append("")
    lines.append(f"## Best config: `{best_name}`  (composite score = {best_score:.2f})")
    lines.append("")
    if issues:
        lines.append("## Issues")
        lines.extend(issues)
        lines.append("")

    lines.append("## Per-config detail (CI95 + n_seeds aggregates)")
    for r in rows:
        lines.append("")
        lines.append(f"### {r.get('config_idx')}. {r.get('name')}")
        ov = r.get("overrides") or {}
        if ov:
            lines.append(f"- overrides: `{ov}`")
        ci = r.get("metrics_ci95") or {}
        if ci:
            lines.append(f"- CI95: `{ci}`")
        agg = r.get("n_seeds_aggregate")
        if agg:
            lines.append(f"- n_seeds aggregate:")
            lines.append("  ```json")
            lines.append("  " + json.dumps(agg, indent=2).replace("\n", "\n  "))
            lines.append("  ```")

    (OUT_ROOT / "A5_summary.md").write_text("\n".join(lines), encoding="utf-8")

    (OUT_ROOT / "A5_summary.json").write_text(
        json.dumps(rows, indent=2, default=str), encoding="utf-8"
    )

    print(f"wrote A5_summary.md ({len(rows)} configs, total {total_wall}s)")
    print(f"best: {best_name}")
    if issues:
        print(f"issues: {len(issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
