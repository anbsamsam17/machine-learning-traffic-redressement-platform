# A3_Skip_LayerNorm

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de penetration FCD/Boucle Comptage TV

## Phase 5 — Architecture ablation
| Champ | Valeur |
|---|---|
| activation | `elu` |
| optimizer | `adam` |
| weight_decay | `0.0` |
| clipnorm | `None` |
| use_skip_connection | `True` |
| norm_layer | `layer` |
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
- Capteurs tolerance inclus: **2129/3671** (58.0%)
- Erreur relative p80: **31.23%**
- Erreur relative mediane: 15.03%
- R2: 0.6797
- RMSE: 0.6874
- MAE: 0.4021
- GEH < 5: 100.0%
- N validation rows: 3671
- Duree d'entrainement: 223.0s