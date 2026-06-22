# Analyse D — Qualité des données des 226 discontinuités TVr

Investigation : les 226 cas top de discontinuité TVr sont-ils causés par des **problèmes de qualité de données FCD** plutôt que par le modèle TV lui-même ?

- CSV cases : `top250_discontinuities_with_inputs.csv` (226 cas)
- FCD source : `FCDREFGLOBAL_2025.parquet` (241,857 segments)
- Lookup miss E=0, N=0 (devrait être 0)

## 1. Bimodalité des inputs (E vs N)

Pour chaque input, ratio `min(|E|,|N|) / max(|E|,|N|)` par cas : valeur proche de 0 = un côté quasi nul vs un côté élevé (signature d'une coupure FCD).

| Input | médiane ratio | %cas <10% | %cas <25% | |Δ| p95 |
|---|---:|---:|---:|---:|
| TMJOFCDTV | 0.13 | 42% | 65% | 2299 |
| TMJOFCDPL | 0.10 | 49% | 72% | 919 |
| avg_distance_before_m | 0.78 | 1% | 15% | 55946 |

**Lecture** : un fort pourcentage de cas avec ratio < 10 % indique une bimodalité franche (un côté présent, l'autre quasi absent), typique d'un **gap de couverture FCD** ou d'une troncature.

## 2. Flags d'imputation FCD

Baseline FCDREFGLOBAL : **23.6%** des segments ont au moins une variable imputée.

- Au moins 1 imputation côté E : **3** / 226 (1.3%)
- Au moins 1 imputation côté N : **1** / 226 (0.4%)
- **Les deux** côtés imputés : **0** (0.0%)
- Asymétrique (un seul côté imputé) : **4** (1.8%)
- Aucun côté imputé : **222** (98.2%)

**Détail par flag :**

| Flag | E imputé | E % | N imputé | N % |
|---|---:|---:|---:|---:|
| car_average_speed_kmh | 0 | 0.0% | 0 | 0.0% |
| car_average_distance_km | 0 | 0.0% | 0 | 0.0% |
| car_average_distance_before_km | 0 | 0.0% | 0 | 0.0% |
| car_average_distance_after_km | 0 | 0.0% | 0 | 0.0% |
| car_min_average_distance_km | 0 | 0.0% | 0 | 0.0% |
| truck_average_speed_kmh | 3 | 1.3% | 1 | 0.4% |
| truck_average_distance_km | 3 | 1.3% | 1 | 0.4% |
| truck_average_distance_before_km | 3 | 1.3% | 1 | 0.4% |
| truck_average_distance_after_km | 3 | 1.3% | 1 | 0.4% |
| truck_min_average_distance_km | 3 | 1.3% | 1 | 0.4% |

**Lift** : la probabilité qu'au moins un côté soit imputé est **1.8%** vs **23.6%** en moyenne FCD → enrichissement ×**0.08**. Les 226 cas top sont donc peu sur-représentés en imputations.

## 3. Outliers mensuels (CV sur M01..M12)

- |ΔCV(TV)| > 0.30 entre E et N : **59** cas (26.1%)
- |ΔCV(PL)| > 0.30 entre E et N : **65** cas (28.8%)
- CV(TV) > 0.50 sur au moins un côté : **59** cas (26.1%)
- CV(TV) médian E=0.11 / N=0.11

**Lecture** : un CV mensuel très différent entre les deux côtés (ou très élevé d'un côté) suggère une **série temporelle FCD bruitée** ou un échantillonnage déséquilibré sur l'année.

## 4. Cohérence de l'année

- Valeurs uniques de `Annee` : ['2025']
- Cas avec Annee_E ≠ Annee_N : **0**

## 5. Matrice de transition functional_class (E × N)

- Même FC E et N : **79** (35.0%)
- |ΔFC| = 1 : **51** (22.6%)
- |ΔFC| ≥ 2 (transition franche, hiérarchie réseau) : **96** (42.5%)

Matrice FC_E (lignes) × FC_N (colonnes) :

```
functional_class   1   2   3  4  5
functional_class                  
1                 28   9  19  4  6
2                  8  30  15  8  7
3                 17  13  19  4  6
4                  2   3   2  2  0
5                  7  11   6  0  0
```

**RAMP / ROUNDABOUT :**

- RAMP asymétrique (un seul côté est une bretelle) : **125** ; au moins un côté RAMP = 137
- ROUNDABOUT asymétrique : **6** ; au moins un côté = 6

## 6. Anomalies géographiques

- Étendue lat/lon des 226 nœuds : ~60.7 km (zone Grand Lyon)
- lat ∈ [45.5419, 45.9789], lon ∈ [4.6511, 5.1212]
- Le CSV ne fournit qu'un lat/lon partagé (nœud commun) — les arêtes E et N partagent par construction l'extrémité, distance ≈ 0. Pas d'adjacence corrompue détectable depuis ce CSV.

## Verdict

- **DATA quality pur** (imputation ou ΔCV élevé sans transition réseau franche) : **40** cas (17.7%)
- **Transition légitime pure** (|ΔFC|≥2 ou RAMP/RB asymétrique, sans signe d'imputation/CV) : **135** cas (59.7%)
- **Les deux causes simultanées** : **32** cas (14.2%)
- **Inexpliqué** (ni signature data, ni transition réseau) : **19** cas (8.4%) → très probablement erreur de modèle TV

**Conclusion** : sur 226 cas, **72** (32%) présentent au moins une signature de problème de données FCD ; **135** (60%) sont des transitions réseau légitimes sans signe d'imputation. Le résiduel **19** cas est à investiguer côté modèle.

## Top 5 cas pour revue QA (data-quality pur, severity max)

| rank | agregId_E | agregId_N | severity | TVr_E | TVr_N | Δ% | imp_E | imp_N | fc_E | fc_N | cv_tv_E | cv_tv_N |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 62165604 | 724107724 | 58083 | 12100 | 57300 | 78.9% | 0 | 0 | 3 | 2 | 0.13 | 0.12 |
| 9 | 724107724 | 62165604 | 58083 | 57300 | 12100 | 78.9% | 0 | 0 | 2 | 3 | 0.12 | 0.13 |
| 58 | 1179281608 | 62165678 | 40970 | 56400 | 22200 | 60.6% | 0 | 0 | 2 | 2 | 0.12 | 0.59 |
| 59 | 62165678 | 1179281608 | 40970 | 22200 | 56400 | 60.6% | 0 | 0 | 2 | 2 | 0.59 | 0.12 |
| 70 | 1143846598 | 1143846599 | 37489 | 52600 | 21200 | 59.7% | 0 | 0 | 2 | 2 | 0.07 | 1.73 |

---
*Méthode : lookup `agregId_E/N` → `segment_id` dans `FCDREFGLOBAL_2025.parquet`. Flags d'imputation : 10 colonnes `*_was_imputed`. CV mensuel calculé sur M01..M12. Seuils : imputation = OR sur 10 flags ; CV élevé = écart > 0.30 entre E et N.*