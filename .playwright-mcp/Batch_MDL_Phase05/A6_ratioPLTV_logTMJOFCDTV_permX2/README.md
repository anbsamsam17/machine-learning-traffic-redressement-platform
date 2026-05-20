# A6_ratioPLTV_logTMJOFCDTV_permX2

Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Stack
- loss: `mse`
- feature_engineering.add_pl_tv_ratio: ON (ratio_PLTV)
- feature_engineering.log_transform_cols: ['TMJOFCDTV']

## Weighting
- flag_permanent: True (x2.0)
- flag_recent_year: False (x2.0)

## Entrees (13 features)
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
| ratio_PLTV | OUI | derive TMJOFCDPL/max(TMJOFCDTV,1) |
| log_TMJOFCDTV | OUI | derive log1p |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`

## Metriques validation (in-sample)
- Capteurs tolerance inclus: **2229/3632** (61.4%)
- Erreur relative p80: **27.83%**
- Erreur relative mediane: 13.93%
- R2: 0.6847
- RMSE: 0.6614  |  MAE: 0.3682
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [59.66, 63.16]
- p80: [26.811, 28.8945]
- r2: [0.635643, 0.732705]

- Train: 113.1s