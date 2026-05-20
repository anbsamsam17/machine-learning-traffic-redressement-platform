"""Re-evaluate the first 4 A3 configs against their CORRECT server-side
models. The original worker used sub_dirs[0] (alphabetical first) which
caused every run after A3_AdamW_wd4 to be evaluated against the wrong
model — explains the byte-identical R²=0.665 across architectures.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import requests

PROJECT_ROOT = Path(
    r"C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio"
)
BATCH = PROJECT_ROOT / ".playwright-mcp" / "Batch_MDL_Phase05"
SESSION_MODELS = (
    PROJECT_ROOT
    / "tmp_workdir"
    / "7783f4fc35c54d12aee3fd50880fe829"
    / "models"
)
PORT = 7003
YEAR_MAPPING = {"2019": 1, "2020": 2, "2021": 3, "2022": 4, "2023": 5, "2024": 6, "2025": 7}

# Re-login to get a fresh token.
EMAIL = "agenta3@example.com"
PW = "TestPass123!"


def _api(p: str) -> str:
    return f"http://localhost:{PORT}{p}"


MAPPING = {
    "A3_AdamW_wd4": "elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.0001",
    "A3_AdamW_wd3": "elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.001",
    "A3_AdamW_wd4_clipnorm1": "elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.0001_cn1.0",
    "A3_Skip": "elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_skip",
}


def main() -> int:
    r = requests.post(
        _api("/api/auth/login"),
        json={"email": EMAIL, "password": PW},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Find the existing session (we know its id).
    sid = "7783f4fc35c54d12aee3fd50880fe829"
    # Verify session is still alive — try the evaluation/run endpoint.

    for run_name, actual in MAPPING.items():
        target = BATCH / run_name
        if not target.exists():
            print(f"skip {run_name}: dir missing")
            continue
        model_dir = SESSION_MODELS / actual
        if not model_dir.exists():
            print(f"skip {run_name}: model dir missing {model_dir}")
            continue

        eval_body = {
            "session_id": sid,
            "model_name": actual,
            "model_dir": str(SESSION_MODELS),
            "year_column_name": "Annee",
            "year_value_mapping": YEAR_MAPPING,
        }
        print(f"re-eval {run_name} -> {actual}")
        r = requests.post(
            _api("/api/evaluation/run?bootstrap_iter=1000"),
            json=eval_body,
            headers=headers,
            timeout=900,
        )
        if r.status_code != 200:
            print(f"  ERR {r.status_code}: {r.text[:200]}")
            continue
        metrics = r.json()["metrics"]

        r2 = requests.get(
            _api(f"/api/evaluation/report/{sid}"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=180,
        )
        html = r2.json().get("report_html", "")

        m_tol = re.search(
            r'Capteurs tolerance inclus</div>\s*<div class="v">\s*(\d+)\s*/\s*(\d+)',
            html,
        )
        m_p80 = re.search(
            r'Err\. rel\. p80</div>\s*<div class="v">\s*([\d.]+)\s*%', html
        )
        tol_in = int(m_tol.group(1)) if m_tol else 0
        tol_total = int(m_tol.group(2)) if m_tol else 0
        p80 = float(m_p80.group(1)) if m_p80 else float("nan")

        # Update metrics.json + replace report.html + sync model dir.
        metrics_path = target / "metrics.json"
        doc = json.loads(metrics_path.read_text(encoding="utf-8"))
        doc["metrics"] = metrics
        doc["actual_model_name"] = actual
        doc["tol_inclus"] = tol_in
        doc["tol_total"] = tol_total
        doc["err_p80_pct"] = p80
        doc["barplot_broken"] = "Aucune donnee disponible" in html
        metrics_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

        (target / "report.html").write_text(html, encoding="utf-8")

        # Sync model dir (copy fresh from server in case it differs).
        dst = target / "model"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(model_dir, dst)

        # Patch README.
        readme = target / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
            r2_val = metrics.get("r_squared", 0)
            rmse = metrics.get("rmse")
            mae = metrics.get("mae")
            text = re.sub(
                r"Capteurs tolérance inclus:.*",
                f"Capteurs tolérance inclus: **{tol_in}/{tol_total}** ({100 * tol_in / max(tol_total, 1):.1f}%)",
                text,
            )
            text = re.sub(
                r"Erreur relative p80:.*",
                f"Erreur relative p80: **{p80}%**",
                text,
            )
            text = re.sub(r"R²:.*", f"R²: {r2_val:.4f}", text)
            text = re.sub(r"RMSE:.*", f"RMSE: {rmse}", text)
            text = re.sub(r"MAE:.*", f"MAE: {mae}", text)
            readme.write_text(text, encoding="utf-8")

        print(
            f"  tol={tol_in}/{tol_total} ({100 * tol_in / max(tol_total, 1):.1f}%) p80={p80}% R2={metrics.get('r_squared', 0):.4f}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
