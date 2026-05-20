"""Post-process A2 runs to correct metrics that were attached to the wrong
server-side model (worker bug: picked sub_dirs[0] which is alphabetical-first,
not the model just trained).

Fix strategy:
  1. For each config in configs_A2.json, walk the server workspace
     ``tmp_workdir/<sid>/models/`` and pick the model whose
     ``training_config.json`` lists exactly the same ``input_cols`` (and
     ``on_off_norm``) as the config.
  2. If found, re-run /api/evaluation/run against that model and rewrite
     metrics.json + README.md + report.html.
  3. If the right model is missing from the server (e.g. configs #1/#2
     whose 12-fmask model was overwritten by config #4), keep the
     existing batch-dir model copy and re-run eval against it instead —
     the batch copy was taken right after training so it is still
     correct in those cases.

A `_fix_log.txt` summarises every action.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
BATCH = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05"
WORKSPACE = PROJECT_ROOT / "tmp_workdir"
CONFIGS = json.loads((BATCH / "configs_A2.json").read_text(encoding="utf-8"))

EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"
PORT = 7002

YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4, "2023": 5, "2024": 6, "2025": 7}


def _api(path: str) -> str:
    return f"http://127.0.0.1:{PORT}{path}"


def _login_and_session() -> tuple[str, str]:
    r = requests.post(_api("/api/auth/login"), json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]

    # Recreate a session by uploading the validation file (same one) + mapping
    headers = {"Authorization": f"Bearer {token}"}
    dataset = BATCH / "A2_TV_features.geojson"
    with open(dataset, "rb") as f:
        r = requests.post(_api("/api/upload"), files={"file": (dataset.name, f)}, data={"mode": "tv"}, headers=headers, timeout=300)
    r.raise_for_status()
    sid = r.json()["session_id"]

    r = requests.post(_api("/api/mapping/auto"), json={"session_id": sid}, headers={**headers, "Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}

    extras = [
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
    r = requests.put(_api("/api/mapping/validate"),
        json={"session_id": sid, "mapping": mapping, "territory": "default", "extra_cols": extras},
        headers={**headers, "Content-Type": "application/json"}, timeout=120)
    r.raise_for_status()

    with open(dataset, "rb") as f:
        r = requests.post(_api("/api/evaluation/upload-validation"),
            files={"file": (dataset.name, f)}, data={"session_id": sid, "column_mapping": "{}"},
            headers=headers, timeout=300)
    r.raise_for_status()
    return token, sid


def _find_correct_model_dir(cfg: dict, worker_sid: str) -> tuple[Path, str] | None:
    """Look in worker_sid's server models dir for a model whose
    training_config.input_cols matches cfg['input_cols'] exactly.
    Returns (parent_dir, model_name) on success; None if absent."""
    server = WORKSPACE / worker_sid / "models"
    if not server.exists():
        return None
    target = list(cfg["input_cols"])
    for sub in server.iterdir():
        if not sub.is_dir():
            continue
        tc = sub / "training_config.json"
        if not tc.exists():
            continue
        try:
            d = json.loads(tc.read_text(encoding="utf-8"))
        except Exception:
            continue
        if list(d.get("input_cols", [])) == target:
            return server, sub.name
    return None


def _find_batch_model_if_correct(cfg: dict) -> tuple[Path, str] | None:
    """If the batch-dir model copy already matches cfg.input_cols, use it."""
    bdir = BATCH / cfg["name"] / "model"
    tc = bdir / "training_config.json"
    if not tc.exists():
        return None
    try:
        d = json.loads(tc.read_text(encoding="utf-8"))
    except Exception:
        return None
    if list(d.get("input_cols", [])) == list(cfg["input_cols"]):
        return BATCH / cfg["name"], "model"
    return None


def _rerun_eval(token: str, sid: str, model_dir: Path, model_name: str, bootstrap: int = 1000) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {
        "session_id": sid,
        "model_name": model_name,
        "model_dir": str(model_dir),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    r = requests.post(_api(f"/api/evaluation/run?bootstrap_iter={bootstrap}"), json=body, headers=headers, timeout=900)
    r.raise_for_status()
    eval_resp = r.json()

    r = requests.get(_api(f"/api/evaluation/report/{sid}"), headers={"Authorization": f"Bearer {token}"}, timeout=180)
    r.raise_for_status()
    html = r.json()["report_html"]

    m_inclus = re.search(r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)', html)
    m_p80 = re.search(r'Err\. rel\. p80</div>\s*<div class="v">\s*([0-9.+\-eE]+)\s*%', html)
    tol_in = int(m_inclus.group(1)) if m_inclus else 0
    tol_total = int(m_inclus.group(2)) if m_inclus else 0
    p80_val = float(m_p80.group(1)) if m_p80 else float("nan")
    barplot_broken = "Aucune donnee disponible" in html
    return {
        "metrics": eval_resp["metrics"],
        "metrics_ci95": eval_resp.get("metrics_ci95"),
        "metrics_by_tmja_bucket": eval_resp.get("metrics_by_tmja_bucket") or [],
        "tol_inclus": tol_in,
        "tol_total": tol_total,
        "err_p80_pct": p80_val,
        "barplot_broken": barplot_broken,
        "report_html": html,
    }


def _write_outputs(cfg: dict, eval_result: dict, train_seconds: float | None) -> None:
    target = BATCH / cfg["name"]
    target.mkdir(parents=True, exist_ok=True)
    html = eval_result["report_html"]
    (target / "report.html").write_text(html, encoding="utf-8")

    broken_reasons: list[str] = []
    if eval_result["tol_total"] == 0:
        broken_reasons.append("tol_total==0")
    if eval_result["err_p80_pct"] != eval_result["err_p80_pct"]:
        broken_reasons.append("p80=NaN")
    if eval_result["barplot_broken"]:
        broken_reasons.append("barplot_broken")
    ci = eval_result.get("metrics_ci95") or {}
    if ci.get("tol_in_pct"):
        lo, hi = ci["tol_in_pct"]
        width = hi - lo
        mean_tol = (lo + hi) / 2
        if mean_tol > 0 and width / mean_tol > 0.5:
            broken_reasons.append(f"CI95_width_too_large({width:.1f}/{mean_tol:.1f})")

    # Build on/off norm same way the worker did so the README is consistent.
    no_norm_raw = {
        "year_mapped", "functional_class", "flag_permanent", "flag_recent_year",
        "fc_1", "fc_2", "fc_3", "fc_4", "fc_5", "yemb1", "yemb2", "yemb3",
    }
    on_off = [
        False if c in no_norm_raw or c.startswith("rs_") else True
        for c in cfg["input_cols"]
    ]

    summary = {
        "run_name": cfg["name"],
        "description": cfg.get("description", ""),
        "input_cols": cfg["input_cols"],
        "n_inputs": len(cfg["input_cols"]),
        "on_off_norm": on_off,
        "robust_scaled": bool(cfg.get("robust_scaled", False)),
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
        "metrics": eval_result["metrics"],
        "metrics_ci95": eval_result["metrics_ci95"],
        "metrics_by_tmja_bucket": eval_result["metrics_by_tmja_bucket"],
        "tol_inclus": eval_result["tol_inclus"],
        "tol_total": eval_result["tol_total"],
        "err_p80_pct": eval_result["err_p80_pct"],
        "barplot_broken": eval_result["barplot_broken"],
        "broken": bool(broken_reasons),
        "broken_reasons": broken_reasons,
        "train_seconds": train_seconds,
    }
    (target / "metrics.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # README
    m = eval_result["metrics"]
    lines: list[str] = []
    lines.append(f"# {cfg['name']}")
    lines.append("")
    lines.append(f"_Feature-engineering ablation A2 — {cfg.get('description', '')}_")
    lines.append("")
    lines.append(f"Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)")
    lines.append(f"Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)")
    lines.append("")
    lines.append(f"## Entrees ({len(cfg['input_cols'])} features)")
    lines.append("| Feature | Normalise |")
    lines.append("|---|---|")
    for col, norm in zip(cfg["input_cols"], on_off):
        lines.append(f"| {col} | {'OUI (z-score)' if norm else 'NON'} |")
    lines.append("")
    lines.append("## Hyperparametres")
    lines.append("- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`")
    lines.append("- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`")
    lines.append("- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`")
    lines.append("- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`")
    lines.append(f"- robust_scaled: `{cfg.get('robust_scaled', False)}`")
    lines.append("")
    lines.append("## Sample weighting")
    lines.append("- INACTIF (poids = 1 partout)")
    lines.append("")
    lines.append("## Metriques validation")
    tol_pct = 100 * summary["tol_inclus"] / max(summary["tol_total"], 1)
    lines.append(f"- Capteurs tolerance inclus: **{summary['tol_inclus']}/{summary['tol_total']}** ({tol_pct:.1f}%)")
    lines.append(f"- Erreur relative p80: **{summary['err_p80_pct']}%**")
    lines.append(f"- Erreur relative mediane: {m.get('median_relative_error')}%")
    r2v = m.get('r_squared')
    if isinstance(r2v, (int, float)):
        lines.append(f"- R2: {r2v:.4f}")
    lines.append(f"- RMSE: {m.get('rmse')}  |  MAE: {m.get('mae')}")
    lines.append(f"- GEH < 5: {m.get('geh_pct_below_5')}%")
    lines.append(f"- N validation: {m.get('n_samples')}")
    if ci:
        lines.append("")
        lines.append("## CI95 (bootstrap 1000 iter)")
        for k in ("tol_in_pct", "p80", "r2"):
            if ci.get(k):
                lines.append(f"- {k}: [{ci[k][0]}, {ci[k][1]}]")
    if train_seconds is not None:
        lines.append("")
        lines.append(f"- Train: {train_seconds}s")
    if broken_reasons:
        lines.append("")
        lines.append(f"### Quality gates failed: {', '.join(broken_reasons)}")
    (target / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    # Parse worker session id straight from the worker log so we look at
    # *our* training output and not another agent's workspace.
    worker_log = BATCH / "worker_A2.log"
    worker_sid = None
    if worker_log.exists():
        m = re.search(r"session_id=([0-9a-f]+)", worker_log.read_text(encoding="utf-8"))
        if m:
            worker_sid = m.group(1)
    if not worker_sid:
        # Fallback: pick the session whose models[].input_cols overlap the
        # most with our expected configs (last-resort heuristic).
        best = (0, None)
        for sid_dir in WORKSPACE.iterdir():
            models = sid_dir / "models"
            if not models.exists():
                continue
            hits = 0
            for sub in models.iterdir():
                tc = sub / "training_config.json"
                if not tc.exists():
                    continue
                try:
                    d = json.loads(tc.read_text(encoding="utf-8"))
                    ic = list(d.get("input_cols", []))
                    if any(ic == list(c["input_cols"]) for c in CONFIGS):
                        hits += 1
                except Exception:
                    pass
            if hits > best[0]:
                best = (hits, sid_dir.name)
        worker_sid = best[1]
    if not worker_sid:
        print("Could not identify worker session.")
        return
    server_models = WORKSPACE / worker_sid / "models"
    n_models = sum(1 for _ in server_models.iterdir() if _.is_dir()) if server_models.exists() else 0
    print(f"Using worker session sid={worker_sid} ({n_models} models on disk)")

    # New eval session for the fix-up
    token, sid = _login_and_session()
    print(f"Fix session: sid={sid}")

    log_lines: list[str] = []

    for cfg in CONFIGS:
        name = cfg["name"]
        # 1. Check if batch-dir model already matches.
        batch_match = _find_batch_model_if_correct(cfg)
        # 2. Else look in worker server dir.
        server_match = _find_correct_model_dir(cfg, worker_sid)

        if batch_match:
            mdir, mname = batch_match
            source = "batch"
        elif server_match:
            mdir, mname = server_match
            source = "server"
        else:
            log_lines.append(f"[{name}] SKIP — no matching model found in batch or server.")
            print(log_lines[-1])
            continue

        # Existing batch metrics — keep train_seconds if available.
        existing_metrics = BATCH / name / "metrics.json"
        train_seconds = None
        if existing_metrics.exists():
            try:
                d = json.loads(existing_metrics.read_text(encoding="utf-8"))
                train_seconds = d.get("train_seconds")
            except Exception:
                pass

        try:
            print(f"[{name}] eval via {source}: dir={mdir} name={mname}")
            ev = _rerun_eval(token, sid, mdir, mname, bootstrap=1000)
        except Exception as exc:
            log_lines.append(f"[{name}] EVAL FAILED: {exc}")
            print(log_lines[-1])
            continue

        # If we used the server copy, refresh the batch dir model with the right one.
        if source == "server":
            dst = BATCH / name / "model"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(Path(mdir) / mname, dst)

        _write_outputs(cfg, ev, train_seconds)
        log_lines.append(
            f"[{name}] OK source={source} tol={ev['tol_inclus']}/{ev['tol_total']} "
            f"p80={ev['err_p80_pct']} R2={ev['metrics'].get('r_squared')}"
        )
        print(log_lines[-1])

    (BATCH / "_fix_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
    print(f"Wrote {BATCH / '_fix_log.txt'}")


if __name__ == "__main__":
    sys.exit(main())
