# A4_Full_recentX2

Dataset: `lyon_allyears.geojson` (3671 capteurs, 2019-2025)
Sortie: `TxPen` — taux de pénétration FCD/Boucle Comptage TV

## Phase 5 — Worker A4 pondération axis
| Champ | Valeur |
|---|---|
| weighting | `flag_recent_year x2.0` |
| use_flag_permanent_weighting | `False` |
| flag_priority_weight | `1.0` |
| use_flag_recent_year_weighting | `True` |
| recent_year_priority_weight | `2.0` |
| use_log_flow_weighting | `False` |
| activation | `elu` |
| dropout | `0.025` |
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
- Capteurs tolérance inclus: **2075/3671** (56.5%)
- Erreur relative p80: **31.51%**
- Erreur relative médiane: 15.73%
- R²: 0.6614
- RMSE: 0.7068
- MAE: 0.4166
- GEH < 5: 100.0%
- N validation rows: 3671
- Durée d'entraînement: 206.6s

## CI95 (bootstrap=1000)
- r2: [0.6238, 0.7003]
- p80: [30.7984, 32.7058]
- tol_in_pct: [55.0000, 58.0500]