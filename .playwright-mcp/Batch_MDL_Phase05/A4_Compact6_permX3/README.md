# A4_Compact6_permX3

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV

## Phase 5 — Worker A4 pondération axis
| Champ | Valeur |
|---|---|
| weighting | `flag_permanent x3.0` |
| use_flag_permanent_weighting | `True` |
| flag_priority_weight | `3.0` |
| use_flag_recent_year_weighting | `False` |
| recent_year_priority_weight | `1.0` |
| use_log_flow_weighting | `False` |
| activation | `elu` |
| dropout | `0.025` |
| min_nb_epochs | `1000` |
| max_epochs | `1250` |
| neurons_factors | `[3, 2, 1]` |
| batch_size | `256` |
| learning_rate | `0.01` |
| test_size | `0.05` |

## Entrées (6 features)
```
- year_mapped
- TMJOFCDTV
- TMJOFCDPL
- functional_class
- avg_min_distance_m
- truck_avg_min_distance_m
```

## Métriques de validation (sur 3671 capteurs)
- Capteurs tolérance inclus: **2014/3671** (54.9%)
- Erreur relative p80: **31.81%**
- Erreur relative médiane: 16.3%
- R²: 0.6471
- RMSE: 0.7215
- MAE: 0.4253
- GEH < 5: 100.0%
- N validation rows: 3671
- Durée d'entraînement: 109.8s

## CI95 (bootstrap=1000)
- r2: [0.6074, 0.6873]
- p80: [30.8345, 32.7637]
- tol_in_pct: [53.2800, 56.4200]