# A6_C9_TTA

TTA re-evaluation of config 9 (`A6_AdamW_skip_huber_permX3`).

## TTA parameters
- tta_iter: `5`
- tta_noise_std: `0.01`

## Comparison (parent vs TTA)
| Metric | Parent | TTA |
|---|---|---|
| tol_in | 2045/3632 (56.3%) | 2047/3632 (56.4%) |
| err_rel_p80 (%) | 30.52 | 30.57 |
| R2 | 0.662223 | 0.662259 |
| RMSE | 0.6846 | 0.6845 |
| MAE | 0.4004 | 0.4004 |
| GEH<5 (%) | 100.0 | 100.0 |

## CI95 (TTA, bootstrap 1000 iter)
- tol_in_pct: [54.73, 58.01]
- p80: [29.8096, 31.5622]
- r2: [0.612317, 0.712014]

- eval_seconds: 11.0