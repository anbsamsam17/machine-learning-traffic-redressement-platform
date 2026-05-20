# A5_HardMining_perm2

**Worker:** A5 (port 7005)
**Phase 05:** training tricks (hard mining, curriculum, quantile, k-fold)
**Dataset:** `BCFCDREF_AllYears_TV.geojson` (3632 capteurs Grand Lyon, 2019-2025)

## Overrides (on top of baseline)
```json
{
  "use_hard_example_mining": true,
  "use_flag_permanent_weighting": true,
  "flag_priority_weight": 2.0
}
```

## Baseline
- 11 features (year_mapped, TMJOFCDTV, TMJOFCDPL, functional_class, 7 distance vars)
- loss=`mse`, dropout=0.025, neurons_factors=[3.0, 2.0, 1.0], lr=0.01, batch=256, activation=elu
- epochs_requested=1250, epochs_trained=1035, test_size=0.05

## Training tricks enabled
- use_hard_example_mining: `True`
- use_curriculum: `False`
- use_quantile_head: `None`
- target_log_transform: `None`
- use_flag_permanent_weighting: `True`
- use_flag_recent_year_weighting: `False`
- n_seeds: `1`

## Validation metrics (n=3632)
- Capteurs tolérance inclus: **2207/3632** (60.77%)
- Erreur relative p80: **28.9511%**
- R²: **0.680557**
- GEH < 5: **100.0%**
- RMSE: 0.6657  MAE: 0.3777  MAPE: 21.91%
- Median rel. error: 14.13%

## CI95 (bootstrap)
```json
{
  "r2": [
    0.631854,
    0.728623
  ],
  "p80": [
    28.0012,
    29.9011
  ],
  "tol_in_pct": [
    59.11,
    62.39
  ]
}
```

## Per-bucket TMJOBCTV
| bucket | n | tol_in_n | tol% | p80 | R² |
| ------ | - | -------- | ---- | --- | -- |
| 0-1k | 200 | 95 | 47.5% | 62.3576 | 0.059358 |
| 1k-5k | 1361 | 777 | 57.09% | 34.9372 | 0.458733 |
| 5k-20k | 1618 | 996 | 61.56% | 24.999 | 0.543397 |
| 20k+ | 453 | 339 | 74.83% | 15.9501 | 0.707468 |

## Drift by year
| year | n | R² | MAE | tol% | p80% |
| ---- | - | -- | --- | ---- | ---- |
| 2019 | 222 | 0.594791 | 0.2879 | 56.76% | 26.4595% |
| 2020 | 266 | 0.791861 | 0.3025 | 57.89% | 24.8582% |
| 2021 | 347 | 0.861398 | 0.2654 | 64.27% | 21.4799% |
| 2022 | 390 | 0.858701 | 0.2565 | 65.64% | 22.5312% |
| 2023 | 440 | 0.725636 | 0.2935 | 61.14% | 23.3824% |
| 2024 | 453 | 0.595993 | 0.3502 | 58.28% | 26.4859% |
| 2025 | 1514 | 0.645435 | 0.4937 | 40.62% | 43.4726% |

_Wall-clock: 276.5s  bootstrap_iter=1000_