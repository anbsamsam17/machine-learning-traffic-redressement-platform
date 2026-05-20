# Worker A4 — 14 weighting axis configs (port 7004)

Dataset: `lyon_allyears.geojson` (3671 capteurs, années 2019-2025)
Baseline: mse, drp=0.025, ep=1000, neurons=[3,2,1], lr=0.01, batch=256, elu, test_size=0.05

Quality gates: tol_total>0, barplot not broken, p80 finite, R²>0.

| Config | Pondération | R² | RMSE | MAE | MedRelErr% | p80% | Tol% | GEH<5 | N | TrainSec | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A4_Full_baseline | none (uniform weights) | 0.6650 | 0.7030 | 0.4031 | 15.0400 | 30.6900 | 58.5944 | 100.0000 | 3671 | 213 | OK |
| A4_Full_permX2 | flag_permanent x2.0 | 0.6650 | 0.7030 | 0.4031 | 15.0400 | 30.6900 | 58.5944 | 100.0000 | 3671 | 211 | OK |
| A4_Full_permX3 | flag_permanent x3.0 | 0.6650 | 0.7030 | 0.4031 | 15.0400 | 30.6900 | 58.5944 | 100.0000 | 3671 | 208 | OK |
| A4_Full_recentX2 | flag_recent_year x2.0 | 0.6614 | 0.7068 | 0.4166 | 15.7300 | 31.5100 | 56.5241 | 100.0000 | 3671 | 207 | OK |
| A4_Full_recentX3 | flag_recent_year x3.0 | 0.6628 | 0.7053 | 0.4201 | 15.9200 | 31.7900 | 55.8431 | 100.0000 | 3671 | 197 | OK |
| A4_Full_combX2 | perm x2.0 + recent x2.0 | 0.6614 | 0.7068 | 0.4166 | 15.7300 | 31.5100 | 56.5241 | 100.0000 | 3671 | 212 | OK |
| A4_Full_combX3 | perm x3.0 + recent x3.0 | 0.6628 | 0.7053 | 0.4201 | 15.9200 | 31.7900 | 55.8431 | 100.0000 | 3671 | 195 | OK |
| A4_Full_combPx2Rx3 | perm x2.0 + recent x3.0 | 0.6628 | 0.7053 | 0.4201 | 15.9200 | 31.7900 | 55.8431 | 100.0000 | 3671 | 190 | OK |
| A4_Full_logFlow | log_flow (continuous on TMJOBCTV) | 0.6650 | 0.7030 | 0.4031 | 15.0400 | 30.6900 | 58.5944 | 100.0000 | 3671 | 234 | OK |
| A4_Compact6_baseline | none (uniform) | 0.6471 | 0.7215 | 0.4253 | 16.3000 | 31.8100 | 54.8624 | 100.0000 | 3671 | 186 | OK |
| A4_Compact6_permX2 | flag_permanent x2.0 | 0.6471 | 0.7215 | 0.4253 | 16.3000 | 31.8100 | 54.8624 | 100.0000 | 3671 | 120 | OK |
| A4_Compact6_permX3 | flag_permanent x3.0 | 0.6471 | 0.7215 | 0.4253 | 16.3000 | 31.8100 | 54.8624 | 100.0000 | 3671 | 110 | OK |
| A4_Compact6_recentX2 | flag_recent_year x2.0 | 0.6475 | 0.7211 | 0.4356 | 16.7600 | 32.5300 | 54.3449 | 100.0000 | 3671 | 104 | OK |
| A4_Compact6_combX2 | perm x2.0 + recent x2.0 | 0.6475 | 0.7211 | 0.4356 | 16.7600 | 32.5300 | 54.3449 | 100.0000 | 3671 | 104 | OK |

## Notes importantes

1. **`flag_permanent` is all-zero on this dataset** : le geojson Grand Lyon `lyon_allyears.geojson` n'a pas de colonne "Permanent" ou "is_permanent" exploitable, et le préprocesseur (A4_orchestrator._preprocess_geojson) n'a trouvé aucun capteur Permanent via "Type Compteur". Tous les `flag_permanent=0`. **Conséquence** : les configs `permX2` / `permX3` produisent des métriques **strictement identiques** au baseline correspondant (Full ou Compact6) — le poids `4×0+1 = 1` pour toutes les lignes.

2. **`use_log_flow_weighting` non propagé** : le flag `use_log_flow_weighting` est défini dans `split_train_valid` (apps/api/app/services/ml/data_prep.py) mais `training_pipeline.run_training` ne le passe pas. Config 9 (`A4_Full_logFlow`) se comporte donc comme le baseline. Métriques identiques à `A4_Full_baseline` confirment ce silent-skip.

3. **`flag_recent_year=1` pour 1548/3671 (42%)** : seul ce flag varie. Les configs `recentX2`, `recentX3`, `combX2/X3/Px2Rx3` montrent un effet réel mais légèrement **dégradant** sur le validation set complet (R² 0.665 → 0.661–0.663, p80 30.69 → 31.5–31.8 %, tol 58.6 % → 55.8–56.5 %). Logique : on sur-pondère les capteurs 2025 au détriment des autres années, ce qui pénalise les métriques globales mais devrait améliorer la performance spécifique sur l'année cible.

4. **Compact6 vs Full** : la perte de 5 features (vitesses VL/PL, distances before/after, flag_permanent) coûte ~1.8 pt de R² (0.665 → 0.647) et ~3.7 pt de Tol% (58.6 → 54.9). Les distances `before/after` et `truck_avg_distance_m` apportent donc de l'information utile.

## Quality gates

Toutes les configs passent : `tol_total>0`, barplot non broken, p80 fini, R²>0. Aucun crash, aucune métrique manquante. Le bootstrap CI95 est dans chaque `metrics.json` (clé `metrics_ci95`).

## Fichiers livrés par run

Chaque sous-dossier `A4_<name>/` contient :
- `metrics.json` (configs + metrics + CI95 + tol/p80 parsés du rapport)
- `README.md` (récap markdown lisible)
- `report.html` (rapport HTML complet)
- `model/` (NNarchitecture.json, NNweights.weights.h5, NNnormCoefficients.json, model.keras, training_config.json, training_metrics.json, meta.json)
