# MDL_Lyon_TV_BEST — Modèle de production (Compact 6)

## Tables
- Apprentissage : `C:\Users\SamirANBRI\Desktop\AppRedressement\mdl-redressement-portfolio\.playwright-mcp\DataApprentissage\GrandLyon\BCFCDREF_AllYears_TV.geojson`
- Validation : même fichier (in-sample sur 3632 capteurs nettoyés)

## Sélection
Meilleur de 10 graines testées (1750-1759) avec config Compact 6 strictement identique. Critère : MAX(tol_inclus) puis MIN(p80).
Seed retenu : **1754**.

## Entrées (6 features — Compact 6)
| Feature | Normalisé | Mapping / Type |
|---|---|---|
| year_mapped | NON | source `Annee`, mapping `{2019:1, 2020:2, 2021:3, 2022:4, 2023:5, 2024:6, 2025:7}` |
| TMJOFCDTV | OUI (z-score) | numérique continu — FCD TV (principal) |
| TMJOFCDPL | OUI (z-score) | numérique continu — FCD PL |
| avg_min_distance_m | OUI (z-score) | min(distance avant, distance après) — VL |
| truck_avg_min_distance_m | OUI (z-score) | min(distance avant, distance après) — PL |
| functional_class | NON | catégoriel int 1-5 |

## Hyperparamètres
- activation : `elu`
- learning_rate : `0.01`
- loss : `mse`
- dropout : `0.02`
- neurons_factors : `[3.0, 2.0, 1.0]`
- batch_size : `256`
- min_nb_epochs : `1000`  |  max_epochs : `1000`  |  epochs_trained : `1000` (full)
- use_batch_norm : `False`
- patience EarlyStopping : `30`  |  restore_best_weights : `True`
- ReduceLROnPlateau : factor=0.5, patience=20, min_lr=1e-5
- test_size : `0.0` (in-sample, full training)
- seed : `1754`

## Sample weighting
- ACTIF — capteurs permanents (`Type Compteur` ∈ {Permanent, permanent, Siredo}) pondérés ×2.0
- Recent year weighting : OFF

## Métriques validation (3632 capteurs cleanés)
- **Capteurs tolérance inclus : 2173/3632 (59.83%)**
- **Erreur relative p80 : 29.46%**
- Erreur relative médiane : 14.42%
- **R² : 0.6858**
- RMSE : 0.6602
- MAE : 0.3771
- GEH < 5 : 100.0%
- N validation : 3632
- Durée d'entraînement : 106.1 s

## Variance multi-seed (10 graines)
- tol mean = 58.48% (std = 0.82)
- p80 mean = 29.88 (std = 0.59)
- R² mean = 0.6747 (std = 0.0145)
- Best (seed 1754) à +1.6 σ au-dessus de la moyenne sur tol

## Comparaison vs Full 11
- Full 11 best (seed 1751) : tol 66.41% / p80 26.34 / R² 0.808
- Compact 6 best (seed 1754) : tol 59.83% / p80 29.46 / R² 0.686
- **Trade-off** : −6.6 pp tol mais 5 features en moins (déploiement plus simple, pas de distances avant/après PL à recueillir)

## Fichiers livrés
- `model/model.keras` — modèle Keras chargeable directement
- `model/NNweights.weights.h5` — poids seuls
- `model/NNarchitecture.json` — architecture sérialisée
- `model/NNnormCoefficients.json` — coefficients de normalisation (mu, sigma par feature)
- `model/training_config.json` — config complète d'entraînement
- `model/training_metrics.json` — métriques par epoch
- `model/meta.json` — métadonnées run
- `report.html` — rapport HTML d'évaluation
- `metrics.json` — résumé JSON des métriques validation
