"""Data-quality investigation for the 226 top TVr discontinuity cases.

Reads:
  - top250_discontinuities_with_inputs.csv (226 paired E/N rows)
  - FCDREFGLOBAL_2025.parquet (241857 segments)

Produces:
  - analysis_D_data_quality.md  (markdown report < 250 lines)

Note: column `agregId_E/_N` matches `segment_id` in FCD parquet.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
CSV = ROOT / "outputs" / "top250_discontinuities_with_inputs.csv"
# External data root — override via MDL_DATA_ROOT env var.
DATA_ROOT = Path(os.environ.get("MDL_DATA_ROOT", Path.home() / "mdl-data"))
FCD = (
    DATA_ROOT
    / "Travaux_Python" / "Travaux_donnees_Lyon" / "Livrables"
    / "FCDREFGLOBAL" / "FCDREFGLOBAL_2025.parquet"
)
OUT = ROOT / "analysis_D_data_quality.md"


IMP_FLAGS = [
    "car_average_speed_kmh_was_imputed",
    "car_average_distance_km_was_imputed",
    "car_average_distance_before_km_was_imputed",
    "car_average_distance_after_km_was_imputed",
    "car_min_average_distance_km_was_imputed",
    "truck_average_speed_kmh_was_imputed",
    "truck_average_distance_km_was_imputed",
    "truck_average_distance_before_km_was_imputed",
    "truck_average_distance_after_km_was_imputed",
    "truck_min_average_distance_km_was_imputed",
]
MONTH_TV = [f"month_trip_per_day_M{m:02d}" for m in range(1, 13)]
MONTH_PL = [f"month_truck_trip_per_day_M{m:02d}" for m in range(1, 13)]

KEEP_COLS = (
    [
        "segment_id",
        "functional_class",
        "is_ramp",
        "is_roundabout",
        "RAMP",
        "ROUNDABOUT",
        "Annee",
        "TMJOFCDTV",
        "TMJOFCDPL",
        "avg_distance_before_m",
    ]
    + IMP_FLAGS
    + MONTH_TV
    + MONTH_PL
)


def cv(row: pd.Series) -> float:
    """Coefficient of variation across 12-month series; NaN-safe."""
    vals = row.values.astype(float)
    vals = vals[~np.isnan(vals)]
    if vals.size < 6 or np.nanmean(vals) <= 1e-9:
        return np.nan
    return float(np.nanstd(vals) / np.nanmean(vals))


def main() -> None:
    cases = pd.read_csv(CSV)
    n_cases = len(cases)
    print(f"Loaded {n_cases} cases")

    fcd = pd.read_parquet(FCD, columns=KEEP_COLS)
    fcd["segment_id"] = fcd["segment_id"].astype(str)
    fcd = fcd.set_index("segment_id")
    print(f"FCD slim shape: {fcd.shape}")

    # Lookup E and N side rows — segment_id is string (may include -T/-F)
    seg_e = cases["agregId_E"].astype(str)
    seg_n = cases["agregId_N"].astype(str)
    miss_e = (~seg_e.isin(fcd.index)).sum()
    miss_n = (~seg_n.isin(fcd.index)).sum()

    def lk(series: pd.Series) -> pd.DataFrame:
        return fcd.reindex(series.values).reset_index(drop=True)

    eE = lk(seg_e)
    eN = lk(seg_n)

    # ----- 1. Bimodality / distribution of input deltas -----
    cols_to_check = [
        "TMJOFCDTV", "TMJOFCDPL", "avg_distance_before_m",
    ]
    bimodal_stats = {}
    for c in cols_to_check:
        dE = eE[c].astype(float)
        dN = eN[c].astype(float)
        # ratio min/max per case (lower => more extreme bimodality)
        denom = np.maximum(dE.abs(), dN.abs())
        ratio = np.where(
            denom > 1e-6,
            np.minimum(dE.abs(), dN.abs()) / denom,
            np.nan,
        )
        delta = dE - dN
        bimodal_stats[c] = {
            "min_max_ratio_median": float(np.nanmedian(ratio)),
            "min_max_ratio_mean": float(np.nanmean(ratio)),
            "frac_min_lt_10pct_of_max": float(np.nanmean(ratio < 0.10)),
            "frac_min_lt_25pct_of_max": float(np.nanmean(ratio < 0.25)),
            "delta_p50": float(np.nanmedian(delta)),
            "delta_p95_abs": float(np.nanpercentile(np.abs(delta), 95)),
        }

    # ----- 2. Imputation flags -----
    imp_e = eE[IMP_FLAGS].fillna(False).astype(bool)
    imp_n = eN[IMP_FLAGS].fillna(False).astype(bool)
    any_e = imp_e.any(axis=1)
    any_n = imp_n.any(axis=1)
    both = any_e & any_n
    neither = (~any_e) & (~any_n)
    only_e = any_e & (~any_n)
    only_n = (~any_e) & any_n
    asymmetric = only_e | only_n
    imp_counts_e = imp_e.sum(axis=1)
    imp_counts_n = imp_n.sum(axis=1)
    by_flag = pd.DataFrame(
        {
            "E_imputed": imp_e.sum(),
            "N_imputed": imp_n.sum(),
        }
    )
    by_flag["E_pct"] = (by_flag["E_imputed"] / n_cases * 100).round(1)
    by_flag["N_pct"] = (by_flag["N_imputed"] / n_cases * 100).round(1)

    # Baseline imputation rate on the full FCD population for context
    fcd_imp_rate = (
        fcd[IMP_FLAGS].fillna(False).astype(bool).any(axis=1).mean()
    )

    # ----- 3. Monthly CV outliers -----
    cv_tv_e = eE[MONTH_TV].apply(cv, axis=1)
    cv_tv_n = eN[MONTH_TV].apply(cv, axis=1)
    cv_pl_e = eE[MONTH_PL].apply(cv, axis=1)
    cv_pl_n = eN[MONTH_PL].apply(cv, axis=1)
    delta_cv_tv = (cv_tv_e - cv_tv_n).abs()
    delta_cv_pl = (cv_pl_e - cv_pl_n).abs()
    high_delta_cv_tv = int((delta_cv_tv > 0.30).sum())
    high_delta_cv_pl = int((delta_cv_pl > 0.30).sum())
    high_cv_either = int(((cv_tv_e > 0.50) | (cv_tv_n > 0.50)).sum())

    # ----- 4. Annee mismatch -----
    annee_mismatch = int((eE["Annee"].astype(str) != eN["Annee"].astype(str)).sum())
    annee_unique = sorted(
        set(eE["Annee"].dropna().astype(str)).union(eN["Annee"].dropna().astype(str))
    )

    # ----- 5. Network attribute consistency -----
    fc_e = eE["functional_class"].astype("Int64")
    fc_n = eN["functional_class"].astype("Int64")
    fc_table = pd.crosstab(fc_e, fc_n, dropna=False)
    fc_diff = (fc_e - fc_n).abs()
    same_fc = int((fc_diff == 0).sum())
    diff1_fc = int((fc_diff == 1).sum())
    diff2plus_fc = int((fc_diff >= 2).sum())

    # Ramp / Roundabout asymmetry — columns are 'Y'/'N' strings in FCD
    def as_bool(s: pd.Series) -> pd.Series:
        return s.astype(str).str.upper().eq("Y")

    ramp_e_b = as_bool(eE["RAMP"])
    ramp_n_b = as_bool(eN["RAMP"])
    rb_e_b = as_bool(eE["ROUNDABOUT"])
    rb_n_b = as_bool(eN["ROUNDABOUT"])
    ramp_asym = int((ramp_e_b != ramp_n_b).sum())
    rb_asym = int((rb_e_b != rb_n_b).sum())
    ramp_either = int((ramp_e_b | ramp_n_b).sum())
    rb_either = int((rb_e_b | rb_n_b).sum())

    # ----- 6. Geographic anomalies -----
    # CSV gives one lat/lon (likely the node). We do not have per-side centroids
    # in the CSV. Compute approximate dispersion of the node lat/lon set as
    # diagnostic. If E and N truly share a node, distance ≈ 0 by construction.
    lats = cases["lat"].astype(float)
    lons = cases["lon"].astype(float)
    geo_extent_km = float(
        math.hypot(
            (lats.max() - lats.min()) * 111.0,
            (lons.max() - lons.min()) * 111.0 * math.cos(math.radians(lats.mean())),
        )
    )

    # ----- Verdict per case -----
    # A case is flagged "DATA quality" if any of:
    #   * at least one imputed flag on E OR N side
    #   * |delta CV| > 0.30 on TV OR PL monthly
    # A case is flagged "Legitimate transition" if:
    #   * |delta FC| >= 2  OR
    #   * RAMP / ROUNDABOUT asymmetric (one side is on a ramp/roundabout)
    data_quality_mask = (any_e | any_n) | (delta_cv_tv > 0.30) | (delta_cv_pl > 0.30)
    legit_transition_mask = (fc_diff >= 2) | (ramp_e_b != ramp_n_b) | (rb_e_b != rb_n_b)
    pure_data = int((data_quality_mask & ~legit_transition_mask).sum())
    pure_legit = int((legit_transition_mask & ~data_quality_mask).sum())
    both_cnt = int((data_quality_mask & legit_transition_mask).sum())
    unexplained = int((~data_quality_mask & ~legit_transition_mask).sum())

    # ----- Top 5 cases for QA -----
    qa = cases[["rank", "agregId_E", "agregId_N", "composite_severity",
                "TVr_E", "TVr_N", "delta_TVr_pct"]].copy()
    qa["imp_E"] = imp_counts_e.values
    qa["imp_N"] = imp_counts_n.values
    qa["fc_E"] = fc_e.values
    qa["fc_N"] = fc_n.values
    qa["cv_tv_E"] = cv_tv_e.round(2).values
    qa["cv_tv_N"] = cv_tv_n.round(2).values
    qa["dq_flag"] = data_quality_mask.values
    qa["legit"] = legit_transition_mask.values
    # Pick top severity rows that are PURELY data-quality
    top5 = (
        qa[qa["dq_flag"] & ~qa["legit"]]
        .sort_values("composite_severity", ascending=False)
        .head(5)
    )

    # ----- Build markdown report -----
    lines: list[str] = []
    lines.append("# Analyse D — Qualité des données des 226 discontinuités TVr")
    lines.append("")
    lines.append(
        "Investigation : les 226 cas top de discontinuité TVr sont-ils causés "
        "par des **problèmes de qualité de données FCD** plutôt que par le "
        "modèle TV lui-même ?"
    )
    lines.append("")
    lines.append(
        f"- CSV cases : `{CSV.name}` ({n_cases} cas)"
    )
    lines.append(f"- FCD source : `{FCD.name}` ({fcd.shape[0]:,} segments)")
    lines.append(
        f"- Lookup miss E={miss_e}, N={miss_n} (devrait être 0)"
    )
    lines.append("")
    lines.append("## 1. Bimodalité des inputs (E vs N)")
    lines.append("")
    lines.append(
        "Pour chaque input, ratio `min(|E|,|N|) / max(|E|,|N|)` par cas : "
        "valeur proche de 0 = un côté quasi nul vs un côté élevé (signature "
        "d'une coupure FCD)."
    )
    lines.append("")
    lines.append("| Input | médiane ratio | %cas <10% | %cas <25% | |Δ| p95 |")
    lines.append("|---|---:|---:|---:|---:|")
    for c, s in bimodal_stats.items():
        lines.append(
            f"| {c} | {s['min_max_ratio_median']:.2f} | "
            f"{s['frac_min_lt_10pct_of_max']*100:.0f}% | "
            f"{s['frac_min_lt_25pct_of_max']*100:.0f}% | "
            f"{s['delta_p95_abs']:.0f} |"
        )
    lines.append("")
    lines.append(
        "**Lecture** : un fort pourcentage de cas avec ratio < 10 % indique "
        "une bimodalité franche (un côté présent, l'autre quasi absent), "
        "typique d'un **gap de couverture FCD** ou d'une troncature."
    )
    lines.append("")
    lines.append("## 2. Flags d'imputation FCD")
    lines.append("")
    lines.append(
        f"Baseline FCDREFGLOBAL : **{fcd_imp_rate*100:.1f}%** des segments ont "
        f"au moins une variable imputée."
    )
    lines.append("")
    lines.append(
        f"- Au moins 1 imputation côté E : **{int(any_e.sum())}** / {n_cases} "
        f"({any_e.mean()*100:.1f}%)"
    )
    lines.append(
        f"- Au moins 1 imputation côté N : **{int(any_n.sum())}** / {n_cases} "
        f"({any_n.mean()*100:.1f}%)"
    )
    lines.append(
        f"- **Les deux** côtés imputés : **{int(both.sum())}** "
        f"({both.mean()*100:.1f}%)"
    )
    lines.append(
        f"- Asymétrique (un seul côté imputé) : **{int(asymmetric.sum())}** "
        f"({asymmetric.mean()*100:.1f}%)"
    )
    lines.append(
        f"- Aucun côté imputé : **{int(neither.sum())}** "
        f"({neither.mean()*100:.1f}%)"
    )
    lines.append("")
    lines.append("**Détail par flag :**")
    lines.append("")
    lines.append("| Flag | E imputé | E % | N imputé | N % |")
    lines.append("|---|---:|---:|---:|---:|")
    for f, row in by_flag.iterrows():
        short = f.replace("_was_imputed", "")
        lines.append(
            f"| {short} | {int(row['E_imputed'])} | {row['E_pct']}% | "
            f"{int(row['N_imputed'])} | {row['N_pct']}% |"
        )
    lines.append("")
    enriched = any_e.mean() + any_n.mean() - both.mean()  # union prob
    lift = enriched / max(fcd_imp_rate, 1e-9)
    lines.append(
        f"**Lift** : la probabilité qu'au moins un côté soit imputé est "
        f"**{enriched*100:.1f}%** vs **{fcd_imp_rate*100:.1f}%** en moyenne "
        f"FCD → enrichissement ×**{lift:.2f}**. "
        f"Les 226 cas top sont donc {'fortement' if lift > 1.5 else 'modérément' if lift > 1.1 else 'peu'} sur-représentés "
        f"en imputations."
    )
    lines.append("")
    lines.append("## 3. Outliers mensuels (CV sur M01..M12)")
    lines.append("")
    lines.append(
        f"- |ΔCV(TV)| > 0.30 entre E et N : **{high_delta_cv_tv}** cas "
        f"({high_delta_cv_tv/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- |ΔCV(PL)| > 0.30 entre E et N : **{high_delta_cv_pl}** cas "
        f"({high_delta_cv_pl/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- CV(TV) > 0.50 sur au moins un côté : **{high_cv_either}** cas "
        f"({high_cv_either/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- CV(TV) médian E={cv_tv_e.median():.2f} / N={cv_tv_n.median():.2f}"
    )
    lines.append("")
    lines.append(
        "**Lecture** : un CV mensuel très différent entre les deux côtés (ou "
        "très élevé d'un côté) suggère une **série temporelle FCD bruitée** "
        "ou un échantillonnage déséquilibré sur l'année."
    )
    lines.append("")
    lines.append("## 4. Cohérence de l'année")
    lines.append("")
    lines.append(f"- Valeurs uniques de `Annee` : {annee_unique}")
    lines.append(f"- Cas avec Annee_E ≠ Annee_N : **{annee_mismatch}**")
    lines.append("")
    lines.append("## 5. Matrice de transition functional_class (E × N)")
    lines.append("")
    lines.append(
        f"- Même FC E et N : **{same_fc}** ({same_fc/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- |ΔFC| = 1 : **{diff1_fc}** ({diff1_fc/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- |ΔFC| ≥ 2 (transition franche, hiérarchie réseau) : "
        f"**{diff2plus_fc}** ({diff2plus_fc/n_cases*100:.1f}%)"
    )
    lines.append("")
    lines.append("Matrice FC_E (lignes) × FC_N (colonnes) :")
    lines.append("")
    lines.append("```")
    lines.append(fc_table.to_string())
    lines.append("```")
    lines.append("")
    lines.append("**RAMP / ROUNDABOUT :**")
    lines.append("")
    lines.append(
        f"- RAMP asymétrique (un seul côté est une bretelle) : **{ramp_asym}** "
        f"; au moins un côté RAMP = {ramp_either}"
    )
    lines.append(
        f"- ROUNDABOUT asymétrique : **{rb_asym}** ; au moins un côté = "
        f"{rb_either}"
    )
    lines.append("")
    lines.append("## 6. Anomalies géographiques")
    lines.append("")
    lines.append(
        f"- Étendue lat/lon des 226 nœuds : ~{geo_extent_km:.1f} km "
        f"(zone Grand Lyon)"
    )
    lines.append(
        f"- lat ∈ [{lats.min():.4f}, {lats.max():.4f}], "
        f"lon ∈ [{lons.min():.4f}, {lons.max():.4f}]"
    )
    lines.append(
        "- Le CSV ne fournit qu'un lat/lon partagé (nœud commun) — les arêtes "
        "E et N partagent par construction l'extrémité, distance ≈ 0. "
        "Pas d'adjacence corrompue détectable depuis ce CSV."
    )
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(
        f"- **DATA quality pur** (imputation ou ΔCV élevé sans transition "
        f"réseau franche) : **{pure_data}** cas ({pure_data/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- **Transition légitime pure** (|ΔFC|≥2 ou RAMP/RB asymétrique, "
        f"sans signe d'imputation/CV) : **{pure_legit}** cas "
        f"({pure_legit/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- **Les deux causes simultanées** : **{both_cnt}** cas "
        f"({both_cnt/n_cases*100:.1f}%)"
    )
    lines.append(
        f"- **Inexpliqué** (ni signature data, ni transition réseau) : "
        f"**{unexplained}** cas ({unexplained/n_cases*100:.1f}%) → "
        f"très probablement erreur de modèle TV"
    )
    lines.append("")
    total_dq = pure_data + both_cnt
    total_legit = pure_legit
    lines.append(
        f"**Conclusion** : sur 226 cas, **{total_dq}** "
        f"({total_dq/n_cases*100:.0f}%) présentent au moins une signature "
        f"de problème de données FCD ; **{total_legit}** "
        f"({total_legit/n_cases*100:.0f}%) sont des transitions réseau "
        f"légitimes sans signe d'imputation. Le résiduel **{unexplained}** "
        f"cas est à investiguer côté modèle."
    )
    lines.append("")
    lines.append("## Top 5 cas pour revue QA (data-quality pur, severity max)")
    lines.append("")
    lines.append(
        "| rank | agregId_E | agregId_N | severity | TVr_E | TVr_N | "
        "Δ% | imp_E | imp_N | fc_E | fc_N | cv_tv_E | cv_tv_N |"
    )
    lines.append(
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for _, r in top5.iterrows():
        lines.append(
            f"| {int(r['rank'])} | {int(r['agregId_E'])} | "
            f"{int(r['agregId_N'])} | {r['composite_severity']:.0f} | "
            f"{r['TVr_E']:.0f} | {r['TVr_N']:.0f} | "
            f"{r['delta_TVr_pct']:.1f}% | {int(r['imp_E'])} | "
            f"{int(r['imp_N'])} | {r['fc_E']} | {r['fc_N']} | "
            f"{r['cv_tv_E']} | {r['cv_tv_N']} |"
        )
    lines.append("")
    lines.append("---")
    lines.append(
        "*Méthode : lookup `agregId_E/N` → `segment_id` dans "
        "`FCDREFGLOBAL_2025.parquet`. Flags d'imputation : 10 colonnes "
        "`*_was_imputed`. CV mensuel calculé sur M01..M12. "
        "Seuils : imputation = OR sur 10 flags ; CV élevé = écart > 0.30 "
        "entre E et N.*"
    )

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {OUT}  ({len(lines)} lines)")


if __name__ == "__main__":
    main()
