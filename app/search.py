"""Ricerca multi-aeroporto: N partenze × M arrivi, andata e ritorno indipendenti."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .cache import TTLCache
from .config import settings
from .filters import FlightFilters
from .flights import FlightSearchError, GoogleHints, Itinerary, search_one_way, shift_date
from .roundtrip import roundtrip_links, same_carrier

_cache = TTLCache(settings.cache_ttl_seconds)

SearchFn = Callable[[str, str, str, int, GoogleHints], list[Itinerary]]


class TooManyQueries(ValueError):
    pass


@dataclass
class SearchRequest:
    origins: list[str]
    destinations: list[str]
    depart_date: str
    return_date: str | None = None
    # Aeroporti del ritorno: se vuoti, si usano destinazioni → origini.
    return_origins: list[str] = field(default_factory=list)
    return_destinations: list[str] = field(default_factory=list)
    flex_days: int = 0  # ± giorni su entrambe le date
    adults: int = 1
    outbound_filters: FlightFilters = field(default_factory=FlightFilters)
    inbound_filters: FlightFilters = field(default_factory=FlightFilters)
    min_hours_at_destination: int = 3  # tempo minimo tra arrivo andata e partenza ritorno
    max_results: int = 60
    max_combos: int = 30


@dataclass(frozen=True)
class Leg:
    origin: str
    destination: str
    date: str


def _dates(date: str, flex: int) -> list[str]:
    return [shift_date(date, d) for d in range(-flex, flex + 1)]


def plan_legs(origins: list[str], destinations: list[str], date: str, flex: int) -> list[Leg]:
    return [
        Leg(o, d, day)
        for day in _dates(date, flex)
        for o in origins
        for d in destinations
        if o != d
    ]


def _clean(codes: list[str]) -> list[str]:
    out: list[str] = []
    for c in codes:
        c = c.strip().upper()
        if len(c) == 3 and c.isalpha() and c not in out:
            out.append(c)
    return out


async def _run_legs(legs: list[Leg], adults: int, hints: GoogleHints, search_fn: SearchFn,
                    sem: asyncio.Semaphore) -> tuple[list[Itinerary], list[dict]]:
    async def one(leg: Leg):
        key = (leg, adults, hints)
        cached = _cache.get(key)
        if cached is not None:
            return leg, cached, None
        async with sem:
            await asyncio.sleep(random.uniform(0.1, 0.6))  # non martellare Google
            try:
                res = await asyncio.to_thread(search_fn, leg.origin, leg.destination, leg.date, adults, hints)
            except FlightSearchError as exc:
                return leg, None, str(exc)
            except Exception as exc:  # parsing cambiato, ecc.
                return leg, None, f"errore imprevisto: {exc.__class__.__name__}: {exc}"
        _cache.set(key, res)
        return leg, res, None

    results = await asyncio.gather(*(one(l) for l in legs))
    itineraries: list[Itinerary] = []
    errors: list[dict] = []
    for leg, res, err in results:
        if err:
            errors.append({"origin": leg.origin, "destination": leg.destination, "date": leg.date, "error": err})
        else:
            itineraries.extend(res)
    return itineraries, errors


def _sort_key(it: Itinerary):
    return (it.price if it.price is not None else 10**9, it.duration)


def _dedupe(items: list[Itinerary]) -> list[Itinerary]:
    seen: dict[str, Itinerary] = {}
    for it in items:
        if it.key not in seen or _sort_key(it) < _sort_key(seen[it.key]):
            seen[it.key] = it
    return list(seen.values())


def build_combos(outbound: list[Itinerary], inbound: list[Itinerary], min_gap_hours: int,
                 limit: int, pool: int = 40, adults: int = 1) -> list[dict]:
    """Abbina andate e ritorni compatibili e restituisce le combinazioni più economiche."""
    outs = [o for o in outbound if o.price is not None][:pool]
    ins = [i for i in inbound if i.price is not None][:pool]
    gap = timedelta(hours=min_gap_hours)
    combos = []
    for o in outs:
        arr = datetime.fromisoformat(o.arrival)
        for i in ins:
            if datetime.fromisoformat(i.departure) < arr + gap:
                continue
            nights = (datetime.fromisoformat(i.departure).date() - arr.date()).days
            combos.append({
                "total": o.price + i.price,
                "outbound": o.key,
                "inbound": i.key,
                "nights": nights,
                "same_airports": o.origin == i.destination and o.destination == i.origin,
            })
    combos.sort(key=lambda c: c["total"])
    top = combos[:limit]
    by_out = {o.key: o for o in outs}
    by_in = {i.key: i for i in ins}
    for c in top:
        o, i = by_out[c["outbound"]], by_in[c["inbound"]]
        c["same_airline"] = same_carrier(o, i) is not None
        c["roundtrip_links"] = roundtrip_links(o, i, adults)
    return top


def price_calendar(items: list[Itinerary], dates: list[str]) -> list[dict]:
    """Prezzo minimo per giorno di partenza (tra tutti gli aeroporti), per il grafico delle date."""
    best: dict[str, Itinerary] = {}
    count: dict[str, int] = {}
    for it in items:
        if it.price is None:
            continue
        d = it.departure[:10]
        count[d] = count.get(d, 0) + 1
        if d not in best or it.price < best[d].price:
            best[d] = it
    out = []
    for d in dates:
        b = best.get(d)
        out.append({
            "date": d,
            "price": b.price if b else None,
            "route": f"{b.origin}-{b.destination}" if b else None,
            "airline": ", ".join(b.airlines) if b else None,
            "count": count.get(d, 0),
        })
    return out


async def run_search(req: SearchRequest, search_fn: SearchFn = search_one_way) -> dict:
    origins = _clean(req.origins)
    destinations = _clean(req.destinations)
    if not origins or not destinations:
        raise ValueError("servono almeno un aeroporto di partenza e uno di arrivo")
    flex = max(0, min(req.flex_days, 3))

    out_legs = plan_legs(origins, destinations, req.depart_date, flex)
    in_legs: list[Leg] = []
    if req.return_date:
        r_orig = _clean(req.return_origins) or destinations
        r_dest = _clean(req.return_destinations) or origins
        in_legs = plan_legs(r_orig, r_dest, req.return_date, flex)

    total = len(out_legs) + len(in_legs)
    if total > settings.max_queries:
        raise TooManyQueries(
            f"la ricerca richiede {total} query (massimo {settings.max_queries}): "
            "riduci aeroporti o giorni di flessibilità"
        )

    sem = asyncio.Semaphore(settings.max_concurrency)
    (out_raw, out_err), (in_raw, in_err) = await asyncio.gather(
        _run_legs(out_legs, req.adults, req.outbound_filters.google_hints(), search_fn, sem),
        _run_legs(in_legs, req.adults, req.inbound_filters.google_hints(), search_fn, sem),
    )

    outbound = sorted((i for i in _dedupe(out_raw) if req.outbound_filters.accepts(i)), key=_sort_key)
    inbound = sorted((i for i in _dedupe(in_raw) if req.inbound_filters.accepts(i)), key=_sort_key)

    combos = (build_combos(outbound, inbound, req.min_hours_at_destination, req.max_combos, adults=req.adults)
              if in_legs else [])
    calendar = {
        "outbound": price_calendar(outbound, _dates(req.depart_date, flex)),
        "inbound": price_calendar(inbound, _dates(req.return_date, flex)) if req.return_date else [],
    }

    # Le combinazioni possono riferirsi a voli oltre il limite di visualizzazione: includili.
    out_show = outbound[: req.max_results]
    in_show = inbound[: req.max_results]
    shown_out = {i.key for i in out_show}
    shown_in = {i.key for i in in_show}
    by_key_out = {i.key: i for i in outbound}
    by_key_in = {i.key: i for i in inbound}
    for c in combos:
        if c["outbound"] not in shown_out:
            out_show.append(by_key_out[c["outbound"]]); shown_out.add(c["outbound"])
        if c["inbound"] not in shown_in:
            in_show.append(by_key_in[c["inbound"]]); shown_in.add(c["inbound"])

    return {
        "outbound": [i.to_dict() for i in out_show],
        "inbound": [i.to_dict() for i in in_show],
        "combos": combos,
        "calendar": calendar,
        "errors": out_err + in_err,
        "stats": {
            "queries": total,
            "outbound_found": len(out_raw),
            "outbound_after_filters": len(outbound),
            "inbound_found": len(in_raw),
            "inbound_after_filters": len(inbound),
            "currency": settings.currency,
        },
    }
