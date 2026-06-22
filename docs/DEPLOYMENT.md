# Runbook de déploiement — MDL Redressement Tool

Mise en production de **MDL Redressement Tool v2** sur **Oracle Cloud Always Free**
(VM `VM.Standard.A1.Flex`, ARM64 Ampere A1, Ubuntu 22.04 aarch64), derrière un reverse
proxy **Caddy** (auto-TLS), avec images Docker **multi-arch** publiées sur **GHCR** et
déploiement continu par **GitHub Actions**.

Domaine public : `https://Trafic-Tool.anbri-tools-ia.online`
Audience : interne (~5-10 utilisateurs). Budget cible : 0 EUR/mois.

Ce runbook est factuel et aligné sur l'état du dépôt :

- `infra/docker-compose.prod.yml` — stack de production (redis, api, web, caddy)
- `infra/Caddyfile` — reverse proxy auto-TLS
- `infra/.env.prod.example` — gabarit des variables d'environnement
- `infra/Dockerfile.api`, `infra/Dockerfile.web` — images multi-arch
- `scripts/oracle-bootstrap.sh` — durcissement initial de la VM
- `.github/workflows/ci.yml` — pipeline lint / test / build-and-push / deploy

---

## 1. Architecture cible

```
Internet
   │  80/443 (+ 443/udp HTTP/3)
   ▼
┌──────────────────────── VM Oracle A1 (ARM64) ────────────────────────┐
│  caddy (auto-TLS, reverse proxy, seul service exposé)                 │
│     ├─ /api/*  ─────────────▶ api:8000   (FastAPI, TensorFlow CPU)    │
│     ├─ /api/training/stream/* ▶ api:8000 (SSE, flush_interval -1)     │
│     ├─ /health ─────────────▶ api:8000                                │
│     ├─ /metrics (LAN only) ─▶ api:8000                                │
│     └─ /*       ─────────────▶ web:3000  (Next.js standalone)         │
│  api ──▶ redis:6379  (sessions, état)                                 │
│  Volumes : /data/mdl_workdir (bind), redis_data, caddy_data           │
└──────────────────────────────────────────────────────────────────────┘
```

Réseau Docker interne `internal` (bridge). Aucun port applicatif (3000/8000/6379)
n'est publié sur l'hôte : seul Caddy expose 80/443. C'est aligné sur
`infra/docker-compose.prod.yml` (section `ports:` uniquement sous `caddy`).

---

## 2. Prérequis

### 2.1 Compte et VM Oracle Cloud

- Tenancy Oracle Cloud Always Free.
- Une VM `VM.Standard.A1.Flex` (recommandé : 4 OCPU / 24 GB RAM, ou au minimum
  les ressources permettant `mem_limit: 16g` sur l'api comme déclaré dans le compose).
- Image **Ubuntu 22.04 LTS aarch64**.
- Un **block volume** persistant attaché (monté en `/data`) pour le workspace et Redis.
  Important : ne jamais stocker le workspace sur `/tmp`.
- Security List / NSG de la VCN : autoriser l'ingress **22, 80, 443** (TCP) et
  **443/udp** (HTTP/3). Tout le reste reste fermé.

### 2.2 DNS

- Enregistrement **A** (et **AAAA** si IPv6) `Trafic-Tool.anbri-tools-ia.online`
  pointant vers l'IP publique de la VM. Caddy a besoin que le DNS résolve **avant**
  le premier démarrage pour obtenir le certificat Let's Encrypt.

### 2.3 Poste local

- Clé SSH (recommandé ed25519) dont la **clé publique** sera injectée par le bootstrap,
  et dont la **clé privée** servira de secret GitHub `ORACLE_SSH_KEY`.
- `docker` + `git` (pour interventions manuelles ponctuelles).

### 2.4 GitHub

- Dépôt `anbsamsam17/machine-learning-traffic-redressement-platform`.
- GHCR activé (packages). Le workflow utilise `secrets.GITHUB_TOKEN` avec la
  permission `packages: write` pour pousser les images.
- Un **environnement GitHub `production`** configuré dans les settings du dépôt,
  idéalement avec un *required reviewer* pour valider chaque déploiement en un clic
  (le job `deploy` référence `environment: name: production`).

---

## 3. Secrets requis

### 3.1 Secrets GitHub Actions (job `deploy`)

Référencés dans `.github/workflows/ci.yml` :

| Secret            | Usage                                                       |
| ----------------- | ---------------------------------------------------------- |
| `ORACLE_HOST`     | IP publique ou FQDN de la VM (hôte SSH)                    |
| `ORACLE_USER`     | Utilisateur SSH (ex. `samir`, créé par le bootstrap)      |
| `ORACLE_SSH_KEY`  | Clé privée SSH correspondant à la clé publique injectée   |
| `GITHUB_TOKEN`    | Fourni automatiquement — pousse les images sur GHCR        |

> Le port SSH utilisé par l'action est `22` (codé dans le workflow).

### 3.2 Secret applicatif sur la VM (`infra/.env.prod`)

Le fichier `infra/.env.prod` (gitignoré, jamais commité) vit sur la VM dans
`/opt/mdl/infra/.env.prod`. Voir `infra/.env.prod.example` pour la liste complète.

| Variable              | Obligatoire | Détail                                                                 |
| --------------------- | :---------: | --------------------------------------------------------------------- |
| `JWT_SECRET`          | **Oui**     | 32+ caractères, **ne doit pas** contenir `change-me` (validé par `config.py`). Compose **refuse de démarrer** sans (`${JWT_SECRET:?...}`). |
| `IMAGE_TAG`           | Oui         | Tag d'image déployé. `latest` par défaut, surchargé par la CI avec le SHA. |
| `ENVIRONMENT`         | Non         | `production`                                                          |
| `REDIS_URL`           | Non         | `redis://redis:6379/0`                                                |
| `HOST_WORKSPACE_ROOT` | Oui         | Chemin hôte monté dans l'api (`/data/mdl_workdir`)                    |
| `WORKSPACE_ROOT`      | Oui         | Chemin interne conteneur (`/data/mdl_workdir`)                        |
| `CORS_ORIGINS`        | Oui         | `https://Trafic-Tool.anbri-tools-ia.online`                          |
| `NEXT_PUBLIC_API_URL` | Oui         | URL publique injectée dans le bundle Next.js au build                 |
| `SESSION_TTL_SECONDS` | Non         | `7200`                                                                |
| `MAX_UPLOAD_MB`       | Non         | `500` (cohérent avec `request_body max_size` du Caddyfile)           |
| `MAX_TRAINING_MINUTES`| Non         | `60` (cohérent avec les timeouts 1h du Caddyfile)                    |
| `SENTRY_DSN`          | Non         | Observabilité (recommandé)                                            |

Générer le secret JWT :

```bash
openssl rand -hex 32
```

Sécuriser le fichier :

```bash
chmod 600 /opt/mdl/infra/.env.prod
```

---

## 4. Préparation initiale de la VM (one-shot)

À exécuter **une seule fois** après le premier accès SSH (en tant que `ubuntu`),
via `scripts/oracle-bootstrap.sh`. Le script est idempotent et durcit la machine.

```bash
sudo SSH_PUBKEY="$(cat ~/.ssh/oracle_a1.pub)" bash scripts/oracle-bootstrap.sh
```

Ce que fait le bootstrap (cf. en-tête du script) :

1. `apt update/upgrade/autoremove`
2. Création de l'utilisateur `samir` (configurable via `SAMIR_USER`), sudo sans mot
   de passe + clé SSH
3. Durcissement SSH (`PermitRootLogin no`, `PasswordAuthentication no`, `AllowUsers`)
4. UFW (22/80/443 autorisés, reste refusé) + purge des règles iptables (Oracle DROP par défaut)
5. fail2ban (jail sshd)
6. unattended-upgrades (patchs de sécurité automatiques)
7. Docker (get.docker.com) + `daemon.json` (rotation des logs, live-restore) + ajout au groupe `docker`
8. Swap 8 GB + `vm.swappiness=10`
9. Montage du block volume `/dev/oracleoci/oraclevdb` sur `/data` via `/etc/fstab`,
   création de `workdir` / `redis` / `backups`
10. Outils utilitaires (`curl`, `git`, `jq`, `htop`, `ncdu`, `rclone`, `stress-ng`)

> Important : valider que `/data` est bien monté sur le block volume persistant
> **avant** le premier `up`, car `HOST_WORKSPACE_ROOT` y est bindé.

### 4.1 Cloner le dépôt sur la VM

Le job `deploy` attend le dépôt dans `/opt/mdl` :

```bash
sudo install -d -o samir -g samir /opt/mdl
git clone https://github.com/anbsamsam17/machine-learning-traffic-redressement-platform.git /opt/mdl
cd /opt/mdl
```

### 4.2 Créer `infra/.env.prod`

```bash
cd /opt/mdl
cp infra/.env.prod.example infra/.env.prod
JWT=$(openssl rand -hex 32) && sed -i "s|^JWT_SECRET=.*$|JWT_SECRET=${JWT}|" infra/.env.prod
chmod 600 infra/.env.prod
```

---

## 5. Stratégie d'images (GHCR multi-arch par SHA)

Le job `build-and-push` du CI construit deux images **multi-arch**
`linux/amd64,linux/arm64` (QEMU + Buildx) et les pousse uniquement sur `push` vers `main` :

- `ghcr.io/anbsamsam17/machine-learning-traffic-redressement-platform/api`
- `ghcr.io/anbsamsam17/machine-learning-traffic-redressement-platform/web`

Tags publiés pour chacune :

- `:${github.sha}` — **tag immuable par commit** (source de vérité pour rollback)
- `:latest`
- `:latest-arm64`

L'image `web` est buildée avec `NEXT_PUBLIC_API_URL` injecté en build-arg
(URL publique inlinée dans le bundle Next.js).

Le compose tire l'image selon `IMAGE_TAG` :

```yaml
image: ghcr.io/.../api:${IMAGE_TAG:-latest}
pull_policy: always
```

Le déploiement par SHA garantit qu'on déploie exactement le commit testé en CI,
et qu'un rollback consiste simplement à re-déployer un SHA antérieur.

---

## 6. Déploiement

### 6.1 Déploiement continu (nominal, via CI)

Sur `push` vers `main`, le pipeline enchaîne :
`lint-backend` / `lint-frontend` → `test-backend` (avec service redis) →
`build-and-push` → `deploy`.

Le job `deploy` (conditionné à `main`, soumis à l'environnement `production`) se
connecte en SSH à la VM et exécute, dans `/opt/mdl` :

```bash
set -euo pipefail
cd /opt/mdl
git fetch --quiet origin main
git checkout -q "${GITHUB_SHA}"
export IMAGE_TAG="${GITHUB_SHA}"
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
docker image prune -f
docker compose -f infra/docker-compose.prod.yml ps
```

Le `pull` par SHA + `up -d` recrée uniquement les services dont l'image a changé
(pas de rebuild sur la VM). `web` redémarre sans interruption longue côté front.

### 6.2 Déploiement / bring-up manuel (depuis la VM)

Premier démarrage ou intervention manuelle :

```bash
cd /opt/mdl
# Optionnel : épingler un SHA précis plutôt que latest
export IMAGE_TAG="$(git rev-parse HEAD)"

# Valider la config compose (interpolation des variables)
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod config >/dev/null

docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
docker compose -f infra/docker-compose.prod.yml ps
```

> Au tout premier `up`, Caddy demande le certificat Let's Encrypt : le DNS doit déjà
> pointer vers la VM et les ports 80/443 être ouverts. En phase de test, on peut
> activer l'ACME staging (ligne `acme_ca` commentée dans `infra/Caddyfile`) pour
> éviter les limites de débit de la prod.

---

## 7. Healthchecks

Healthchecks déclarés dans `infra/docker-compose.prod.yml` :

| Service | Test                                                      | Détail                          |
| ------- | -------------------------------------------------------- | ------------------------------- |
| redis   | `redis-cli ping`                                         | interval 10s, retries 5         |
| api     | `curl -fsS http://localhost:8000/health`                | start_period 60s (chargement TF)|
| web     | requête HTTP Node sur `http://localhost:3000` (< 500)    | start_period 30s                |
| caddy   | `wget --spider http://localhost:2019/metrics` (admin)   | endpoint admin local            |

`depends_on` avec conditions :
`api` attend `redis: service_healthy`, `web` attend `api: service_healthy`,
`caddy` attend `api: service_healthy` + `web: service_started`.

### 7.1 Vérifications post-déploiement

```bash
# État des conteneurs et santé
docker compose -f infra/docker-compose.prod.yml ps

# Santé API en interne
docker compose -f infra/docker-compose.prod.yml exec api curl -fsS http://localhost:8000/health

# Santé via le domaine public (route /health exposée par Caddy)
curl -fsS https://Trafic-Tool.anbri-tools-ia.online/health

# Logs
docker compose -f infra/docker-compose.prod.yml logs -f --tail=100 caddy
docker compose -f infra/docker-compose.prod.yml logs -f --tail=100 api
```

`/metrics` n'est accessible que depuis le LAN privé (matcher `private_ranges` dans
le Caddyfile) ; un accès externe renvoie `403`.

---

## 8. Rollback (par SHA)

Le rollback repose sur l'immuabilité des tags `:${SHA}` sur GHCR.

### 8.1 Identifier le SHA précédent

```bash
cd /opt/mdl
git log --oneline -n 10
```

### 8.2 Re-déployer un SHA antérieur (sur la VM)

```bash
cd /opt/mdl
PREV_SHA=<sha_du_commit_sain>
git fetch --quiet origin main
git checkout -q "${PREV_SHA}"
export IMAGE_TAG="${PREV_SHA}"
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
docker compose -f infra/docker-compose.prod.yml ps
```

### 8.3 Rollback via CI

Re-déclencher le workflow sur le commit cible (re-run du run associé au `PREV_SHA`,
ou `git revert` puis push sur `main`). L'environnement `production` permet de valider
le re-déploiement en un clic si un reviewer est configuré.

> Comme les images sont taguées par SHA, aucun rebuild n'est nécessaire pour revenir
> en arrière : on tire simplement l'image déjà publiée du commit visé.

---

## 9. Opérations courantes

### 9.1 Redémarrer un service

```bash
cd /opt/mdl
docker compose -f infra/docker-compose.prod.yml restart api
```

### 9.2 Recharger Caddy après édition du Caddyfile

```bash
cd /opt/mdl
# Valider la config avant de l'appliquer
docker compose -f infra/docker-compose.prod.yml exec caddy caddy validate --config /etc/caddy/Caddyfile
docker compose -f infra/docker-compose.prod.yml exec caddy caddy reload --config /etc/caddy/Caddyfile
```

### 9.3 Sauvegarde du workspace et de Redis

Le workspace persiste dans `/data/mdl_workdir` (bind) et Redis dans le volume
`redis_data`. Le bootstrap prévoit `/data/backups`.

```bash
# Snapshot du workspace
tar czf /data/backups/mdl_workdir-$(date +%F).tar.gz -C /data mdl_workdir

# Dump Redis (déclenche un SAVE puis copie le RDB)
docker compose -f infra/docker-compose.prod.yml exec redis redis-cli SAVE
docker compose -f infra/docker-compose.prod.yml cp redis:/data/dump.rdb /data/backups/redis-$(date +%F).rdb
```

### 9.4 Nettoyage des images orphelines

```bash
docker image prune -f
```

---

## 10. Dépannage

| Symptôme                                  | Piste                                                                                  |
| ----------------------------------------- | ------------------------------------------------------------------------------------- |
| Compose refuse de démarrer (`JWT_SECRET`) | `infra/.env.prod` manquant/incomplet : `JWT_SECRET` 32+ chars, sans `change-me`.       |
| Certificat TLS non obtenu                 | DNS qui ne résout pas encore, ou 80/443 fermés sur la VCN/UFW. Tester en ACME staging. |
| api `unhealthy` au démarrage              | Chargement TensorFlow long : `start_period` 60s. Vérifier `/data/mdl_workdir` montable. |
| 502/504 sur uploads ou entraînements      | Vérifier `max_size 500MB` (Caddyfile) et timeouts 1h ; aligner `MAX_*` de `.env.prod`. |
| SSE training figé / bufferisé             | Route `/api/training/stream/*` avec `flush_interval -1` dans le Caddyfile.              |
| Déploiement SSH échoue                    | Vérifier `ORACLE_HOST/USER/SSH_KEY`, `AllowUsers` côté sshd, port 22 ouvert.           |
| `/metrics` renvoie 403                    | Comportement attendu : accès restreint au LAN privé (`private_ranges`).                 |

---

## 11. Références dans le dépôt

- `infra/docker-compose.prod.yml`
- `infra/Caddyfile`
- `infra/.env.prod.example`
- `infra/Dockerfile.api`, `infra/Dockerfile.web`
- `scripts/oracle-bootstrap.sh`
- `.github/workflows/ci.yml`
- `plans/p4-oracle-deploy.md`
