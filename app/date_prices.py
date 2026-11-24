"""Prezzo più basso per ogni giorno (sola andata), per colorare il calendario.

Usa lo stesso servizio di Google Flights che colora il calendario sul loro sito
(tramite la libreria open source `flights`/fli): una sola richiesta copre più
aeroporti di partenza e di arrivo e fino a 61 giorni.
"""

from __future__ import annotations

import threading
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

    dep, arr = _airports(origins), _airports(destinations)
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
    try:
        with _lock:
            res = SearchDates().search(filters, currency=settings.currency, language=settings.language, country="IT")
    except Exception as exc:  # rete, formato cambiato, limiti di Google
        raise DatePricesError(f"{exc.__class__.__name__}: {exc}") from exc

    prices: dict[str, float] = {}
    for item in res or []:
        d = item.date[0].date().isoformat()
        if item.price and (d not in prices or item.price < prices[d]):
            prices[d] = round(item.price)
    _cache.set(key, prices)
    return prices
