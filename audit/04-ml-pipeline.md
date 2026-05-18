# Audit pipeline ML & data — MDL Redressement Tool v2

## Resume executif

**Note globale : 4.5 / 10.**

Le pipeline ML reproduit fidelement le script Streamlit historique (`xScripts/CreateMDL_TV.py`) — c'est sa qualite et son plafond. Les fonctions de normalisation, d'application de modele et de calcul GEH sont correctes et testees unitairement (`test_normalize.py`, `test_grid_search.py`, `test_data_prep.py`). L'architecture "service" (`apps/api/app/services/ml/*.py`) est nettement superieure au router "live" (`apps/api/app/routers/training.py`) : separation des couches, dataclasses GridCombination, support sample_weight, metriques etendues, batch_norm propre. Helas, **c'est le router live qui tourne en production** — pas le service. Resultat : on perd le sample weighting `flag_comptage`, les metriques MAPE/R2 train-time, la lisibilite et une partie du chemin de tests.

Trois risques majeurs sur la qualite scientifique des modeles produits :

1. **Reproductibilite incomplete** : `PYTHONHASHSEED` non figee, `tf.config.experimental.enable_op_determinism()` jamais appele, ops GPU/CPU non deterministes acceptees (`TF_DISABLE_SEGMENT_REDUCTION_OP_DETERMINISM_EXCEPTIONS=1` desactive justement le garde-fou). Un re-run du meme grid search ne redonne pas exactement les memes poids.
2. **Early-stopping mal configure** : `start_from_epoch=min_nb_epochs` (500-1000) bloque tout arret precoce pendant la moitie de l'entrainement, meme en cas de divergence claire. Combine avec `patience=max(30, max_epochs//10)=205` epochs, on peut bruler 700 epochs avant de stopper un modele moribond. Cout calcul direct, pas de gain qualite.
3. **Pas de tracking d'experimentations, format de sauvegarde fragile** : aucun MLflow / W&B, le nom de run encode les HPs mais ne couvre pas seed/`max_epochs`/`use_batch_norm` (collisions possibles), les poids sont stockes en `.weights.h5` (legacy HDF5) avec une architecture rejouee depuis `NNarchitecture.json` — fragile au changement d'API Keras 3, impossible de comparer deux sessions entre elles, irreproductible a 6 mois sans une image Docker pinnee.

---

## Findings ML tries P0 / P1 / P2

### P0 — Bloquants scientifiques

#### P0-1 — Reproductibilite illusoire
- **Fichiers** : `apps/api/app/routers/training.py:280, 338-340` ; `apps/api/app/services/ml/training_pipeline.py:240-241`
- **Constat** : seules `np.random.seed` et `tf.random.set_seed` sont appelees. Manquent :
  - `random.seed(seed)` (utilise implicitement par Keras pour les initialisations, le shuffle de `model.fit`, etc.)
  - `os.environ['PYTHONHASHSEED'] = str(seed)` — doit etre fixe **avant le demarrage du processus** Python pour avoir un effet
  - `tf.config.experimental.enable_op_determinism()` (TF >=2.10) — sans lui, les ops `tf.nn.bias_add`, les reductions GPU, et certains kernels CPU restent non deterministes
  - `keras.utils.set_random_seed(seed)` (qui groupe les trois generateurs)
- **Pire** : ligne 280, `TF_DISABLE_SEGMENT_REDUCTION_OP_DETERMINISM_EXCEPTIONS=1` **desactive explicitement** l'exception qui aurait alerte si une op non-deterministe etait utilisee. Le commentaire pretend que c'est pour "GPU" mais le code force CPU (`CUDA_VISIBLE_DEVICES=-1`).
- **`train_test_split`** est seede (`random_state=seed`, training.py:359 / data_prep.py:161) — bon point.
- **`tf.random.set_seed(seed)` n'est appele qu'une fois au demarrage du worker** ; il n'est pas re-applique avant chaque `model.fit`. Avec un grid search de 2300 modeles dans la meme session TF, le state s'accumule et l'ordre des combos influe sur les poids initiaux.
- **Impact** : impossible de comparer deux runs scientifiquement, debug "pourquoi ce modele est-il meilleur aujourd'hui ?" infaisable, audit reglementaire (si jamais cet outil sert a justifier un investissement infra) compromis.

#### P0-2 — Sample weighting du `flag_comptage` perdu en production
- **Fichiers** : `apps/api/app/services/ml/training_pipeline.py:172-181, 137-145` (logique propre) vs `apps/api/app/routers/training.py:580-590` (router live, **ne passe jamais** `sample_weight`).
- **Constat** : le service ML propre gere `use_flag_comptage_weighting` avec `flag_priority_weight=4.0` — les capteurs permanents/tournants comptent 4x plus pendant l'entrainement, ce qui est la regle metier explicite (cf. derivation `_derive_flag_comptage` qui marque "per"/"tou"). Le router live, lui, accepte le parametre dans `TrainingConfig` (training.py:89-90) mais **ne l'utilise jamais** dans `_training_worker` — aucun `sample_weight` n'est passe a `model.fit` (training.py:580-590).
- **Impact** : les modeles entraines dans l'app reelle ignorent une regle metier qui devrait booster d'un facteur 4 le poids des capteurs de reference. Le modele se cale davantage sur la masse des capteurs ponctuels (moins fiables) au lieu des permanents. Ecart attendu sur RMSE et tolerance des capteurs PER/TOU.
- **Recommandation** : faire pointer le router sur `services/ml/training_pipeline.run_training()` au lieu de re-coder une version degradee.

#### P0-3 — Early-stopping qui n'arrete jamais a temps
- **Fichier** : `apps/api/app/routers/training.py:541-577` ; `apps/api/app/services/ml/training_pipeline.py:107-115`
- **Constat** :
  ```python
  patience = max(30, max_epochs // 10)  # = 205 avec max_epochs=2050
  EarlyStopping(
      monitor=monitor_metric,
      patience=patience,
      restore_best_weights=True,
      start_from_epoch=min_ep,  # 500 ou 1000
  )
  ```
  `start_from_epoch=500` interdit a EarlyStopping de stopper avant l'epoch 500, meme si la `val_loss` diverge des l'epoch 50. Combine a `patience=205`, on peut entrainer 705 epochs sur un modele qui surapprend depuis longtemps. Avec 2300 combos x 700 epochs en moyenne, le cout est colossal.
- **Pas de `ReduceLROnPlateau`** — un classique sur Adam avec LR=0.01 ou 0.001 pour stabiliser la fin d'entrainement.
- **Recommandation** : retirer `start_from_epoch` (ou le ramener a 50), reduire la patience a 50 max, ajouter `ReduceLROnPlateau(factor=0.5, patience=20)`.

#### P0-4 — Fuite potentielle de la cible (`y`) — normalisation y sur train OK, mais pas auditable sur fichier upload
- **Fichier** : `apps/api/app/routers/training.py:364-372`
- **Constat** : `y_train_norm, mu_y, sigma_y = _normalize(y_train, y_on_off)` calcule mu_y/sigma_y sur `y_train` seulement — **bon, pas de fuite ici**. Idem pour x : ligne 470, `mu_x, sigma_x = _normalize(x_tr, on_off_subset)` sur le train uniquement. C'est correct.
- **Mais** : `test_size=0.0` est la valeur par defaut (`training.py:78`). Dans ce cas (training.py:360-362), `idx_valid = None` et **tout le dataset est utilise comme train**. Le `model.evaluate` final (training.py:597) tourne alors sur les memes donnees (`x_all_norm`, ligne 480) — c'est une evaluation in-sample, pas une vraie validation. La metrique `val_loss` reportee dans `results_list` ne refletera donc pas la generalisation.
- **Impact** : le `best_val_loss` rapporte au front (training.py:600-602) est en realite un train_loss. Le choix du "meilleur modele" est biaise vers les modeles qui surapprennent.
- **Recommandation** : forcer `test_size > 0` (au minimum 0.15) ou exposer un warning critique cote UI quand `test_size=0`. Cross-validation k-fold serait l'ideal pour des datasets petits.

#### P0-5 — Fonction `_my_norm` de `carte.py` casse les types pandas
- **Fichier** : `apps/api/app/routers/carte.py:85-98`
- **Constat** :
  ```python
  Xnorm = pd.DataFrame(index=X.index, columns=X.columns)  # dtype=object par defaut
  for idx in on_idx:
      Xnorm.iloc[:, idx] = (X.iloc[:, idx].values - mu_arr[idx]) / S_arr[idx]
  Xnorm.loc[:, ~on_off] = X.loc[:, ~on_off].values
  return Xnorm
  ```
  Le DataFrame `Xnorm` est cree sans dtype, donc en `object`. Ensuite converti via `np.array(xNorm_tv).astype(np.float32)` (ligne 493) — fonctionne, mais inefficace et fragile : si une colonne contient `NaN` ou un type non-castable, l'erreur ne sera revelee qu'a la prediction. Pire, la boucle `for idx in on_idx` est en pur Python pour potentiellement des milliers de lignes — alors que la version `services/ml/normalize.py:simple_norm` fait tout en numpy vectorise.
- **Recommandation** : remplacer par `services/ml/normalize.py:simple_norm(X.values, mu, sigma)` directement.

### P1 — Bloquants ingenierie

#### P1-1 — Code en double : router live vs service ML
- **Constat** : `routers/training.py` (870 lignes) re-implemente `_normalize`, `_build_feature_sets`, `_build_combinations`, `_training_worker` alors que `services/ml/*.py` propose deja les memes fonctions, mieux testees. Les deux divergent : le service supporte `sample_weight`, metriques etendues (mae+mape+r2), `analysis_scope`, year_mapping. Le router accumule un buffer `task.progress` sans cap (`training.py:415`), risque OOM sur long grid search.
- **Le route `/api/training/start` instancie `TrainingTask` puis lance un thread qui re-implemente tout** — au lieu d'appeler `run_training()` du service.
- **Impact** : maintenance double, divergence de comportement, tests du service ne couvrent pas le code reellement execute.
- **Recommandation** : refactor `_training_worker` pour invoquer `services.ml.training_pipeline.run_training()` avec un `progress_callback` qui pousse dans `task.progress`. Couper 500 lignes de code dupliques.

#### P1-2 — Validation des inputs DataFrame faible
- **Fichier** : `apps/api/app/routers/training.py:316-336` ; `apps/api/app/services/ml/data_prep.py:122-133`
- **Constat** :
  - Pas de check de **type** (un `TMJAFCDTV` arrivant en string "1 500,3" sera silencieusement converti en NaN par `pd.to_numeric(..., errors="coerce")` puis drop)
  - Pas de detection d'**outliers** (valeurs negatives, vitesse > 200 km/h, distance > 1000 km, TxPen > 100% qui est un non-sens metier)
  - `dropna` **brutal** (training.py:334) — un seul NaN dans une colonne fait disparaitre la ligne entiere, sans logging du volume perdu
  - Pas de check de **dimension** (5 lignes minimum, training.py:335-336, mais 5 lignes pour entrainer un reseau de neurones est deja une aberration — devrait etre >= 50)
  - Pas de check de **distribution** : si TxPen est constant a 100%, le modele est inutile
- **Recommandation** : ajouter un module `data_quality.py` avec un rapport synthetique (taux NaN, outliers, plages min/max, distribution de la target) loggue avant chaque entrainement, et des warnings cote UI.

#### P1-3 — Versioning des modeles fragile : pas de hash, pas de meta-env
- **Fichier** : `apps/api/app/routers/training.py:641-665`
- **Constat** : `training_config.json` stocke les HPs mais pas :
  - `tensorflow.__version__`, `keras.__version__`, `numpy.__version__`, `sklearn.__version__`, `python_version`
  - Le **hash du dataset d'entree** (MD5/SHA-256 de `learning_df.to_csv()`)
  - Le **hash du code de training** (git commit SHA)
  - Le `max_epochs` n'est pas dans le `run_name` — deux runs avec le meme nom mais `max_epochs=1000` puis `max_epochs=2050` ecraseront l'un l'autre via le skip (`training.py:386-388`)
  - `use_batch_norm` non encode dans `run_name` (training.py:226-230)
- **Risque de collision** : deux configurations distinctes peuvent produire le meme `run_name` et l'une effacera silencieusement l'autre.
- **Reproductibilite a 6 mois** : impossible. Si on retrouve un modele `elu_lr0.01_ep500_mse_drp0.05_nf1.0x1.0_bs256_fmask_111010` en 2027, on ne saura pas avec quelle version de TF il a ete entraine, quel commit, quel dataset.
- **Recommandation** : ajouter un `meta.json` par modele avec `{git_sha, tf_version, keras_version, np_version, sklearn_version, python_version, data_sha256, training_started_at, training_ended_at, hostname}`.

#### P1-4 — Format `.weights.h5` legacy + architecture rejouee
- **Fichier** : `apps/api/app/routers/training.py:629` ; `apps/api/app/services/ml/packaging.py:47`
- **Constat** : on sauve `NNweights.weights.h5` (poids HDF5) + `NNarchitecture.json` (architecture JSON). C'est l'approche legacy de Keras 2. Probleme :
  - HDF5 est en cours d'abandon dans Keras 3
  - Le rejeu via `model_from_json` est fragile (custom layers, fonctions de loss custom — qui n'existent pas ici mais limiterait toute evolution)
  - Le format moderne `.keras` (Keras 3) regroupe tout en un seul fichier zip, plus portable
- **Recommandation** : passer a `model.save(path / "model.keras")` ; garder le format actuel en fallback pour les modeles existants. Documenter une migration.

#### P1-5 — Grid search peut exploser, aucune protection
- **Fichier** : `apps/api/app/routers/training.py:191-243`
- **Constat** : 6 features avec subset grid -> 2^6 - 1 = 63 subsets ; combine avec 3 activations × 3 LRs × 3 losses × 3 dropouts × 2 nf × 2 bs × 2 min_epochs = **65k+ modeles possibles**. Aucun garde-fou cote API (pas de `MAX_COMBINATIONS`), aucune estimation de duree affichee avant `/start`. Un utilisateur peut bloquer le worker pendant des jours.
- **Pas de pruning** (median stopping, Successive Halving), pas de **Bayesian optimization** (Optuna), pas de **HyperBand**. Pour un projet 2026 c'est un retard de 6 ans.
- **Recommandation** : (a) bloquer si `total_combinations > 200` avec warning + override explicite ; (b) ajouter `optuna` ou `keras-tuner` en alternative au grid search exhaustif ; (c) afficher une duree estimee dans `TrainingStartResponse`.

#### P1-6 — Pas de tracking d'experimentations
- **Constat** : aucun MLflow, W&B, ClearML, Neptune, ou meme TensorBoard. Le seul stockage est `training_metrics.json` par modele dans un dossier. Comparer deux sessions necessite de parcourir manuellement le filesystem.
- Le frontend a un tableau dans `evaluation.py` qui compare les modeles **d'une seule session**. Pas de vue cross-session.
- **Recommandation** : integrer MLflow en local (`mlflow.set_tracking_uri("sqlite:///mlruns.db")`), logguer `params`, `metrics`, `artifacts` (le dossier modele). Mini-effort, gros gain. Alternative : `mlflow.fastapi` ou simplement un endpoint `/api/training/history` qui agrege les `training_metrics.json` de toutes les sessions.

#### P1-7 — Metriques d'entrainement appauvries
- **Fichier** : `apps/api/app/routers/training.py:535-539` vs `apps/api/app/services/ml/model_builder.py:92-96`
- **Constat** : le router compile avec `metrics=["mae"]` (juste MAE). Le service propose `["mae", "mape", "r2"]`. La compile-string `"mae"` cree une MeanAbsoluteError compilee differemment de `keras.metrics.MeanAbsoluteError(name="mae")` (le nom logue dans `history.history` differe, ce qui peut perturber le parsing en aval).
- **Impact** : on perd la possibilite de tracer MAPE/R2 epoch par epoch — alors que ce sont les metriques metier reportees a la fin. Pas de courbe d'apprentissage MAPE/R2 dans les artefacts.

#### P1-8 — Memoire TF : `clear_session` insuffisant pour gros grid
- **Fichier** : `apps/api/app/routers/training.py:449-455`
- **Constat** : `tf.keras.backend.clear_session()` n'est appele qu'**entre groupes de feature_mask**, pas entre modeles d'un meme groupe. Pour un groupe de 36 modeles (HPs sans subset), aucune liberation. Sur grosse base, fuite memoire confirmee (les modeles Keras stockent leur graphe dans le default graph qui s'accumule).
- **De plus** : `routers/carte.py:494, 582` appelle `model.predict` sans aucun `clear_session` apres. Si l'utilisateur regenere la carte plusieurs fois dans la meme session (deux uploads de modeles successifs), la RAM grimpe.
- **Recommandation** : `clear_session()` apres chaque `model.fit`, et `del model; gc.collect(); tf.keras.backend.clear_session()` dans `carte.py` apres chaque prediction.

### P2 — Cosmetique / dette progressive

#### P2-1 — Metrique GEH : formule correcte, mais seuil hardcode
- **Fichier** : `apps/api/app/routers/evaluation.py:84-88` ; `apps/api/app/services/ml/evaluation_pipeline.py:150-156`
- **Constat** : formule `sqrt((O-P)^2 / ((O+P)/2))` = `sqrt(2*(O-P)^2/(O+P))` — **correcte** (l'evaluation_pipeline applique correctement la division par 24 pour avoir un debit horaire, qui est la convention GEH standard). Le router `routers/evaluation.py:84-88` **n'applique PAS la division par 24** — incoherent avec `evaluation_pipeline.py:150-153` qui le fait. Resultat : le `geh_mean` dans `_compute_metrics` est mathematiquement faux pour la convention trafic.
- Le seuil GEH<5 est standard (DfT UK, FHWA US), OK.
- **Recommandation** : harmoniser — soit toujours diviser par 24, soit jamais. Sinon les chiffres reportes a l'utilisateur sont incoherents entre la "carte API" et le rapport HTML.

#### P2-2 — Intervalles de confiance "Erreur_dyn" — regles metier en dur sans source
- **Fichier** : `apps/api/app/routers/carte.py:37-41, 145-188` ; `apps/api/app/services/ml/evaluation_pipeline.py:184-193`
- **Constat** : les bornes (0.14, 0.18, 0.25) sont **hardcodees**, pas calibrees sur les donnees, pas sourcees dans le code. Les fonctions `_calculer_DPLmin/max` definissent des paliers en escalier (`< 500`, `< 1000`, etc.) qui creent des **discontinuites** : un capteur a 999 vehicules/jour aura un intervalle different d'un capteur a 1001, alors que physiquement c'est la meme situation.
- **Impact** : intervalles de confiance non-statistiques, plutot des "tolerances expertes". Le metier les a peut-etre valides historiquement, mais aucune trace ne le prouve dans le code.
- **Recommandation** : extraire ces seuils dans un YAML `confidence_thresholds.yml` versionne avec un commentaire de provenance ; mieux : calibrer empiriquement (quantile 10/90 de l'erreur observee par decile de debit).

#### P2-3 — Sensibilite "a la main" vs methodes standards
- **Fichier** : `apps/api/app/routers/evaluation.py:440-682`
- **Constat** : `_build_sensitivity_section_html` varie une feature en fixant les autres a Q1/Med/Q3 — c'est l'**ICE plot** classique, OK pedagogiquement. Mais aucune mention de **SHAP**, **permutation importance**, **partial dependence avec interactions**, ni de tests de robustesse (donnees adversariales).
- 60 points par feature, 3 baselines, N features -> chaque appel `model.predict` est petit mais multiplie : pour 6 features = 18 appels. Acceptable.
- **Recommandation** : ajouter une section "Permutation importance" (5 lignes avec `sklearn.inspection.permutation_importance`) — plus rigoureuse que les ICE plots seuls.

#### P2-4 — `_normalize` re-defini dans `routers/training.py:250-265`
- Dupliquait `services/ml/normalize.py:normalize()`. Code duplique non teste — le test `test_normalize.py` ne couvre que le service. Si le router diverge (cas de sigma=0 par exemple), bug silencieux.

#### P2-5 — `analysis_scope` du service inutilise dans le router
- Le service supporte `analysis_scope: "all" | "valid"` (evaluation sur tout / sur validation seule) — `training_pipeline.py:150-156`. Le router live ignore ce parametre et fait toujours "all" si pas de split, "valid" sinon. Perte de flexibilite.

#### P2-6 — `mu_x/sigma_x` stockes en `[[...]]` (liste de listes) — convention douteuse
- **Fichier** : `apps/api/app/routers/training.py:631-637`
  ```python
  norm_json = json.dumps({
      "muX": [mu_x.tolist()],   # double wrap
      "SX": [sigma_x.tolist()],
  ...
  ```
  Heritage Streamlit. Le reader `evaluation.py:1207-1210` fait `norm_raw["muX"][0]` pour deballer. Risque de bug si quelqu'un reorganise le format un jour.

#### P2-7 — `carte.py` charge le modele en bloc, pas de cache
- **Fichier** : `apps/api/app/routers/carte.py:191-226`
- A chaque `/api/carte/generate`, on relit les fichiers, on parse le JSON, on recree le modele, on charge les poids. Pour un utilisateur qui ajuste `error_thresholds` et regenere, c'est 5-10 secondes perdues.
- **Recommandation** : cache LRU `@lru_cache(maxsize=4)` par chemin de modele.

#### P2-8 — Test coverage modeste
- 5 tests fichiers (data_prep, grid_search, normalize, packaging, types). `test_packaging.py` skip tout (pas de TF en CI). Pas de test sur `_training_worker`, ni sur `apply_model`, ni sur le calcul GEH, ni sur `_compute_metrics`, ni sur `_load_model_from_dir`. Couverture estimee : <30% du chemin ML.

#### P2-9 — Inputs/outputs metier : la cible est bien `TxPenTVRef = TMJAFCDTV / TMJABCTV * 100`
- Confirme par `data_prep.py:31-47` et `types.py:79-81`. Le modele predit le **taux de penetration** (ratio FCD/comptage), pas le debit directement. Le debit `TVr = TMJAFCDTV / TP_pred * 100` est calcule en post-traitement. **C'est elegant** : la cible est bornee [0,100], gaussienne-ish, facile a apprendre. Bon choix mathematique.
- Risque : si TP_pred -> 0, TVr -> infini. Code dans `carte.py:498` fait `np.abs(yestT_tv[:, 0])` ce qui est un patch fragile.

---

## Plan d'amelioration ML

### Sprint 1 — Debloquer la rigueur scientifique (1-2 semaines)
1. **Reproductibilite** : implementer un util `seed_everything(seed)` qui fixe `PYTHONHASHSEED`, `random`, `numpy`, `tf`, `keras.utils.set_random_seed`, et appelle `tf.config.experimental.enable_op_determinism()`. L'invoquer **avant `train_test_split` ET avant chaque `model.fit`**. **Bloquant** pour toute pretention de pipeline serieux.
2. **Refactor router -> service** : faire pointer `_training_worker` (training.py:268-710) vers `services/ml/training_pipeline.run_training()`. Recuperer au passage `sample_weight`, metriques etendues, `analysis_scope`. Supprimer 400 lignes dupliquees.
3. **Forcer un split de validation reel** : default `test_size=0.2`, warning si l'utilisateur force `0.0`.
4. **Corriger EarlyStopping** : `patience=50`, supprimer `start_from_epoch`, ajouter `ReduceLROnPlateau(factor=0.5, patience=20, min_lr=1e-5)`.
5. **Harmoniser GEH** : decider une fois (avec division /24) et appliquer partout. Tester unitairement.

### Sprint 2 — Outillage MLOps (2-3 semaines)
6. **Versioning modeles** : ajouter `meta.json` (versions packages, git SHA, data hash, timestamps).
7. **MLflow embedded** : tracker chaque run, exposer `/api/training/history`.
8. **Format modele moderne** : `.keras` natif en plus du legacy.
9. **Validation data quality** : module `data_quality.py` + rapport pre-training.
10. **Cache modele** dans `carte.py` (LRU).

### Sprint 3 — Optimisation (1 mois)
11. **Remplacer grid search exhaustif** par Optuna (TPE) ou KerasTuner (HyperBand). Garder le grid en mode "expert".
12. **Permutation importance** dans le rapport d'eval (5 lignes de code).
13. **Calibration empirique des intervalles** "Erreur_dyn" (quantiles observes).
14. **Tests d'integration** end-to-end : upload -> training -> evaluation -> carte, avec assertion sur RMSE attendu.

### Cosmetique (continu)
- Eliminer le `[[...]]` wrap des norms.
- Logguer le volume perdu par `dropna`.
- Documenter la provenance des seuils metier.

---

## Best practices MLOps manquantes — checklist

| Domaine | Pratique | Etat actuel | Priorite |
|---|---|---|---|
| **Reproductibilite** | `seed_everything()` complete (5 generateurs) | Partiel (2/5) | **P0** |
| | `enable_op_determinism()` | **Absent** | **P0** |
| | `PYTHONHASHSEED` fixe au demarrage | **Absent** | **P0** |
| | Seeds re-applies avant chaque `fit` | Non | P1 |
| **Data leakage** | Normalisation fittee sur train uniquement | OK | - |
| | `train_test_split` seede | OK | - |
| | Validation set par defaut | Non (test_size=0) | **P0** |
| **Data quality** | Schema check des inputs (Pandera, Great Expectations) | **Absent** | P1 |
| | Outlier detection automatique | **Absent** | P1 |
| | Distribution check de la target | **Absent** | P2 |
| | Volume perdu par dropna loggue | Non | P2 |
| **Versioning** | Hash dataset, code, env | **Absent** | P1 |
| | Format moderne `.keras` | Non (.h5 legacy) | P1 |
| | Meta.json (versions packages) | **Absent** | P1 |
| **Experiment tracking** | MLflow / W&B / Neptune | **Absent** | P1 |
| | TensorBoard logs | **Absent** | P2 |
| | Cross-session comparison UI | Non | P2 |
| **Model registry** | Promotion staging/production | **Absent** | P2 |
| | Tags semantiques (best_per_region) | **Absent** | P2 |
| | Lineage (model -> dataset -> code) | **Absent** | P1 |
| **Monitoring drift** | Distribution shift detection (Evidently, NannyML) | **Absent** | P2 |
| | Performance monitoring en prod | **Absent** | P2 |
| | Alerting sur GEH degrade | **Absent** | P2 |
| **CI/CD ML** | Tests d'integration training+eval | Partiel | P1 |
| | Pipeline CI qui re-train sur PR | **Absent** | P2 |
| | Smoke test predictions | **Absent** | P1 |
| **Cost / efficience** | HP search intelligent (Bayesian, HyperBand) | **Absent** | P1 |
| | Pruning de mauvais runs | **Absent** | P1 |
| | Budget combinations / temps | **Absent** | P1 |
| **Interpretabilite** | SHAP / permutation importance | Partiel (ICE plots) | P2 |
| | Feature importance global | **Absent** | P2 |
| **Robustesse** | Stress tests (NaN, inf, types) | **Absent** | P1 |
| | Adversarial inputs | **Absent** | P2 |
| **Documentation** | Model card par run | **Absent** | P2 |
| | Datasheet for dataset | **Absent** | P2 |
| **Securite** | Validation taille upload | OK (carte.py) | - |
| | Pickling absent (json only) | OK | - |

---

## Conclusion

Le pipeline est **fonctionnel et fidele a l'historique Streamlit** — c'est sa valeur immediate. Mais il est aussi le miroir des angles morts d'un script de chercheur transforme en API : la reproductibilite est cosmetique, le grid search est brut, le tracking inexistant, et le code de production diverge silencieusement d'une version "propre" testee qui n'est jamais executee.

Les 3 actions a impact immediat, par ordre de ROI :

1. **Brancher le router sur `services/ml/training_pipeline.py`** (gain : sample weighting, metriques, lisibilite, divise les LOC par 2).
2. **`seed_everything()` complet + `enable_op_determinism()`** (gain : tout devient debuggable et auditable).
3. **MLflow embedded + `meta.json`** (gain : on peut enfin comparer scientifiquement les runs entre sessions et a 6 mois d'intervalle).

Sans ces 3 corrections, l'outil reste une preuve de concept robuste mais non un produit ML reglementairement defendable. Avec elles, on monte d'un cran (note projetee : 7/10) et on entre dans le territoire des outils ML internes serieux.
