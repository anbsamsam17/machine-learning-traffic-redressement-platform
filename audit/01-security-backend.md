# Audit sécurité backend — MDL Redressement Tool v2

## Résumé exécutif

**Note globale : 3.5 / 10.** Le backend embarque une auth JWT/bcrypt correctement écrite mais **aucun endpoint métier ne l'utilise** : l'API est de facto publique. À cela s'ajoutent une **désérialisation Pickle exploitable depuis Redis**, **plusieurs path-traversal** sur les paramètres `model_dir` / `output_dir` / `dir`, et un **secret JWT identique pour tous les déploiements** versionné dans `.env.production`. L'isolation multi-tenant n'existe pas : la `session_id` (UUID v4) est l'unique cookie d'accès, devinable par énumération via les endpoints non-auth ou bruteforçable à 200 req/min (limiter trop large). Posture acceptable pour un POC LAN, **dangereuse en exposition Internet** sur `Trafic-Tool.anbri-tools-ia.online`. Trois P0, trois P1, deux P2, deux P3.

## Findings

### [P0-1] Aucun endpoint métier n'exige d'authentification — API entièrement publique

**Fichier** : `apps/api/app/main.py:162-185` (montage des routers) ; vérifié par `grep` sur tous les `@router.*` : seul `apps/api/app/auth.py:255` (`/api/auth/me`) a `Depends(get_current_user)`.
**Description** : Le système JWT existe (`/api/auth/register`, `/login`, `/me`) mais aucun router (upload, training, evaluation, export, carte, compteurs, mapping, models) n'injecte `get_current_user`. N'importe quel client connaissant l'URL peut uploader 500 MB, démarrer un grid search, lister les modèles, télécharger les exports.
**Impact** : Confidentialité (tout fichier uploadé est lisible par toute IP qui devine ou énumère une `session_id`), intégrité (pollution de session/modèles), disponibilité (DoS CPU et stockage), exfiltration de modèles entraînés par concurrents.
**Exploitation** :
```bash
# Étranger non authentifié :
curl -X POST https://trafic-tool.anbri-tools-ia.online/api/upload \
  -F "file=@anything.csv" -F "mode=TV"   # 201 + session_id
curl -X POST .../api/training/start -d '{"session_id":"...","max_epochs":2050}'
```
**Fix recommandé** : ajouter `current_user: Annotated[UserRecord, Depends(get_current_user)]` à **chaque** signature de route métier, puis stocker `user_id` dans la `Session` à la création (`session_manager.create_session(mode, owner_id=user.user_id)`) et vérifier l'ownership dans `get_session` ou dans une dépendance dédiée `require_session_owner`.
**Effort** : M (≈ 2 h, ~30 endpoints).

---

### [P0-2] Désérialisation Pickle non sécurisée depuis Redis (RCE)

**Fichier** : `apps/api/app/session.py:246-249` (`_deserialize_value` → `pickle.loads`), production via `_RedisDataProxy` chargeant n'importe quelle clé `mdl:sdata:*` ; serializer fallback `apps/api/app/session.py:238-242`.
**Description** : Toute valeur Redis préfixée `__DFPKL__` est dépicklée. Si Redis est compromis, mal configuré (bind 0.0.0.0 sans password, c'est le cas par défaut dans `infra/docker-compose.yml:1-13`), ou si une faille d'injection de clé existe, un attaquant écrit `SET mdl:sdata:<sid>:raw_df "__DFPKL__<payload pickle malicieux>"` puis déclenche n'importe quelle route qui lit `raw_df` (mapping/auto, training, carte/generate) → **RCE comme l'utilisateur du process API**.
**Impact** : RCE complète sur l'host Oracle Cloud, accès au filesystem (modèles, autres sessions), pivot réseau.
**Exploitation** : si Redis port 6379 atteignable (compose expose `6379:6379` sur l'hôte par défaut → publié sur Internet sur Oracle Cloud Always Free si pas de firewall) :
```bash
redis-cli -h target -x SET mdl:sdata:abc:raw_df < pickle_payload.bin
curl https://.../api/mapping/auto -d '{"session_id":"abc"}'
```
**Fix recommandé** :
1. Supprimer le fallback Pickle : sérialiser les `DataFrame` problématiques en Parquet après cast geometry→str (déjà tenté dans `mapping.py:256-259`), sinon JSON.
2. Si Pickle indispensable, signer chaque blob avec HMAC-SHA256 sur `JWT_SECRET` : `__DFPKL__<hmac><payload>` ; refuser tout blob non signé.
3. Bind Redis sur `127.0.0.1` uniquement, ajouter `requirepass`, ne pas exposer le port en compose prod.
**Effort** : S (signer) ou M (supprimer pickle).

---

### [P0-3] JWT_SECRET en dur dans le repo + défauts triviaux

**Fichiers** :
- `.env.production:9` : `JWT_SECRET=54dc5a32a784bc109f203087d453ab43391bc77aa9b2789f7777026c6e8a6b09` (en clair, non tracké git mais présent sur disque dev).
- `apps/api/app/config.py:53` : default `"change-me-in-production-use-a-real-secret"`.
- `infra/docker-compose.yml:40,65` : `JWT_SECRET=${JWT_SECRET:-change-me-in-production}` (fallback prod identique).

**Description** : Si la variable env n'est pas définie en prod, le secret tombe sur la chaîne publique → forge de JWT triviale. Le secret de `.env.production` est probablement réutilisé sur Oracle Cloud ; toute fuite (backup, log, partage écran) compromet tous les comptes.
**Impact** : Forge de tokens, impersonation de n'importe quel `user_id`. Si combiné avec un futur déploiement d'auth (cf. P0-1), bypass complet.
**Exploitation** :
```python
from jose import jwt
jwt.encode({"sub": "any_user_id_hex32", "email": "x@y"}, "change-me-in-production", "HS256")
```
**Fix recommandé** :
1. Refuser de démarrer si `JWT_SECRET` est vide, vaut un default, ou fait moins de 32 octets aléatoires — `pydantic_settings` + `field_validator`.
2. Régénérer un secret unique par déploiement via `openssl rand -hex 32`, le stocker dans le secret manager d'Oracle Cloud (ou variable d'environnement Systemd avec mode 600), **jamais** dans un fichier `.env.production` qui dort sur le poste dev.
3. Purger le secret actuel de l'historique git si jamais commité (`git log --all -p .env.production`).
**Effort** : XS.

---

### [P1-1] Path traversal : `model_dir`, `output_dir`, `dir` non validés

**Fichiers** :
- `apps/api/app/routers/evaluation.py:1195` (`Path(body.model_dir) / body.model_name` → `_load_model_from_dir`).
- `apps/api/app/routers/evaluation.py:1461` (`download-model` : `Path(model_dir) / model_name` → `rglob("*")` puis stream zip).
- `apps/api/app/routers/carte.py:441,446` (`_load_model(body.model_tv_dir)` ; `model_pl_dir` idem ; `validate-model` à la ligne 277).
- `apps/api/app/routers/export.py:89-101` (`output_dir` lu de la session mais `out_path.rglob("*")` sans clamp `WORKSPACE_ROOT`).
- `apps/api/app/routers/models.py:128` : `validate_path(dir)` **appelé sans `allowed_root`** → root = `WORKSPACE_ROOT` ; OK pour ce point précis, mais le code aurait dû passer `allowed_root=str(WORKSPACE_ROOT/session_id)` pour l'isolation par session.

**Description** : Aucun de ces handlers n'appelle `security.validate_path`. Un attaquant non authentifié (cf. P0-1) peut lire/zip n'importe quel répertoire lisible par l'utilisateur Docker :
```bash
curl "https://.../api/evaluation/download-model?model_dir=/etc&model_name=ssh"
curl -X POST .../api/carte/validate-model -d '{"model_dir":"/proc/self/environ"}'
```
Le ZIP retourné contient tous les fichiers récursifs (clefs SSH, JWT secret de `.env`, secrets cloud-init Oracle, etc.).
**Impact** : Exfiltration complète du filesystem accessible à l'API (R), pivotage cloud.
**Fix recommandé** : envelopper chaque path d'entrée :
```python
from ..security import validate_path
session_root = Path(settings.WORKSPACE_ROOT) / session_id
safe = validate_path(body.model_dir, allowed_root=str(session_root))
```
Forcer aussi côté `/api/models/list` que `dir` reste sous `WORKSPACE_ROOT/{session_id}/`.
**Effort** : S.

---

### [P1-2] Pas d'isolation multi-tenant : la `session_id` est l'unique secret d'accès

**Fichiers** : `apps/api/app/session.py:84` (sid = `uuid.uuid4().hex`, 122 bits OK en entropie) ; consommée brute par tous les endpoints (`upload.py:189`, `training.py:719`, `models.py:153`, etc.) ; `WORKSPACE_ROOT/{session_id}/models` sur disque (`models.py:106-109`) sans ACL par utilisateur.
**Description** : Sans auth (P0-1), il suffit de connaître/deviner une `session_id` pour lire raw_df, learning_df, modèles entraînés d'un autre. Même après correction P0-1, si un user A obtient l'sid d'un user B (via support log, copier-coller, lien partagé, request-ID inutilement exposé `X-Request-ID` en header), il peut accéder à toutes les données de B. C'est un IDOR systémique.
**Impact** : Confidentialité des données métier (modèles entraînés = propriété intellectuelle, datasets routiers parfois sensibles).
**Fix recommandé** :
1. Stocker `owner_user_id` dans `Session`, refuser tout accès si `session.owner_user_id != current_user.user_id` dans une dépendance commune `get_owned_session(session_id, current_user)`.
2. Ne **jamais** logger une session_id complète en clair (actuellement `session.py:88,99,264` etc. le font — log injection mineure).
3. Préfixer aussi les paths disque par `user_id` : `WORKSPACE_ROOT/{user_id}/{session_id}/models`.
**Effort** : M.

---

### [P1-3] Rate-limit déclaratif mais non appliqué + DoS training

**Fichiers** :
- `apps/api/app/main.py:30` : `Limiter(default_limits=["200/minute"])`.
- Aucune décoration `@limiter.limit(...)` n'existe sur les routes (grep vide).
- `apps/api/app/routers/training.py:763` : un POST = un `threading.Thread` natif, pas de queue, pas de cap (`MAX_CONCURRENT_TRAININGS` absent), `MAX_TRAINING_MINUTES` configurée mais **jamais vérifiée** dans `_training_worker`.
- Grid combinatoire `_build_combinations` (`training.py:191-243`) : produit cartésien `feature_subsets × activations × learning_rates × min_nb_epochs × losses × dropouts × neurons_factors × batch_sizes`. Avec `feature_subset_grid=True` et 6 features optionnelles, on a 2^6 = 64 subsets × axes ≈ **plusieurs centaines à milliers** de modèles, chacun jusqu'à `max_epochs=2050`.

**Description** :
- Le `default_limits` slowapi n'est en réalité pas effectif tant qu'il n'y a pas de décorateur (FastAPI ignore le default sans rate-limit middleware ASGI). `register`/`login` ne sont pas protégés → bruteforce mots de passe et énumération users (cf. P2-1).
- N'importe quel client peut lancer 10 trainings parallèles, chacun avec 1000 combinaisons : saturation du CPU 2-core Oracle Always Free en quelques minutes, OOM (chaque copie de DataFrame en mémoire).

**Impact** : DoS bon marché (10 lignes curl), perte de service.
**Fix recommandé** :
1. Décorer explicitement `/api/auth/login` (`5/minute` par IP), `/api/auth/register` (`3/hour`), `/api/upload` (`10/minute`), `/api/training/start` (`2/hour par user`).
2. Cap dur côté serveur : `total_pending > MAX_GRID_SIZE (e.g. 200)` → 400 Bad Request avant de lancer le thread.
3. Pool unique `concurrent.futures.ThreadPoolExecutor(max_workers=1)` partagé pour tous les trainings.
4. Implémenter réellement `MAX_TRAINING_MINUTES` via deadline absolue testée à chaque epoch via le `GridProgressCallback`.
**Effort** : S à M.

---

### [P2-1] Énumération d'utilisateurs via différence de réponse login/register

**Fichier** : `apps/api/app/auth.py:236` (register → 409 « Un compte avec cet email existe deja ») vs `auth.py:245` (login → 401 « Email ou mot de passe incorrect » uniforme — celui-ci est OK).
**Description** : Le 409 explicite à `/register` permet de tester l'existence d'un email. Sans rate-limit (cf. P1-3), un dump rapide est possible.
**Impact** : Préparation de campagnes de phishing ciblées.
**Fix recommandé** : retourner toujours 201 avec un message générique « Si l'email est valide, un compte sera créé… », ou exiger un email de validation avant activation. À défaut, rate-limit strict `3/hour/IP` et logging des tentatives.
**Effort** : XS.

---

### [P2-2] Headers de sécurité absents (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)

**Fichiers** : `apps/api/app/main.py` (aucun middleware d'injection de headers) ; `infra/nginx.conf:14-31` (proxy nu, pas d'`add_header`).
**Description** : Réponses JSON et HTML (rapport d'évaluation `/api/evaluation/report/{session_id}`) servies sans aucun header de sécurité. Le rapport HTML inclut du **contenu généré côté serveur à partir de DataFrame user-controlled** (colonnes `PTM_ID`, `Identifiant`, etc., utilisées dans des `f-string` Plotly et HTML sans échappement systématique — cf. `evaluation.py:265,378-385`). XSS stockée possible si un attaquant uploade un CSV avec `<script>` dans une cellule.
**Impact** : XSS via rapport, clickjacking, sniffing MIME, fuite référer cross-site.
**Fix recommandé** : middleware FastAPI ajoutant :
```
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self' cdn.plot.ly cdn.datatables.net code.jquery.com 'unsafe-inline'; img-src 'self' data: *.openstreetmap.org *.cartocdn.com; frame-src 'none'
```
Idem dans `nginx.conf`. Échapper toutes les valeurs CSV dans le rapport (`html.escape`).
**Effort** : XS pour les headers, S pour l'échappement systématique.

---

### [P3-1] Stack-traces et détails internes leakés en réponse

**Fichier** : `apps/api/app/main.py:128-132` (handler global : `detail=f"Erreur interne: {type(exc).__name__}: {exc}"`).
**Description** : Toute exception non gérée fuit la classe et le message Python (chemins de fichiers, noms de colonnes, parfois adresses Redis). Combiné avec l'API non auth (P0-1), c'est une mine d'or pour reconnaissance.
**Impact** : Information disclosure.
**Fix recommandé** : log côté serveur, renvoyer un détail générique avec request_id : `{"detail": "internal error", "request_id": "..."}` ; activer Sentry pour le debug.
**Effort** : XS.

---

### [P3-2] `/health` leake la version et `active_sessions`, `/metrics` Prometheus public, `/docs` exposé par défaut

**Fichiers** :
- `apps/api/app/main.py:190-196` : `/health` renvoie `"version": "2.0.0-preview-fix-v2"` + nombre de sessions actives → fingerprint + side-channel d'activité.
- `apps/api/app/main.py:156` : `Instrumentator().expose(app, include_in_schema=False)` → `/metrics` accessible sans auth (utile à un attaquant pour profiler le CPU pendant un DoS).
- `FastAPI(...)` sans `docs_url=None` → `/docs` et `/openapi.json` exposent toute la surface API.

**Impact** : Reconnaissance facilitée.
**Fix recommandé** : `/health` minimal `{"status":"ok"}` (ne pas exposer la version ni le compteur sessions) ; protéger `/metrics` par Basic-Auth nginx ou IP-allowlist ; en prod `app = FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)` ou même chose derrière un flag `ENVIRONMENT != "production"`.
**Effort** : XS.

---

### [Notes complémentaires — risques modérés non comptés P0-P3]

- **Bcrypt** : `bcrypt.gensalt()` par défaut = 12 rounds, correct.
- **Pas de revocation JWT** : token de 24 h sans liste de tokens révoqués (`auth.py:42`). Pas de `/logout` côté serveur. Acceptable pour 5-10 utilisateurs internes mais à documenter.
- **CORS** strict OK (`main.py:139-146`), `allow_credentials=True` couplé à `allow_origins` explicite — bonne posture.
- **Zip bomb** : `_check_zip_bomb` (`upload.py:26-38`) limite à 1 GB décompressé — correct, mais ne couvre pas les bombes imbriquées (zip-in-zip). Acceptable.
- **Shapefile via geopandas** (`upload.py:106-128`) : `tempfile.TemporaryDirectory` + `extractall` sans filtrage = risque path-traversal mineur (les chemins relatifs malicieux iront dans le tmpdir éphémère, donc bornés). À tracer si jamais on persiste.
- **Pas d'antivirus** sur uploads — acceptable pour usage interne, à mentionner.
- **`request_id` propagé via header `x-request-id` accepté du client** (`logging_config.py:96-97`) — risque mineur de log injection si client met un saut de ligne ; pas d'impact critique mais à sanitizer.
- **Logs** : structurés JSON, bonne base ; mais ils incluent `body.email` (`auth.py:237,250`) et `session_id` complet — RGPD léger, attention.

## Checklist OWASP Top 10 (2021)

| Item | Statut | Commentaire |
|---|---|---|
| A01 Broken Access Control | **KO** | Aucun endpoint métier protégé, IDOR systémique (P0-1, P1-2) |
| A02 Cryptographic Failures | **KO** | JWT_SECRET défaut + versionné (P0-3), pas de HSTS (P2-2) |
| A03 Injection | OK (partiel) | Pas de SQL ni subprocess ; mais XSS rapport HTML possible (P2-2) |
| A04 Insecure Design | KO | Multi-tenant sans owner check par design (P1-2) |
| A05 Security Misconfiguration | KO | `/docs`, `/metrics`, `/health` verbose, Redis exposé compose, headers manquants (P3-2, P2-2) |
| A06 Vulnerable Components | N/A audit visuel | TF 2.15-2.22 OK, jose 3.3+ OK ; `passlib[bcrypt]>=1.7` (deprecated mais bcrypt direct utilisé), à `pip-audit` |
| A07 Identification / Auth Failures | KO | Énumération users (P2-1), pas de rate-limit login (P1-3) |
| A08 Software & Data Integrity Failures | **KO** | Pickle non signé depuis Redis (P0-2) |
| A09 Security Logging & Monitoring | OK (partiel) | JSON structuré, Sentry optionnel ; manque détection bruteforce |
| A10 SSRF | N/A | Pas de fetch outbound piloté par user |

## Recommandations d'architecture sécurité

1. **Imposer l'auth via dépendance globale** plutôt que par endpoint. Définir `protected_router = APIRouter(dependencies=[Depends(get_current_user)])` et faire hériter tous les routers métier, sinon `app.include_router(..., dependencies=[Depends(get_current_user)])`. Une seule ligne, zéro endpoint oublié.

2. **Coupler `Session` à `user_id` au modèle de données.** Ajouter `owner_user_id: str` à `Session`, le persister dans Redis, et créer `get_owned_session(sid: str, user: UserRecord = Depends(get_current_user))` à utiliser partout où `session_manager.get_session(...)` est appelé. Cela supprime d'un coup l'IDOR et permet le partage volontaire futur (en passant `shared_with: list[str]`).

3. **Bannir Pickle, ou le signer.** Le cas `__DFPKL__` est un raccourci pour quelques DataFrame contenant des dicts geometry — il est plus propre de toujours caster `geometry` → str JSON avant Parquet (déjà fait dans `mapping.py:256`, à généraliser dans `_serialize_value`). Sinon HMAC-SHA256(`JWT_SECRET`) sur le payload Pickle et vérification à la désérialisation.

4. **Hardening déploiement Oracle Cloud** : firewall ingress autorisé seulement sur 443 (nginx TLS), Redis bind 127.0.0.1 + `requirepass`, Docker compose `expose` au lieu de `ports` pour Redis et API (seul nginx publie). Volume `/tmp/mdl_workdir` monté avec quota disque (cf. DoS stockage par upload répétés). Run l'API en user non-root (Dockerfile non audité ici mais à vérifier).

5. **Cap quantitatif et budget CPU sur le training**. Single-thread executor partagé (`ThreadPoolExecutor(max_workers=1)`), `MAX_GRID_COMBINATIONS=100` strict, deadline `MAX_TRAINING_MINUTES` réellement vérifié via callback `on_epoch_end` qui set `model.stop_training`. Ajouter une queue Celery (déjà installée mais non utilisée par `training.py`) pour découpler le worker du process API.
