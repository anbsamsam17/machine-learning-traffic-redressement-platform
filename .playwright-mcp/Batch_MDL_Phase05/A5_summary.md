# A5 — Phase 05 batch summary (training tricks)

Worker A5, port 7005. Baseline: Full 11 features, mse, drp=0.025,
ep=1000, no weighting, neurons=[3,2,1], lr=0.01, batch=256, elu, test=0.05.

Total wall-clock: **1710s** (28m 30s).

| # | Name | tol% | p80% | R² | GEH<5% | broken? | wall(s) |
| - | ---- | ---- | ---- | -- | ------ | ------- | ------- |
| 1 | A5_HardMining | 60.3 | 29.0602 | 0.679003 | 100.0 |  | None |
| 2 | A5_Curriculum | 53.41 | 33.5633 | 0.622347 | 100.0 |  | 231.6 |
| 3 | A5_HardMining_Curriculum | 53.77 | 33.4416 | 0.622515 | 100.0 |  | 247.4 |
| 4 | A5_QuantileHead | 60.3 | 29.0602 | 0.679003 | 100.0 |  | 183.4 |
| 5 | A5_PinballP80_LogTarget | 46.61 | 33.1744 | 0.623026 | 100.0 |  | 183.1 |
| 6 | A5_nseeds3 | 60.1333 | 29.4185 | 0.6802 | 100.0 |  | None |
| 7 | A5_nseeds3_perm2 | 60.5667 | 29.205 | 0.6824 | 100.0 |  | None |
| 8 | A5_BootstrapCI95 | 60.3 | 29.0584 | 0.679003 | 100.0 |  | 165.7 |
| 9 | A5_kfold_k5 | 60.3 | 29.0602 | 0.679003 | 100.0 | yes | 177.6 |
| 10 | A5_HardMining_perm2 | 60.77 | 28.9511 | 0.680557 | 100.0 |  | 276.5 |
| 11 | A5_Curriculum_perm2 | 52.53 | 33.433 | 0.622775 | 100.0 |  | 124.1 |
| 12 | A5_Curriculum_recent2 | 52.23 | 33.3102 | 0.616302 | 100.0 |  | 124.1 |

## Best config: `A5_HardMining_perm2`  (composite score = 128.83)

## Issues
- **A5_kfold_k5**: k-fold endpoint API bug: name 'logger' is not defined (all 5 folds failed)

## Per-config detail (CI95 + n_seeds aggregates)

### 1. A5_HardMining
- overrides: `{'use_hard_example_mining': True}`
- CI95: `{'r2': [0.630336, 0.726799], 'p80': [27.9614, 30.1591], 'tol_in_pct': [58.59, 61.95]}`

### 2. A5_Curriculum
- overrides: `{'use_curriculum': True}`
- CI95: `{'r2': [0.574116, 0.668552], 'p80': [32.6765, 34.4502], 'tol_in_pct': [51.71, 55.18]}`

### 3. A5_HardMining_Curriculum
- overrides: `{'use_hard_example_mining': True, 'use_curriculum': True}`
- CI95: `{'r2': [0.574018, 0.668884], 'p80': [32.342, 34.5413], 'tol_in_pct': [52.06, 55.45]}`

### 4. A5_QuantileHead
- overrides: `{'use_quantile_head': True}`
- CI95: `{'r2': [0.630336, 0.726799], 'p80': [27.9614, 30.1591], 'tol_in_pct': [58.59, 61.95]}`

### 5. A5_PinballP80_LogTarget
- overrides: `{'losses': ['pinball_p80'], 'target_log_transform': True}`
- CI95: `{'r2': [0.577812, 0.665128], 'p80': [32.18, 34.1688], 'tol_in_pct': [44.99, 48.16]}`

### 6. A5_nseeds3
- overrides: `{'n_seeds': 3}`
- n_seeds aggregate:
  ```json
  {
    "config_name": "A5_nseeds3",
    "n_seeds": 3,
    "seeds": [
      0,
      1,
      2
    ],
    "tol_in_pct": {
      "mean": 60.1333,
      "std": 0.7343,
      "n": 3,
      "values": [
        60.3,
        60.77,
        59.33
      ]
    },
    "err_rel_p80": {
      "mean": 29.4185,
      "std": 0.592,
      "n": 3,
      "values": [
        29.0602,
        29.0936,
        30.1018
      ]
    },
    "r_squared": {
      "mean": 0.6802,
      "std": 0.0147,
      "n": 3,
      "values": [
        0.679,
        0.6954,
        0.6661
      ]
    },
    "geh_pct_below_5": {
      "mean": 100.0,
      "std": 0.0,
      "n": 3,
      "values": [
        100.0,
        100.0,
        100.0
      ]
    }
  }
  ```

### 7. A5_nseeds3_perm2
- overrides: `{'n_seeds': 3, 'use_flag_permanent_weighting': True, 'flag_priority_weight': 2.0}`
- n_seeds aggregate:
  ```json
  {
    "config_name": "A5_nseeds3_perm2",
    "n_seeds": 3,
    "seeds": [
      0,
      1,
      2
    ],
    "tol_in_pct": {
      "mean": 60.5667,
      "std": 0.8436,
      "n": 3,
      "values": [
        60.77,
        61.29,
        59.64
      ]
    },
    "err_rel_p80": {
      "mean": 29.205,
      "std": 0.6746,
      "n": 3,
      "values": [
        28.9511,
        28.6941,
        29.9697
      ]
    },
    "r_squared": {
      "mean": 0.6824,
      "std": 0.0141,
      "n": 3,
      "values": [
        0.6806,
        0.6973,
        0.6693
      ]
    },
    "geh_pct_below_5": {
      "mean": 100.0,
      "std": 0.0,
      "n": 3,
      "values": [
        100.0,
        100.0,
        100.0
      ]
    }
  }
  ```

### 8. A5_BootstrapCI95
- CI95: `{'r2': [0.629006, 0.726449], 'p80': [27.9577, 30.1591], 'tol_in_pct': [58.67, 61.92]}`

### 9. A5_kfold_k5
- CI95: `{'r2': [0.630336, 0.726799], 'p80': [27.9614, 30.1591], 'tol_in_pct': [58.59, 61.95]}`

### 10. A5_HardMining_perm2
- overrides: `{'use_hard_example_mining': True, 'use_flag_permanent_weighting': True, 'flag_priority_weight': 2.0}`
- CI95: `{'r2': [0.631854, 0.728623], 'p80': [28.0012, 29.9011], 'tol_in_pct': [59.11, 62.39]}`

### 11. A5_Curriculum_perm2
- overrides: `{'use_curriculum': True, 'use_flag_permanent_weighting': True, 'flag_priority_weight': 2.0}`
- CI95: `{'r2': [0.573886, 0.669319], 'p80': [32.4794, 34.3866], 'tol_in_pct': [50.88, 54.21]}`

### 12. A5_Curriculum_recent2
- overrides: `{'use_curriculum': True, 'use_flag_recent_year_weighting': True, 'recent_year_priority_weight': 2.0}`
- CI95: `{'r2': [0.568515, 0.661907], 'p80': [32.4627, 34.1576], 'tol_in_pct': [50.5, 53.83]}`