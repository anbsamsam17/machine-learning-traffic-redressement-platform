# A2_Compact6_ratio_robust

_Feature-engineering ablation A2 — [year, rs_TMJOFCDTV, rs_TMJOFCDPL, ratio_PLTV, functional_class, rs_avg_min_distance_m]_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (6 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| rs_TMJOFCDTV | NON |
| rs_TMJOFCDPL | NON |
| ratio_PLTV | OUI (z-score) |
| functional_class | NON |
| rs_avg_min_distance_m | NON |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- robust_scaled: `True`

## Sample weighting
- INACTIF (poids = 1 partout)

## Metriques validation
- Capteurs tolerance inclus: **2122/3632** (58.4%)
- Erreur relative p80: **29.19%**
- Erreur relative mediane: 15.3%
- R2: 0.6527
- RMSE: 0.6942  |  MAE: 0.3968
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [56.88, 60.13]
- p80: [28.4269, 30.2765]
- r2: [0.603489, 0.699239]

- Train: 170.4s