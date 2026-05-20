# A3_SELU

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de penetration FCD/Boucle Comptage TV

## Phase 5 — Architecture ablation
| Champ | Valeur |
|---|---|
| activation | `selu` |
| optimizer | `adam` |
| weight_decay | `0.0` |
| clipnorm | `None` |
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
- Capteurs tolerance inclus: **2088/3671** (56.9%)
- Erreur relative p80: **35.46%**
- Erreur relative mediane: 15.35%
- R2: 0.6436
- RMSE: 0.7251
- MAE: 0.4185
- GEH < 5: 100.0%
- N validation rows: 3671
- Duree d'entrainement: 190.0s