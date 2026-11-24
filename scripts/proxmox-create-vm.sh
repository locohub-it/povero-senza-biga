#!/usr/bin/env bash
# Crea su Proxmox VE una VM Debian 12 (cloud-init) che esegue "Povero e senza biga" in Docker.
#
# Da lanciare sull'host Proxmox come root, ad esempio:
#   curl -fsSLO https://raw.githubusercontent.com/locohub-it/povero-senza-biga/main/scripts/proxmox-create-vm.sh
#   less proxmox-create-vm.sh          # leggilo prima di eseguirlo
#   bash proxmox-create-vm.sh                                  # sito aperto, senza password
#   APP_PASSWORD='la-tua-password' bash proxmox-create-vm.sh   # sito con password condivisa
#
# Per entrare nella VM via SSH dal tuo computer, passa la tua chiave pubblica
# (il contenuto di ~/.ssh/id_ed25519.pub del tuo computer):
#   SSH_PUBKEY='ssh-ed25519 AAAA... tu@mac' bash proxmox-create-vm.sh
#
# Tutti i parametri si cambiano con variabili d'ambiente (vedi sotto i valori predefiniti).
# Esempio con IP statico:
#   VMID=210 IP_CIDR=192.168.1.50/24 GATEWAY=192.168.1.1 bash proxmox-create-vm.sh

set -euo pipefail
# Mai più uscite silenziose: se un comando fallisce, dice quale e a che riga.
trap 'rc=$?; printf "\033[1;31mERRORE:\033[0m comando fallito (codice %s) alla riga %s: %s\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2' ERR

# ---------------- parametri ----------------
VMID="${VMID:-}"                                  # vuoto = primo ID libero
VM_NAME="${VM_NAME:-povero-senza-biga}"
STORAGE="${STORAGE:-local-lvm}"                   # dove va il disco della VM
SNIPPET_STORAGE="${SNIPPET_STORAGE:-local}"       # storage con contenuto "snippets" (per cloud-init)
BRIDGE="${BRIDGE:-vmbr0}"
VLAN_TAG="${VLAN_TAG:-}"
MEMORY="${MEMORY:-1024}"                          # MB
CORES="${CORES:-1}"
DISK_SIZE="${DISK_SIZE:-8G}"
IP_CIDR="${IP_CIDR:-dhcp}"                        # "dhcp" oppure es. 192.168.1.50/24
GATEWAY="${GATEWAY:-}"                            # obbligatorio con IP statico
DNS="${DNS:-}"                                    # es. "1.1.1.1"
VM_USER="${VM_USER:-psb}"
SSH_KEY_FILE="${SSH_KEY_FILE:-}"                  # file con chiavi pubbliche da autorizzare
SSH_PUBKEY="${SSH_PUBKEY:-}"                      # oppure la chiave pubblica direttamente
VM_PASSWORD="${VM_PASSWORD:-}"                    # password utente VM; vuota e senza chiavi SSH = generata
APP_PASSWORD="${APP_PASSWORD:-}"                  # vuoto = sito aperto senza password
HOST_PORT="${HOST_PORT:-8000}"
REPO_URL="${REPO_URL:-https://github.com/locohub-it/povero-senza-biga.git}"
BRANCH="${BRANCH:-main}"
IMAGE_URL="${IMAGE_URL:-https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2}"
IMAGE_DIR="${IMAGE_DIR:-/var/lib/vz/template/cache}"
START_ON_BOOT="${START_ON_BOOT:-1}"

# ---------------- helper ----------------
log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERRORE:\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "va eseguito come root sull'host Proxmox"
command -v qm >/dev/null || die "comando 'qm' non trovato: sei sull'host Proxmox?"
command -v pvesm >/dev/null || die "comando 'pvesm' non trovato"

# ---------------- VMID ----------------
if [[ -z "$VMID" ]]; then
  VMID="$(pvesh get /cluster/nextid)"
fi
if qm status "$VMID" >/dev/null 2>&1; then
  die "la VM $VMID esiste già: scegli un altro VMID (es. VMID=$((VMID + 1)))"
fi

# ---------------- rete ----------------
if [[ "$IP_CIDR" == "dhcp" ]]; then
  IPCONFIG="ip=dhcp"
else
  [[ -n "$GATEWAY" ]] || die "con IP statico serve anche GATEWAY"
  IPCONFIG="ip=${IP_CIDR},gw=${GATEWAY}"
fi
NET0="virtio,bridge=${BRIDGE}"
[[ -n "$VLAN_TAG" ]] && NET0+=",tag=${VLAN_TAG}"

# ---------------- chiave SSH ----------------
SSH_KEYS="${SSH_PUBKEY}"$'\n'
if [[ -n "$SSH_KEY_FILE" ]]; then
  [[ -r "$SSH_KEY_FILE" ]] || die "non riesco a leggere $SSH_KEY_FILE"
  SSH_KEYS+="$(grep -E '^(ssh-|ecdsa-|sk-)' "$SSH_KEY_FILE" || true)"
else
  for f in /root/.ssh/authorized_keys /root/.ssh/id_ed25519.pub /root/.ssh/id_rsa.pub; do
    if [[ -r "$f" ]]; then
      SSH_KEYS+="$(grep -E '^(ssh-|ecdsa-|sk-)' "$f" || true)"$'\n'
    fi
  done
fi
SSH_KEYS="$(printf '%s\n' "$SSH_KEYS" | sed '/^[[:space:]]*$/d' | sort -u)"

# Stringa casuale. NON usare "tr </dev/urandom | head": con pipefail il SIGPIPE
# fa uscire lo script in silenzio (era il bug della prima versione).
rand() { openssl rand -hex "$1"; }

GENERATED_VM_PASSWORD=0
if [[ -z "$SSH_KEYS" && -z "$VM_PASSWORD" ]]; then
  VM_PASSWORD="$(rand 8)"
  GENERATED_VM_PASSWORD=1
  warn "nessuna chiave SSH: genero una password per l'utente $VM_USER (la stampo alla fine)"
fi

# ---------------- password del sito ----------------
if [[ -z "$APP_PASSWORD" ]]; then
  log "nessuna APP_PASSWORD: il sito sarà aperto a chiunque raggiunga la VM (va bene in rete di casa)"
fi
SECRET_KEY="$(rand 24)"

# ---------------- storage snippets ----------------
STORAGE_JSON="$(pvesh get "/storage/${SNIPPET_STORAGE}" --output-format json 2>/dev/null)" \
  || die "storage $SNIPPET_STORAGE non trovato"
SNIPPET_CONTENT="$(printf '%s' "$STORAGE_JSON" | sed -n 's/.*"content" *: *"\([^"]*\)".*/\1/p')"
if [[ ",$SNIPPET_CONTENT," != *",snippets,"* ]]; then
  log "abilito il contenuto 'snippets' sullo storage $SNIPPET_STORAGE (serve per cloud-init)"
  pvesm set "$SNIPPET_STORAGE" --content "${SNIPPET_CONTENT:+$SNIPPET_CONTENT,}snippets"
fi
SNIPPET_DIR="$(pvesm path "${SNIPPET_STORAGE}:snippets/x" | xargs dirname)"
mkdir -p "$SNIPPET_DIR"
SNIPPET_NAME="psb-${VMID}-user.yaml"
SNIPPET_PATH="${SNIPPET_DIR}/${SNIPPET_NAME}"

# ---------------- immagine cloud ----------------
mkdir -p "$IMAGE_DIR"
IMAGE_PATH="${IMAGE_DIR}/$(basename "$IMAGE_URL")"
if [[ ! -s "$IMAGE_PATH" ]]; then
  log "scarico l'immagine Debian 12 cloud…"
  curl -fL --retry 3 -o "${IMAGE_PATH}.part" "$IMAGE_URL"
  mv "${IMAGE_PATH}.part" "$IMAGE_PATH"
else
  log "immagine già presente: $IMAGE_PATH"
fi

# ---------------- cloud-init user-data ----------------
log "scrivo la configurazione cloud-init in $SNIPPET_PATH"
umask 077
{
  cat <<EOF
#cloud-config
hostname: ${VM_NAME}
manage_etc_hosts: true
timezone: Europe/Rome
users:
  - name: ${VM_USER}
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
EOF
  if [[ -n "$VM_PASSWORD" ]]; then
    echo "    lock_passwd: false"
    printf "    plain_text_passwd: '%s'\n" "${VM_PASSWORD//\'/\'\'}"
  else
    echo "    lock_passwd: true"
  fi
  if [[ -n "$SSH_KEYS" ]]; then
    echo "    ssh_authorized_keys:"
    while IFS= read -r k; do printf '      - %s\n' "$k"; done <<<"$SSH_KEYS"
  fi
  cat <<EOF
package_update: true
package_upgrade: true
packages: [qemu-guest-agent, git, ca-certificates, curl, gnupg, unattended-upgrades]
write_files:
  - path: /opt/psb/.env
    permissions: "0600"
    content: |
      APP_PASSWORD=${APP_PASSWORD}
      SECRET_KEY=${SECRET_KEY}
      CURRENCY=EUR
      LANGUAGE=it
      MAX_CONCURRENCY=4
      MAX_QUERIES=48
      CACHE_TTL_MINUTES=30
      HOST_PORT=${HOST_PORT}
  - path: /usr/local/bin/psb-update
    permissions: "0755"
    content: |
      #!/bin/sh
      # Aggiorna il sito all'ultima versione su GitHub
      set -e
      cd /opt/psb/app
      git pull --ff-only
      docker compose --env-file /opt/psb/.env up -d --build
      docker image prune -f
runcmd:
  - systemctl enable --now qemu-guest-agent
  - install -m 0755 -d /etc/apt/keyrings
  - curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  - chmod a+r /etc/apt/keyrings/docker.asc
  - sh -c 'echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \$(. /etc/os-release && echo \$VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list'
  - apt-get update
  - DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  - usermod -aG docker ${VM_USER}
  - git clone --branch ${BRANCH} ${REPO_URL} /opt/psb/app
  - ln -sf /opt/psb/.env /opt/psb/app/.env
  - cd /opt/psb/app && docker compose --env-file /opt/psb/.env up -d --build
final_message: "Povero e senza biga pronto dopo \$UPTIME secondi"
EOF
} >"$SNIPPET_PATH"
umask 022

# ---------------- creazione VM ----------------
log "creo la VM $VMID ($VM_NAME)"
qm create "$VMID" \
  --name "$VM_NAME" \
  --memory "$MEMORY" \
  --cores "$CORES" \
  --cpu host \
  --net0 "$NET0" \
  --scsihw virtio-scsi-single \
  --ostype l26 \
  --agent enabled=1 \
  --serial0 socket --vga serial0 \
  --onboot "$START_ON_BOOT"

log "importo il disco su $STORAGE"
if ! qm set "$VMID" --scsi0 "${STORAGE}:0,import-from=${IMAGE_PATH},discard=on,ssd=1" >/dev/null 2>&1; then
  # Proxmox 7: niente import-from, si usa importdisk
  qm importdisk "$VMID" "$IMAGE_PATH" "$STORAGE" >/dev/null
  DISK_REF="$(qm config "$VMID" | awk -F': ' '/^unused0/ {print $2}')"
  qm set "$VMID" --scsi0 "${DISK_REF},discard=on,ssd=1" >/dev/null
fi
qm resize "$VMID" scsi0 "$DISK_SIZE" >/dev/null

qm set "$VMID" --ide2 "${STORAGE}:cloudinit" --boot order=scsi0 >/dev/null
qm set "$VMID" --ipconfig0 "$IPCONFIG" --cicustom "user=${SNIPPET_STORAGE}:snippets/${SNIPPET_NAME}" >/dev/null
[[ -n "$DNS" ]] && qm set "$VMID" --nameserver "$DNS" >/dev/null

log "avvio la VM"
qm start "$VMID"

# ---------------- attesa IP ----------------
VM_IP=""
if [[ "$IP_CIDR" != "dhcp" ]]; then
  VM_IP="${IP_CIDR%/*}"
else
  log "attendo che la VM riceva un IP (max 5 minuti)…"
  for _ in $(seq 1 60); do
    VM_IP="$(qm guest cmd "$VMID" network-get-interfaces 2>/dev/null \
      | grep -oE '"ip-address" *: *"[0-9]+(\.[0-9]+){3}"' \
      | grep -oE '[0-9]+(\.[0-9]+){3}' | grep -v '^127\.' | head -n1 || true)"
    [[ -n "$VM_IP" ]] && break
    sleep 5
  done
fi

echo
log "VM $VMID creata."
if [[ -n "$VM_IP" ]]; then
  echo "    IP:   $VM_IP"
  echo "    Sito: http://${VM_IP}:${HOST_PORT}   (pronto dopo 3-6 minuti: installa Docker e costruisce l'immagine)"
  echo "    SSH:  ssh ${VM_USER}@${VM_IP}"
else
  echo "    IP non ancora disponibile: controllalo nel riepilogo della VM in Proxmox."
fi
if [[ -n "$APP_PASSWORD" ]]; then
  echo "    Il sito chiede la password che hai indicato in APP_PASSWORD"
else
  echo "    Sito senza password (APP_PASSWORD vuota)"
fi
if [[ $GENERATED_VM_PASSWORD -eq 1 ]]; then
  echo "    Password utente ${VM_USER} (console Proxmox / SSH): ${VM_PASSWORD}"
fi
echo "    Avanzamento installazione: ssh nella VM e 'sudo tail -f /var/log/cloud-init-output.log'"
echo "    Aggiornare all'ultima versione: ssh nella VM e 'sudo psb-update'"
echo "    La configurazione (con la password) è in $SNIPPET_PATH e in /opt/psb/.env nella VM."
