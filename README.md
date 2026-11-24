# Povero e senza biga

Cercavoli per viaggi improvvisati ed extreme low cost: più aeroporti di partenza, più aeroporti di arrivo, andata e ritorno indipendenti.

## Perché

I siti più famosi gestiscono male la ricerca con più aeroporti di partenza **e** di arrivo. Se vivi tra due aeroporti e vuoi andare in una regione con altri due scali comodi, finisci a fare 4 ricerche a mano e a confrontare i risultati a occhio.

Qui indichi N aeroporti di partenza e M di arrivo e l'app li incrocia tutti. Andata e ritorno sono cercati come **sole andate indipendenti**: puoi partire da un aeroporto e rientrare in un altro, anche con compagnie diverse. Alla fine l'app abbina andate e ritorni compatibili e ti mostra le migliori combinazioni A/R per prezzo totale.

## Funzioni

- **Multi-aeroporto**: fino a 6 aeroporti di partenza e 6 di arrivo; per il ritorno si possono scegliere aeroporti diversi da quelli dell'andata (di default si usano quelli speculari).
- **Flessibilità fino a ±3 giorni** sulle date.
- **Filtri orari** su partenza e arrivo, separati per andata e ritorno. Esempio: "arrivo entro le 20:00" per fare il check-in. Attenzione: se imposti solo "entro le X", gli arrivi tra mezzanotte e le 05:00 vengono esclusi (altrimenti un volo che atterra alle 00:25 passerebbe come "entro le 20"). Per includerli imposta anche l'orario "dalle".
- **Scali anche lunghissimi**: gli scali lunghi sono evidenziati come "città gratis" (una gita gratuita durante la coincidenza) e c'è il filtro "solo scali lunghi" (soglia predefinita 6 ore).
- Scali massimi, durata minima/massima dello scalo, prezzo massimo, durata massima del viaggio.
- Tempo minimo di permanenza a destinazione tra arrivo dell'andata e partenza del ritorno.
- **Link agli alloggi economici** già filtrati: Hostelworld, Booking.com (ostelli, B&B, affittacamere, con budget massimo a notte), Airbnb (stanze private), Google Hotels, Couchsurfing.
- **Gruppi di aeroporti preferiti** per rilanciare ricerche frequenti.
- **Password condivisa** per far usare il sito agli amici.

## Come funziona e limiti

- I voli arrivano da **Google Flights** tramite la libreria open source [fast-flights](https://github.com/AWeirdDev/flights). Non è un'API ufficiale e non serve nessuna chiave. Può smettere di funzionare se Google cambia la pagina.
- Usalo con moderazione: parallelismo e numero massimo di query per ricerca sono limitati (`MAX_CONCURRENCY`, `MAX_QUERIES`) e i risultati restano in cache 30 minuti, per non farsi bloccare da Google.
- I prezzi sono **indicativi**: si prenota sul sito della compagnia o su Google Flights, usando il link presente in ogni risultato.
- Gli alloggi sono **link di ricerca già filtrati**, non prezzi in tempo reale: non esistono API pubbliche gratuite per questo.

## Avvio in locale (macOS/Linux)

Serve Python 3.12 o superiore.

```bash
git clone https://github.com/locohub-it/povero-senza-biga.git
cd povero-senza-biga

# con uv
uv venv && source .venv/bin/activate
uv pip install -r requirements-dev.txt

# oppure con venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
uvicorn app.main:app --reload --env-file .env
```

Apri <http://localhost:8000>.

L'app legge le variabili d'ambiente, non il file `.env` direttamente: per questo si usa `--env-file .env` (funziona perché `uvicorn[standard]` include `python-dotenv`). In alternativa: `set -a; source .env; set +a`.

Con `APP_PASSWORD` vuota non c'è nessun login: va bene in locale, non in rete.

### Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `APP_PASSWORD` | vuota | password condivisa; vuota = nessun login |
| `SECRET_KEY` | `dev-secret-change-me` | chiave per firmare il cookie di sessione, usane una lunga e casuale |
| `CURRENCY` | `EUR` | valuta dei prezzi |
| `LANGUAGE` | `it` | lingua richiesta a Google Flights |
| `MAX_CONCURRENCY` | `4` | query in parallelo verso Google |
| `MAX_QUERIES` | `48` | query massime per singola ricerca |
| `CACHE_TTL_MINUTES` | `30` | durata della cache dei risultati |

## Docker

```bash
cp .env.example .env
# modifica .env: almeno APP_PASSWORD e SECRET_KEY
docker compose up -d --build
```

Il sito risponde su `http://localhost:8000` (cambia la porta con `HOST_PORT` in `.env`).

## Proxmox: container LXC (consigliato)

`scripts/proxmox-create-lxc.sh` crea un container **LXC Debian 12** e ci installa l'app con Python e systemd (niente Docker). **Non richiede KVM**: funziona anche se la virtualizzazione è disattivata nel BIOS o se Proxmox gira dentro un'altra VM (errore *"KVM virtualisation configured, but not available"*). È anche più leggero di una VM.

Sull'host Proxmox, come root:

```bash
curl -fsSLO https://raw.githubusercontent.com/locohub-it/povero-senza-biga/main/scripts/proxmox-create-lxc.sh
less proxmox-create-lxc.sh     # leggilo prima di eseguirlo
SSH_PUBKEY='ssh-ed25519 AAAA... tu@computer' bash proxmox-create-lxc.sh
```

Alla fine stampa l'indirizzo del sito, la password di root del container (generata, se non passi `ROOT_PASSWORD`) e verifica che il sito risponda. Senza `APP_PASSWORD` il sito è aperto senza login.

| Variabile | Default | Descrizione |
|---|---|---|
| `CTID` | primo libero | ID del container |
| `CT_NAME` | `povero-senza-biga` | hostname |
| `STORAGE` | `local-lvm` | storage del disco |
| `TEMPLATE_STORAGE` | `local` | dove scaricare il template Debian |
| `BRIDGE` / `VLAN_TAG` | `vmbr0` / vuoto | rete |
| `IP_CIDR` / `GATEWAY` / `DNS` | `dhcp` / vuoto / vuoto | IP statico, es. `192.168.1.50/24` |
| `MEMORY` / `SWAP` / `CORES` / `DISK_SIZE` | `1024` / `512` / `1` / `6` (GB) | risorse |
| `SSH_PUBKEY` / `SSH_KEY_FILE` | vuoto | chiavi pubbliche autorizzate per root |
| `ROOT_PASSWORD` | generata | password di root del container |
| `APP_PASSWORD` | vuota | password del sito; vuota = nessun login |
| `APP_PORT` | `8000` | porta del sito |

Comandi utili dall'host: `pct enter <CTID>` (shell), `pct exec <CTID> -- /usr/local/bin/psb-update` (aggiorna all'ultima versione), `pct exec <CTID> -- journalctl -u povero-senza-biga -f` (log).

## Proxmox: VM con Docker (richiede KVM)

`scripts/proxmox-create-vm.sh` crea su Proxmox VE una VM **Debian 12** dall'immagine cloud ufficiale, la configura con **cloud-init**, installa **Docker**, clona questo repository e avvia l'app con Docker Compose. Mette il file `.env` in `/opt/psb/.env` (con `SECRET_KEY` casuale), abilita l'avvio automatico della VM e installa il comando `psb-update`.

Sull'host Proxmox, come root:

```bash
curl -fsSLO https://raw.githubusercontent.com/locohub-it/povero-senza-biga/main/scripts/proxmox-create-vm.sh
less proxmox-create-vm.sh     # leggilo prima di eseguirlo
SSH_PUBKEY='ssh-ed25519 AAAA... tu@computer' bash proxmox-create-vm.sh
```

- Senza `APP_PASSWORD` il sito è **aperto, senza login** (va bene in rete di casa). Con `APP_PASSWORD='...'` chiede la password condivisa.
- `SSH_PUBKEY` è la tua chiave pubblica (contenuto di `~/.ssh/id_ed25519.pub` sul tuo computer) per entrare nella VM con `ssh psb@<ip>`. Se non c'è nessuna chiave, lo script genera una password per l'utente `psb` e la stampa alla fine (vale anche per la console Proxmox).
- Se qualcosa va storto lo script stampa `ERRORE:` con il comando e la riga che hanno fallito.

L'installazione richiede 3-6 minuti dopo l'avvio della VM.

Principali variabili (tutte opzionali):

| Variabile | Default | Descrizione |
|---|---|---|
| `VMID` | primo libero | ID della VM |
| `VM_NAME` | `povero-senza-biga` | nome/hostname |
| `STORAGE` | `local-lvm` | storage del disco |
| `SNIPPET_STORAGE` | `local` | storage con contenuto "snippets" per cloud-init (viene abilitato se manca) |
| `BRIDGE` | `vmbr0` | bridge di rete |
| `VLAN_TAG` | vuoto | tag VLAN |
| `MEMORY` | `1024` | RAM in MB |
| `CORES` | `1` | core CPU |
| `DISK_SIZE` | `8G` | dimensione disco |
| `IP_CIDR` | `dhcp` | `dhcp` oppure IP statico, es. `192.168.1.50/24` |
| `GATEWAY` | vuoto | obbligatorio con IP statico |
| `DNS` | vuoto | server DNS, es. `1.1.1.1` |
| `VM_USER` | `psb` | utente della VM |
| `SSH_PUBKEY` | vuoto | chiave pubblica SSH da autorizzare (testo) |
| `SSH_KEY_FILE` | vuoto | file di chiavi pubbliche da autorizzare (in più cerca in `/root/.ssh`) |
| `VM_PASSWORD` | vuota | password dell'utente della VM; se vuota e senza chiavi viene generata |
| `APP_PASSWORD` | vuota | password del sito; vuota = sito senza login |
| `HOST_PORT` | `8000` | porta esposta dalla VM |
| `REPO_URL` | questo repository | repository da clonare |
| `BRANCH` | `main` | branch da clonare |
| `START_ON_BOOT` | `1` | avvia la VM con l'host |

Esempio con IP statico:

```bash
VMID=210 IP_CIDR=192.168.1.50/24 GATEWAY=192.168.1.1 DNS=1.1.1.1 \
  bash proxmox-create-vm.sh
```

Dopo l'installazione, nella VM (`ssh psb@<ip>`):

- aggiornare all'ultima versione: `sudo psb-update` (git pull, rebuild, riavvio);
- avanzamento dell'installazione: `sudo tail -f /var/log/cloud-init-output.log`;
- log dell'app: `cd /opt/psb/app && docker compose logs -f`.

La configurazione, password inclusa, è in `/opt/psb/.env` nella VM e nello snippet cloud-init sull'host Proxmox: proteggili di conseguenza.

## Pubblicarlo online gratis

**GitHub Pages non va bene**: serve solo siti statici, mentre qui c'è un backend Python che interroga i voli. Alternative:

- **Render**: web service gratuito costruito dal `Dockerfile`. Si addormenta dopo un periodo di inattività, quindi la prima richiesta è lenta.
- **Fly.io**: deploy dal `Dockerfile` (`fly launch`); il container ascolta sulla porta indicata da `PORT` (default 8000). Verifica i limiti del piano gratuito in vigore.
- **VM di casa esposta con Cloudflare Tunnel o Tailscale Funnel**: gratis e senza aprire porte sul router. È la soluzione più comoda se hai già la VM Proxmox.

In ogni caso imposta `APP_PASSWORD` e una `SECRET_KEY` casuale (per esempio `openssl rand -hex 32`): senza password chiunque può usare le tue query verso Google.

## Struttura del progetto

```
app/
  main.py       API FastAPI e pagine (login, index)
  search.py     ricerca N×M, flessibilità date, cache, combinazioni A/R
  filters.py    filtri su orari, scali, prezzo, durata
  flights.py    interrogazione di Google Flights e parsing dei risultati
  stays.py      link di ricerca per gli alloggi
  auth.py       password condivisa e cookie di sessione
  cache.py      cache con scadenza
  config.py     configurazione da variabili d'ambiente
  data/airports.json   elenco aeroporti
scripts/
  proxmox-create-vm.sh   crea la VM su Proxmox
  build_airports.py      rigenera airports.json
static/         interfaccia web (HTML/CSS/JS)
tests/          test pytest
Dockerfile, docker-compose.yml
```

## API

| Endpoint | Descrizione |
|---|---|
| `GET /api/airports?q=...` | cerca aeroporti per codice IATA, città o nome |
| `POST /api/search` | ricerca voli (andata, ritorno, filtri, combinazioni) |
| `GET /api/stays?city=...&checkin=...&checkout=...` | link agli alloggi (opzionali `guests`, `max_price`, `country`) |
| `GET /healthz` | controllo di stato |

## Test

```bash
pytest
```

## Aggiornare gli aeroporti

```bash
python scripts/build_airports.py
```

Rigenera `app/data/airports.json` dai dati di [OurAirports](https://ourairports.com/data/) (dominio pubblico).

## Licenza

MIT.
