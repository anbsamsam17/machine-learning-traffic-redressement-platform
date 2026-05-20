"""Rebuild A2_summary.md from the per-run metrics.json files."""
from __future__ import annotations

import json
from pathlib import Path

BATCH = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
    r"\.playwright-mcp\Batch_MDL_Phase05"
)
SUMMARY_MD = BATCH / "A2_summary.md"
CONFIGS = json.loads((BATCH / "configs_A2.json").read_text(encoding="utf-8"))

HEADER = """# Worker A2 — Feature-engineering ablation (12 configs)

Phase 0-5, baseline locked: `mse`, `dropout=0.025`, `min_epochs=1000`,
`max_epochs=1250`, `neurons_factors=[3,2,1]`, `lr=0.01`, `batch_size=256`,
`elu`, `test_size=0.05`, no sample-weighting.

Port: **7002**. Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon TV, 3632 capteurs, 2019-2025), in-sample validation.

Pre-processing of the geojson (`preprocess_A2.py`) adds:
- `flag_permanent` (1 if Type Compteur == Permanent), `flag_recent_year` (year==2025).
- `year_mapped` (2019..2025 -> 1..7), `Annee` alias.
- `ratio_PLTV = TMJOFCDPL / max(TMJOFCDTV, 1)`.
- `log_TMJOFCDTV = log1p(max(TMJOFCDTV, 0))`, idem `log_TMJOFCDPL`.
- one-hot `fc_1..fc_5` from `functional_class`.
- `rs_*` = RobustScaler-encoded copies (median, IQR/1.349) of the 9 numeric distances/flows for config #7.
- `yemb1..yemb3` = sinusoidal positional encoding of `year_mapped` (dim=3 emulation for config #8).

## Notes on emulated knobs

- **Config #7 (RobustScaler)** — `normalize()` supports `robust` internally
  but `training_pipeline.py` hard-wires `"standard"`. We pre-encode 9 features
  via `(x - median)/(IQR/1.349)` and feed them with `on_off_norm=False`.
- **Config #8 (year_embedding dim=3)** — `use_year_embedding` is wired in
  `model_builder.py` but ignored by `training_pipeline.py`. Emulated with
  three sinusoidal positional encodings of `year_mapped`.

## Results

| # | run_name | n_in | tol_in % | p80 % | R^2 | RMSE | MAE | GEH<5 % | train_s | broken? |
|---|---|---|---|---|---|---|---|---|---|---|
"""

CI_HEADER = """
## CI95 (bootstrap 1000 iter)

| # | run_name | tol_in_pct | p80 | r2 |
|---|---|---|---|---|
"""


def _row(idx: int, cfg: dict) -> tuple[str, str, dict | None]:
    name = cfg["name"]
    path = BATCH / name / "metrics.json"
    if not path.exists():
        return (f"| {idx} | {name} | {len(cfg['input_cols'])} | -- | -- | -- | -- | -- | -- | -- | NO_DATA |\n", "", None)
    d = json.loads(path.read_text(encoding="utf-8"))
    m = d.get("metrics") or {}
    tol_in = d.get("tol_inclus", 0)
    tol_total = d.get("tol_total", 0)
    tol_pct = (100 * tol_in / tol_total) if tol_total else float("nan")
    p80 = d.get("err_p80_pct")
    r2 = m.get("r_squared")
    rmse = m.get("rmse")
    mae = m.get("mae")
    geh5 = m.get("geh_pct_below_5")
    train_s = d.get("train_seconds")
    broken = "YES" if d.get("broken") else "no"
    if broken == "YES":
        broken += " ({})".format(",".join(d.get("broken_reasons", [])))

    def _fmt(v, digits=3):
        try:
            return f"{float(v):.{digits}f}"
        except (TypeError, ValueError):
            return "--"

    main = (
        f"| {idx} | {name} | {d.get('n_inputs', len(cfg['input_cols']))} "
        f"| {_fmt(tol_pct, 2)} | {_fmt(p80, 2)} | {_fmt(r2, 4)} "
        f"| {_fmt(rmse, 4)} | {_fmt(mae, 4)} | {_fmt(geh5, 2)} "
        f"| {_fmt(train_s, 1)} | {broken} |\n"
    )

    ci_line = ""
    ci = d.get("metrics_ci95") or {}
    if ci:
        def _ci(k):
            v = ci.get(k)
            if not v:
                return "--"
            return f"[{v[0]}, {v[1]}]"

        ci_line = (
            f"| {idx} | {name} | {_ci('tol_in_pct')} | {_ci('p80')} | {_ci('r2')} |\n"
        )
    return main, ci_line, d


def main() -> None:
    rows = []
    ci_rows = []
    raw: list[dict] = []
    for cfg in CONFIGS:
        idx = cfg["id"]
        row, ci_row, summary = _row(idx, cfg)
        rows.append(row)
        if ci_row:
            ci_rows.append(ci_row)
        if summary:
            raw.append(summary)

    text = HEADER + "".join(rows)
    if ci_rows:
        text += CI_HEADER + "".join(ci_rows)

    # Best by tol_in_pct (excluding broken runs)
    healthy = [d for d in raw if not d.get("broken")]
    if healthy:
        def _tol_pct(d):
            ti = d.get("tol_inclus", 0)
            tt = d.get("tol_total", 0)
            return (100 * ti / tt) if tt else 0.0

        ranked = sorted(healthy, key=_tol_pct, reverse=True)
        text += "\n## Ranking by tol_in % (healthy only)\n\n"
        for i, d in enumerate(ranked[:12], start=1):
            text += f"{i}. **{d['run_name']}** — tol_in={_tol_pct(d):.2f}%, p80={d.get('err_p80_pct')}, R^2={d.get('metrics', {}).get('r_squared')}\n"

    SUMMARY_MD.write_text(text, encoding="utf-8")
    print(f"Wrote {SUMMARY_MD}")


if __name__ == "__main__":
    main()
