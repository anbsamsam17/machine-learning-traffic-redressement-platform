# A5_PinballP80_LogTarget

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "losses": [
    "pinball_p80"
  ],
  "target_log_transform": true
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`pinball_p80`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1033, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `False`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `False`
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **1693/3632** (46.61%)
- Erreur relative p80: **33.1744%**
- R²: **0.623026**
- GEH < 5: **100.0%**
- RMSE: 0.7232  MAE: 0.4777  MAPE: 30.81%
- Median rel. error: 20.95%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.577812,
    0.665128
  ],
  "p80": [
    32.18,
    34.1688
  ],
  "tol_in_pct": [
    44.99,
    48.16
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 79 | 39.5% | 59.9569 | 0.097366 |
| 1k-5k | 1361 | 665 | 48.86% | 35.8687 | 0.443 |
| 5k-20k | 1618 | 657 | 40.61% | 31.191 | 0.388375 |
| 20k+ | 453 | 292 | 64.46% | 19.0653 | 0.565098 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.319754 | 0.4115 | 36.49% | 44.2768% |
| 2020 | 266 | 0.704921 | 0.3705 | 45.49% | 37.8006% |
| 2021 | 347 | 0.797349 | 0.3405 | 52.74% | 32.576% |
| 2022 | 390 | 0.776842 | 0.3396 | 52.56% | 32.6727% |
| 2023 | 440 | 0.63123 | 0.4115 | 44.77% | 35.9773% |
| 2024 | 453 | 0.529601 | 0.4735 | 39.51% | 39.9082% |
| 2025 | 1514 | 0.605573 | 0.5937 | 29.79% | 60.2669% |

_Wall-clock: 183.1s  bootstrap_iter=1000_