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
      "Défaut **[8, 6, 4, 3]** — 4 layers wider validée sur Batch Compact9 (71.23 % tol). Plafond observé : au-delà de 6 couches ou 12 neurones d'entrée, plus aucun gain.",
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
      "Défaut **128** — LE levier-clé : +4-5 pp tol vs bs=256. Surtout ne pas changer.",
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
      "Défaut **7 features** — `year_mapped`, `TMJOFCDTV`, `TMJOFCDPL`, `functional_class`, `avg_distance_before_m`, `avg_min_distance_m`, `truck_avg_distance_before_m`. Ajouter une 3e distance VL = gain marginal.",
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
      "Défaut **1750** — variance multi-seed observée 58-67 % sur même config. Toujours essayer plusieurs graines (`n_seeds=3`) en production.",
  },
  // Form key — used by config-form.tsx for the "capteurs permanents" toggle.
  flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **OFF** — testé exhaustivement, pondération sans effet ou négative sur ce dataset.",
  },
  // Alias requested by spec (canonical name used in the API payload).
  use_flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **OFF** — testé exhaustivement, pondération sans effet ou négative sur ce dataset.",
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
};

/**
 * Version stamp for the dismissed-localStorage key. Bump when the panel
 * copy is refreshed — users will see the new recommendations re-appear.
 */
export const SAM_COACHING_VERSION = "D4_8643_bs128_ep1500";
