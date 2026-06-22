# Model Card — Redressement de debits (MDL Redressement Tool)

Carte de modele decrivant le reseau de neurones utilise par l'outil de
redressement de debits routiers. Tous les elements ci-dessous sont verifies
dans le code source sous `apps/api/app/services/ml/`.

---

## 1. Tache

Redressement (correction / estimation) de debits de trafic a partir de
donnees de comptage et de variables explicatives.

L'outil supporte plusieurs typologies de vehicules / periodes, materialisees
par des modeles entraines separement avec la meme mecanique :

- **TV** — tous vehicules ;
- **PL** — poids lourds ;
- **HPM** — heure de pointe du matin ;
- **HPS** — heure de pointe du soir.

La cible apprise est exprimee en espace z-score (cible normalisee par
`mu_y` / `sigma_y`) ; la regression est de type point-estimate par defaut,
avec une variante multi-quantile optionnelle.

## 2. Entrees / Sorties

### Entrees
- Vecteur de variables continues de dimension `input_size` (resolu
  dynamiquement a partir des colonnes selectionnees), passe a
  `keras.Input(shape=(input_size,))`
  (`model_builder.py`, `_build_functional` / `_build_sequential`).
- Les entrees sont normalisees (z-score) avant le modele ; cf.
  `normalize.py`.
- Variable categorielle de millesime `year_mapped` (encodage 1..N, mapping
  canonique 2019..2025 = 1..7) — optionnellement routee vers une couche
  d'embedding apprise (`year_embedding`, `_build_with_year_embedding`).

### Sorties
- **Mode point-estimate (defaut)** : `output_size` neurone(s) de sortie,
  activation lineaire (`Dense(out_units, activation="linear")`).
- **Mode multi-quantile (P3.9, optionnel)** : `len(quantiles)` neurones de
  sortie (defaut `quantiles = (0.2, 0.5, 0.8)`), activation lineaire. La
  prediction principale en aval est la colonne q=0.5 ; q=0.2 / q=0.8
  fournissent un intervalle indicatif
  (`build_model(..., use_quantile_head=True)`).

## 3. Architecture

MLP entierement connecte, a profondeur et largeur parametrables
(`build_model`, `model_builder.py`).

- Profondeur / largeur via `neurons_factors` (defaut `[1.0, 1.0]`) : chaque
  couche cachee a `max(2, round(input_size * factor))` neurones.
- Bloc cache standard : `Dropout -> (Normalisation optionnelle) -> Dense`
  (`_apply_hidden_stack`).
- Activations : `elu` / `relu` / `selu` ... ; SELU declenche l'initialiseur
  `lecun_normal` + `AlphaDropout` et desactive toute normalisation
  supplementaire (auto-normalisant). Sinon initialiseur `he_normal`.
- Normalisation (P3.7) : `none` / `batch` / `layer` via `norm_layer`
  (retro-compatible avec le booleen historique `use_batch_norm`).
- Options : embedding du millesime (P2B.7), connexion skip entree -> derniere
  couche cachee (P3.3), planning de dropout `uniform` / `decreasing` (P3.4).
- Trois chemins de construction selon les options : Sequential (chemin
  historique, byte-identique sans nouvelle option), Functional (skip /
  quantile), Functional avec embedding millesime.
- Optimiseur (P3.1/P3.5) : `Adam` (defaut) ou `AdamW` (`weight_decay`
  decouple), avec `clipnorm` optionnel (`_build_optimizer`).

## 4. Perte par defaut + alternatives

Perte par defaut : **MSE** (`build_model(loss="mse")`).

Alternatives disponibles (`losses.py`, resolues via `keras.losses.get`
et enregistrees au chargement du module) :

- `huber` -> `HuberLoss(delta=0.25)` ;
- `mae` -> `MeanAbsoluteError` ;
- `tolerance_aware` -> `ToleranceAwareLoss(tolerance=0.15,
  penalty_factor=1.5)` : MAE en espace z-score avec penalite
  supplementaire sur les echantillons hors tolerance ;
- `pinball_p80` / `pinball` -> `PinballP80Loss` (q=0.8) ;
- `PinballLoss(quantile=...)` : pinball parametrable.

En mode multi-quantile, la perte est automatiquement remplacee par une
**somme/moyenne de pertes pinball** sur les quantiles
(`_multi_quantile_loss`, `_compile_model(..., use_quantile_head=True)`).

## 5. Metrique metier

Definitions verifiees dans `metrics_advanced.py` et `stats_compare.py` :

- **Tolerance +/-15 %** (`tol_in_pct`) : pourcentage de capteurs dont
  l'erreur relative `|pred - obs| / obs` est dans la bande de tolerance.
  Le seuil par defaut utilise dans la derive annuelle est `<= 15 %`
  (`_compute_drift_by_year`). Le code de tolerance pre-calcule
  `Tolerance_IN_OUT == 1` ("inclus") sert au comptage
  (`_metric_tol_in_pct`, `_stratify_by_tmja`).
- **p80 de l'erreur relative** (`_metric_p80_err_rel`) : 80e percentile de
  `|obs - pred| / obs * 100`.
- **R2** (`_metric_r2`) : coefficient de determination, version ponderee
  disponible lorsque des poids sont fournis ; renvoie `0.0` si la variance
  totale est nulle.

Pendant l'entrainement (mode point-estimate), Keras suit egalement `mae`,
`mape` et `r2` comme metriques de compilation
(`_compile_model`).

## 6. Validation

- **Holdout** : split interne train / validation via `test_size` dans le
  pipeline d'entrainement (`training_pipeline.py`).
- **K-fold** (P1.3, `kfold.py`) : re-entrainement du modele sur k plis avec
  exactement les memes hyperparametres (1 combo, `test_size=0` pour que le
  pli tenu de cote joue le role de validation), via le pipeline public
  `run_training` ; mesure la variance inter-plis des metriques.
- **Bootstrap CI95** (P1.1, `bootstrap_ci95`) : intervalle de confiance a
  95 % par percentile (2.5e / 97.5e) sur `tol_in_pct` / p80 / R2,
  `n_iter=1000` par defaut, seed 1750. Renvoie `None` en dessous de
  `_BOOTSTRAP_MIN_SAMPLES = 30` echantillons (bootstrap non fiable sur
  petit echantillon).
- **McNemar** (P1.4, `stats_compare.py`) : test apparie non parametrique sur
  le statut binaire `in_tolerance` de chaque capteur, pour comparer deux
  modeles. Branche chi2 avec correction de continuite si discordances
  `n01 + n10 >= 25`, sinon test binomial exact bilateral (`p = 0.5`).
- **Stratification** par bucket de trafic (P1.2, `_stratify_by_tmja`) :
  metriques recalculees sur 4 buckets canoniques (`0-1k`, `1k-5k`, `5k-20k`,
  `20k+`) ; drapeau `low_sample_warning` sous 10 lignes (buckets non
  supprimes).
- **Derive annuelle** (P4.3, `_compute_drift_by_year`) : R2 / MAE /
  tol_in_pct / p80 par `year_mapped` ; annees a moins de
  `_DRIFT_MIN_SAMPLES = 10` lignes ignorees.

## 7. Reproductibilite

- **Seed de base : 1750** (convention projet).
- **Re-seed par run** (`training_pipeline.py`) :
  `run_idx = model_idx - 1` (0-based), puis
  `run_seed = seed + run_idx`, suivi de
  `seed_everything(run_seed, enable_op_determinism=False)` puis
  `tf.keras.utils.set_random_seed(run_seed)`. Chaque run du grid obtient
  ainsi un offset deterministe unique.
- `seed_everything` (`seeding.py`) graine Python `random`, NumPy,
  TensorFlow et Keras et active `tf.config.experimental.enable_op_determinism`
  (activation unique en amont du grid).
- `derive_seed` existe dans `seeding.py` mais est **du code mort** (non
  utilise par le pipeline).
- GPU desactive avant tout import TensorFlow
  (`CUDA_VISIBLE_DEVICES=-1`, `TF_CPP_MIN_LOG_LEVEL=3`) — entrainement et
  evaluation deterministes sur CPU.
- **Lineage `meta.json`** (`packaging.py`, `build_meta`) : horodatage,
  version Python / plateforme / hote, `seed`, `data_sha256` (hash stable du
  contenu du DataFrame), versions TensorFlow / Keras / NumPy / scikit-learn,
  et `git_sha` (HEAD). Embarque dans l'archive du modele.

## 8. Limites connues

- **Croisement de quantiles (quantile crossing)** : en mode multi-quantile,
  chaque quantile est optimise independamment puis les pertes pinball sont
  moyennees. Cette somme de pinballs **n'est pas monotone** : aucune
  contrainte n'impose `q20 <= q50 <= q80` ligne par ligne, donc les
  quantiles predits peuvent se croiser (cf. `_multi_quantile_loss` dans
  `model_builder.py`). Aucun re-tri / isotonisation n'est applique ; la
  prediction principale reste la colonne q=0.5.
- **Tolerance approximee dans `ToleranceAwareLoss`** : la cible etant en
  espace z-score, la tolerance est interpretee comme une fraction d'un
  ecart-type et non comme un +/-15 % relatif strict (cf. note
  d'approximation dans `losses.py`).
- **Robustesse inter-plis** : un modele dont `tol_in_pct` varie fortement
  entre plis k-fold n'est pas robuste, meme avec un bon score sur un seul
  split (cf. `kfold.py`).
- **Bootstrap non fiable sous 30 echantillons** : `bootstrap_ci95` renvoie
  `None` (cf. `_BOOTSTRAP_MIN_SAMPLES`).
- **`obs == 0`** : capteurs a observation nulle traites comme hors tolerance
  (erreur relative indefinie) dans `in_tolerance_mask` (`stats_compare.py`).

## 9. Donnees

- Source : donnees FCD (Floating Car Data) Grand Lyon, completees par les
  variables de comptage et explicatives consommees par le modele.
- Les colonnes du DataFrame respectent les 35 noms standard du projet
  (cf. `project-context.md`).
- L'integrite des donnees d'entrainement est tracee via
  `data_sha256` dans `meta.json` (`packaging.py`).

---

*Document de reference verifie ligne par ligne dans
`apps/api/app/services/ml/` (model_builder.py, losses.py, seeding.py,
metrics_advanced.py, stats_compare.py, kfold.py, training_pipeline.py,
packaging.py, normalize.py).*
