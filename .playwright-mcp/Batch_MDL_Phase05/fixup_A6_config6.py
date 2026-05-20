"""Re-evaluate A6 config 6 with a validation file augmented with ratio_PLTV
and log_TMJOFCDTV columns.

Config 6's eval failed because the validation_df doesn't carry the derived
features that data_prep.py creates at training time. Workaround: upload a
pre-augmented validation file in a fresh session so /api/evaluation/run
finds ratio_PLTV / log_TMJOFCDTV directly.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PORT = 7006
PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
DATASET_PATH = (
    PROJECT_ROOT
    / ".playwright-mcp/DataApprentissage/GrandLyon/BCFCDREF_AllYears_TV.geojson"
)
BATCH_DIR = PROJECT_ROOT / ".playwright-mcp/Batch_MDL_Phase05"
RUN_NAME = "A6_ratioPLTV_logTMJOFCDTV_permX2"
EMAIL = "samir.anbri@gmail.com"
PASSWORD = "TestPass123!"
YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4, "2023": 5, "2024": 6, "2025": 7}


def _api(path: str) -> str:
    return f"http://localhost:{PORT}{path}"


def _augment_geojson(raw_path: Path) -> Path:
    """Read the source GeoJSON, add ratio_PLTV and log_TMJOFCDTV per feature,
    write a new GeoJSON to a tmp path, return that path."""
    data = json.loads(raw_path.read_text(encoding="utf-8"))
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        try:
            tv = float(props.get("TMJOFCDTV") or 0)
        except (TypeError, ValueError):
            tv = 0.0
        try:
            pl = float(props.get("TMJOFCDPL") or 0)
        except (TypeError, ValueError):
            pl = 0.0
        denom = tv if tv >= 1.0 else 1.0
        props["ratio_PLTV"] = float(pl) / float(denom)
        props["log_TMJOFCDTV"] = float(np.log1p(max(tv, 0.0)))
        feat["properties"] = props
    out = raw_path.with_suffix(".augmented.geojson")
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def main() -> int:
    target = BATCH_DIR / RUN_NAME
    metrics_path = target / "metrics.json"
    if not metrics_path.exists():
        print(f"[fixup] metrics.json missing at {metrics_path}", flush=True)
        return 1
    summary = json.loads(metrics_path.read_text(encoding="utf-8"))

    # Locate the model — prefer backup dir if present.
    backup = summary.get("server_backup_dir")
    smodels = Path(backup) if backup else Path(summary["server_model_dir"])
    if not smodels.exists():
        smodels = Path(summary["server_model_dir"])
    if not smodels.exists():
        print(f"[fixup] no server model dir at {smodels}", flush=True)
        return 2
    produced = summary.get("produced_model_names") or []
    sub_dirs = [smodels / n for n in produced if (smodels / n).is_dir()]
    if not sub_dirs:
        sub_dirs = [p for p in smodels.iterdir() if p.is_dir()]
    if not sub_dirs:
        print(f"[fixup] no model subdir under {smodels}", flush=True)
        return 3
    actual = sub_dirs[0].name

    # Login
    r = requests.post(_api("/api/auth/login"),
                      json={"email": EMAIL, "password": PASSWORD}, timeout=30)
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # New session: upload + map + validate (so /api/evaluation/run has a session_id)
    with open(DATASET_PATH, "rb") as f:
        r = requests.post(_api("/api/upload"),
                          files={"file": (DATASET_PATH.name, f)},
                          data={"mode": "tv"}, headers=headers, timeout=300)
    r.raise_for_status()
    sid = r.json()["session_id"]
    print(f"[fixup] sid={sid}", flush=True)

    r = requests.post(_api("/api/mapping/auto"),
                      json={"session_id": sid},
                      headers={**headers, "Content-Type": "application/json"},
                      timeout=60)
    r.raise_for_status()
    mapping = {m["target"]: m["source"] for m in r.json()["mappings"]}
    r = requests.put(_api("/api/mapping/validate"),
                     json={"session_id": sid, "mapping": mapping,
                           "territory": "default",
                           "extra_cols": ["flag_permanent", "flag_recent_year",
                                          "year_mapped", "Type Compteur", "Annee"]},
                     headers={**headers, "Content-Type": "application/json"},
                     timeout=120)
    r.raise_for_status()

    # Build augmented validation file
    augmented = _augment_geojson(DATASET_PATH)
    print(f"[fixup] augmented geojson written to {augmented}", flush=True)

    with open(augmented, "rb") as f:
        r = requests.post(_api("/api/evaluation/upload-validation"),
                          files={"file": (augmented.name, f)},
                          data={"session_id": sid, "column_mapping": "{}"},
                          headers=headers, timeout=300)
    r.raise_for_status()
    print(f"[fixup] augmented validation uploaded", flush=True)

    # Run eval (bootstrap 1000)
    eval_body = {
        "session_id": sid,
        "model_name": actual,
        "model_dir": str(smodels),
        "year_column_name": "Annee",
        "year_value_mapping": YEAR_MAPPING,
    }
    print(f"[fixup] eval model={actual} dir={smodels}", flush=True)
    r = requests.post(
        _api("/api/evaluation/run?bootstrap_iter=1000"),
        json=eval_body, headers={**headers, "Content-Type": "application/json"},
        timeout=900,
    )
    if r.status_code != 200:
        print(f"[fixup] eval failed {r.status_code}: {r.text[:400]}", flush=True)
        return 4
    eval_resp = r.json()
    metrics = eval_resp["metrics"]
    metrics_ci95 = eval_resp.get("metrics_ci95")

    # Fetch new report HTML
    r = requests.get(_api(f"/api/evaluation/report/{sid}"), headers=headers, timeout=180)
    r.raise_for_status()
    html = r.json()["report_html"]
    (target / "report.html").write_text(html, encoding="utf-8")

    # Parse tol/p80 from the fresh HTML
    m_inclus = re.search(
        r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)',
        html,
    )
    m_p80 = re.search(
        r'Err\. rel\. p80</div>\s*<div class="v">\s*([\-\d.]+)\s*%?', html,
    )
    if m_inclus:
        tol_in = int(m_inclus.group(1))
        tol_total = int(m_inclus.group(2))
    else:
        tol_in, tol_total = 0, 0
    try:
        p80 = float(m_p80.group(1)) if m_p80 else float("nan")
    except ValueError:
        p80 = float("nan")
    barplot_broken = "Aucune donnee disponible" in html

    summary["metrics"] = metrics
    summary["metrics_ci95"] = metrics_ci95
    summary["tol_inclus"] = tol_in
    summary["tol_total"] = tol_total
    summary["err_p80_pct"] = p80
    summary["barplot_broken"] = barplot_broken
    broken_reasons = []
    if tol_total == 0:
        broken_reasons.append("tol_total==0")
    if p80 != p80:
        broken_reasons.append("p80=NaN")
    if barplot_broken:
        broken_reasons.append("barplot_broken")
    summary["broken"] = bool(broken_reasons)
    summary["broken_reasons"] = broken_reasons
    summary["fixup_note"] = (
        "Validation file was augmented with ratio_PLTV + log_TMJOFCDTV "
        "before /api/evaluation/run because the evaluation router doesn't "
        "yet derive feature-engineered columns at inference time."
    )
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(
        f"[fixup] DONE tol={tol_in}/{tol_total} p80={p80} "
        f"R2={metrics.get('r_squared')} broken={broken_reasons}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
