/**
 * Sam coaching content — single source of truth for the `/config` page
 * recommendations panel + every per-field tooltip.
 *
 * All copy is in French to match the rest of the redressement pipeline UI.
 * Recommendations are drawn from the audit (Phase 1 → 5):
 *   - p80 / tol_in sensitivity to loss & outliers
 *   - flag_comptage + flag_y2025 weighting gains on the in-tol sensor count
 *   - empirical sweet-spot grid on dropout / neurons_factors
 *   - bootstrap CI95 for stability of tol_in
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
      label: "Loss",
      body:
        "Préférez `huber` ou `tolerance_aware` au lieu de `mse` pour réduire l'impact des outliers (~−3 à −5 % sur le p80).",
    },
    {
      label: "Pondération",
      body:
        "Activez `flag_comptage` + `flag_y2025` ensemble : gain observé de +60 à +90 capteurs in-tol sur les runs audit.",
    },
    {
      label: "Architecture",
      body:
        "Testez `dropout 0.10–0.15` avec `neurons_factors [2.0, 1.5, 1.0]` — sweet spot observé sur la grille d'audit.",
    },
    {
      label: "Régularisation",
      body:
        "`AdamW` + `weight_decay=1e-4` réduit l'overfit sur les modèles deep (≥3 couches).",
    },
    {
      label: "Validation",
      body:
        "`test_size=0.05` (5 %) combiné à un bootstrap CI95 donne des intervalles fiables sur tol_in.",
    },
  ],
  pitfalls: [
    {
      label: "Min epochs trop bas",
      body:
        "`min_nb_epochs < 20` produit des modèles dégénérés. Gardez toujours ≥ 20, idéalement ≥ 100.",
    },
    {
      label: "MSE sur cible brute",
      body:
        "Loss `mse` sur cible non-transformée est fortement biaisée par les capteurs > 20 000 TMJOBCTV — préférez `huber`.",
    },
    {
      label: "Seed unique",
      body:
        "`n_seeds=1` ne mesure pas la variance — sur ce dataset bruité, les runs ne sont pas comparables sans multi-seed.",
    },
  ],
  strategy: {
    models: "30–60 modèles",
    epochs: "200–500 epochs",
    batch: "batch_size = 256",
    rationale:
      "Volume suffisant pour couvrir les sous-ensembles de features sans exploser le temps de calcul GPU/CPU.",
  },
  advancedRecommendations: [
    {
      label: "Skip connections",
      body:
        "Pour les architectures ≥ 3 couches, des skip connections (résiduelles) améliorent la stabilité du gradient.",
    },
    {
      label: "LayerNorm",
      body:
        "`LayerNorm` après chaque couche cachée stabilise mieux que `BatchNorm` quand `batch_size < 128`.",
    },
    {
      label: "Quantile head",
      body:
        "Une tête de prédiction quantile (q=0.5) en parallèle de la régression donne un proxy direct pour le p80.",
    },
    {
      label: "Multi-seed averaging",
      body:
        "Moyenner 3–5 seeds par configuration réduit la variance des métriques de tol_in de ~30 %.",
    },
    {
      label: "Cosine LR schedule",
      body:
        "Un schedule cosine + warmup sur 10 % des epochs surpasse le LR constant sur les runs ≥ 500 epochs.",
    },
  ],
};

// ---------------------------------------------------------------------------
// Per-field tooltips — keys correspond to logical field names exposed by the
// ConfigForm. Each entry combines a 1-sentence purpose with an audit-driven
// recommendation. Editing one entry updates every tooltip on the form.
// ---------------------------------------------------------------------------

export interface FieldTooltip {
  /** One-sentence description of what the field controls. */
  purpose: string;
  /** Concrete value / range recommendation drawn from the audit. */
  recommendation: string;
}

export const fieldTooltips: Record<string, FieldTooltip> = {
  // ── Architecture ────────────────────────────────────────────────────────
  neurons_factors: {
    purpose:
      "Facteurs multiplicateurs de N (nombre de features) qui définissent le nombre de neurones par couche cachée.",
    recommendation:
      "Sweet spot audit : [2.0, 1.5, 1.0] ou [2, 1]. Ajoutez [3, 2, 1] pour les datasets riches (≥ 8 features).",
  },
  activations: {
    purpose:
      "Fonction(s) d'activation des couches cachées — testées en grid search si plusieurs sélectionnées.",
    recommendation:
      "`elu` reste la baseline robuste. Testez `selu` si vous activez LayerNorm/SkipConnections.",
  },
  use_batch_norm: {
    purpose:
      "Ajoute une couche `BatchNormalization` après chaque couche cachée.",
    recommendation:
      "Recommandé pour `batch_size ≥ 128`. Désactivez si vous passez à `batch_size < 64` (préférez LayerNorm).",
  },
  dropouts: {
    purpose:
      "Taux de dropout appliqué à chaque couche cachée — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Sweet spot observé : 0.10 à 0.15. Évitez 0.0 (overfit) et > 0.30 (sous-apprentissage).",
  },

  // ── Training ────────────────────────────────────────────────────────────
  losses: {
    purpose:
      "Fonction(s) de perte minimisée(s) pendant l'entraînement.",
    recommendation:
      "Préférez `huber` à `mse` — réduit l'impact des outliers (~−3 à −5 % p80). `mae` reste utile en secondaire.",
  },
  learning_rates: {
    purpose:
      "Pas d'apprentissage Adam — testé en grid search si plusieurs valeurs.",
    recommendation:
      "Baseline : `0.01`. Pour les architectures deep (≥ 3 couches), essayez aussi `0.001`.",
  },
  batch_sizes: {
    purpose:
      "Nombre d'échantillons traités par étape de gradient.",
    recommendation:
      "Baseline audit : `256`. Augmentez à `512` si vous avez ≥ 5 000 lignes d'entraînement.",
  },
  min_nb_epochs_list: {
    purpose:
      "Nombre d'epochs minimum avant que l'EarlyStopping puisse arrêter l'entraînement.",
    recommendation:
      "Toujours ≥ 20 (< 20 = modèles dégénérés). Recommandé : `[100, 200]` pour bien explorer.",
  },
  max_epochs: {
    purpose:
      "Plafond d'epochs — l'entraînement s'arrête au plus tard à cette valeur.",
    recommendation:
      "500 suffit pour la plupart des configs. Montez à 1000 si l'EarlyStopping ne se déclenche jamais.",
  },
  test_size: {
    purpose:
      "Fraction du dataset réservée au test final (hold-out).",
    recommendation:
      "`0.05` (5 %) recommandé — combiné à un bootstrap CI95 pour des intervalles de tol_in fiables.",
  },

  // ── Feature subsets ─────────────────────────────────────────────────────
  input_cols: {
    purpose:
      "Liste des colonnes d'entrée utilisées comme features par le modèle.",
    recommendation:
      "Gardez le set par défaut TV/PL — ajoutez `TMJOBCTV_HPM` / `HPS` uniquement si présents dans vos données.",
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
      "Activez si votre dataset couvre ≥ 2 années — gain mesuré sur la tol_in sur les runs 2023-2025.",
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
      "Mapping linéaire (1, 2, 3...) suffit. Évitez les valeurs négatives ou les sauts non monotones.",
  },
  year_normalization: {
    purpose:
      "Normalise la feature `year_mapped` en même temps que les autres features.",
    recommendation:
      "Désactivé par défaut — l'année garde un sens ordinal plus interprétable sans normalisation.",
  },

  // ── Avancé ──────────────────────────────────────────────────────────────
  seed: {
    purpose:
      "Graine aléatoire numpy / TensorFlow pour la reproductibilité.",
    recommendation:
      "`1750` par défaut sur le projet. Changez pour explorer la variance (idéalement avec multi-seed).",
  },
  use_flag_comptage_weighting: {
    purpose:
      "Pondère les échantillons selon le flag `flag_comptage` (capteurs permanents) dans la loss.",
    recommendation:
      "Activez — gain observé de +60 à +90 capteurs in-tol sur les runs audit Phase 2.",
  },
  flag_priority_weight: {
    purpose:
      "Poids appliqué aux échantillons `flag_comptage=1` (capteurs permanents).",
    recommendation:
      "`4.0` est le sweet spot audit. Évitez > 8.0 (surapprentissage sur les permanents).",
  },

  // ── Phase 2A / 3 / 4 — Régularisation & architecture avancée ─────────────
  optimizer: {
    purpose:
      "Choix de l'optimiseur — `adam` (baseline) ou `adamw` (Adam avec weight decay découplé).",
    recommendation:
      "`adamw` + `weight_decay=1e-4` recommandé sur les architectures ≥ 3 couches pour limiter l'overfit.",
  },
  weight_decay: {
    purpose:
      "Pénalité L2 découplée appliquée par AdamW. Ignorée si l'optimiseur est `adam`.",
    recommendation:
      "`1e-4` (0.0001) est un point de départ sûr. > 1e-2 dégrade généralement la convergence.",
  },
  use_skip_connection: {
    purpose:
      "Ajoute une connexion résiduelle entrée → dernière couche cachée (force l'API Functional Keras).",
    recommendation:
      "Activez sur les architectures ≥ 3 couches — améliore la stabilité du gradient.",
  },
  dropout_schedule: {
    purpose:
      "Stratégie de répartition du dropout sur les couches : `uniform` (constant) ou `decreasing` (décroissant).",
    recommendation:
      "`decreasing` est préféré sur les architectures profondes — moins de dropout sur les dernières couches.",
  },
  clipnorm: {
    purpose:
      "Plafonnement de la norme globale du gradient à chaque step. `null` = désactivé.",
    recommendation:
      "Activez avec `1.0` si vous observez des instabilités (loss NaN ou pics) durant l'entraînement.",
  },
  norm_layer: {
    purpose:
      "Type de couche de normalisation appliqué après chaque couche cachée.",
    recommendation:
      "`batch` quand `batch_size ≥ 128`, `layer` quand `batch_size < 64`. `none` désactive complètement.",
  },
  use_quantile_head: {
    purpose:
      "Ajoute une tête multi-quantile (q=0.2/0.5/0.8) en parallèle de la sortie de régression.",
    recommendation:
      "Recommandé pour estimer directement le p80 sans bootstrap. Coût compute marginal (~+5 %).",
  },
  n_seeds: {
    purpose:
      "Nombre de seeds aléatoires entraînées par combinaison du grid — réplique l'expérience pour mesurer la variance.",
    recommendation:
      "`3` à `5` réduit la variance des métriques de tol_in d'environ 30 %. Au-delà : coût marginal élevé.",
  },
  use_year_embedding: {
    purpose:
      "Route `year_mapped` à travers une couche `Embedding` apprise au lieu d'un scalaire dans la pile Dense.",
    recommendation:
      "Activez si vous avez ≥ 3 années dans le dataset — meilleure représentation qu'un mapping linéaire.",
  },
  target_log_transform: {
    purpose:
      "Applique `log1p(TxPen)` sur la cible avant normalisation. L'évaluation ré-applique `expm1`.",
    recommendation:
      "Activez si la distribution de TxPen est très asymétrique — réduit l'impact des outliers en valeur cible.",
  },
  use_curriculum: {
    purpose:
      "Apprentissage curriculaire : entraîne d'abord sur les 50 % de lignes à faible TMJOBCTV puis sur l'ensemble.",
    recommendation:
      "Utile sur les datasets très hétérogènes. Désactivé par défaut — testez si la convergence est instable.",
  },
  use_hard_example_mining: {
    purpose:
      "Augmente le poids des échantillons à forte erreur (>15 %) toutes les 10 époques après l'epoch 30.",
    recommendation:
      "Activez sur les datasets bruités — gain typique de quelques points de tol_in. Boost compound limité à 3x.",
  },
  tta_iter: {
    purpose:
      "Nombre d'itérations Test-Time Augmentation (bruit gaussien sur les inputs en prédiction).",
    recommendation:
      "`1` = pas de TTA. `5` à `10` lisse les prédictions sans coût d'entraînement supplémentaire.",
  },
  tta_noise_std: {
    purpose:
      "Écart-type du bruit gaussien ajouté aux features normalisées à chaque itération TTA.",
    recommendation:
      "`0.01` à `0.05` selon la sensibilité du modèle. Plus élevé = plus de lissage mais perte de finesse.",
  },
  bootstrap_iter: {
    purpose:
      "Nombre d'itérations bootstrap pour calculer les intervalles de confiance à 95 % sur les métriques.",
    recommendation:
      "`1000` est le défaut éprouvé. `0` désactive complètement. Plage valide : 0 ou 100–10 000.",
  },
};

/**
 * Version stamp for the dismissed-localStorage key. Bump when the panel
 * copy is refreshed — users will see the new recommendations re-appear.
 */
export const SAM_COACHING_VERSION = "v1";
