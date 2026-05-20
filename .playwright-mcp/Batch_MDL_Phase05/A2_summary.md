# Worker A2 — Feature-engineering ablation (12 configs)

Phase 0-5, baseline locked: `mse`, `dropout=0.025`, `min_epochs=1000`,
`max_epochs=1250`, `neurons_factors=[3,2,1]`, `lr=0.01`, `batch_size=256`,
`elu`, `test_size=0.05`, no sample-weighting.

Port: **7002**. Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon TV, 3632 capteurs, 2019-2025), in-sample validation.

Pre-processing of the geojson (`preprocess_A2.py`) adds:
- `flag_permanent` (1 if Type Compteur == Permanent), `flag_recent_year` (year==2025).
- `year_mapped` (2019..2025 -> 1..7), `Annee` alias.
- `ratio_PLTV = TMJOFCDPL / max(TMJOFCDTV, 1)`.
- `log_TMJOFCDTV = log1p(max(TMJOFCDTV, 0))`, idem `log_TMJOFCDPL`.
- one-hot `fc_1..fc_5` from `functional_class`.
- `rs_*` = RobustScaler-encoded copies (median, IQR/1.349) of the 9 numeric distances/flows for config #7.
- `yemb1..yemb3` = sinusoidal positional encoding of `year_mapped` (dim=3 emulation for config #8).

## Notes on emulated knobs

- **Config #7 (RobustScaler)** — `normalize()` supports `robust` internally
  but `training_pipeline.py` hard-wires `"standard"`. We pre-encode 9 features
  via `(x - median)/(IQR/1.349)` and feed them with `on_off_norm=False`.
- **Config #8 (year_embedding dim=3)** — `use_year_embedding` is wired in
  `model_builder.py` but ignored by `training_pipeline.py`. Emulated with
  three sinusoidal positional encodings of `year_mapped`.

## Results

| # | run_name | n_in | tol_in % | p80 % | R^2 | RMSE | MAE | GEH<5 % | train_s | broken? |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | A2_Full_logTV | 12 | 60.93 | 29.03 | 0.6743 | 0.6723 | 0.3744 | 100.00 | 155.6 | no |
| 2 | A2_Full_logPL | 12 | 57.98 | 31.42 | 0.6609 | 0.6860 | 0.3976 | 100.00 | 382.7 | no |
| 3 | A2_Full_logBoth | 13 | 59.69 | 28.97 | 0.6734 | 0.6732 | 0.3793 | 100.00 | 367.0 | no |
| 4 | A2_Full_ratioPLTV | 12 | 61.01 | 29.27 | 0.6806 | 0.6657 | 0.3767 | 100.00 | 195.5 | no |
| 5 | A2_Full_fcOH | 15 | 63.08 | 28.52 | 0.6919 | 0.6538 | 0.3646 | 100.00 | 190.5 | no |
| 6 | A2_Full_ratio_fcOH | 16 | 63.11 | 28.10 | 0.6985 | 0.6468 | 0.3611 | 100.00 | 190.4 | no |
| 7 | A2_Full_robust | 11 | 62.14 | 27.73 | 0.6822 | 0.6640 | 0.3718 | 100.00 | 185.5 | no |
| 8 | A2_Full_yearEmb3 | 14 | 60.44 | 29.72 | 0.6840 | 0.6622 | 0.3802 | 100.00 | 195.5 | no |
| 9 | A2_Compact6_logTV_fcOH | 9 | 57.13 | 29.97 | 0.6468 | 0.7000 | 0.4027 | 100.00 | 185.4 | no |
| 10 | A2_Compact6_ratio_robust | 6 | 58.43 | 29.19 | 0.6527 | 0.6942 | 0.3968 | 100.00 | 170.4 | no |
| 11 | A2_Min4 | 4 | 53.08 | 32.48 | 0.6248 | 0.7216 | 0.4362 | 100.00 | 185.4 | no |
| 12 | A2_Min5_ratio | 5 | 53.41 | 31.58 | 0.6358 | 0.7109 | 0.4265 | 100.00 | 180.4 | no |

## CI95 (bootstrap 1000 iter)

| # | run_name | tol_in_pct | p80 | r2 |
|---|---|---|---|---|
| 1 | A2_Full_logTV | [59.33, 62.58] | [28.0014, 30.1491] | [0.622267, 0.724375] |
| 2 | A2_Full_logPL | [56.36, 59.58] | [30.1474, 32.4565] | [0.612293, 0.708374] |
| 3 | A2_Full_logBoth | [58.15, 61.34] | [28.1018, 29.8847] | [0.623994, 0.722401] |
| 4 | A2_Full_ratioPLTV | [59.36, 62.75] | [28.1476, 30.3555] | [0.631596, 0.727589] |
| 5 | A2_Full_fcOH | [61.4, 64.68] | [27.4751, 29.6602] | [0.642909, 0.739568] |
| 6 | A2_Full_ratio_fcOH | [61.37, 64.65] | [26.8149, 29.0656] | [0.64951, 0.745194] |
| 7 | A2_Full_robust | [60.49, 63.74] | [26.6999, 28.7916] | [0.633124, 0.730493] |
| 8 | A2_Full_yearEmb3 | [58.84, 62.22] | [28.5797, 30.9068] | [0.637046, 0.729677] |
| 9 | A2_Compact6_logTV_fcOH | [55.48, 58.78] | [28.9415, 30.9934] | [0.594566, 0.696315] |
| 10 | A2_Compact6_ratio_robust | [56.88, 60.13] | [28.4269, 30.2765] | [0.603489, 0.699239] |
| 11 | A2_Min4 | [51.35, 54.93] | [31.6391, 33.4792] | [0.578028, 0.671098] |
| 12 | A2_Min5_ratio | [51.73, 55.04] | [30.7427, 32.4189] | [0.588629, 0.682069] |

## Ranking by tol_in % (healthy only)

1. **A2_Full_ratio_fcOH** — tol_in=63.11%, p80=28.1, R^2=0.698523
2. **A2_Full_fcOH** — tol_in=63.08%, p80=28.52, R^2=0.691918
3. **A2_Full_robust** — tol_in=62.14%, p80=27.73, R^2=0.682218
4. **A2_Full_ratioPLTV** — tol_in=61.01%, p80=29.27, R^2=0.680615
5. **A2_Full_logTV** — tol_in=60.93%, p80=29.03, R^2=0.674269
6. **A2_Full_yearEmb3** — tol_in=60.44%, p80=29.72, R^2=0.683969
7. **A2_Full_logBoth** — tol_in=59.69%, p80=28.97, R^2=0.67339
8. **A2_Compact6_ratio_robust** — tol_in=58.43%, p80=29.19, R^2=0.652696
9. **A2_Full_logPL** — tol_in=57.98%, p80=31.42, R^2=0.660865
10. **A2_Compact6_logTV_fcOH** — tol_in=57.13%, p80=29.97, R^2=0.646795
11. **A2_Min5_ratio** — tol_in=53.41%, p80=31.58, R^2=0.635776
12. **A2_Min4** — tol_in=53.08%, p80=32.48, R^2=0.624756
