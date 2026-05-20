# A6v2_tolerance_permX2_recX2_d02

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV

## Phase 5 — Architecture ablation
| Champ | Valeur |
|---|---|
| activation | `elu` |
| optimizer | `adam` |
| weight_decay | `0.0` |
| clipnorm | `None` |
| use_skip_connection | `False` |
| norm_layer | `None` |
| dropout_schedule | `uniform` |
| dropout | `0.02` |
| min_nb_epochs | `1000` |
| max_epochs | `1250` |
| neurons_factors | `[3, 2, 1]` |
| batch_size | `256` |
| learning_rate | `0.01` |
| test_size | `0.05` |

## Entrées (11 features)
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

## Métriques de validation (sur 3671 capteurs)
- Capteurs tolérance inclus: **2364/3671** (64.4%)
- Erreur relative p80: **29.0%**
- Erreur relative médiane: 12.72%
- R²: 0.6716
- RMSE: 0.696
- MAE: 0.3665
- GEH < 5: 100.0%
- N validation rows: 3671
- Durée d'entraînement: 303.4s