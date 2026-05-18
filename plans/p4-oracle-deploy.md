# Plan P4 — Runbook deploiement Oracle Cloud Always Free (ARM64 / Caddy)

Auteur : architecte DevOps/SRE senior. Cible : mettre en ligne **MDL Redressement Tool v2** sur une VM Oracle Cloud `VM.Standard.A1.Flex` (4 OCPU, 24 GB RAM, Ubuntu 22.04 LTS aarch64) avec reverse proxy Caddy auto-TLS, domaine `Trafic-Tool.anbri-tools-ia.online` (DNS Hostinger), CI GitHub Actions, audience interne ~5-10 users, budget mensuel cible **0 EUR**.

Ce runbook prolonge l'audit `audit/05-infra-devops.md` (5 P0, 10 P1, 7 P2) et derive de la macro-phase deja esquissee section "Runbook deploy — structure macro" lignes 402-449. Tout est pret au copier-coller, tout est versionne dans `infra/` ou `scripts/`.

---

## Section 1 — Preparation du code (avant deploy)

Avant d'allumer la VM, on patche le repo `mdl-redressement-v2` pour qu'il soit **deployable** sur ARM64 sans Railway. Les modifs ci-dessous adressent les P0-1 a P0-5 et P1-1, P1-2, P1-8 de l'audit.

### 1.1 Nouveau fichier : `infra/docker-compose.prod.yml`

Justification : `infra/docker-compose.yml:1-87` cible le dev (ports 3000/8000/6379 exposes au LAN, `JWT_SECRET` fallback, worker celery casse, nginx). En prod on veut : pas de ports exposes en dehors de Caddy, volume bind sur `/data`, fail-fast sur secrets manquants, images GHCR multi-arch, healthcheck strict, log rotation.

```yaml
# infra/docker-compose.prod.yml
name: mdl-prod

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"

services:
  redis:
    image: redis:7-alpine@sha256:<digest>   # pin via `docker pull && docker inspect`
    restart: unless-stopped
    command: ["redis-server", "--save", "300", "10", "--appendonly", "no", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    volumes:
      - redis_data:/data
    networks: [internal]
    logging: *default-logging
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    image: ghcr.io/anbsamsam17/anbri-tools-portfolio/api:${IMAGE_TAG:-latest}
    pull_policy: always
    restart: unless-stopped
    environment:
      - CUDA_VISIBLE_DEVICES=-1
      - TF_CPP_MIN_LOG_LEVEL=3
      - TF_ENABLE_ONEDNN_OPTS=0
      - TF_NUM_INTRAOP_THREADS=2
      - TF_NUM_INTEROP_THREADS=1
      - PYTHONUNBUFFERED=1
      - REDIS_URL=redis://redis:6379/0
      - JWT_SECRET=${JWT_SECRET:?JWT_SECRET is required}
      - SENTRY_DSN=${SENTRY_DSN:-}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - WORKSPACE_ROOT=/data/mdl_workdir
      - SESSION_TTL_SECONDS=${SESSION_TTL_SECONDS:-7200}
      - MAX_UPLOAD_MB=${MAX_UPLOAD_MB:-500}
      - MDL_MAX_TRAINING_MINUTES=${MDL_MAX_TRAINING_MINUTES:-60}
      - CORS_ORIGINS=https://Trafic-Tool.anbri-tools-ia.online
    volumes:
      - type: bind
        source: /data/mdl_workdir
        target: /data/mdl_workdir
    networks: [internal]
    depends_on:
      redis:
        condition: service_healthy
    logging: *default-logging
    mem_limit: 16g
    cpus: 3.0
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 5
      start_period: 60s

  web:
    image: ghcr.io/anbsamsam17/anbri-tools-portfolio/web:${IMAGE_TAG:-latest}
    pull_policy: always
    restart: unless-stopped
    environment:
      - NEXT_TELEMETRY_DISABLED=1
      - NODE_ENV=production
    networks: [internal]
    depends_on:
      api:
        condition: service_healthy
    logging: *default-logging
    mem_limit: 1g

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"   # HTTP/3
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
      - caddy_logs:/var/log/caddy
    networks: [internal]
    depends_on:
      api:
        condition: service_healthy
      web:
        condition: service_started
    logging: *default-logging

networks:
  internal:
    driver: bridge

volumes:
  redis_data:
  caddy_data:
  caddy_config:
  caddy_logs:
```

Note critique : `JWT_SECRET=${JWT_SECRET:?JWT_SECRET is required}` fait planter le `docker compose up` si la var est absente — supprime le defaut `change-me-in-production` (`infra/docker-compose.yml:40,65`, P0-3). Le bind `/data/mdl_workdir` remplace `tmp_data` (P0-5).

### 1.2 Nouveau fichier : `infra/Caddyfile`

Justification : remplace `infra/nginx.conf:1-77`. Auto-TLS Let's Encrypt, HSTS, CSP minimal, SSE no-buffer (P1-8 corrige naturellement via `X-Forwarded-*` auto).

```caddy
{
    email admin@anbri-tools-ia.online
    # acme_ca https://acme-staging-v02.api.letsencrypt.org/directory   # decommenter pour tests
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
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
        X-Content-Type-Options    "nosniff"
        X-Frame-Options           "SAMEORIGIN"
        Referrer-Policy           "strict-origin-when-cross-origin"
        Permissions-Policy        "geolocation=(), microphone=(), camera=()"
        Content-Security-Policy   "default-src 'self'; img-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'"
        -Server
    }

    request_body {
        max_size 500MB
    }

    # SSE stream training — flush immediat
    @sse path /api/training/stream*
    handle @sse {
        reverse_proxy api:8000 {
            flush_interval -1
            transport http {
                read_timeout  1h
                write_timeout 1h
            }
        }
    }

    handle /api/* {
        reverse_proxy api:8000 {
            transport http {
                read_timeout  10m
                write_timeout 10m
            }
        }
    }

    handle /health {
        reverse_proxy api:8000
    }

    handle /metrics {
        @internal remote_ip 10.0.0.0/8 127.0.0.1/32
        reverse_proxy @internal api:8000
        respond 403
    }

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

### 1.3 Nouveau fichier : `infra/.env.prod.example`

Template a copier en `.env.prod` (gitignore). Tous les leviers d'exploitation.

```bash
# infra/.env.prod.example — copier en .env.prod puis remplir
# 1. JWT_SECRET : openssl rand -hex 32   (32+ chars, sinon API refuse de booter)
JWT_SECRET=

# 2. Image tag deployee (latest ou SHA)
IMAGE_TAG=latest

# 3. Sentry (optionnel mais recommande) — creer projet sentry.io free
SENTRY_DSN=

# 4. Logging
LOG_LEVEL=INFO

# 5. Sessions Redis
SESSION_TTL_SECONDS=7200

# 6. Limites upload + training
MAX_UPLOAD_MB=500
MDL_MAX_TRAINING_MINUTES=60

# 7. Build-time : URL publique injectee dans Next.js
NEXT_PUBLIC_API_URL=https://Trafic-Tool.anbri-tools-ia.online
```

### 1.4 Modifs `infra/Dockerfile.api`

Trois changements :
- pin base image par digest (P1-3),
- bump `tensorflow-cpu>=2.16,<2.20` dans `pyproject.toml:30` pour avoir le wheel ARM64 natif,
- changer `mkdir -p /tmp/mdl_workdir` (`Dockerfile.api:28`) en `mkdir -p /data/mdl_workdir`.

```dockerfile
# Patch Dockerfile.api (extrait des lignes a remplacer)
FROM python:3.11-slim@sha256:<DIGEST_BOOKWORM> AS builder    # pin (P1-3)
# ...
FROM python:3.11-slim@sha256:<DIGEST_BOOKWORM> AS runtime    # pin
# ...
RUN mkdir -p /data/mdl_workdir \
    && useradd -m appuser && chown -R appuser:appuser /app /data/mdl_workdir
```

Recuperer le digest pour le tag `bookworm` aarch64 : `docker buildx imagetools inspect python:3.11-slim`.

### 1.5 Modifs `infra/Dockerfile.web`

Ajouter `ARG NEXT_PUBLIC_API_URL` pour que Next.js l'inline au build (sans ca, l'URL est `http://localhost:8001` par defaut, cf `apps/web/next.config.ts:3`).

```dockerfile
# Stage builder
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ .
ARG NEXT_PUBLIC_API_URL=https://Trafic-Tool.anbri-tools-ia.online
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build
```

Et dans le step `build-and-push` web du CI : `build-args: NEXT_PUBLIC_API_URL=https://Trafic-Tool.anbri-tools-ia.online`.

### 1.6 Suppressions

`git rm` les artefacts morts (P1-1, P1-2) :

```bash
git rm infra/Dockerfile.api.railway
git rm infra/Dockerfile.web.railway
git rm infra/Dockerfile.worker
git rm scripts/deploy-railway.sh
git rm railway.toml
# Retirer le service `worker` du compose dev (infra/docker-compose.yml:56-72)
# Retirer celery du pyproject.toml ligne 18 (dependance `celery[redis]>=5.3`)
git commit -m "chore: drop Railway artefacts and broken Celery worker"
```

### 1.7 Modifs `.github/workflows/ci.yml`

Patch P0-1 (multi-arch) + P0-2 (deploy reel) + P1-9 (cache scope).

```yaml
build-and-push:
  runs-on: ubuntu-latest
  needs: [test-backend, lint-frontend]
  permissions:
    contents: read
    packages: write
  steps:
    - uses: actions/checkout@v4
    - uses: docker/setup-qemu-action@v3
    - uses: docker/setup-buildx-action@v3
    - uses: docker/login-action@v3
      if: github.event_name == 'push' && github.ref == 'refs/heads/main'
      with:
        registry: ghcr.io
        username: ${{ github.actor }}
        password: ${{ secrets.GITHUB_TOKEN }}

    - uses: docker/build-push-action@v5
      with:
        context: .
        file: infra/Dockerfile.api
        platforms: linux/amd64,linux/arm64
        push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
        tags: |
          ghcr.io/${{ github.repository }}/api:${{ github.sha }}
          ghcr.io/${{ github.repository }}/api:latest
        cache-from: type=gha,scope=api
        cache-to: type=gha,mode=max,scope=api

    - uses: docker/build-push-action@v5
      with:
        context: .
        file: infra/Dockerfile.web
        platforms: linux/amd64,linux/arm64
        build-args: |
          NEXT_PUBLIC_API_URL=https://Trafic-Tool.anbri-tools-ia.online
        push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}
        tags: |
          ghcr.io/${{ github.repository }}/web:${{ github.sha }}
          ghcr.io/${{ github.repository }}/web:latest
        cache-from: type=gha,scope=web
        cache-to: type=gha,mode=max,scope=web

deploy:
  runs-on: ubuntu-latest
  needs: build-and-push
  if: github.event_name == 'push' && github.ref == 'refs/heads/main'
  environment: production
  steps:
    - uses: appleboy/ssh-action@v1.0.3
      with:
        host: ${{ secrets.ORACLE_HOST }}
        username: ${{ secrets.ORACLE_USER }}
        key: ${{ secrets.ORACLE_SSH_KEY }}
        port: 22
        script: |
          set -euo pipefail
          cd /opt/mdl
          export IMAGE_TAG=${{ github.sha }}
          docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
          docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --no-build
          docker image prune -f
```

### 1.8 Nouveau script : `scripts/oracle-bootstrap.sh`

Idempotent — peut etre rejoue. Cible : VM Ubuntu 22.04 vierge.

```bash
#!/usr/bin/env bash
set -euo pipefail
# scripts/oracle-bootstrap.sh — bring-up VM Oracle A1 Ubuntu 22.04 aarch64
SAMIR_USER="samir"
SSH_PUBKEY="${SSH_PUBKEY:?export SSH_PUBKEY=ssh-ed25519...}"

# 1. updates
apt-get update && apt-get -y upgrade && apt-get -y autoremove

# 2. user non-root
if ! id "${SAMIR_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${SAMIR_USER}"
  install -d -m 700 -o "${SAMIR_USER}" -g "${SAMIR_USER}" "/home/${SAMIR_USER}/.ssh"
  echo "${SSH_PUBKEY}" > "/home/${SAMIR_USER}/.ssh/authorized_keys"
  chmod 600 "/home/${SAMIR_USER}/.ssh/authorized_keys"
  chown "${SAMIR_USER}:${SAMIR_USER}" "/home/${SAMIR_USER}/.ssh/authorized_keys"
fi
usermod -aG sudo "${SAMIR_USER}"
echo "${SAMIR_USER} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/90-${SAMIR_USER}
chmod 0440 /etc/sudoers.d/90-${SAMIR_USER}

# 3. SSH hardening
sed -ri 's/^#?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -ri 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -ri 's/^#?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
grep -q "^AllowUsers ${SAMIR_USER}" /etc/ssh/sshd_config || echo "AllowUsers ${SAMIR_USER}" >> /etc/ssh/sshd_config
systemctl reload sshd

# 4. UFW
apt-get install -y ufw
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow http
ufw allow https
ufw --force enable

# 5. fail2ban
apt-get install -y fail2ban
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban

# 6. unattended-upgrades
apt-get install -y unattended-upgrades apt-listchanges
dpkg-reconfigure -f noninteractive unattended-upgrades

# 7. Docker
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${SAMIR_USER}"
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "50m", "max-file": "5"},
  "default-address-pools": [{"base": "172.30.0.0/16", "size": 24}],
  "live-restore": true
}
EOF
systemctl restart docker

# 8. /data block volume mount (suppose /dev/oracleoci/oraclevdb attache)
if [ -b /dev/oracleoci/oraclevdb ] && ! mountpoint -q /data; then
  blkid /dev/oracleoci/oraclevdb || mkfs.ext4 -F /dev/oracleoci/oraclevdb
  mkdir -p /data
  UUID=$(blkid -s UUID -o value /dev/oracleoci/oraclevdb)
  grep -q "${UUID}" /etc/fstab || echo "UUID=${UUID} /data ext4 defaults,_netdev,nofail 0 2" >> /etc/fstab
  mount -a
fi
install -d -o "${SAMIR_USER}" -g "${SAMIR_USER}" /data/mdl_workdir /data/redis /data/backups

# 9. tools utilitaires
apt-get install -y curl git jq htop ncdu rclone stress-ng

echo "Bootstrap OK. Reconnecte-toi en SSH avec ${SAMIR_USER}."
```

A executer une seule fois via `sudo SSH_PUBKEY="ssh-ed25519 AAAA..." bash scripts/oracle-bootstrap.sh`.

---

## Section 2 — Inscription et provisioning Oracle Cloud

### 2.1 Creation compte Always Free (15-30 min)

1. Aller sur `https://signup.cloud.oracle.com`.
2. Champs : email, pays = **Germany** (force la region Frankfurt par defaut, meilleure dispo ARM A1 que Paris), prenom/nom, n de telephone (SMS verif). Mot de passe fort.
3. Donnees societe : pour usage perso, mettre "Personal use" / nom prenom.
4. Adresse : adresse perso reelle, doit matcher la CB.
5. **Carte bancaire** (verification 1 EUR, jamais debitee tant qu'on reste Always Free). Cards prepayees Revolut/N26 acceptees.
6. Validation email (lien) puis SMS (code 6 chiffres).
7. **Home Region** = `eu-frankfurt-1` (immuable apres choix, choisir avec attention).
8. Attendre le mail "Your OCI account is ready" (5-20 min).

### 2.2 Compartment

Pour un seul projet, le compartment racine suffit. Skip.

### 2.3 Reseau VCN (Virtual Cloud Network)

1. Console : `https://cloud.oracle.com` -> burger menu -> **Networking -> Virtual Cloud Networks**.
2. Bouton **"Start VCN Wizard"** -> "VCN with Internet Connectivity" -> Start.
3. Form :
   - VCN Name : `vcn-mdl`
   - CIDR : `10.0.0.0/16` (par defaut, OK)
   - Public Subnet CIDR : `10.0.0.0/24`
   - Private Subnet CIDR : `10.0.1.0/24` (inutilise, on garde par confort)
4. Click **Next -> Create**. Le wizard cree VCN + Internet Gateway + NAT GW + Route Tables + Security Lists automatiquement.
5. Apres creation, ouvrir VCN -> **Security Lists -> Default Security List**.
6. **Add Ingress Rules** :

| Source | IP Protocol | Source Port | Destination Port | Description |
|---|---|---|---|---|
| 0.0.0.0/0 | TCP | All | 22 | SSH |
| 0.0.0.0/0 | TCP | All | 80 | HTTP (ACME) |
| 0.0.0.0/0 | TCP | All | 443 | HTTPS |
| 0.0.0.0/0 | UDP | All | 443 | HTTP/3 (optionnel) |

Egress : laisser tout autorise par defaut.

### 2.4 Provisioning instance A1 Flex

1. Menu -> **Compute -> Instances -> Create Instance**.
2. Form :
   - **Name** : `vm-mdl-prod`
   - **Placement** : laisser AD par defaut (Oracle round-robin). Si "Out of capacity" -> tester AD-2 puis AD-3.
   - **Image** : Edit -> "Change Image" -> Canonical Ubuntu -> **22.04** -> selectionner build aarch64. Click "Select Image".
   - **Shape** : Edit -> "Change Shape" -> Ampere -> **VM.Standard.A1.Flex** -> OCPU = **4**, Memory = **24 GB**. Si grise : selectionner une AD differente.
   - **Networking** : VCN = `vcn-mdl`, Subnet = `Public Subnet`, "Assign a public IPv4 address" coche.
   - **SSH keys** : "Upload public key files" -> uploader le `~/.ssh/oracle_a1.pub` genere localement par `ssh-keygen -t ed25519 -f ~/.ssh/oracle_a1 -C "samir@mdl"`.
   - **Boot volume** : 100 GB (max Always Free = 200 GB cumule), VPU 10 par defaut.
3. Click **Create**.
4. Attendre status **RUNNING** (~2 min). Noter l'IP publique ephemere.

### 2.5 Strategie anti "Out of host capacity"

ARM A1 sature regulierement en Frankfurt. Si erreur :

1. Retry immediat sur AD-2, AD-3.
2. Sinon : script bash qui retry chaque 5 min via OCI CLI :

```bash
# scripts/oracle-retry-launch.sh
while true; do
  oci compute instance launch --from-json file://launch.json && break
  echo "$(date) — capacity unavailable, retry in 5 min"
  sleep 300
done
```

3. Alternative : changer Home Region (re-creer compte separe) : `eu-amsterdam-1`, `eu-marseille-1`, `eu-paris-1` ont parfois plus de marge.
4. Une fois l'instance creee, **ne plus l'eteindre** : Oracle peut refuser de la relancer si la capacite a disparu.

### 2.6 Reservation Reserved Public IP

L'IP ephemere change a chaque arret. On en reserve une (2 gratuites en Always Free).

1. Menu -> **Networking -> Reserved Public IPs -> Reserve Public IP Address**.
2. Name : `ip-mdl-prod`. Region = home region. Click Reserve.
3. Aller sur l'instance -> **Attached VNICs** -> cliquer la VNIC primaire -> **IPv4 Addresses** -> trois points a droite de l'IP -> **Edit** -> Public IP Type = "Reserved Public IP" -> selectionner `ip-mdl-prod` -> Update.
4. L'IP publique est maintenant stable. Noter sa valeur (ex `141.147.x.y`).

### 2.7 (Optionnel) Block Volume separe 100 GB

Always Free permet jusqu'a 200 GB de block storage. Le boot fait deja 100 GB. On peut ajouter un second volume dedie `/data` (recommande, isole les modeles de l'OS).

1. **Storage -> Block Volumes -> Create Block Volume**. Name = `bv-mdl-data`. Size = 100 GB. Performance = "Lower Cost" (Always Free). Backup Policy = "Bronze" (snapshots quotidiens free).
2. Apres creation -> "Attached Instances" -> Attach to Instance = `vm-mdl-prod`. Mode = "Read/Write", Type = "Paravirtualized". Attach.
3. Sur la VM, le volume apparait en `/dev/oracleoci/oraclevdb` (geres par `oci-iscsi-config`). Le script `oracle-bootstrap.sh` section 1.8 le formate ext4 et le monte automatiquement en `/data`.

### 2.8 Premier SSH

```bash
ssh -i ~/.ssh/oracle_a1 ubuntu@141.147.x.y
# Attention : user de base = "ubuntu" (default Oracle Ubuntu image).
# On creera "samir" via le bootstrap, puis on bascule.
```

---

## Section 3 — Hardening initial Ubuntu 22.04

Commandes a passer en tant que `ubuntu` puis `sudo`, dans l'ordre. Au cas ou on ne lance pas `oracle-bootstrap.sh`, voici la version manuelle commentee.

```bash
# 1. updates
sudo apt-get update && sudo apt-get -y upgrade && sudo apt-get -y autoremove
sudo reboot   # uniquement si le kernel a ete update
```

Reconnexion SSH apres reboot, puis :

```bash
# 2. user non-root + SSH key
sudo adduser --disabled-password --gecos "" samir
sudo usermod -aG sudo samir
sudo install -d -m 700 -o samir -g samir /home/samir/.ssh
sudo cp /home/ubuntu/.ssh/authorized_keys /home/samir/.ssh/
sudo chown samir:samir /home/samir/.ssh/authorized_keys
echo "samir ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/90-samir
sudo chmod 0440 /etc/sudoers.d/90-samir

# Tester depuis un autre terminal : ssh -i ~/.ssh/oracle_a1 samir@<IP>
```

```bash
# 3. SSH hardening (apres validation que samir fonctionne)
sudo sed -ri 's/^#?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -ri 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
echo "AllowUsers samir" | sudo tee -a /etc/ssh/sshd_config
sudo systemctl reload sshd
```

```bash
# 4. UFW
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow http
sudo ufw allow https
sudo ufw --force enable
sudo ufw status verbose
```

**Important Oracle Ubuntu** : `iptables` est configure par defaut avec une regle DROP en INPUT qui bloque tout sauf 22. UFW ne suffit pas, il faut purger :

```bash
sudo iptables -F INPUT
sudo iptables -P INPUT ACCEPT   # UFW reprendra le controle
sudo netfilter-persistent save 2>/dev/null || sudo iptables-save | sudo tee /etc/iptables/rules.v4
```

```bash
# 5. fail2ban
sudo apt-get install -y fail2ban
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd

# 6. unattended-upgrades
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# 7. swap (8 GB) — defense en profondeur si TF saturee
sudo fallocate -l 8G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf
```

```bash
# 8. Verifications finales
ss -lntp                          # ports en ecoute : sshd:22 uniquement
sudo ufw status verbose           # 22/80/443 allowed
sudo systemctl status fail2ban    # active (running)
sudo journalctl -u sshd --since "5 min ago"
```

---

## Section 4 — Installation Docker + Caddy

### 4.1 Docker (recommandation : script officiel)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker samir
newgrp docker   # OU se reconnecter SSH
docker version
docker compose version
docker run --rm hello-world
docker run --rm --platform linux/arm64 hello-world   # confirme ARM natif
```

### 4.2 Daemon config (log rotation + live-restore)

```bash
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "50m", "max-file": "5"},
  "live-restore": true
}
EOF
sudo systemctl restart docker
```

### 4.3 Caddy : container (recommande) vs apt

**Recommandation : Caddy en container**, comme defini dans `infra/docker-compose.prod.yml` section 1.1. Avantages :
- versionne dans le compose, redeploye comme le reste,
- volume `caddy_data` persiste les certs Let's Encrypt entre redemarrages,
- pas de demon systemd parallele a maintenir.

L'alternative `apt install caddy` (binary natif) reste pertinente si on veut Caddy au-dessus du compose pour decoupler le cycle de vie (renouveler certs sans toucher au compose). Mais 2 reverse proxies = 2 surfaces. Choisir **container**.

Aucune commande supplementaire ici : le service `caddy` du compose prod est leve a la section 6.

---

## Section 5 — Configuration DNS Hostinger

1. Login `https://hpanel.hostinger.com`.
2. Menu lateral : **Domains** -> selectionner `anbri-tools-ia.online` -> **DNS / Name Servers**.
3. Verifier que les nameservers sont bien ceux d'Hostinger (`ns1.dns-parking.com` / `ns2.dns-parking.com` ou les NS Hostinger officiels) — si tu utilises Cloudflare proxy, faire ces etapes cote Cloudflare a la place.
4. Section **DNS records** -> **Add new record** :
   - Type : `A`
   - Name : `Trafic-Tool` (Hostinger ajoute `.anbri-tools-ia.online` automatiquement)
   - Points to : `141.147.x.y` (IP reservee Oracle, section 2.6)
   - TTL : `300` (5 min, pratique pour iteration). Repasser a `3600` apres stabilisation.
5. Click **Add Record**.

Attention : si un record CNAME ou wildcard `*` existe deja pour `anbri-tools-ia.online`, il peut interferer. Le record A le plus specifique gagne.

### Verification propagation

```bash
# Depuis ta machine locale
dig +short Trafic-Tool.anbri-tools-ia.online @1.1.1.1
dig +short Trafic-Tool.anbri-tools-ia.online @8.8.8.8
nslookup Trafic-Tool.anbri-tools-ia.online 8.8.8.8
```

Ou via `https://www.whatsmydns.net/#A/Trafic-Tool.anbri-tools-ia.online`.

Compter 1-15 min avec TTL=300, jusqu'a 24h en pire cas. Ne pas lancer Caddy avant que le DNS resolve correctement, sinon le challenge HTTP-01 Let's Encrypt echoue et tu te manges 5 tentatives ratees (rate-limit ACME : 5 echecs/heure puis ban 1h).

---

## Section 6 — Premier deploiement

### 6.1 Preparer l'arborescence

```bash
# Sur la VM en tant que samir
sudo mkdir -p /opt/mdl
sudo chown samir:samir /opt/mdl
cd /opt/mdl

git clone https://github.com/anbsamsam17/Anbri-Tools-portfolio.git .
git log -1 --oneline   # confirme le commit
```

### 6.2 Variables d'environnement

```bash
cp infra/.env.prod.example infra/.env.prod
# Generer un JWT secret fort (32+ chars)
JWT=$(openssl rand -hex 32)
sed -i "s|^JWT_SECRET=$|JWT_SECRET=${JWT}|" infra/.env.prod
# Editer les autres lignes (SENTRY_DSN si pret, sinon laisser vide)
nano infra/.env.prod
chmod 600 infra/.env.prod
```

Sauvegarder ce JWT dans Bitwarden / pass / 1Password immediatement. Il ne doit jamais quitter la VM sauf chiffre.

### 6.3 Login GHCR (pour pull d'images privees)

Si le repo GitHub est public, les images GHCR le sont aussi : skip. Sinon :

```bash
# Creer un PAT sur https://github.com/settings/tokens?type=beta avec scope read:packages
echo "ghp_xxxxx" | docker login ghcr.io -u anbsamsam17 --password-stdin
```

### 6.4 Option A — pull image registry (recommande si CI multi-arch OK)

```bash
cd /opt/mdl
export IMAGE_TAG=latest   # ou le SHA d'un commit precis
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
```

Premiere fois : `docker compose pull` telecharge 3 images (~800 MB total). Compter 2-5 min selon bande passante.

### 6.5 Option B — build local sur la VM (fallback si pas d'image ARM64 publiee)

Long mais autonome. Attention : `tensorflow-cpu` n'est pas distribue en wheel ARM64 sur certaines versions, il faut basculer sur `tensorflow` plain.

```bash
cd /opt/mdl
# Editer apps/api/pyproject.toml ligne 30 si besoin :
# - "tensorflow-cpu>=2.16,<2.20",
# + "tensorflow>=2.16,<2.20",
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod build --pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
```

Build api : 15-25 min sur 4 OCPU (compile bcrypt, scipy, geopandas). Build web : 3-5 min.

### 6.6 Verifications certs Let's Encrypt + healthcheck

```bash
# Caddy obtient les certs sur le 1er hit
docker compose -f infra/docker-compose.prod.yml logs -f caddy | grep -iE "certificate|obtained|served"
# Attendre la ligne : "certificate obtained successfully"  (~30 s)

# Test HTTPS
curl -I https://Trafic-Tool.anbri-tools-ia.online/health
# HTTP/2 200
# server: Caddy
# content-type: application/json

curl https://Trafic-Tool.anbri-tools-ia.online/health
# {"status":"ok",...}
```

Si Caddy echoue (ACME refuse) : verifier que port 80 est bien ouvert cote Oracle Security List ET UFW ET que le DNS resolve sur la bonne IP. Repasser sur l'`acme_ca` staging (decommenter dans `Caddyfile`) le temps de debugger pour eviter le rate-limit prod.

### 6.7 Smoke test workflow complet

1. Naviguer `https://Trafic-Tool.anbri-tools-ia.online/register`, creer un user.
2. Login -> mode TV.
3. Upload mini-fichier (echantillon `tests/fixtures/sample.csv` ou autre).
4. Mapping colonnes -> Config (max_epochs=2, batch=64) -> lancer Training.
5. Observer le SSE stream : `Network -> /api/training/stream/{job_id}` doit renvoyer du `text/event-stream` avec batchs reguliers.
6. Eval -> verifier que les metriques s'affichent.
7. Carte -> verifier le rendu Folium.
8. Compteurs -> verifier persistance Redis (`docker exec -it mdl-prod-redis-1 redis-cli KEYS 'session:*'`).

Si tout passe : le deployment est valide, on peut basculer en routine.

---

## Section 7 — Auto-deploy CI -> VM

### 7.1 Comparaison des options

| Option | Effort | Securite | Reactivite | Choix |
|---|---|---|---|---|
| **SSH push depuis GA** (appleboy/ssh-action) | bas | bonne (cle dediee, command= restreint) | ~2 min apres merge | **Recommande** |
| GitHub Actions self-hosted runner | moyen | moindre (demon GH sur VM = surface attaque) | < 1 min | Skip (overkill 5-10 users) |
| Watchtower poll registry | tres bas | mauvaise (chaque merge = prod, pas de gate) | 5 min (poll interval) | Skip (pas de controle) |
| Webhook signe (Caddy + script) | moyen | bonne | < 1 min | Skip (custom code a maintenir) |

**Decision : SSH push** depuis le job `deploy` du CI, deja code section 1.7.

### 7.2 Setup de la cle SSH dediee

Sur ton poste local :

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oracle_deploy -C "github-actions-mdl" -N ""
# Genere ~/.ssh/oracle_deploy (privee) + .pub
```

Sur la VM (en tant que `samir`) :

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
cat >> ~/.ssh/authorized_keys <<'EOF'
ssh-ed25519 AAAA... github-actions-mdl
EOF
chmod 600 ~/.ssh/authorized_keys
```

Optionnel mais conseille : restreindre la cle a une seule commande (defense en profondeur si la cle fuit) en prefixant la ligne `authorized_keys` :

```
command="cd /opt/mdl && docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull && docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --no-build",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA...
```

(Si on choisit le `command=`, le script du job `deploy` est ignore — c'est la commande forcee qui s'execute. Plus sur, mais moins flexible pour `IMAGE_TAG` dynamique. Compromis : se contenter de la cle non-restreinte pour pouvoir piloter le tag.)

### 7.3 Secrets GitHub Actions

`https://github.com/anbsamsam17/Anbri-Tools-portfolio/settings/secrets/actions/new` :

| Nom | Valeur |
|---|---|
| `ORACLE_HOST` | `141.147.x.y` (IP reservee) |
| `ORACLE_USER` | `samir` |
| `ORACLE_SSH_KEY` | contenu de `~/.ssh/oracle_deploy` (cle privee complete, BEGIN OPENSSH... END OPENSSH PRIVATE KEY) |

Et creer l'environnement `production` (`Settings -> Environments -> New environment -> production`), avec **required reviewer = samir** : chaque deploy demande approbation manuelle (1 click). Active une protection contre les regressions accidentelles en attendant que la suite de tests soit etoffee.

### 7.4 Test end-to-end CI

```bash
# Sur ta machine
git checkout -b test-deploy
echo "test" >> README.md
git add README.md && git commit -m "chore: test deploy pipeline"
git push origin test-deploy
# Ouvrir PR, merger sur main.
# Aller sur https://github.com/.../actions, attendre approbation prod, approuver.
# Observer le step SSH.
```

Sur la VM : `docker compose -f infra/docker-compose.prod.yml ps` doit montrer les conteneurs avec `Created X seconds ago`.

---

## Section 8 — Observabilite et monitoring (gratuit)

### 8.1 Sentry (crash reporting)

1. `https://sentry.io/signup/` -> Free Developer (5k errors/mois).
2. Create project -> Platform = Python (FastAPI). Recopier le DSN du form (`https://abc123@o123.ingest.sentry.io/456`).
3. Editer `/opt/mdl/infra/.env.prod` : `SENTRY_DSN=https://abc123@...`.
4. `docker compose -f infra/docker-compose.prod.yml up -d api` -> redemarre api avec DSN.
5. Verifier : declencher une erreur volontaire (`/api/debug/raise` si endpoint debug, sinon casser un upload) -> elle doit apparaitre dans le dashboard Sentry sous 30 s.

Code deja branche dans `apps/api/app/main.py` (lignes ~57-72 selon audit). Aucun code a ecrire.

### 8.2 Healthchecks.io (uptime externe)

1. `https://healthchecks.io/` -> sign up free (20 checks).
2. Add check : Name = `MDL prod health`. Schedule = "Simple", period 5 min, grace 1 min. Click Create.
3. Copier l'URL ping (`https://hc-ping.com/UUID`).
4. Sur la VM, creer un cron qui ping uniquement si `/health` OK :

```bash
sudo tee /etc/cron.d/mdl-healthcheck <<EOF
*/5 * * * * samir curl -fsS --max-time 10 https://Trafic-Tool.anbri-tools-ia.online/health > /dev/null && curl -fsS -m 10 --retry 3 https://hc-ping.com/<UUID> > /dev/null
EOF
```

5. Configurer alerte mail sur Healthchecks.io -> Integrations -> Email (gratuit) ou Slack/Discord.

### 8.3 Grafana Cloud (optionnel)

A activer seulement si besoin de dashboards. Sinon `docker stats` + `journalctl` suffisent.

1. `https://grafana.com/auth/sign-up/create-user` -> Free (10k metric series, 50 GB logs).
2. Stack creee auto -> noter Prometheus remote write URL + API key.
3. Installer Grafana Agent ARM64 sur la VM :

```bash
ARCH=arm64
VERSION=0.40.0
curl -OL "https://github.com/grafana/agent/releases/download/v${VERSION}/grafana-agent-linux-${ARCH}.zip"
sudo unzip grafana-agent-linux-${ARCH}.zip -d /usr/local/bin/
sudo chmod +x /usr/local/bin/grafana-agent-linux-${ARCH}
```

4. Config `/etc/grafana-agent.yaml` minimale : scrape `https://Trafic-Tool.anbri-tools-ia.online/metrics` (via IP locale 127.0.0.1 a cause de la restriction IP du Caddyfile section 1.2) toutes les 30 s, push vers Grafana Cloud.
5. Importer dashboard ID 14282 (FastAPI Observability).

### 8.4 Logs containers

Par defaut (cf daemon.json section 4.2) : 50 MB/fichier, 5 fichiers max = 250 MB max/conteneur.

```bash
# Tail temps reel
docker compose -f /opt/mdl/infra/docker-compose.prod.yml logs -f --tail=100 api

# Filtrer par service
docker compose -f /opt/mdl/infra/docker-compose.prod.yml logs --since=1h web

# Sortir un fichier
docker compose -f /opt/mdl/infra/docker-compose.prod.yml logs --no-color > /tmp/all-logs.txt
```

Caddy : logs JSON dans `caddy_logs` volume, rotation native (50 MB x 5).

---

## Section 9 — Backups

### 9.1 Strategie

| Cible | Frequence | Retention | Stockage |
|---|---|---|---|
| `/data/mdl_workdir` (modeles + datasets sessions) | quotidien 03h00 | 7 dailies + 4 weeklies + 12 monthlies | OCI Object Storage |
| Redis BGSAVE | toutes les 6h | 7 j sur disque | `/data/backups/redis/` |
| Boot volume Oracle | quotidien (Bronze policy auto) | 7 j | snapshots OCI |
| `.env.prod` + Caddyfile | sur changement | dans Bitwarden | manuel |

### 9.2 Setup OCI Object Storage + rclone

1. Console OCI -> **Storage -> Buckets -> Create Bucket**. Name = `mdl-backups`. Storage Tier = Standard. Versioning Disabled. Click Create.
2. Generer un Customer Secret Key : profil user -> Customer Secret Keys -> Generate Secret Key. Noter `Access Key` + `Secret Key`.
3. Recuperer namespace OCI : `oci os ns get --query data --raw-output` (si OCI CLI installe) ou Console -> Tenancy details -> Object Storage Namespace.
4. Sur la VM :

```bash
rclone config
# n) new remote
# name: oci
# Storage: 4 (Amazon S3 compliant) — Oracle Object Storage est S3-compatible
# provider: 11 (Other)
# env_auth: false
# access_key_id: <Access Key>
# secret_access_key: <Secret Key>
# region: eu-frankfurt-1
# endpoint: https://<namespace>.compat.objectstorage.eu-frankfurt-1.oraclecloud.com
# location_constraint: <vide>
# acl: private
# y/y/y

# Test
rclone lsd oci:
rclone mkdir oci:mdl-backups   # si pas deja cree cote console
```

### 9.3 Script backup

```bash
sudo tee /usr/local/bin/mdl-backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y-%m-%dT%H%M%SZ)
BACKUP_DIR=/data/backups
mkdir -p "${BACKUP_DIR}/redis" "${BACKUP_DIR}/models"

# 1. Snapshot Redis
docker exec mdl-prod-redis-1 redis-cli BGSAVE
sleep 5
docker cp mdl-prod-redis-1:/data/dump.rdb "${BACKUP_DIR}/redis/dump-${TS}.rdb"
find "${BACKUP_DIR}/redis" -name 'dump-*.rdb' -mtime +7 -delete

# 2. Tarball mdl_workdir
TAR="${BACKUP_DIR}/models/mdl-${TS}.tar.gz"
tar --warning=no-file-changed -czf "${TAR}" -C /data mdl_workdir

# 3. Upload OCI (chiffre cote client via age si secret_key dispo)
rclone copyto "${TAR}" "oci:mdl-backups/daily/mdl-${TS}.tar.gz" --s3-no-check-bucket

# 4. Rotation : 7 dailies + 4 weeklies (dimanches) + 12 monthlies (1er du mois)
DOW=$(date -u +%u)
DOM=$(date -u +%d)
if [ "${DOM}" = "01" ]; then
  rclone copyto "${TAR}" "oci:mdl-backups/monthly/mdl-${TS}.tar.gz"
elif [ "${DOW}" = "7" ]; then
  rclone copyto "${TAR}" "oci:mdl-backups/weekly/mdl-${TS}.tar.gz"
fi

# 5. Cleanup distant
rclone delete --min-age 7d "oci:mdl-backups/daily/" --include "mdl-*.tar.gz"
rclone delete --min-age 28d "oci:mdl-backups/weekly/" --include "mdl-*.tar.gz"
rclone delete --min-age 365d "oci:mdl-backups/monthly/" --include "mdl-*.tar.gz"

# 6. Cleanup local
find "${BACKUP_DIR}/models" -name 'mdl-*.tar.gz' -mtime +2 -delete

echo "[$(date -u)] backup OK: ${TAR}"
EOF
sudo chmod +x /usr/local/bin/mdl-backup.sh
```

### 9.4 Cron

```bash
sudo tee /etc/cron.d/mdl-backup <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Daily 03h00 UTC
0 3 * * * root /usr/local/bin/mdl-backup.sh >> /var/log/mdl-backup.log 2>&1
EOF
sudo touch /var/log/mdl-backup.log && sudo chown root:root /var/log/mdl-backup.log
```

### 9.5 Test de restauration (a faire au moins 1 fois)

```bash
# Snapshot du dernier backup distant
rclone copy oci:mdl-backups/daily/mdl-YYYY-MM-DDTHHMMSSZ.tar.gz /tmp/

# Sur env de test (autre VM, ou /tmp/restore-test/ sur la prod)
mkdir -p /tmp/restore-test
tar -xzf /tmp/mdl-YYYY-*.tar.gz -C /tmp/restore-test/
ls -la /tmp/restore-test/mdl_workdir/
# Verifier : modeles presents, taille coherente, fichier model_*.keras lisible
```

---

## Section 10 — Anti-resiliation Oracle Always Free

Oracle a deja resilie des comptes "idle" (zero traffic 7 j). Le simple fait que Caddy serve HTTPS + healthchecks.io ping toutes les 5 min suffit en pratique. En ceinture-bretelles :

```bash
sudo tee /etc/cron.d/mdl-keepalive <<'EOF'
# Petit pic CPU mensuel pour signaler activite
0 12 1 * * root /usr/bin/stress-ng --cpu 1 --timeout 60s > /dev/null 2>&1
# Touch un fichier d'activite
*/30 * * * * samir date >> /home/samir/.keepalive
EOF
```

Suivre les emails Oracle ("Your account is at risk of reclamation") : repondre en cliquant le lien dans le mail dans les 24 h, sinon resilation sous 7 j.

---

## Section 11 — Runbook ops courant

### 11.1 SSH

```bash
ssh -i ~/.ssh/oracle_a1 samir@Trafic-Tool.anbri-tools-ia.online
# Si IP a change (jamais avec Reserved IP, mais au cas ou) :
ssh -i ~/.ssh/oracle_a1 samir@141.147.x.y
```

### 11.2 Redeployer une nouvelle version

Cas standard (auto via CI) : merger sur `main`, approuver l'env `production` dans GitHub Actions. Rien d'autre a faire.

Cas manuel (hotfix sans CI) :

```bash
ssh samir@Trafic-Tool.anbri-tools-ia.online
cd /opt/mdl
git fetch && git checkout <SHA>
export IMAGE_TAG=<SHA>
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod pull
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --no-build
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod ps
```

Rollback :

```bash
export IMAGE_TAG=<SHA_precedent>
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d --no-build
```

### 11.3 Logs

```bash
cd /opt/mdl
# Tous services, 100 dernieres lignes, suivi temps reel
docker compose -f infra/docker-compose.prod.yml logs -f --tail=100

# Par service
docker compose -f infra/docker-compose.prod.yml logs -f api
docker compose -f infra/docker-compose.prod.yml logs -f web
docker compose -f infra/docker-compose.prod.yml logs -f caddy
docker compose -f infra/docker-compose.prod.yml logs -f redis

# Caddy access logs structures
docker compose -f infra/docker-compose.prod.yml exec caddy tail -f /var/log/caddy/access.log | jq .
```

### 11.4 Restaurer un backup

```bash
# 1. Stopper l'api le temps du remplacement
cd /opt/mdl
docker compose -f infra/docker-compose.prod.yml stop api

# 2. Sauvegarder l'etat courant au cas ou
sudo mv /data/mdl_workdir /data/mdl_workdir.bak-$(date +%s)

# 3. Recup et extract
rclone copy oci:mdl-backups/daily/mdl-YYYY-MM-DDTHHMMSSZ.tar.gz /tmp/
sudo mkdir -p /data/mdl_workdir
sudo tar -xzf /tmp/mdl-YYYY-*.tar.gz -C /data --strip-components=0
sudo chown -R 1000:1000 /data/mdl_workdir   # uid appuser du conteneur

# 4. Restart
docker compose -f infra/docker-compose.prod.yml up -d api
docker compose -f infra/docker-compose.prod.yml logs -f api
```

### 11.5 Scaler CPU/RAM a chaud (A1 Flex)

Always Free englobe 4 OCPU + 24 GB en un seul tenant. On peut redimensionner sans recreer la VM tant qu'on ne depasse pas ce quota.

1. Console -> Compute -> Instances -> `vm-mdl-prod` -> bouton **Edit** -> **Edit shape**.
2. Modifier OCPU (1-4) et Memory (6-24 GB). Click Save.
3. La VM reboote (~1 min). Tous les conteneurs avec `restart: unless-stopped` remontent seuls.

### 11.6 Inspecter Redis

```bash
docker compose -f /opt/mdl/infra/docker-compose.prod.yml exec redis redis-cli
> KEYS 'session:*'
> INFO memory
> DBSIZE
> CLIENT LIST
```

### 11.7 Trouver une erreur dans Sentry

Aller sur `https://sentry.io/organizations/anbri/issues/`, filter par projet `mdl-api`. Chaque erreur a stack trace + valeurs des variables locales + breadcrumbs HTTP.

### 11.8 Renouveler le JWT secret (rotation)

```bash
ssh samir@...
cd /opt/mdl
NEW_JWT=$(openssl rand -hex 32)
sed -i "s|^JWT_SECRET=.*$|JWT_SECRET=${NEW_JWT}|" infra/.env.prod
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d api
# /!\ Tous les utilisateurs sont deconnectes (JWT existants invalides). Prevenir.
```

---

## Section 12 — Estimation temps et checklist go-live

### 12.1 Budget temps

| Section | Effort | Quand |
|---|---|---|
| 1. Prep code (5 P0 + Caddyfile + compose prod) | 4-6 h | J-3 |
| 2. Inscription + provisioning Oracle | 1-3 h (depend dispo ARM) | J-2 |
| 3. Hardening Ubuntu (bootstrap script) | 30 min | J-2 |
| 4. Docker (script auto) | 15 min | J-2 |
| 5. DNS Hostinger + verification | 30 min + 15 min propagation | J-2 |
| 6. Premier deploiement + smoke test | 1-2 h | J-1 |
| 7. CI auto-deploy (cle SSH + secrets + test) | 1 h | J-1 |
| 8. Sentry + Healthchecks + Grafana | 1-2 h | J0 |
| 9. Backups (rclone + script + cron + test restore) | 2 h | J0 |
| 10. Anti-resiliation | 10 min | J0 |
| 11. Documentation runbook | 1 h | J0 |
| **Total** | **~14-18 h sur 4 jours** | |

### 12.2 Checklist go-live (a cocher avant d'annoncer l'URL)

**Code et CI :**
- [ ] `infra/docker-compose.prod.yml` mergé sur `main`
- [ ] `infra/Caddyfile` mergé
- [ ] `infra/.env.prod.example` mergé
- [ ] `Dockerfile.api` pin par digest + TF >= 2.16 + WORKSPACE_ROOT=/data/mdl_workdir
- [ ] `Dockerfile.web` accepte `ARG NEXT_PUBLIC_API_URL`
- [ ] Artefacts Railway supprimes (`Dockerfile.*.railway`, `railway.toml`, `deploy-railway.sh`)
- [ ] `worker` service retire du compose, `celery` retire de `pyproject.toml`
- [ ] `JWT_SECRET` fail-fast dans `apps/api/app/config.py` (validator rejette `change-me*` et < 32 chars)
- [ ] `.github/workflows/ci.yml` : `platforms: linux/amd64,linux/arm64`, `cache scope` par image, job `deploy` actif avec `appleboy/ssh-action`
- [ ] CI verte sur le commit deployable (CI temps total < 25 min)

**Infra Oracle :**
- [ ] Compte Always Free actif, region `eu-frankfurt-1`
- [ ] VCN + Security List (22/80/443) cree
- [ ] VM A1 Flex 4 OCPU/24 GB Ubuntu 22.04 aarch64 lancee
- [ ] Reserved Public IP attachee
- [ ] Block volume 100 GB monte en `/data` via `/etc/fstab`
- [ ] `oracle-bootstrap.sh` execute, user `samir` accessible SSH par cle, `ubuntu` desactive

**Secu :**
- [ ] UFW actif (22/80/443 only), iptables INPUT vide
- [ ] fail2ban actif, jail SSH OK
- [ ] unattended-upgrades active
- [ ] SSH PasswordAuth = no, PermitRootLogin = no
- [ ] `.env.prod` 0600, owner samir, JWT_SECRET unique stocke en Bitwarden

**DNS et TLS :**
- [ ] Record A `Trafic-Tool.anbri-tools-ia.online -> IP reservee` cote Hostinger
- [ ] `dig Trafic-Tool.anbri-tools-ia.online +short` retourne l'IP
- [ ] Caddy logs "certificate obtained successfully"
- [ ] `curl -I https://Trafic-Tool.anbri-tools-ia.online/health` -> 200 OK avec cert Let's Encrypt valide
- [ ] HSTS header present (`Strict-Transport-Security` dans la reponse)
- [ ] `/metrics` retourne 403 depuis l'exterieur

**App :**
- [ ] `/health` retourne `{"status":"ok"}`
- [ ] `/register` cree un user
- [ ] Login -> mode TV
- [ ] Upload + mapping + config + training (max_epochs=2) end-to-end
- [ ] SSE stream `/api/training/stream/{job_id}` recoit des messages
- [ ] Eval -> metriques affichees
- [ ] Carte folium rendue
- [ ] Compteurs Redis persiste apres reload page
- [ ] Sessions expirent apres `SESSION_TTL_SECONDS`

**Observabilite et backups :**
- [ ] Sentry DSN configure, erreur volontaire visible dans dashboard
- [ ] Healthchecks.io check actif, ping recu, alerte mail teste (couper Caddy 2 min)
- [ ] Cron `mdl-backup.sh` execute une fois manuellement (`sudo /usr/local/bin/mdl-backup.sh`)
- [ ] OCI bucket `mdl-backups` contient le 1er tarball
- [ ] Test de restauration sur `/tmp/restore-test` reussit
- [ ] OCI Block Volume Backup Policy "Bronze" activee
- [ ] Cron keepalive Oracle pose

**Auto-deploy :**
- [ ] Cle SSH dediee `oracle_deploy` cree, pub key sur VM
- [ ] Secrets GH `ORACLE_HOST`, `ORACLE_USER`, `ORACLE_SSH_KEY` poses
- [ ] Environnement GH `production` cree avec required reviewer
- [ ] Merge test sur main -> deploy CI approuve -> conteneurs `Created N seconds ago`
- [ ] Rollback teste (`IMAGE_TAG=<SHA-1>` puis up -d)

**Doc :**
- [ ] Ce runbook commit dans `plans/p4-oracle-deploy.md`
- [ ] README projet mis a jour : URL prod, comment SSH, comment deploy
- [ ] Equipe (5-10 users) informee de l'URL, des credentials initiaux, du process inscription

Une fois les 60+ cases cochees, annoncer publiquement l'URL. En cas de doute sur une case, ne pas la cocher : un incident en prod coute 10x plus cher qu'une demi-heure de verification.

---

## Annexe — recap des chemins fichiers a creer/modifier

| Action | Path | Statut |
|---|---|---|
| Creer | `infra/docker-compose.prod.yml` | nouveau |
| Creer | `infra/Caddyfile` | nouveau |
| Creer | `infra/.env.prod.example` | nouveau |
| Modifier | `infra/Dockerfile.api` (digest pin + /data path) | patch |
| Modifier | `infra/Dockerfile.web` (ARG NEXT_PUBLIC_API_URL) | patch |
| Modifier | `apps/api/pyproject.toml` (TF >= 2.16, retirer celery) | patch |
| Modifier | `apps/api/app/config.py` (validator JWT_SECRET) | patch |
| Modifier | `.github/workflows/ci.yml` (multi-arch + deploy SSH) | patch |
| Modifier | `infra/docker-compose.yml` (retirer worker service) | patch |
| Creer | `scripts/oracle-bootstrap.sh` | nouveau |
| Supprimer | `infra/Dockerfile.api.railway` | git rm |
| Supprimer | `infra/Dockerfile.web.railway` | git rm |
| Supprimer | `infra/Dockerfile.worker` | git rm |
| Supprimer | `scripts/deploy-railway.sh` | git rm |
| Supprimer | `railway.toml` | git rm |
| Supprimer | `infra/nginx.conf` (remplace par Caddyfile) | git rm |

Une PR unique "feat(infra): oracle ARM64 deploy + caddy + CI auto-deploy" couvre toutes ces modifs. Reviewer doit verifier que la CI multi-arch construit bien les 2 plateformes (badge `linux/arm64` visible dans l'output `docker buildx`), que l'environnement `production` est bien protege par approbation manuelle, et que `JWT_SECRET` n'a aucun defaut.

Quand la PR merge, le pipeline CI tourne, build les images ARM64, demande l'approbation prod, et deploie automatiquement sur la VM Oracle. Premier deploy "vrai" = couper le mode test et inviter les utilisateurs.
