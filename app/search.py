"""Ricerca a tappe multi-aeroporto.

Un viaggio è una sequenza di tappe (voli di sola andata). Ogni tappa va da un
insieme di aeroporti a un altro: la prima da «Da» ad «A», le successive dagli
aeroporti della tappa precedente a quelli nuovi. Andata e ritorno classico =
due tappe, con la seconda che torna agli aeroporti di partenza.
Ogni coppia di aeroporti viene cercata come sola andata, poi il sito combina le
tappe nella sequenza compatibile più economica.
"""

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
from .roundtrip import chain_links, same_carrier_chain

_cache = TTLCache(settings.cache_ttl_seconds)

SearchFn = Callable[[str, str, str, int, GoogleHints], list[Itinerary]]

MAX_TRIP_LEGS = 5
RETRY_DELAYS = (2.0, 5.0)  # attese prima dei nuovi tentativi quando Google risponde male


class TooManyQueries(ValueError):
    pass


@dataclass
class TripLeg:
    """Una tappa del viaggio. `origins` vuoto = aeroporti di arrivo della tappa precedente."""

    destinations: list[str]
    date: str
    origins: list[str] = field(default_factory=list)
    filters: FlightFilters = field(default_factory=FlightFilters)


@dataclass
class SearchRequest:
    legs: list[TripLeg]
    flex_days: int = 0  # ± giorni su tutte le date
    adults: int = 1
    min_hours_at_destination: int = 3  # tempo minimo tra l'arrivo di una tappa e la partenza della successiva
    max_results: int = 60
    max_combos: int = 30


@dataclass(frozen=True)
class Query:
    """Una singola ricerca di sola andata su Google Flights."""

    origin: str
    destination: str
    date: str


def _dates(date: str, flex: int) -> list[str]:
    return [shift_date(date, d) for d in range(-flex, flex + 1)]


def plan_queries(origins: list[str], destinations: list[str], date: str, flex: int) -> list[Query]:
    return [
        Query(o, d, day)
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


async def _run_queries(queries: list[Query], adults: int, hints: GoogleHints, search_fn: SearchFn,
                       sem: asyncio.Semaphore) -> tuple[list[Itinerary], list[dict]]:
    async def one(q: Query):
        key = (q, adults, hints)
        cached = _cache.get(key)
        if cached is not None:
            return q, cached, None
        err = None
        for attempt in range(len(RETRY_DELAYS) + 1):
            async with sem:
                await asyncio.sleep(random.uniform(0.1, 0.6))  # non martellare Google
                try:
                    res = await asyncio.to_thread(search_fn, q.origin, q.destination, q.date, adults, hints)
                    err = None
                    break
                except FlightSearchError as exc:
                    err = str(exc)
                    if not getattr(exc, "retryable", True):
                        break
                except Exception as exc:  # parsing cambiato, ecc.
                    err = f"errore imprevisto: {exc.__class__.__name__}: {exc}"
                    break
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(RETRY_DELAYS[attempt])  # fuori dal semaforo: le altre ricerche continuano
        if err:
            return q, None, err + (f" (dopo {len(RETRY_DELAYS) + 1} tentativi)" if len(RETRY_DELAYS) else "")
        _cache.set(key, res)
        return q, res, None

    results = await asyncio.gather(*(one(q) for q in queries))
    itineraries: list[Itinerary] = []
    errors: list[dict] = []
    for q, res, err in results:
        if err:
            errors.append({"origin": q.origin, "destination": q.destination, "date": q.date, "error": err})
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


def build_chains(legs: list[list[Itinerary]], min_gap_hours: int, limit: int, pool: int = 30,
                 beam: int = 400, adults: int = 1) -> list[dict]:
    """Combina un volo per ogni tappa nella sequenza più economica.

    Vincolo: ogni volo parte almeno `min_gap_hours` dopo l'arrivo del precedente.
    Gli aeroporti tra una tappa e l'altra possono essere diversi (es. arrivo a
    Malpensa e ripartenza da Linate): viene segnalato nel risultato.
    """
    if len(legs) < 2 or any(not l for l in legs):
        return []
    gap = timedelta(hours=min_gap_hours)
    pools = [[i for i in leg if i.price is not None][:pool] for leg in legs]
    chains: list[tuple[int, list[Itinerary]]] = [(it.price, [it]) for it in pools[0]]
    for nxt in pools[1:]:
        grown = []
        for total, chain in chains:
            ready = datetime.fromisoformat(chain[-1].arrival) + gap
            for it in nxt:
                if datetime.fromisoformat(it.departure) >= ready:
                    grown.append((total + it.price, chain + [it]))
        grown.sort(key=lambda c: c[0])
        chains = grown[:beam]
        if not chains:
            return []

    out = []
    for total, chain in chains[:limit]:
        nights = [
            (datetime.fromisoformat(b.departure).date() - datetime.fromisoformat(a.arrival).date()).days
            for a, b in zip(chain, chain[1:])
        ]
        connections = [a.destination == b.origin for a, b in zip(chain, chain[1:])]
        out.append({
            "total": total,
            "keys": [it.key for it in chain],
            "nights": nights,
            "same_airport_connections": connections,
            "returns_home": chain[-1].destination == chain[0].origin,
            "same_airline": same_carrier_chain(chain) is not None,
            "links": chain_links(chain, adults),
        })
    return out


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
    if not req.legs:
        raise ValueError("serve almeno una tappa")
    if len(req.legs) > MAX_TRIP_LEGS:
        raise ValueError(f"massimo {MAX_TRIP_LEGS} tappe")
    flex = max(0, min(req.flex_days, 3))

    # Risolvi aeroporti di ogni tappa: la partenza di default è l'arrivo della tappa precedente.
    resolved: list[tuple[list[str], list[str], TripLeg]] = []
    prev_dest: list[str] = []
    for i, leg in enumerate(req.legs):
        origins = _clean(leg.origins) or prev_dest
        dests = _clean(leg.destinations)
        if not origins:
            raise ValueError("servono almeno un aeroporto di partenza e uno di arrivo")
        if not dests:
            raise ValueError(f"la tappa {i + 1} non ha aeroporti di arrivo")
        if i > 0 and leg.date < req.legs[i - 1].date:
            raise ValueError(f"la data della tappa {i + 1} è prima di quella della tappa {i}")
        resolved.append((origins, dests, leg))
        prev_dest = dests

    plans = [plan_queries(o, d, leg.date, flex) for o, d, leg in resolved]
    total = sum(len(p) for p in plans)
    if total > settings.max_queries:
        raise TooManyQueries(
            f"la ricerca richiede {total} query (massimo {settings.max_queries}): "
            "riduci aeroporti, tappe o giorni di flessibilità"
        )

    sem = asyncio.Semaphore(settings.max_concurrency)
    raw = await asyncio.gather(*(
        _run_queries(plan, req.adults, leg.filters.google_hints(), search_fn, sem)
        for plan, (_, _, leg) in zip(plans, resolved)
    ))

    filtered: list[list[Itinerary]] = []
    errors: list[dict] = []
    for (items, errs), (_, _, leg) in zip(raw, resolved):
        filtered.append(sorted((i for i in _dedupe(items) if leg.filters.accepts(i)), key=_sort_key))
        errors.extend(errs)

    combos = build_chains(filtered, req.min_hours_at_destination, req.max_combos, adults=req.adults)

    legs_out = []
    for idx, ((origins, dests, leg), items, (found, _)) in enumerate(zip(resolved, filtered, raw)):
        shown = items[: req.max_results]
        shown_keys = {i.key for i in shown}
        by_key = {i.key: i for i in items}
        # le combinazioni possono usare voli oltre il limite di visualizzazione: includili
        for c in combos:
            k = c["keys"][idx]
            if k not in shown_keys:
                shown.append(by_key[k]); shown_keys.add(k)
        legs_out.append({
            "index": idx,
            "origins": origins,
            "destinations": dests,
            "date": leg.date,
            "itineraries": [i.to_dict() for i in shown],
            "calendar": price_calendar(items, _dates(leg.date, flex)),
            "found": len(found),
            "after_filters": len(items),
        })

    return {
        "legs": legs_out,
        "combos": combos,
        "errors": errors,
        "stats": {"queries": total, "currency": settings.currency},
    }
