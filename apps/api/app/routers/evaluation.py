"""Evaluation router — run model evaluation and generate reports."""

from __future__ import annotations

import json
import logging
import math
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..session import session_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

DEFAULT_HIGH_FLOW_THRESHOLD = 1000.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class EvalRequest(BaseModel):
    session_id: str
    high_flow_threshold: float = DEFAULT_HIGH_FLOW_THRESHOLD


class MetricsResult(BaseModel):
    rmse: float
    mae: float
    mape: float | None = None
    r_squared: float
    geh_mean: float
    geh_pct_below_5: float  # percentage of GEH < 5
    n_samples: int
    hd_rmse: float | None = None  # high-demand subset
    ld_rmse: float | None = None  # low-demand subset


class EvalResponse(BaseModel):
    session_id: str
    metrics: MetricsResult
    predictions_preview: list[dict]


class ReportResponse(BaseModel):
    session_id: str
    report_html: str


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------

def _geh(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """GEH statistic (traffic engineering)."""
    denom = (observed + predicted) / 2.0
    denom = np.where(denom == 0, 1e-9, denom)
    return np.sqrt((observed - predicted) ** 2 / denom)


def _compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    high_threshold: float,
) -> MetricsResult:
    residuals = y_true - y_pred
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))

    # MAPE — avoid division by zero
    nonzero = y_true != 0
    mape = float(np.mean(np.abs(residuals[nonzero] / y_true[nonzero])) * 100) if nonzero.any() else None

    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0

    geh_vals = _geh(y_true, y_pred)
    geh_mean = float(np.mean(geh_vals))
    geh_below_5 = float(np.mean(geh_vals < 5) * 100)

    # HD / LD subsets
    hd_mask = y_true >= high_threshold
    ld_mask = ~hd_mask
    hd_rmse = float(np.sqrt(np.mean(residuals[hd_mask] ** 2))) if hd_mask.any() else None
    ld_rmse = float(np.sqrt(np.mean(residuals[ld_mask] ** 2))) if ld_mask.any() else None

    return MetricsResult(
        rmse=round(rmse, 4),
        mae=round(mae, 4),
        mape=round(mape, 2) if mape is not None else None,
        r_squared=round(r2, 6),
        geh_mean=round(geh_mean, 4),
        geh_pct_below_5=round(geh_below_5, 2),
        n_samples=len(y_true),
        hd_rmse=round(hd_rmse, 4) if hd_rmse is not None else None,
        ld_rmse=round(ld_rmse, 4) if ld_rmse is not None else None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/run", response_model=EvalResponse)
async def run_evaluation(body: EvalRequest) -> EvalResponse:
    """Run model evaluation on validation data (or the training split)."""
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    model_json_str = session.data.get("trained_model_json")
    weights_bytes = session.data.get("trained_weights")
    norm_params = session.data.get("norm_params")

    if not all([model_json_str, weights_bytes, norm_params]):
        raise HTTPException(
            status_code=400,
            detail="Aucun modele entraine dans cette session. Lancez l'entrainement d'abord.",
        )

    # Load model
    from tensorflow.keras.models import model_from_json
    model = model_from_json(model_json_str)

    with tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False) as tmp:
        tmp.write(weights_bytes)
        tmp_path = tmp.name
    model.load_weights(tmp_path)
    Path(tmp_path).unlink(missing_ok=True)

    # Determine evaluation data
    eval_df: pd.DataFrame | None = session.data.get("validation_df")
    if eval_df is None:
        eval_df = session.data.get("learning_df")
    if eval_df is None:
        raise HTTPException(status_code=400, detail="Aucune donnee d'evaluation disponible.")

    # Rename columns for compatibility
    df = eval_df.copy()
    renames = {"TMJATV": "TMJAFCDTV", "TMJAPL": "TMJAFCDPL", "TxPen": "TxPenTVRef"}
    for old, new in renames.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    input_cols: list[str] = norm_params["input_cols"]
    output_col: str = norm_params["output_col"]

    missing = [c for c in input_cols + [output_col] if c not in df.columns]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes dans les donnees d'evaluation: {missing}",
        )

    sub = df[input_cols + [output_col]].dropna()
    if len(sub) < 2:
        raise HTTPException(status_code=400, detail="Trop peu de lignes valides pour l'evaluation.")

    X = sub[input_cols].values.astype(np.float64)
    y_true = sub[output_col].values.astype(np.float64)

    x_mean = np.array(norm_params["x_mean"])
    x_std = np.array(norm_params["x_std"])
    y_mean = norm_params["y_mean"]
    y_std = norm_params["y_std"]

    X_norm = (X - x_mean) / x_std
    y_pred_norm = model.predict(X_norm, verbose=0).flatten()
    y_pred = y_pred_norm * y_std + y_mean

    metrics = _compute_metrics(y_true, y_pred, body.high_flow_threshold)

    # Store for export
    session_manager.store_data(body.session_id, "eval_metrics", metrics.model_dump())
    session_manager.store_data(body.session_id, "eval_y_true", y_true.tolist())
    session_manager.store_data(body.session_id, "eval_y_pred", y_pred.tolist())

    # Preview: first 20 rows
    preview = []
    for i in range(min(20, len(y_true))):
        preview.append({
            "index": i,
            "observed": round(float(y_true[i]), 2),
            "predicted": round(float(y_pred[i]), 2),
            "residual": round(float(y_true[i] - y_pred[i]), 2),
            "geh": round(float(_geh(y_true[i:i+1], y_pred[i:i+1])[0]), 3),
        })

    logger.info(
        "Evaluation done: session=%s RMSE=%.4f R2=%.4f GEH<5=%.1f%%",
        body.session_id, metrics.rmse, metrics.r_squared, metrics.geh_pct_below_5,
    )

    return EvalResponse(
        session_id=body.session_id,
        metrics=metrics,
        predictions_preview=preview,
    )


@router.get("/report/{session_id}", response_model=ReportResponse)
async def get_report(session_id: str) -> ReportResponse:
    """Generate a simple HTML evaluation report."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    metrics = session.data.get("eval_metrics")
    y_true = session.data.get("eval_y_true")
    y_pred = session.data.get("eval_y_pred")

    if metrics is None:
        raise HTTPException(status_code=400, detail="Lancez l'evaluation d'abord (/api/evaluation/run).")

    # Build a minimal HTML report
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="utf-8"><title>Rapport Evaluation MDL</title>
<style>
body {{ font-family: Arial, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: right; }}
th {{ background: #f5f5f5; text-align: left; }}
.good {{ color: #2e7d32; }} .warn {{ color: #f57f17; }} .bad {{ color: #c62828; }}
</style>
</head>
<body>
<h1>Rapport d'Evaluation - Modele de Redressement</h1>
<h2>Metriques globales</h2>
<table>
<tr><th>Metrique</th><th>Valeur</th></tr>
<tr><td>RMSE</td><td>{metrics['rmse']}</td></tr>
<tr><td>MAE</td><td>{metrics['mae']}</td></tr>
<tr><td>MAPE (%)</td><td>{metrics.get('mape', 'N/A')}</td></tr>
<tr><td>R&sup2;</td><td>{metrics['r_squared']}</td></tr>
<tr><td>GEH moyen</td><td>{metrics['geh_mean']}</td></tr>
<tr><td>GEH &lt; 5 (%)</td><td>{metrics['geh_pct_below_5']}</td></tr>
<tr><td>Echantillons</td><td>{metrics['n_samples']}</td></tr>
<tr><td>RMSE (fort trafic)</td><td>{metrics.get('hd_rmse', 'N/A')}</td></tr>
<tr><td>RMSE (faible trafic)</td><td>{metrics.get('ld_rmse', 'N/A')}</td></tr>
</table>
<p><em>Rapport genere par MDL Redressement API v2.0</em></p>
</body></html>"""

    return ReportResponse(session_id=session_id, report_html=html)
