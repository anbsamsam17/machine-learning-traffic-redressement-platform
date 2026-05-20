# A2_Compact6_logTV_fcOH

_Feature-engineering ablation A2 — [year, TMJOFCDTV, log_TMJOFCDTV, TMJOFCDPL, fc_1..fc_5]_

Dataset: `A2_TV_features.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Entrees (9 features)
| Feature | Normalise |
|---|---|
| year_mapped | NON |
| TMJOFCDTV | OUI (z-score) |
| log_TMJOFCDTV | OUI (z-score) |
| TMJOFCDPL | OUI (z-score) |
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
- Capteurs tolerance inclus: **2075/3632** (57.1%)
- Erreur relative p80: **29.97%**
- Erreur relative mediane: 15.58%
- R2: 0.6468
- RMSE: 0.7  |  MAE: 0.4027
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [55.48, 58.78]
- p80: [28.9415, 30.9934]
- r2: [0.594566, 0.696315]

- Train: 185.4s