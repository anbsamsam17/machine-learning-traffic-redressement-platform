# A1_huber_025_ep1000

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
- activation: `elu`  |  learning_rate: `0.01`  |  loss: `huber`
- dropout: `0.025`  |  neurons_factors: `[3.0, 2.0, 1.0]`
- batch_size: `256`  |  min_nb_epochs: `1000`  |  max_epochs: `1250`
- test_size: `0.05`  |  patience (EarlyStopping): `30`  |  restore_best_weights: `True`
- target_log_transform: `False`

## Sample weighting
- INACTIF (poids = 1 partout, pas de flag_permanent / flag_recent_year)

## Metriques validation
- Capteurs tolerance inclus: **2235/3632** (61.5%)
- Erreur relative p80: **28.51%**
- Erreur relative mediane: 13.79%
- R2: 0.6676
- RMSE: 0.6792  |  MAE: 0.3712
- GEH < 5: 100.0%
- N validation: 3632

## CI95 (bootstrap 1000 iter)
- tol_in_pct: [59.83, 63.19]
- p80: [27.6846, 29.6905]
- r2: [0.614341, 0.719832]

- Train: 303.6s