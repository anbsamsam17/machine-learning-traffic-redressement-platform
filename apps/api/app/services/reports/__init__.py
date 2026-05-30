"""HTML report generators for the evaluation pipeline.

Three flavours of self-contained HTML reports are produced from a single
``MetricsResult`` + enriched DataFrame:

* :func:`generate_html_report_tv` — TV (daily v/j) report.
* :func:`generate_html_report_pl` — PL (daily v/j, Poids Lourds) report.
* :func:`generate_html_report_peak` — HPM / HPS (hourly v/h) report.

Common display helpers (label translation between the legacy Bordeaux
schema and the FCD HERE schema, numeric formatting, calibration / residuals
/ drift plot fragments, tolerance + flow metric wrappers) live in this
module so all three generators can share them.

Public exports keep the original ``_generate_html_report*`` names available
under their new (snake_case) aliases for ease of grep across the codebase.
"""

from __future__ import annotations

import html as _html
import logging
import math
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Display-label mapping: the dataframe still stores legacy Bordeaux column
# names internally (TMJABCTV / TMJAFCDTV / TxPenTVRef) because val_renames
# aliases the FCD HERE schema onto them, but every label shown to the user
# in the HTML report must use the modern FCD HERE names.
# ---------------------------------------------------------------------------
_DISPLAY_LABELS: dict[str, str] = {
    "TMJABCTV": "TMJOBCTV",
    "TMJABCPL": "TMJOBCPL",
    "TMJAFCDTV": "TMJOFCDTV",
    "TMJAFCDPL": "TMJOFCDPL",
    "TxPenTVRef": "TxPen",
    "TxPenPLRef": "TxPenPL",
}


def _label(col: str) -> str:
    """Return the user-facing label for a (possibly legacy) column name."""
    return _DISPLAY_LABELS.get(col, col)


def _fmt(v, digits=2) -> str:
    """Format a numeric value for display, handling NaN/Inf."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "-"
    return f"{v:.{digits}f}"


# ---------------------------------------------------------------------------
# Thin wrappers around services.ml.evaluation_pipeline (TV / PL flow metrics
# and tolerance helpers). Kept as zero-arg-defaulted callables for back-compat
# with the original evaluation.py call sites.
# ---------------------------------------------------------------------------

def _add_tolerance_columns(df: pd.DataFrame, type_config: Any = None) -> pd.DataFrame:
    """Compute tolerance band columns + Tolerance_IN_OUT.

    When ``type_config`` is None, defaults to TV_CONFIG (back-compat for the
    TV-only call sites that pre-date the PL report). Pass ``PL_CONFIG`` to
    operate on ``DPL`` / ``TMJOBCPL`` instead of ``TVr`` / ``TMJOBCTV``.
    Delegates to the unified service implementation (B3).
    """
    from ..ml.evaluation_pipeline import add_tolerance_columns
    from ..ml.types import TV_CONFIG
    if type_config is None:
        type_config = TV_CONFIG
    return add_tolerance_columns(df, type_config)


def _compute_flow_metrics(df: pd.DataFrame, type_config: Any = None) -> dict:
    """Compute flow metrics — delegates to service.evaluation_pipeline (B3).

    When ``type_config`` is None, defaults to TV_CONFIG (back-compat). Pass
    ``PL_CONFIG`` to compute the same metrics from the PL columns (DPL /
    TMJOBCPL).
    """
    from ..ml.evaluation_pipeline import compute_flow_metrics
    from ..ml.types import TV_CONFIG
    if type_config is None:
        type_config = TV_CONFIG
    return compute_flow_metrics(df, type_config)


def _compute_tolerance_counts(df: pd.DataFrame) -> dict:
    """Count Tolerance_IN_OUT — delegates to service.evaluation_pipeline (B3)."""
    from ..ml.evaluation_pipeline import compute_tolerance_counts
    return compute_tolerance_counts(df)


# ---------------------------------------------------------------------------
# Shared GEH helper — kept in sync with the evaluation router so daily
# (TV/PL) reports compute GEH on hourly-converted volumes.
# ---------------------------------------------------------------------------

def _geh(observed: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """GEH statistic (traffic engineering).

    Inputs are TMJA (volumes journaliers) — converted to hourly (/24) before
    applying the standard GEH formula `sqrt(2*(M-C)**2/(M+C))`. Matches the
    implementation in services/ml/evaluation_pipeline.py.
    """
    obs_h = observed / 24.0
    pred_h = predicted / 24.0
    denom = (obs_h + pred_h) / 2.0
    denom = np.where(denom == 0, 1e-9, denom)
    return np.sqrt((obs_h - pred_h) ** 2 / denom)


# ---------------------------------------------------------------------------
# Generic plot fragments shared by all three report flavours (TV / PL / Peak).
# Each one renders a self-contained <p>...<figure>... HTML snippet so the
# parent report only has to embed the string and add a heading.
# ---------------------------------------------------------------------------

def _make_calibration_plot_html(
    calibration_data: dict[str, Any] | None,
) -> str:
    """Render the P4.1 calibration scatter (pred vs obs) + y=x reference.

    Returns an empty-state ``<p>`` when ``calibration_data`` is None or empty.
    """
    if not calibration_data:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; vecteurs obs/pred vides.</p>'
        )
    obs = calibration_data.get("obs") or []
    pred = calibration_data.get("pred") or []
    if not obs or not pred:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; vecteurs obs/pred vides.</p>'
        )

    import plotly.graph_objects as go
    import plotly.io as pio

    obs_arr = np.asarray(obs, dtype=np.float64)
    pred_arr = np.asarray(pred, dtype=np.float64)
    finite = np.isfinite(obs_arr) & np.isfinite(pred_arr)
    if not finite.any():
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; aucune paire (obs, pred) finie.</p>'
        )
    obs_arr = obs_arr[finite]
    pred_arr = pred_arr[finite]

    lo = float(min(obs_arr.min(), pred_arr.min()))
    hi = float(max(obs_arr.max(), pred_arr.max()))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=obs_arr.tolist(),
        y=pred_arr.tolist(),
        mode="markers",
        name="Capteurs",
        marker=dict(
            size=6,
            color="#0057b7",
            opacity=0.55,
            line=dict(width=0),
        ),
        hovertemplate=(
            "<b>Observe</b> : %{x:.2f}<br>"
            "<b>Predit</b> : %{y:.2f}<extra></extra>"
        ),
    ))
    fig.add_trace(go.Scatter(
        x=[lo, hi],
        y=[lo, hi],
        mode="lines",
        name="y = x (parfait)",
        line=dict(color="#e74c3c", width=2, dash="dash"),
        hoverinfo="skip",
    ))
    n_full = int(calibration_data.get("n", len(obs_arr)))
    n_plotted = int(calibration_data.get("n_plotted", len(obs_arr)))
    subtitle = ""
    if n_plotted < n_full:
        subtitle = f" (echantillon {n_plotted} sur {n_full})"
    fig.update_layout(
        template="plotly_white",
        title=f"Calibration : predit vs observe{subtitle}",
        xaxis_title="Observe (y_true)",
        yaxis_title="Predit (y_pred)",
        margin=dict(l=50, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _make_residuals_by_fc_html(
    residuals_by_fc: list[dict[str, Any]] | None,
) -> str:
    """Render the P4.2 residual boxplot grouped by functional_class."""
    if not residuals_by_fc:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; colonne <code>functional_class</code> '
            '(ou one-hot <code>fc_1..fc_5</code>) absente du jeu de validation.</p>'
        )

    import plotly.graph_objects as go
    import plotly.io as pio

    fig = go.Figure()
    palette = ["#0057b7", "#1a80e8", "#16a085", "#f39c12", "#e74c3c", "#6c5ce7", "#444"]
    for i, entry in enumerate(residuals_by_fc):
        fc = entry.get("fc", "?")
        residuals = entry.get("residuals") or []
        if not residuals:
            continue
        fig.add_trace(go.Box(
            y=residuals,
            name=f"FC {fc}",
            marker_color=palette[i % len(palette)],
            boxmean=True,
            hovertemplate=(
                f"<b>Classe fonctionnelle</b> : {fc}<br>"
                "<b>Residu</b> : %{y:.4f}<extra></extra>"
            ),
        ))
    if not fig.data:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; aucun residu calculable par classe.</p>'
        )
    fig.add_shape(
        type="line", xref="paper", yref="y",
        x0=0, x1=1, y0=0, y1=0,
        line=dict(color="#999", width=1, dash="dot"),
    )
    fig.update_layout(
        template="plotly_white",
        title="Residus par classe fonctionnelle",
        xaxis_title="Classe fonctionnelle",
        yaxis_title="Residu (pred &minus; obs)",
        showlegend=False,
        margin=dict(l=50, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _make_drift_by_year_html(
    drift_by_year: list[dict[str, Any]] | None,
) -> str:
    """Render the P4.3 annual drift table."""
    if not drift_by_year:
        return (
            '<p style="color:#888;font-style:italic;">'
            'Donnees indisponibles &mdash; colonne <code>year_mapped</code> absente '
            'ou aucune annee n a au moins 10 echantillons.</p>'
        )
    headers = [
        "Annee", "N", "R&sup2;", "MAE", "Tol. inclus (%)", "p80 err.rel (%)",
    ]
    thead = "<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>"
    rows: list[str] = []
    for entry in drift_by_year:
        label = _html.escape(str(entry.get("year_label", "-")))
        ym = entry.get("year_mapped")
        if ym is not None:
            label += (
                f' <small style="color:#56637a;font-weight:500;">'
                f'(year_mapped={ym})</small>'
            )
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{int(entry.get('n_samples', 0))}</td>"
            f"<td>{_fmt(entry.get('r2'), digits=4)}</td>"
            f"<td>{_fmt(entry.get('mae'))}</td>"
            f"<td>{_fmt(entry.get('tol_in_pct'))}</td>"
            f"<td>{_fmt(entry.get('p80'))}</td>"
            "</tr>"
        )
    return (
        '<table id="driftByYearTable" class="display" style="width:100%">'
        f'<thead>{thead}</thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        '</table>'
    )


# ---------------------------------------------------------------------------
# Sensitivity-analysis section (TV / PL — daily v/j scale).
# HPM / HPS use a kind-specific variant living in ``html_peak``.
# ---------------------------------------------------------------------------

def _build_sensitivity_section_html(
    df: pd.DataFrame,
    model: Any,
    mu_x: np.ndarray,
    s_x: np.ndarray,
    mu_y: np.ndarray,
    s_y: np.ndarray,
    input_cols: list[str],
    num_points: int = 60,
    type_config: Any = None,
) -> str:
    """Build sensitivity analysis HTML section.

    For each input feature, varies it from min to max (num_points steps) while
    fixing other features at Q1, Median, Q3 baselines. Predicts the target via
    the model, denormalises, and computes the eval-predicted column:
      - TV : TVr = TMJOFCDTV / TxPen * 100
      - PL : DPL = TMJOFCDPL / TxPenPL * 100

    ``type_config`` defaults to TV_CONFIG (back-compat for callers that have
    not been updated yet). Pass ``PL_CONFIG`` to render the DPL sensitivity
    curves on PL models — without this, the chart wrongly showed TVr on a
    PL model because the numerator fallback hard-coded TMJOFCDTV.
    """
    import plotly.graph_objects as go
    import plotly.io as pio
    from ..ml.types import TV_CONFIG
    if type_config is None:
        type_config = TV_CONFIG
    _pred_label = type_config.eval_predicted_col              # "TVr" or "DPL"
    _numerator_main = type_config.eval_numerator_fcd          # "TMJOFCDTV" or "TMJOFCDPL"
    # Candidates that may appear in input_cols on legacy schemas; first match wins.
    _numerator_candidates = [_numerator_main]
    if _pred_label == "TVr":
        _numerator_candidates += ["TMJAFCDTV", "TMJATV"]
    else:
        _numerator_candidates += ["TMJAFCDPL", "TMJAPL"]

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

    # Determine numerator column for the eval-predicted denormalisation
    # (TVr = TMJOFCDTV / TxPen * 100, or DPL = TMJOFCDPL / TxPenPL * 100).
    # The candidate list comes from type_config above so the chart matches
    # the model type — TV models pick TMJOFCDTV first, PL models TMJOFCDPL.
    _numerator_col: str | None = None
    for _cand in _numerator_candidates:
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

                pred_y = np.where(txpen > 0, numerator / txpen * 100.0, np.nan)
                pred_y = np.where(np.isfinite(pred_y), pred_y, np.nan)

            # Build hover text
            other_feats = [c for c in input_cols if c != feat]
            hover_lines = [
                f"<b>{feat}</b> : %{{x:.2f}}<br>",
                f"<b>{_pred_label}</b> : %{{y:.1f}}<br>",
                f"<i>Autres features fig&#233;es &#224; {bl_label} :</i><br>",
            ] + [
                f"&nbsp;&nbsp;{c} = {q_vec[c]:.2f}<br>"
                for c in other_feats
            ]
            hover_tmpl = "".join(hover_lines) + "<extra></extra>"

            fig.add_trace(go.Scatter(
                x=x_vals.tolist(),
                y=pred_y.tolist(),
                mode="lines",
                name=bl_label,
                line=dict(color=_COLORS[bl_label], dash=_DASHES[bl_label], width=2),
                hovertemplate=hover_tmpl,
            ))

        fig.update_layout(
            title=f"{_pred_label} ~ {feat}",
            xaxis_title=feat,
            yaxis_title=f"{_pred_label} (v&#233;h/jour)",
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
        <p class="sens-desc">Chaque courbe montre comment le <strong>{_pred_label}</strong> pr&#233;dit &#233;volue lorsqu&#8217;une feature varie, les autres fig&#233;es &#224; <strong>Q1</strong>, <strong>M&#233;diane</strong> et <strong>Q3</strong>. Cliquez sur une feature pour afficher son graphe.</p>
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


# ---------------------------------------------------------------------------
# Public exports — re-bind the three generators under their snake_case names.
# Importing here is deferred so each submodule stays optional at import time.
# ---------------------------------------------------------------------------

def generate_html_report_tv(*args, **kwargs) -> str:
    """Self-contained HTML evaluation report for TV models (daily, v/j)."""
    from .html_tv import generate_html_report_tv as _impl
    return _impl(*args, **kwargs)


def generate_html_report_pl(*args, **kwargs) -> str:
    """Self-contained HTML evaluation report for PL (Poids Lourds) models."""
    from .html_pl import generate_html_report_pl as _impl
    return _impl(*args, **kwargs)


def generate_html_report_peak(*args, **kwargs) -> str:
    """Self-contained HTML evaluation report for HPM / HPS peak-hour models."""
    from .html_peak import generate_html_report_peak as _impl
    return _impl(*args, **kwargs)


__all__ = [
    "generate_html_report_tv",
    "generate_html_report_pl",
    "generate_html_report_peak",
    "_DISPLAY_LABELS",
    "_label",
    "_fmt",
    "_geh",
    "_add_tolerance_columns",
    "_compute_flow_metrics",
    "_compute_tolerance_counts",
    "_make_calibration_plot_html",
    "_make_residuals_by_fc_html",
    "_make_drift_by_year_html",
    "_build_sensitivity_section_html",
]
