# A2_Full_robust

_Feature-engineering ablation A2 — Full 11 with RobustScaler-encoded numeric features (rs_*)_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (11 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| rs_TMJOFCDTV | NON |
| rs_TMJOFCDPL | NON |
| functional_class | NON |
| rs_avg_distance_before_m | NON |
| rs_avg_distance_after_m | NON |
| rs_avg_min_distance_m | NON |
| rs_truck_avg_distance_m | NON |
| rs_truck_avg_distance_before_m | NON |
| rs_truck_avg_distance_after_m | NON |
| rs_truck_avg_min_distance_m | NON |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- robust_scaled: `True`

## Sample weighting
- INACTIF (poids = 1 partout)

## Metriques validation
- Capteurs tolerance inclus: **2257/3632** (62.1%)
- Erreur relative p80: **27.73%**
- Erreur relative mediane: 13.97%
- R2: 0.6822
- RMSE: 0.664  |  MAE: 0.3718
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [60.49, 63.74]
- p80: [26.6999, 28.7916]
- r2: [0.633124, 0.730493]

- Train: 185.5s