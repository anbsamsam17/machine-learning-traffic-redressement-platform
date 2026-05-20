"""Generate the aggregated Phase 5 index.html.

Reads every ``metrics.json`` under ``.playwright-mcp/Batch_MDL_Phase05/`` (one
per trained model directory), normalises the per-agent schema variants, and
emits a DataTables-driven sortable HTML page with all 76+ models plus
structured insights.

Reproducibility: re-run with no arguments. The script is idempotent —
existing ``index.html`` is overwritten.

    python build_index.py [--out .playwright-mcp/Batch_MDL_Phase05/index.html]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp" / "Batch_MDL_Phase05"
V1_DIR = PROJECT_ROOT / ".playwright-mcp" / "Batch_MDL_GrandLyon_TV"

DEFAULT_OUT = BATCH_DIR / "index.html"


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _safe_load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_speeds_constraint_violated(input_cols: Iterable[str]) -> bool:
    """The Phase 5 contract forbids using the two speed columns as inputs.

    Returns True when avg_speed_kmh or truck_avg_speed_kmh appears in the
    model's input_cols.
    """
    cols = {str(c) for c in input_cols}
    return bool(cols & {"avg_speed_kmh", "truck_avg_speed_kmh", "car_average_speed_kmh", "truck_average_speed_kmh"})


def _coerce_float(v: Any, default: float = float("nan")) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _row_for(metrics: dict[str, Any], folder: Path) -> dict[str, Any]:
    """Normalise one metrics.json file into a stable row schema."""
    name = metrics.get("name") or metrics.get("run_name") or folder.name

    # The training_flags subdict lives inside A5 outputs; A1/A2/A3/A4/A6 put
    # the same fields at the top level. We merge with top-level precedence.
    tflags = dict(metrics.get("training_flags") or {})
    flat = {**tflags, **{k: v for k, v in metrics.items() if k != "training_flags"}}

    inputs = list(flat.get("input_cols") or [])
    n_inputs = int(flat.get("n_inputs") or len(inputs))

    # Metrics block — some configs put fields at top level, others nest under
    # `metrics`. We support both.
    mblock = dict(flat.get("metrics") or {})

    def _g(key: str, default: float = float("nan")) -> float:
        if key in mblock:
            return _coerce_float(mblock.get(key), default)
        return _coerce_float(flat.get(key), default)

    rmse = _g("rmse")
    mae = _g("mae")
    r2 = _g("r_squared")
    geh_lt5 = _g("geh_pct_below_5")
    geh_med = _g("geh_mean")
    median_rel_err = _g("median_relative_error")
    p80 = _coerce_float(flat.get("err_p80_pct"))
    if math.isnan(p80):
        p80 = _g("err_rel_p80")

    tol_inclus = _coerce_int(flat.get("tol_inclus"))
    tol_total = _coerce_int(flat.get("tol_total"))
    tol_pct = (100.0 * tol_inclus / tol_total) if tol_total > 0 else float("nan")

    ci95 = dict(flat.get("metrics_ci95") or {})

    # CI95 helpers
    def _ci95(key: str) -> tuple[float, float] | None:
        v = ci95.get(key)
        if not v or len(v) != 2:
            # Some agents stash flat keys instead (A4_*: tol_in_pct_ci95 / err_p80_pct_ci95)
            alt = flat.get(f"{key}_ci95")
            if alt and len(alt) == 2:
                return _coerce_float(alt[0]), _coerce_float(alt[1])
            return None
        return _coerce_float(v[0]), _coerce_float(v[1])

    ci_tol = _ci95("tol_in_pct")
    ci_p80 = _ci95("p80")
    ci_r2 = _ci95("r2")

    # Per-bucket tolerance (TMJOBCTV)
    by_bucket = []
    for b in flat.get("metrics_by_tmja_bucket") or []:
        by_bucket.append({
            "label": b.get("bucket") or "",
            "tol_pct": _coerce_float(b.get("tol_in_pct")),
            "n": _coerce_int(b.get("n_samples")),
        })

    # Error counts < 15% and < 20% (where available)
    err_lt15 = _coerce_int(flat.get("n_err_lt15"))
    err_lt20 = _coerce_int(flat.get("n_err_lt20"))

    # Feature engineering & training tricks. The pre-bugfix metrics.json
    # files don't carry the `feature_engineering` echo — we infer chips
    # from input_cols and the config block too (back-compat).
    fe_chips: list[str] = []
    cfg_block = dict(flat.get("config") or {})
    add_pl_tv = bool(
        flat.get("add_pl_tv_ratio") or cfg_block.get("add_pl_tv_ratio")
        or ("ratio_PLTV" in inputs)
    )
    log_cols = list(
        flat.get("log_transform_cols") or cfg_block.get("log_transform_cols") or []
    )
    # Infer log1p augmentation from input_cols when no explicit list is present.
    log_inputs = [c for c in inputs if isinstance(c, str) and c.startswith("log_")]
    if log_inputs and not log_cols:
        log_cols = log_inputs
    one_hot_fc = bool(
        flat.get("one_hot_functional_class") or cfg_block.get("one_hot_functional_class")
        or any(isinstance(c, str) and c.startswith("fc_") for c in inputs)
    )
    use_year_emb = bool(
        flat.get("use_year_embedding") or cfg_block.get("use_year_embedding")
        # Pre-bugfix emulation in A2 used sinusoidal injection — flag from the
        # run name / description so the chip still shows up in the index.
        or "yearemb" in (name or "").lower()
        or "year_embedding" in str(flat.get("description") or "").lower()
    )
    scaler = (
        flat.get("scaler") or cfg_block.get("scaler") or ""
    )
    # Legacy A2 echoed `robust_scaled: True` instead of `scaler="robust"`.
    if not scaler and bool(flat.get("robust_scaled") or cfg_block.get("robust_scaled")):
        scaler = "robust"
    if add_pl_tv:
        fe_chips.append("ratio")
    if log_cols:
        fe_chips.append("log1p")
    if one_hot_fc:
        fe_chips.append("onehot")
    if use_year_emb:
        fe_chips.append("embed")
    if str(scaler) == "robust":
        fe_chips.append("robust")

    # Weighting summary
    use_perm = bool(flat.get("use_flag_permanent_weighting"))
    perm_w = _coerce_float(flat.get("flag_priority_weight"))
    use_recent = bool(flat.get("use_flag_recent_year_weighting"))
    recent_w = _coerce_float(flat.get("recent_year_priority_weight"))
    use_log_flow = bool(flat.get("use_log_flow_weighting"))
    weighting_parts: list[str] = []
    if use_perm and perm_w == perm_w and perm_w > 0:
        weighting_parts.append(f"perm×{int(perm_w)}" if perm_w == int(perm_w) else f"perm×{perm_w:.1f}")
    if use_recent and recent_w == recent_w and recent_w > 0:
        weighting_parts.append(f"recent×{int(recent_w)}" if recent_w == int(recent_w) else f"recent×{recent_w:.1f}")
    if use_log_flow:
        weighting_parts.append("log_flow")
    if use_perm and use_recent:
        # The two boosts are multiplicative in the training pipeline.
        weighting_parts.append("combined")
    weighting = ", ".join(weighting_parts) if weighting_parts else "—"

    # Training tricks
    tricks: list[str] = []
    if bool(flat.get("use_hard_example_mining")):
        tricks.append("hard_mining")
    if bool(flat.get("use_curriculum")):
        tricks.append("curriculum")
    n_seeds = _coerce_int(flat.get("n_seeds"), 1)
    if n_seeds > 1:
        tricks.append(f"nseeds={n_seeds}")
    if "kfold" in str(name).lower() or _coerce_int(flat.get("k"), 0) >= 2:
        tricks.append("kfold")
    tricks_str = ", ".join(tricks) if tricks else "—"

    # TTA
    tta_iter = _coerce_int(flat.get("tta_iter"), 1)

    # Files (relative links from the index.html location).
    relfolder = folder.name
    has_model_zip = (folder / "model.zip").exists()
    has_model_dir = (folder / "model").is_dir() or (folder / "models").is_dir()
    has_readme = (folder / "README.md").exists()
    has_report = (folder / "report.html").exists()

    # Constraint violation: speeds in input_cols.
    violated = _is_speeds_constraint_violated(inputs)

    train_seconds = _coerce_float(flat.get("train_seconds") or flat.get("wall_seconds"))

    row = {
        "name": name,
        "folder": relfolder,
        "agent": (name[:2] if name and name[:2] in {"A1", "A2", "A3", "A4", "A5", "A6"} else relfolder[:2]),
        "n_inputs": n_inputs,
        "ep_min": _coerce_int(flat.get("min_epochs") or flat.get("min_nb_epochs"), 0),
        "ep_max": _coerce_int(flat.get("max_epochs"), 0),
        "ep_trained": _coerce_int(flat.get("epochs_trained"), 0),
        "drop": _coerce_float(flat.get("dropout")),
        "dropout_schedule": str(flat.get("dropout_schedule") or "uniform"),
        "optimizer": str(flat.get("optimizer") or "adam"),
        "weight_decay": _coerce_float(flat.get("weight_decay"), 0.0),
        "clipnorm": flat.get("clipnorm"),
        "norm_layer": (flat.get("norm_layer") or ""),
        "use_skip": bool(flat.get("use_skip_connection")),
        "loss": str(flat.get("loss") or "mse"),
        "fe_chips": fe_chips,
        "target_log_transform": bool(flat.get("target_log_transform")),
        "use_quantile_head": bool(flat.get("use_quantile_head")),
        "weighting": weighting,
        "tricks": tricks_str,
        "tta": tta_iter,
        "tol_in": tol_inclus,
        "tol_total": tol_total,
        "tol_pct": tol_pct,
        "p80": p80,
        "r2": r2,
        "geh_lt5": geh_lt5,
        "err_med": median_rel_err,
        "ci_tol": ci_tol,
        "ci_p80": ci_p80,
        "ci_r2": ci_r2,
        "buckets": by_bucket,
        "err_lt15_n": err_lt15,
        "err_lt20_n": err_lt20,
        "train_seconds": train_seconds,
        "violated": violated,
        "has_report": has_report,
        "has_readme": has_readme,
        "has_model_zip": has_model_zip,
        "has_model_dir": has_model_dir,
    }
    return row


def collect_rows(batch_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sub in sorted(batch_dir.iterdir()):
        if not sub.is_dir():
            continue
        m = sub / "metrics.json"
        if not m.exists():
            continue
        data = _safe_load_json(m)
        if not data:
            continue
        try:
            rows.append(_row_for(data, sub))
        except Exception as exc:
            print(f"warn: failed to parse {m}: {exc}", file=sys.stderr)
    return rows


def collect_v1_rows(v1_dir: Path) -> list[dict[str, Any]]:
    """Same shape as collect_rows but used only for "vs v1" comparisons."""
    if not v1_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for sub in sorted(v1_dir.iterdir()):
        if not sub.is_dir():
            continue
        m = sub / "metrics.json"
        if not m.exists():
            continue
        data = _safe_load_json(m)
        if not data:
            continue
        try:
            rows.append(_row_for(data, sub))
        except Exception:
            continue
    return rows


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _best_by(rows: list[dict[str, Any]], key: str, lower_is_better: bool = False):
    """Return the row with the best (highest by default) value for `key`."""
    def keyfn(r):
        v = r.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return -math.inf if not lower_is_better else math.inf
        return v
    if not rows:
        return None
    rows_sorted = sorted(rows, key=keyfn, reverse=not lower_is_better)
    return rows_sorted[0]


def _mean(values: list[float]) -> float:
    clean = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
    if not clean:
        return float("nan")
    return statistics.mean(clean)


def _axis_effect(rows: list[dict[str, Any]], key: str, top_n: int = 3) -> list[dict[str, Any]]:
    """Compute mean tol_pct / p80 grouped by *key*."""
    by_group: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        v = r.get(key)
        bucket = "—" if v in (None, "", []) else (
            ",".join(v) if isinstance(v, list) else str(v)
        )
        by_group.setdefault(bucket, []).append(r)
    out = []
    for label, group in by_group.items():
        out.append({
            "label": label,
            "n": len(group),
            "tol_mean": _mean([g["tol_pct"] for g in group]),
            "p80_mean": _mean([g["p80"] for g in group]),
            "r2_mean": _mean([g["r2"] for g in group]),
        })
    out.sort(key=lambda x: (-x["tol_mean"] if not math.isnan(x["tol_mean"]) else math.inf))
    return out[:top_n]


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------

def _fmt_pct(v: float, n: int = 2) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    return f"{v:.{n}f}"


def _fmt_int(v: int) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}"


def _fmt_ci(ci: tuple[float, float] | None) -> str:
    if not ci or any(math.isnan(c) for c in ci):
        return "—"
    return f"[{ci[0]:.2f}, {ci[1]:.2f}]"


def _ci_overlaps(a: tuple[float, float] | None, b: tuple[float, float] | None) -> bool:
    if not a or not b:
        return True
    return not (a[1] < b[0] or b[1] < a[0])


def _bucket_cell(tol_pct: float) -> str:
    if math.isnan(tol_pct):
        return "<td class='bk'>—</td>"
    # Colour grade green when >= 70, yellow 50-70, red <50.
    cls = "bk bk-good" if tol_pct >= 70 else ("bk bk-mid" if tol_pct >= 50 else "bk bk-bad")
    return f"<td class='{cls}'>{tol_pct:.1f}</td>"


def _render_links(row: dict[str, Any]) -> str:
    folder = row["folder"]
    parts = []
    if row["has_report"]:
        parts.append(f"<a href='./{escape(folder)}/report.html' title='rapport HTML' target='_blank'>R</a>")
    if row["has_readme"]:
        parts.append(f"<a href='./{escape(folder)}/README.md' title='README' target='_blank'>D</a>")
    if row["has_model_zip"]:
        parts.append(f"<a href='./{escape(folder)}/model.zip' title='model.zip' target='_blank'>Z</a>")
    elif row["has_model_dir"]:
        parts.append(f"<a href='./{escape(folder)}/' title='model dir' target='_blank'>F</a>")
    return " ".join(parts) if parts else "—"


def _render_table_row(
    row: dict[str, Any],
    rank: int,
    best_tol: dict[str, Any] | None,
    second_tol: dict[str, Any] | None,
    best_p80: dict[str, Any] | None,
) -> str:
    # Highlight classes
    classes = ["data-row"]
    if best_tol and row["name"] == best_tol["name"]:
        classes.append("best-tol")
    if best_p80 and row["name"] == best_p80["name"]:
        classes.append("best-p80")
    if row.get("violated"):
        classes.append("violated")

    tol_bold = ""
    if best_tol and row["name"] == best_tol["name"] and second_tol:
        if not _ci_overlaps(row["ci_tol"], second_tol["ci_tol"]):
            tol_bold = " strong-best"

    fe_chips = " ".join(
        f"<span class='chip'>{escape(c)}</span>" for c in row["fe_chips"]
    ) or "—"

    # Bucket cells (always 4)
    bucket_lookup = {b["label"]: b for b in row["buckets"]}
    bucket_order = ["0-1k", "1k-5k", "5k-20k", "20k+"]
    bucket_cells_html = "".join(
        _bucket_cell(bucket_lookup.get(lbl, {}).get("tol_pct", float("nan")))
        for lbl in bucket_order
    )

    clip_str = "—" if row["clipnorm"] in (None, "") else str(row["clipnorm"])
    norm_str = row["norm_layer"] or ("batch" if row.get("use_batch_norm") else "—")
    skip_str = "yes" if row["use_skip"] else "—"
    qhead_str = "yes" if row["use_quantile_head"] else "—"
    tlog_str = "yes" if row["target_log_transform"] else "—"
    violated_str = "<span class='violated-tag'>YES</span>" if row["violated"] else "no"

    return (
        f"<tr class='{' '.join(classes)}'>"
        f"<td>{rank}</td>"
        f"<td class='name'><b>{escape(row['name'])}</b><br><span class='links'>{_render_links(row)}</span></td>"
        f"<td>{row['n_inputs']}</td>"
        f"<td>{row['ep_min']}</td>"
        f"<td>{_fmt_pct(row['drop'], 3)}</td>"
        f"<td>{escape(row['dropout_schedule'])}</td>"
        f"<td>{escape(row['optimizer'])}</td>"
        f"<td>{row['weight_decay']:.4g}</td>"
        f"<td>{clip_str}</td>"
        f"<td>{escape(norm_str)}</td>"
        f"<td>{skip_str}</td>"
        f"<td>{escape(row['loss'])}</td>"
        f"<td>{fe_chips}</td>"
        f"<td>{tlog_str}</td>"
        f"<td>{qhead_str}</td>"
        f"<td>{escape(row['weighting'])}</td>"
        f"<td>{escape(row['tricks'])}</td>"
        f"<td>{row['tta']}</td>"
        f"<td class='tol{tol_bold}' data-sort='{row['tol_pct'] if not math.isnan(row['tol_pct']) else -1}'>"
        f"  <b>{row['tol_in']}/{row['tol_total']}</b><br><span class='pct'>{_fmt_pct(row['tol_pct'], 2)}%</span>"
        f"</td>"
        f"<td>{_fmt_pct(row['p80'], 2)}</td>"
        f"<td>{_fmt_pct(row['r2'], 4)}</td>"
        f"<td>{_fmt_pct(row['geh_lt5'], 1)}</td>"
        f"<td>{_fmt_pct(row['err_med'], 2)}</td>"
        f"<td>{_fmt_ci(row['ci_tol'])}</td>"
        f"<td>{_fmt_ci(row['ci_p80'])}</td>"
        f"<td>{_fmt_ci(row['ci_r2'])}</td>"
        f"{bucket_cells_html}"
        f"<td>{_fmt_int(row['err_lt15_n'])}</td>"
        f"<td>{_fmt_int(row['err_lt20_n'])}</td>"
        f"<td>{_fmt_pct(row['train_seconds'], 0)}</td>"
        f"<td>{violated_str}</td>"
        f"</tr>"
    )


def _filter_options(rows: list[dict[str, Any]], key: str) -> list[str]:
    seen = set()
    for r in rows:
        v = r.get(key)
        if v in (None, ""):
            continue
        if isinstance(v, list):
            for x in v:
                seen.add(str(x))
        else:
            seen.add(str(v))
    return sorted(seen)


# ---------------------------------------------------------------------------
# Insights block
# ---------------------------------------------------------------------------

def _build_insights(
    rows: list[dict[str, Any]],
    v1_rows: list[dict[str, Any]],
    bugs: list[dict[str, str]],
) -> str:
    parts: list[str] = []

    parts.append("<h3>1. Effets par axe</h3>")
    for label, key in [
        ("Loss", "loss"),
        ("Weighting", "weighting"),
        ("Optimizer", "optimizer"),
        ("Norm layer", "norm_layer"),
        ("Dropout schedule", "dropout_schedule"),
        ("Feature engineering", "fe_chips"),
        ("Tricks", "tricks"),
        ("TTA", "tta"),
    ]:
        eff = _axis_effect(rows, key)
        rows_html = "".join(
            f"<tr><td>{escape(e['label'])}</td><td>{e['n']}</td>"
            f"<td>{_fmt_pct(e['tol_mean'], 2)}</td>"
            f"<td>{_fmt_pct(e['p80_mean'], 2)}</td>"
            f"<td>{_fmt_pct(e['r2_mean'], 4)}</td></tr>"
            for e in eff
        )
        parts.append(
            f"<details open><summary>{escape(label)}</summary>"
            f"<table class='insight'><tr><th>Valeur</th><th>n</th>"
            f"<th>tol%</th><th>p80%</th><th>R²</th></tr>{rows_html}</table>"
            f"</details>"
        )

    parts.append("<h3>2. Top 5 modèles (tol % puis p80)</h3>")
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            -(r["tol_pct"] if not math.isnan(r["tol_pct"]) else -1),
            r["p80"] if not math.isnan(r["p80"]) else math.inf,
        ),
    )
    head = "<table class='insight'><tr><th>#</th><th>Modèle</th><th>tol%</th><th>p80%</th><th>R²</th></tr>"
    parts.append(head + "".join(
        f"<tr><td>{i+1}</td><td>{escape(r['name'])}</td>"
        f"<td>{_fmt_pct(r['tol_pct'], 2)}</td>"
        f"<td>{_fmt_pct(r['p80'], 2)}</td>"
        f"<td>{_fmt_pct(r['r2'], 4)}</td></tr>"
        for i, r in enumerate(sorted_rows[:5])
    ) + "</table>")

    parts.append("<h3>3. Comparaison vs Batch v1 (Batch_MDL_GrandLyon_TV)</h3>")
    if v1_rows:
        best_v1 = _best_by(v1_rows, "tol_pct")
        best_v5 = _best_by(rows, "tol_pct")
        parts.append("<table class='insight'><tr><th>Référence</th><th>tol%</th>"
                     "<th>p80%</th><th>R²</th></tr>")
        if best_v1:
            parts.append(
                f"<tr><td>v1 best ({escape(best_v1['name'])})</td>"
                f"<td>{_fmt_pct(best_v1['tol_pct'], 2)}</td>"
                f"<td>{_fmt_pct(best_v1['p80'], 2)}</td>"
                f"<td>{_fmt_pct(best_v1['r2'], 4)}</td></tr>"
            )
        if best_v5:
            parts.append(
                f"<tr><td>v5 best ({escape(best_v5['name'])})</td>"
                f"<td>{_fmt_pct(best_v5['tol_pct'], 2)}</td>"
                f"<td>{_fmt_pct(best_v5['p80'], 2)}</td>"
                f"<td>{_fmt_pct(best_v5['r2'], 4)}</td></tr>"
            )
        parts.append("</table>")
        if best_v1 and best_v5:
            gain_tol = best_v5["tol_pct"] - best_v1["tol_pct"]
            gain_p80 = best_v1["p80"] - best_v5["p80"]
            parts.append(
                f"<p><b>Gain absolu vs v1</b> : Δtol = {gain_tol:+.2f} pts, "
                f"Δp80 = {gain_p80:+.2f} pts (lower-better on p80).</p>"
            )
    else:
        parts.append("<p>Pas de référence v1 trouvée.</p>")

    parts.append("<h3>4. Bugs détectés et patchés pendant le batch</h3>")
    parts.append("<table class='insight'><tr><th>#</th><th>Bug</th><th>Fichier</th></tr>")
    for i, b in enumerate(bugs, 1):
        parts.append(
            f"<tr><td>{i}</td><td>{escape(b['title'])}</td>"
            f"<td><code>{escape(b['file'])}</code></td></tr>"
        )
    parts.append("</table>")

    # Highlight the configs the brief flags as needing a re-run after
    # the patches — these rows in the table above carry the OLD (buggy)
    # behaviour. Identified by name pattern.
    parts.append("<h3>5. Configs concernées par les bugs (re-run recommandé)</h3>")
    affected_keywords = {
        "A1_*_tlog (Bug 1)": ["A1_mse_025_ep1000_tlog", "A1_huber_025_ep1000_tlog"],
        "A5 quantile head (Bug 4)": ["A5_QuantileHead"],
        "A5 kfold (Bug 3)": ["A5_kfold_k5"],
        "A6 AdamW/Skip (Bug 7 was the in-flight patch, but optimizer plumbing was P3)":
            ["A6_AdamW_skip_LN_permX2", "A6_AdamW_skip_LN_permX2_recX2",
             "A6_AdamW_skip_huber_permX3", "A6_AdamW_skip_permX2_nseeds3"],
        "A6 scaler/year_emb/FE (Bug 5/6/7)":
            ["A6_robustScaler_permX2", "A6_yearEmb_permX2",
             "A6_ratioPLTV_logTMJOFCDTV_permX2"],
        "A4 (all 14) — Bug 8 (flag_permanent=0)":
            [r["name"] for r in rows if r["agent"] == "A4"],
    }
    parts.append(
        "<p>Ces lignes carry the pre-patch behaviour and should be re-trained "
        "with the fixed worker / pipeline. The smoke test (smoke_phase05_patches.py) "
        "now exercises all 8 fixes.</p>"
    )
    parts.append("<ul>")
    for label, names in affected_keywords.items():
        if not names:
            continue
        items = ", ".join(escape(n) for n in names[:8])
        more = f" (+{len(names) - 8})" if len(names) > 8 else ""
        parts.append(f"<li><b>{escape(label)}</b>: {items}{more}</li>")
    parts.append("</ul>")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

BUGS = [
    {"title": "target_log_transform not forwarded to split_train_valid",
     "file": "apps/api/app/services/ml/training_pipeline.py:run_training"},
    {"title": "use_log_flow_weighting + log_flow_weighting_col not forwarded",
     "file": "apps/api/app/services/ml/training_pipeline.py:run_training"},
    {"title": "logger NameError on /api/evaluation/kfold per-fold path",
     "file": "apps/api/app/services/ml/training_pipeline.py:run_training"},
    {"title": "use_quantile_head not plumbed (grid axis + artifact echo + evaluate scalar)",
     "file": "apps/api/app/services/ml/training_pipeline.py:_train_single + grid"},
    {"title": "use_year_embedding inert — derive year_feature_idx + year_n_categories",
     "file": "apps/api/app/services/ml/training_pipeline.py:_train_single"},
    {"title": "scaler='robust' not forwarded to normalize()",
     "file": "apps/api/app/services/ml/training_pipeline.py:run_training"},
    {"title": "/api/evaluation/run doesn't replay feature_engineering on validation df",
     "file": "apps/api/app/services/ml/evaluation_pipeline.py + apps/api/app/routers/evaluation.py"},
    {"title": "Worker _preprocess_geojson — flag_permanent lookup ignored 'Type Compteur'",
     "file": ".playwright-mcp/Batch_MDL_Phase05/run_phase05_worker.py:_preprocess_geojson"},
]


def build_html(rows: list[dict[str, Any]], v1_rows: list[dict[str, Any]]) -> str:
    # Sort by tol desc, then p80 asc.
    rows.sort(
        key=lambda r: (
            -(r["tol_pct"] if not math.isnan(r["tol_pct"]) else -1),
            r["p80"] if not math.isnan(r["p80"]) else math.inf,
        )
    )

    best_tol = _best_by(rows, "tol_pct")
    sorted_by_tol = sorted(
        rows, key=lambda r: -(r["tol_pct"] if not math.isnan(r["tol_pct"]) else -1)
    )
    second_tol = sorted_by_tol[1] if len(sorted_by_tol) > 1 else None
    best_p80 = _best_by(rows, "p80", lower_is_better=True)
    best_r2 = _best_by(rows, "r2")

    # Cards
    total_models = len(rows)
    # v1 reference for the headline card
    v1_best_tol = _best_by(v1_rows, "tol_pct") if v1_rows else None
    if best_tol and v1_best_tol and not math.isnan(best_tol["tol_pct"]) \
            and not math.isnan(v1_best_tol["tol_pct"]):
        _delta = best_tol["tol_pct"] - v1_best_tol["tol_pct"]
        gain_tol_line = f"{_delta:+.2f} pts vs v1"
    elif not v1_rows:
        gain_tol_line = "no v1 reference"
    else:
        gain_tol_line = "—"

    cards_html = f"""
    <div class='cards'>
      <div class='card'><div class='lbl'>Modèles évalués</div>
        <div class='val'>{total_models}</div></div>
      <div class='card'><div class='lbl'>Best tolérance</div>
        <div class='val'>{_fmt_pct(best_tol['tol_pct'], 2) if best_tol else '—'}%</div>
        <div class='sub'>{escape(best_tol['name']) if best_tol else ''}</div></div>
      <div class='card'><div class='lbl'>Best p80</div>
        <div class='val'>{_fmt_pct(best_p80['p80'], 2) if best_p80 else '—'}%</div>
        <div class='sub'>{escape(best_p80['name']) if best_p80 else ''}</div></div>
      <div class='card'><div class='lbl'>Best R²</div>
        <div class='val'>{_fmt_pct(best_r2['r2'], 4) if best_r2 else '—'}</div>
        <div class='sub'>{escape(best_r2['name']) if best_r2 else ''}</div></div>
      <div class='card'><div class='lbl'>Gain vs v1</div>
        <div class='val'>{escape(gain_tol_line)}</div></div>
    </div>
    """

    # Filter dropdowns
    losses = _filter_options(rows, "loss")
    weightings = _filter_options(rows, "weighting")
    optimizers = _filter_options(rows, "optimizer")
    tricks_opts = _filter_options(rows, "tricks")
    tlog_opts = ["yes", "no"]
    nfeat_opts = sorted({str(r["n_inputs"]) for r in rows})

    def _opts(label_id: str, opts: list[str]) -> str:
        return "<option value=''>(tous)</option>" + "".join(
            f"<option value='{escape(o)}'>{escape(o)}</option>" for o in opts
        )

    filters_html = f"""
    <div class='filters'>
      <label>Inputs <select id='f-ninputs'>{_opts('ninputs', nfeat_opts)}</select></label>
      <label>Loss <select id='f-loss'>{_opts('loss', losses)}</select></label>
      <label>Optimizer <select id='f-optimizer'>{_opts('opt', optimizers)}</select></label>
      <label>Weighting <select id='f-weighting'>{_opts('weighting', weightings)}</select></label>
      <label>Tricks <select id='f-tricks'>{_opts('tricks', tricks_opts)}</select></label>
      <label>target_log_transform <select id='f-tlog'>{_opts('tlog', tlog_opts)}</select></label>
      <label class='reset'><button id='btn-reset' type='button'>Reset filtres</button></label>
    </div>
    """

    header = """
    <thead>
      <tr>
        <th>#</th><th>Modèle / liens</th><th>n_in</th><th>ep_min</th><th>drop</th>
        <th>drop_sched</th><th>opt</th><th>wd</th><th>clip</th><th>norm</th>
        <th>skip</th><th>loss</th><th>FE</th><th>tlog</th><th>qhead</th>
        <th>weighting</th><th>tricks</th><th>tta</th>
        <th>tol</th><th>p80%</th><th>R²</th><th>GEH&lt;5%</th><th>err_med%</th>
        <th>CI95 tol</th><th>CI95 p80</th><th>CI95 R²</th>
        <th>0-1k</th><th>1k-5k</th><th>5k-20k</th><th>20k+</th>
        <th>err&lt;15</th><th>err&lt;20</th><th>train_s</th><th>violated</th>
      </tr>
    </thead>
    """

    body = "\n".join(
        _render_table_row(r, i + 1, best_tol, second_tol, best_p80)
        for i, r in enumerate(rows)
    )

    insights = _build_insights(rows, v1_rows, BUGS)

    css = """
    :root {
      --bg: #fafafa; --fg: #1a1a1a; --muted: #6b6b6b;
      --accent: #2563eb; --good: #16a34a; --mid: #f59e0b; --bad: #dc2626;
      --border: #e5e7eb;
    }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: var(--bg); color: var(--fg); margin: 0; padding: 24px; }
    h1 { margin: 0 0 4px 0; font-size: 24px; }
    .subtitle { color: var(--muted); margin-bottom: 24px; font-size: 13px; }
    .cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
    .card { background: white; border: 1px solid var(--border); border-radius: 6px;
            padding: 14px 18px; min-width: 180px; }
    .card .lbl { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    .card .val { font-size: 22px; font-weight: 600; }
    .card .sub { font-size: 11px; color: var(--muted); margin-top: 4px;
                 max-width: 220px; overflow: hidden; text-overflow: ellipsis;
                 white-space: nowrap; }
    .filters { margin-bottom: 12px; background: white; padding: 10px;
               border: 1px solid var(--border); border-radius: 6px; }
    .filters label { margin-right: 14px; font-size: 12px; }
    .filters select { padding: 4px; font-size: 12px; margin-left: 4px; }
    .filters button { padding: 4px 10px; font-size: 12px; cursor: pointer; }
    table.dt { width: 100%; border-collapse: collapse; font-size: 11px;
               background: white; }
    table.dt th, table.dt td { border: 1px solid var(--border); padding: 4px 6px;
                                text-align: center; vertical-align: middle; }
    table.dt th { background: #f3f4f6; position: sticky; top: 0;
                  font-weight: 600; cursor: pointer; }
    table.dt td.name { text-align: left; max-width: 220px; word-break: break-word; }
    .data-row.best-tol { background: #ecfdf5; }
    .data-row.best-p80 { background: #fef3c7; }
    .data-row.violated { background: #fee2e2; }
    .data-row .tol { font-size: 11px; }
    .data-row .tol .pct { color: var(--muted); }
    .strong-best b { color: var(--good); }
    .chip { display: inline-block; background: #eef2ff; color: #4338ca;
            padding: 1px 5px; border-radius: 3px; font-size: 10px; margin: 1px; }
    .bk { font-size: 10px; }
    .bk-good { background: #ecfdf5; }
    .bk-mid  { background: #fffbeb; }
    .bk-bad  { background: #fee2e2; }
    .violated-tag { color: white; background: var(--bad); padding: 1px 6px;
                    border-radius: 3px; font-weight: 600; }
    .links a { display: inline-block; padding: 1px 5px; margin: 1px;
               background: var(--accent); color: white; border-radius: 3px;
               text-decoration: none; font-size: 10px; }
    .links a:hover { opacity: 0.8; }
    .insights { margin-top: 32px; background: white; padding: 16px 22px;
                border: 1px solid var(--border); border-radius: 6px; }
    .insights h3 { margin-top: 18px; }
    .insights details summary { cursor: pointer; font-weight: 600; padding: 6px 0; }
    .insights table.insight { border-collapse: collapse; font-size: 12px;
                              width: 100%; margin: 6px 0 14px 0; }
    .insights table.insight th, .insights table.insight td { border: 1px solid var(--border);
                                                              padding: 5px 8px; text-align: center; }
    .insights table.insight th { background: #f9fafb; }
    """

    js = r"""
    // Lightweight table sort + filter (no external CDN dependency to keep the
    // page usable offline). The table is already pre-sorted by tol desc / p80
    // asc on the server side, so click-to-sort starts from that order.
    (function() {
      const table = document.getElementById('models');
      if (!table) return;
      const tbody = table.querySelector('tbody');
      const headers = table.querySelectorAll('thead th');

      headers.forEach((th, idx) => {
        th.addEventListener('click', () => sortBy(idx));
      });

      function sortBy(colIdx) {
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const dir = table.dataset.sortCol == colIdx && table.dataset.sortDir == 'asc' ? 'desc' : 'asc';
        rows.sort((a, b) => {
          const av = cellSortValue(a.cells[colIdx]);
          const bv = cellSortValue(b.cells[colIdx]);
          if (av < bv) return dir == 'asc' ? -1 : 1;
          if (av > bv) return dir == 'asc' ? 1 : -1;
          return 0;
        });
        rows.forEach(r => tbody.appendChild(r));
        table.dataset.sortCol = colIdx;
        table.dataset.sortDir = dir;
      }

      function cellSortValue(td) {
        if (!td) return -Infinity;
        if (td.dataset.sort) return parseFloat(td.dataset.sort);
        const txt = td.textContent.trim();
        const num = parseFloat(txt.replace('%', '').replace(',', '.'));
        if (!isNaN(num)) return num;
        return txt.toLowerCase();
      }

      // Filters
      const filters = {
        'f-ninputs':   { col: 2 },
        'f-loss':      { col: 11 },
        'f-optimizer': { col: 6 },
        'f-weighting': { col: 15 },
        'f-tricks':    { col: 16 },
        'f-tlog':      { col: 13 },
      };

      function applyFilters() {
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(r => {
          let show = true;
          for (const [id, info] of Object.entries(filters)) {
            const sel = document.getElementById(id);
            if (!sel || sel.value === '') continue;
            const cellTxt = r.cells[info.col].textContent.trim();
            if (!cellTxt.toLowerCase().includes(sel.value.toLowerCase())) {
              show = false; break;
            }
          }
          r.style.display = show ? '' : 'none';
        });
      }
      Object.keys(filters).forEach(id => {
        const sel = document.getElementById(id);
        if (sel) sel.addEventListener('change', applyFilters);
      });
      const reset = document.getElementById('btn-reset');
      if (reset) reset.addEventListener('click', () => {
        Object.keys(filters).forEach(id => {
          const sel = document.getElementById(id);
          if (sel) sel.value = '';
        });
        applyFilters();
      });
    })();
    """

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <title>MDL Redressement — Batch Phase 05 — Index</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>{css}</style>
</head>
<body>
  <h1>Batch MDL Phase 05 — Index aggregated</h1>
  <div class="subtitle">
    Généré {escape(now)} · {total_models} modèles ·
    sortable par colonne · filtres en haut · highlight = best tol (vert) /
    best p80 (jaune) / contraintes-vitesses violées (rouge)
  </div>
  {cards_html}
  {filters_html}
  <table id="models" class="dt" data-sort-col="18" data-sort-dir="desc">
    {header}
    <tbody>
      {body}
    </tbody>
  </table>
  <div class="insights">
    <h2>Insights</h2>
    {insights}
  </div>
  <script>{js}</script>
</body>
</html>
"""
    return html


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(DEFAULT_OUT))
    args = p.parse_args(argv)

    print(f"Reading metrics from {BATCH_DIR} ...", file=sys.stderr)
    rows = collect_rows(BATCH_DIR)
    print(f"  -> {len(rows)} rows", file=sys.stderr)

    v1_rows = collect_v1_rows(V1_DIR)
    print(f"v1 reference: {len(v1_rows)} rows from {V1_DIR}", file=sys.stderr)

    html = build_html(rows, v1_rows)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({out_path.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
