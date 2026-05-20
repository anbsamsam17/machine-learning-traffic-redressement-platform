# A2_Min5_ratio

_Feature-engineering ablation A2 — [year, TMJOFCDTV, TMJOFCDPL, ratio_PLTV, functional_class]_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (5 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| TMJOFCDTV | OUI (z-score) |
| TMJOFCDPL | OUI (z-score) |
| ratio_PLTV | OUI (z-score) |
| functional_class | NON |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `mse`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- robust_scaled: `False`

## Sample weighting
- INACTIF (poids = 1 partout)

## Metriques validation
- Capteurs tolerance inclus: **1940/3632** (53.4%)
- Erreur relative p80: **31.58%**
- Erreur relative mediane: 17.15%
- R2: 0.6358
- RMSE: 0.7109  |  MAE: 0.4265
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [51.73, 55.04]
- p80: [30.7427, 32.4189]
- r2: [0.588629, 0.682069]

- Train: 180.4s