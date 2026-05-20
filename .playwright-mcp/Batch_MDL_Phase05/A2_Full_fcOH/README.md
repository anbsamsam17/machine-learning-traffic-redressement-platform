# A2_Full_fcOH

_Feature-engineering ablation A2 — Full 10 (FC retire) + fc_1..fc_5_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (15 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| TMJOFCDTV | OUI (z-score) |
| TMJOFCDPL | OUI (z-score) |
| avg_distance_before_m | OUI (z-score) |
| avg_distance_after_m | OUI (z-score) |
| avg_min_distance_m | OUI (z-score) |
| truck_avg_distance_m | OUI (z-score) |
| truck_avg_distance_before_m | OUI (z-score) |
| truck_avg_distance_after_m | OUI (z-score) |
| truck_avg_min_distance_m | OUI (z-score) |
| fc_1 | NON |
| fc_2 | NON |
| fc_3 | NON |
| fc_4 | NON |
| fc_5 | NON |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- robust_scaled: `False`

## Sample weighting
- INACTIF (poids = 1 partout)

## Metriques validation
- Capteurs tolerance inclus: **2291/3632** (63.1%)
- Erreur relative p80: **28.52%**
- Erreur relative mediane: 13.39%
- R2: 0.6919
- RMSE: 0.6538  |  MAE: 0.3646
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [61.4, 64.68]
- p80: [27.4751, 29.6602]
- r2: [0.642909, 0.739568]

- Train: 190.5s