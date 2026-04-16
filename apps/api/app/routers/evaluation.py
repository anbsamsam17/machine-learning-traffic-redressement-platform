"""Evaluation router — upload validation data, run model evaluation, generate HTML report, download model."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
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
    model_name: str | None = None
    model_dir: str | None = None
    high_flow_threshold: float = DEFAULT_HIGH_FLOW_THRESHOLD
    filter_flag_comptage: bool = False  # if True, only evaluate on flag_comptage == 1 (permanent sensors)


class MetricsResult(BaseModel):
    rmse: float
    mae: float
    mape: float | None = None
    r_squared: float
    geh_mean: float
    geh_pct_below_5: float
    n_samples: int
    hd_rmse: float | None = None
    ld_rmse: float | None = None
    median_relative_error: float | None = None


class EvalResponse(BaseModel):
    session_id: str
    model_name: str
    metrics: MetricsResult
    report_url: str


class ReportResponse(BaseModel):
    session_id: str
    report_html: str


class ModelInfo(BaseModel):
    name: str
    path: str
    has_weights: bool
    has_architecture: bool
    has_norm: bool
    training_config: dict[str, Any] | None = None


class ModelsListResponse(BaseModel):
    models: list[ModelInfo]


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

    # MAPE
    nonzero = y_true != 0
    mape = float(np.mean(np.abs(residuals[nonzero] / y_true[nonzero])) * 100) if nonzero.any() else None

    # Median relative error
    median_rel = float(np.median(np.abs(residuals[nonzero] / y_true[nonzero])) * 100) if nonzero.any() else None

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
        median_relative_error=round(median_rel, 2) if median_rel is not None else None,
    )


# ---------------------------------------------------------------------------
# HTML report generator
# ---------------------------------------------------------------------------

def _generate_html_report(
    metrics: MetricsResult,
    model_name: str,
    training_config: dict[str, Any] | None,
    y_true: np.ndarray,
    y_pred: np.ndarray,
) -> str:
    """Generate a self-contained HTML evaluation report."""

    # Architecture description
    arch_str = "N/A"
    activation_str = "N/A"
    lr_str = "N/A"
    epochs_str = "N/A"
    loss_str = "N/A"
    input_cols_str = "N/A"
    output_col_str = "N/A"

    if training_config:
        nf = training_config.get("neurons_factors", [])
        if nf:
            arch_str = " - ".join(str(f) for f in nf)
        activation_str = str(training_config.get("activation", "N/A"))
        lr_str = str(training_config.get("learning_rate", "N/A"))
        epochs_str = str(training_config.get("epochs_trained", training_config.get("epochs_requested", "N/A")))
        loss_str = str(training_config.get("loss", "N/A"))
        input_cols = training_config.get("input_cols", [])
        if input_cols:
            input_cols_str = ", ".join(input_cols)
        output_col_str = str(training_config.get("output_col", "N/A"))

    # GEH distribution
    geh_vals = _geh(y_true, y_pred)
    geh_lt3 = float(np.mean(geh_vals < 3) * 100)
    geh_lt5 = float(np.mean(geh_vals < 5) * 100)
    geh_lt10 = float(np.mean(geh_vals < 10) * 100)

    # Error distribution
    nonzero = y_true != 0
    if nonzero.any():
        rel_errors = np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero]) * 100
        pct_lt5 = float(np.mean(rel_errors < 5) * 100)
        pct_lt10 = float(np.mean(rel_errors < 10) * 100)
        pct_lt15 = float(np.mean(rel_errors < 15) * 100)
        pct_lt20 = float(np.mean(rel_errors < 20) * 100)
        p25 = float(np.percentile(rel_errors, 25))
        p50 = float(np.percentile(rel_errors, 50))
        p75 = float(np.percentile(rel_errors, 75))
        p90 = float(np.percentile(rel_errors, 90))
    else:
        pct_lt5 = pct_lt10 = pct_lt15 = pct_lt20 = 0.0
        p25 = p50 = p75 = p90 = 0.0

    # R² color
    r2_class = "good" if metrics.r_squared > 0.95 else ("warn" if metrics.r_squared > 0.85 else "bad")
    geh_class = "good" if metrics.geh_pct_below_5 > 85 else ("warn" if metrics.geh_pct_below_5 > 70 else "bad")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Rapport d'Evaluation - {model_name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: #0a0a1a;
    color: #e2e8f0;
    max-width: 1000px;
    margin: 0 auto;
    padding: 40px 24px;
    line-height: 1.6;
  }}
  h1 {{
    font-size: 1.8em;
    background: linear-gradient(135deg, #6366f1, #06b6d4);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
  }}
  h2 {{
    font-size: 1.2em;
    color: #a5b4fc;
    margin: 32px 0 16px;
    border-bottom: 1px solid rgba(99,102,241,0.3);
    padding-bottom: 8px;
  }}
  .subtitle {{ color: #94a3b8; font-size: 0.9em; margin-bottom: 32px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    background: rgba(15,15,35,0.6);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(99,102,241,0.2);
  }}
  th {{
    background: rgba(99,102,241,0.15);
    text-align: left;
    padding: 12px 16px;
    font-size: 0.85em;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #a5b4fc;
  }}
  td {{
    padding: 10px 16px;
    border-top: 1px solid rgba(99,102,241,0.1);
    font-size: 0.9em;
  }}
  tr:hover td {{ background: rgba(99,102,241,0.05); }}
  .good {{ color: #34d399; font-weight: 600; }}
  .warn {{ color: #fbbf24; font-weight: 600; }}
  .bad {{ color: #f87171; font-weight: 600; }}
  .metric-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin: 16px 0;
  }}
  .metric-card {{
    background: rgba(15,15,35,0.6);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 12px;
    padding: 16px;
    text-align: center;
  }}
  .metric-card .label {{ color: #94a3b8; font-size: 0.8em; margin-bottom: 4px; }}
  .metric-card .value {{ font-size: 1.4em; font-weight: 700; color: #e2e8f0; }}
  .footer {{
    margin-top: 48px;
    padding-top: 16px;
    border-top: 1px solid rgba(99,102,241,0.2);
    color: #64748b;
    font-size: 0.8em;
    text-align: center;
  }}
</style>
</head>
<body>

<h1>Rapport d'Evaluation</h1>
<p class="subtitle">Modele : <strong>{model_name}</strong> | {metrics.n_samples} echantillons</p>

<h2>Metriques globales</h2>
<div class="metric-grid">
  <div class="metric-card">
    <div class="label">MAE</div>
    <div class="value">{metrics.mae:.2f}</div>
  </div>
  <div class="metric-card">
    <div class="label">RMSE</div>
    <div class="value">{metrics.rmse:.2f}</div>
  </div>
  <div class="metric-card">
    <div class="label">R&sup2;</div>
    <div class="value {r2_class}">{metrics.r_squared:.4f}</div>
  </div>
  <div class="metric-card">
    <div class="label">GEH &lt; 5</div>
    <div class="value {geh_class}">{metrics.geh_pct_below_5:.1f}%</div>
  </div>
  <div class="metric-card">
    <div class="label">Erreur relative mediane</div>
    <div class="value">{metrics.median_relative_error:.1f}%</div>
  </div>
</div>

<h2>Tableau comparatif des metriques</h2>
<table>
  <tr><th>Metrique</th><th>Valeur</th></tr>
  <tr><td>RMSE</td><td>{metrics.rmse:.4f}</td></tr>
  <tr><td>MAE</td><td>{metrics.mae:.4f}</td></tr>
  <tr><td>MAPE (%)</td><td>{metrics.mape if metrics.mape is not None else 'N/A'}</td></tr>
  <tr><td>R&sup2;</td><td class="{r2_class}">{metrics.r_squared:.6f}</td></tr>
  <tr><td>GEH moyen</td><td>{metrics.geh_mean:.4f}</td></tr>
  <tr><td>GEH &lt; 5 (%)</td><td class="{geh_class}">{metrics.geh_pct_below_5:.2f}%</td></tr>
  <tr><td>Erreur relative mediane (%)</td><td>{metrics.median_relative_error if metrics.median_relative_error is not None else 'N/A'}</td></tr>
  <tr><td>Echantillons</td><td>{metrics.n_samples}</td></tr>
  <tr><td>RMSE (fort trafic &ge; {DEFAULT_HIGH_FLOW_THRESHOLD:.0f})</td><td>{metrics.hd_rmse if metrics.hd_rmse is not None else 'N/A'}</td></tr>
  <tr><td>RMSE (faible trafic)</td><td>{metrics.ld_rmse if metrics.ld_rmse is not None else 'N/A'}</td></tr>
</table>

<h2>Distribution GEH</h2>
<table>
  <tr><th>Seuil GEH</th><th>% capteurs</th></tr>
  <tr><td>GEH &lt; 3</td><td class="{'good' if geh_lt3 > 80 else 'warn'}">{geh_lt3:.1f}%</td></tr>
  <tr><td>GEH &lt; 5</td><td class="{'good' if geh_lt5 > 85 else 'warn'}">{geh_lt5:.1f}%</td></tr>
  <tr><td>GEH &lt; 10</td><td class="{'good' if geh_lt10 > 95 else 'warn'}">{geh_lt10:.1f}%</td></tr>
</table>

<h2>Distribution des erreurs relatives</h2>
<table>
  <tr><th>Seuil</th><th>% capteurs</th></tr>
  <tr><td>Erreur &lt; 5%</td><td>{pct_lt5:.1f}%</td></tr>
  <tr><td>Erreur &lt; 10%</td><td>{pct_lt10:.1f}%</td></tr>
  <tr><td>Erreur &lt; 15%</td><td>{pct_lt15:.1f}%</td></tr>
  <tr><td>Erreur &lt; 20%</td><td>{pct_lt20:.1f}%</td></tr>
</table>
<table>
  <tr><th>Percentile</th><th>Erreur relative (%)</th></tr>
  <tr><td>P25</td><td>{p25:.1f}%</td></tr>
  <tr><td>P50 (mediane)</td><td>{p50:.1f}%</td></tr>
  <tr><td>P75</td><td>{p75:.1f}%</td></tr>
  <tr><td>P90</td><td>{p90:.1f}%</td></tr>
</table>

<h2>Architecture et hyperparametres</h2>
<table>
  <tr><th>Parametre</th><th>Valeur</th></tr>
  <tr><td>Nom du modele</td><td>{model_name}</td></tr>
  <tr><td>Architecture (facteurs neurones)</td><td>{arch_str}</td></tr>
  <tr><td>Activation</td><td>{activation_str}</td></tr>
  <tr><td>Learning rate</td><td>{lr_str}</td></tr>
  <tr><td>Epochs</td><td>{epochs_str}</td></tr>
  <tr><td>Fonction de perte</td><td>{loss_str}</td></tr>
  <tr><td>Variables d'entree</td><td>{input_cols_str}</td></tr>
  <tr><td>Variable de sortie</td><td>{output_col_str}</td></tr>
</table>

<div class="footer">
  Rapport genere par MDL Redressement API v2.0
</div>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Helper: load model from disk
# ---------------------------------------------------------------------------

def _load_model_from_dir(model_path: Path) -> tuple[Any, dict]:
    """Load a Keras model + norm coefficients from a model directory on disk."""
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    from tensorflow.keras.models import model_from_json

    arch_file = model_path / "NNarchitecture.json"
    if not arch_file.exists():
        raise FileNotFoundError(f"NNarchitecture.json introuvable dans {model_path}")

    model_json = arch_file.read_text(encoding="utf-8")
    model = model_from_json(model_json)

    # Try both naming conventions for weights
    weights_file = model_path / "NNweights.weights.h5"
    if not weights_file.exists():
        weights_file = model_path / "NNweights.h5"
    if not weights_file.exists():
        raise FileNotFoundError(f"Fichier de poids introuvable dans {model_path}")

    model.load_weights(str(weights_file))

    # Load norm coefficients
    norm_file = model_path / "NNnormCoefficients.json"
    if not norm_file.exists():
        raise FileNotFoundError(f"NNnormCoefficients.json introuvable dans {model_path}")

    norm_data = json.loads(norm_file.read_text(encoding="utf-8"))

    # Load training config if available
    config_file = model_path / "training_config.json"
    training_config = None
    if config_file.exists():
        training_config = json.loads(config_file.read_text(encoding="utf-8"))

    return model, norm_data, training_config


def _read_uploaded_df(session: Any) -> pd.DataFrame:
    """Get validation DataFrame from session."""
    df = session.data.get("validation_df")
    if df is None:
        df = session.data.get("learning_df")
    if df is None:
        raise ValueError("Aucune donnee de validation disponible dans la session.")
    return df.copy()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/upload-validation")
async def upload_validation(
    file: UploadFile = File(...),
    session_id: str = Form(...),
) -> dict:
    """Upload a validation file (GeoJSON or CSV) and store it in the session."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    content = await file.read()
    filename = file.filename or "validation"

    try:
        if filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
        elif filename.lower().endswith((".geojson", ".json")):
            import geopandas as gpd
            df = gpd.read_file(io.BytesIO(content))
            # Convert to regular DataFrame (drop geometry for ML)
            if "geometry" in df.columns:
                df = pd.DataFrame(df.drop(columns=["geometry"]))
        else:
            # Try CSV fallback
            df = pd.read_csv(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Impossible de lire le fichier : {exc}",
        )

    # Column renames for compatibility (same aliases as training scripts)
    renames = {
        "TMJATV": "TMJAFCDTV",
        "TMJFCDTV": "TMJAFCDTV",
        "TMJAPL": "TMJAFCDPL",
        "TMJFCDPL": "TMJAFCDPL",
        "TMJAVL": "TMJAFCDVL",
        "TxPen": "TxPenTVRef",
        "TxPenPL": "TxPenPLRef",
    }
    for old, new in renames.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # Also try case-insensitive matching for columns the model expects
    col_lower_map = {c.lower(): c for c in df.columns}
    common_cols = [
        "TMJAFCDTV", "TMJAFCDPL", "TMJABCTV", "TMJABCPL",
        "car_average_speed_kmh", "car_average_distance_km",
        "truck_average_speed_kmh", "truck_min_average_distance_km",
        "car_count", "truck_count", "variabilite_FCD",
        "TxPenTVRef", "TxPenPLRef", "flag_comptage",
    ]
    for target in common_cols:
        if target not in df.columns and target.lower() in col_lower_map:
            df[target] = df[col_lower_map[target.lower()]]

    logger.info("Validation columns after renames: %s", list(df.columns)[:20])
    session_manager.store_data(session_id, "validation_df", df)

    logger.info(
        "Validation file uploaded: session=%s file=%s rows=%d cols=%d",
        session_id, filename, len(df), len(df.columns),
    )

    return {
        "status": "ok",
        "filename": filename,
        "rows": len(df),
        "columns": len(df.columns),
    }


@router.post("/run", response_model=EvalResponse)
async def run_evaluation(body: EvalRequest) -> EvalResponse:
    """Run model evaluation on validation data.

    Supports two modes:
    1. model_name + model_dir: load model from disk (output_dir from training)
    2. Fallback to session-stored model (legacy)
    """
    import os
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

    session = session_manager.get_session(body.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    # --- Determine model source ---
    model = None
    norm_params = None
    training_config = None
    model_name = body.model_name or "model"

    if body.model_name and body.model_dir:
        # Load from disk
        model_path = Path(body.model_dir) / body.model_name
        if not model_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Dossier modele introuvable : {model_path}",
            )
        try:
            model, norm_raw, training_config = _load_model_from_dir(model_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Parse norm coefficients from disk format (muX/SX/muY/SY)
        x_mean = np.array(norm_raw["muX"][0], dtype=np.float64)
        x_std = np.array(norm_raw["SX"][0], dtype=np.float64)
        y_mean = float(norm_raw["muY"][0][0])
        y_std = float(norm_raw["SY"][0][0])

        # Get input/output cols from training config
        if training_config:
            input_cols = training_config.get("input_cols", [])
            output_col = training_config.get("output_col", "TxPenTVRef")
        else:
            raise HTTPException(
                status_code=400,
                detail="training_config.json manquant dans le dossier modele.",
            )
    else:
        # Legacy: load from session
        model_json_str = session.data.get("trained_model_json")
        weights_bytes = session.data.get("trained_weights")
        session_norm = session.data.get("norm_params")

        if not all([model_json_str, weights_bytes, session_norm]):
            raise HTTPException(
                status_code=400,
                detail="Aucun modele entraine. Specifiez model_name + model_dir ou lancez l'entrainement.",
            )

        from tensorflow.keras.models import model_from_json
        model = model_from_json(model_json_str)

        with tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False) as tmp:
            tmp.write(weights_bytes)
            tmp_path = tmp.name
        model.load_weights(tmp_path)
        Path(tmp_path).unlink(missing_ok=True)

        input_cols = session_norm["input_cols"]
        output_col = session_norm["output_col"]
        x_mean = np.array(session_norm["x_mean"])
        x_std = np.array(session_norm["x_std"])
        y_mean = session_norm["y_mean"]
        y_std = session_norm["y_std"]

    # --- Get evaluation data ---
    try:
        df = _read_uploaded_df(session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Apply column renames on validation data too (same as upload)
    val_renames = {
        "TMJATV": "TMJAFCDTV", "TMJFCDTV": "TMJAFCDTV",
        "TMJAPL": "TMJAFCDPL", "TMJFCDPL": "TMJAFCDPL",
        "TxPen": "TxPenTVRef", "TxPenPL": "TxPenPLRef",
    }
    for old, new in val_renames.items():
        if old in df.columns and new not in df.columns:
            df[new] = df[old]

    # Case-insensitive fallback for missing columns
    col_lower = {c.lower(): c for c in df.columns}
    for target in input_cols + [output_col]:
        if target not in df.columns and target.lower() in col_lower:
            df[target] = df[col_lower[target.lower()]]

    # Filter by flag_comptage if requested (permanent sensors only)
    if body.filter_flag_comptage:
        if "flag_comptage" in df.columns:
            before = len(df)
            df = df[pd.to_numeric(df["flag_comptage"], errors="coerce") == 1]
            logger.info("Filtre flag_comptage=1 : %d -> %d lignes", before, len(df))
        else:
            logger.warning("flag_comptage demande mais colonne absente — pas de filtre applique")

    missing = [c for c in input_cols + [output_col] if c not in df.columns]
    if missing:
        # Log available columns for debugging
        logger.error("Colonnes manquantes: %s. Colonnes disponibles: %s", missing, list(df.columns)[:30])
        raise HTTPException(
            status_code=400,
            detail=f"Colonnes manquantes dans les donnees de validation : {missing}. Colonnes disponibles : {list(df.columns)[:20]}",
        )

    sub = df[input_cols + [output_col]].dropna()
    if len(sub) < 2:
        raise HTTPException(status_code=400, detail="Trop peu de lignes valides pour l'evaluation.")

    X = sub[input_cols].values.astype(np.float64)
    y_true = sub[output_col].values.astype(np.float64)

    # Normalize and predict
    x_std_safe = np.where(x_std == 0, 1.0, x_std)
    X_norm = (X - x_mean) / x_std_safe
    y_pred_norm = model.predict(X_norm, verbose=0).flatten()
    y_pred = y_pred_norm * y_std + y_mean

    # Compute metrics
    metrics = _compute_metrics(y_true, y_pred, body.high_flow_threshold)

    # Generate HTML report
    report_html = _generate_html_report(
        metrics=metrics,
        model_name=model_name,
        training_config=training_config,
        y_true=y_true,
        y_pred=y_pred,
    )

    # Store in session
    session_manager.store_data(body.session_id, "eval_metrics", metrics.model_dump())
    session_manager.store_data(body.session_id, "eval_y_true", y_true.tolist())
    session_manager.store_data(body.session_id, "eval_y_pred", y_pred.tolist())
    session_manager.store_data(body.session_id, "eval_report_html", report_html)
    session_manager.store_data(body.session_id, "eval_model_name", model_name)

    logger.info(
        "Evaluation done: session=%s model=%s RMSE=%.4f R2=%.4f GEH<5=%.1f%%",
        body.session_id, model_name, metrics.rmse, metrics.r_squared, metrics.geh_pct_below_5,
    )

    return EvalResponse(
        session_id=body.session_id,
        model_name=model_name,
        metrics=metrics,
        report_url=f"/api/evaluation/report/{body.session_id}",
    )


@router.get("/report/{session_id}", response_model=ReportResponse)
async def get_report(session_id: str) -> ReportResponse:
    """Return the generated HTML evaluation report."""
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session non trouvee ou expiree.")

    report_html = session.data.get("eval_report_html")
    if report_html is None:
        # Fallback: generate a minimal report from stored metrics
        metrics_dict = session.data.get("eval_metrics")
        if metrics_dict is None:
            raise HTTPException(status_code=400, detail="Lancez l'evaluation d'abord (/api/evaluation/run).")

        metrics = MetricsResult(**metrics_dict)
        model_name = session.data.get("eval_model_name", "modele")
        y_true = np.array(session.data.get("eval_y_true", []))
        y_pred = np.array(session.data.get("eval_y_pred", []))

        report_html = _generate_html_report(
            metrics=metrics,
            model_name=model_name,
            training_config=None,
            y_true=y_true,
            y_pred=y_pred,
        )

    return ReportResponse(session_id=session_id, report_html=report_html)


@router.get("/download-model")
async def download_model(
    model_name: str = Query(...),
    model_dir: str = Query(...),
    session_id: str = Query(None),
) -> StreamingResponse:
    """Download a model folder as a ZIP file."""
    model_path = Path(model_dir) / model_name
    if not model_path.exists() or not model_path.is_dir():
        raise HTTPException(status_code=404, detail=f"Dossier modele introuvable : {model_path}")

    # Create ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in model_path.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(model_path)
                zf.write(file, arcname)

    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{model_name}.zip"',
        },
    )
