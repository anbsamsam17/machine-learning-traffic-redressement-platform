# A6_AdamW_skip_permX2_nseeds3

Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Stack
- loss: `mse`
- optimizer: `adamw` (weight_decay=0.0001)
- skip_connection: ON
- n_seeds: 3

## Weighting
- flag_permanent: True (x2.0)
- flag_recent_year: False (x2.0)

## Entrees (11 features)
| Feature | Normalise | Type |
|---|---|---|
| year_mapped | NON | Annee 2019..2025 -> 1..7 |
| TMJOFCDTV | OUI | numerique continu |
| TMJOFCDPL | OUI | numerique continu |
| functional_class | NON | categoriel int 1-5 |
| avg_distance_before_m | OUI | numerique continu |
| avg_distance_after_m | OUI | numerique continu |
| avg_min_distance_m | OUI | numerique continu |
| truck_avg_distance_m | OUI | numerique continu |
| truck_avg_distance_before_m | OUI | numerique continu |
| truck_avg_distance_after_m | OUI | numerique continu |
| truck_avg_min_distance_m | OUI | numerique continu |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`

## Metriques validation (in-sample)
- Capteurs tolerance inclus: **2258/3632** (62.2%)
- Erreur relative p80: **29.45%**
- Erreur relative mediane: 17.62%
- R2: 0.6716
- RMSE: 0.675  |  MAE: 0.4235
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [50.14, 53.44]
- p80: [31.0473, 32.8394]
- r2: [0.624692, 0.716534]

## Per-seed (n_seeds > 1)
- elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.0001_skip_seed0: R2=0.671636 RMSE=0.675 MAE=0.4235 p80=17.62
- elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.0001_skip_seed1: R2=0.706241 RMSE=0.6384 MAE=0.3671 p80=13.55
- elu_lr0.01_ep1000_mse_drp0.025_nf3.0x2.0x1.0_bs256_fmask_11111111111_adamw_wd0.0001_skip_seed2: R2=0.693055 RMSE=0.6526 MAE=0.3724 p80=13.71

- Train: 246.6s