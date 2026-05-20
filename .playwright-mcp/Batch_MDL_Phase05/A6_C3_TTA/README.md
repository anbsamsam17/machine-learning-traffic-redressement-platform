# A6_C3_TTA

TTA re-evaluation of config 3 (`A6_AdamW_skip_LN_permX2`).

## TTA parameters
- tta_iter: `5`
- tta_noise_std: `0.01`

## Comparison (parent vs TTA)
| Metric | Parent | TTA |
|---|---|---|
| tol_in | 2107/3632 (58.0%) | 2112/3632 (58.1%) |
| err_rel_p80 (%) | 31.19 | 31.18 |
| R2 | 0.661534 | 0.661501 |
| RMSE | 0.6853 | 0.6853 |
| MAE | 0.3991 | 0.3991 |
| GEH<5 (%) | 100.0 | 100.0 |

## CI95 (TTA, bootstrap 1000 iter)
- tol_in_pct: [56.47, 59.83]
- p80: [30.2189, 32.7484]
- r2: [0.612488, 0.708113]

- eval_seconds: 11.1