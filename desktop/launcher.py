"""Povero e senza biga come applicazione desktop (Windows).

Avvia il sito su una porta libera di 127.0.0.1 (visibile solo da questo computer)
e lo apre in una finestra propria con pywebview (WebView2 su Windows), che segue
il tema chiaro/scuro del sistema. Chiudendo la finestra si ferma anche il server.

`--selftest`: avvia il server senza finestra, controlla che risponda e termina
(codice 0 = tutto ok). Lo usa la build automatica su GitHub.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "Povero e senza biga"

# Versione desktop: niente password, ognuno usa la propria copia.
os.environ["APP_PASSWORD"] = ""

# Senza console (exe "finestra") stdout/stderr sono None: uvicorn e logging si romperebbero.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

if not getattr(sys, "frozen", False):
    # esecuzione da sorgenti: python desktop/launcher.py
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    d = Path(base) / "PoveroSenzaBiga"
    d.mkdir(parents=True, exist_ok=True)
    return d


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def start_server():
    import uvicorn

    from app.main import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_config=None, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(200):  # fino a 20 secondi
        try:
            if get(base + "/healthz", 1)[0] == 200:
                return server, thread, base
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("il server interno non è partito")


def selftest(base: str) -> int:
    log = logging.getLogger("selftest")
    status, body = get(base + "/")
    assert status == 200 and b"Povero" in body, "pagina principale"
    assert get(base + "/static/app.js")[0] == 200, "file statici"
    codes = [a["iata"] for a in json.loads(get(base + "/api/airports?q=bari")[1])]
    assert "BRI" in codes, f"aeroporti: {codes}"
    # le librerie native per parlare con Google devono essere state impacchettate
    import primp  # noqa: F401
    from curl_cffi import requests as _cc  # noqa: F401
    from fli.search import SearchDates  # noqa: F401
    SearchDates()
    log.info("selftest ok")
    return 0


def main() -> int:
    logging.basicConfig(filename=data_dir() / "povero.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().addHandler(logging.StreamHandler(sys.stderr))
    try:
        server, thread, base = start_server()
    except Exception:
        logging.exception("avvio fallito")
        return 1

    if "--selftest" in sys.argv:
        try:
            return selftest(base)
        except Exception:
            logging.exception("selftest fallito")
            return 1
        finally:
            server.should_exit = True
            thread.join(5)

    logging.info("sito interno su %s", base)
    import webview

    webview.create_window(APP_NAME, base + "/", width=1280, height=880, min_size=(380, 560))
    # private_mode=False: ricorda tema e ultima ricerca tra un avvio e l'altro
    webview.start(private_mode=False, storage_path=str(data_dir() / "webview"))
    server.should_exit = True
    thread.join(5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
