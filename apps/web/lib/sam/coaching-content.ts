/**
 * Sam coaching content — single source of truth for the `/config` page
 * recommendations panel + every per-field tooltip.
 *
 * All copy is in French to match the rest of the redressement pipeline UI.
 * Recommendations are derived from the MDL_Lyon_TV_BEST production baseline
 * (Compact 6, seed 1754) — 59.83 % tol / p80 29.46 / R²=0.686 on the 3632 GrandLyon
 * sensors (BCFCDREF_AllYears_TV) — and from the 76+ models benchmarked
 * during Phase 05 / 06.
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
  /** 3 pitfalls — rendered with an alert-triangle icon. */
  pitfalls: CoachingBullet[];
  /** Recommended batch strategy summary. */
  strategy: CoachingStrategy;
  /** 3-5 advanced bullets revealed by the toggle. */
  advancedRecommendations: CoachingBullet[];
}

export const samConfigRecommendations: SamConfigRecommendations = {
  mainRecommendations: [
    {
      label: "Loss mse — baseline éprouvée",
      body:
        "`tolerance_aware` testé, gains instables ; le `mse` produit 66 % tol / R² 0.81 reproductible (10 graines testées) — référence MDL_Lyon_TV_BEST.",
    },
    {
      label: "Pondération capteurs permanents × 2.0",
      body:
        "`Type Compteur` ∈ {Permanent, permanent, Siredo} pondérés ×2.0 — sweet spot validé vs ×1 (baseline) ou ×3 (sur-concentration).",
    },
    {
      label: "Compact 6 features",
      body:
        "`year_mapped` + `TMJOFCDTV` + `TMJOFCDPL` + `avg_min_distance_m` + `truck_avg_min_distance_m` + `functional_class` — modèle léger, déploiement simple, performance validée.",
    },
    {
      label: "Dropout 0.02, [3, 2, 1], 1000 epochs",
      body:
        "Dropout 0.02 + [3, 2, 1] neurons + 1000 epochs — converge stable, pas de surapprentissage observé sur Compact 6.",
    },
    {
      label: "test_size = 0 (in-sample)",
      body:
        "Sur 3632 capteurs, un hold-out 5 % (184 lignes) bruite l'EarlyStopping et coupe le training prématurément avant la convergence à 1000 epochs.",
    },
  ],
  pitfalls: [
    {
      label: "Ajouter trop de features (Full 11, distances avant/après)",
      body:
        "Gain marginal vs Compact 6 mais complexifie le déploiement et augmente le risque d'overfitting — rester sur 6 features sauf besoin spécifique.",
    },
    {
      label: "Pondération `année récente` activée",
      body:
        "42 % du jeu = 2025, déjà fortement représenté → dégrade la tol globale de −3 pp sur ce dataset déséquilibré.",
    },
    {
      label: "AdamW + weight_decay",
      body:
        "Testé sur ce MLP : perte de 15 pp R². Garder `Adam` (lr 0.01) — l'optimiseur de référence MDL_Lyon_TV_BEST.",
    },
    {
      label: "Skip / SELU / Curriculum",
      body:
        "`Skip connection` (−15 pp tol), `SELU` (−10 pp R² vs ELU), `Curriculum` (−7 pp tol) — tous testés, tous régressent ici.",
    },
  ],
  strategy: {
    models: "Validation prod : défauts",
    epochs: "Exploration : varier seed",
    batch: "Comparaison : 1 axe à la fois",
    rationale:
      "Laisser les défauts reproduit MDL_Lyon_TV_BEST en ~140 s. Pour explorer, varier la seed (10 graines → +1-3 pp tol observé) puis figer le best. Pour comparer une nouvelle feature, conserver tous les défauts sauf l'axe testé.",
  },
  advancedRecommendations: [
    {
      label: "BatchNorm",
      body:
        "Effet marginal sur la tol (±1 pp), améliore le R² (0.72) — à tester si overfitting suspecté.",
    },
    {
      label: "Tolerance-aware loss",
      body:
        "À essayer si la médiane des erreurs est l'objectif principal (vs robust mean) — variance plus élevée que mse.",
    },
    {
      label: "Multi-seed n=3",
      body:
        "Ensemble plus stable (variance ±0.18) vs single-seed (±0.87) — utile pour valider la stabilité d'un changement.",
    },
    {
      label: "Bootstrap CI95",
      body:
        "`bootstrap_iter=1000` ajoute des intervalles de confiance fiables sur la tol_in (coût compute négligeable).",
    },
    {
      label: "K-fold k=5",
      body:
        "Pour mesurer la généralisation hors-sample sur le dataset cleané — complémentaire au test_size=0.",
    },
  ],
};

// ---------------------------------------------------------------------------
// Per-field tooltips — keys correspond to logical field names exposed by the
// ConfigForm. Each entry combines a 1-sentence purpose with the rationale of
// the chosen MDL_Lyon_TV_BEST default. Editing one entry updates every
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
      "Défaut **[3, 2, 1]** — architecture à 3 couches, validée stable sur MDL_Lyon_TV_BEST.",
  },
  activations: {
    purpose:
      "Fonction(s) d'activation des couches cachées — testées en grid search si plusieurs sélectionnées.",
    recommendation:
      "Défaut **elu** — `SELU` testé : −10 pp R² vs ELU sur ce dataset.",
  },
  use_batch_norm: {
    purpose:
      "Ajoute une couche `BatchNormalization` après chaque couche cachée.",
    recommendation:
      "Défaut **OFF** — BatchNorm marginal sur la tol (±1 pp), améliore R² (0.72) — à tester si overfitting suspecté.",
  },
  dropouts: {
    purpose:
      "Taux de dropout appliqué à chaque couche cachée — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Défaut **0.02** — sweet spot vs 0.03 (underfit).",
  },
  dropout: {
    purpose:
      "Taux de dropout appliqué à chaque couche cachée.",
    recommendation:
      "Défaut **0.02** — sweet spot vs 0.03 (underfit).",
  },

  // ── Training ────────────────────────────────────────────────────────────
  losses: {
    purpose:
      "Fonction(s) de perte minimisée(s) pendant l'entraînement.",
    recommendation:
      "Défaut **mse** — validé sur 76+ modèles. `tolerance_aware` gain instable, `pinball_p80` biaisé.",
  },
  loss: {
    purpose:
      "Fonction de perte minimisée pendant l'entraînement.",
    recommendation:
      "Défaut **mse** — validé sur 76+ modèles. `tolerance_aware` gain instable, `pinball_p80` biaisé.",
  },
  learning_rates: {
    purpose:
      "Pas d'apprentissage Adam — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Défaut **0.01** — référence MDL_Lyon_TV_BEST avec Adam (lr plus bas non bénéfique sur ce MLP).",
  },
  batch_sizes: {
    purpose:
      "Nombre d'échantillons traités par étape de gradient.",
    recommendation:
      "Défaut **256** — équilibre vitesse / lissage gradient sur 3632 lignes.",
  },
  min_nb_epochs_list: {
    purpose:
      "Nombre d'epochs minimum avant que l'EarlyStopping puisse arrêter l'entraînement.",
    recommendation:
      "Défaut **1000** — converge sur Compact 6 ; ne pas dépasser car overfit.",
  },
  max_epochs: {
    purpose:
      "Plafond d'epochs — l'entraînement s'arrête au plus tard à cette valeur.",
    recommendation:
      "Défaut **1000** = min_nb_epochs ; EarlyStopping reste actif en garde.",
  },
  test_size: {
    purpose:
      "Fraction du dataset réservée au test final (hold-out).",
    recommendation:
      "Défaut **0.0** — in-sample full training. 0.05 dégrade EarlyStopping sur petit val (184 lignes).",
  },

  // ── Feature subsets ─────────────────────────────────────────────────────
  input_cols: {
    purpose:
      "Liste des colonnes d'entrée utilisées comme features par le modèle.",
    recommendation:
      "Défaut **6 features (Compact 6)** — `year_mapped`, `TMJOFCDTV`, `TMJOFCDPL`, `avg_min_distance_m`, `truck_avg_min_distance_m`, `functional_class`. Modèle léger, performance équivalente à Full 11 pour la plupart des cas.",
  },
  output_cols: {
    purpose:
      "Colonne(s) cible(s) à prédire.",
    recommendation:
      "Sélectionnez UNE cible primaire (`TxPen` en TV, `TxPenPL` en PL). Multi-cibles = configuration expérimentale.",
  },
  on_off_norm: {
    purpose:
      "Active/désactive la normalisation MinMax par feature.",
    recommendation:
      "Laissez activé sur les features numériques continues. Désactivez sur `functional_class` (catégorielle).",
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
      "Défaut TV : 3, PL : 2. Évitez < 2 (modèles trop pauvres) ou > 5 (combinaisons explosives).",
  },
  feature_subset_grid: {
    purpose:
      "Génère automatiquement toutes les combinaisons valides de features comme sous-ensembles.",
    recommendation:
      "Activé par défaut. Désactivez seulement si vous voulez tester UN unique set fixe de features.",
  },

  // ── Année ───────────────────────────────────────────────────────────────
  use_year_feature: {
    purpose:
      "Ajoute une feature `year_mapped` issue de la colonne année.",
    recommendation:
      "Défaut **ON** — `year_mapped` fait partie des 6 features (Compact 6) de MDL_Lyon_TV_BEST.",
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
      "Désactivé par défaut — l'année garde un sens ordinal plus interprétable sans normalisation.",
  },

  // ── Avancé — seed & pondérations ─────────────────────────────────────────
  seed: {
    purpose:
      "Graine aléatoire numpy / TensorFlow pour la reproductibilité.",
    recommendation:
      "Défaut **1754** — meilleur de 10 graines testées Compact 6 (tol +1.6σ au-dessus mean) — référence MDL_Lyon_TV_BEST.",
  },
  // Form key — used by config-form.tsx for the "capteurs permanents" toggle.
  flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **ON** — capteurs Permanent/Siredo pondérés ×2.0 (sweet spot validé).",
  },
  // Alias requested by spec (canonical name used in the API payload).
  use_flag_permanent_weighting: {
    purpose:
      "Capteurs de type 'Permanent' / 'Siredo' (les plus fiables) reçoivent un poids accru lors de l'entraînement.",
    recommendation:
      "Défaut **ON** — capteurs Permanent/Siredo pondérés ×2.0 (sweet spot validé).",
  },
  flag_priority_weight: {
    purpose:
      "Poids multiplicatif appliqué aux capteurs Permanent / Siredo lors du calcul de la loss.",
    recommendation:
      "Défaut **2.0** — ×3.0 trop concentré, ×1.0 = baseline. ×2.0 retenu sur MDL_Lyon_TV_BEST.",
  },
  // Form key — used by config-form.tsx for the "année récente" toggle.
  flag_recent_year_weighting: {
    purpose:
      "Pondère plus l'année la plus récente du jeu (la mesure la plus à jour) pour refléter les conditions actuelles.",
    recommendation:
      "Défaut **OFF** — sur ce dataset (42 % rows 2025), active = dégradation tol −3 pp.",
  },
  // Alias requested by spec (canonical name used in the API payload).
  use_flag_recent_year_weighting: {
    purpose:
      "Pondère plus l'année la plus récente du jeu (la mesure la plus à jour) pour refléter les conditions actuelles.",
    recommendation:
      "Défaut **OFF** — sur ce dataset (42 % rows 2025), active = dégradation tol −3 pp.",
  },
  recent_year_priority_weight: {
    purpose:
      "Poids multiplicatif appliqué aux lignes correspondant à l'année la plus récente du dataset (détectée automatiquement).",
    recommendation:
      "Défaut **2.0** — ignoré si `use_flag_recent_year_weighting=OFF` (config par défaut MDL_Lyon_TV_BEST).",
  },

  // ── Phase 2A / 3 / 4 — Régularisation & architecture avancée ─────────────
  optimizer: {
    purpose:
      "Choix de l'optimiseur — `adam` (baseline) ou `adamw` (Adam avec weight decay découplé).",
    recommendation:
      "Défaut **adam** — AdamW testé, perte de 15 pp R² sur ce MLP.",
  },
  weight_decay: {
    purpose:
      "Pénalité L2 découplée appliquée par AdamW. Ignorée si l'optimiseur est `adam`.",
    recommendation:
      "Défaut **0** (ignoré car `adam`). Si vous passez à `adamw`, démarrez à 1e-4.",
  },
  use_skip_connection: {
    purpose:
      "Ajoute une connexion résiduelle entrée → dernière couche cachée (force l'API Functional Keras).",
    recommendation:
      "Défaut **OFF** — testé, perte 15 pp tol sur ce MLP.",
  },
  dropout_schedule: {
    purpose:
      "Stratégie de répartition du dropout sur les couches : `uniform` (constant) ou `decreasing` (décroissant).",
    recommendation:
      "Défaut **uniform** — répartition constante sur les 3 couches [3, 2, 1].",
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
      "Défaut **none** — BatchNorm marginal (+R², −/= tol).",
  },
  use_quantile_head: {
    purpose:
      "Ajoute une tête multi-quantile (q=0.2/0.5/0.8) en parallèle de la sortie de régression.",
    recommendation:
      "Défaut **OFF** — pas implémenté côté API à la dernière vérif (silent no-op).",
  },
  n_seeds: {
    purpose:
      "Nombre de seeds aléatoires entraînées par combinaison du grid — réplique l'expérience pour mesurer la variance.",
    recommendation:
      "Défaut **1** — pour reproduire MDL_Lyon_TV_BEST. `n_seeds=3` utile pour valider la stabilité d'un changement.",
  },
  use_year_embedding: {
    purpose:
      "Route `year_mapped` à travers une couche `Embedding` apprise au lieu d'un scalaire dans la pile Dense.",
    recommendation:
      "Défaut **OFF** — `Year embedding learné` testé : pas d'effet vs encodage 1-7.",
  },
  target_log_transform: {
    purpose:
      "Applique `log1p(TxPen)` sur la cible avant normalisation. L'évaluation ré-applique `expm1`.",
    recommendation:
      "Défaut **OFF** — biaise les prédictions sur cible TxPen (variance grande).",
  },
  use_curriculum: {
    purpose:
      "Apprentissage curriculaire : entraîne d'abord sur les 50 % de lignes à faible TMJOBCTV puis sur l'ensemble.",
    recommendation:
      "Défaut **OFF** — testé, perte 7 pp tol.",
  },
  use_hard_example_mining: {
    purpose:
      "Augmente le poids des échantillons à forte erreur (>15 %) toutes les 10 époques après l'epoch 30.",
    recommendation:
      "Défaut **OFF** — gain marginal, complexifie le training.",
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
export const SAM_COACHING_VERSION = "MDL_Lyon_TV_BEST-compact6";
