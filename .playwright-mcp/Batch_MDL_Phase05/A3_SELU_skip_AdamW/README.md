# A3_SELU_skip_AdamW

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV

## Phase 5 — Architecture ablation
| Champ | Valeur |
|---|---|
| activation | `selu` |
| optimizer | `adamw` |
| weight_decay | `0.0001` |
| clipnorm | `None` |
| use_skip_connection | `True` |
| norm_layer | `None` |
| dropout_schedule | `uniform` |
| dropout | `0.025` |
| min_nb_epochs | `1000` |
| max_epochs | `1250` |
| neurons_factors | `[3.0, 2.0, 1.0]` |
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
- Capteurs tolérance inclus: **2103/3671** (57.3%)
- Erreur relative p80: **32.86%**
- Erreur relative médiane: 14.91%
- R²: 0.6533
- RMSE: 0.7152
- MAE: 0.412
- GEH < 5: 100.0%
- N validation rows: 3671
- Durée d'entraînement: 208.7s