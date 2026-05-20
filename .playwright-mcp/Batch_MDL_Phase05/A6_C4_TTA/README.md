# A6_C4_TTA

TTA re-evaluation of config 4 (`A6_AdamW_skip_LN_permX2_recX2`).

## TTA parameters
- tta_iter: `5`
- tta_noise_std: `0.01`

## Comparison (parent vs TTA)
| Metric | Parent | TTA |
|---|---|---|
| tol_in | 2080/3632 (57.3%) | 2087/3632 (57.5%) |
| err_rel_p80 (%) | 31.11 | 31.29 |
| R2 | 0.668137 | 0.668164 |
| RMSE | 0.6786 | 0.6785 |
| MAE | 0.402 | 0.402 |
| GEH<5 (%) | 100.0 | 100.0 |

## CI95 (TTA, bootstrap 1000 iter)
- tol_in_pct: [55.89, 59.17]
- p80: [30.1907, 32.3893]
- r2: [0.619989, 0.713343]

- eval_seconds: 10.3