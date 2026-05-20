# A6_C1_TTA

TTA re-evaluation of config 1 (`A6_huber_permX2_recX2`).

## TTA parameters
- tta_iter: `5`
- tta_noise_std: `0.01`

## Comparison (parent vs TTA)
| Metric | Parent | TTA |
|---|---|---|
| tol_in | 2236/3632 (61.6%) | 2238/3632 (61.6%) |
| err_rel_p80 (%) | 28.92 | 28.76 |
| R2 | 0.668843 | 0.668881 |
| RMSE | 0.6778 | 0.6778 |
| MAE | 0.3743 | 0.3743 |
| GEH<5 (%) | 100.0 | 100.0 |

## CI95 (TTA, bootstrap 1000 iter)
- tol_in_pct: [60.02, 63.24]
- p80: [27.7326, 29.8885]
- r2: [0.615851, 0.720627]

- eval_seconds: 10.6