"""Evaluation router — upload validation data, run model evaluation, generate HTML report, download model."""

from __future__ import annotations

import html as _html
import io
import json
import logging
import math
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
    filter_flag_comptage: bool = False
    column_mapping: dict[str, str] | None = None  # target -> source mapping from frontend


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

def _fmt(v, digits=2):
    """Format a numeric value for display, handling NaN/Inf."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "-"
    return f"{v:.{digits}f}"


def _add_tolerance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute TVrmin, TVrmax, Tolerance_IN_OUT (1=in, 2=near, 3=out) exactly as original."""
    out = df.copy()
    out["TVr"] = pd.to_numeric(out["TVr"], errors="coerce")

    def erreur_pourcentage(tvr):
        if pd.isna(tvr):
            return np.nan
        if tvr > 10000:
            return 0.14
        if tvr > 5000:
            return 0.18
        if tvr > 2000:
            return 0.18
        return 0.25

    out["Erreur_dyn"] = out["TVr"].apply(erreur_pourcentage)
    out["TVrmin"] = out["TVr"] * (1 - out["Erreur_dyn"])
    out["TVrmax"] = out["TVr"] * (1 + out["Erreur_dyn"])

    mask10 = out["TVr"] > 10000
    out.loc[mask10, "TVrmin"] = np.round(out.loc[mask10, "TVrmin"], -2)
    out.loc[mask10, "TVrmax"] = np.round(out.loc[mask10, "TVrmax"], -2)

    mask500 = out["TVr"] < 500
    out.loc[mask500, "TVrmin"] = 10 * np.floor(out.loc[mask500, "TVrmin"] / 10)
    out.loc[mask500, "TVrmax"] = 10 * np.ceil(out.loc[mask500, "TVrmax"] / 10)

    mask_middle = out["TVr"] >= 500
    out.loc[mask_middle, "TVrmin"] = 100 * np.floor(out.loc[mask_middle, "TVrmin"] / 100)
    out.loc[mask_middle, "TVrmax"] = 100 * np.ceil(out.loc[mask_middle, "TVrmax"] / 100)

    out.loc[out["TVrmin"].notna() & (out["TVrmin"] < 100), "TVrmin"] = 0
    out.loc[out["TVrmax"].notna() & (out["TVrmax"] < 100), "TVrmax"] = 100

    for c in ["TMJABCTV", "TVrmin", "TVrmax"]:
        out[c] = pd.to_numeric(out.get(c), errors="coerce")

    tmja = out["TMJABCTV"]
    lower = np.minimum(out["TVrmin"], out["TVrmax"])
    upper = np.maximum(out["TVrmin"], out["TVrmax"])

    in_range = tmja.ge(lower) & tmja.le(upper)
    near_lower = tmja.lt(lower) & tmja.ge(0.85 * lower)
    near_upper = tmja.gt(upper) & tmja.le(1.15 * upper)
    near_bound = near_lower | near_upper

    out["Tolerance_IN_OUT"] = pd.Series(
        np.select([in_range, near_bound], [1, 2], default=3),
        index=out.index,
    ).astype("Int64")

    mask_nan = tmja.isna() | lower.isna() | upper.isna()
    out.loc[mask_nan, "Tolerance_IN_OUT"] = pd.NA
    return out


def _compute_flow_metrics(df: pd.DataFrame) -> dict:
    """Compute flow metrics from a DataFrame with TVr and TMJABCTV columns."""
    d = df.copy()
    d["TMJABCTV"] = pd.to_numeric(d.get("TMJABCTV"), errors="coerce")
    d["TVr"] = pd.to_numeric(d.get("TVr"), errors="coerce")
    d["GEH"] = pd.to_numeric(d.get("GEH"), errors="coerce")
    d = d.dropna(subset=["TMJABCTV", "TVr"])

    if d.empty:
        return {
            "n": 0, "err_rel_med": np.nan, "err_abs_med": np.nan,
            "err_rel_p80": np.nan, "err_abs_p80": np.nan,
            "geh_lt5_pct": np.nan, "geh_le10_pct": np.nan,
        }

    err_abs = (d["TVr"] - d["TMJABCTV"]).abs().astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        err_rel = np.where(d["TMJABCTV"] != 0, err_abs / d["TMJABCTV"] * 100.0, np.nan)
    err_rel = pd.Series(err_rel).replace([np.inf, -np.inf], np.nan)

    geh = pd.to_numeric(d["GEH"], errors="coerce")
    valid_geh = geh.notna().sum()
    geh_lt5_pct = 100.0 * (geh < 5).sum() / valid_geh if valid_geh > 0 else np.nan
    geh_le10_pct = 100.0 * (geh <= 10).sum() / valid_geh if valid_geh > 0 else np.nan

    return {
        "n": int(len(d)),
        "err_rel_med": float(np.nanmedian(err_rel)),
        "err_abs_med": float(np.nanmedian(err_abs)),
        "err_rel_p80": float(np.nanpercentile(err_rel, 80)),
        "err_abs_p80": float(np.nanpercentile(err_abs, 80)),
        "geh_lt5_pct": float(geh_lt5_pct),
        "geh_le10_pct": float(geh_le10_pct),
    }


def _compute_tolerance_counts(df: pd.DataFrame) -> dict:
    """Count tolerance categories from Tolerance_IN_OUT column."""
    tol = pd.to_numeric(df.get("Tolerance_IN_OUT"), errors="coerce")
    return {
        "tol_total": int(tol.notna().sum()),
        "tol_in": int((tol == 1).sum()),
        "tol_near": int((tol == 2).sum()),
        "tol_out": int((tol == 3).sum()),
    }


def _make_barplot_html(df: pd.DataFrame, title: str) -> str:
    """Grouped bar chart TMJABCTV vs TVr (max 200 sensors), returns Plotly HTML fragment."""
    import plotly.graph_objects as go
    import plotly.io as pio

    d = df.copy()
    d["TMJABCTV"] = pd.to_numeric(d.get("TMJABCTV"), errors="coerce")
    d["TVr"] = pd.to_numeric(d.get("TVr"), errors="coerce")
    d = d.dropna(subset=["TMJABCTV", "TVr"])
    if d.empty:
        return f"<p>Aucune donnee ({title})</p>"

    n_sample = min(200, len(d))
    d = d.sample(n=n_sample, random_state=42).reset_index(drop=True)

    labels = d["PTM_ID"].astype(str).tolist() if "PTM_ID" in d.columns else [str(i) for i in range(len(d))]

    hover_cols = [
        c for c in [
            "PTM_ID", "Identifiant", "STA", "Type", "Commune", "Route",
            "TMJAFCDTV", "TMJAFCDPL",
            "car_count", "car_average_speed_kmh", "car_average_distance_km",
            "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
            "TMJABCTV", "TVr", "TP_redressement",
            "Erreur %", "Erreur absolue", "GEH",
            "TVrmin", "TVrmax", "Tolerance_IN_OUT",
        ] if c in d.columns
    ]

    def _fmtv(v):
        if v is None:
            return "-"
        try:
            if math.isnan(float(v)) or math.isinf(float(v)):
                return "-"
            if isinstance(v, float):
                return f"{v:.2f}"
        except (TypeError, ValueError):
            pass
        return str(v)

    customdata = [[_fmtv(row.get(c)) for c in hover_cols] for _, row in d.iterrows()]
    hover_lines = "".join(f"<b>{c}</b> : %{{customdata[{i}]}}<br>" for i, c in enumerate(hover_cols))
    hover_template = hover_lines + "<extra></extra>"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=d["TMJABCTV"].tolist(),
        name="TMJABCTV (validation)", marker_color="#1f77b4",
        customdata=customdata,
        hovertemplate=hover_template,
    ))
    fig.add_trace(go.Bar(
        x=labels, y=d["TVr"].tolist(),
        name="TVr (predit)", marker_color="#00b894",
        customdata=customdata,
        hovertemplate=hover_template,
    ))
    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title=title,
        xaxis_title="Capteurs",
        yaxis_title="TMJA (veh/jour)",
        margin=dict(l=40, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _make_folium_map_html(stats_df: pd.DataFrame, model_name: str) -> str:
    """Build a folium map coloured by Tolerance_IN_OUT, returns iframe HTML."""
    import folium

    df = stats_df.copy()
    df["lat"] = pd.to_numeric(df.get("lat"), errors="coerce")
    df["lon"] = pd.to_numeric(df.get("lon"), errors="coerce")
    valid = df.dropna(subset=["lat", "lon"])
    if valid.empty:
        return "<p style='color:#888;font-style:italic;'>Aucune coordonnee geographique disponible pour afficher la carte (colonnes lat/lon absentes).</p>"

    tol = pd.to_numeric(valid.get("Tolerance_IN_OUT"), errors="coerce")
    n1 = int((tol == 1).sum())
    n2 = int((tol == 2).sum())
    n3 = int((tol == 3).sum())
    n_valid = int(tol.notna().sum())

    def _color(val):
        try:
            k = int(val)
        except Exception:
            return "#808080"
        return {1: "#2ecc71", 2: "#f39c12", 3: "#e74c3c"}.get(k, "#808080")

    s = pd.to_numeric(valid.get("TMJABCTV"), errors="coerce")
    lo = float(np.nanquantile(s.dropna(), 0.01)) if s.notna().any() else 0.0
    hi = float(np.nanquantile(s.dropna(), 0.99)) if s.notna().any() else 1.0
    if not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0

    def _radius(v):
        try:
            v = float(v)
        except Exception:
            return 4.0
        return 3.0 + (min(max(v, lo), hi) - lo) / (hi - lo) * 9.0

    m = folium.Map(
        location=[float(valid["lat"].mean()), float(valid["lon"].mean())],
        zoom_start=11,
        tiles="cartodbpositron",
    )
    layer = folium.FeatureGroup(name="Capteurs")
    layer.add_to(m)

    info_cols = [
        c for c in [
            "PTM_ID", "Identifiant", "STA", "Type", "Commune", "Route",
            "TMJAFCDTV", "TMJAFCDPL",
            "car_count", "car_average_speed_kmh", "car_average_distance_km",
            "truck_count", "truck_average_speed_kmh", "truck_min_average_distance_km",
            "TMJABCTV", "TVr", "TP_redressement",
            "Erreur %", "Erreur absolue", "GEH",
            "TVrmin", "TVrmax", "Tolerance_IN_OUT",
            "flag_comptage",
        ] if c in valid.columns
    ]

    for _, row in valid.iterrows():
        lines = []
        for c in info_cols:
            v = row.get(c, "-")
            if isinstance(v, float):
                v = "-" if (math.isnan(v) or math.isinf(v)) else f"{v:.2f}"
            lines.append(f"<b>{c}</b> : {v}")
        popup_html = (
            "<div style='font-size:13px;font-family:Manrope,sans-serif;line-height:1.7;'>"
            + "<br>".join(lines)
            + "</div>"
        )
        tooltip_txt = str(row.get("PTM_ID", f"({row['lat']:.4f}, {row['lon']:.4f})"))
        folium.CircleMarker(
            location=(row["lat"], row["lon"]),
            radius=_radius(row.get("TMJABCTV")),
            color=_color(row.get("Tolerance_IN_OUT")),
            fill=True,
            fill_opacity=0.85,
            weight=1.2,
            popup=folium.Popup(popup_html, max_width=360),
            tooltip=tooltip_txt,
        ).add_to(layer)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds([
        [float(valid["lat"].min()), float(valid["lon"].min())],
        [float(valid["lat"].max()), float(valid["lon"].max())],
    ])

    pct = lambda n: (100.0 * n / n_valid) if n_valid > 0 else 0.0
    legend_html = f"""
    <div style="position:fixed;bottom:20px;left:20px;z-index:9999;background:white;
            padding:10px 14px;border:1px solid #ccc;border-radius:10px;
            box-shadow:0 2px 8px rgba(0,0,0,.18);font-size:13px;font-family:Manrope,sans-serif;">
      <div style="font-weight:700;margin-bottom:7px;">Tolerance &ndash; {_html.escape(model_name)}</div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#2ecc71;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>1 Inclus <b>({n1} &ndash; {pct(n1):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#f39c12;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>2 Hors &lt;15% borne <b>({n2} &ndash; {pct(n2):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#e74c3c;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>3 Hors &gt;15% borne <b>({n3} &ndash; {pct(n3):.1f}%)</b></div>
      <div style="margin-top:6px;font-size:11px;color:#666;">Total: {n_valid} | Rayon ~ TMJABCTV</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    map_full_html = m.get_root().render()
    # Use base64 srcdoc to avoid quote-escaping issues that break the HTML
    import base64
    encoded = base64.b64encode(map_full_html.encode("utf-8")).decode("ascii")
    return (
        f'<iframe id="folium-map-frame" width="100%" height="600" '
        f'style="border:none;border-radius:12px;display:block;" '
        f'sandbox="allow-scripts allow-same-origin"></iframe>\n'
        f'<script>\n'
        f'(function(){{\n'
        f'  var iframe = document.getElementById("folium-map-frame");\n'
        f'  var html = atob("{encoded}");\n'
        f'  iframe.srcdoc = html;\n'
        f'}})();\n'
        f'</script>'
    )


def _build_sensitivity_section_html(
    df: pd.DataFrame,
    model: Any,
    mu_x: np.ndarray,
    s_x: np.ndarray,
    mu_y: np.ndarray,
    s_y: np.ndarray,
    input_cols: list[str],
    num_points: int = 60,
) -> str:
    """Build sensitivity analysis HTML section.

    For each input feature, varies it from min to max (num_points steps) while
    fixing other features at Q1, Median, Q3 baselines. Predicts TxPen via the
    model, denormalises, and computes TVr = TMJAFCDTV / TxPen * 100.

    Returns a complete HTML string (CSS + section + JS) ready to embed in the report.
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    n_inputs = len(input_cols)
    # Expand mu_x/s_x if needed (for non-normalized trailing columns like year_mapped)
    if len(mu_x) < n_inputs:
        on_off_norm = np.ones(n_inputs, dtype=bool)
        n_not_normed = n_inputs - len(mu_x)
        on_off_norm[-n_not_normed:] = False
        if int(on_off_norm.sum()) == len(mu_x):
            full_mu = np.zeros(n_inputs, dtype=float)
            full_s = np.ones(n_inputs, dtype=float)
            full_mu[on_off_norm] = mu_x
            full_s[on_off_norm] = s_x
            mu_x = full_mu
            s_x = full_s

    # Cast input columns to numeric
    df_num = df[input_cols].copy()
    for c in input_cols:
        df_num[c] = pd.to_numeric(df_num[c], errors="coerce")

    # Compute Q1 / Median / Q3 baselines
    q_baselines = {
        "Q1":  df_num.quantile(0.25),
        "Med": df_num.quantile(0.50),
        "Q3":  df_num.quantile(0.75),
    }

    # Determine numerator column for TVr
    _numerator_col: str | None = None
    for _cand in ("TMJAFCDTV", "TMJATV"):
        if _cand in input_cols:
            _numerator_col = _cand
            break

    _COLORS = {"Q1": "#6eb5ff", "Med": "#0057b7", "Q3": "#003d80"}
    _DASHES = {"Q1": "dot", "Med": "solid", "Q3": "dash"}

    plots_dict: dict[str, str] = {}
    rendered_cols: list[str] = []

    s_x_safe = np.where(s_x == 0, 1.0, s_x)

    for feat in input_cols:
        col_series = df_num[feat].dropna()
        if col_series.empty:
            continue
        vmin, vmax = float(col_series.min()), float(col_series.max())
        if not (np.isfinite(vmin) and np.isfinite(vmax)):
            continue
        if vmax == vmin:
            continue

        x_vals = np.linspace(vmin, vmax, num_points, dtype=float)

        fig = go.Figure()

        for bl_label, q_vec in q_baselines.items():
            # Build input matrix: all features at baseline
            mat = np.tile(q_vec.values.astype(float), (num_points, 1))
            df_x = pd.DataFrame(mat, columns=input_cols)
            # Vary the current feature
            df_x[feat] = x_vals

            # Normalise -> predict -> denormalise
            x_norm = ((df_x.values - mu_x) / s_x_safe).astype(np.float32)
            y_norm = model.predict(x_norm, verbose=0)
            txpen = y_norm.flatten().astype(float) * float(s_y) + float(mu_y)

            # Compute TVr
            with np.errstate(divide="ignore", invalid="ignore"):
                if feat == _numerator_col:
                    numerator = x_vals
                elif _numerator_col is not None:
                    numerator = np.full(num_points, float(q_vec[_numerator_col]), dtype=float)
                else:
                    numerator = np.ones(num_points, dtype=float)

                tvr = np.where(txpen > 0, numerator / txpen * 100.0, np.nan)
                tvr = np.where(np.isfinite(tvr), tvr, np.nan)

            # Build hover text
            other_feats = [c for c in input_cols if c != feat]
            hover_lines = [
                f"<b>{feat}</b> : %{{x:.2f}}<br>",
                f"<b>TVr</b> : %{{y:.1f}}<br>",
                f"<i>Autres features fig&#233;es &#224; {bl_label} :</i><br>",
            ] + [
                f"&nbsp;&nbsp;{c} = {q_vec[c]:.2f}<br>"
                for c in other_feats
            ]
            hover_tmpl = "".join(hover_lines) + "<extra></extra>"

            fig.add_trace(go.Scatter(
                x=x_vals.tolist(),
                y=tvr.tolist(),
                mode="lines",
                name=bl_label,
                line=dict(color=_COLORS[bl_label], dash=_DASHES[bl_label], width=2),
                hovertemplate=hover_tmpl,
            ))

        fig.update_layout(
            title=f"TVr ~ {feat}",
            xaxis_title=feat,
            yaxis_title="TVr (v&#233;h/jour)",
            template="plotly_white",
            margin=dict(l=50, r=40, t=60, b=60),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
            legend=dict(
                orientation="h",
                yanchor="bottom", y=1.02,
                xanchor="left", x=0,
                title_text="Baseline",
            ),
        )

        plots_dict[feat] = pio.to_html(fig, include_plotlyjs=False, full_html=False)
        rendered_cols.append(feat)

    # Build the HTML section
    if not rendered_cols:
        return (
            '  <h2>Analyse de sensibilit&#233; &#8211; mod&#232;le</h2>\n'
            '  <p class="hint">Mod&#232;le ou colonnes d&#8217;entr&#233;e non disponibles '
            'pour l&#8217;analyse de sensibilit&#233;.</p>'
        )

    # Pills
    pills_html = "\n        ".join(
        f'<button class="sens-pill{" sens-pill--active" if i == 0 else ""}" '
        f'data-feat="{feat}" role="button" tabindex="0" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{feat}</button>'
        for i, feat in enumerate(rendered_cols)
    )
    # Plot divs
    plot_divs_html = "\n".join(
        f'<div id="sens-plot-{feat}" class="sens-plot-slot" '
        f'style="display:{"block" if i == 0 else "none"};">'
        f'{plots_dict[feat]}</div>'
        for i, feat in enumerate(rendered_cols)
    )

    return f"""
<style>
.sens-block{{font-family:Manrope,"Segoe UI",Arial,sans-serif;color:#122033;margin-bottom:16px;}}
.sens-panel{{background:linear-gradient(180deg,#fff,#fbfdff);border:1px solid #dfe7f2;border-radius:16px;padding:20px;box-shadow:0 10px 22px rgba(12,52,103,.07);}}
.sens-header{{display:flex;align-items:flex-start;gap:12px;margin-bottom:6px;}}
.sens-icon{{flex-shrink:0;width:38px;height:38px;background:linear-gradient(135deg,#0057b7,#1a80e8);border-radius:10px;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 10px rgba(0,87,183,.22);}}
.sens-icon svg{{width:20px;height:20px;stroke:#fff;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}}
.sens-titles h2{{margin:0 0 3px;font-size:18px;font-weight:800;color:#0d1f35;}}
.sens-desc{{color:#56637a;font-size:12.5px;line-height:1.5;margin:0;max-width:680px;}}
.sens-divider{{border:none;border-top:1px solid #e8eef7;margin:14px 0;}}
.sens-controls{{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px;}}
.sens-controls-label{{font-size:11.5px;font-weight:700;color:#56637a;text-transform:uppercase;letter-spacing:.06em;white-space:nowrap;}}
.sens-pills{{display:flex;flex-wrap:wrap;gap:7px;}}
.sens-pill{{cursor:pointer;padding:5px 14px;border-radius:999px;font-size:12.5px;font-weight:600;border:1.5px solid #c8d8ef;background:#f0f5fc;color:#3d5a80;transition:background .16s,color .16s,border-color .16s,box-shadow .16s;user-select:none;line-height:1.4;white-space:nowrap;}}
.sens-pill:hover{{background:#daeaf9;border-color:#7ab3e0;color:#0b3d7a;}}
.sens-pill.sens-pill--active{{background:linear-gradient(135deg,#0057b7,#1a80e8);border-color:#0057b7;color:#fff;box-shadow:0 3px 10px rgba(0,87,183,.28);}}
.sens-legend{{display:flex;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;}}
.sens-legend-item{{display:flex;align-items:center;gap:6px;font-size:11.5px;color:#56637a;}}
.sens-legend-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0;}}
.sens-legend-dot--q1{{background:#93c4f0;}}.sens-legend-dot--med{{background:#0057b7;}}.sens-legend-dot--q3{{background:#003a7a;}}
.sens-chart-wrap{{border-radius:10px;overflow:hidden;background:#f8fbff;border:1px solid #e8eef7;min-height:420px;}}
.sens-plot-slot{{width:100%;}}
.sens-plot-slot>div{{width:100%!important;}}
@media(max-width:600px){{.sens-pills{{display:grid;grid-template-columns:1fr 1fr;}}.sens-pill{{text-align:center;}}}}
</style>
<section class="sens-block">
  <div class="sens-panel">
    <div class="sens-header">
      <div class="sens-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><polyline points="3 17 8 12 13 15 21 7"/><line x1="3" y1="21" x2="21" y2="21"/><line x1="3" y1="3" x2="3" y2="21"/></svg>
      </div>
      <div class="sens-titles">
        <h2>Analyse de sensibilit&#233;</h2>
        <p class="sens-desc">Chaque courbe montre comment le <strong>TVr</strong> pr&#233;dit &#233;volue lorsqu&#8217;une feature varie, les autres fig&#233;es &#224; <strong>Q1</strong>, <strong>M&#233;diane</strong> et <strong>Q3</strong>. Cliquez sur une feature pour afficher son graphe.</p>
      </div>
    </div>
    <hr class="sens-divider">
    <div class="sens-controls">
      <span class="sens-controls-label">Feature</span>
      <div class="sens-pills" id="sensPills" role="group">
        {pills_html}
      </div>
    </div>
    <div class="sens-legend">
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--q1"></span><span>Q1 &#8212; 25e percentile</span></div>
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--med"></span><span>M&#233;diane &#8212; 50e percentile</span></div>
      <div class="sens-legend-item"><span class="sens-legend-dot sens-legend-dot--q3"></span><span>Q3 &#8212; 75e percentile</span></div>
    </div>
    <div class="sens-chart-wrap">
      {plot_divs_html}
    </div>
  </div>
</section>
<script>
(function() {{
  var pills = document.querySelectorAll("#sensPills .sens-pill");
  pills.forEach(function(pill) {{
    pill.addEventListener("click", function() {{
      var feat = this.getAttribute("data-feat");
      pills.forEach(function(p) {{
        p.classList.remove("sens-pill--active");
        p.setAttribute("aria-pressed", "false");
      }});
      this.classList.add("sens-pill--active");
      this.setAttribute("aria-pressed", "true");
      document.querySelectorAll(".sens-plot-slot").forEach(function(div) {{
        div.style.display = "none";
      }});
      var target = document.getElementById("sens-plot-" + feat);
      if (target) {{
        target.style.display = "block";
        var plotDiv = target.querySelector(".plotly-graph-div");
        if (plotDiv && window.Plotly) {{ window.Plotly.Plots.resize(plotDiv); }}
      }}
    }});
    pill.addEventListener("keydown", function(e) {{
      if (e.key === "Enter" || e.key === " ") {{ e.preventDefault(); this.click(); }}
    }});
  }});
}})();
</script>"""


def _generate_html_report(
    metrics: MetricsResult,
    model_name: str,
    training_config: dict[str, Any] | None,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    df: pd.DataFrame | None = None,
    sensitivity_html: str | None = None,
) -> str:
    """Generate a self-contained HTML evaluation report matching the original Streamlit style.

    Parameters
    ----------
    metrics : MetricsResult
        Pre-computed global metrics (RMSE, MAE, R2, ...).
    model_name : str
        Name of the evaluated model.
    training_config : dict | None
        Training configuration (architecture, input_cols, etc.).
    y_true, y_pred : np.ndarray
        True and predicted values (TxPen or output col).
    df : pd.DataFrame | None
        Full evaluation DataFrame with columns like TMJAFCDTV, TMJABCTV, TVr,
        Tolerance_IN_OUT, Erreur %, GEH, lat, lon, etc.  When provided, the
        report includes the barplot, outlier table and Folium map.
    sensitivity_html : str | None
        Pre-built sensitivity analysis HTML section. When provided, inserted
        after the Folium map section.
    """

    # --- Build stats row (same structure as original rows[]) ---
    if df is not None and "TVr" in df.columns and "TMJABCTV" in df.columns:
        flow_metrics = _compute_flow_metrics(df)
        tol_counts = _compute_tolerance_counts(df)

        err_pct = pd.to_numeric(df.get("Erreur %"), errors="coerce")
        n_total_pct = int(err_pct.notna().sum())
        n_err_lt10 = int((err_pct < 10).sum())
        n_err_lt15 = int((err_pct < 15).sum())
        n_err_lt20 = int((err_pct < 20).sum())

        row = {
            "model": model_name,
            "n": flow_metrics["n"],
            "err_rel_med": flow_metrics["err_rel_med"],
            "err_abs_med": flow_metrics["err_abs_med"],
            "err_rel_p80": flow_metrics["err_rel_p80"],
            "err_abs_p80": flow_metrics["err_abs_p80"],
            "geh_lt5_pct": flow_metrics["geh_lt5_pct"],
            "geh_le10_pct": flow_metrics["geh_le10_pct"],
            "n_err_lt10": n_err_lt10,
            "pct_err_lt10": 100.0 * n_err_lt10 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt15": n_err_lt15,
            "pct_err_lt15": 100.0 * n_err_lt15 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt20": n_err_lt20,
            "pct_err_lt20": 100.0 * n_err_lt20 / n_total_pct if n_total_pct > 0 else float("nan"),
            **tol_counts,
        }
    else:
        # Fallback: compute basic stats from y_true / y_pred arrays
        nonzero = y_true != 0
        if nonzero.any():
            rel_errors = np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero]) * 100
            n_total_pct = len(rel_errors)
            n_err_lt10 = int((rel_errors < 10).sum())
            n_err_lt15 = int((rel_errors < 15).sum())
            n_err_lt20 = int((rel_errors < 20).sum())
        else:
            n_total_pct = 0
            n_err_lt10 = n_err_lt15 = n_err_lt20 = 0

        geh_vals = _geh(y_true, y_pred)
        row = {
            "model": model_name,
            "n": len(y_true),
            "err_rel_med": float(metrics.median_relative_error) if metrics.median_relative_error is not None else float("nan"),
            "err_abs_med": float(metrics.mae),
            "err_rel_p80": float("nan"),
            "err_abs_p80": float("nan"),
            "geh_lt5_pct": float(metrics.geh_pct_below_5),
            "geh_le10_pct": float(np.mean(geh_vals < 10) * 100),
            "n_err_lt10": n_err_lt10,
            "pct_err_lt10": 100.0 * n_err_lt10 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt15": n_err_lt15,
            "pct_err_lt15": 100.0 * n_err_lt15 / n_total_pct if n_total_pct > 0 else float("nan"),
            "n_err_lt20": n_err_lt20,
            "pct_err_lt20": 100.0 * n_err_lt20 / n_total_pct if n_total_pct > 0 else float("nan"),
            "tol_total": 0,
            "tol_in": 0,
            "tol_near": 0,
            "tol_out": 0,
        }

    # --- Card styling helpers ---
    def _card_style(v, good_thresh, mid_thresh, higher_is_better=False):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return ""
        if higher_is_better:
            good = v >= good_thresh
            mid = v >= mid_thresh
        else:
            good = v <= good_thresh
            mid = v <= mid_thresh
        if good:
            return "background:linear-gradient(145deg,#f1fff7,#e6f9ef);border-color:#b8e9cf;"
        if mid:
            return "background:linear-gradient(145deg,#fff9ec,#fff2d9);border-color:#f2ddb0;"
        return "background:linear-gradient(145deg,#fff0f0,#ffe4e4);border-color:#efc0c0;"

    tol_ratio = row["tol_in"] / max(row["tol_total"], 1)
    tol_style = _card_style(tol_ratio, 0.75, 0.60, higher_is_better=True)
    err_style = _card_style(row.get("err_rel_med"), 12.0, 20.0)

    pct10 = row.get("pct_err_lt10", float("nan"))
    pct15 = row.get("pct_err_lt15", float("nan"))
    pct20 = row.get("pct_err_lt20", float("nan"))
    n10 = row.get("n_err_lt10", "-")
    n15 = row.get("n_err_lt15", "-")
    n20 = row.get("n_err_lt20", "-")

    pct10_style = _card_style(pct10, 60.0, 40.0, higher_is_better=True)
    pct15_style = _card_style(pct15, 70.0, 50.0, higher_is_better=True)
    pct20_style = _card_style(pct20, 80.0, 60.0, higher_is_better=True)

    # --- Barplot ---
    if df is not None and "TVr" in df.columns and "TMJABCTV" in df.columns:
        bar_html = _make_barplot_html(df, title=f"{model_name} - validation")
    else:
        bar_html = "<p>Aucune donnee disponible.</p>"

    # --- Folium map ---
    if df is not None and "lat" in df.columns and "lon" in df.columns:
        map_html = _make_folium_map_html(df, model_name)
    else:
        map_html = "<p style='color:#888;font-style:italic;'>Donnees non disponibles pour la carte.</p>"

    # --- Outlier table (Erreur % > 15%) ---
    if df is not None and "Erreur %" in df.columns:
        out_df = df.copy()
        out_df["Erreur %"] = pd.to_numeric(out_df.get("Erreur %"), errors="coerce")
        out_df = out_df[out_df["Erreur %"] > 15].sort_values("Erreur %", ascending=False)
        outlier_cols = [c for c in out_df.columns if c not in ("geometry", "__geometry")]
        if not out_df.empty:
            _oth = "<tr>" + "".join(f"<th>{c}</th>" for c in outlier_cols) + "</tr>"
            _otrows = []
            for _, r in out_df.iterrows():
                err = r.get("Erreur %", float("nan"))
                if isinstance(err, float) and not math.isnan(err) and err > 50:
                    style = ' style="background:#fff0f0;"'
                elif isinstance(err, float) and not math.isnan(err) and err > 30:
                    style = ' style="background:#fff7ec;"'
                else:
                    style = ""
                cells = []
                for c in outlier_cols:
                    v = r.get(c, "-")
                    if isinstance(v, float):
                        v = "-" if (math.isnan(v) or math.isinf(v)) else f"{v:.2f}"
                    cells.append(f"<td>{v}</td>")
                _otrows.append(f"<tr{style}>" + "".join(cells) + "</tr>")
            outlier_html = (
                f'<table id="outlierTable" class="display" style="width:100%">'
                f'<thead>{_oth}</thead>'
                f'<tbody>{"".join(_otrows)}</tbody>'
                f'</table>'
            )
            outlier_count = len(out_df)
        else:
            outlier_html = "<p style='color:#2ecc71;font-weight:600;'>Aucun capteur avec une erreur &gt; 15%.</p>"
            outlier_count = 0
    else:
        outlier_html = "<p style='color:#888;font-style:italic;'>Donnees non disponibles.</p>"
        outlier_count = 0

    # --- Comparison table (single model row, same 18 columns as original) ---
    header_cells = [
        "Modele", "N", "Err.rel med (%)", "Err.abs med",
        "Err.rel p80 (%)", "Err.abs p80", "GEH<5 (%)", "GEH<=10 (%)",
        "Err<10% N", "Err<10% %", "Err<15% N", "Err<15% %", "Err<20% N", "Err<20% %",
        "Tol 1 Inclus", "Tol 2 Hors<15%", "Tol 3 Hors>15%", "Tol Total",
    ]
    thead = "<tr>" + "".join(f"<th>{h}</th>" for h in header_cells) + "</tr>"

    tag = ' <span style="background:#d7f5e8;color:#0a7a4b;border-radius:6px;padding:2px 6px;font-size:11px;">Meilleur</span>'
    cells = [
        f'{_html.escape(row["model"])}{tag}',
        str(row.get("n", "-")),
        _fmt(row.get("err_rel_med")),
        _fmt(row.get("err_abs_med")),
        _fmt(row.get("err_rel_p80")),
        _fmt(row.get("err_abs_p80")),
        _fmt(row.get("geh_lt5_pct")),
        _fmt(row.get("geh_le10_pct")),
        str(row.get("n_err_lt10", "-")),
        _fmt(row.get("pct_err_lt10")),
        str(row.get("n_err_lt15", "-")),
        _fmt(row.get("pct_err_lt15")),
        str(row.get("n_err_lt20", "-")),
        _fmt(row.get("pct_err_lt20")),
        str(row.get("tol_in", "-")),
        str(row.get("tol_near", "-")),
        str(row.get("tol_out", "-")),
        str(row.get("tol_total", "-")),
    ]
    tbody_row = '<tr style="background:#eafaf2;font-weight:700;">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"

    # --- Assemble full HTML ---
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Evaluation - {_html.escape(model_name)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css"/>
  <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
  <style>
    body{{font-family:Manrope,"Segoe UI",Arial,sans-serif;margin:0;background:radial-gradient(circle at 10% 0%,#e7f0ff 0%,#f2f7ff 28%,#ecf3fb 62%,#e8f0f8 100%);color:#122033;}}
    .wrap{{max-width:1600px;margin:0 auto;padding:24px 22px 30px;}}
    h1{{margin:0 0 6px;font-size:28px;font-weight:800;color:#0f2f57;}}
    .subtitle{{color:#56637a;font-size:13px;margin-bottom:16px;}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:18px;}}
    .card{{background:linear-gradient(180deg,#fff,#f9fcff);border-radius:16px;padding:14px;box-shadow:0 10px 22px rgba(13,61,120,.08);border:1px solid #dfe8f3;}}
    .k{{font-size:12px;color:#6b778c;font-weight:600;}}
    .v{{font-size:22px;font-weight:800;margin-top:6px;color:#0d3b66;}}
    .best-tag{{display:inline-block;padding:4px 10px;border-radius:999px;background:#d7f5e8;color:#0a7a4b;font-weight:700;font-size:12px;}}
    .panel{{background:linear-gradient(180deg,#fff,#fbfdff);border:1px solid #dfe7f2;border-radius:16px;padding:14px;box-shadow:0 10px 22px rgba(12,52,103,.07);margin-bottom:16px;overflow-x:auto;}}
    h2{{margin:20px 0 10px;font-size:18px;font-weight:800;}}
    table.dataTable thead th{{background:#f0f6ff;color:#12345a;font-weight:700;}}
    table.dataTable tbody td{{font-size:12px;}}
    table.dataTable tbody tr:hover{{background:#f4f9ff!important;}}
    .plot-wrap{{margin-top:14px;}}
    .hint{{color:#56637a;font-size:12px;margin-top:4px;}}
  </style>
</head>
<body>
<div class="wrap">
  <h1>Evaluation sur donnees de validation</h1>
  <div class="subtitle">Modele : <code>{_html.escape(model_name)}</code> | {row['n']} capteurs</div>

  <div class="cards">
    <div class="card" style="background:linear-gradient(145deg,#eef6ff,#e6f0ff);border-color:#bfd5f3;">
      <div class="k">Modele evalue</div>
      <div class="v" style="font-size:18px;overflow-wrap:anywhere;">{_html.escape(model_name)}</div>
      <div class="best-tag">Tolerance max + erreurs minimisees</div>
    </div>
    <div class="card" style="{tol_style}">
      <div class="k">Capteurs tolerance inclus</div>
      <div class="v">{row['tol_in']}/{row['tol_total']}</div>
    </div>
    <div class="card" style="{err_style}">
      <div class="k">Err. rel. mediane</div>
      <div class="v">{_fmt(row.get('err_rel_med'))}%</div>
    </div>
    <div class="card">
      <div class="k">Err. rel. p80</div>
      <div class="v">{_fmt(row.get('err_rel_p80'))}%</div>
    </div>
    <div class="card">
      <div class="k">GEH &lt; 5</div>
      <div class="v">{_fmt(row.get('geh_lt5_pct'))}%</div>
    </div>
    <div class="card" style="{pct10_style}">
      <div class="k">Capteurs erreur &lt; 10%</div>
      <div class="v">{n10} <small style="font-size:14px;color:#56637a;">({_fmt(pct10)}%)</small></div>
    </div>
    <div class="card" style="{pct15_style}">
      <div class="k">Capteurs erreur &lt; 15%</div>
      <div class="v">{n15} <small style="font-size:14px;color:#56637a;">({_fmt(pct15)}%)</small></div>
    </div>
    <div class="card" style="{pct20_style}">
      <div class="k">Capteurs erreur &lt; 20%</div>
      <div class="v">{n20} <small style="font-size:14px;color:#56637a;">({_fmt(pct20)}%)</small></div>
    </div>
  </div>

  <h2>Tableau des metriques detaillees</h2>
  <p class="hint">Metriques calculees sur les donnees de validation. Tolerance : 1 = inclus, 2 = hors &lt;15% borne, 3 = hors &gt;15% borne.</p>
  <div class="panel">
    <table id="valTable" class="display" style="width:100%">
      <thead>{thead}</thead>
      <tbody>{tbody_row}</tbody>
    </table>
  </div>

  <h2>Barplot - TMJABCTV vs TVr (validation)</h2>
  <div class="panel plot-wrap">
    {bar_html}
  </div>

  <h2>Capteurs avec ecart &gt; 15% ({outlier_count} capteur(s))</h2>
  <p class="hint">Liste triee par erreur decroissante. Fond rose = erreur &gt; 50%, fond orange clair = erreur &gt; 30%.</p>
  <div class="panel">
    {outlier_html}
  </div>

  <h2>Carte des capteurs (validation)</h2>
  <p class="hint">Cliquez sur un capteur pour voir toutes ses informations. Couleur = tolerance (vert = inclus, orange = hors &lt;15%, rouge = hors &gt;15%). Taille = TMJABCTV.</p>
  <div class="panel" style="padding:6px;overflow:hidden;">
    {map_html}
  </div>

  {sensitivity_html if sensitivity_html else ""}

</div>
<script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
<script src="https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"></script>
<script>
$(document).ready(function(){{
  $('#valTable').DataTable({{
    pageLength: 25,
    order: [[14, 'desc'], [2, 'asc'], [4, 'asc']],
  }});
  if ($('#outlierTable').length) {{
    $('#outlierTable').DataTable({{
      pageLength: 25,
      order: [[7, 'desc']],
    }});
  }}
}});
</script>
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


def _read_uploaded_df(session_id: str) -> pd.DataFrame:
    """Get validation DataFrame from session (try multiple keys).

    Works with both MemoryBackend (session.data) and RedisBackend (get_data).
    """
    for key in ("validation_df", "learning_df", "raw_df"):
        try:
            df = session_manager.get_data(session_id, key)
            if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                logger.info("Using '%s' as validation data (%d rows)", key, len(df))
                return df.copy()
        except (KeyError, Exception) as e:
            logger.debug("Key '%s' not found: %s", key, e)
            continue
    raise ValueError("Aucune donnee de validation disponible dans la session.")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/upload-validation")
async def upload_validation(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    column_mapping: str = Form(""),
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
            # Extract lat/lon from Point geometry before dropping
            if "geometry" in df.columns:
                try:
                    points = df["geometry"]
                    if "lat" not in df.columns:
                        df["lat"] = points.y
                    if "lon" not in df.columns:
                        df["lon"] = points.x
                except (AttributeError, ValueError) as exc:
                    logger.warning("Could not derive lat/lon from geometry: %s", exc)
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

    # Apply user-provided column mapping (target -> source)
    if column_mapping:
        try:
            mapping_dict: dict[str, str] = json.loads(column_mapping)
            for target_col, source_col in mapping_dict.items():
                if source_col and source_col in df.columns and target_col not in df.columns:
                    df[target_col] = df[source_col]
                    logger.info("Mapping colonne: %s -> %s", source_col, target_col)
        except (json.JSONDecodeError, TypeError):
            logger.warning("column_mapping invalide, ignore: %s", column_mapping[:100])

    logger.info("Validation columns after renames+mapping: %s", list(df.columns)[:30])
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
        model_json_str = session_manager.get_data(body.session_id, "trained_model_json")
        weights_bytes = session_manager.get_data(body.session_id, "trained_weights")
        session_norm = session_manager.get_data(body.session_id, "norm_params")

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
        df = _read_uploaded_df(body.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Apply user-provided column mapping first (from frontend)
    if body.column_mapping:
        for target_col, source_col in body.column_mapping.items():
            if source_col and source_col in df.columns and target_col not in df.columns:
                df[target_col] = df[source_col]

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

    # Keep the full DataFrame for the report (with all columns like lat, lon, PTM_ID, etc.)
    # but only use rows where input_cols + output_col are non-null for prediction
    all_needed = input_cols + [output_col]
    sub = df.copy()
    sub[all_needed] = sub[all_needed].apply(pd.to_numeric, errors="coerce")
    valid_mask = sub[all_needed].notna().all(axis=1)
    sub = sub[valid_mask].copy()

    if len(sub) < 2:
        raise HTTPException(status_code=400, detail="Trop peu de lignes valides pour l'evaluation.")

    X = sub[input_cols].values.astype(np.float64)
    y_true = sub[output_col].values.astype(np.float64)

    # Normalize and predict
    x_std_safe = np.where(x_std == 0, 1.0, x_std)
    X_norm = (X - x_mean) / x_std_safe
    y_pred_norm = model.predict(X_norm, verbose=0).flatten()
    y_pred = y_pred_norm * y_std + y_mean

    # Compute basic API metrics
    metrics = _compute_metrics(y_true, y_pred, body.high_flow_threshold)

    # --- Build enriched DataFrame for the HTML report ---
    # Add TVr, tolerance, error columns (same logic as evaluate_best_model.py)
    report_df = sub.copy()
    report_df["TP_redressement"] = pd.to_numeric(y_pred, errors="coerce")

    # TVr = TMJAFCDTV / TP_redressement * 100
    tmja_fcd_col = None
    for cand in ("TMJAFCDTV", "TMJATV"):
        if cand in report_df.columns:
            tmja_fcd_col = cand
            break
    if tmja_fcd_col is not None:
        report_df["TVr"] = (
            pd.to_numeric(report_df[tmja_fcd_col], errors="coerce")
            / report_df["TP_redressement"]
            * 100.0
        )
    else:
        # Fallback: treat y_pred directly as TVr
        report_df["TVr"] = pd.to_numeric(y_pred, errors="coerce")

    # Ensure TMJABCTV is numeric
    if "TMJABCTV" in report_df.columns:
        report_df["TMJABCTV"] = pd.to_numeric(report_df["TMJABCTV"], errors="coerce")

    # Erreur absolue & Erreur %
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        report_df["Erreur absolue"] = (report_df["TVr"] - report_df["TMJABCTV"]).abs().round(1)
        denom = report_df["TMJABCTV"].replace([np.inf, -np.inf], np.nan)
        report_df["Erreur %"] = (
            report_df["Erreur absolue"] / denom * 100.0
        ).replace([np.inf, -np.inf], np.nan)
    else:
        report_df["Erreur absolue"] = np.nan
        report_df["Erreur %"] = np.nan

    # GEH
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        a = report_df["TVr"] / 24.0
        b = report_df["TMJABCTV"] / 24.0
        with np.errstate(divide="ignore", invalid="ignore"):
            geh_vals = np.sqrt(2.0 * (a - b) ** 2 / (a + b))
        report_df["GEH"] = pd.to_numeric(geh_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)

    # lat/lon from __lat/__lon if needed
    if "__lat" in report_df.columns and "lat" not in report_df.columns:
        report_df["lat"] = pd.to_numeric(report_df["__lat"], errors="coerce")
    if "__lon" in report_df.columns and "lon" not in report_df.columns:
        report_df["lon"] = pd.to_numeric(report_df["__lon"], errors="coerce")

    # Tolerance columns (TVrmin, TVrmax, Tolerance_IN_OUT)
    if "TVr" in report_df.columns and "TMJABCTV" in report_df.columns:
        report_df = _add_tolerance_columns(report_df)

    # Build sensitivity analysis section
    sensitivity_html = None
    try:
        if model is not None and input_cols:
            mu_x_arr = np.array(x_mean, dtype=np.float64)
            s_x_arr = np.array(x_std, dtype=np.float64)
            mu_y_arr = np.array(y_mean, dtype=np.float64)
            s_y_arr = np.array(y_std, dtype=np.float64)
            sensitivity_html = _build_sensitivity_section_html(
                df=report_df,
                model=model,
                mu_x=mu_x_arr,
                s_x=s_x_arr,
                mu_y=mu_y_arr,
                s_y=s_y_arr,
                input_cols=input_cols,
            )
    except Exception as exc:
        logger.warning("Sensitivity analysis failed (non-blocking): %s", exc)
        sensitivity_html = None

    # Generate HTML report
    report_html = _generate_html_report(
        metrics=metrics,
        model_name=model_name,
        training_config=training_config,
        y_true=y_true,
        y_pred=y_pred,
        df=report_df,
        sensitivity_html=sensitivity_html,
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

    report_html = session_manager.get_data(session_id, "eval_report_html")
    if report_html is None:
        # Fallback: generate a minimal report from stored metrics
        metrics_dict = session_manager.get_data(session_id, "eval_metrics")
        if metrics_dict is None:
            raise HTTPException(status_code=400, detail="Lancez l'evaluation d'abord (/api/evaluation/run).")

        metrics = MetricsResult(**metrics_dict)
        model_name = session_manager.get_data(session_id, "eval_model_name", "modele")
        y_true = np.array(session_manager.get_data(session_id, "eval_y_true", []))
        y_pred = np.array(session_manager.get_data(session_id, "eval_y_pred", []))

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
