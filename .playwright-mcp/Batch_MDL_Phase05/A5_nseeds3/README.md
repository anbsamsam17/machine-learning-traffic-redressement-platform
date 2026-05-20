# A5_nseeds3

**Worker:** A5 (port 7005)
**Phase 05:** training tricks — multi-seed ensemble
**n_seeds:** 3  (seed indices: [0, 1, 2])

## Aggregate metrics (mean ± std across seeds)
| Metric | Mean | Std | Values |
| ------ | ---- | --- | ------ |
| tol_in_pct | 60.1333 | 0.7343 | [60.3, 60.77, 59.33] |
| err_rel_p80 | 29.4185 | 0.592 | [29.0602, 29.0936, 30.1018] |
| r_squared | 0.6802 | 0.0147 | [0.679, 0.6954, 0.6661] |
| geh_pct_below_5 | 100.0 | 0.0 | [100.0, 100.0, 100.0] |

Per-seed metrics live in sibling directories: `A5_nseeds3_seed0/`, `A5_nseeds3_seed1/`, `A5_nseeds3_seed2/`.

Full aggregate JSON also at `A5_nseeds3_summary.json` in the batch root.