# A6_robustScaler_permX2

Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Stack
- loss: `mse`
- scaler: `robust` (note: API plumbing best-effort)

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
- Capteurs tolerance inclus: **2207/3632** (60.8%)
- Erreur relative p80: **29.11%**
- Erreur relative mediane: 14.13%
- R2: 0.6806
- RMSE: 0.6657  |  MAE: 0.3777
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [59.11, 62.39]
- p80: [28.0012, 29.9011]
- r2: [0.631854, 0.728623]

- Train: 105.6s