# A6_AdamW_skip_huber_permX3

Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Stack
- loss: `huber`
- optimizer: `adamw` (weight_decay=0.0001)
- skip_connection: ON

## Weighting
- flag_permanent: True (x3.0)
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
- Capteurs tolerance inclus: **2045/3632** (56.3%)
- Erreur relative p80: **30.52%**
- Erreur relative mediane: 15.89%
- R2: 0.6622
- RMSE: 0.6846  |  MAE: 0.4004
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [54.68, 57.96]
- p80: [29.7313, 31.5854]
- r2: [0.612349, 0.712011]

- Train: 91.5s