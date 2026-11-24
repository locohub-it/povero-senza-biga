"""Prezzi reali di ostelli, B&B e pensioni da Google Hotels.

Non esiste un'API gratuita: leggiamo i dati strutturati della pagina di
Google Hotels (come facciamo con Google Flights). Per ogni struttura:
nome, tipo, valutazione, prezzo per notte e totale del soggiorno.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlencode

from primp import Client

from .cache import TTLCache
from .config import settings
from .flights import CONSENT_COOKIE

log = logging.getLogger("povero.hotels")

GOOGLE_HOTELS_URL = "https://www.google.com/travel/search"
MONTHS_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"]
# "hotel economici" è la formula che Google accetta sempre con le date (include ostelli e B&B);
# "ostelli" aggiunge altre strutture, ma con alcune città italiane non restituisce nulla.
QUERIES = ["hotel economici {city}", "ostelli {city}"]

_cache = TTLCache(6 * 60 * 60, max_items=300)


class HotelSearchError(Exception):
    pass


def _it_date(d: date) -> str:
    return f"{d.day} {MONTHS_IT[d.month - 1]} {d.year}"


def build_query(template: str, city: str, checkin: date, checkout: date, guests: int, country: str = "") -> str:
    # il paese aiuta a non confondere città omonime; per l'Italia non serve
    place = f"{city}, {country}" if country and country.lower() not in ("italy", "italia") else city
    q = template.format(city=place) + f" dal {_it_date(checkin)} al {_it_date(checkout)}"
    if guests > 1:
        q += f" per {guests} adulti"
    return q


def _payload(html: str) -> list:
    m = re.search(r"AF_initDataCallback\(\{key: 'ds:0'.*?data:(.*?), sideChannel", html, re.S)
    if not m:
        raise HotelSearchError("risposta di Google Hotels inattesa")
    return json.loads(m.group(1))


def _is_record(x) -> bool:
    """Una struttura: [_, nome, [[lat, lon], indirizzo, ...], [tipo, stelle], ...]."""
    return (isinstance(x, list) and len(x) > 12 and isinstance(x[1], str) and x[1]
            and isinstance(x[2], list) and x[2] and isinstance(x[2][0], list) and len(x[2][0]) == 2
            and all(isinstance(v, (int, float)) for v in x[2][0]))


def _find_records(x, out: list) -> None:
    if _is_record(x):
        out.append(x)
        return
    if isinstance(x, dict):
        for v in x.values():
            _find_records(v, out)
    elif isinstance(x, list):
        for v in x:
            _find_records(v, out)


def _stay_dates(block) -> tuple[date, date] | None:
    """Date del soggiorno a cui si riferiscono i prezzi: [[a,m,g],[a,m,g],notti,ospiti]."""
    m = re.search(r"\[\[(\d{4}),\s*(\d+),\s*(\d+)\],\s*\[(\d{4}),\s*(\d+),\s*(\d+)\],\s*\d+,\s*\d+\]",
                  json.dumps(block))
    if not m:
        return None
    y1, m1, d1, y2, m2, d2 = map(int, m.groups())
    return date(y1, m1, d1), date(y2, m2, d2)


def _prices(block) -> tuple[float | None, float | None]:
    """(prezzo per notte, totale) cercati nel blocco offerte della struttura."""
    nightly = total = None

    def walk(x):
        nonlocal nightly, total
        if isinstance(x, list):
            # ["52 €", null, 52.11, null, 52]
            if (nightly is None and len(x) >= 5 and isinstance(x[0], str) and "€" in x[0]
                    and isinstance(x[2], (int, float)) and x[2] > 0):
                nightly = float(x[2])
            # [..., [[a,m,g],[a,m,g],notti,ospiti], ["365 €"], ...]: il totale segue le date
            if total is None:
                for a, b in zip(x, x[1:]):
                    if (isinstance(a, list) and len(a) >= 3 and isinstance(a[0], list) and len(a[0]) == 3
                            and isinstance(a[2], int) and isinstance(b, list) and len(b) == 1 and isinstance(b[0], str)):
                        digits = re.sub(r"[^\d]", "", b[0])
                        if digits:
                            total = float(digits)
                            break
            for y in x:
                walk(y)

    walk(block)
    return nightly, total


def _get(lst, *path):
    for i in path:
        try:
            lst = lst[i]
        except (IndexError, TypeError, KeyError):
            return None
    return lst


def parse_hotels(data: list, city: str, checkin: date, checkout: date) -> list[dict]:
    recs: list = []
    _find_records(data, recs)
    out = []
    for r in recs:
        if _stay_dates(_get(r, 6)) != (checkin, checkout):
            continue  # prezzi per altre date (Google a volte ignora quelle richieste)
        nightly, total = _prices(_get(r, 6))
        if nightly is None:
            continue
        rating = _get(r, 7, 0)
        name = r[1]
        out.append({
            "name": name,
            "type": _get(r, 3, 0) or "",
            "price": round(nightly),
            "total": round(total) if total else None,
            "rating": rating[0] if isinstance(rating, list) and rating and isinstance(rating[0], (int, float)) else None,
            "reviews": rating[1] if isinstance(rating, list) and len(rating) > 1 else None,
            "description": _get(r, 11, 0) or "",
            "image": _get(r, 12, 0) or None,
            "lat": _get(r, 2, 0, 0),
            "lon": _get(r, 2, 0, 1),
            "url": GOOGLE_HOTELS_URL + "?" + urlencode({
                "q": f"{name} {city} dal {_it_date(checkin)} al {_it_date(checkout)}",
                "hl": settings.language, "curr": settings.currency,
            }),
        })
    return out


def _fetch(query: str) -> str:
    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, timeout=30)
    res = client.get(GOOGLE_HOTELS_URL, params={"q": query, "hl": settings.language, "gl": "it",
                                                "curr": settings.currency},
                     headers={"Cookie": CONSENT_COOKIE})
    if res.status_code != 200:
        raise HotelSearchError(f"Google Hotels ha risposto {res.status_code}")
    return res.text


def search_stays(city: str, checkin: str, checkout: str, guests: int = 1, country: str = "") -> dict:
    """Strutture economiche con prezzi reali per le date indicate. Bloccante."""
    d_in, d_out = date.fromisoformat(checkin), date.fromisoformat(checkout)
    if d_out <= d_in:
        raise ValueError("il check-out deve essere dopo il check-in")
    key = (city.lower(), country.lower(), checkin, checkout, guests)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    queries = [build_query(t, city, d_in, d_out, guests, country) for t in QUERIES]
    items: dict[str, dict] = {}
    errors = []
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        for q, fut in zip(queries, [pool.submit(_fetch, q) for q in queries]):
            try:
                found = parse_hotels(_payload(fut.result()), city, d_in, d_out)
            except Exception as exc:  # rete, pagina cambiata
                log.warning("alloggi %r: %s", q, exc)
                errors.append(str(exc))
                continue
            for h in found:
                prev = items.get(h["name"])
                if prev is None or h["price"] < prev["price"]:
                    items[h["name"]] = h
    if not items and errors:
        raise HotelSearchError(errors[0])
    result = {
        "items": sorted(items.values(), key=lambda h: h["price"]),
        "nights": (d_out - d_in).days,
        "currency": settings.currency,
        "source_url": GOOGLE_HOTELS_URL + "?" + urlencode({"q": queries[0], "hl": settings.language,
                                                            "curr": settings.currency}),
    }
    if result["items"]:
        _cache.set(key, result)
    return result
