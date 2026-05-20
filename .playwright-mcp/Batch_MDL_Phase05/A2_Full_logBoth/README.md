# A2_Full_logBoth

_Feature-engineering ablation A2 — Full 11 + log_TMJOFCDTV + log_TMJOFCDPL_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (13 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| TMJOFCDTV | OUI (z-score) |
| TMJOFCDPL | OUI (z-score) |
| functional_class | NON |
| avg_distance_before_m | OUI (z-score) |
| avg_distance_after_m | OUI (z-score) |
| avg_min_distance_m | OUI (z-score) |
| truck_avg_distance_m | OUI (z-score) |
| truck_avg_distance_before_m | OUI (z-score) |
| truck_avg_distance_after_m | OUI (z-score) |
| truck_avg_min_distance_m | OUI (z-score) |
| log_TMJOFCDTV | OUI (z-score) |
| log_TMJOFCDPL | OUI (z-score) |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- robust_scaled: `False`

## Sample weighting
- INACTIF (poids = 1 partout)

## Metriques validation
- Capteurs tolerance inclus: **2168/3632** (59.7%)
- Erreur relative p80: **28.97%**
- Erreur relative mediane: 14.3%
- R2: 0.6734
- RMSE: 0.6732  |  MAE: 0.3793
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [58.15, 61.34]
- p80: [28.1018, 29.8847]
- r2: [0.623994, 0.722401]

- Train: 367.0s