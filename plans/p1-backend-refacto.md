# Plan refonte backend — MDL

## Vision

Refondre le backend FastAPI MDL v2 (cible : ~5-10 users internes sur Oracle Cloud ARM A1, 1 worker uvicorn) sur trois axes : (1) **sécurité** (auth obligatoire, ownership session, suppression Pickle Redis, JWT hardening, path traversal, rate-limit, headers), (2) **dette Python** (suppression Celery mort, bascule routers `training`/`evaluation` vers les services `services/ml/*` déjà testés, IO non-bloquant via `asyncio.to_thread`, exceptions explicites), (3) **rigueur ML** (reproductibilité complète, `sample_weight`, early-stopping sain, format `.keras`, métadonnées, cap grid). Volume : **~7 j-homme** parallélisables E1 (sécu, ~1,6 j) + E2 (refacto+ML+tests, ~5 j).

## Actions ordonnées

### Bloc A — Sécurité [P0, owner E1]

**A1. Auth obligatoire sur tous routers métier** — files: `apps/api/app/main.py` (l.178-185) — effort: 1,5h — bloque: A2.
Dans `main.py`, modifier chaque `app.include_router(<r>.router)` métier en `app.include_router(<r>.router, dependencies=[Depends(get_current_user)])`. Importer `Depends` et `from .auth import get_current_user`. `auth_router` reste sans (sinon `/register`/`/login` deviennent inaccessibles). Routers couverts : `upload`, `mapping`, `training`, `evaluation`, `export`, `carte`, `compteurs`, `models` — soit 28 endpoints (les 26 listés via grep `@router.*` + variantes upload). Avantage : une ligne, zéro endpoint oublié.
_Pourquoi_ : audit 01, finding P0-1.

**A2. Couplage `Session.owner_user_id` + `get_owned_session`** — files: `apps/api/app/session.py` (classe `Session` ~l.60, `create_session` l.84, sérialiseurs), `apps/api/app/auth.py`, tous routers consommant `session_id` — effort: 3h — bloque: A5.
(a) Ajouter `owner_user_id: str` au `Session` et le persister dans Redis. (b) `create_session(mode, owner_user_id)` étendu. (c) Helper dans `auth.py` :
```python
def get_owned_session(session_id: str, current_user: UserRecord = Depends(get_current_user)) -> Session:
    s = session_manager.get_session(session_id)
    if s is None or s.owner_user_id != current_user.user_id:
        raise HTTPException(404, "Session introuvable")
    return s
```
(d) Remplacer `session_manager.get_session(...)` par `session: Session = Depends(get_owned_session)` dans chaque endpoint training/evaluation/carte/compteurs/export/models/mapping. (e) `POST /api/upload` appelle `create_session(mode, owner_user_id=current_user.user_id)`. (f) Tronquer `session_id` à 8 hex dans logs (`session.py:88,99,264`).
_Pourquoi_ : audit 01, finding P1-2 (IDOR systémique).

**A3. Supprimer fallback Pickle Redis** — files: `apps/api/app/session.py` (`_serialize_value` l.238-242, `_deserialize_value` l.246-249), `apps/api/app/routers/mapping.py` (l.256-259 pattern existant) — effort: 2h — bloque: aucun.
(a) Retirer `pickle.dumps` du `_serialize_value` ; toujours Parquet via helper `_df_to_parquet_safe(df)` qui cast colonnes non-Parquet (geometry, dict, objets) en str JSON. (b) Retirer `pickle.loads` du `_deserialize_value` ; sur préfixe `__DFPKL__` raise `ValueError("legacy pickle blob refused")` + log — blobs Pickle existants invalidés au prochain redémarrage (TTL court). (c) Test : `test_session_no_pickle_loaded()` injecte `__DFPKL__` et vérifie le refus.
_Pourquoi_ : audit 01, finding P0-2 (RCE).

**A4. Hardening `JWT_SECRET` (fail-fast)** — files: `apps/api/app/config.py` (l.53), `.env.production`, `infra/docker-compose.yml` (l.40,65) — effort: 30 min — bloque: aucun.
`field_validator("JWT_SECRET")` Pydantic v2 dans `Settings` : refuse `{"", "change-me-in-production", "change-me-in-production-use-a-real-secret"}` et toute longueur `< 32`. Retirer default trivial. Dans `docker-compose.yml`, retirer fallback `:-change-me-in-production`. README : doc `openssl rand -hex 32`. Vérifier `git log --all -p .env.production` ; si commit présent → rotation immédiate.
_Pourquoi_ : audit 01, P0-3.

**A5. Path traversal : confiner sous `WORKSPACE_ROOT/{user_id}/{session_id}/`** — files: `apps/api/app/security.py`, `apps/api/app/config.py`, `apps/api/app/routers/evaluation.py` (l.1195, l.1461), `apps/api/app/routers/carte.py` (l.277, l.441, l.446), `apps/api/app/routers/export.py` (l.89-101), `apps/api/app/routers/models.py` (l.128), `apps/api/app/routers/training.py` (output) — effort: 2h — dépend de A2.
(a) Helper `session_root(user_id, session_id) -> Path`. (b) Migrer structure disque : `WORKSPACE_ROOT/{user_id}/{session_id}/{models|carte|compteurs}/`. (c) Dans chaque endpoint recevant `model_dir`/`model_tv_dir`/`model_pl_dir`/`output_dir`/`dir` :
```python
safe = validate_path(body.model_dir, allowed_root=str(session_root(user.user_id, session.session_id)))
```
Échappement → `HTTPException(400, "invalid path")`. (d) `download-model` zip : `rglob` confiné sous `session_root`.
_Pourquoi_ : audit 01, finding P1-1.

**A6. Rate-limit slowapi effectif** — files: `apps/api/app/auth.py` (register l.230, login l.245), `apps/api/app/routers/upload.py` (l.137), `apps/api/app/routers/training.py` (l.717), `apps/api/app/routers/carte.py` (l.425) — effort: 1h — bloque: aucun.
Exposer `limiter` via `app/rate_limit.py` (casse cycle d'import). Décorateurs :
- `@limiter.limit("5/minute")` sur `POST /api/auth/login`
- `@limiter.limit("3/hour")` sur `POST /api/auth/register`
- `@limiter.limit("10/minute")` sur `POST /api/upload`
- `@limiter.limit("2/hour")` sur `POST /api/training/start` (clé = user_id)
- `@limiter.limit("5/minute")` sur `POST /api/carte/generate`
Ajouter `request: Request` aux signatures décorées. Vérifier `SlowAPIMiddleware` dans la stack.
_Pourquoi_ : audit 01, finding P1-3.

**A7. Middleware headers sécurité** — files: `apps/api/app/main.py` (middleware avant l.150), `infra/nginx.conf` (l.14-31) — effort: 45 min — bloque: aucun.
`@app.middleware("http")` ajoutant à toute réponse : `Strict-Transport-Security: max-age=63072000; includeSubDomains`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, et CSP : `default-src 'self'; script-src 'self' cdn.plot.ly cdn.datatables.net code.jquery.com 'unsafe-inline'; img-src 'self' data: *.openstreetmap.org *.cartocdn.com; frame-src 'none'`. Dupliquer en `add_header` nginx. XSS rapport HTML (`evaluation.py:265,378-385`) : wrapper interpolation CSV via `html.escape()`.
_Pourquoi_ : audit 01, finding P2-2.

**A8. `/metrics` `/docs` `/health` + handler global** — files: `apps/api/app/main.py` (l.128-132, l.156, l.190-196, init FastAPI) — effort: 45 min — bloque: aucun.
(a) Si `settings.ENVIRONMENT == "production"` : `FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)`. (b) `/health` minimal `{"status":"ok"}` (retirer version, active_sessions). (c) `/metrics` : dépendance IP-allowlist (`request.client.host in settings.METRICS_ALLOWED_IPS`) ou Basic-Auth. (d) Handler global : logger complet côté serveur, renvoyer `{"detail": "internal error", "request_id": req_id}` sans `type(exc).__name__` ni message.
_Pourquoi_ : audit 01, P3-1 et P3-2.

**A9. Cap CPU training : sémaphore N=1/user + deadline réelle** — files: `apps/api/app/routers/training.py` (l.268-710, l.717-770), `apps/api/app/config.py` (settings `MAX_TRAINING_MINUTES`, `MAX_GRID_COMBINATIONS`) — effort: 1,5h — bloque: aucun.
(a) Module : `_TRAINING_EXECUTOR = ThreadPoolExecutor(max_workers=1)` + `_user_locks: dict[str, threading.Lock]`. (b) `start_training` : `if not _user_locks.setdefault(user.user_id, threading.Lock()).acquire(blocking=False): raise HTTPException(409, "training already running")` ; libérer dans `finally`. (c) `if len(combinations) > settings.MAX_GRID_COMBINATIONS: raise HTTPException(400, ...)`. (d) `GridProgressCallback.on_epoch_end` : si `datetime.now() > deadline` (start + MAX_TRAINING_MINUTES) → `self.model.stop_training = True` + `task.status="timeout"`.
_Pourquoi_ : audit 01, P1-3 + audit ML P1-5.

---

### Bloc B — Refacto Python [P0/P1, owner E2]

**B1. Suppression Celery mort** — files: `apps/api/app/tasks.py`, `apps/api/app/celery_app.py`, `infra/Dockerfile.worker`, `infra/docker-compose.yml` (service `worker`), `apps/api/pyproject.toml` (dep `celery[redis]>=5.3` l.18) — effort: 20 min — bloque: aucun.
`rm tasks.py celery_app.py Dockerfile.worker` ; retirer le bloc `worker:` du compose ; retirer la dépendance Celery du `pyproject.toml`. `poetry/uv lock` à régénérer. Aucun appel actif (vérifié : `main.py` n'importe ni `celery_app` ni `tasks`).
_Pourquoi_ : audit 02, P1 « Code mort — Celery + tâches inexistantes ».

**B2. Migration `_training_worker` → `services.ml.training_pipeline.run_training`** — files: `apps/api/app/routers/training.py` (l.268-710 à supprimer, l.717-770 à rebrancher), `apps/api/app/services/ml/training_pipeline.py` — effort: 12h — bloque: B5, C2, D1.
(a) Étendre `run_training(..., cancel_event: threading.Event | None, progress_callback: Callable[[ProgressEvent], None] | None)`. (b) Conserver `TrainingTask` (état SSE) + executor + route SSE ; `_training_worker` réduit à : parser config, charger session data, appeler `run_training(..., progress_callback=lambda ev: task.push(ev), cancel_event=task.cancel_event)`, sérialiser artifacts via `packaging.export_model_zip`. (c) Supprimer `_normalize` (l.250-265), `_build_feature_sets` (l.150-188), `_build_combinations` (l.191-243), `GridProgressCallback` (l.549-565) — tout existe dans `services/ml/{normalize,grid_search,progress}.py`. (d) Backward compat clés SSE.
_Pourquoi_ : audit 02, P0 #1 ; audit ML P1-1 et P0-2 (récupère `sample_weight`).

**B3. Migration scoring `evaluation.py` → `services.ml.evaluation_pipeline`** — files: `apps/api/app/routers/evaluation.py` (l.146-318 supprimer `_add_tolerance_columns`, `_compute_flow_metrics`, `_compute_tolerance_counts`, `erreur_pourcentage`), `apps/api/app/services/ml/evaluation_pipeline.py` — effort: 4h — bloque: D1.
Remplacer les helpers dupliqués par les fonctions paramétrées du service (`add_tolerance_columns`, `compute_flow_metrics`, `compute_tolerance_counts`). Profiter du paramétrage `type_config.eval_predicted_col` pour supporter PL gratis. Conserver la couche présentation (génération HTML/Plotly) dans le router.
_Pourquoi_ : audit 02, P1 « Duplication routers/evaluation.py ↔ services/ml/evaluation_pipeline.py » ; audit ML P2-1.

**B4. Wrap routes async via `asyncio.to_thread`** — files: `apps/api/app/routers/evaluation.py` (l.1172-1421), `apps/api/app/routers/carte.py` (l.425-773), `apps/api/app/routers/compteurs.py` (l.211-252), `apps/api/app/routers/upload.py` (l.137-180) — effort: 4h — bloque: aucun.
Pour chaque route lourde : extraire bloc CPU/IO en helper sync `_run_eval_sync`, `_generate_carte_sync`, `_process_upload_sync` ; coroutine fait `result = await asyncio.to_thread(_run_eval_sync, args...)`. Cibles : `model.predict`, `pd.read_csv`, `model.save`, `zipfile.ZipFile.extractall`, ops `geopandas`. Ne pas wrapper ops <50ms.
_Pourquoi_ : audit 02, P0 « Tâches longues bloquent event loop ».

**B5. Nettoyer les 13 `except Exception: pass`** — files: `apps/api/app/routers/training.py:294,298,302,454`, `apps/api/app/services/ml/progress.py:91`, `apps/api/app/services/ml/model_builder.py:34`, `apps/api/app/session.py:165,194`, `apps/api/app/routers/evaluation.py:1067,1105`, `apps/api/app/routers/carte.py:249`, `apps/api/app/routers/models.py:62,91` — effort: 2h — bloque: aucun.
Pour chaque cas : (1) typer l'exception réellement attendue (`OSError`, `json.JSONDecodeError`, `KeyError`, `tf.errors.InvalidArgumentError`), (2) à défaut `except Exception` + `logger.warning("ctx: %s", exc, exc_info=True)`. Cas `evaluation.py:1067` : `(KeyError, Exception)` → `Exception`. Cas `model_builder.py:27-35` : helper `_safe_call_tf_setter(setter, name)` réutilisable.
_Pourquoi_ : audit 02, P0 « Exception handling muet ».

**B6. Type hints signatures publiques + helpers critiques** — files: `apps/api/app/routers/training.py` (l.191, l.580), `apps/api/app/routers/evaluation.py` (l.139, l.151, l.337, l.350), `apps/api/app/routers/carte.py` (l.85, l.191), `apps/api/app/auth.py`, `apps/api/app/session.py`, `apps/api/app/services/ml/training_pipeline.py:57` — effort: 2h — bloque: aucun.
Cibler ~15 signatures publiques. Convertir `UserRecord`, `TrainingTask`, `TrainedModelArtifact` en `@dataclass(slots=True)`. `dict` nu → `dict[str, Any]`. Ajouter `-> None` aux 8 `__init__` manquants. Activer `ruff` règles `ANN` en mode `warning` dans `pyproject.toml`.
_Pourquoi_ : audit 02, P2 « Annotations ».

---

### Bloc C — ML [P1, owner E2]

**C1. `seed_everything()` + `enable_op_determinism`** — files: `apps/api/app/services/ml/training_pipeline.py`, `apps/api/app/routers/training.py` (l.280), `apps/api/app/config.py`, `apps/api/app/main.py` — effort: 1,5h — bloque: aucun.
(a) Ajouter dans `services/ml/training_pipeline.py` :
```python
def seed_everything(seed: int) -> None:
    import os, random, numpy as np, tensorflow as tf, keras
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed); np.random.seed(seed); tf.random.set_seed(seed)
    keras.utils.set_random_seed(seed)
    tf.config.experimental.enable_op_determinism()
```
(b) Appeler au début de `run_training` ET avant chaque `model.fit` dans la boucle. (c) Supprimer `TF_DISABLE_SEGMENT_REDUCTION_OP_DETERMINISM_EXCEPTIONS=1` (training.py:280). (d) Documenter dans README : lancer uvicorn avec `PYTHONHASHSEED=1750` dans unit systemd.
_Pourquoi_ : audit ML P0-1.

**C2. Réintroduire `sample_weight = flag_comptage * 4`** — files: `apps/api/app/services/ml/training_pipeline.py` (l.172-181 déjà OK) — effort: 0 (couvert par B2).
La logique existe (`use_flag_comptage_weighting`, `flag_priority_weight=4.0`). B2 la réactive. Vérifier que `TrainingConfig.use_flag_comptage_weighting` est exposé côté API et `True` par défaut.
_Pourquoi_ : audit ML P0-2.

**C3. EarlyStopping sain + ReduceLROnPlateau** — files: `apps/api/app/services/ml/training_pipeline.py` (l.107-115) — effort: 30 min.
`patience=50` (au lieu de `max(30, max_epochs//10)`), `start_from_epoch=min(50, min_nb_epochs // 4)` (permet arrêt avant `min_epochs` si divergence). Ajouter `ReduceLROnPlateau(monitor=monitor_metric, factor=0.5, patience=20, min_lr=1e-5)`.
_Pourquoi_ : audit ML P0-3.

**C4. Migration `.h5` → `.keras` natif (rétrocompat lecture)** — files: `apps/api/app/services/ml/packaging.py` (l.47), `apps/api/app/routers/evaluation.py` (l.1028), `apps/api/app/routers/carte.py` (l.191-226) — effort: 2h — bloque: aucun.
(a) Écriture : `model.save(path / "model.keras")` à la place de archi JSON + `.weights.h5`. Conserver `training_config.json` et `meta.json`. (b) Lecture : helper `_load_model_compat(model_dir)` essaie `keras.models.load_model(dir / "model.keras")`, fallback `model_from_json(...)` + `load_weights("NNweights.weights.h5")`. (c) Appliquer dans `evaluation.py` et `carte.py`.
_Pourquoi_ : audit ML P1-4.

**C5. Métadonnées modèles (`meta.json`)** — files: `apps/api/app/services/ml/packaging.py`, `apps/api/app/config.py` (lit `GIT_SHA` via `git rev-parse HEAD` au boot) — effort: 1h — bloque: aucun.
À chaque save modèle, écrire `meta.json` avec : `git_sha`, `tf_version`, `keras_version`, `numpy_version`, `sklearn_version`, `python_version`, `seed`, `data_sha256`, `training_started_at`, `training_ended_at`, `hostname`. Hash dataset : `hashlib.sha256(pd.util.hash_pandas_object(df, index=True).values.tobytes()).hexdigest()`.
_Pourquoi_ : audit ML P1-3.

**C6. Cap grid ≤ 100 combos + ETA** — files: `apps/api/app/services/ml/grid_search.py`, `apps/api/app/routers/training.py` (l.717), `apps/api/app/config.py` — effort: 30 min — partiel via A9.
`MAX_GRID_COMBINATIONS = 100` dans settings. Après `build_combinations` : `if len(combos) > settings.MAX_GRID_COMBINATIONS: raise HTTPException(400, ...)`. Inclure ETA (`n_combos * mean_epochs * 0.5s`) dans `TrainingStartResponse`.
_Pourquoi_ : audit ML P1-5.

**C7. `clear_session()` entre chaque modèle** — files: `apps/api/app/services/ml/training_pipeline.py` (boucle grid l.~200), `apps/api/app/routers/carte.py` (l.494, l.582) — effort: 30 min — bloque: aucun.
Fin de chaque itération de la boucle `run_training` : `del model; gc.collect(); tf.keras.backend.clear_session()`. Idem dans `carte.py` après `model.predict` (2 occurrences). Couvre fuite mémoire sur grids longs.
_Pourquoi_ : audit ML P1-8.

---

### Bloc D — Tests [P1, owner E2]

**D1. Tests routers (happy-path + erreur)** — files: `apps/api/tests/test_carte.py`, `test_compteurs.py`, `test_evaluation.py`, `test_export.py`, `test_models.py`, `test_training.py` (tous nouveaux) — effort: 8h — dépend de B2, B3.
Par router : 1 happy-path (200 + clés attendues) + 1 erreur auth (401 sans token) + 1 erreur métier (mauvais session_id → 404, model_dir hors workspace → 400). Mocker `tensorflow` via `monkeypatch.setattr("apps.api.app.services.ml.training_pipeline.tf", MagicMock())` pour CI (pattern de `test_packaging.py` skip). Réutiliser `AsyncClient` et fixtures `conftest.py:34-86`.
_Pourquoi_ : audit 02, P2 « routers métier non couverts ».

**D2. Test du flow auth complet (register → login → endpoint protégé)** — files: `apps/api/tests/test_auth_flow.py` (nouveau) — effort: 1,5h — bloque: dépend de A1.
3 tests : (a) `POST /api/auth/register` → 201 + user_id ; (b) `POST /api/auth/login` avec mêmes credentials → 200 + token JWT décodable ; (c) `POST /api/upload` sans header `Authorization` → 401 ; même requête avec `Bearer <token>` → 201. Couvre la régression « auth obligatoire ».
_Pourquoi_ : audit 01, P0-1 + audit 02, P2 tests routers absents.

**D3. Fixtures partagées `conftest.py`** — files: `apps/api/tests/conftest.py` — effort: 1h — bloque: D1, D2.
Ajouter : `authenticated_client` (AsyncClient avec `Bearer <token>` pré-injecté), `owned_session_id` (user + session associée), `tmp_workspace` (override `WORKSPACE_ROOT` via monkeypatch). Permet aux tests D1/D2 de tenir en 5-10 lignes chacun.
_Pourquoi_ : audit 02, P2.

---

## Récap effort

| Bloc | Action | Effort (h) | Owner |
|---|---|---:|---|
| A | A1 Auth routers | 1,5 | E1 |
| A | A2 Ownership session | 3 | E1 |
| A | A3 Suppression Pickle | 2 | E1 |
| A | A4 JWT hardening | 0,5 | E1 |
| A | A5 Path traversal | 2 | E1 |
| A | A6 Rate-limit | 1 | E1 |
| A | A7 Headers sécurité | 0,75 | E1 |
| A | A8 /metrics /docs /health | 0,75 | E1 |
| A | A9 Cap CPU training | 1,5 | E1 |
| **Bloc A total** | | **13** (~1,6 j) | E1 |
| B | B1 Suppr Celery | 0,3 | E2 |
| B | B2 Migration training | 12 | E2 |
| B | B3 Migration evaluation | 4 | E2 |
| B | B4 asyncio.to_thread | 4 | E2 |
| B | B5 Exceptions | 2 | E2 |
| B | B6 Type hints | 2 | E2 |
| **Bloc B total** | | **24,3** (~3 j) | E2 |
| C | C1 Reproductibilité | 1,5 | E2 |
| C | C2 sample_weight | 0 (via B2) | E2 |
| C | C3 EarlyStopping | 0,5 | E2 |
| C | C4 Format .keras | 2 | E2 |
| C | C5 meta.json | 1 | E2 |
| C | C6 Cap grid | 0,5 | E2 |
| C | C7 clear_session | 0,5 | E2 |
| **Bloc C total** | | **6** (~0,75 j) | E2 |
| D | D1 Tests routers | 8 | E2 |
| D | D2 Tests auth flow | 1,5 | E2 |
| D | D3 Fixtures | 1 | E2 |
| **Bloc D total** | | **10,5** (~1,3 j) | E2 |
| **GRAND TOTAL** | | **~54 h (~6,8 j)** | E1 + E2 |

## Plan d'exécution recommandé

**Deux pistes parallèles** (E1 sécurité, E2 refacto/ML/tests). Wall-clock ~5 jours si parallèle, 7 jours si séquentiel.

| Jour | E1 (sécurité) | E2 (refacto + ML + tests) |
|---|---|---|
| 1 | A4 → A1 → A3 (API auth-only, plus de RCE Redis) | B1 → B5 → C1 → C3 → C7 (quick wins ML sans toucher au router) |
| 2 | A2 (gros morceau) → A5 | Démarrer B2 phase 1 (adapter `run_training` cancel+callback) |
| 3 | A6 → A9 → A7 → A8 (sécu E1 terminée, ~13 h) | Suite B2 (brancher worker sur `run_training`, conserver SSE) |
| 4 | Code review + hardening déploiement (firewall Oracle, Redis bind 127.0.0.1, user non-root Dockerfile) + tests sécu manuels | Finir B2 (smoke SSE) → B3 → C2 |
| 5 | dispo | B4 → C4 → C5 → C6 |
| 6 | — | B6 → D3 → D2 → D1 partiel (training + evaluation) |
| 7 | — | D1 reste (carte, compteurs, export, models) + `pytest --cov` (≥ 55 %) |

**Synchronisations E1 ↔ E2**
- Fin J1 (A1) : E2 ajoute `Authorization: Bearer` dans tests (fixture D3 à anticiper).
- Fin J2 (A2) : signature `Depends(get_owned_session)` change tous routers ; E2 rebase B2/B3 sur la version post-A2 pour éviter conflits.
- Fin J2 (A5) : E2 utilise `session_root(user_id, session_id)` pour `output_dir` training (cohérence C4/C5).

**Hors scope (différé sprint 2)** : MLflow embedded (audit ML P1-6, ROI faible 5-10 users), Optuna/KerasTuner (P1-5), `data_quality.py` (P1-2), cache LRU `_load_model` carte (P2-7). Le fix bug GEH /24 est **déjà appliqué** dans `routers/evaluation.py` (hors scope).
