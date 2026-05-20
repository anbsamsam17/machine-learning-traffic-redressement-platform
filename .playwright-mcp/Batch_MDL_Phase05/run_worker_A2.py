"""Worker A2 Phase 0-5 — feature-engineering ablation (12 configs).

Baseline: mse, drp=0.025, ep=1000, no weighting, neurons_factors=[3,2,1],
lr=0.01, batch=256, elu, test_size=0.05.

For each config we override the input_cols set (already pre-computed in
A2_TV_features.geojson). on_off_norm is computed dynamically based on
column type:
  - categorical / discrete / already-normalised : NOT z-scored
  - everything else                             : z-scored (standard)

Configs marked ``robust_scaled`` use ``rs_*`` columns where the values are
already RobustScaler-encoded (median/IQR/1.349), so we set on_off_norm=False
for those — the in-pipeline normalize() would otherwise re-scale them as
standard z-scores and undo the robust scaling we want to measure.
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
DATASET_PATH = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05/A2_TV_features.geojson"
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05"

EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"

# Columns that must NOT be z-scored (raw integer / one-hot / categorical).
# Anything not in this set defaults to z-scored = True UNLESS it starts with
# ``rs_`` (already RobustScaler-encoded — we want to keep those raw).
NO_NORM_RAW = {
    "year_mapped",
    "functional_class",
    "flag_permanent",
    "flag_recent_year",
    "fc_1", "fc_2", "fc_3", "fc_4", "fc_5",
    # yemb* are bounded sinusoidal in [-1, 1] — leaving them un-normalised
    # keeps the year-embedding emulation faithful.
    "yemb1", "yemb2", "yemb3",
    # log_* columns are already on log-scale — z-scoring them is the most
    # common practice (PyTorch / sklearn defaults), so DO keep on_off_norm=True
    # for them. (No entry here.)
}

# Extra cols we pass through validate so derived features land in learning_df.
EXTRA_COLS = [
    "flag_permanent", "flag_recent_year", "year_mapped",
    "ratio_PLTV", "log_TMJOFCDTV", "log_TMJOFCDPL",
    "fc_1", "fc_2", "fc_3", "fc_4", "fc_5",
    "rs_TMJOFCDTV", "rs_TMJOFCDPL",
    "rs_avg_distance_before_m", "rs_avg_distance_after_m",
    "rs_avg_min_distance_m", "rs_truck_avg_distance_m",
    "rs_truck_avg_distance_before_m", "rs_truck_avg_distance_after_m",
    "rs_truck_avg_min_distance_m",
    "yemb1", "yemb2", "yemb3",
    "Type Compteur", "Annee",
]


def _api(port: int, path: str) -> str:
    return f"http://127.0.0.1:{port}{path}"


def _on_off_for(cols: list[str], robust_scaled: bool) -> list[bool]:
    out: list[bool] = []
    for c in cols:
        if c in NO_NORM_RAW:
            out.append(False)
        elif c.startswith("rs_"):
            # RobustScaler-encoded — leave as-is.
            out.append(False)
        else:
            out.append(True)
    return out


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
    val_resp = r.json()
    print(f"[setup] mapping validated rows={val_resp['rows']} cols={len(val_resp['columns'])}", flush=True)

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


def build_training_body(cfg_entry: dict, sid: str, server_short_dir: str) -> tuple[dict, str]:
    inputs = cfg_entry["input_cols"]
    robust = bool(cfg_entry.get("robust_scaled", False))
    on_off = _on_off_for(inputs, robust)
    body = {
        "session_id": sid,
        "output_dir": server_short_dir,
        "model_type": "TV",
        "input_cols": inputs,
        "output_cols": ["TxPen"],
        "on_off_norm": on_off,
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
        "mandatory_input_cols": [],
        "min_input_count": 0,
        "feature_subset_grid": False,
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
        "use_flag_permanent_weighting": False,
        "use_flag_recent_year_weighting": False,
        "use_flag_comptage_weighting": False,
        "target_log_transform": False,
    }
    return body, cfg_entry["name"]


def run_one(port: int, token: str, sid: str, cfg_entry: dict, bootstrap_iter: int = 1000) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    run_name = cfg_entry["name"]
    short = hashlib.md5(run_name.encode()).hexdigest()[:8]
    server_short_dir = f"a2_{short}"
    body, _ = build_training_body(cfg_entry, sid, server_short_dir)

    n_inp = len(cfg_entry["input_cols"])
    print(
        f"[{run_name}] start train n_inputs={n_inp} robust={cfg_entry.get('robust_scaled', False)}",
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
    timeout_s = 3600
    last_heartbeat = 0.0
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
        if elapsed - last_heartbeat > 60:
            last_heartbeat = elapsed
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

    # Locate produced model subdir
    server_models = Path(model_dir_server)
    sub_dirs = [p for p in server_models.iterdir() if p.is_dir()] if server_models.exists() else []
    if not sub_dirs:
        return {"run_name": run_name, "error": f"no model at {server_models}"}
    actual = sub_dirs[0].name

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
        return {"run_name": run_name, "error": f"eval failed {r.status_code}: {r.text[:400]}"}
    eval_resp = r.json()
    metrics = eval_resp["metrics"]
    metrics_ci95 = eval_resp.get("metrics_ci95")
    metrics_by_bucket = eval_resp.get("metrics_by_tmja_bucket") or []

    # Report
    r = requests.get(
        _api(port, f"/api/evaluation/report/{sid}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=180,
    )
    if r.status_code != 200:
        return {"run_name": run_name, "error": f"report failed {r.status_code}: {r.text[:400]}"}
    html = r.json()["report_html"]

    # Parse the headline tiles. Tile structure is
    #   <div class="k">Capteurs tolerance inclus</div>
    #   <div class="v">1928/3632 <small ...>(53.08%)</small> ...</div>
    # so we match the leading "N/M" up to the first whitespace/tag char.
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)',
        html,
    )
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([0-9.+\-eE]+)\s*%',
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
        "description": cfg_entry.get("description", ""),
        "input_cols": cfg_entry["input_cols"],
        "n_inputs": n_inp,
        "on_off_norm": _on_off_for(cfg_entry["input_cols"], cfg_entry.get("robust_scaled", False)),
        "robust_scaled": bool(cfg_entry.get("robust_scaled", False)),
        "neurons_factors": [3.0, 2.0, 1.0],
        "dropout": 0.025,
        "min_epochs": 1000,
        "max_epochs": 1250,
        "batch_size": 256,
        "learning_rate": 0.01,
        "activation": "elu",
        "loss": "mse",
        "test_size": 0.05,
        "use_batch_norm": False,
        "target_log_transform": False,
        "use_flag_permanent_weighting": False,
        "use_flag_recent_year_weighting": False,
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
    inputs = cfg_entry["input_cols"]
    on_off = summary["on_off_norm"]
    m = summary["metrics"]
    lines: list[str] = []
    lines.append(f"# {summary['run_name']}")
    lines.append("")
    lines.append(f"_Feature-engineering ablation A2 — {cfg_entry.get('description', '')}_")
    lines.append("")
    lines.append(f"Dataset: `{DATASET_PATH.name}` (Grand Lyon, 3632 capteurs, 2019-2025)")
    lines.append(f"Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)")
    lines.append("")
    lines.append("## Tables")
    lines.append(f"- Apprentissage : `{DATASET_PATH}`")
    lines.append(f"- Validation   : `{DATASET_PATH}` (in-sample)")
    lines.append("")
    lines.append(f"## Entrees ({len(inputs)} features)")
    lines.append("| Feature | Normalise | Type |")
    lines.append("|---|---|---|")
    for col, norm in zip(inputs, on_off):
        if col == "year_mapped":
            t = "Annee 2019..2025 -> 1..7"
        elif col == "functional_class":
            t = "categoriel int 1-5"
        elif col.startswith("fc_"):
            t = "one-hot functional_class"
        elif col.startswith("rs_"):
            t = "RobustScaler pre-encode (median/IQR/1.349)"
        elif col.startswith("log_"):
            t = "log1p(col)"
        elif col == "ratio_PLTV":
            t = "TMJOFCDPL / max(TMJOFCDTV, 1)"
        elif col.startswith("yemb"):
            t = "year-embedding sinusoidal (dim=3 emulation)"
        else:
            t = "numerique continu"
        nstr = "OUI (z-score)" if norm else "NON"
        lines.append(f"| {col} | {nstr} | {t} |")
    lines.append("")
    lines.append("## Hyperparametres")
    lines.append(f"- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`")
    lines.append(f"- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`")
    lines.append(f"- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`")
    lines.append(f"- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`")
    lines.append(f"- robust_scaled: `{cfg_entry.get('robust_scaled', False)}`")
    lines.append("")
    lines.append("## Sample weighting")
    lines.append("- INACTIF (poids = 1 partout, pas de flag_permanent / flag_recent_year)")
    lines.append("")
    lines.append("## Metriques validation")
    tol_pct = 100 * summary["tol_inclus"] / max(summary["tol_total"], 1)
    lines.append(f"- Capteurs tolerance inclus: **{summary['tol_inclus']}/{summary['tol_total']}** ({tol_pct:.1f}%)")
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
    p.add_argument("--port", type=int, default=7002)
    p.add_argument("--configs", default=str(BATCH_DIR / "configs_A2.json"))
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--only", type=int, default=None, help="run only one config id (1-12)")
    args = p.parse_args()

    cfgs = json.loads(Path(args.configs).read_text(encoding="utf-8"))
    if args.only is not None:
        cfgs = [c for c in cfgs if c["id"] == args.only]

    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[A2] starting batch of {len(cfgs)} configs on port {args.port}", flush=True)
    wall_t0 = time.time()
    token, sid = setup_session(args.port)
    print(f"[A2] session ready sid={sid}", flush=True)

    runs: list[dict[str, Any]] = []
    for cfg in cfgs:
        try:
            runs.append(run_one(args.port, token, sid, cfg, args.bootstrap))
        except Exception as exc:
            print(f"[{cfg.get('name')}] EXCEPTION: {exc}", flush=True)
            traceback.print_exc()
            runs.append({"run_name": cfg.get("name"), "error": str(exc)})
        # Persist incremental progress so a crash doesn't lose results.
        (BATCH_DIR / "_summary_A2.json").write_text(
            json.dumps(
                {"wall_clock_seconds": round(time.time() - wall_t0, 1), "n_runs": len(runs), "runs": runs},
                indent=2,
            ),
            encoding="utf-8",
        )

    wall_elapsed = time.time() - wall_t0
    print(
        f"[A2] DONE n_runs={len(runs)} wall={wall_elapsed:.0f}s ({wall_elapsed/60:.1f}min)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
