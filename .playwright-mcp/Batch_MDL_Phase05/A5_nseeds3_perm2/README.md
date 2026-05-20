# A5_nseeds3_perm2

**Worker:** A5 (port 7005)
**Phase 05:** training tricks — multi-seed ensemble
**n_seeds:** 3  (seed indices: [0, 1, 2])

## Aggregate metrics (mean ± std across seeds)
| Metric | Mean | Std | Values |
| ------ | ---- | --- | ------ |
| tol_in_pct | 60.5667 | 0.8436 | [60.77, 61.29, 59.64] |
| err_rel_p80 | 29.205 | 0.6746 | [28.9511, 28.6941, 29.9697] |
| r_squared | 0.6824 | 0.0141 | [0.6806, 0.6973, 0.6693] |
| geh_pct_below_5 | 100.0 | 0.0 | [100.0, 100.0, 100.0] |

Per-seed metrics live in sibling directories: `A5_nseeds3_perm2_seed0/`, `A5_nseeds3_perm2_seed1/`, `A5_nseeds3_perm2_seed2/`.

Full aggregate JSON also at `A5_nseeds3_perm2_summary.json` in the batch root.