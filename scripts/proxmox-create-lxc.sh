#!/usr/bin/env bash
# Crea su Proxmox VE un container LXC Debian 12 che esegue "Povero e senza biga".
# Non serve la virtualizzazione KVM (funziona anche se nel BIOS è disattivata o se
# Proxmox gira dentro un'altra VM) ed è più leggero di una VM: niente Docker, l'app
# gira direttamente con Python + systemd.
#
# Da lanciare sull'host Proxmox come root:
#   curl -fsSLO https://raw.githubusercontent.com/locohub-it/povero-senza-biga/main/scripts/proxmox-create-lxc.sh
#   less proxmox-create-lxc.sh                                 # leggilo prima di eseguirlo
#   bash proxmox-create-lxc.sh                                 # sito aperto, senza password
#   APP_PASSWORD='la-tua-password' bash proxmox-create-lxc.sh  # sito con password condivisa
#
# Per entrare nel container via SSH dal tuo computer, passa la tua chiave pubblica:
#   SSH_PUBKEY='ssh-ed25519 AAAA... tu@mac' bash proxmox-create-lxc.sh
# Dalla shell dell'host puoi sempre entrare con:  pct enter <CTID>
#
# Esempio con IP statico:
#   CTID=210 IP_CIDR=192.168.1.50/24 GATEWAY=192.168.1.1 bash proxmox-create-lxc.sh

set -euo pipefail
trap 'rc=$?; printf "\033[1;31mERRORE:\033[0m comando fallito (codice %s) alla riga %s: %s\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2' ERR

# ---------------- parametri ----------------
CTID="${CTID:-}"                                  # vuoto = primo ID libero
CT_NAME="${CT_NAME:-povero-senza-biga}"
STORAGE="${STORAGE:-local-lvm}"                   # dove va il disco del container
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"     # dove scaricare il template Debian
BRIDGE="${BRIDGE:-vmbr0}"
VLAN_TAG="${VLAN_TAG:-}"
MEMORY="${MEMORY:-1024}"                          # MB
SWAP="${SWAP:-512}"                               # MB
CORES="${CORES:-1}"
DISK_SIZE="${DISK_SIZE:-6}"                       # GB
IP_CIDR="${IP_CIDR:-dhcp}"                        # "dhcp" oppure es. 192.168.1.50/24
GATEWAY="${GATEWAY:-}"                            # obbligatorio con IP statico
DNS="${DNS:-}"                                    # es. "1.1.1.1"
SSH_PUBKEY="${SSH_PUBKEY:-}"                      # chiave pubblica da autorizzare per root
SSH_KEY_FILE="${SSH_KEY_FILE:-}"                  # oppure un file di chiavi pubbliche
ROOT_PASSWORD="${ROOT_PASSWORD:-}"                # vuota = generata e stampata alla fine
APP_PASSWORD="${APP_PASSWORD:-}"                  # vuota = sito aperto senza password
APP_PORT="${APP_PORT:-8000}"
REPO_URL="${REPO_URL:-https://github.com/locohub-it/povero-senza-biga.git}"
BRANCH="${BRANCH:-main}"
START_ON_BOOT="${START_ON_BOOT:-1}"

# ---------------- helper ----------------
log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }
rand() { openssl rand -hex "$1"; }

[[ $EUID -eq 0 ]] || die "va eseguito come root sull'host Proxmox"
for c in pct pveam pvesh openssl; do
  command -v "$c" >/dev/null || die "comando '$c' non trovato: sei sull'host Proxmox?"
done

# ---------------- CTID ----------------
if [[ -z "$CTID" ]]; then
  CTID="$(pvesh get /cluster/nextid)"
fi
if pct status "$CTID" >/dev/null 2>&1 || qm status "$CTID" >/dev/null 2>&1; then
  die "l'ID $CTID è già usato: scegline un altro (es. CTID=$((CTID + 1)))"
fi

# ---------------- rete ----------------
if [[ "$IP_CIDR" == "dhcp" ]]; then
  NET0="name=eth0,bridge=${BRIDGE},ip=dhcp"
else
  [[ -n "$GATEWAY" ]] || die "con IP statico serve anche GATEWAY"
  NET0="name=eth0,bridge=${BRIDGE},ip=${IP_CIDR},gw=${GATEWAY}"
fi
if [[ -n "$VLAN_TAG" ]]; then NET0+=",tag=${VLAN_TAG}"; fi

# ---------------- chiavi SSH e password ----------------
KEYS_FILE="$(mktemp)"
cleanup() { rm -f "$KEYS_FILE" "${SETUP_FILE:-}"; }
trap cleanup EXIT
if [[ -n "$SSH_PUBKEY" ]]; then printf '%s\n' "$SSH_PUBKEY" >>"$KEYS_FILE"; fi
if [[ -n "$SSH_KEY_FILE" ]]; then
  [[ -r "$SSH_KEY_FILE" ]] || die "non riesco a leggere $SSH_KEY_FILE"
  cat "$SSH_KEY_FILE" >>"$KEYS_FILE"
fi
GENERATED_ROOT_PASSWORD=0
if [[ -z "$ROOT_PASSWORD" ]]; then
  ROOT_PASSWORD="$(rand 8)"
  GENERATED_ROOT_PASSWORD=1
fi
SECRET_KEY="$(rand 24)"
if [[ -z "$APP_PASSWORD" ]]; then
  log "nessuna APP_PASSWORD: il sito sarà aperto a chiunque raggiunga il container (va bene in rete di casa)"
fi

# ---------------- template Debian 12 ----------------
log "cerco il template Debian 12…"
pveam update >/dev/null || warn "pveam update non riuscito, uso l'elenco template già presente"
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep '^debian-12-standard' | sort -V | tail -n1 || true)"
[[ -n "$TEMPLATE" ]] || die "nessun template debian-12-standard trovato (prova: pveam update)"
if [[ "$(pveam list "$TEMPLATE_STORAGE")" != *"$TEMPLATE"* ]]; then
  log "scarico il template $TEMPLATE su $TEMPLATE_STORAGE"
  pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
else
  log "template già presente: $TEMPLATE"
fi

# ---------------- creazione container ----------------
log "creo il container $CTID ($CT_NAME)"
CREATE_ARGS=(
  --hostname "$CT_NAME"
  --memory "$MEMORY" --swap "$SWAP" --cores "$CORES"
  --rootfs "${STORAGE}:${DISK_SIZE}"
  --net0 "$NET0"
  --unprivileged 1
  --features nesting=1
  --onboot "$START_ON_BOOT"
  --ostype debian
  --timezone Europe/Rome
  --password "$ROOT_PASSWORD"
)
if [[ -s "$KEYS_FILE" ]]; then CREATE_ARGS+=(--ssh-public-keys "$KEYS_FILE"); fi
if [[ -n "$DNS" ]]; then CREATE_ARGS+=(--nameserver "$DNS"); fi
pct create "$CTID" "${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}" "${CREATE_ARGS[@]}"

log "avvio il container"
pct start "$CTID"

log "attendo la rete (max 2 minuti)…"
for _ in $(seq 1 60); do
  if pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1; then break; fi
  sleep 2
done
pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 \
  || die "il container $CTID non raggiunge internet: controlla bridge/IP/gateway/DNS (pct enter $CTID)"

# ---------------- installazione app nel container ----------------
SETUP_FILE="$(mktemp)"
cat >"$SETUP_FILE" <<EOF
#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3 python3-venv ca-certificates curl unattended-upgrades openssh-server

id psb >/dev/null 2>&1 || useradd --system --home /opt/psb --shell /usr/sbin/nologin psb
mkdir -p /opt/psb
if [[ ! -d /opt/psb/app/.git ]]; then
  git clone --branch '${BRANCH}' '${REPO_URL}' /opt/psb/app
fi
python3 -m venv /opt/psb/venv
/opt/psb/venv/bin/pip install -q --upgrade pip
/opt/psb/venv/bin/pip install -q -r /opt/psb/app/requirements.txt

umask 077
cat >/opt/psb/.env <<'ENVEOF'
APP_PASSWORD=${APP_PASSWORD}
SECRET_KEY=${SECRET_KEY}
CURRENCY=EUR
LANGUAGE=it
MAX_CONCURRENCY=4
MAX_QUERIES=48
CACHE_TTL_MINUTES=30
ENVEOF
umask 022
chown -R psb:psb /opt/psb

cat >/etc/systemd/system/povero-senza-biga.service <<'UNITEOF'
[Unit]
Description=Povero e senza biga
After=network-online.target
Wants=network-online.target

[Service]
User=psb
WorkingDirectory=/opt/psb/app
EnvironmentFile=/opt/psb/.env
ExecStart=/opt/psb/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT}
Restart=always
RestartSec=5
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
UNITEOF

cat >/usr/local/bin/psb-update <<'UPDEOF'
#!/bin/sh
# Aggiorna il sito all'ultima versione su GitHub
set -e
cd /opt/psb/app
runuser -u psb -- git pull --ff-only
runuser -u psb -- /opt/psb/venv/bin/pip install -q -r requirements.txt
systemctl restart povero-senza-biga
echo "aggiornato: \$(runuser -u psb -- git log --oneline -1)"
UPDEOF
chmod 755 /usr/local/bin/psb-update

systemctl daemon-reload
systemctl enable --now povero-senza-biga
EOF

log "installo l'app nel container (1-3 minuti)…"
pct push "$CTID" "$SETUP_FILE" /root/psb-setup.sh --perms 0700
pct exec "$CTID" -- bash /root/psb-setup.sh
pct exec "$CTID" -- rm -f /root/psb-setup.sh

# ---------------- verifica ----------------
CT_IP="$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}' || true)"
OK=0
for _ in $(seq 1 15); do
  if pct exec "$CTID" -- curl -fsS "http://127.0.0.1:${APP_PORT}/healthz" >/dev/null 2>&1; then OK=1; break; fi
  sleep 2
done

echo
if [[ $OK -eq 1 ]]; then
  log "Container $CTID pronto: il sito risponde."
else
  warn "il container è creato ma il sito non risponde ancora: controlla con  pct exec $CTID -- journalctl -u povero-senza-biga -n 50"
fi
echo "    Sito:   http://${CT_IP:-<ip-del-container>}:${APP_PORT}"
echo "    Shell:  pct enter $CTID   (dall'host Proxmox)"
if [[ -s "$KEYS_FILE" ]]; then echo "    SSH:    ssh root@${CT_IP:-<ip>}"; fi
if [[ $GENERATED_ROOT_PASSWORD -eq 1 ]]; then echo "    Password root del container: ${ROOT_PASSWORD}"; fi
if [[ -n "$APP_PASSWORD" ]]; then
  echo "    Il sito chiede la password indicata in APP_PASSWORD"
else
  echo "    Sito senza password (APP_PASSWORD vuota)"
fi
echo "    Aggiornare all'ultima versione:  pct exec $CTID -- psb-update"
echo "    Log del sito:  pct exec $CTID -- journalctl -u povero-senza-biga -f"
