# A3_AdamW_DropDec_clipnorm

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de penetration FCD/Boucle Comptage TV

## Phase 5 — Architecture ablation
| Champ | Valeur |
|---|---|
| activation | `elu` |
| optimizer | `adamw` |
| weight_decay | `0.0001` |
| clipnorm | `1.0` |
| use_skip_connection | `False` |
| norm_layer | `None` |
| dropout_schedule | `decreasing` |
| dropout | `0.025` |
| min_nb_epochs | `1000` |
| max_epochs | `1250` |
| neurons_factors | `[3.0, 2.0, 1.0]` |
| batch_size | `256` |
| learning_rate | `0.01` |
| test_size | `0.05` |

## Entrees (11 features)
```
- year_mapped
- TMJOFCDTV
- TMJOFCDPL
- functional_class
- avg_distance_before_m
- avg_distance_after_m
- avg_min_distance_m
- truck_avg_distance_m
- truck_avg_distance_before_m
- truck_avg_distance_after_m
- truck_avg_min_distance_m
```

## Metriques de validation (sur 3671 capteurs)
- Capteurs tolerance inclus: **2190/3671** (59.7%)
- Erreur relative p80: **30.15%**
- Erreur relative mediane: 14.52%
- R2: 0.6751
- RMSE: 0.6923
- MAE: 0.3931
- GEH < 5: 100.0%
- N validation rows: 3671
- Duree d'entrainement: 194.7s