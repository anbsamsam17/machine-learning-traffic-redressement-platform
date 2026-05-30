"""HTML report generator — TV models (daily, v/j, TVr vs TMJOBCTV).

This module hosts the TV-flavour Plotly barplot, Folium map and full
``generate_html_report_tv`` builder. Shared display helpers (``_fmt``,
``_label``, calibration / residuals / drift section builders) live in the
package ``__init__`` so PL and HPM/HPS reports reuse them verbatim.

Kept verbatim from the legacy ``apps/api/app/routers/evaluation.py`` body
to preserve byte-for-byte output of the HTML report.
"""

from __future__ import annotations

import base64
import html as _html
import math
from typing import Any

import numpy as np
import pandas as pd

from . import (
    _compute_flow_metrics,
    _compute_tolerance_counts,
    _fmt,
    _geh,
    _label,
    _make_calibration_plot_html,
    _make_drift_by_year_html,
    _make_residuals_by_fc_html,
)

__all__ = [
    "generate_html_report_tv",
    "_make_barplot_html",
    "_make_folium_map_html",
]


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
    hover_lines = "".join(
        f"<b>{_label(c)}</b> : %{{customdata[{i}]}}<br>"
        for i, c in enumerate(hover_cols)
    )
    hover_template = hover_lines + "<extra></extra>"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=d["TMJABCTV"].tolist(),
        name=f"{_label('TMJABCTV')} (validation)", marker_color="#1f77b4",
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

    # Tolerance_IN_OUT may be missing entirely for the new FCD HERE schema.
    # `.get()` returns None when absent; coerce to an empty numeric Series so
    # downstream `.notna()` / mask operations stay vectorised.
    tol_raw = valid.get("Tolerance_IN_OUT")
    if tol_raw is None:
        tol = pd.Series([np.nan] * len(valid), index=valid.index)
    else:
        tol = pd.to_numeric(tol_raw, errors="coerce")
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

    # Reference flow column name varies with the schema (Bordeaux: TMJABCTV,
    # Lyon: TMJOBCTV). Try both, then any column starting with TMJ as last fallback.
    ref_col_candidates = ["TMJOBCTV", "TMJABCTV"]
    s_raw = None
    for c in ref_col_candidates:
        if c in valid.columns:
            s_raw = valid[c]
            break
    if s_raw is None:
        s = pd.Series([np.nan] * len(valid), index=valid.index)
    else:
        s = pd.to_numeric(s_raw, errors="coerce")
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
            lines.append(f"<b>{_label(c)}</b> : {v}")
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
      <div style="margin-top:6px;font-size:11px;color:#666;">Total: {n_valid} | Rayon ~ TMJOBCTV</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    map_full_html = m.get_root().render()
    # Use base64 srcdoc to avoid quote-escaping issues that break the HTML
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


def generate_html_report_tv(
    metrics,
    model_name: str,
    training_config: dict[str, Any] | None,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    df: pd.DataFrame | None = None,
    sensitivity_html: str | None = None,
    metrics_ci95: dict[str, list[float] | None] | None = None,
    metrics_by_tmja_bucket: list[dict[str, Any]] | None = None,
    calibration_data: dict[str, Any] | None = None,
    residuals_by_fc: list[dict[str, Any]] | None = None,
    drift_by_year: list[dict[str, Any]] | None = None,
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
    metrics_ci95 : dict | None
        Bootstrap CI95 intervals (P1.1) keyed by ``tol_in_pct`` / ``p80`` /
        ``r2``. Each value is ``[ci_low, ci_high]`` or ``None`` when skipped.
    calibration_data : dict | None
        P4.1 — {"obs": [...], "pred": [...], "n": int} for the predicted
        vs observed scatter. None falls back to an empty-state message.
    residuals_by_fc : list[dict] | None
        P4.2 — per-functional-class residual summaries. Empty list falls
        back to an empty-state message.
    drift_by_year : list[dict] | None
        P4.3 — per-year metrics rows. Empty list falls back to an
        empty-state message.
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

    # P1.1 - CI95 helper for inline display next to metric values
    def _ci_span(key: str, digits: int = 2, suffix: str = "") -> str:
        if not metrics_ci95:
            return ""
        ci = metrics_ci95.get(key)
        if not ci or len(ci) != 2:
            return ""
        lo, hi = ci
        if lo is None or hi is None:
            return ""
        return (
            f' <small style="font-size:11px;color:#56637a;font-weight:600;">'
            f'(CI95 [{lo:.{digits}f}{suffix}, {hi:.{digits}f}{suffix}])</small>'
        )

    tol_in_pct_val = (100.0 * row["tol_in"] / row["tol_total"]) if row.get("tol_total") else float("nan")
    r2_val = metrics.r_squared

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

    # --- P1.2 Stratification table per TMJOBCTV bucket ---
    if metrics_by_tmja_bucket:
        _bucket_headers = [
            "Bucket TMJOBCTV", "N", "Tol. inclus (N)", "Tol. inclus (%)",
            "p80 err.rel (%)", "R&sup2;",
        ]
        _bucket_thead = (
            "<tr>" + "".join(f"<th>{h}</th>" for h in _bucket_headers) + "</tr>"
        )
        _bucket_rows: list[str] = []
        for _b in metrics_by_tmja_bucket:
            _warn = bool(_b.get("low_sample_warning"))
            _row_style = (
                ' style="background:#fff7ec;"' if _warn else ""
            )
            _label_cell = _html.escape(str(_b.get("bucket", "-")))
            if _warn:
                _label_cell += (
                    ' <small style="color:#b97a00;font-weight:600;" '
                    'title="Moins de 10 echantillons — fiabilite limitee.">'
                    '(n&lt;10)</small>'
                )
            _bucket_rows.append(
                f"<tr{_row_style}>"
                f"<td>{_label_cell}</td>"
                f"<td>{int(_b.get('n_samples', 0))}</td>"
                f"<td>{int(_b.get('tol_in_n', 0))}</td>"
                f"<td>{_fmt(_b.get('tol_in_pct'))}</td>"
                f"<td>{_fmt(_b.get('p80'))}</td>"
                f"<td>{_fmt(_b.get('r2'), digits=4)}</td>"
                f"</tr>"
            )
        bucket_table_html = (
            '  <h2>Metriques stratifiees par tranche de TMJOBCTV</h2>\n'
            '  <p class="hint">Memes metriques recalculees sur 4 buckets de '
            'volume de trafic observe. Permet de detecter un modele performant '
            'globalement mais defaillant sur les capteurs faible/forte densite. '
            'Une ligne sur fond orange indique moins de 10 echantillons '
            '(metriques peu fiables).</p>\n'
            '  <div class="panel">\n'
            '    <table id="tmjaBucketTable" class="display" style="width:100%">\n'
            f'      <thead>{_bucket_thead}</thead>\n'
            f'      <tbody>{"".join(_bucket_rows)}</tbody>\n'
            '    </table>\n'
            '  </div>\n'
        )
    else:
        bucket_table_html = (
            '  <h2>Metriques stratifiees par tranche de TMJOBCTV</h2>\n'
            '  <p class="hint" style="color:#888;font-style:italic;">'
            'Stratification indisponible : colonne TMJOBCTV (ou TMJABCTV) '
            'absente des donnees de validation.</p>\n'
        )

    # --- P4.1 Calibration plot ---
    calibration_plot_inner = _make_calibration_plot_html(calibration_data)
    calibration_section_html = (
        '  <h2>Calibration : predit vs observe</h2>\n'
        '  <p class="hint">Chaque point est un capteur. La diagonale rouge '
        '<code>y = x</code> represente une prediction parfaite. Un nuage '
        'systematiquement en dessous (resp. au-dessus) indique un biais de '
        'sous-estimation (resp. sur-estimation).</p>\n'
        '  <div class="panel plot-wrap">\n'
        f'    {calibration_plot_inner}\n'
        '  </div>\n'
    )

    # --- P4.2 Residual boxplot by functional_class ---
    residuals_plot_inner = _make_residuals_by_fc_html(residuals_by_fc)
    residuals_section_html = (
        '  <h2>Residus par classe fonctionnelle</h2>\n'
        '  <p class="hint">Distribution des residus <code>pred &minus; obs</code> '
        'pour chaque classe fonctionnelle (FC). Une boite centree sur 0 indique '
        'un modele non biaise sur cette classe ; une boite decalee revele un '
        'biais systematique propre a la classe.</p>\n'
        '  <div class="panel plot-wrap">\n'
        f'    {residuals_plot_inner}\n'
        '  </div>\n'
    )

    # --- P4.3 Drift by year ---
    drift_inner = _make_drift_by_year_html(drift_by_year)
    drift_section_html = (
        '  <h2>Derive annuelle (metriques par annee)</h2>\n'
        '  <p class="hint">Memes metriques recalculees pour chaque annee '
        'presente dans le jeu de validation (au moins 10 echantillons). Une '
        'forte variation du R&sup2; ou du tol_in entre annees suggere une '
        'derive temporelle du modele.</p>\n'
        '  <div class="panel">\n'
        f'    {drift_inner}\n'
        '  </div>\n'
    )

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
      <div class="v">{row['tol_in']}/{row['tol_total']} <small style="font-size:13px;color:#56637a;">({_fmt(tol_in_pct_val)}%)</small>{_ci_span('tol_in_pct', digits=2, suffix='%')}</div>
    </div>
    <div class="card" style="{err_style}">
      <div class="k">Err. rel. mediane</div>
      <div class="v">{_fmt(row.get('err_rel_med'))}%</div>
    </div>
    <div class="card">
      <div class="k">Err. rel. p80</div>
      <div class="v">{_fmt(row.get('err_rel_p80'))}%{_ci_span('p80', digits=2, suffix='%')}</div>
    </div>
    <div class="card">
      <div class="k">R&sup2;</div>
      <div class="v">{_fmt(r2_val, digits=4)}{_ci_span('r2', digits=4)}</div>
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

{bucket_table_html}
{calibration_section_html}
{residuals_section_html}
{drift_section_html}
  <h2>Barplot - TMJOBCTV vs TVr (validation)</h2>
  <div class="panel plot-wrap">
    {bar_html}
  </div>

  <h2>Capteurs avec ecart &gt; 15% ({outlier_count} capteur(s))</h2>
  <p class="hint">Liste triee par erreur decroissante. Fond rose = erreur &gt; 50%, fond orange clair = erreur &gt; 30%.</p>
  <div class="panel">
    {outlier_html}
  </div>

  <h2>Carte des capteurs (validation)</h2>
  <p class="hint">Cliquez sur un capteur pour voir toutes ses informations. Couleur = tolerance (vert = inclus, orange = hors &lt;15%, rouge = hors &gt;15%). Taille = TMJOBCTV.</p>
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
  if ($('#tmjaBucketTable').length) {{
    // 4 buckets total — no pagination / search / info needed.
    $('#tmjaBucketTable').DataTable({{
      paging: false,
      searching: false,
      info: false,
      ordering: false,
    }});
  }}
  if ($('#driftByYearTable').length) {{
    // Up to 7 rows — no pagination / search / info needed; allow sorting.
    $('#driftByYearTable').DataTable({{
      paging: false,
      searching: false,
      info: false,
      order: [[0, 'asc']],
    }});
  }}
}});
</script>
</body>
</html>"""
    return html
