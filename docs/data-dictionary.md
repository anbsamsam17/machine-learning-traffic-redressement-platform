# Dictionnaire des donnees — schema cible (26 colonnes)

Source de verite : `apps/api/app/routers/mapping.py`
(`TARGET_COLUMNS`, `TARGET_GROUPS`, `SYNONYMS`, `CRITICAL_COLS`).

Le pipeline TV/PL standardise toute table source vers **26 colonnes cibles**.
L'auto-mapping (`POST /api/mapping/auto`) detecte la colonne source de chaque
cible par : (1) correspondance exacte insensible a la casse, (2) synonyme/alias,
(3) correspondance floue (`difflib`, cutoff 0.75). Des colonnes additionnelles
libres peuvent etre ajoutees telles quelles via `extra_cols`.

## Retrocompatibilite km / m (Bordeaux)

Les datasets historiques Bordeaux exposent les distances en **km**
(`car_average_distance_km`, `truck_min_average_distance_km`, etc.) et des noms
type `TMJATV` / `TMJAFCDTV` / `car_*`. Ces noms restent acceptes via `SYNONYMS`
pour le matching, mais les colonnes cibles sont suffixees `_m` (metres) :
l'unite doit etre verifiee, la conversion m<->km etant geree au niveau du
service ML pour les modeles entraines sur les anciens noms. Le script
`scripts/enrich_fcdrefglobal.py` applique la conversion km -> m a la source.

## Colonnes critiques

Les colonnes suivantes sont marquees critiques (`CRITICAL_COLS`) : si l'une est
absente apres mapping, un avertissement fort est emis et l'entrainement risque
d'echouer : `TMJOBCTV` (target principale TV), `TMJOFCDTV`, `TMJOFCDPL`,
`TxPen`, `avg_distance_m`, `avg_speed_kmh`, `truck_avg_min_distance_m`,
`truck_avg_speed_kmh`, `functional_class`.

---

## Tableau des colonnes cibles

Conventions de nommage : `TMJO` = TMJ Ouvre, `BC` = Boucle Comptage,
`FCD` = Floating Car Data (HERE), `HPM` = heure de pointe matin (8h-9h),
`HPS` = heure de pointe soir (17h-18h).

### Identification (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `Identifiant` | str | — | NO_DU_POSTE, no_du_poste, id_poste, ID, id, Poste |
| `Annee` | int | annee | annee, ANNEE, year, Year, an |
| `Adresse` | str | — | adresse compteur, Adresse compteur, ADRESSE, adresse, Route, route |
| `Type Compteur` | str | — | type compteur, TypeCompteur, type_compteur, Type |

> `Type Compteur` derive la colonne `flag_comptage` (Permanent -> 1, Temporaire
> -> 0 ; fallback historique Bordeaux "Per"/"Tou"). Non incluse dans les 26
> cibles, ajoutee automatiquement pour la ponderation des echantillons.

### Comptage capteur — BC = Boucle Comptage (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `TMJOBCTV` | float | veh/j | TMJABCTV, tmjabctv, TMJOBCTV, TMJABCTOTAL |
| `TMJOBCPL` | float | veh/j | TMJABCPL, tmjabcpl, TMJOBCPL |
| `TMJOBCTV_HPM` | float | veh/h | TMJABCTV_HPM, tmjabctv_hpm, tmjobctv_hpm, BCTV_HPM, BCTV_h08, BC_HPM_TV |
| `TMJOBCTV_HPS` | float | veh/h | TMJABCTV_HPS, tmjabctv_hps, tmjobctv_hps, BCTV_HPS, BCTV_h17, BC_HPS_TV |

### FCD HERE (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `TMJOFCDTV` | float | veh/j | TMJAFCDTV, TMJFCDTV, TMJATV, tmjafcdtv, tmjatv |
| `TMJOFCDPL` | float | veh/j | TMJAFCDPL, TMJFCDPL, TMJAPL, tmjafcdpl, tmjapl |
| `FCD_HPM_TV` | float | veh/h | FCDTV_h08, FCDTV_HPM, FCDTV_hpm, fcdtv_h08, fcd_hpm_tv, FCD_HPM, FCDHPMTV, TMJOFCDTV_HPM, tmjofcdtv_hpm |
| `FCD_HPS_TV` | float | veh/h | FCDTV_h17, FCDTV_HPS, FCDTV_hps, fcdtv_h17, fcd_hps_tv, FCD_HPS, FCDHPSTV, TMJOFCDTV_HPS, tmjofcdtv_hps |

### Taux de penetration (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `TxPen` | float | % | TxPen_brut, TxPenTVRef, TxPenRef, TXPENTV, TXPENTVREF, txpen |
| `TxPenPL` | float | % | TxPenPLRef, TXPENPL, TXPENPLREF, txpenpl |
| `TxPen_HPM` | float | % | txpen_hpm, TXPEN_HPM, TxPenHPM, TxPen_HPM_brut, TxPenHPMRef, TXPENHPM |
| `TxPen_HPS` | float | % | txpen_hps, TXPEN_HPS, TxPenHPS, TxPen_HPS_brut, TxPenHPSRef, TXPENHPS |

> Derivations automatiques si absents : `TxPen = TMJOFCDTV / TMJOBCTV * 100`,
> `TxPenPL = TMJOFCDPL / TMJOBCPL * 100`.

### Mapping & qualite (2)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `segment_id_match` | str/int | — | LINK_ID, link_id, segmentId, segmentid, ref_in_id, REF_IN_ID |
| `mapmatch_status` | str | — | match_status, mapmatch, mapmatch_state, status |

### Reseau HERE (1)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `functional_class` | int | classe (1-5) | linkFC, FC, fc, FUNCTIONAL_CLASS |

### Vitesses FCD lissees (2)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `avg_speed_kmh` | float | km/h | car_average_speed_kmh, avg_speed, car_speed, vitesse_voitures_kmh |
| `truck_avg_speed_kmh` | float | km/h | truck_average_speed_kmh, truck_speed, vitesse_camions_kmh |

### Distances VL (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `avg_distance_m` | float | m | car_average_distance_km (km, retrocompat), car_avg_distance, avg_distance |
| `avg_distance_before_m` | float | m | car_distance_before, avg_dist_before |
| `avg_distance_after_m` | float | m | car_distance_after, avg_dist_after |
| `avg_min_distance_m` | float | m | car_min_average_distance_km (km, retrocompat), avg_min_dist, car_min_distance |

> Note retrocompat : les anciens datasets Bordeaux fournissent ces distances en
> **km**. Le synonyme est conserve pour le matching, mais la cible est en
> **metres** — verifier / convertir l'unite avant entrainement.

### Distances PL (4)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `truck_avg_distance_m` | float | m | truck_average_distance_km (km, retrocompat), truck_avg_distance |
| `truck_avg_distance_before_m` | float | m | truck_distance_before |
| `truck_avg_distance_after_m` | float | m | truck_distance_after |
| `truck_avg_min_distance_m` | float | m | truck_min_average_distance_km (km, retrocompat), truck_min_avg_distance |

### Geometrie (3)

| Cible | Type | Unite | Synonymes / alias acceptes |
|---|---|---|---|
| `geometry` | LineString / JSON | EPSG:4326 | __geometry_json, geom, the_geom, shape, SHAPE |
| `HD` | int | degres (0-359) | HD, heading, Heading, Hd, hd |
| `DIR_TRAVEL` | str | — ("B" = bidirectionnel) | DIR_TRAVEL, dir_travel, direction, Direction |

> `geometry` est serialisee en chaine JSON a la validation (compatibilite
> pyarrow). `HD` (heading FCDREFGLOBAL) sert de fallback geometrique cote carte
> si absent ; `DIR_TRAVEL` ("B" = bidirectionnel) est mappe sur `DD` (bool).
