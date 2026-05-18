# Audit infra / devops / ARM64 — MDL pour Oracle Cloud Always Free

Auditeur : DevOps/SRE senior — focus Docker prod, ARM64, CI/CD, Caddy, Oracle Cloud A1.
Cible : VM unique Oracle Cloud Always Free **Ampere A1** (4 OCPU / 24 GB RAM, Ubuntu 22.04 LTS aarch64), domaine `Trafic-Tool.anbri-tools-ia.online` (DNS Hostinger), équipe interne ~5-10 users, reverse proxy Caddy auto-TLS.

---

## Resume executif

**Note prepa prod : 6.5 / 10.** Le socle Docker est correct (multi-stage api/web, healthchecks, non-root, restart policies, volumes nommes) et le pipeline CI lint+test+build+push GHCR fonctionne. Mais le projet a **ete pense pour Railway** (Dockerfiles `*.railway` paralleles, script `deploy-railway.sh`, `railway.toml`, hardcoded `WORKSPACE_ROOT=/tmp/mdl_workdir` qui est inadapte a un volume persistant), et **plusieurs trous bloquants** restent pour un deploiement Oracle ARM64 auto-heberge avec domaine custom.

**3 blockers deploiement :**
1. **CI build single-arch (`linux/amd64` par defaut)** — `ci.yml:73-106` n'utilise pas `platforms: linux/arm64`. Pull sur A1 echouera ou exigera emulation QEMU lente. Faute d'images ARM64, soit on rebuild sur la VM (1ere build TF ~25-45 min), soit on bascule en buildx multi-arch.
2. **Job `deploy` est un `echo` commente (`ci.yml:116-123`)** — aucune mecanique de pull+restart sur la VM Oracle. Pas de webhook, pas de watchtower, pas de runner self-hosted.
3. **`JWT_SECRET` defaut `change-me-in-production` injecte par compose** (`docker-compose.yml:40,65` + `config.py:53`) — fail-open silencieux : si l'admin oublie d'exporter la var, l'API demarre avec un secret connu publiquement, tous les JWT sont forgeable.

**3 quick wins (< 4h chacun) :**
1. Switch `nginx.conf` -> `Caddyfile` : auto-TLS Let's Encrypt pour `Trafic-Tool.anbri-tools-ia.online`, supprime la gestion certbot manuelle, conserve SSE / body 500M / timeouts longs.
2. Ajouter `platforms: linux/amd64,linux/arm64` dans `docker/build-push-action@v5` + cache GHA scope par plateforme. Premier build ARM64 lent (~30 min QEMU), suivants ~3 min cache.
3. Fail-fast sur `JWT_SECRET` defaut : refuser le boot si valeur dans la liste noire (`change-me-*`, longueur < 32). Patch 5 lignes dans `config.py`.

**Verdict :** la stack est solide en local et CI-buildable, mais le **chemin Oracle ARM64 + auto-deploy + monitoring gratuit** demande ~2-3 jours de travail cible. Aucun blocker conceptuel — uniquement de la plomberie devops.

---

## Compatibilite ARM64 — tableau par dependance

Verifie a partir de `apps/api/pyproject.toml:5-33` et de la connaissance des wheels `manylinux2014_aarch64` publiees sur PyPI.

| Dependance | Version contrainte | Wheel ARM64 dispo ? | Detail / action |
|---|---|---|---|
| **tensorflow-cpu** | `>=2.15,<2.22` | OUI depuis 2.16 | `tensorflow-cpu-aarch64` n'existe **pas** sur PyPI ; le paquet `tensorflow` a partir de **2.16** publie un wheel `linux_aarch64` natif (CPU). Pour 2.15 il faut le wheel ARM via Linaro (`https://snapshots.linaro.org/...`) ou monter a 2.16+. **Recommandation : pin `tensorflow-cpu>=2.16,<2.20` et tester en CI ARM.** Sinon fallback `tensorflow==2.16.1` plain (CPU par defaut sans CUDA). |
| **numpy** | `>=1.24` | OUI | Wheels ARM64 depuis ~1.21. Aucune action. |
| **pandas** | `>=2.1` | OUI | Wheels ARM64 natifs depuis 2.0. RAS. |
| **scipy** | `>=1.11` | OUI | Wheels ARM64 manylinux depuis 1.10. RAS. |
| **scikit-learn** | `>=1.3` | OUI | Wheels ARM64 depuis 1.2. RAS. |
| **geopandas** | `>=0.14` | OUI (Python pur) | Lui-meme pure Python. Depends de fiona/shapely/pyproj. |
| **shapely** | transitif | OUI | Wheels ARM64 depuis 2.0 (`libgeos` embarque). RAS. |
| **fiona** | transitif | OUI | Wheels ARM64 depuis 1.9 (`libgdal` embarque). RAS. |
| **pyproj** | transitif | OUI | Wheels ARM64 depuis 3.4. RAS. |
| **rtree** | transitif | OUI | Wheels ARM64 depuis 1.0 (`libspatialindex`). RAS. |
| **pyarrow** | `>=14.0` | OUI | Wheels ARM64 depuis 10.0. Tres bien sur A1 (Arrow optimise aarch64). RAS. |
| **bcrypt** | `>=4.0` | OUI | bcrypt 4.x publie wheels ARM64 manylinux. RAS. |
| **cffi** | transitif | OUI | Wheels ARM64 depuis 1.15. RAS. |
| **python-jose[cryptography]** | `>=3.3` | OUI | `cryptography` publie wheels ARM64 depuis 3.4. RAS. |
| **redis** | `>=5.0` | OUI (pure Python) | RAS. |
| **celery[redis]** | `>=5.3` | OUI (pure Python) | Worker actuellement casse (cf audit applicatif), a supprimer du compose. |
| **sentry-sdk[fastapi]** | `>=1.40` | OUI (pure Python) | RAS. |
| **slowapi / prometheus-fastapi-instrumentator** | — | OUI (pure Python) | RAS. |
| **gdal-bin / libgdal-dev (system)** | apt | OUI Ubuntu 22.04 arm64 | `Dockerfile.api:5` installe via apt sur python:3.11-slim. Slim est multi-arch. **Mais `libgdal32` runtime n'existe que sur Debian bookworm** : python:3.11-slim base bookworm depuis fin 2023, OK. |
| **node:20-alpine** | base web | OUI natif | Image multi-arch officielle Docker Hub, tag `arm64v8` auto-selectionne. RAS. |
| **redis:7-alpine** | base | OUI natif | RAS. |

**Synthese ARM64 : 0 dependance ne necessite de build from source.** Seul point d'attention : tensorflow-cpu — verifier que `pip install tensorflow-cpu==2.16.1` sur aarch64 reussit, sinon basculer sur `tensorflow==2.16.1` (meme code, juste sans le suffixe `-cpu` qui n'est plus publie pour ARM64 sur certaines versions).

---

## Findings infra / devops

### P0 — bloquants deploiement Oracle ARM64

**P0-1. CI ne produit pas d'image ARM64**
Path : `.github/workflows/ci.yml:73-106`
Les trois `docker/build-push-action@v5` n'ont pas de `platforms:`. Build par defaut = host runner = `linux/amd64`. Pull sur Ampere A1 echouera (`no matching manifest for linux/arm64/v8`) ou Docker tirera l'image x86 et la fera tourner en emulation QEMU (TF en emulation = inutilisable, 10x plus lent).
**Fix :**
```yaml
- uses: docker/setup-qemu-action@v3
- uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64
    cache-from: type=gha,scope=api-${{ matrix.arch }}
    cache-to: type=gha,mode=max,scope=api-${{ matrix.arch }}
```
Premier build ARM64 ~30 min via QEMU, ensuite cache GHA -> ~3 min. Alternative plus rapide : runner ARM natif GitHub-hosted (`ubuntu-24.04-arm`, GA depuis 2025).

**P0-2. Pas d'auto-deploy sur la VM Oracle**
Path : `.github/workflows/ci.yml:108-123`
Job `deploy` ne fait que `echo`. Aucun mecanisme pour pousser le nouveau tag sur la VM.
**3 options classees par effort/fiabilite :**
1. **SSH + docker compose pull** (recommande, simple) : ajouter dans le step `ssh -i $KEY $USER@$HOST "cd /opt/mdl && git pull && docker compose pull && docker compose up -d"`. Necessite secret `ORACLE_SSH_KEY` + `ORACLE_HOST` + IP fixe ou DDNS. Atomic via tag SHA dans compose : `image: ghcr.io/${REPO}/api:${SHA}`.
2. **Watchtower** : conteneur qui polle GHCR toutes les 5 min et restart si nouveau tag `:latest`. Zero config, mais pas de controle deploiement (chaque merge main = prod, dangereux).
3. **GitHub Actions self-hosted runner sur la VM** : runner local execute le `docker compose pull/up -d`. Plus de SSH, mais ajoute un demon GH sur la VM (surface d'attaque). A reserver si plusieurs VM.

**P0-3. `JWT_SECRET` defaut fail-open**
Paths : `docker-compose.yml:40,65` + `apps/api/app/config.py:53`.
Le fallback `${JWT_SECRET:-change-me-in-production}` fait demarrer l'API meme sans secret. Combine au defaut `change-me-in-production-use-a-real-secret` dans `config.py:53`, tout JWT signe avec ce secret connu est forgeable par n'importe qui.
**Fix :**
```python
# config.py
@field_validator("JWT_SECRET")
@classmethod
def _reject_default_secret(cls, v: str) -> str:
    if "change-me" in v.lower() or len(v) < 32:
        raise ValueError("JWT_SECRET must be set to a strong random value (>=32 chars)")
    return v
```
Et dans `docker-compose.yml` supprimer le fallback : `JWT_SECRET=${JWT_SECRET:?JWT_SECRET is required}`.

**P0-4. `.env.production` contient un vrai secret en clair sur disque**
Path : `.env.production` (gitignored, OK pour Git, mais present localement avec `JWT_SECRET=54dc5a32...`).
Non-bloquant pour le repo mais signal d'alarme operationnel : ce secret doit etre rote avant le 1er deploiement reel, gere via Oracle Vault ou docker secrets, jamais commit ni laisse trainer sur la machine de dev. Recommander `pre-commit` gitleaks pour detecter futurs leaks.

**P0-5. `WORKSPACE_ROOT=/tmp/mdl_workdir` n'est pas persistant**
Paths : `docker-compose.yml:43,66`, `Dockerfile.api:28`, `Dockerfile.worker:29`, `apps/api/app/config.py:47`.
`/tmp` sur Linux peut etre purgee a tout moment (systemd-tmpfiles, redemarrage). Le volume nomme `tmp_data` masque le probleme **a l'interieur du conteneur**, mais le nommage induit en erreur : `/tmp` suggere "ephemere". Sur Oracle A1, dedier un block volume separe pour `/data` (100 GB free).
**Fix compose Oracle :**
```yaml
volumes:
  mdl_models:
    driver_opts:
      type: none
      o: bind
      device: /data/mdl_workdir
```
+ changer defaut `WORKSPACE_ROOT=/data/mdl_workdir` dans `config.py:47` et Dockerfile.

---

### P1 — gaps importants mais non-bloquants

**P1-1. Worker Celery casse mais toujours dans compose**
Paths : `docker-compose.yml:56-72`, `Dockerfile.worker`.
Selon contexte mission, le worker est "casse, a virer". Garder un service qui crashloop pollue les logs, consomme RAM, et complique le debug. **Action : supprimer le service `worker` du compose + supprimer `Dockerfile.worker` + retirer celery de pyproject.toml (sauf si tasks.py les utilise encore — verifier).**

**P1-2. Doublons Dockerfile.{api,web}.railway**
Paths : `infra/Dockerfile.api.railway`, `infra/Dockerfile.web.railway`, `scripts/deploy-railway.sh`, `railway.toml`.
Auteur a teste Railway puis pivote vers Oracle. Ces fichiers sont morts : Dockerfile.api.railway est mono-stage (image plus grosse), n'utilise pas `--prefix=/install`, `WORKSPACE_ROOT` divergent (`/data/mdl_workdir` vs `/tmp/mdl_workdir` dans le mainstream). **Action : `git rm infra/Dockerfile.{api,web}.railway scripts/deploy-railway.sh railway.toml`** une fois la decision Oracle confirmee.

**P1-3. Aucun pinning par SHA des images de base**
Paths : `Dockerfile.api:2,13`, `Dockerfile.web:2,8,16`, `docker-compose.yml:3,75`.
`python:3.11-slim`, `node:20-alpine`, `redis:7-alpine`, `nginx:alpine` = tags mouvants. Reproductibilite faible, surface supply-chain. **Fix :** pin par digest `python:3.11-slim@sha256:abc...`. Renovate/Dependabot peut bump automatiquement.

**P1-4. Pas de tests frontend en CI**
Path : `.github/workflows/ci.yml:23-31`.
Job `lint-frontend` lance seulement `eslint`. Pas de Vitest/Jest/Playwright. Aucun test des composants critiques (forms upload, mapping, training stream). Gap qualite reconnu, prioritaire si l'equipe grandit.

**P1-5. Pas de scan SAST / vulnerabilites**
- Pas de CodeQL (gratuit pour repos publics).
- Pas de Trivy/Snyk sur images Docker.
- Pas de `pip-audit` ni `npm audit` en CI.
**Fix minimal :** ajouter step `trivy image --severity HIGH,CRITICAL --exit-code 1 ghcr.io/.../api:${SHA}` apres build. Plus `actions/dependency-review-action` sur PR.

**P1-6. Pas de Dependabot**
Aucun `.github/dependabot.yml`. Manque update auto pyproject.toml, package.json, github-actions, docker. Surface CVE qui s'accumule. Quick win 5 min.

**P1-7. `/metrics` non protege**
Path : `apps/api/app/main.py:150-156`.
`Instrumentator().expose(app)` rend `/metrics` accessible sans auth. Sur internet, ca leak des informations (endpoints, latences, codes erreur). **Fix Caddy :** restreindre par IP ou ajouter basic auth, ou IP allowlist Prometheus scraper.
```caddy
handle /metrics {
  @prometheus remote_ip 10.0.0.0/8 127.0.0.1
  reverse_proxy @prometheus api:8000
  respond 403
}
```

**P1-8. nginx perd des proxy headers pour la route `/`**
Path : `infra/nginx.conf:48-54`.
Le `location /` (frontend) omet `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`. Next.js peut mal generer les URLs absolues, et les middlewares CORS/rate-limit cote API verront l'IP nginx au lieu du client. Caddy le fera correctement par defaut (`X-Forwarded-*` auto).

**P1-9. Build cache GHA sans scope**
Path : `.github/workflows/ci.yml:81-82,93-94,105-106`.
`cache-from: type=gha` et `cache-to: type=gha,mode=max` sur les 3 jobs partagent le meme scope -> collisions. Avec multi-arch, ca empire. **Fix :** `scope=api`, `scope=web`, `scope=worker` (ou `scope=${{ matrix.image }}`).

**P1-10. Pre-commit incomplet**
Path : `.pre-commit-config.yaml`.
Manque cote backend : `mypy` n'est pas en hook (mais en dependency dev). Manque cote frontend : `eslint --fix` + `prettier` sur `apps/web/**`. Manque secret-scan : ajouter `gitleaks` :
```yaml
- repo: https://github.com/gitleaks/gitleaks
  rev: v8.21.0
  hooks: [{id: gitleaks}]
```

---

### P2 — ameliorations

- **P2-1.** `apt-get install` dans Dockerfile.api builder + runtime duplique le code apt. Extraire un script `install-system-deps.sh` ou utiliser BuildKit `RUN --mount=type=cache,target=/var/cache/apt`.
- **P2-2.** Aucun label OCI sur les images (`org.opencontainers.image.{source,revision,created}`). Utile pour tracer en prod. `docker/metadata-action@v5` les genere auto.
- **P2-3.** `Dockerfile.web` fait `npm ci --omit=dev` en deps puis copie le code complet — devrait aussi exclure les `.next/` et `node_modules/` via `.dockerignore` (`.dockerignore` ligne 2 a `.next` mais pas `apps/web/.next` explicitement, OK le glob marche).
- **P2-4.** `Dockerfile.api.railway:28` utilise `--workers 2` pour uvicorn alors que `Dockerfile.api:36` n'a qu'un seul worker. Sur A1 4 vCPU, **2-4 workers** uvicorn est le bon compromis (TF garde du C++ thread-parallelism dedans).
- **P2-5.** `next.config.ts:3` defaut `http://localhost:8001` — incoherent avec `docker-compose.yml:22` qui passe `:8000`. Fonctionne car la var d'env ecrase, mais incoherence a corriger.
- **P2-6.** Pas de gestion de log rotation cote conteneurs. Sur Oracle, configurer `daemon.json` avec `"log-driver": "json-file", "log-opts": {"max-size":"50m","max-file":"5"}`.
- **P2-7.** Pas de `restart: unless-stopped` sur le worker (deja `unless-stopped`, OK), mais aucune politique max retry (Docker boucle infiniment si crashloop). Ajouter `restart: on-failure:5`.

---

## Stack monitoring / backups gratuit — recommandation

### Monitoring (cible ~5-10 users, budget 0 EUR)

| Couche | Outil | Free tier | Pourquoi |
|---|---|---|---|
| **Crash reporting** | Sentry SaaS | 5 000 errors / mois, 1 user | SDK deja integre (`main.py:57-72`). Suffisant pour 5-10 users. Self-hosted Sentry mange 8 GB RAM = mauvais sur A1. |
| **Uptime / healthcheck externe** | Healthchecks.io | 20 checks free | Ping `/health` toutes les 5 min. Alerte mail/Slack si down 2 minutes. Indispensable car Oracle peut redemarrer la VM. |
| **Metriques + dashboards** | Grafana Cloud free | 10 k series Prometheus, 50 GB logs, 14j retention | Scrape `/metrics` via Grafana Agent installe sur la VM. Dashboard FastAPI public dispo. **Alternative plus simple :** Netdata Cloud free (5 nodes, dashboards out-of-the-box). |
| **Logs centralises** | Grafana Loki via Grafana Cloud | 50 GB ingest / mois | Promtail sur la VM tail `docker logs`. Sinon, garder log JSON local + `journalctl` suffit pour 5-10 users. |
| **Traces** | (skip) | — | OpenTelemetry pas necessaire a ce stade. Re-evaluer si > 50 users. |

**Recommandation pragmatique pour MVP :** Sentry + Healthchecks.io + dashboards Grafana Cloud free **uniquement si necessaire** (sinon `docker stats` + logs JSON suffisent au demarrage).

### Backups

| Cible | Solution | Cout | Strategie |
|---|---|---|---|
| **Volume `mdl_models` (modeles + datasets sessions)** | Oracle Object Storage + `rclone` | 10 GB free | Cron quotidien `tar.gz` du volume -> upload chiffre OCI bucket. Retention 7 dailies + 4 weeklies. |
| **Volume `redis_data`** | Snapshot `BGSAVE` + copie locale | 0 EUR | Faible criticite (sessions = 2h TTL). `BGSAVE` toutes les 6h sur 2eme block volume. |
| **Code + config** | Git remote (GitHub) | 0 EUR | Deja en place. Ajouter export `.env` (chiffre gpg) en gist prive. |
| **Block volume Oracle** | OCI Volume Backup Policy | Free pour Always Free block volumes | Activer policy "Bronze" : daily snapshot, retention 7j. **Gratuit jusqu'a 200 GB total Always Free.** |

**Cron backup** (a placer dans `/etc/cron.d/mdl-backup`) :
```cron
# Backup modeles vers OCI Object Storage tous les jours a 3h
0 3 * * * root /usr/local/bin/mdl-backup.sh >> /var/log/mdl-backup.log 2>&1
```
Avec `mdl-backup.sh` qui fait `docker run --rm -v mdl_models:/data alpine tar czf - /data | rclone rcat oci:mdl-backups/$(date +%F).tar.gz`.

### Anti-resiliation Oracle Always Free

Oracle reclame des comptes "inactifs" (zero traffic 7 jours). Cron mensuel de keepalive :
```cron
# Keepalive Oracle Always Free — petite charge CPU mensuelle
0 12 1 * * root stress-ng --cpu 1 --timeout 60s > /dev/null 2>&1
```
Le simple fait que la VM serve du HTTPS public via Caddy suffit deja (Let's Encrypt renewal toutes les 60j, healthchecks externes), mais le cron est une ceinture-bretelles.

---

## Caddyfile cible — snippet production

A placer dans `infra/Caddyfile`, monte en `:ro` sur `/etc/caddy/Caddyfile` dans le service Caddy du compose.

```caddy
{
    email admin@anbri-tools-ia.online
    # Optionnel : staging Let's Encrypt pendant tests
    # acme_ca https://acme-staging-v02.api.letsencrypt.org/directory
    servers {
        timeouts {
            read_body   10m
            read_header 30s
            write       1h
            idle        2m
        }
    }
}

Trafic-Tool.anbri-tools-ia.online {
    # Compression
    encode zstd gzip

    # Headers de securite
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options    "nosniff"
        X-Frame-Options           "SAMEORIGIN"
        Referrer-Policy           "strict-origin-when-cross-origin"
        Permissions-Policy        "geolocation=(), microphone=(), camera=()"
        # CSP minimal — adapter selon CDN front
        Content-Security-Policy   "default-src 'self'; img-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'"
        -Server
    }

    # Body 500M (uploads gros datasets)
    request_body {
        max_size 500MB
    }

    # SSE stream training — pas de buffering, timeouts longs
    @sse path /api/training/stream*
    reverse_proxy @sse api:8000 {
        flush_interval -1
        transport http {
            read_timeout  1h
            write_timeout 1h
        }
    }

    # API
    handle /api/* {
        reverse_proxy api:8000 {
            transport http {
                read_timeout  10m
                write_timeout 10m
            }
        }
    }

    # Healthcheck public (utile pour Healthchecks.io)
    handle /health {
        reverse_proxy api:8000
    }

    # Metrics — restreint LAN/loopback
    handle /metrics {
        @internal remote_ip 10.0.0.0/8 127.0.0.1/32
        reverse_proxy @internal api:8000
        respond 403
    }

    # Frontend Next.js (catch-all)
    handle {
        reverse_proxy web:3000
    }

    log {
        output file /var/log/caddy/access.log {
            roll_size 50mb
            roll_keep 5
        }
        format json
    }
}
```

**Compose entry Caddy** :
```yaml
caddy:
  image: caddy:2-alpine
  restart: unless-stopped
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./Caddyfile:/etc/caddy/Caddyfile:ro
    - caddy_data:/data
    - caddy_config:/config
    - caddy_logs:/var/log/caddy
  depends_on:
    api:
      condition: service_healthy
    web:
      condition: service_started
volumes:
  caddy_data:
  caddy_config:
  caddy_logs:
```

**Ce qu'on conserve vs `nginx.conf` actuel :**
- body 500M : `request_body max_size 500MB` (= `client_max_body_size 500M` ligne 16).
- SSE no-buffer : `flush_interval -1` (= `proxy_buffering off` ligne 43).
- Timeouts 1h : `read_timeout 1h` (= `proxy_read_timeout 3600s` ligne 28-29).
- X-Forwarded-* : auto par Caddy reverse_proxy.

**Ce qu'on gagne :** auto-TLS Let's Encrypt (zero cert manuel, renouvellement auto), HSTS + CSP par defaut, logs JSON natifs, hot-reload config sans restart.

---

## DNS Hostinger

Configuration A record cote Hostinger DNS :
```
Type: A
Name: Trafic-Tool
Value: <IP publique Oracle A1>
TTL: 3600
Proxy: off (Hostinger ne proxie pas, OK)
```
**Pas de CNAME** vers une URL Oracle — Always Free n'expose pas de nom DNS stable, prendre l'IP publique reservee de la VM. Caddy gere ACME HTTP-01 challenge sur port 80 -> ouvrir 80+443 dans Security List Oracle.

---

## Sizing Oracle A1 — 4 OCPU / 24 GB RAM

Reservation memoire estimee en regime nominal :

| Service | RAM idle | RAM pic | Note |
|---|---|---|---|
| api (uvicorn + TF) | ~600 MB | **8-14 GB** | TF charge le modele en RAM, batch training peut grimper. Limiter `MAX_TRAINING_MINUTES=60` aide. |
| web (Next.js standalone) | ~150 MB | ~400 MB | RSC + SSR Next 16, leger. |
| redis | ~30 MB | ~500 MB | Cache sessions + Celery broker (a degager si worker supprime). |
| caddy | ~30 MB | ~80 MB | Tres leger. |
| OS Ubuntu + monitoring | ~1.5 GB | ~2 GB | systemd, journald, Grafana Agent. |
| **Total nominal** | **~2.3 GB** | **~17 GB** | Marge ~7 GB libre, OK |

**Reco compose limits** (eviter qu'un service mange toute la RAM) :
```yaml
api:
  deploy:
    resources:
      limits:
        memory: 16G
        cpus: '3.0'
web:
  deploy:
    resources:
      limits:
        memory: 1G
redis:
  deploy:
    resources:
      limits:
        memory: 1G
```
**Attention :** `deploy.resources.limits` n'est honore par `docker compose up` qu'avec le mode swarm OU `compose v2 --compatibility`. Sinon utiliser `mem_limit:` / `cpus:` top-level (deprecated mais effectif). Pour A1 reel, plus simple : laisser sans limit, surveiller via `docker stats`.

CPU : 4 OCPU = 4 threads. Allouer 2 a uvicorn (`--workers 2`), 1 web, 0.5 redis+caddy, 0.5 OS. TF en intra-op respecte `TF_NUM_INTRAOP_THREADS` — pinner a 2 pour ne pas saturer.

---

## Runbook deploy — structure macro

Le runbook complet derive du plan P4 vague 2. Voici les phases macro :

### Phase 1 — preparation locale (J-3, ~2h)
1. Pinner `tensorflow-cpu>=2.16,<2.20`, supprimer fichiers Railway, supprimer service `worker`.
2. Fix `JWT_SECRET` fail-fast dans `config.py`.
3. Changer `WORKSPACE_ROOT` defaut -> `/data/mdl_workdir`.
4. Ajouter Caddyfile, retirer nginx.conf.
5. Mettre a jour `ci.yml` : multi-arch build + scopes cache.
6. Generer un vrai `JWT_SECRET` via `openssl rand -hex 32` et le stocker dans Bitwarden / pass / Oracle Vault.

### Phase 2 — bring-up VM Oracle (J-2, ~3h)
1. Creer compute instance Always Free Ampere A1 (Ubuntu 22.04 aarch64, 4 OCPU/24GB, 200 GB boot, reserve public IP).
2. Security List : autoriser 22, 80, 443.
3. SSH bootstrap : `ufw allow 22,80,443`, `apt install docker.io docker-compose-plugin`, ajouter user au groupe docker, configurer `daemon.json` log rotation.
4. Creer block volume 100 GB, attacher `/dev/oracleoci/oraclevdb`, mkfs.ext4, mount `/data` via `/etc/fstab`, mkdir `/data/mdl_workdir`.
5. Configurer DNS Hostinger A record vers IP publique, verifier `dig`.

### Phase 3 — deploiement initial (J-1, ~2h)
1. Sur VM : `git clone` repo (ou rsync tarball release).
2. Creer `/opt/mdl/.env` avec `JWT_SECRET`, `SENTRY_DSN`, `CORS_ORIGINS`, `WORKSPACE_ROOT=/data/mdl_workdir`.
3. `docker login ghcr.io` (PAT read:packages).
4. `docker compose --profile prod pull` (recupere ARM64 si CI a publie correctement).
5. `docker compose --profile prod up -d`.
6. Verifier `curl https://Trafic-Tool.anbri-tools-ia.online/health` -> 200.
7. Verifier cert Let's Encrypt valide (`curl -vI`).
8. Creer admin user via `/register` puis demote API endpoint.

### Phase 4 — observabilite + backups (J0, ~2h)
1. Brancher Sentry DSN (creer projet sentry.io free).
2. Brancher Healthchecks.io : creer check, mettre URL ping dans cron VM `*/5 * * * * curl -fsS https://hc-ping.com/UUID`.
3. Installer Grafana Agent ou Netdata (optionnel).
4. Installer `mdl-backup.sh` + cron + rclone OCI Object Storage.
5. Activer Block Volume Backup Policy Bronze.
6. Ajouter cron keepalive Oracle.

### Phase 5 — auto-deploy CI -> VM (J+1, ~1h)
1. Generer cle SSH dediee `ed25519` pour deploy, ajouter pubkey sur VM (`~/.ssh/authorized_keys` avec `command="cd /opt/mdl && git pull && docker compose pull && docker compose up -d"` pour restriction).
2. Ajouter secrets GitHub : `ORACLE_SSH_KEY`, `ORACLE_HOST`, `ORACLE_USER`.
3. Reactiver job `deploy` dans `ci.yml` avec `appleboy/ssh-action@v1` ou `webfactory/ssh-agent@v0.9`.
4. Smoke test : merge bidon sur main, verifier deploy auto.

### Phase 6 — durcissement post-launch (J+7)
1. fail2ban sur SSH.
2. Audit logs nginx/caddy hebdo.
3. Premier restore-test des backups (le seul backup teste est un backup qui marche).
4. Documenter le runbook complet (DR, incident response, on-call).

---

## Synthese chiffres

- **Findings :** 5 P0 (deploiement bloque sans correction), 10 P1, 7 P2.
- **Effort ARM64 :** ~4h CI multi-arch + 30 min test wheels TF + 0h sur autres deps (toutes ARM64-compat native).
- **Effort total bring-up Oracle :** ~10-12h sur 3 jours (vol horaire decompose en phases).
- **Risque ARM64 residuel :** faible, contingence = build TF from source en CI sur runner ARM (`ubuntu-24.04-arm`) si wheel cassee.
- **Cout mensuel cible :** 0 EUR (Oracle Always Free + Sentry free + Healthchecks free + Grafana Cloud free + OCI Object Storage 10 GB).
- **Cout si surcharge :** ~5 EUR/mois OCI Block Storage si > 200 GB ; ~25 EUR/mois Grafana Cloud Pro si > 50 GB logs.

Decision recommandee : faire les 5 P0 dans la semaine, livrer en prod, puis enchainer les P1 prioritaires (worker cleanup, dependabot, multi-arch verifie en vrai pull ARM, /metrics protege) sur 2 sprints.
