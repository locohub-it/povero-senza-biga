"""Prezzo più basso per ogni giorno (sola andata), per colorare il calendario.

Usa lo stesso servizio di Google Flights che colora il calendario sul loro sito
(tramite la libreria open source `flights`/fli): una sola richiesta copre più
aeroporti di partenza e di arrivo e fino a 61 giorni.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, timedelta

from .cache import TTLCache
from .config import settings

MAX_DAYS = 61
_cache = TTLCache(6 * 60 * 60, max_items=500)  # i prezzi del calendario cambiano lentamente
_lock = threading.Lock()  # il client HTTP di fli è condiviso: una richiesta alla volta


class DatePricesError(Exception):
    pass


def _airports(codes: list[str]):
    from fli.models import Airport

    out = []
    for c in codes:
        a = getattr(Airport, c.upper(), None)
        if a is not None:
            out.append([a, 0])
    return out


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_calendar_response(text: str) -> dict[str, float]:
    """Estrae {data: prezzo} dalla risposta di GetCalendarGraph.

    La risposta è una serie di righe JSON; i prezzi stanno in elementi
    [\"YYYY-MM-DD\", null, [[null, prezzo], token], ...]. Li cerchiamo ovunque,
    così un piccolo cambio di struttura non ci lascia senza prezzi.
    """
    prices: dict[str, float] = {}

    def walk(x):
        if isinstance(x, list):
            if (len(x) >= 3 and isinstance(x[0], str) and _DATE_RE.match(x[0])
                    and isinstance(x[2], list) and x[2] and isinstance(x[2][0], list)
                    and len(x[2][0]) >= 2 and isinstance(x[2][0][1], (int, float))):
                d, p = x[0], x[2][0][1]
                if p > 0 and (d not in prices or p < prices[d]):
                    prices[d] = round(p)
                return
            for y in x:
                walk(y)
        elif isinstance(x, str) and x[:1] == "[" and "-" in x[:400]:
            try:
                walk(json.loads(x))
            except ValueError:
                pass

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        try:
            walk(json.loads(line))
        except ValueError:
            continue
    return prices


def fetch_date_prices(origins: list[str], destinations: list[str], start: str, end: str,
                      adults: int = 1) -> dict[str, float]:
    """{'YYYY-MM-DD': prezzo minimo} per i giorni tra start ed end (inclusi). Bloccante."""
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    today = date.today()
    if d0 < today:
        d0 = today
    if d1 < d0:
        return {}
    if (d1 - d0).days + 1 > MAX_DAYS:
        d1 = d0 + timedelta(days=MAX_DAYS - 1)

    key = (tuple(sorted(origins)), tuple(sorted(destinations)), d0.isoformat(), d1.isoformat(), adults)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    from fli.models import DateSearchFilters, FlightSegment, MaxStops, PassengerInfo, SeatType, TripType
    from fli.search import SearchDates

    from fli.search._urls import with_locale_params

    search = SearchDates()
    url = with_locale_params(search.BASE_URL, settings.currency, settings.language, "IT")

    def one_pair(o: str, d: str) -> dict[str, float]:
        dep, arr = _airports([o]), _airports([d])
        if not dep or not arr:
            return {}
        filters = DateSearchFilters(
            trip_type=TripType.ONE_WAY,
            passenger_info=PassengerInfo(adults=adults),
            flight_segments=[FlightSegment(departure_airport=dep, arrival_airport=arr, travel_date=d0.isoformat())],
            stops=MaxStops.ANY,
            seat_type=SeatType.ECONOMY,
            from_date=d0.isoformat(),
            to_date=d1.isoformat(),
        )
        for attempt in range(2):
            with _lock:
                res = search.client.post(url=url, data=f"f.req={filters.encode()}", impersonate="chrome",
                                         allow_redirects=True)
            if res.status_code != 200:
                raise DatePricesError(f"Google ha risposto {res.status_code}")
            got = parse_calendar_response(res.text)
            if got:
                return got
            time.sleep(1.0)  # a volte la risposta arriva vuota: un secondo tentativo basta
        return {}

    # Google accetta più aeroporti di partenza/arrivo nella stessa richiesta solo a volte:
    # una richiesta per coppia è più lenta ma affidabile. Per ogni giorno si tiene il minimo.
    prices: dict[str, float] = {}
    errors = []
    pairs = [(o, d) for o in origins for d in destinations if o != d]
    for o, d in pairs:
        try:
            got = one_pair(o, d)
        except Exception as exc:  # rete, limiti di Google
            errors.append(f"{o}-{d}: {exc}")
            continue
        for day, p in got.items():
            if d0.isoformat() <= day <= d1.isoformat() and (day not in prices or p < prices[day]):
                prices[day] = p
    if not prices and errors:
        raise DatePricesError("; ".join(errors)[:300])
    if not prices:
        return {}  # niente cache per i risultati vuoti
    _cache.set(key, prices)
    return prices
