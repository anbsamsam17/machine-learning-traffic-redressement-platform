/**
 * Sam coaching content — single source of truth for the `/config` page
 * recommendations panel + every per-field tooltip.
 *
 * All copy is in French to match the rest of the redressement pipeline UI.
 * Recommendations are derived from the D4_8643_bs128_ep1500 production baseline
 * — 71.23% tol / p80 23.52 / R²=0.8346 on 3671 GrandLyon sensors
 * (BCFCDREF_AllYears_TV, Batch Compact9) — and from the 60+ models benchmarked
 * during the bs=128/architecture sweep.
 *
 * Edit copy here once → it propagates to the panel AND every tooltip.
 */

export interface CoachingBullet {
  /** Short label that opens the bullet (e.g. "Loss"). */
  label: string;
  /** The concrete recommendation rendered as the bullet body. */
  body: string;
}

export interface CoachingStrategy {
  models: string;
  epochs: string;
  batch: string;
  /** One-line rationale shown below the strategy chips. */
  rationale: string;
}

export interface SamConfigRecommendations {
  /** 4-5 headline recommendations — rendered as a bullet list. */
  mainRecommendations: CoachingBullet[];
  /** 3-4 pitfalls — rendered with an alert-triangle icon. */
  pitfalls: CoachingBullet[];
  /** Recommended batch strategy summary. */
  strategy: CoachingStrategy;
  /** 3-5 advanced bullets revealed by the toggle. */
  advancedRecommendations: CoachingBullet[];
}

// ---------------------------------------------------------------------------
// TV model (Tous Véhicules) — defaults from D4_8643_bs128_ep1500 winner
// (Batch Compact9, BCFCDREF_AllYears_TV, 71.23% tol).
// ---------------------------------------------------------------------------
export const samConfigRecommendations: SamConfigRecommendations = {
  mainRecommendations: [
    {
      label: "batch_size = 128 — LE levier-clé",
      body:
        "Passer de `bs=256` à `bs=128` apporte **+4-5 pp tol** sur ce dataset (testé sur 60 modèles). C'est l'unique levier qui débloque le palier des 70 % — à ne jamais relever.",
    },
    {
      label: "Architecture 4 layers `[8, 6, 4, 3]`",
      body:
        "Wider + deeper que `[3, 2, 1]` → **+13 pp tol**. Plafond observé : au-delà de 12 neurones d'entrée ou de 6 couches, aucun gain supplémentaire.",
    },
    {
      label: "min_nb_epochs = max_epochs = 1500",
      body:
        "Force le training complet : le modèle continue à descendre jusqu'à 1500 epochs sur cette architecture. EarlyStopping désactivé en pratique.",
    },
    {
      label: "Dropout 0.015 + lr 0.01 + loss mse",
      body:
        "Combo stable et reproductible — testé contre 0.02 / 0.025 / 0.03 (tous dégradent). `lr=0.02` aussi efficace mais avec bs=128 uniquement.",
    },
    {
      label: "7 features (year + 6 raw)",
      body:
        "`year_mapped` + `TMJOFCDTV` + `TMJOFCDPL` + `functional_class` + `avg_distance_before_m` + `avg_min_distance_m` + `truck_avg_distance_before_m`. Ajouter une 3e distance VL = gain marginal.",
    },
  ],
  pitfalls: [
    {
      label: "batch_size = 256 (défaut historique)",
      body:
        "Sur ce dataset, bs=256 coûte **−4-5 pp tol** vs bs=128. Toujours préférer bs=128 — c'est le seul changement qui débloque le palier.",
    },
    {
      label: "Pondération `flag_permanent` / `recent_year`",
      body:
        "INEFFICACE sur ce dataset (testé exhaustivement, plusieurs poids et combinaisons). On désactive les deux toggles — gain nul ou négatif.",
    },
    {
      label: "Dropout > 0.02 ou < 0.015",
      body:
        "Sweet spot très étroit autour de **0.015** : toutes les valeurs au-dessus (0.02, 0.025, 0.03) ou en-dessous dégradent la tol.",
    },
    {
      label: "Options Phase 2A / 3 (AdamW, Skip, BN, SELU, log, quantile, curriculum, hard-mining)",
      body:
        "Toutes testées exhaustivement sur cette configuration : **toutes régressent**. Garder Adam + ELU + tête de régression standard.",
    },
  ],
  strategy: {
    models: "Validation prod : défauts",
    epochs: "Explorer : varier l'archi",
    batch: "Production : multi-seed n=3",
    rationale:
      "Laisser les défauts reproduit ~71 % tol en ~2 min. Pour explorer, tester `[12, 8, 6, 4, 3]` (6L) ou `[10, 6, 5, 4]`. Forte variance observée multi-seed (58-67 % sur même config) → `n_seeds=3` recommandé en production.",
  },
  advancedRecommendations: [
    {
      label: "lr = 0.02 + bs = 128",
      body:
        "Atteint un R² record **0.8462** mais tol légèrement inférieur à 71.23 %. À tester en mode exploration uniquement.",
    },
    {
      label: "9 features (3 distances VL + 2 distances PL)",
      body:
        "Atteint 70.01 % tol. Moins compact que la config gagnante 7 features sans gain de performance — gain marginal du 9e feature.",
    },
    {
      label: "Architecture 6 layers `[12, 8, 6, 4, 3]`",
      body:
        "Alternative robuste (69.08 % tol) — utile si vous avez besoin d'un modèle plus expressif. Plafond architectural observé.",
    },
    {
      label: "`truck_avg_distance_before_m` > variantes",
      body:
        "Sur cette tâche, `before_m` surpasse `min/avg/after_m` côté PL. Garder `truck_avg_distance_before_m` comme distance PL principale.",
    },
    {
      label: "Architecture 3 layers `[8, 6, 4]` + bs=128",
      body:
        "Atteint 69.79 % tol — option plus compacte si vous voulez un modèle plus léger en inférence.",
    },
  ],
};

// ---------------------------------------------------------------------------
// PL model (Poids Lourds) — defaults from E3_09_all3_plus_after winner
// (Batch_MDL_PL_Compact4, BCFCDREF_AllYears_PL_enriched, 94,00 % tol /
// 658/700 capteurs, R² 0,9722, MAE 0,1657, medE 7,99 %, GEH<5 99,86 %).
// 8 seeds × 10 subsets soit 80 modèles entraînés sur Grand Lyon ; effets
// marginaux mesurés vs subsets sans la feature (cf. memory/02_calibration_modele_PL.md).
// ---------------------------------------------------------------------------
export const samConfigRecommendationsPL: SamConfigRecommendations = {
  mainRecommendations: [
    {
      label: "9 features Compact4 — subset `09_all3_plus_after`",
      body:
        "`TMJOFCDPL`, `functional_class`, 4 distances PL (`truck_avg_distance_m`, `truck_avg_min_distance_m`, `truck_avg_distance_before_m`, `truck_avg_distance_after_m`) + **3 features dérivées** (`fcd_log`, `tv_pl_ratio`, `dist_to_lyon_center`). +10,82 pp tol vs Compact3 base.",
    },
    {
      label: "`dist_to_lyon_center` — meilleur gain marginal",
      body:
        "Distance Haversine au centre (Place Bellecour, km). Capte la décroissance radiale du trafic PL Grand Lyon. **+6,41 pp tol marginal** (mesure 6 subsets avec / 4 sans, 8 seeds). À recalculer si territoire différent.",
    },
    {
      label: "`tv_pl_ratio` — composition de l'axe",
      body:
        "`TMJOFCDTV / (TMJOFCDPL + 0,1)`. Ratio faible (5-15) = axe lourd (autoroute), ratio élevé (>50) = voie urbaine résiduelle. **+6,07 pp tol marginal**.",
    },
    {
      label: "Architecture 5 layers `[8, 6, 4, 3, 2]` + bs=64 + 1500 epochs",
      body:
        "Recipe figée Compact4 : `bs=64`, `lr=0,01`, `dropout=0,015`, `activation=elu`, `loss=mse`, `min_nb_epochs=max_epochs=1500`. EarlyStopping désactivé en pratique. Temps : ~213 s/modèle CPU.",
    },
    {
      label: "Cible `TxPenPL` (sortie scalaire)",
      body:
        "Le réseau prédit `TxPenPL` ; le redressement métier est `DPL = TMJOFCDPL / TxPenPL × 100`. Validation contre `TMJOBCPL` (boucle de comptage PL).",
    },
  ],
  pitfalls: [
    {
      label: "`fcd_log` seul (sans les 2 autres features)",
      body:
        "Subset `01_plus_log` → tol 79,77 % ± 5,11 (très instable, **inférieur** à la baseline 80,16 %). `fcd_log` n'a de valeur qu'en synergie avec `tv_pl_ratio` et `dist_to_lyon_center`.",
    },
    {
      label: "Pondération `flag_permanent` / `recent_year` (toujours OFF en PL)",
      body:
        "Les 80 runs Compact4 ont `use_flag_permanent_weighting=false` et `use_flag_recent_year_weighting=false`. Aucun gain mesuré sur PL ; activer ces toggles écarte de la config validée.",
    },
    {
      label: "Hold-out `test_size > 0`",
      body:
        "Défaut **0.0** comme tous les runs Compact4 (les 700 lignes servent à l'entraînement). Activer un split test_size > 0 réduit la taille d'apprentissage (déjà faible) et bruite l'EarlyStopping.",
    },
    {
      label: "Feature `year_mapped` ou Embedding année",
      body:
        "Non utilisée dans le subset gagnant PL (vs config TV où elle figure dans les 7 inputs). À laisser OFF pour reproduire le Compact4.",
    },
    {
      label: "Limite territoriale : `dist_to_lyon_center` non transposable",
      body:
        "Le centroïde (Place Bellecour, 45,7578° N / 4,8320° E) est hardcodé. Pour un autre territoire (Bordeaux, Île-de-France), recalculer la feature avec le centre local — sinon désactiver ce feature.",
    },
  ],
  strategy: {
    models: "Production : 9 features",
    epochs: "1500 epochs forcés",
    batch: "Multi-seed n=8 (1750..1757)",
    rationale:
      "Le winner individuel `E3_09_all3_plus_after` (seed 1752) atteint 94,00 % tol / R²=0,9722. Moyenne 8 seeds = 91,55 % ± 1,52 (très stable). En production, multi-seed `n_seeds=3..8` recommandé pour absorber la variance.",
  },
  advancedRecommendations: [
    {
      label: "Subset `07_all3` (8 features sans `truck_avg_distance_after_m`)",
      body:
        "Alternative à -0,55 pp tol_mean (91,00 % vs 91,55 %) mais à -0,01 pp std. Préférer si `truck_avg_distance_after_m` est manquant dans le territoire cible.",
    },
    {
      label: "Subset `08_swap_log` (substitution `TMJOFCDPL` → `fcd_log`)",
      body:
        "Métriques identiques au subset `07` → le réseau apprend à représenter `log` depuis la feature brute. Conclusion : garder `TMJOFCDPL` en clair, ne pas remplacer.",
    },
    {
      label: "`learning_rate = 0,01` — pas tester à 0,001",
      body:
        "Tous les 80 runs Compact4 utilisent `lr=0,01` (recipe figée). À 1500 epochs c'est calibré ; baisser à 1e-3 nécessiterait d'augmenter `max_epochs` à 3000+.",
    },
    {
      label: "Normalisation : `functional_class` **non normalisé** (catégoriel 1-5)",
      body:
        "Les 8 autres features sont z-scorées (mask `[true, false, true, true, true, true, true, true, true]`). Si vous ajoutez une feature catégorielle, l'OFFer explicitement.",
    },
    {
      label: "Toutes options Phase 2A / 3 testées — laisser OFF",
      body:
        "AdamW, Skip, BatchNorm, LayerNorm, target_log_transform, curriculum, hard-mining, quantile-head : aucune n'a été activée dans le winner Compact4. `optimizer=adam`, `dropout_schedule=uniform`, `clipnorm=null`.",
    },
  ],
};

// ---------------------------------------------------------------------------
// HPM model (Heure de Pointe Matin, 8h-9h) — pipeline horaire derive de TV
// (architecture identique). Sortie HPM_FCDr (v/h). Cible TxPen_HPM, source
// FCD horaire FCD_HPM_TV, compteur TMJOBCTV_HPM.
// ---------------------------------------------------------------------------
export const samConfigRecommendationsHPM: SamConfigRecommendations = {
  mainRecommendations: [
    {
      label: "Tu modelises le debit en heure de pointe matin (8h-9h)",
      body:
        "Cible : `TxPen_HPM` (taux de penetration FCD HERE sur 8h-9h). Source FCD : `FCD_HPM_TV`. Compteur de reference : `TMJOBCTV_HPM`. **Unite partout : v/h** (vehicules par heure) — jamais v/j.",
    },
    {
      label: "Sortie HPM_FCDr (debit redresse heure de pointe matin)",
      body:
        "Le modele predit `TxPen_HPM`, et la sortie metier est `HPM_FCDr = FCD_HPM_TV / TxPen_HPM × 100`. C'est ce que ton fichier de sortie contiendra (v/h).",
    },
    {
      label: "Architecture identique a la chaine TV — defauts deja valides",
      body:
        "Le modele HPM partage la meme architecture neuronale que TV : 4 couches `[8, 6, 4, 3]`, batch_size 128, dropout 0.015, lr 0.01, loss mse, 1500 epochs. Les defauts du formulaire reprennent cette recette.",
    },
    {
      label: "Charge un fichier qui contient TMJOBCTV_HPM et FCD_HPM_TV",
      body:
        "Ces deux colonnes sont indispensables. Si ton fichier source contient des colonnes horaires `FCDTV_h08` (8h-9h), tu peux les renommer en `FCD_HPM_TV` avant l'upload ou laisser l'auto-mapping faire la suggestion.",
    },
    {
      label: "Features distance / vitesse / functional_class — meme schema TV",
      body:
        "Les proprietes du segment (`avg_distance_m`, `avg_speed_kmh`, `functional_class`) sont valables sur n'importe quelle fenetre horaire. Aucun changement vs TV — l'unique difference est la cible et la source FCD.",
    },
  ],
  pitfalls: [
    {
      label: "Mention TVr / v/j dans tes sorties",
      body:
        "Le pipeline HPM produit `HPM_FCDr` en `v/h`. Ne confonds pas avec la sortie TV (`TVr` en `v/j`). Les deux modeles sont distincts et leurs sorties ne sont pas interchangeables.",
    },
    {
      label: "Fenetre horaire alternative (7h-8h, 9h-10h)",
      body:
        "Le modele HPM est calibre sur 8h-9h. Si tu veux modeliser une autre fenetre (par ex. 7h-8h), il faut soit recalculer `TxPen_HPM` avec les nouvelles colonnes horaires, soit creer un modele dedie — ne pas remapper a la volee.",
    },
    {
      label: "Ponderation capteurs permanents",
      body:
        "Inutilise dans le pipeline horaire (memes conclusions que TV : aucun gain mesurable). Garder OFF par defaut.",
    },
  ],
  strategy: {
    models: "Production : defauts HPM",
    epochs: "1500 epochs forces",
    batch: "bs=128 + multi-seed n=3",
    rationale:
      "Architecture TV portee a la cible 8h-9h. Reproduit la recette D4_8643 — varier batch_size ou architecture seulement en exploration.",
  },
  advancedRecommendations: [
    {
      label: "Si TxPen_HPM est manquant dans ton fichier",
      body:
        "Le backend peut le recalculer a partir de `TMJOBCTV_HPM` et `FCD_HPM_TV` (formule `TxPen_HPM = FCD_HPM_TV / TMJOBCTV_HPM × 100`). Verifie que ces deux colonnes sont mappees.",
    },
    {
      label: "Source FCD horaire alternative (FCDTV_h08)",
      body:
        "Si ton fichier expose `FCDTV_h08` au lieu de `FCD_HPM_TV`, l'auto-mapping doit suggerer le bon alias. Verifie la suggestion avant de valider.",
    },
    {
      label: "Toutes les options Phase 2A / 3 / 4 — laisser OFF",
      body:
        "Les conclusions TV portent : AdamW, Skip, BatchNorm, target_log_transform regressent. Garder Adam + ELU + tete de regression standard.",
    },
  ],
};

// ---------------------------------------------------------------------------
// HPS model (Heure de Pointe Soir, 17h-18h) — pipeline horaire derive de TV.
// Sortie HPS_FCDr (v/h). Cible TxPen_HPS, source FCD horaire FCD_HPS_TV,
// compteur TMJOBCTV_HPS.
// ---------------------------------------------------------------------------
export const samConfigRecommendationsHPS: SamConfigRecommendations = {
  mainRecommendations: [
    {
      label: "Tu modelises le debit en heure de pointe soir (17h-18h)",
      body:
        "Cible : `TxPen_HPS` (taux de penetration FCD HERE sur 17h-18h). Source FCD : `FCD_HPS_TV`. Compteur de reference : `TMJOBCTV_HPS`. **Unite partout : v/h** (vehicules par heure) — jamais v/j.",
    },
    {
      label: "Sortie HPS_FCDr (debit redresse heure de pointe soir)",
      body:
        "Le modele predit `TxPen_HPS`, et la sortie metier est `HPS_FCDr = FCD_HPS_TV / TxPen_HPS × 100`. C'est ce que ton fichier de sortie contiendra (v/h).",
    },
    {
      label: "Architecture identique a la chaine TV — defauts deja valides",
      body:
        "Le modele HPS partage la meme architecture neuronale que TV : 4 couches `[8, 6, 4, 3]`, batch_size 128, dropout 0.015, lr 0.01, loss mse, 1500 epochs. Les defauts du formulaire reprennent cette recette.",
    },
    {
      label: "Charge un fichier qui contient TMJOBCTV_HPS et FCD_HPS_TV",
      body:
        "Ces deux colonnes sont indispensables. Si ton fichier source contient des colonnes horaires `FCDTV_h17` (17h-18h), tu peux les renommer en `FCD_HPS_TV` avant l'upload ou laisser l'auto-mapping faire la suggestion.",
    },
    {
      label: "Features distance / vitesse / functional_class — meme schema TV",
      body:
        "Les proprietes du segment (`avg_distance_m`, `avg_speed_kmh`, `functional_class`) sont valables sur n'importe quelle fenetre horaire. Aucun changement vs TV — l'unique difference est la cible et la source FCD.",
    },
  ],
  pitfalls: [
    {
      label: "Mention TVr / v/j dans tes sorties",
      body:
        "Le pipeline HPS produit `HPS_FCDr` en `v/h`. Ne confonds pas avec la sortie TV (`TVr` en `v/j`). Les deux modeles sont distincts et leurs sorties ne sont pas interchangeables.",
    },
    {
      label: "Fenetre horaire alternative (16h-17h, 18h-19h)",
      body:
        "Le modele HPS est calibre sur 17h-18h. Si tu veux modeliser une autre fenetre, il faut recalculer `TxPen_HPS` avec les nouvelles colonnes horaires, ou creer un modele dedie — ne pas remapper a la volee.",
    },
    {
      label: "Ponderation capteurs permanents",
      body:
        "Inutilise dans le pipeline horaire (memes conclusions que TV : aucun gain mesurable). Garder OFF par defaut.",
    },
  ],
  strategy: {
    models: "Production : defauts HPS",
    epochs: "1500 epochs forces",
    batch: "bs=128 + multi-seed n=3",
    rationale:
      "Architecture TV portee a la cible 17h-18h. Reproduit la recette D4_8643 — varier batch_size ou architecture seulement en exploration.",
  },
  advancedRecommendations: [
    {
      label: "Si TxPen_HPS est manquant dans ton fichier",
      body:
        "Le backend peut le recalculer a partir de `TMJOBCTV_HPS` et `FCD_HPS_TV` (formule `TxPen_HPS = FCD_HPS_TV / TMJOBCTV_HPS × 100`). Verifie que ces deux colonnes sont mappees.",
    },
    {
      label: "Source FCD horaire alternative (FCDTV_h17)",
      body:
        "Si ton fichier expose `FCDTV_h17` au lieu de `FCD_HPS_TV`, l'auto-mapping doit suggerer le bon alias. Verifie la suggestion avant de valider.",
    },
    {
      label: "Toutes les options Phase 2A / 3 / 4 — laisser OFF",
      body:
        "Les conclusions TV portent : AdamW, Skip, BatchNorm, target_log_transform regressent. Garder Adam + ELU + tete de regression standard.",
    },
  ],
};

// ---------------------------------------------------------------------------
// Per-field tooltips — keys correspond to logical field names exposed by the
// ConfigForm. Each entry combines a 1-sentence purpose with the rationale of
// the chosen D4_8643_bs128_ep1500 default. Editing one entry updates every
// tooltip on the form.
// ---------------------------------------------------------------------------

export interface FieldTooltip {
  /** One-sentence description of what the field controls. */
  purpose: string;
  /** Concrete value / range recommendation drawn from the production baseline. */
  recommendation: string;
}

export const fieldTooltips: Record<string, FieldTooltip> = {
  // ── Architecture ────────────────────────────────────────────────────────
  neurons_factors: {
    purpose:
      "Facteurs multiplicateurs de N (nombre de features) qui définissent le nombre de neurones par couche cachée.",
    recommendation:
      "TV — défaut **[8, 6, 4, 3]** (4 couches, Batch Compact9, 71.23 % tol). PL — défaut **[8, 6, 4, 3, 2]** (5 couches deep, Batch Compact4, 94,00 % tol). Plafond observé : au-delà de 6 couches ou 12 neurones d'entrée, plus aucun gain.",
  },
  activations: {
    purpose:
      "Fonction(s) d'activation des couches cachées — testées en grid search si plusieurs sélectionnées.",
    recommendation:
      "Défaut **elu** — `SELU` testé, dégrade tol et R² sur ce dataset.",
  },
  use_batch_norm: {
    purpose:
      "Ajoute une couche `BatchNormalization` après chaque couche cachée.",
    recommendation:
      "Défaut **OFF** — BatchNorm testé sur cette config, n'apporte aucun gain et dégrade légèrement la tol.",
  },
  dropouts: {
    purpose:
      "Taux de dropout appliqué à chaque couche cachée — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Défaut **0.015** — sweet spot validé sur 200+ modèles (vs 0.02 / 0.025 / 0.03 qui dégradent tous).",
  },
  dropout: {
    purpose:
      "Taux de dropout appliqué à chaque couche cachée.",
    recommendation:
      "Défaut **0.015** — sweet spot validé sur 200+ modèles (vs 0.02 / 0.025 / 0.03 qui dégradent tous).",
  },

  // ── Training ────────────────────────────────────────────────────────────
  losses: {
    purpose:
      "Fonction(s) de perte minimisée(s) pendant l'entraînement.",
    recommendation:
      "Défaut **mse** — `huber` / `tolerance_aware` testés, variance forte et gain instable sur ce dataset.",
  },
  loss: {
    purpose:
      "Fonction de perte minimisée pendant l'entraînement.",
    recommendation:
      "Défaut **mse** — `huber` / `tolerance_aware` testés, variance forte et gain instable sur ce dataset.",
  },
  learning_rates: {
    purpose:
      "Pas d'apprentissage Adam — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Défaut **0.01** — `0.02` également efficace combiné avec `bs=128` (R² record 0.8462).",
  },
  batch_sizes: {
    purpose:
      "Nombre d'échantillons traités par étape de gradient.",
    recommendation:
      "TV — défaut **128** : LE levier-clé Compact9, +4-5 pp tol vs bs=256. PL — défaut **64** (Batch Compact4, dataset Grand Lyon 700 lignes). Ne pas relever sans tester.",
  },
  min_nb_epochs_list: {
    purpose:
      "Nombre d'epochs minimum avant que l'EarlyStopping puisse arrêter l'entraînement.",
    recommendation:
      "Défaut **1500** — force le training complet, le modèle continue à descendre jusqu'à 1500 sur cette architecture.",
  },
  max_epochs: {
    purpose:
      "Plafond d'epochs — l'entraînement s'arrête au plus tard à cette valeur.",
    recommendation:
      "Défaut **1500** = min_nb_epochs → désactive EarlyStopping en pratique (training complet forcé).",
  },
  test_size: {
    purpose:
      "Fraction du dataset réservée au test final (hold-out).",
    recommendation:
      "Défaut **0.0** — in-sample full training. Un hold-out bruite l'EarlyStopping sur ce dataset.",
  },

  // ── Feature subsets ─────────────────────────────────────────────────────
  input_cols: {
    purpose:
      "Liste des colonnes d'entrée utilisées comme features par le modèle.",
    recommendation:
      "TV — 7 features (D4_8643 Compact9) : `year_mapped`, `TMJOFCDTV`, `TMJOFCDPL`, `functional_class`, `avg_distance_before_m`, `avg_min_distance_m`, `truck_avg_distance_before_m`. PL — 9 features (E3_09_all3_plus_after Compact4) : `TMJOFCDPL`, `functional_class`, 4 distances trucks + 3 features dérivées (`fcd_log`, `tv_pl_ratio`, `dist_to_lyon_center`).",
  },
  output_cols: {
    purpose:
      "Colonne(s) cible(s) à prédire.",
    recommendation:
      "Sélectionnez UNE cible primaire (`TxPen` en TV, `TxPenPL` en PL). Multi-cibles = configuration expérimentale.",
  },
  on_off_norm: {
    purpose:
      "Active/désactive la normalisation z-score par feature.",
    recommendation:
      "Toutes les features numériques continues z-scorées (ON). Désactivez sur `functional_class` (entier 1-5 catégoriel) et `year_mapped` (entier ordinal 1-7).",
  },
  mandatory_input_cols: {
    purpose:
      "Colonnes toujours présentes dans chaque sous-ensemble de features généré par le grid.",
    recommendation:
      "Toujours marquer `TMJOFCDTV` (TV) ou `TMJOFCDPL` (PL) — colonne source de référence.",
  },
  min_input_count: {
    purpose:
      "Nombre minimum de features dans chaque combinaison du grid de feature subsets.",
    recommendation:
      "Défaut **0** — pas de grille de sous-ensembles (entraînement sur l'ensemble des features sélectionnées en une seule combinaison).",
  },
  feature_subset_grid: {
    purpose:
      "Génère automatiquement toutes les combinaisons valides de features comme sous-ensembles.",
    recommendation:
      "Désactivé par défaut — l'entraînement utilise exactement les 7 features sélectionnées en une seule combinaison.",
  },

  // ── Année ───────────────────────────────────────────────────────────────
  use_year_feature: {
    purpose:
      "Ajoute une feature `year_mapped` issue de la colonne année.",
    recommendation:
      "Défaut **ON** — `year_mapped` est la 7e feature de la config gagnante (raw, non-normalisée).",
  },
  year_column_name: {
    purpose:
      "Nom de la colonne contenant l'année dans le DataFrame source.",
    recommendation:
      "Standard pipeline : `Annee`. Vérifiez le mapping côté étape Données si nom différent.",
  },
  year_value_mapping: {
    purpose:
      "Table de correspondance année → valeur numérique injectée comme feature.",
    recommendation:
      "Défaut **mapping 1-7** (2019→1, 2020→2, …, 2025→7) — `Year embedding learné` testé : pas d'effet vs encodage scalaire.",
  },
  year_normalization: {
    purpose:
      "Normalise la feature `year_mapped` en même temps que les autres features.",
    recommendation:
      "Défaut **OFF** — l'année reste en encodage ordinal raw (1-7), plus interprétable et validée gagnante.",
  },

  // ── Avancé — seed & pondérations ─────────────────────────────────────────
  seed: {
    purpose:
      "Graine aléatoire numpy / TensorFlow pour la reproductibilité.",
    recommendation:
      "Défaut **1750** (convention projet). Côté PL, le winner individuel Compact4 est obtenu à seed **1752** (E3_09_all3_plus_after, 94,00 % tol). Variance multi-seed observée 58-67 % TV / 89,57-94,00 % PL → multi-seed `n_seeds=3` recommandé en production.",
  },
  // Form key — used by config-form.tsx for the "capteurs permanents" toggle.
  flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **OFF** — testé exhaustivement TV (Compact9) et PL (Compact4, 80 runs `use_flag_permanent_weighting=false`). Pondération sans effet ou négative sur les deux datasets.",
  },
  // Alias requested by spec (canonical name used in the API payload).
  use_flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **OFF** — testé exhaustivement TV (Compact9) et PL (Compact4, 80 runs `use_flag_permanent_weighting=false`). Pondération sans effet ou négative sur les deux datasets.",
  },
  flag_priority_weight: {
    purpose:
      "Poids multiplicatif appliqué aux capteurs Permanent / Siredo lors du calcul de la loss.",
    recommendation:
      "Inutilisé tant que `use_flag_permanent_weighting=OFF` (config par défaut).",
  },
  // Form key — used by config-form.tsx for the "année récente" toggle.
  flag_recent_year_weighting: {
    purpose:
      "Pondère plus l'année la plus récente du jeu (la mesure la plus à jour) pour refléter les conditions actuelles.",
    recommendation:
      "Défaut **OFF** — testé, dégrade la tol de −3 pp sur ce dataset déséquilibré (42 % rows 2025).",
  },
  // Alias requested by spec (canonical name used in the API payload).
  use_flag_recent_year_weighting: {
    purpose:
      "Pondère plus l'année la plus récente du jeu (la mesure la plus à jour) pour refléter les conditions actuelles.",
    recommendation:
      "Défaut **OFF** — testé, dégrade la tol de −3 pp sur ce dataset déséquilibré (42 % rows 2025).",
  },
  recent_year_priority_weight: {
    purpose:
      "Poids multiplicatif appliqué aux lignes correspondant à l'année la plus récente du dataset (détectée automatiquement).",
    recommendation:
      "Inutilisé tant que `use_flag_recent_year_weighting=OFF` (config par défaut).",
  },

  // ── Phase 2A / 3 / 4 — Régularisation & architecture avancée ─────────────
  optimizer: {
    purpose:
      "Choix de l'optimiseur — `adam` (baseline) ou `adamw` (Adam avec weight decay découplé).",
    recommendation:
      "Défaut **adam** — AdamW testé, dégrade R² sur ce MLP.",
  },
  weight_decay: {
    purpose:
      "Pénalité L2 découplée appliquée par AdamW. Ignorée si l'optimiseur est `adam`.",
    recommendation:
      "Défaut **0** (ignoré car `adam`). Si vous passez à `adamw`, démarrez à 1e-4 — mais l'option régresse sur ce dataset.",
  },
  use_skip_connection: {
    purpose:
      "Ajoute une connexion résiduelle entrée → dernière couche cachée (force l'API Functional Keras).",
    recommendation:
      "Défaut **OFF** — testé, dégrade tol sur ce MLP.",
  },
  dropout_schedule: {
    purpose:
      "Stratégie de répartition du dropout sur les couches : `uniform` (constant) ou `decreasing` (décroissant).",
    recommendation:
      "Défaut **uniform** — répartition constante sur les 4 couches `[8, 6, 4, 3]`.",
  },
  clipnorm: {
    purpose:
      "Plafonnement de la norme globale du gradient à chaque step. `null` = désactivé.",
    recommendation:
      "Défaut **désactivé** — aucune instabilité observée avec Adam + lr 0.01 sur ce dataset.",
  },
  norm_layer: {
    purpose:
      "Type de couche de normalisation appliqué après chaque couche cachée.",
    recommendation:
      "Défaut **none** — BatchNorm / LayerNorm testés, dégradent la tol.",
  },
  use_quantile_head: {
    purpose:
      "Ajoute une tête multi-quantile (q=0.2/0.5/0.8) en parallèle de la sortie de régression.",
    recommendation:
      "Défaut **OFF** — testé, dégrade tol sur cette config.",
  },
  n_seeds: {
    purpose:
      "Nombre de seeds aléatoires entraînées par combinaison du grid — réplique l'expérience pour mesurer la variance.",
    recommendation:
      "Défaut **1** pour reproduire le best. Variance multi-seed observée 58-67 % → `n_seeds=3` recommandé en production.",
  },
  use_year_embedding: {
    purpose:
      "Route `year_mapped` à travers une couche `Embedding` apprise au lieu d'un scalaire dans la pile Dense.",
    recommendation:
      "Défaut **OFF** — testé, pas d'effet vs encodage 1-7 raw.",
  },
  target_log_transform: {
    purpose:
      "Applique `log1p(TxPen)` sur la cible avant normalisation. L'évaluation ré-applique `expm1`.",
    recommendation:
      "Défaut **OFF** — testé, dégrade la tol sur cible TxPen.",
  },
  use_curriculum: {
    purpose:
      "Apprentissage curriculaire : entraîne d'abord sur les 50 % de lignes à faible TMJOBCTV puis sur l'ensemble.",
    recommendation:
      "Défaut **OFF** — testé, dégrade tol.",
  },
  use_hard_example_mining: {
    purpose:
      "Augmente le poids des échantillons à forte erreur (>15 %) toutes les 10 époques après l'epoch 30.",
    recommendation:
      "Défaut **OFF** — testé, gain nul / dégrade selon les seeds.",
  },
  tta_iter: {
    purpose:
      "Nombre d'itérations Test-Time Augmentation (bruit gaussien sur les inputs en prédiction).",
    recommendation:
      "Défaut **1** — pas de TTA à l'inférence (gain ±0.2 pp observé).",
  },
  tta_noise_std: {
    purpose:
      "Écart-type du bruit gaussien ajouté aux features normalisées à chaque itération TTA.",
    recommendation:
      "Défaut **0.01** — ignoré si `tta_iter=1`. À monter à 0.02-0.05 uniquement si TTA activé.",
  },
  bootstrap_iter: {
    purpose:
      "Nombre d'itérations bootstrap pour calculer les intervalles de confiance à 95 % sur les métriques.",
    recommendation:
      "Défaut **1000** — ajoute des CI95 fiables sur tol_in (coût compute négligeable). `0` désactive.",
  },

  // ── PL features dérivées (Batch Compact4 winner) ─────────────────────────
  // Tooltips dédiés au modèle Poids Lourds — affichés via la clé `feature_<name>`
  // dans les chips d'INPUT_COLS lorsque mode === "pl".
  feature_fcd_log: {
    purpose:
      "`log(1 + TMJOFCDPL)` — logarithme naturel du trafic PL FCD, compresse la distribution longue-traîne (skew positif fort) et linéarise la relation entrée → débit corrigé.",
    recommendation:
      "Ablation Compact4 : **+3,18 pp tol marginal** (6 subsets avec / 4 sans, 8 seeds). Calculé par `scripts/enrich_fcdrefglobal.py` via `np.log1p(TMJOFCDPL)`. Redondant si `TMJOFCDPL` est présent — garder les deux pour la stabilité.",
  },
  feature_tv_pl_ratio: {
    purpose:
      "`TMJOFCDTV / (TMJOFCDPL + 0,1)` — ratio trafic VL/PL (floor 0,1 pour éviter div/0). Encode la composition de l'axe : ratio bas (5-15) = axe lourd, ratio élevé (>50) = voie urbaine.",
    recommendation:
      "Ablation Compact4 : **+6,07 pp tol marginal**. Calculé par `scripts/enrich_fcdrefglobal.py`. Floor 0,1 (pas 1) pour conserver l'amplitude sur petits flux PL.",
  },
  feature_dist_to_lyon_center: {
    purpose:
      "Distance Haversine (km) entre le centroïde de la LINESTRING et Place Bellecour (45,7578° N / 4,8320° E). Capte la structure radiale du trafic PL Grand Lyon (pénétrantes vs hyper-centre).",
    recommendation:
      "Ablation Compact4 : **+6,41 pp tol marginal** (le plus fort apport individuel). À recalculer si autre territoire (centre local) ; à désactiver sur territoires polycentriques où l'effet radial n'existe pas.",
  },
  feature_TMJOFCDPL: {
    purpose:
      "TMJA FCD Poids Lourds — input principal du modèle PL, fournit l'intensité brute du trafic PL observée par les FCD HERE.",
    recommendation:
      "Toujours présent dans le winner Compact4. Z-scoré par défaut. Pente de TVr la plus marquée en analyse de sensibilité.",
  },
  feature_functional_class: {
    purpose:
      "Classe fonctionnelle HERE du segment (entier 1-5, 1 = autoroute, 5 = voie résidentielle).",
    recommendation:
      "Feature catégorielle — **normalisation OFF** (laisser raw 1-5). Marginale en isolé, utile en combinaison.",
  },
  feature_truck_avg_distance_m: {
    purpose:
      "Distance inter-trucks moyenne sur le segment (mètres), depuis la donnée FCD HERE.",
    recommendation:
      "Une des 4 distances PL inter-trucks. Apporte l'information micro-locale ; retirer une seule distance ne casse pas la convergence (subset 3pl reste à ~80 %).",
  },
  feature_truck_avg_min_distance_m: {
    purpose:
      "Distance minimale inter-trucks sur le segment (mètres).",
    recommendation:
      "Complémentaire à `truck_avg_distance_m` pour capter la variabilité des pelotons PL.",
  },
  feature_truck_avg_distance_before_m: {
    purpose:
      "Distance moyenne inter-trucks avec le segment précédent (mètres).",
    recommendation:
      "Information de continuité amont — utile pour les fins de rampe / sorties d'autoroute.",
  },
  feature_truck_avg_distance_after_m: {
    purpose:
      "Distance moyenne inter-trucks avec le segment suivant (mètres).",
    recommendation:
      "Information de continuité aval — la feature qui distingue le subset gagnant `09` (94 %) du subset `07` (91 % moyen).",
  },
};

/**
 * Version stamp for the dismissed-localStorage key. Bump when the panel
 * copy is refreshed — users will see the new recommendations re-appear.
 * Encodes both the TV winner (D4_8643) and PL winner (Compact4 E3_09).
 */
export const SAM_COACHING_VERSION = "D4_8643_bs128_ep1500-PLCompact4_E3_09";
