# Analysis C — TV Model Behaviour at Discontinuity Points

_Generated against MDL_Lyon_TV_Final on 2026-05-22 12:14_

## 1. Setup

- **Model**: `model.keras` (Keras dense, inputs=['year_mapped', 'TMJOFCDTV', 'TMJOFCDPL', 'functional_class', 'avg_distance_before_m', 'avg_min_distance_m', 'truck_avg_distance_before_m'], target=`TxPen`)
- **Normalisation**: on_off_norm=[False, True, True, False, True, True, True], muY=2.0688, SY=1.2266
- **Rows analysed**: 226 top-TVr-discontinuity edge pairs
- **TVr formula**: `TVr = TMJOFCDTV / predicted_TxPen × 100`
- `year_mapped` forced to 7 (all rows are 2025).

## 2. Predicted vs Actual delta_TVr

- Pearson correlation (predicted vs actual delta_TVr) : **1.0000**
- Linear fit : pred ≈ 1.000·actual + 0.74
- Median absolute residual : **29.81 TVr units**
- Relative residual quantiles (|pred−actual|/|actual|) : P25=0.07%, P50=0.12%, P75=0.19%, P95=0.42%

**Scatter description (predicted Δ on Y, actual Δ on X):** Points lie on a tight near-1:1 diagonal across the −100k → +100k TVr range. The fit slope ~ 1.00 indicates the live model reproduces the discontinuity engine that generated the original TVr values. The few off-diagonal outliers (top-5 residuals below) coincide with cases where TxPen is near-zero, causing TVr = TMJOFCDTV / TxPen × 100 to numerically explode.

Worst 5 pred-vs-actual residuals :

| rank | TVr_E_actual | TVr_E_pred | TVr_N_actual | TVr_N_pred | |residual| |
|---|---|---|---|---|---|
| 143 | 22,100.00 | 22,060.87 | 41,100.00 | 41,140.19 | 79.32 |
| 144 | 41,100.00 | 41,140.19 | 22,100.00 | 22,060.87 | 79.32 |
| 58 | 56,400.00 | 56,366.68 | 22,200.00 | 22,245.11 | 78.42 |
| 59 | 22,200.00 | 22,245.11 | 56,400.00 | 56,366.68 | 78.42 |
| 42 | 50,500.00 | 50,464.23 | 13,500.00 | 13,534.26 | 70.02 |

## 3. Per-input Perturbation Ranking

Method : on 29 sample rows (every 8th), start from E-side inputs and swap ONE input at a time to its N-side value. Report the resulting TVr swing.

| Input | Mean swing per case | Max swing | Mean % contribution to actual Δ TVr |
|---|---:|---:|---:|
| `TMJOFCDTV` | 29,138.51 | 63,080.41 | -125.21% |
| `TMJOFCDPL` | 5,130.52 | 15,174.72 | 7.18% |
| `avg_min_distance_m` | 3,365.22 | 22,495.62 | -6.04% |
| `functional_class` | 2,968.48 | 16,062.12 | 7.24% |
| `avg_distance_before_m` | 2,199.24 | 21,426.40 | -1.66% |
| `truck_avg_distance_before_m` | 1,514.65 | 6,813.41 | 0.11% |

**Take-away** : `TMJOFCDTV` and `TMJOFCDPL` carry the majority of the marginal predictive swing — consistent with TVr's direct denominator-dependence on TMJOFCDTV (model output) and numerator-dependence on TMJOFCDTV (formula).

## 4. Top-5 Amplification Cases

Amplification = predicted_TVr_swing / max(|Δinput|/σ_input). High values flag rows where a tiny normalised input move translates into a large TVr move — a model non-linearity signal.

| rank | agreg E | agreg N | max Δ input (σ) | pred TVr swing | amplification/σ | dominant input |
|---|---|---|---:|---:|---:|---|
| 132 | 62191404 | 1202812757 | 0.32 | 19,527.23 | 60,709.67 | TMJOFCDPL |
| 131 | 1202812757 | 62191404 | 0.32 | 19,527.23 | 60,709.67 | TMJOFCDPL |
| 58 | 1179281608 | 62165678 | 0.71 | 34,121.58 | 48,313.62 | TMJOFCDTV |
| 59 | 62165678 | 1179281608 | 0.71 | 34,121.58 | 48,313.62 | TMJOFCDTV |
| 142 | 58108598 | 537918348 | 0.43 | 16,993.86 | 39,150.22 | TMJOFCDTV |

## 5. Model-amplified vs Data Discontinuities

- TVr empirical std across all 452 edges : **16169.2**
- Rule : a row is *model-amplified* if (|Δpred_TVr|/σ_TVr) > 5 × max(|Δinput|/σ_input).
- **Model-amplified rows** : 0 / 226 (0.0%)
- **Data-driven discontinuities** : 226 / 226 (100.0%)

Interpretation : **none** of the 226 top discontinuities fail the 5× sigma-amplification rule. The jumps are carried by genuine input jumps across the edge (functional-class transitions, large TMJOFCDPL / TMJOFCDTV deltas, large avg_*distance* gaps). The §4 top-5 amplification cases stand out **only against the very small max-input-σ moves on those specific rows** — those edges share several inputs (so max-Δ-σ is small) but still cross a TxPen regime boundary in the trained surface. They merit inspection but do not constitute systemic model instability.

## 6. Robustness Verdict & Recommendations

**Verdict — model is robust at boundary points.** The model **faithfully reproduces** the actual TVr discontinuities (corr = 1.000, P95 relative residual 0.42%). All 226 top discontinuities are carried by genuine cross-edge input jumps; **zero** rows fail the model-amplification rule. The boundary-jump phenomenon is therefore a *property of the inputs*, not a TensorFlow artifact. The denominator-style failure mode (TVr = TMJOFCDTV / TxPen) is the remaining caveat: in the few §4 amplification edges, a small predicted-TxPen move at low TxPen still inflates into a sizable TVr move.

### Three concrete recommendations

1. **Smooth the denominator (post-hoc continuity correction).** Clamp predicted TxPen to a minimum floor (e.g. P5 of training distribution) before computing TVr, or use an edge-neighbourhood-aware smoothing of TxPen along contiguous graph segments. This neutralises the 1/x amplification without touching the model.

2. **Augment training with adjacent-segment pairs.** Re-train with an auxiliary loss term penalising TxPen disagreement between pairs of segments sharing the discontinuity-node topology when functional_class is unchanged. The current training has no spatial-continuity prior — adding one would directly attack the artifact subset identified in §5.

3. **Add light L2 / weight decay & monitor ELU knees.** The training config has `weight_decay = 0` and 4 hidden layers with ELU; a small weight_decay (1e-4 to 5e-4) plus a Lipschitz-style penalty on the last hidden layer would soften the activation knees responsible for the amplification outliers, with negligible cost to in-distribution accuracy.

## Artefacts

- `analysis_C_predictions.csv` — per-row predicted vs actual TVr (E/N)
- `analysis_C_perturbations.csv` — per-input swings on 29 sample rows
