"""HTML report generator — HPM / HPS peak-hour models (hourly, v/h).

Convention CEREMA Grand Lyon :

* HPM = heure de pointe matin (h08-h09, 8h00-8h59), unite v/h.
* HPS = heure de pointe soir  (h17-h18, 17h00-17h59), unite v/h.

Reference compteur : ``TMJOBCTV_HPM`` / ``TMJOBCTV_HPS``.
Predit             : ``HPM_FCDr`` / ``HPS_FCDr`` (jamais ``TVr`` — c'est le daily TV).

Pas de variante PL pour ces kinds (couverture insuffisante des flottes PL).

The :func:`generate_html_report_peak` builder is parametrised by a
``ModelTypeConfig`` (HPM_CONFIG or HPS_CONFIG) so the same code generates
both reports — only label / columns / unit differ. The thin aliases
``_generate_html_report_HPM`` / ``_generate_html_report_HPS`` from the
original router still resolve to this function.
"""

from __future__ import annotations

import base64
import html as _html
import math
from typing import Any

import numpy as np
import pandas as pd

from . import (
    _compute_tolerance_counts,
    _fmt,
    _make_calibration_plot_html,
    _make_drift_by_year_html,
    _make_residuals_by_fc_html,
)

__all__ = [
    "generate_html_report_peak",
    "_add_tolerance_columns_HPM_HPS",
    "_compute_flow_metrics_HPM_HPS",
    "_make_barplot_html_HPM_HPS",
    "_make_distribution_barplot_html_HPM_HPS",
    "_make_folium_map_html_HPM_HPS",
    "_build_sensitivity_section_html_HPM_HPS",
    "_HPM_HPS_TOL_BINS",
    "_HPM_HPS_BARPLOT_BINS_VH",
]


# Tolerance bins en v/h (recalibres pour la pointe horaire — les tranches
# v/j 0-1000/1000-2000/... ne s'appliquent PAS aux donnees horaires).
# Validation visuelle attendue sur dataset Lyon en aval ; baseline raisonnable.
_HPM_HPS_TOL_BINS: list[tuple[float, float, float]] = [
    (0.0, 100.0, 0.25),  # zones calmes
    (100.0, 300.0, 0.18),
    (300.0, 600.0, 0.18),
    (600.0, 1200.0, 0.14),  # axes structurants
    (1200.0, float("inf"), 0.14),  # autoroutes / peri en pointe
]

# Bornes du barplot par tranche v/h pour la repartition (cf. spec : 0/50/100/200/400/800/1500/3000).
_HPM_HPS_BARPLOT_BINS_VH: list[float] = [0.0, 50.0, 100.0, 200.0, 400.0, 800.0, 1500.0, 3000.0]


def _add_tolerance_columns_HPM_HPS(
    df: pd.DataFrame,
    type_config: Any,
) -> pd.DataFrame:
    """HPM/HPS dynamic tolerance bands — recalibrated for v/h scale.

    Mirrors ``add_tolerance_columns`` (TV/PL) but uses the v/h tranches from
    ``_HPM_HPS_TOL_BINS`` so a 60 v/h prediction doesn't get the 25%
    tolerance that was tuned for daily TV (where 60 v/j is noise).
    """
    out = df.copy()
    pred_col = type_config.eval_predicted_col  # HPM_FCDr / HPS_FCDr
    ref_col = type_config.eval_reference_col  # TMJOBCTV_HPM / TMJOBCTV_HPS

    out[pred_col] = pd.to_numeric(out[pred_col], errors="coerce")

    def erreur_pourcentage(val: float) -> float:
        if pd.isna(val):
            return np.nan
        for lo, hi, tol in _HPM_HPS_TOL_BINS:
            if lo <= val < hi:
                return tol
        return _HPM_HPS_TOL_BINS[-1][2]

    out["Erreur_dyn"] = out[pred_col].apply(erreur_pourcentage)
    min_col = f"{pred_col}min"
    max_col = f"{pred_col}max"
    out[min_col] = out[pred_col] * (1 - out["Erreur_dyn"])
    out[max_col] = out[pred_col] * (1 + out["Erreur_dyn"])

    # Arrondis v/h-friendly : pas de palier 10000 (irrealiste en pointe horaire).
    # Sous 100 v/h on arrondit au 5 ; entre 100 et 500 au 10 ; >=500 au 50.
    mask_low = out[pred_col] < 100
    out.loc[mask_low, min_col] = 5 * np.floor(out.loc[mask_low, min_col] / 5)
    out.loc[mask_low, max_col] = 5 * np.ceil(out.loc[mask_low, max_col] / 5)

    mask_mid = (out[pred_col] >= 100) & (out[pred_col] < 500)
    out.loc[mask_mid, min_col] = 10 * np.floor(out.loc[mask_mid, min_col] / 10)
    out.loc[mask_mid, max_col] = 10 * np.ceil(out.loc[mask_mid, max_col] / 10)

    mask_hi = out[pred_col] >= 500
    out.loc[mask_hi, min_col] = 50 * np.floor(out.loc[mask_hi, min_col] / 50)
    out.loc[mask_hi, max_col] = 50 * np.ceil(out.loc[mask_hi, max_col] / 50)

    # Bornes <0 -> clamp.
    out.loc[out[min_col].notna() & (out[min_col] < 0), min_col] = 0

    for c in [ref_col, min_col, max_col]:
        out[c] = pd.to_numeric(out[c], errors="coerce")

    tmja = out[ref_col]
    lower = np.minimum(out[min_col], out[max_col])
    upper = np.maximum(out[min_col], out[max_col])

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


def _compute_flow_metrics_HPM_HPS(
    df: pd.DataFrame,
    type_config: Any,
) -> dict:
    """Same shape as compute_flow_metrics (TV/PL) but reads HPM_FCDr / HPS_FCDr
    against TMJOBCTV_HPM / TMJOBCTV_HPS. GEH uses the raw hourly volumes (no
    /24 conversion since they are already hourly — the universal GEH formula
    ``sqrt(2*(M-C)**2/(M+C))`` applies as-is).
    """
    d = df.copy()
    pred_col = type_config.eval_predicted_col
    ref_col = type_config.eval_reference_col

    d[pred_col] = pd.to_numeric(d.get(pred_col), errors="coerce")
    d[ref_col] = pd.to_numeric(d.get(ref_col), errors="coerce")
    d["GEH"] = pd.to_numeric(d.get("GEH"), errors="coerce")
    d = d.dropna(subset=[ref_col, pred_col])

    if d.empty:
        return {
            "n": 0,
            "err_rel_med": np.nan,
            "err_abs_med": np.nan,
            "err_rel_p80": np.nan,
            "err_abs_p80": np.nan,
            "geh_lt5_pct": np.nan,
            "geh_le10_pct": np.nan,
        }

    err_abs = (d[pred_col] - d[ref_col]).abs().astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        err_rel = np.where(d[ref_col] != 0, err_abs / d[ref_col] * 100.0, np.nan)
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


def _make_barplot_html_HPM_HPS(
    df: pd.DataFrame,
    title: str,
    type_config: Any,
) -> str:
    """Grouped bar chart REF vs PRED for HPM/HPS (echelle v/h).

    Reference = TMJOBCTV_HPM / TMJOBCTV_HPS (compteur reel).
    Predit    = HPM_FCDr / HPS_FCDr (sortie modele).
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    pred_col = type_config.eval_predicted_col
    ref_col = type_config.eval_reference_col
    unit = type_config.unit_label  # "v/h"

    d = df.copy()
    d[ref_col] = pd.to_numeric(d.get(ref_col), errors="coerce")
    d[pred_col] = pd.to_numeric(d.get(pred_col), errors="coerce")
    d = d.dropna(subset=[ref_col, pred_col])
    if d.empty:
        return f"<p>Aucune donnee ({title})</p>"

    n_sample = min(200, len(d))
    d = d.sample(n=n_sample, random_state=42).reset_index(drop=True)

    labels = (
        d["PTM_ID"].astype(str).tolist()
        if "PTM_ID" in d.columns
        else [str(i) for i in range(len(d))]
    )

    hover_cols = [
        c
        for c in [
            "PTM_ID",
            "Identifiant",
            "STA",
            "Type",
            "Commune",
            "Route",
            type_config.fcd_col,
            "TMJOFCDPL",
            "avg_speed_kmh",
            "avg_distance_m",
            "truck_avg_speed_kmh",
            "truck_avg_min_distance_m",
            ref_col,
            pred_col,
            "TP_redressement",
            "Erreur %",
            "Erreur absolue",
            "GEH",
            f"{pred_col}min",
            f"{pred_col}max",
            "Tolerance_IN_OUT",
        ]
        if c in d.columns
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
        f"<b>{c}</b> : %{{customdata[{i}]}}<br>" for i, c in enumerate(hover_cols)
    )
    hover_template = hover_lines + "<extra></extra>"

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=d[ref_col].tolist(),
            name=f"{ref_col} (validation)",
            marker_color="#1f77b4",
            customdata=customdata,
            hovertemplate=hover_template,
        )
    )
    fig.add_trace(
        go.Bar(
            x=labels,
            y=d[pred_col].tolist(),
            name=f"{pred_col} (predit)",
            marker_color="#00b894",
            customdata=customdata,
            hovertemplate=hover_template,
        )
    )
    fig.update_layout(
        barmode="group",
        template="plotly_white",
        title=title,
        xaxis_title="Capteurs",
        yaxis_title=f"Debit ({unit})",  # v/h (jamais v/j)
        margin=dict(l=40, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs="cdn", full_html=False)


def _make_distribution_barplot_html_HPM_HPS(
    df: pd.DataFrame,
    type_config: Any,
) -> str:
    """Histogramme de repartition des capteurs par tranche de debit (v/h).

    Bornes : ``_HPM_HPS_BARPLOT_BINS_VH`` (0/50/100/200/400/800/1500/3000).
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    ref_col = type_config.eval_reference_col
    unit = type_config.unit_label

    if ref_col not in df.columns:
        return "<p>Aucune donnee de repartition.</p>"
    vals = pd.to_numeric(df[ref_col], errors="coerce").dropna().to_numpy()
    if vals.size == 0:
        return "<p>Aucune donnee de repartition.</p>"

    bins = _HPM_HPS_BARPLOT_BINS_VH
    edges = bins + [float(np.nanmax(vals)) + 1.0] if vals.max() > bins[-1] else bins
    counts, _ = np.histogram(vals, bins=edges)
    labels = [f"{int(edges[i])}-{int(edges[i+1])}" for i in range(len(edges) - 1)]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=labels,
            y=counts.tolist(),
            marker_color="#0057b7",
            hovertemplate="<b>Tranche</b> : %{x} "
            + unit
            + "<br><b>N capteurs</b> : %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_white",
        title=f"Repartition des capteurs par tranche de {ref_col} ({unit})",
        xaxis_title=f"Tranche ({unit})",
        yaxis_title="N capteurs",
        margin=dict(l=40, r=40, t=60, b=60),
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
    )
    return pio.to_html(fig, include_plotlyjs=False, full_html=False)


def _make_folium_map_html_HPM_HPS(
    stats_df: pd.DataFrame,
    model_name: str,
    type_config: Any,
) -> str:
    """Folium map for HPM/HPS — coloured by Tolerance_IN_OUT, sized by ref (v/h)."""
    import folium

    pred_col = type_config.eval_predicted_col
    ref_col = type_config.eval_reference_col
    unit = type_config.unit_label
    label = type_config.label or type_config.name

    df = stats_df.copy()
    df["lat"] = pd.to_numeric(df.get("lat"), errors="coerce")
    df["lon"] = pd.to_numeric(df.get("lon"), errors="coerce")
    valid = df.dropna(subset=["lat", "lon"])
    if valid.empty:
        return (
            "<p style='color:#888;font-style:italic;'>Aucune coordonnee "
            "geographique disponible pour afficher la carte (colonnes lat/lon "
            "absentes).</p>"
        )

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

    s_raw = valid.get(ref_col)
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
    layer = folium.FeatureGroup(name=f"Capteurs {type_config.name}")
    layer.add_to(m)

    info_cols = [
        c
        for c in [
            "PTM_ID",
            "Identifiant",
            "STA",
            "Type",
            "Commune",
            "Route",
            type_config.fcd_col,
            "TMJOFCDPL",
            "avg_speed_kmh",
            "avg_distance_m",
            "truck_avg_speed_kmh",
            "truck_avg_min_distance_m",
            ref_col,
            pred_col,
            "TP_redressement",
            "Erreur %",
            "Erreur absolue",
            "GEH",
            f"{pred_col}min",
            f"{pred_col}max",
            "Tolerance_IN_OUT",
            "flag_comptage",
        ]
        if c in valid.columns
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
            radius=_radius(row.get(ref_col)),
            color=_color(row.get("Tolerance_IN_OUT")),
            fill=True,
            fill_opacity=0.85,
            weight=1.2,
            popup=folium.Popup(popup_html, max_width=360),
            tooltip=tooltip_txt,
        ).add_to(layer)

    folium.LayerControl(collapsed=False).add_to(m)
    m.fit_bounds(
        [
            [float(valid["lat"].min()), float(valid["lon"].min())],
            [float(valid["lat"].max()), float(valid["lon"].max())],
        ]
    )

    def pct(n):
        return (100.0 * n / n_valid) if n_valid > 0 else 0.0

    legend_html = f"""
    <div style="position:fixed;bottom:20px;left:20px;z-index:9999;background:white;
            padding:10px 14px;border:1px solid #ccc;border-radius:10px;
            box-shadow:0 2px 8px rgba(0,0,0,.18);font-size:13px;font-family:Manrope,sans-serif;">
      <div style="font-weight:700;margin-bottom:7px;">Tolerance {label} &ndash; {_html.escape(model_name)}</div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#2ecc71;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>1 Inclus <b>({n1} &ndash; {pct(n1):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#f39c12;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>2 Hors &lt;15% borne <b>({n2} &ndash; {pct(n2):.1f}%)</b></div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#e74c3c;border:1px solid #999;margin-right:6px;border-radius:50%;"></span>3 Hors &gt;15% borne <b>({n3} &ndash; {pct(n3):.1f}%)</b></div>
      <div style="margin-top:6px;font-size:11px;color:#666;">Total: {n_valid} | Rayon ~ {ref_col} ({unit})</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    map_full_html = m.get_root().render()
    encoded = base64.b64encode(map_full_html.encode("utf-8")).decode("ascii")
    return (
        f'<iframe id="folium-map-frame" width="100%" height="600" '
        f'style="border:none;border-radius:12px;display:block;" '
        f'sandbox="allow-scripts allow-same-origin"></iframe>\n'
        f"<script>\n"
        f"(function(){{\n"
        f'  var iframe = document.getElementById("folium-map-frame");\n'
        f'  var html = atob("{encoded}");\n'
        f"  iframe.srcdoc = html;\n"
        f"}})();\n"
        f"</script>"
    )


def _build_sensitivity_section_html_HPM_HPS(
    df: pd.DataFrame,
    model: Any,
    mu_x: np.ndarray,
    s_x: np.ndarray,
    mu_y: np.ndarray,
    s_y: np.ndarray,
    input_cols: list[str],
    type_config: Any,
    num_points: int = 60,
) -> str:
    """Sensitivity analysis for HPM/HPS (predit en v/h).

    Features = FCD_HPM_TV / FCD_HPS_TV + TMJOFCDPL + speed/distance HERE +
    functional_class. Axis = v/h (jamais v/j).
    """
    import plotly.graph_objects as go
    import plotly.io as pio

    _pred_label = type_config.eval_predicted_col  # HPM_FCDr / HPS_FCDr
    _numerator_main = type_config.eval_numerator_fcd  # FCD_HPM_TV / FCD_HPS_TV
    unit = type_config.unit_label  # "v/h"
    _numerator_candidates = [_numerator_main]

    n_inputs = len(input_cols)
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

    df_num = df[input_cols].copy()
    for c in input_cols:
        df_num[c] = pd.to_numeric(df_num[c], errors="coerce")

    q_baselines = {
        "Q1": df_num.quantile(0.25),
        "Med": df_num.quantile(0.50),
        "Q3": df_num.quantile(0.75),
    }

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
        if not (np.isfinite(vmin) and np.isfinite(vmax)) or vmax == vmin:
            continue

        x_vals = np.linspace(vmin, vmax, num_points, dtype=float)
        fig = go.Figure()

        for bl_label, q_vec in q_baselines.items():
            mat = np.tile(q_vec.values.astype(float), (num_points, 1))
            df_x = pd.DataFrame(mat, columns=input_cols)
            df_x[feat] = x_vals

            x_norm = ((df_x.values - mu_x) / s_x_safe).astype(np.float32)
            y_norm = model.predict(x_norm, verbose=0)
            txpen = y_norm.flatten().astype(float) * float(s_y) + float(mu_y)

            with np.errstate(divide="ignore", invalid="ignore"):
                if feat == _numerator_col:
                    numerator = x_vals
                elif _numerator_col is not None:
                    numerator = np.full(num_points, float(q_vec[_numerator_col]), dtype=float)
                else:
                    numerator = np.ones(num_points, dtype=float)
                pred_y = np.where(txpen > 0, numerator / txpen * 100.0, np.nan)
                pred_y = np.where(np.isfinite(pred_y), pred_y, np.nan)

            other_feats = [c for c in input_cols if c != feat]
            hover_lines = [
                f"<b>{feat}</b> : %{{x:.2f}}<br>",
                f"<b>{_pred_label}</b> : %{{y:.1f}} {unit}<br>",
                f"<i>Autres features fig&#233;es &#224; {bl_label} :</i><br>",
            ] + [f"&nbsp;&nbsp;{c} = {q_vec[c]:.2f}<br>" for c in other_feats]
            hover_tmpl = "".join(hover_lines) + "<extra></extra>"

            fig.add_trace(
                go.Scatter(
                    x=x_vals.tolist(),
                    y=pred_y.tolist(),
                    mode="lines",
                    name=bl_label,
                    line=dict(color=_COLORS[bl_label], dash=_DASHES[bl_label], width=2),
                    hovertemplate=hover_tmpl,
                )
            )

        fig.update_layout(
            title=f"{_pred_label} ~ {feat}",
            xaxis_title=feat,
            yaxis_title=f"{_pred_label} ({unit})",
            template="plotly_white",
            margin=dict(l=50, r=40, t=60, b=60),
            hoverlabel=dict(bgcolor="white", font_size=12, font_family="Manrope,sans-serif"),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                title_text="Baseline",
            ),
        )
        plots_dict[feat] = pio.to_html(fig, include_plotlyjs=False, full_html=False)
        rendered_cols.append(feat)

    if not rendered_cols:
        return (
            "  <h2>Analyse de sensibilit&#233; &#8211; mod&#232;le</h2>\n"
            '  <p class="hint">Mod&#232;le ou colonnes d&#8217;entr&#233;e non disponibles '
            "pour l&#8217;analyse de sensibilit&#233;.</p>"
        )

    pills_html = "\n        ".join(
        f'<button class="sens-pill{" sens-pill--active" if i == 0 else ""}" '
        f'data-feat="{feat}" role="button" tabindex="0" '
        f'aria-pressed="{"true" if i == 0 else "false"}">{feat}</button>'
        for i, feat in enumerate(rendered_cols)
    )
    plot_divs_html = "\n".join(
        f'<div id="sens-plot-{feat}" class="sens-plot-slot" '
        f'style="display:{"block" if i == 0 else "none"};">'
        f"{plots_dict[feat]}</div>"
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
</style>
<section class="sens-block">
  <div class="sens-panel">
    <div class="sens-header">
      <div class="sens-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><polyline points="3 17 8 12 13 15 21 7"/><line x1="3" y1="21" x2="21" y2="21"/><line x1="3" y1="3" x2="3" y2="21"/></svg>
      </div>
      <div class="sens-titles">
        <h2>Analyse de sensibilit&#233;</h2>
        <p class="sens-desc">Chaque courbe montre comment le <strong>{_pred_label}</strong> pr&#233;dit &#233;volue lorsqu&#8217;une feature varie, les autres fig&#233;es &#224; <strong>Q1</strong>, <strong>M&#233;diane</strong> et <strong>Q3</strong>. Unite : {unit}. Cliquez sur une feature pour afficher son graphe.</p>
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


def generate_html_report_peak(
    metrics,
    model_name: str,
    training_config: dict[str, Any] | None,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    type_config: Any,
    df: pd.DataFrame | None = None,
    sensitivity_html: str | None = None,
    metrics_ci95: dict[str, list[float] | None] | None = None,
    metrics_by_tmja_bucket: list[dict[str, Any]] | None = None,
    calibration_data: dict[str, Any] | None = None,
    residuals_by_fc: list[dict[str, Any]] | None = None,
    drift_by_year: list[dict[str, Any]] | None = None,
) -> str:
    """Generate a self-contained HTML evaluation report for HPM or HPS.

    Sibling of ``generate_html_report_tv`` (TV) and ``generate_html_report_pl``
    (PL). Parametrised by ``type_config`` so the same code generates HPM and
    HPS reports (only label/columns/unit differ).

    Convention CEREMA Grand Lyon :
      HPM = heure de pointe matin (h08-h09, 8h00-8h59), unite v/h.
      HPS = heure de pointe soir  (h17-h18, 17h00-17h59), unite v/h.
    Reference = TMJOBCTV_HPM / TMJOBCTV_HPS (compteur reel ; jamais TMJOBCTV).
    Predit    = HPM_FCDr / HPS_FCDr (jamais TVr, jamais TV).
    Pas de variante PL pour ces kinds.
    """
    pred_col = type_config.eval_predicted_col  # HPM_FCDr / HPS_FCDr
    ref_col = type_config.eval_reference_col  # TMJOBCTV_HPM / TMJOBCTV_HPS
    unit = type_config.unit_label  # "v/h"
    full_label = type_config.label or type_config.name  # "Heure de Pointe Matin"
    kind_name = type_config.name  # "HPM" / "HPS"
    hour_window = type_config.hour_window  # (8,9) or (17,18)
    hw_text = f"{hour_window[0]:02d}h00-{hour_window[1]:02d}h00" if hour_window else ""

    # --- Build stats row from HPM/HPS columns ---
    if df is not None and pred_col in df.columns and ref_col in df.columns:
        flow_metrics = _compute_flow_metrics_HPM_HPS(df, type_config)
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

        # GEH universel (M=mesure, C=compte) — pas de /24 pour la pointe horaire.
        with np.errstate(divide="ignore", invalid="ignore"):
            geh_vals = np.sqrt(2.0 * (y_true - y_pred) ** 2 / (y_true + y_pred))
        geh_vals = np.where(np.isfinite(geh_vals), geh_vals, np.nan)

        row = {
            "model": model_name,
            "n": len(y_true),
            "err_rel_med": (
                float(metrics.median_relative_error)
                if metrics.median_relative_error is not None
                else float("nan")
            ),
            "err_abs_med": float(metrics.mae),
            "err_rel_p80": float("nan"),
            "err_abs_p80": float("nan"),
            "geh_lt5_pct": (
                float(np.nanmean(geh_vals < 5) * 100)
                if np.isfinite(geh_vals).any()
                else float("nan")
            ),
            "geh_le10_pct": (
                float(np.nanmean(geh_vals < 10) * 100)
                if np.isfinite(geh_vals).any()
                else float("nan")
            ),
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

    # --- Card styling ---
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
            f"(CI95 [{lo:.{digits}f}{suffix}, {hi:.{digits}f}{suffix}])</small>"
        )

    tol_in_pct_val = (
        (100.0 * row["tol_in"] / row["tol_total"]) if row.get("tol_total") else float("nan")
    )
    r2_val = metrics.r_squared

    # --- Barplot ---
    if df is not None and pred_col in df.columns and ref_col in df.columns:
        bar_html = _make_barplot_html_HPM_HPS(
            df, title=f"{model_name} - validation", type_config=type_config
        )
        dist_html = _make_distribution_barplot_html_HPM_HPS(df, type_config)
    else:
        bar_html = "<p>Aucune donnee disponible.</p>"
        dist_html = "<p>Aucune donnee de repartition.</p>"

    # --- Folium map ---
    if df is not None and "lat" in df.columns and "lon" in df.columns:
        map_html = _make_folium_map_html_HPM_HPS(df, model_name, type_config)
    else:
        map_html = (
            "<p style='color:#888;font-style:italic;'>Donnees non disponibles pour la carte.</p>"
        )

    # --- Outlier table ---
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
                f"<thead>{_oth}</thead>"
                f'<tbody>{"".join(_otrows)}</tbody>'
                f"</table>"
            )
            outlier_count = len(out_df)
        else:
            outlier_html = f"<p style='color:#2ecc71;font-weight:600;'>Aucun capteur {kind_name} avec une erreur &gt; 15%.</p>"
            outlier_count = 0
    else:
        outlier_html = "<p style='color:#888;font-style:italic;'>Donnees non disponibles.</p>"
        outlier_count = 0

    # --- Comparison table ---
    header_cells = [
        f"Modele {kind_name}",
        "N",
        "Err.rel med (%)",
        f"Err.abs med ({unit})",
        "Err.rel p80 (%)",
        f"Err.abs p80 ({unit})",
        "GEH<5 (%)",
        "GEH<=10 (%)",
        "Err<10% N",
        "Err<10% %",
        "Err<15% N",
        "Err<15% %",
        "Err<20% N",
        "Err<20% %",
        "Tol 1 Inclus",
        "Tol 2 Hors<15%",
        "Tol 3 Hors>15%",
        "Tol Total",
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
    tbody_row = (
        '<tr style="background:#eafaf2;font-weight:700;">'
        + "".join(f"<td>{c}</td>" for c in cells)
        + "</tr>"
    )

    # --- Stratification table per ref bucket ---
    if metrics_by_tmja_bucket:
        _bucket_headers = [
            f"Bucket {ref_col} ({unit})",
            "N",
            "Tol. inclus (N)",
            "Tol. inclus (%)",
            "p80 err.rel (%)",
            "R&sup2;",
        ]
        _bucket_thead = "<tr>" + "".join(f"<th>{h}</th>" for h in _bucket_headers) + "</tr>"
        _bucket_rows: list[str] = []
        for _b in metrics_by_tmja_bucket:
            _warn = bool(_b.get("low_sample_warning"))
            _row_style = ' style="background:#fff7ec;"' if _warn else ""
            _label_cell = _html.escape(str(_b.get("bucket", "-")))
            if _warn:
                _label_cell += (
                    ' <small style="color:#b97a00;font-weight:600;" '
                    'title="Moins de 10 echantillons — fiabilite limitee.">'
                    "(n&lt;10)</small>"
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
            f"  <h2>Metriques stratifiees par tranche de {ref_col}</h2>\n"
            f'  <p class="hint">Memes metriques recalculees sur 4 buckets de '
            f"volume de trafic {kind_name} observe ({unit}). Une ligne sur fond "
            "orange indique moins de 10 echantillons (metriques peu fiables).</p>\n"
            '  <div class="panel">\n'
            '    <table id="tmjaBucketTable" class="display" style="width:100%">\n'
            f"      <thead>{_bucket_thead}</thead>\n"
            f'      <tbody>{"".join(_bucket_rows)}</tbody>\n'
            "    </table>\n"
            "  </div>\n"
        )
    else:
        bucket_table_html = (
            f"  <h2>Metriques stratifiees par tranche de {ref_col}</h2>\n"
            '  <p class="hint" style="color:#888;font-style:italic;">'
            f"Stratification {kind_name} indisponible : colonne {ref_col} absente des donnees de validation.</p>\n"
        )

    # --- P4.1 / P4.2 / P4.3 sections (reuse generic builders, unit-agnostic) ---
    calibration_plot_inner = _make_calibration_plot_html(calibration_data)
    calibration_section_html = (
        f"  <h2>Calibration {kind_name} : predit vs observe</h2>\n"
        f'  <p class="hint">Chaque point est un capteur {kind_name}. Echelle : {unit}. '
        "La diagonale rouge <code>y = x</code> represente une prediction parfaite.</p>\n"
        '  <div class="panel plot-wrap">\n'
        f"    {calibration_plot_inner}\n"
        "  </div>\n"
    )

    residuals_plot_inner = _make_residuals_by_fc_html(residuals_by_fc)
    residuals_section_html = (
        f"  <h2>Residus {kind_name} par classe fonctionnelle</h2>\n"
        '  <p class="hint">Distribution des residus <code>pred &minus; obs</code> '
        "pour chaque classe fonctionnelle (FC). Une boite centree sur 0 indique "
        "un modele non biaise sur cette classe.</p>\n"
        '  <div class="panel plot-wrap">\n'
        f"    {residuals_plot_inner}\n"
        "  </div>\n"
    )

    drift_inner = _make_drift_by_year_html(drift_by_year)
    drift_section_html = (
        f"  <h2>Derive annuelle {kind_name} (metriques par annee)</h2>\n"
        '  <p class="hint">Memes metriques recalculees pour chaque annee '
        "presente dans le jeu de validation (au moins 10 echantillons).</p>\n"
        '  <div class="panel">\n'
        f"    {drift_inner}\n"
        "  </div>\n"
    )

    # --- Assemble full HTML ---
    title_hr = f"Evaluation — {full_label}"
    if hw_text:
        title_hr += f" ({hw_text})"

    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>{title_hr} - {_html.escape(model_name)}</title>
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
  <h1>{title_hr}</h1>
  <div class="subtitle">Modele {kind_name} : <code>{_html.escape(model_name)}</code> | {row['n']} capteurs | Pointe horaire ({hw_text}) — unite {unit} — reference {ref_col}</div>

  <div class="cards">
    <div class="card" style="background:linear-gradient(145deg,#eef6ff,#e6f0ff);border-color:#bfd5f3;">
      <div class="k">Modele {kind_name} evalue</div>
      <div class="v" style="font-size:18px;overflow-wrap:anywhere;">{_html.escape(model_name)}</div>
      <div class="best-tag">Tolerance max + erreurs minimisees</div>
    </div>
    <div class="card" style="{tol_style}">
      <div class="k">Capteurs tolerance inclus</div>
      <div class="v">{row['tol_in']}/{row['tol_total']} <small style="font-size:13px;color:#56637a;">({_fmt(tol_in_pct_val)}%)</small>{_ci_span('tol_in_pct', digits=2, suffix='%')}</div>
    </div>
    <div class="card" style="{err_style}">
      <div class="k">Err. rel. mediane {kind_name}</div>
      <div class="v">{_fmt(row.get('err_rel_med'))}%</div>
    </div>
    <div class="card">
      <div class="k">Err. rel. p80 {kind_name}</div>
      <div class="v">{_fmt(row.get('err_rel_p80'))}%{_ci_span('p80', digits=2, suffix='%')}</div>
    </div>
    <div class="card">
      <div class="k">R&sup2; {kind_name}</div>
      <div class="v">{_fmt(r2_val, digits=4)}{_ci_span('r2', digits=4)}</div>
    </div>
    <div class="card">
      <div class="k">GEH &lt; 5 ({kind_name})</div>
      <div class="v">{_fmt(row.get('geh_lt5_pct'))}%</div>
    </div>
    <div class="card" style="{pct10_style}">
      <div class="k">Capteurs {kind_name} erreur &lt; 10%</div>
      <div class="v">{n10} <small style="font-size:14px;color:#56637a;">({_fmt(pct10)}%)</small></div>
    </div>
    <div class="card" style="{pct15_style}">
      <div class="k">Capteurs {kind_name} erreur &lt; 15%</div>
      <div class="v">{n15} <small style="font-size:14px;color:#56637a;">({_fmt(pct15)}%)</small></div>
    </div>
    <div class="card" style="{pct20_style}">
      <div class="k">Capteurs {kind_name} erreur &lt; 20%</div>
      <div class="v">{n20} <small style="font-size:14px;color:#56637a;">({_fmt(pct20)}%)</small></div>
    </div>
  </div>

  <h2>Tableau des metriques detaillees {kind_name}</h2>
  <p class="hint">Metriques calculees sur les donnees de validation {full_label} — debits en {unit}. Tolerance : 1 = inclus, 2 = hors &lt;15% borne, 3 = hors &gt;15% borne.</p>
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

  <h2>Repartition des capteurs par tranche ({unit})</h2>
  <p class="hint">Histogramme des capteurs par tranche de debit {ref_col} ({unit}). Tranches : 0/50/100/200/400/800/1500/3000 {unit}.</p>
  <div class="panel plot-wrap">
    {dist_html}
  </div>

  <h2>Barplot - {ref_col} vs {pred_col} (validation, {unit})</h2>
  <div class="panel plot-wrap">
    {bar_html}
  </div>

  <h2>Capteurs {kind_name} avec ecart &gt; 15% ({outlier_count} capteur(s))</h2>
  <p class="hint">Liste triee par erreur decroissante. Fond rose = erreur &gt; 50%, fond orange clair = erreur &gt; 30%.</p>
  <div class="panel">
    {outlier_html}
  </div>

  <h2>Carte des capteurs {kind_name} (validation)</h2>
  <p class="hint">Cliquez sur un capteur pour voir toutes ses informations. Couleur = tolerance. Taille = {ref_col} ({unit}).</p>
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
    $('#tmjaBucketTable').DataTable({{
      paging: false, searching: false, info: false, ordering: false,
    }});
  }}
  if ($('#driftByYearTable').length) {{
    $('#driftByYearTable').DataTable({{
      paging: false, searching: false, info: false, order: [[0, 'asc']],
    }});
  }}
}});
</script>
</body>
</html>"""
    return html
