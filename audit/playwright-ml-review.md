# Audit ML — pipeline d'entraînement (post-test Playwright Bordeaux)

> Contexte : test end-to-end Playwright sur `DataApprentissage_Bordeaux.geojson` (1961 features, 39 colonnes), 1 combinaison, ELU, lr=0.01, MSE, dropout=0.05, neurons_factors=[1.0,1.0], batch=32, min/max epochs=50/80, test_size=0.2, weighting `flag_comptage` actif (poids 4). Entraînement terminé en 67 epochs (EarlyStopping), seed=1750, sha256 dataset `a778683755…d387df`.

---

## 1. Verdict global

Le pipeline est **structurellement sain et reproductible** : seed unique, déterminisme TF activé par défaut, sauvegardes `.keras` natif + legacy h5 + `meta.json` (TF/Keras/git SHA), `restore_best_weights=True`, weighting capteurs permanents correctement propagé à `model.fit(sample_weight=…)`. Deux **réserves méthodologiques majeures** : (1) `analysis_scope="all"` ré-évalue sur l'union train+valid → R²/GEH **gonflés par leak**, (2) architecture sous-dimensionnée (6→6→6→1, ~85 params) pour 1568 samples × 6 features. Le test Playwright valide la convergence, **pas la généralisation**.

---

## 2. Convergence — lecture des métriques

| Métrique | Valeur | Lecture |
|---|---|---|
| RMSE | 0.1661 | Cohérent avec l'échelle de TxPenTVRef (~0–1). Faible biais résiduel. |
| MAE | 0.1197 | ~12 pp d'erreur absolue moyenne sur le taux de pénétration — acceptable mais bruité. |
| MAPE | 16.54 % | Élevé en valeur relative — la divergence MAE/MAPE indique que l'erreur est plus pénalisante sur les **petites valeurs** de TxPen. |
| R² | 0.871 | **Mesuré sur train+valid réunis (`analysis_scope="all"`)** ⇒ surestimé. R² val-only probablement 0.75–0.82. |
| GEH mean | 0.0272 | Très faible mais GEH n'a de sens que sur volumes (TxPen est un ratio). À recadrer ou retirer du rapport. |
| GEH < 5 = 100% | 1961/1961 | **Trivialement vrai** : TxPen ∈ [0,1], GEH = `sqrt(2(M-C)²/(M+C))` est mécaniquement <5 pour des valeurs aussi petites. **Métrique non informative ici.** |
| n_samples eval | 1961 | = train(1568) + valid(393) ⇒ leak. |

> **Conclusion convergence** : le modèle a convergé (EarlyStopping à 67/80, restore best, plateau de val_loss respecté). Les chiffres absolus de ce run **ne doivent pas être utilisés comme indicateurs de performance produit**.

---

## 3. Audit point par point

### Q1 — GEH 100% < 5 sur l'eval = train ⇒ overfit ou cohérence ?

- **Statut** : ⚠️ méthodologiquement incorrect (mais admissible pour un test de convergence).
- **Référence** : `apps/api/app/services/ml/training_pipeline.py:169-174` — `analysis_scope == "all"` ⇒ `eval_x, eval_y = x_all_norm, y_all_norm`.
- **Diagnostic** : ni overfit ni "cohérence", c'est un **artefact d'échelle** : TxPen ∈ [0,1] rend GEH dégénéré. Couplé au leak train→eval, cette métrique n'apporte aucune information sur la généralisation.
- **Reco** : (a) désactiver GEH pour les modèles de ratio (TxPen) — la métrique GEH est conçue pour les **volumes horaires de trafic**, pas pour des taux ; (b) forcer `analysis_scope="valid"` lorsque `test_size > 0` ; (c) afficher dans l'UI : "GEH non applicable (cible = ratio)".

### Q2 — Leak train→eval (1568+393=1961)

- **Statut** : ⚠️ à améliorer (architecturalement attendu, pas un bug).
- **Référence** : `training_pipeline.py:337` (`analysis_scope = config.get("analysis_scope", "all")`) + `:169-174`.
- **Diagnostic** : par défaut `analysis_scope="all"` ⇒ l'éval inclut le train. Pour ce test c'est documenté ; pour un usage prod, c'est trompeur.
- **Reco** : changer la **valeur par défaut** à `"valid"` quand `test_size > 0`, et logger explicitement `eval_scope=train+valid (leak)` quand `analysis_scope="all"`. Voir snippet T2.

### Q3 — Reproductibilité et déterminisme TF

- **Statut** : ✅ OK (avec une nuance).
- **Référence** : `apps/api/app/services/ml/seeding.py:24-75` + `training_pipeline.py:263, 404`.
- **Diagnostic** :
  - `seed_everything(1750)` appelé deux fois : une fois en début de `run_training` avec `enable_op_determinism=True` (défaut), puis **avant chaque fit** avec `enable_op_determinism=False` — c'est volontaire pour éviter la double-init (`tf.config.experimental.enable_op_determinism` ne peut pas être re-toggle après init TF).
  - `TF_DISABLE_SEGMENT_REDUCTION_OP_DETERMINISM_EXCEPTIONS` mentionné dans `audit/04-ml-pipeline.md` est **absent** du code actuel — confirmé via grep. Si l'audit A4 le recommandait, il n'a jamais été ajouté.
  - `PYTHONHASHSEED` posé au runtime → sans effet sur le process courant (déjà démarré), seulement utile pour subprocesses.
- **Reco** : ajouter `os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")` dans `training_pipeline.py` (top-level, avant `import tensorflow`) pour les ops cuDNN non couvertes par `enable_op_determinism`. Documenter `PYTHONHASHSEED` (set côté process manager / Dockerfile, pas runtime).

### Q4 — Sample weights `flag_comptage`

- **Statut** : ✅ OK — câblage correct.
- **Référence** : `data_prep.py:171-181` (calcul `all_sw = np.where(flag==1, 4.0, 1.0)`) → `training_pipeline.py:422-423` (`train_sample_weight=split["train_sample_weight"]`) → `:156-164` (`fit_kwargs["sample_weight"] = train_sample_weight` et idem dans `validation_data`).
- **Diagnostic** : les capteurs permanents (flag=1) sont effectivement pondérés ×4 dans la loss train **et** la val_loss (cohérent — l'EarlyStopping suit donc la perte pondérée). Aucune fuite, aucun double-comptage.
- **Reco** : documenter dans `meta.json` la **distribution effective** des poids (`n_flag1`, `n_flag0`, ratio effectif). Permet d'auditer post-hoc qu'un dataset déséquilibré n'a pas fait dériver l'optimisation.

### Q5 — Format de sauvegarde + restore_best_weights

- **Statut** : ✅ OK — formats correctement persistés, mais doublon à rationaliser.
- **Référence** : `routers/training.py:223-233` (save `.keras` + `to_json` + `save_weights .h5`), `training_pipeline.py:119` (`restore_best_weights=True`).
- **Diagnostic** :
  - `epochs_trained=67 < 80` ⇒ EarlyStopping a tiré, et `restore_best_weights=True` garantit qu'on sauve les **poids du meilleur epoch val_loss** (non le dernier). ✅
  - Le pipeline persiste **trois copies** des poids : `model.keras` (natif), `NNarchitecture.json` + `NNweights.weights.h5` (legacy). C'est volontaire (audit A4 recommandait migration `.keras` ; les deux coexistent pour rétro-compat). À planifier la suppression du legacy une fois les anciens modèles re-saved.
- **Reco** : ajouter un flag config `save_legacy_h5: bool = True` (par défaut True pendant la transition, False ensuite) ; viser à terme un seul artefact `.keras`.

### Q6 — Architecture neurons_factors=[1,1] sur 1568 × 6 features

- **Statut** : ⚠️ à améliorer — sous-dimensionné mais explique le comportement observé.
- **Référence** : `model_builder.py:66-79` — boucle `for i, factor in enumerate(neurons_factors): n_units = max(2, int(round(input_size * factor)))`.
- **Diagnostic** : avec `input_size=6` et `factors=[1.0, 1.0]`, on obtient deux couches Dense(6,elu) + Dense(1,linear). Comptage paramètres :
  - Dense(6) après Dropout(in=6) : 6×6 + 6 = 42
  - Dense(6) : 6×6 + 6 = 42
  - Dense(1) : 6×1 + 1 = 7
  - **Total ≈ 91 paramètres** pour 1568 samples → ratio 17 samples/param ⇒ confortable, mais **capacité expressive faible**. R²=0.87 sur train+valid suggère qu'on capte les patterns linéaires/faiblement non-linéaires uniquement.
- **Reco** : grid par défaut à `[[2.0, 1.0], [4.0, 2.0, 1.0], [1.0, 1.0]]` pour comparer. Sur 1568 lignes, des architectures jusqu'à ~500 params restent saines (ratio >3 samples/param).

### Q7 — start_from_epoch / min_epochs

- **Statut** : ✅ OK — bornée à 50 comme recommandé.
- **Référence** : `training_pipeline.py:113-114` :
  ```py
  patience = 50
  start_from = min(50, max(1, combo.min_nb_epochs // 4))
  ```
- **Diagnostic** : `min_nb_epochs=50` (config test) ⇒ `start_from = min(50, 12) = 12` ✅ (cohérent avec la métadonnée `start_from_epoch: 12`). L'audit A4 craignait des valeurs `start_from_epoch=500-1000` venant directement de `min_nb_epochs_list` — c'est **corrigé** via le cap `min(50, …)`. Aucune action.
- **Reco** : aucune. Documenter la formule dans le frontend (tooltip de `min_nb_epochs`).

### Q8 — Métadonnées (`meta.json`)

- **Statut** : ✅ OK — couverture quasi complète.
- **Référence** : `packaging.py:28-68` (`build_meta`), `routers/training.py:251-262` (écriture `meta.json`).
- **Diagnostic** : `meta.json` capture `saved_at`, `python_version`, `platform`, `hostname`, `seed`, `data_sha256`, `tf_version`, `keras_version`, `numpy_version`, `sklearn_version`, `git_sha`. **Excellent**. Manques mineurs : pas de `pandas_version`, pas de hash du `training_config.json` (utile pour traçabilité diff), pas de `cuda_version` (mais GPU désactivé → ok).
- **Reco** : ajouter `pandas_version`, `n_train_rows`, `n_valid_rows`, `flag_distribution` ; logger `meta` dans l'audit-trail (DB) en plus du disque.

---

## 4. Plan d'amélioration (par impact métier décroissant)

| # | Action | Impact | Effort |
|---|---|---|---|
| 1 | Forcer `analysis_scope="valid"` par défaut quand `test_size>0`, exposer l'option dans l'UI avec warning explicite | Crédibilité des métriques produit | **2 h** |
| 2 | Retirer GEH du dashboard pour les cibles ratio (TxPen) ou afficher "N/A" | Évite fausse impression de qualité | 1 h |
| 3 | Étendre grid neurons_factors par défaut + tester sur Bordeaux pour valider gain R² val-only | Performance modèle | **4 h** (test + bench) |
| 4 | Ajouter `flag_distribution` + `pandas_version` à `meta.json`, persister meta en DB | Traçabilité MLOps | 2 h |
| 5 | Ajouter `os.environ.setdefault("TF_DETERMINISTIC_OPS","1")` en top-level de `training_pipeline.py` | Reproductibilité bit-exacte | 0.5 h |
| 6 | Calculer R²/MAE/MAPE séparément sur train, valid, et "all" — exposer les 3 colonnes dans l'UI | Détection overfit immédiate | **3 h** |
| 7 | Planifier suppression du dual-save (h5 legacy + .keras) après migration audit | Réduction surface code | 2 h |
| 8 | Logger `eval_scope=train+valid (overestimated)` dans `training_metrics.json` quand `analysis_scope="all"` | Audit-trail honnête | 0.5 h |
| 9 | Ajouter validation par K-fold optionnelle (k=5) sur petits datasets (<3000 samples) | Robustesse statistique | **6 h** |
| 10 | Bench batch_size ∈ {16,32,64} pour datasets <2000 lignes — 32 est probablement OK mais à vérifier | Vitesse + stabilité | 3 h |

**Total effort prioritaire (#1, #2, #3, #5, #6, #8) : ~11 h**.

---

## 5. Snippets prêts à appliquer (top 3)

### T1 — Reproductibilité renforcée (`training_pipeline.py`, top du fichier)

```python
# Avant tout import TF
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_DETERMINISTIC_OPS", "1")          # NEW
os.environ.setdefault("TF_CUDNN_DETERMINISTIC", "1")        # NEW (no-op CPU mais utile si GPU futur)
```

### T2 — `analysis_scope` honnête (`training_pipeline.py:337`, `_train_single:169-180`)

```python
# Dans run_training()
analysis_scope = config.get("analysis_scope")
if analysis_scope is None:
    analysis_scope = "valid" if test_size > 0 else "all"  # NEW default

# Dans _train_single(), après evaluate :
if analysis_scope == "all" and test_size > 0:
    metrics["_warning"] = "eval includes training samples (analysis_scope=all)"
config_dict["analysis_scope_effective"] = analysis_scope
config_dict["eval_includes_train"] = bool(
    analysis_scope == "all" and test_size > 0
)
```

### T3 — `meta.json` enrichi (`packaging.py:28`)

```python
def build_meta(*, seed=None, data_sha256=None, extra=None,
               training_config=None):                # NEW arg
    meta = {
        "saved_at": datetime.utcnow().isoformat() + "Z",
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "hostname": socket.gethostname(),
        "seed": seed,
        "data_sha256": data_sha256,
    }
    for mod_name, key in (("tensorflow","tf_version"),("keras","keras_version"),
                           ("pandas","pandas_version"),("sklearn","sklearn_version")):
        try:
            mod = __import__(mod_name)
            meta[key] = mod.__version__
        except Exception as exc:  # noqa: BLE001
            meta[f"{key}_error"] = str(exc)
    meta["numpy_version"] = np.__version__
    try:
        sha = subprocess.check_output(
            ["git","rev-parse","HEAD"],
            cwd=Path(__file__).resolve().parent,
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
        meta["git_sha"] = sha
    except Exception:
        meta["git_sha"] = None
    if training_config:
        meta["train_rows"] = training_config.get("train_rows")
        meta["valid_rows"] = training_config.get("valid_rows")
        meta["flag_priority_weight"] = training_config.get("flag_priority_weight")
        meta["use_flag_comptage_weighting"] = training_config.get(
            "use_flag_comptage_weighting"
        )
    if extra:
        meta.update(extra)
    return meta
```

---

## 6. Synthèse exécutive

| Axe | État | Priorité |
|---|---|---|
| Reproductibilité (seed, TF det.) | ✅ Solide | low — tweak T1 |
| Sauvegarde modèle (`.keras` + meta) | ✅ Solide | low |
| Sample-weight `flag_comptage` | ✅ Correct | low |
| EarlyStopping + restore best | ✅ Correct | low |
| Architecture par défaut (6,6) | ⚠️ Sous-dimensionnée | **medium** — étendre grid |
| Métriques rapportées (R², GEH) | ⚠️ Trompeuses sur ce run | **HIGH** — T2 + retrait GEH |
| Doc / UI clarté train vs valid | ⚠️ À expliciter | **HIGH** |
| `meta.json` couverture | ✅ Bonne, enrichissable | low |

**Action prioritaire #1** : appliquer T2 avant le prochain rapport présenté à un client. Les chiffres actuels (R²=0.871, GEH 100%) sont mathématiquement corrects mais **commercialement dangereux** s'ils sont communiqués sans la mention "eval inclut le train".
