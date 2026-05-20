# A3_AdamW_wd4_clipnorm1

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
| dropout_schedule | `uniform` |
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
- Capteurs tolerance inclus: **2224/3671** (60.6%)
- Erreur relative p80: **29.28%**
- Erreur relative mediane: 14.42%
- R2: 0.6932
- RMSE: 0.6728
- MAE: 0.3854
- GEH < 5: 100.0%
- N validation rows: 3671
- Duree d'entrainement: 213.9s