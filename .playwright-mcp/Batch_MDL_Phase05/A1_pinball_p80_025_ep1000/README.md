# A1_pinball_p80_025_ep1000

Dataset: `BCFCDREF_AllYears_TV.geojson` (Grand Lyon, 3632 capteurs, 2019-2025)
Sortie: `TxPen` (taux de penetration FCD/Boucle Comptage TV)

## Tables
- Apprentissage : `C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio\.playwright-mcp\DataApprentissage\GrandLyon\BCFCDREF_AllYears_TV.geojson`
- Validation   : `C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio\.playwright-mcp\DataApprentissage\GrandLyon\BCFCDREF_AllYears_TV.geojson` (in-sample)

## Entrees (11 features)
| Feature | Normalise | Type |
|---|---|---|
| year_mapped | NON | Annee 2019..2025 -> 1..7 |
| TMJOFCDTV | OUI (z-score) | numerique continu |
| TMJOFCDPL | OUI (z-score) | numerique continu |
| functional_class | NON | categoriel int 1-5 |
| avg_distance_before_m | OUI (z-score) | numerique continu |
| avg_distance_after_m | OUI (z-score) | numerique continu |
| avg_min_distance_m | OUI (z-score) | numerique continu |
| truck_avg_distance_m | OUI (z-score) | numerique continu |
| truck_avg_distance_before_m | OUI (z-score) | numerique continu |
| truck_avg_distance_after_m | OUI (z-score) | numerique continu |
| truck_avg_min_distance_m | OUI (z-score) | numerique continu |

## Hyperparametres
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `pinball_p80`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- target_log_transform: `False`

## Sample weighting
- INACTIF (poids = 1 partout, pas de flag_permanent / flag_recent_year)

## Metriques validation
- Capteurs tolerance inclus: **1693/3632** (46.6%)
- Erreur relative p80: **33.16%**
- Erreur relative mediane: 20.95%
- R2: 0.6230
- RMSE: 0.7232  |  MAE: 0.4777
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [44.99, 48.16]
- p80: [32.18, 34.1688]
- r2: [0.577812, 0.665128]

- Train: 183.0s