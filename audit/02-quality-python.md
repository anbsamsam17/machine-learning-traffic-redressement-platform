# Audit qualité Python — backend MDL

## Résumé exécutif

Note globale : **5,5 / 10**. Code fonctionnel, bien structuré au niveau routers/services et avec un effort réel sur les annotations de types modernes (`X | None`, génériques natifs) — mais miné par trois dettes structurantes qui dégradent la maintenabilité immédiate.

**Trois problèmes structurants :**
1. **Pipeline d'entraînement dupliqué.** `app/routers/training.py:268-710` ré-implémente en 450 lignes inline ce que `app/services/ml/training_pipeline.py` propose déjà proprement (factorisé, testable, type-safe). Le router monolithique est appelé en prod, le service propre est *non câblé* — il est seulement importé par `app/tasks.py:43` qui est lui-même mort (Celery jamais déployé).
2. **Travail IO/CPU bloquant dans des routes `async`.** Toutes les routes lourdes (`evaluation.run`, `carte.generate`, `upload.upload_data`) appellent `model.predict`, `pd.read_csv`, `pickle.dumps` synchrones dans la boucle d'event — aucun `run_in_executor`. Au-delà de 2-3 requêtes concurrentes l'event loop est gelé, faisant écrouler `/health` et le SSE de progression.
3. **Exception handling laxiste.** 13 `except Exception: pass` muets, plus 31 `except Exception` larges. Bugs silencieux garantis (cf. `evaluation.py:1067` qui catche `(KeyError, Exception)` dans un `for` — masque tout).

Posture : **refactoring concerté nécessaire avant nouvelles features**. Le code marche, mais chaque modif touche plusieurs implémentations parallèles. Le delta de qualité entre `services/ml/*` (propre, testé, typé) et `routers/*` (gros, non testés, exceptions avalées) est saisissant — un signe que l'équipe sait écrire propre mais a court-circuité sous pression.

---

## Métriques

| Indicateur | Valeur |
|---|---|
| LOC backend (app + tests) | **8 817** lignes (app : 6 196 ; tests : 1 448 ; conftest : 94) |
| Fichiers Python | 25 (app) + 11 (tests) |
| Fichiers > 500 lignes | **3** : `routers/evaluation.py` (1 481), `routers/training.py` (869), `routers/carte.py` (795) |
| Fonctions définies (signatures `def`) | ~186 |
| Fonctions/méthodes avec annotation de retour `-> X` | ~65 → **~35 % typage retour explicite** |
| Fonctions sans aucune annotation (`def f(...):`) | ~15 fonctions internes (closures, helpers) — toutes localisées dans `evaluation.py`, `carte.py`, `mapping.py`, `training.py` |
| Annotations `Any` / `dict[str, Any]` | 20 + 145 dict/list/tuple non paramétrés — beaucoup de `dict` nu en paramètre |
| Méthodes `__init__` sans `-> None` | 8 / 12 — `auth.UserStore.__init__`, `session.MemoryBackend.__init__`, etc. partiellement typées |
| `except Exception: pass` (silencieux) | **13** occurrences |
| `except Exception` (large catch) | **31** occurrences sur 13 fichiers |
| `except:` (bare) | 0 — bon point |
| `print(` (non-logger) | 0 — bon point |
| `TODO`/`FIXME`/`HACK` | 0 — soit très propre soit pas marqué |
| `from x import *` | 0 — bon point |
| Tests pytest | **130** fonctions de test sur 9 fichiers |
| Modules sans test direct | **8** : `routers/carte.py` (795 l.), `routers/compteurs.py` (278 l.), `routers/evaluation.py` (1 481 l.), `routers/export.py` (175 l.), `routers/models.py` (276 l.), `routers/training.py` (869 l.), `auth.py` (256 l.), `tasks.py` (76 l. — mort) |
| LOC testées vs non testées (estimation) | ~1 800 / 6 196 → **~29 % couverte structurellement** (modules avec tests) |

**Configuration ruff** (`pyproject.toml:46`) : `select = ["E", "F", "I", "UP", "B"]` — minimaliste, n'active **ni** `ANN` (annotations), **ni** `C901` (complexité), **ni** `S` (security), **ni** `SIM`, `PERF`, `RUF`. Inutile en l'état pour rattraper la dette.

---

## Top 10 problèmes priorisés

### [P0] Pipeline training dupliqué — router inline vs service propre non câblé
- **Fichiers** : `app/routers/training.py:268-710` (`_training_worker`, 442 lignes) vs `app/services/ml/training_pipeline.py` (`run_training`, 195 lignes)
- **Symptôme** : Deux implémentations du même grid search coexistent. Le router contient sa propre `_normalize` (l. 250-265), sa propre `_build_feature_sets` (l. 150-188), sa propre `_build_combinations` (l. 191-243), sa propre `GridProgressCallback` (l. 549-565). Ce sont des copies *quasi* identiques aux fonctions de `services/ml/normalize.py`, `grid_search.py`, `progress.py`. Le service propre n'est appelé que par `tasks.py:43` (Celery mort).
- **Effet** : Chaque correctif (le commit `fb5f835` write-through Redis, le `cefaac8` output_dir) doit être appliqué deux fois. Architecture déjà incohérente : `training_pipeline.py` retourne un dict d'artifacts en mémoire ; le router écrit directement sur disque sans passer par `services/ml/packaging.export_model_zip`. Le router compile aussi le modèle à la main au lieu d'utiliser `model_builder.build_model` (avec ses métriques `MeanAbsolutePercentageError`, `R2Score`).
- **Refacto** : Câbler `services/ml/run_training` dans `routers/training.py:_training_worker`. Garder la couche worker (TrainingTask + threading + SSE) mais déléguer toute la logique ML. Supprimer `_normalize`, `_build_feature_sets`, `_build_combinations` du router. Adapter `run_training` pour qu'il accepte un `cancel_event` et un `progress_callback` qui poussent dans `task.progress`.
- **Effort** : **L** (1-2 j) — couvert par les tests existants de `services/ml/*`.

### [P0] Tâches longues bloquent l'event loop FastAPI
- **Fichiers** : `app/routers/evaluation.py:1172-1421` (`run_evaluation`), `app/routers/carte.py:425-773` (`generate_carte`), `app/routers/compteurs.py:212-252`, `app/routers/upload.py:137-180`
- **Symptôme** : Routes déclarées `async` mais corps purement synchrone : `pd.read_csv`, `model.predict`, `zipfile.ZipFile.extractall`, `_my_norm` sur DataFrame de centaines de milliers de lignes, `df.iterrows()` (carte.py:719, compteurs.py:138), génération HTML/Folium (~500 lignes), tout dans la coroutine. Aucun appel à `asyncio.to_thread()` ni `loop.run_in_executor()`.
- **Effet** : Une seule prédiction sur un gros GeoJSON gèle toute l'API jusqu'à la fin (incluant `/health`, `/metrics`, et le SSE `/api/training/stream/{task_id}` qui n'envoie plus d'events). Au-delà de 2-3 users concurrents, le serveur uvicorn devient inaccessible.
- **Refacto** : Wrapper tout corps lourd dans `await asyncio.to_thread(_sync_function, args)`. Pour `model.predict` extraire le bloc CPU-bound en helper synchrone. Pour `extractall` idem.
- **Effort** : **M** (1 j).

### [P0] Exception handling muet — bugs silencieux
- **Fichiers** : `app/routers/training.py:294,298,302,454`, `app/services/ml/progress.py:91`, `app/services/ml/model_builder.py:34`, `app/session.py:165,194`, `app/routers/evaluation.py:1105`, `app/routers/carte.py:249`, `app/routers/models.py:62,91`
- **Symptôme** : 13 `except Exception: pass` sans log. Exemple critique `evaluation.py:1067` :
  ```python
  except (KeyError, Exception) as e:
      logger.debug("Key '%s' not found: %s", key, e)
      continue
  ```
  `(KeyError, Exception)` est redondant (KeyError ⊂ Exception) et le `logger.debug` n'est jamais visible en prod (LOG_LEVEL=INFO). Autre cas grave : `routers/training.py:454` swallow toute erreur `tf.keras.backend.clear_session()` — si la session TF est cassée le grid search continue sur des poids corrompus.
- **Effet** : Diagnostique impossible quand une feature échoue (Sentry voit l'erreur racine mais pas le contexte). Bugs intermittents persistants.
- **Refacto** : Pour chaque `except Exception: pass`, soit (a) typer l'exception attendue (`except OSError`, `except json.JSONDecodeError`), soit (b) ajouter `logger.warning("contexte: %s", exc, exc_info=True)`. Le pattern `for _setter in (lambda: ...): try/except` (model_builder.py:27-35) est un anti-pattern Python — préférer un wrapper nommé `_safe_call_tf_setter(setter, name)`.
- **Effort** : **S** (½ j).

### [P1] `_training_worker` — fonction monstrueuse
- **Fichiers** : `app/routers/training.py:268-710`
- **Symptôme** : 442 lignes, ~30 branches (if/for/try imbriqués), 8 niveaux d'indentation max (boucle `for fmask_idx, (fmask, group_combos) in enumerate(groups.items()):` puis `for combo in group_combos:` puis `if cancelled` puis `for i, factor in enumerate(nf):` puis `if/elif`). Complexité cyclomatique estimée **> 35** (seuil C901 ruff = 10). Mélange : config TF env, lecture session, normalisation, génération combos, training Keras, save disque, logging, gestion cancel — tout en une fonction.
- **Effet** : Untestable unitairement. Tout changement de spec (ex. nouveau loss, nouveau format save) impose de relire les 442 lignes pour trouver le point d'insertion. Le bug `output_dir` Redis (commit `cefaac8`) a échappé pendant N commits parce que la logique de persistance est noyée dans la masse.
- **Refacto** : Découper en `_setup_tf()`, `_load_session_data()`, `_prepare_arrays()`, `_run_grid_loop()`, `_save_artifact()`. Idéalement déléguer à `services/ml/run_training` (cf. P0 #1).
- **Effort** : **L** (1 j si fait isolément, 0 si fusionné avec P0 #1).

### [P1] Duplication `routers/evaluation.py` ↔ `services/ml/evaluation_pipeline.py`
- **Fichiers** : `app/routers/evaluation.py:146-318` vs `app/services/ml/evaluation_pipeline.py:170-309`
- **Symptôme** : `_add_tolerance_columns` (router l. 146-200) duplique `add_tolerance_columns` (service l. 170-240) à l'identique avec hardcoding `TVr`/`TMJABCTV` (router) vs paramétrage `type_config.eval_predicted_col` (service). Idem `_compute_flow_metrics` ↔ `compute_flow_metrics`, `_compute_tolerance_counts` ↔ `compute_tolerance_counts`. Les seuils GEH (5, 10), pourcentages (10/15/20 %) et tolérance dynamique (10000/5000/2000) sont copiés-collés. Le service supporte TV **et** PL ; le router seulement TV.
- **Effet** : Carte PL ne profite pas des fixes appliqués côté TV. Spec drift inévitable.
- **Refacto** : Importer `services.ml.evaluation_pipeline` dans le router. Supprimer les `_compute_*` du router.
- **Effort** : **M** (½ j).

### [P1] Code mort — Celery + tâches inexistantes
- **Fichiers** : `app/tasks.py` (76 l.), `app/celery_app.py` (33 l.)
- **Symptôme** : `tasks.py:43` importe `run_training_pipeline` qui n'existe pas (`services/ml/training_pipeline.py` exporte `run_training`, jamais `run_training_pipeline`). Donc `train_model_task` lèvera `ImportError` immédiatement si jamais Celery est démarré. `main.py` n'appelle ni `celery_app` ni `tasks`, aucun worker n'est documenté. Dépendance `celery[redis]>=5.3` dans `pyproject.toml:18` qui pèse pour rien.
- **Effet** : Bruit cognitif. Faux signal de robustesse architecture (faisait croire à du distribué).
- **Refacto** : Supprimer `tasks.py`, `celery_app.py`, et `celery[redis]` du `pyproject.toml`. Faire le ménage des `# Celery tasks` dans la doc/commits.
- **Effort** : **XS** (15 min).

### [P1] Magic numbers sans config
- **Fichiers** : multiples — exemples ci-dessous
- **Symptôme** :
  - `routers/training.py:27` : `SEED = 1750` (hardcodé, dupliqué `services/ml/training_pipeline.py:35`)
  - `routers/training.py:543` : `patience = max(30, max_epochs // 10)` (heuristique)
  - `routers/training.py:81` : `dropouts: list[float] = [0.05]` defaults
  - `routers/evaluation.py:26` : `DEFAULT_HIGH_FLOW_THRESHOLD = 1000.0`
  - `routers/evaluation.py:156-160` : seuils 10000/5000/2000 et marges 0.14/0.18/0.25 codées dans `erreur_pourcentage` (closure non-paramétrable)
  - `services/ml/evaluation_pipeline.py:186-193` : mêmes seuils dupliqués
  - `routers/carte.py:147-154`, `158-188` : seuils DPL répétés (500/1000/2000/4000/6000/10000)
  - `app/auth.py:42` : `_TOKEN_EXPIRE_HOURS = 24` non configurable
  - `app/main.py:36` : `_CLEANUP_INTERVAL_SECONDS = 300` non configurable
  - `app/session.py` : pas de seuil de cache_size sur `_RedisDataProxy`
- **Effet** : Seuils métier inchangeables sans recompile. `ErrorThresholds` Pydantic dans `carte.py:37-42` montre la bonne approche — à généraliser.
- **Refacto** : Promouvoir tout seuil métier en `Settings` (pydantic) ou en `ModelTypeConfig`. Centraliser les constantes d'algo dans un `constants.py`.
- **Effort** : **M** (½ j).

### [P2] Tests : ~30 % de couverture structurelle, 100 % des routers métier non couverts
- **Fichiers** : `tests/test_*.py`
- **Symptôme** : 130 tests couvrent `data_prep` (22), `grid_search` (20), `types` (28), `session` (21), `upload` (14), `normalize` (10), `mapping` (10), `health` (4), `packaging` (1). **Aucun test** pour `routers/carte.py`, `routers/compteurs.py`, `routers/evaluation.py`, `routers/export.py`, `routers/models.py`, `routers/training.py`, `auth.py`. Chemins d'erreur testés uniquement sur `data_prep` (NaN, missing cols) et `session` (TTL). Fixtures cohérentes (conftest.py:34-86 fournit CSV + GeoJSON minimaux).
- **Effet** : Le service ML propre est testé… mais ce n'est pas lui qui sert en prod. Les routers monolithiques qui contiennent toute la logique métier sont des trous noirs.
- **Refacto** : Ajouter au minimum un happy-path + un chemin d'erreur par route critique. Profiter de l'`AsyncClient(transport=ASGITransport(app=app))` déjà installé (conftest.py:29).
- **Effort** : **M** (1 j pour atteindre 50 %).

### [P2] Annotations de types incomplètes & dict non paramétrés
- **Fichiers** : largement transverse — exemples ci-dessous
- **Symptôme** : Types modernes utilisés (`X | None`, `list[X]`) mais beaucoup de zones non typées :
  - `routers/training.py:191` : `def _build_combinations(cfg: dict) -> list[dict]` — `dict` nu en entrée/sortie (alors que le contenu est très typé)
  - `routers/training.py:580` : `fit_kwargs: dict = {...}` puis `**fit_kwargs` — perte d'info
  - `routers/evaluation.py:139` : `def _fmt(v, digits=2):` — pas d'annotations
  - `routers/evaluation.py:151` : `def erreur_pourcentage(tvr):` — pas d'annotations
  - `routers/evaluation.py:337,350` : `def _color(val):`, `def _radius(v):` — pas d'annotations
  - `routers/carte.py:85` : `def _my_norm(X, on_off_norm, mu, S):` — retour non typé (`-> pd.DataFrame` ?)
  - `routers/carte.py:191` : `def _load_model(model_path: str):` — retour `-> tuple[Model, dict, dict | None]` manquant
  - `services/ml/training_pipeline.py:57` : `def __init__(self, **kwargs: Any):` — anti-pattern, vaudrait un dataclass
  - `auth.py:71-78` : `UserRecord` utilise `__slots__` + annotations dans `__init__` mais pas de dataclass — plus verbeux et moins introspectable
- **Effet** : Mypy ne peut pas remonter les régressions. IDE autocompletion partielle. ~35 % de retours typés vs 100 % attendu sur un backend Python 3.11.
- **Refacto** : Activer `ruff` règles `ANN`. Convertir `UserRecord`, `TrainedModelArtifact`, `TrainingTask` en dataclasses. Typer les helpers privés.
- **Effort** : **M** (1 j).

### [P2] Imports TF lourds dans le path critique + redondance env vars
- **Fichiers** : `services/ml/model_builder.py:8-22`, `services/ml/progress.py:9-17`, `services/ml/training_pipeline.py:10-21`, `tasks.py:6-15`
- **Symptôme** : `setdefault("CUDA_VISIBLE_DEVICES", "-1")`, `setdefault("TF_CPP_MIN_LOG_LEVEL", "3")` répété dans **6** fichiers (config.py, tasks.py, training.py:275, evaluation.py:1018, evaluation.py:1179, carte.py:193, model_builder.py:8, training_pipeline.py:10, progress.py:9, packaging.py:92). Les imports TF top-level dans `model_builder.py`, `progress.py`, `training_pipeline.py` chargent TensorFlow (~3 s, ~500 Mo RAM) dès `from app.services.ml import build_model`. `services/ml/__init__.py:55` a un `__getattr__` lazy précisément pour éviter ça — mais `training_pipeline.py` lui-même importe TF top-level (l. 20), donc à la première utilisation tout charge.
- **Effet** : Démarrage uvicorn lent. Tests unitaires (`test_normalize.py`) tirent TF sans en avoir besoin si on touche au mauvais module.
- **Refacto** : Centraliser le setup TF env vars dans `app/config.get_settings()` (déjà partiellement fait l. 72-74) et y déléguer un `init_tf_env()`. Déplacer `import tensorflow as tf` dans les corps de fonction des modules vraiment lazy.
- **Effort** : **S** (½ j).

---

## Plan de refacto ordonné

| # | Action | Bénéfice principal | Effort |
|---|---|---|---|
| 1 | Supprimer `tasks.py` + `celery_app.py` + dep `celery[redis]` | -110 l. de code mort, dependance bruyante | XS (15 min) |
| 2 | Câbler `services/ml/run_training` dans le worker du router training | Élimine 442 l. dupliquées, rend testable | L (1,5 j) |
| 3 | Câbler `services/ml/evaluation_pipeline` dans le router evaluation | Supporte PL gratuit, élimine 170 l. dupliquées | M (½ j) |
| 4 | Remplacer les 13 `except Exception: pass` par log ou exception typée | Diagnostique prod, fiabilité | S (½ j) |
| 5 | Wrapper en `asyncio.to_thread` toutes les routes lourdes (eval, carte, compteurs, upload) | Concurrence multi-user, SSE fiable | M (1 j) |
| 6 | Découper `_generate_html_report` (320 l.) en helpers nommés + jinja2 template externe | Maintenabilité du rapport, séparation HTML/Python | M (1 j) |
| 7 | Promouvoir magic numbers (seuils GEH, DPL, patience, SEED, TTL token) en `Settings` ou `ModelTypeConfig` | Tuning sans recompile | M (½ j) |
| 8 | Ajouter ruff `ANN`, `C901`, `S`, `SIM`, `PERF`, `RUF` au pyproject.toml + corriger top 50 violations | Garde-fou pérenne | M (1 j) |
| 9 | Tests routers : 1 happy-path + 1 erreur par route critique (training, eval, carte, models, auth) | 30 % → 60 % couverture | M (1 j) |
| 10 | Convertir `UserRecord`, `TrainingTask`, `TrainedModelArtifact` en `@dataclass` | Lisibilité, repr/eq gratis | S (½ j) |
| 11 | Centraliser `import os; os.environ.setdefault(...)` TF en `init_tf_env()` | Cohérence, démarrage propre | S (½ j) |
| 12 | Compléter typage retour (closures, helpers `_fmt`, `_color`, `_radius`, `_my_norm`, `_load_model`) | Mypy strict envisageable | S (½ j) |

**Effort total estimé : ~9-10 j-homme.** Les items 1, 2, 3, 4, 5 (≈4 j) traitent les P0 et débloquent le reste.

---

## Quick wins (< 1h chacun)

- Supprimer `tasks.py`, `celery_app.py`, et `celery[redis]>=5.3` de `pyproject.toml:18`.
- Remplacer `except (KeyError, Exception) as e:` par `except Exception as e:` dans `evaluation.py:1067` (KeyError est déjà couvert).
- Remplacer `(FileNotFoundError, Exception)` par `Exception` dans `carte.py:442,447`.
- Supprimer la closure `class GridProgressCallback` dans `_training_worker` (training.py:549-565) et utiliser `TrainingProgressCallback` de `services/ml/progress.py` (déjà fait pour ça).
- Remplacer `dict` nu par `dict[str, Any]` dans `training.py:191,580`, `tasks.py:27-35`, `auth.py:45`.
- Ajouter `-> None` aux `__init__` non typés (`MemoryBackend.__init__`, `UserStore.__init__`, `RedisBackend.__init__`, `_RedisDataProxy.__init__`, `RequestIDMiddleware.__init__`, `TrainingProgressCallback.__init__`).
- Annoter `_fmt(v, digits=2)` → `_fmt(v: Any, digits: int = 2) -> str` (`evaluation.py:139`).
- Remplacer `f.read()` + `model_from_json(f.read())` par `arch_file.read_text(encoding="utf-8")` dans `carte.py:213-218` (cohérence avec `evaluation.py:1028`).
- Extraire la constante `SEED = 1750` dans `app/config.py` (actuellement dupliquée 2 fois).
- Activer `ruff --select ANN,SIM,PERF` en mode warning pour visualiser la dette sans bloquer le CI.
- Ajouter un test smoke `test_carte.py` qui POST `/api/carte/generate` avec un GeoJSON minimal + un fake model dir (mock TF).
- Sortir le CSS/JS inline du `_generate_html_report` (evaluation.py:603-682 et 892-1009) vers `app/templates/eval_report.html` + utiliser Jinja2.
- Convertir `for old, new in renames.items(): if old in df.columns and new not in df.columns: df[new] = df[old]` (répété 3 fois : `evaluation.py:1118-1129`, `evaluation.py:1262-1269`, `training.py:317-319`) en helper `_rename_aliases(df, mapping) -> pd.DataFrame`.
- Remplacer `df.iterrows()` (carte.py:719, compteurs.py:138, evaluation.py:378) par construction vectorisée numpy / `df.to_dict(orient="records")` — gain perf ×10 sur gros DF.
- Documenter par docstring publique les 3 modules sans docstring : `app/__init__.py` (vide), `tests/__init__.py` (vide).
- Ajouter `pytest-cov` à `[project.optional-dependencies].dev` pour mesurer la couverture réelle.

---

## Annexe — détails par catégorie ruff (probable)

Sur un `ruff check --select ALL` réaliste, les violations probables ranked :

1. **ANN** (annotations) : ~150 — params/retours non annotés dans les helpers internes et closures.
2. **C901** (complexité) : 3-5 — `_training_worker`, `run_evaluation`, `generate_carte`, `_generate_html_report`, `_build_sensitivity_section_html`.
3. **PLR0913** (trop d'args) : 3-5 — `_train_single` (16 paramètres !), `_build_sensitivity_section_html` (8), `split_train_valid` (7).
4. **PLR0915** (trop de statements) : 4-6 — mêmes fonctions monstrueuses + `_generate_html_report` (320 statements).
5. **BLE001** (bare exception catch) : 31 occurrences — toutes les `except Exception`.
6. **S110/S112** (try-except-pass / continue) : 13 occurrences sur les `except Exception: pass`.
7. **PERF401** (manual list comprehension) : ~10 — boucles `for ... append` convertibles.
8. **SIM117** (combine nested with) : 2-3 — `routers/carte.py:213` + `routers/upload.py:235`.
9. **SIM108** (ternary) : ~15 — `if/else` 1-ligne sur affectations.
10. **RUF013** (implicit Optional) : ~5 — paramètres avec `= None` sans `| None` (rare, code globalement propre sur ce point).

Catégories **non préoccupantes** : `E`/`F` (pyflakes) : très peu — `from __future__ import annotations` partout, imports propres. `I` (isort) : OK manuellement. `UP` (pyupgrade) : OK (`X | None`, `list[...]` utilisés). `S` (security) : modules upload font le path traversal check (upload.py:30-37, models.py:166-171). `B` (bugbear) : à vérifier sur les closures de boucle (`_model_counter = model_counter` dans training.py:546 montre une conscience du problème B023).

---

## Annexe — fichiers cités

- `apps/api/app/main.py` (196 l.)
- `apps/api/app/auth.py` (256 l.)
- `apps/api/app/session.py` (375 l.)
- `apps/api/app/config.py` (75 l.)
- `apps/api/app/tasks.py` (76 l. — mort)
- `apps/api/app/celery_app.py` (33 l. — mort)
- `apps/api/app/routers/training.py` (869 l. — monolithe)
- `apps/api/app/routers/evaluation.py` (1 481 l. — monolithe HTML)
- `apps/api/app/routers/carte.py` (795 l. — monolithe TV+PL)
- `apps/api/app/routers/compteurs.py` (278 l.)
- `apps/api/app/routers/mapping.py` (289 l.)
- `apps/api/app/routers/models.py` (276 l.)
- `apps/api/app/routers/export.py` (175 l.)
- `apps/api/app/routers/upload.py` (255 l.)
- `apps/api/app/services/ml/training_pipeline.py` (403 l. — non câblé)
- `apps/api/app/services/ml/evaluation_pipeline.py` (417 l. — non câblé)
- `apps/api/app/services/ml/grid_search.py` (144 l.)
- `apps/api/app/services/ml/data_prep.py` (192 l.)
- `apps/api/app/services/ml/model_builder.py` (98 l.)
- `apps/api/app/services/ml/normalize.py` (53 l.)
- `apps/api/app/services/ml/packaging.py` (142 l.)
- `apps/api/app/services/ml/progress.py` (92 l.)
- `apps/api/app/services/ml/types.py` (127 l.)
- `apps/api/pyproject.toml` (60 l.)
- `apps/api/tests/conftest.py` (94 l.)
