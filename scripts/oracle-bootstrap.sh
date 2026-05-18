#!/usr/bin/env bash
# scripts/oracle-bootstrap.sh
# Idempotent bring-up for an Oracle Cloud Always Free VM.Standard.A1.Flex (Ubuntu 22.04 aarch64).
# Run ONCE as root (or via sudo) after first SSH as `ubuntu`:
#   sudo SSH_PUBKEY="ssh-ed25519 AAAA... samir@laptop" bash scripts/oracle-bootstrap.sh
#
# Safe to re-run: every step checks current state before mutating.
#
# What it does, in order:
#   1.  apt update + upgrade + autoremove
#   2.  Create user `samir` (configurable via SAMIR_USER) with passwordless sudo + SSH key
#   3.  SSH hardening (PermitRootLogin no, PasswordAuthentication no, AllowUsers samir)
#   4.  UFW (allow 22/80/443, deny all other incoming) + iptables purge (Oracle default DROP)
#   5.  fail2ban (sshd jail, 5 retries / 1h ban)
#   6.  unattended-upgrades (security patches automatic)
#   7.  Docker via get.docker.com + daemon.json (log rotation, live-restore) + add samir to docker group
#   8.  Swap 8GB at /swapfile + vm.swappiness=10
#   9.  Mount /dev/oracleoci/oraclevdb (if attached) at /data via /etc/fstab, mkdir workdir/redis/backups
#   10. Utility tools (curl/git/jq/htop/ncdu/rclone/stress-ng)

set -euo pipefail

# --- config ---
SAMIR_USER="${SAMIR_USER:-samir}"
SSH_PUBKEY="${SSH_PUBKEY:-}"
SWAP_SIZE_GB="${SWAP_SIZE_GB:-8}"
DATA_DEVICE="${DATA_DEVICE:-/dev/oracleoci/oraclevdb}"
DATA_MOUNT="${DATA_MOUNT:-/data}"

# --- safety checks ---
if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (use sudo)" >&2
  exit 1
fi

if [[ -z "${SSH_PUBKEY}" ]]; then
  echo "ERROR: export SSH_PUBKEY='ssh-ed25519 AAAA... user@host' before running" >&2
  echo "Example: sudo SSH_PUBKEY=\"\$(cat ~/.ssh/oracle_a1.pub)\" bash $0" >&2
  exit 1
fi

# --- helpers ---
log() { printf '\n[bootstrap %s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# =============================================================================
# 1. apt update + upgrade
# =============================================================================
log "1/10 apt update + upgrade"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq upgrade
apt-get -y -qq autoremove

# =============================================================================
# 2. user samir + SSH key
# =============================================================================
log "2/10 user '${SAMIR_USER}' + SSH key"
if ! id "${SAMIR_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${SAMIR_USER}"
fi

install -d -m 700 -o "${SAMIR_USER}" -g "${SAMIR_USER}" "/home/${SAMIR_USER}/.ssh"
AUTH_KEYS="/home/${SAMIR_USER}/.ssh/authorized_keys"
touch "${AUTH_KEYS}"
chmod 600 "${AUTH_KEYS}"
chown "${SAMIR_USER}:${SAMIR_USER}" "${AUTH_KEYS}"
if ! grep -qF "${SSH_PUBKEY}" "${AUTH_KEYS}"; then
  echo "${SSH_PUBKEY}" >> "${AUTH_KEYS}"
fi

usermod -aG sudo "${SAMIR_USER}"

SUDOERS_FILE="/etc/sudoers.d/90-${SAMIR_USER}"
if [[ ! -f "${SUDOERS_FILE}" ]]; then
  echo "${SAMIR_USER} ALL=(ALL) NOPASSWD: ALL" > "${SUDOERS_FILE}"
  chmod 0440 "${SUDOERS_FILE}"
  visudo -cf "${SUDOERS_FILE}"  # syntax check
fi

# =============================================================================
# 3. SSH hardening
# =============================================================================
log "3/10 SSH hardening"
SSHD="/etc/ssh/sshd_config"
sed -ri 's/^#?PermitRootLogin.*/PermitRootLogin no/' "${SSHD}"
sed -ri 's/^#?PasswordAuthentication.*/PasswordAuthentication no/' "${SSHD}"
sed -ri 's/^#?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "${SSHD}"
sed -ri 's/^#?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' "${SSHD}"
sed -ri 's/^#?UsePAM.*/UsePAM yes/' "${SSHD}"
if ! grep -q "^AllowUsers ${SAMIR_USER}" "${SSHD}"; then
  echo "AllowUsers ${SAMIR_USER}" >> "${SSHD}"
fi
# Validate config before reload (won't lock us out)
sshd -t
systemctl reload ssh || systemctl reload sshd

# =============================================================================
# 4. UFW + iptables purge
# =============================================================================
log "4/10 UFW + iptables purge (Oracle default DROP)"
apt-get install -y -qq ufw iptables-persistent netfilter-persistent

# Oracle Ubuntu images ship with iptables INPUT policy DROP. Wipe it so UFW takes over.
iptables -F INPUT 2>/dev/null || true
iptables -P INPUT ACCEPT 2>/dev/null || true
iptables -F FORWARD 2>/dev/null || true
iptables -P FORWARD ACCEPT 2>/dev/null || true
netfilter-persistent save || true

# Reset UFW only if not already enabled — avoids dropping live SSH
if ! ufw status | grep -q "Status: active"; then
  ufw --force reset
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow OpenSSH
  ufw allow http
  ufw allow https
  ufw --force enable
else
  # already active — just ensure required rules exist (idempotent)
  ufw allow OpenSSH || true
  ufw allow http   || true
  ufw allow https  || true
fi

# =============================================================================
# 5. fail2ban
# =============================================================================
log "5/10 fail2ban"
apt-get install -y -qq fail2ban
JAIL_LOCAL="/etc/fail2ban/jail.d/sshd.local"
if [[ ! -f "${JAIL_LOCAL}" ]]; then
  cat > "${JAIL_LOCAL}" <<'EOF'
[sshd]
enabled  = true
port     = ssh
filter   = sshd
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
fi
systemctl enable --now fail2ban
systemctl restart fail2ban

# =============================================================================
# 6. unattended-upgrades
# =============================================================================
log "6/10 unattended-upgrades"
apt-get install -y -qq unattended-upgrades apt-listchanges
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF

# =============================================================================
# 7. Docker
# =============================================================================
log "7/10 Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "${SAMIR_USER}"

mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  },
  "default-address-pools": [
    {"base": "172.30.0.0/16", "size": 24}
  ],
  "live-restore": true,
  "userland-proxy": false,
  "no-new-privileges": true
}
EOF
systemctl enable docker
systemctl restart docker

# Sanity check
log "    docker hello-world test"
docker run --rm hello-world >/dev/null

# =============================================================================
# 8. Swap
# =============================================================================
log "8/10 swap ${SWAP_SIZE_GB}GB"
if [[ ! -f /swapfile ]]; then
  fallocate -l "${SWAP_SIZE_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
fi
if ! grep -q '^/swapfile' /etc/fstab; then
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10 >/dev/null
echo 'vm.swappiness=10' > /etc/sysctl.d/99-swap.conf

# =============================================================================
# 9. Mount block volume at /data
# =============================================================================
log "9/10 block volume at ${DATA_MOUNT}"
if [[ -b "${DATA_DEVICE}" ]]; then
  if ! mountpoint -q "${DATA_MOUNT}"; then
    if ! blkid "${DATA_DEVICE}" >/dev/null 2>&1; then
      log "    formatting ${DATA_DEVICE} as ext4"
      mkfs.ext4 -F "${DATA_DEVICE}"
    fi
    mkdir -p "${DATA_MOUNT}"
    UUID=$(blkid -s UUID -o value "${DATA_DEVICE}")
    if ! grep -q "${UUID}" /etc/fstab; then
      echo "UUID=${UUID} ${DATA_MOUNT} ext4 defaults,_netdev,nofail 0 2" >> /etc/fstab
    fi
    mount -a
  fi
else
  log "    no block volume at ${DATA_DEVICE} — using boot disk for ${DATA_MOUNT}"
  mkdir -p "${DATA_MOUNT}"
fi

install -d -o "${SAMIR_USER}" -g "${SAMIR_USER}" "${DATA_MOUNT}/mdl_workdir"
install -d -o "${SAMIR_USER}" -g "${SAMIR_USER}" "${DATA_MOUNT}/redis"
install -d -o "${SAMIR_USER}" -g "${SAMIR_USER}" "${DATA_MOUNT}/backups"

# =============================================================================
# 10. utility tools
# =============================================================================
log "10/10 utility tools (curl/git/jq/htop/ncdu/rclone/stress-ng)"
apt-get install -y -qq curl git jq htop ncdu rclone stress-ng ca-certificates gnupg

# =============================================================================
log "DONE."
cat <<EOF

============================================================
 Oracle VM bootstrap completed.
============================================================
 Next steps:
   1. From your laptop:
        ssh -i ~/.ssh/oracle_a1 ${SAMIR_USER}@<PUBLIC_IP>
      You should land directly as '${SAMIR_USER}' (no password).

   2. Verify ssh hardening:
        sudo ss -lntp | grep :22
        sudo ufw status verbose
        sudo systemctl status fail2ban --no-pager

   3. Disable the default 'ubuntu' user (optional, after confirming ${SAMIR_USER} works):
        sudo usermod -L ubuntu
        sudo sed -i '/ubuntu/d' /etc/sudoers.d/90-cloud-init-users

   4. Pull the repo and start the stack:
        sudo mkdir -p /opt/mdl && sudo chown ${SAMIR_USER}: /opt/mdl
        git clone https://github.com/anbsamsam17/Anbri-Tools-portfolio.git /opt/mdl
        cd /opt/mdl
        cp infra/.env.prod.example infra/.env.prod
        # edit JWT_SECRET, then:
        docker compose -f infra/docker-compose.prod.yml --env-file infra/.env.prod up -d
============================================================
EOF
