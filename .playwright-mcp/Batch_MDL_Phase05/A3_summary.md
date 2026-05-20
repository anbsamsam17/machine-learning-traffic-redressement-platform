# Worker A3 — Phase 5 architecture ablation (12 configs)

Port: 7003 · Dataset: lyon_allyears.geojson (3671 capteurs, 2019-2025)
· Feature set: 11 features (Full FCD + dist + truck) · Sortie: TxPen

Baseline (Phase 3 — Batch_MDL/A5_Full_drp025, Adam, no wd, no skip, no norm):
R²=0.805, p80≈24.6%, tol≈63% (training was on test_size=0).

NOTE: Phase 5 baseline uses `test_size=0.05` so EarlyStopping monitors
val_loss on a 184-row split. This narrows the convergence window and is
the main reason every Phase 5 variant trails the Phase 3 baseline by
~0.10–0.16 R² points. The ablation is still apples-to-apples internally.

## Verdict (architecture ablation, ranked by p80 ↓ then R² ↑)

| Rank | Variant | Delta vs baseline (A3_AdamW_wd4) |
|---|---|---|
| 1 | BatchNorm | p80 -1.95pp, R² +0.054 |
| 2 | AdamW wd1e-4 + clipnorm | p80 -1.41pp, R² +0.028 |
| 3 | Dropout decreasing | p80 -0.78pp, R² +0.024 |
| 4 | LayerNorm / Skip+LN / AdamW+Skip+LN | small +R² gain, similar tol |
| 5 | AdamW wd1e-4 / wd1e-3 alone | baseline-equal |
| 6 | Skip alone | tol drops to 50.6% — REGRESSION |
| 7 | SELU / SELU+Skip+AdamW | worst (R²≈0.65) |

Bug discovered + fixed mid-batch: the worker's `actual = sub_dirs[0].name`
picked the FIRST model alphabetically from the session's shared models
directory, so every run after `A3_AdamW_wd4` was evaluated against the
WRONG model (giving byte-identical metrics across architectures). Fixed
by sorting `sub_dirs` by mtime DESC. The first 4 configs were
re-evaluated against their correct models (`reeval_A3_initial.py`).

Two prior changes to the API itself were also required to make Phase 5
work end-to-end:
1. `apps/api/app/services/ml/training_pipeline.py`: plumb the new P3
   axes (optimizer / weight_decay / use_skip_connection / dropout_schedule
   / clipnorm / norm_layer) from `config` -> `generate_all_combinations`
   -> `_train_single` -> `build_model`. Before this fix the dataclass
   carried the fields but `build_model` was called without them, so the
   axes were COSMETIC ONLY (every "adamw" config was secretly trained as
   Adam). The model_name suffix `_adamw_wd0.0001` now reflects the real
   optimizer used.
2. Same file, fix `NameError: name 'logger' is not defined` at the
   deprecated-flag warning site (used the module-private `_logger`).

## Top 3 par p80 (err_p80_pct)
- **A3_BatchNorm** — p80=28.74%, R²=0.7187, tol=2263/3671
- **A3_AdamW_wd4_clipnorm1** — p80=29.28%, R²=0.6932, tol=2224/3671
- **A3_Drop_decreasing** — p80=29.91%, R²=0.6894, tol=2230/3671

## Top 3 par tol_inclus%
- **A3_BatchNorm** — tol=2263/3671 (61.6%), p80=28.74%, R²=0.7187
- **A3_Drop_decreasing** — tol=2230/3671 (60.7%), p80=29.91%, R²=0.6894
- **A3_AdamW_wd4_clipnorm1** — tol=2224/3671 (60.6%), p80=29.28%, R²=0.6932

## Table complète
| Run | Config | tol_in / total (%) | p80 (%) | R² | RMSE | MAE | GEH<5 % | Train s |
|---|---|---|---|---|---|---|---|---|
| A3_AdamW_DropDec_clipnorm | opt=adamw, wd=0.0001, cn=1.0, drp_sched=decreasing | 2190/3671 (59.7%) | 30.15 | 0.6751 | 0.6923 | 0.3931 | 100.0 | 194.7 |
| A3_AdamW_Skip_LayerNorm | opt=adamw, wd=0.0001, skip, norm=layer | 2128/3671 (58.0%) | 31.22 | 0.6797 | 0.6874 | 0.4021 | 100.0 | 222.2 |
| A3_AdamW_wd3 | opt=adamw, wd=0.001 | 2151/3671 (58.6%) | 30.72 | 0.6649 | 0.703 | 0.403 | 100.0 | 365.2 |
| A3_AdamW_wd4 | opt=adamw, wd=0.0001 | 2151/3671 (58.6%) | 30.69 | 0.6650 | 0.703 | 0.4031 | 100.0 | 136.1 |
| A3_AdamW_wd4_clipnorm1 | opt=adamw, wd=0.0001, cn=1.0 | 2224/3671 (60.6%) | 29.28 | 0.6932 | 0.6728 | 0.3854 | 100.0 | 213.9 |
| A3_BatchNorm | norm=batch | 2263/3671 (61.6%) | 28.74 | 0.7187 | 0.6442 | 0.3719 | 100.0 | 229.2 |
| A3_Drop_decreasing | drp_sched=decreasing | 2230/3671 (60.7%) | 29.91 | 0.6894 | 0.6769 | 0.3842 | 100.0 | 211.1 |
| A3_LayerNorm | norm=layer | 2121/3671 (57.8%) | 31.42 | 0.6861 | 0.6805 | 0.4061 | 100.0 | 223.0 |
| A3_SELU | act=selu | 2088/3671 (56.9%) | 35.46 | 0.6436 | 0.7251 | 0.4185 | 100.0 | 190.0 |
| A3_SELU_skip_AdamW | act=selu, opt=adamw, wd=0.0001, skip | 2103/3671 (57.3%) | 32.86 | 0.6533 | 0.7152 | 0.412 | 100.0 | 208.7 |
| A3_Skip | skip | 1856/3671 (50.6%) | 33.02 | 0.6603 | 0.7079 | 0.4458 | 100.0 | 244.7 |
| A3_Skip_LayerNorm | skip, norm=layer | 2129/3671 (58.0%) | 31.23 | 0.6797 | 0.6874 | 0.4021 | 100.0 | 223.0 |