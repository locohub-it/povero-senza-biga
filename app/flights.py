"""Interrogazione di Google Flights tramite fast-flights, con un parser proprio.

Il parser della libreria legge solo la lista "altri voli" e ignora quella dei
"migliori voli" (dove spesso compaiono Ryanair & co.), quindi leggiamo noi il
payload JSON della pagina e normalizziamo entrambe le liste.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from fast_flights import FlightQuery, Passengers, create_query
from primp import Client
from selectolax.lexbor import LexborHTMLParser

from .config import settings

GOOGLE_FLIGHTS_URL = "https://www.google.com/travel/flights"
# Cookie di consenso "rifiuta tutto": senza, dall'UE Google risponde con la pagina dei cookie.
CONSENT_COOKIE = "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg"


class FlightSearchError(Exception):
    """Errore nella ricerca di una singola tratta."""


@dataclass
class Segment:
    origin: str
    origin_name: str
    destination: str
    destination_name: str
    departure: str  # ISO locale, es. 2026-12-15T21:10
    arrival: str
    duration: int  # minuti
    flight_number: str
    airline: str
    aircraft: str


@dataclass
class Layover:
    airport: str
    city: str
    minutes: int
    overnight: bool


@dataclass
class Itinerary:
    origin: str
    destination: str
    date: str
    price: int | None
    currency: str
    airlines: list[str]
    segments: list[Segment]
    layovers: list[Layover] = field(default_factory=list)
    duration: int = 0
    booking_url: str = ""

    @property
    def stops(self) -> int:
        return len(self.segments) - 1

    @property
    def departure(self) -> str:
        return self.segments[0].departure

    @property
    def arrival(self) -> str:
        return self.segments[-1].arrival

    @property
    def key(self) -> str:
        return "|".join(f"{s.flight_number}@{s.departure}" for s in self.segments)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(
            stops=self.stops,
            departure=self.departure,
            arrival=self.arrival,
            key=self.key,
            max_layover=max((l.minutes for l in self.layovers), default=0),
        )
        return d


def _time(value) -> tuple[int, int]:
    padded = [*(value or []), None, None]
    return (padded[0] or 0, padded[1] or 0)


def _iso(date_parts, time_parts) -> str:
    y, m, d = date_parts
    hh, mm = _time(time_parts)
    return f"{y:04d}-{m:02d}-{d:02d}T{hh:02d}:{mm:02d}"


def _get(lst, idx, default=None):
    try:
        v = lst[idx]
    except (IndexError, TypeError):
        return default
    return default if v is None else v


def parse_payload(payload: list, *, origin: str, destination: str, date: str,
                  currency: str, booking_url: str) -> list[Itinerary]:
    """Converte il payload JSON di Google Flights in itinerari normalizzati."""
    raw: list = []
    for idx in (2, 3):  # 2 = migliori voli, 3 = altri voli
        block = _get(payload, idx)
        items = _get(block, 0)
        if items:
            raw.extend(items)

    results: dict[str, Itinerary] = {}
    for item in raw:
        flight = _get(item, 0)
        if not flight:
            continue
        price_block = _get(_get(item, 1), 0)
        price = _get(price_block, 1)

        segments: list[Segment] = []
        for s in _get(flight, 2, []):
            fn = _get(s, 22, [])
            segments.append(Segment(
                origin=_get(s, 3, ""),
                origin_name=_get(s, 4, ""),
                destination=_get(s, 6, ""),
                destination_name=_get(s, 5, ""),
                departure=_iso(_get(s, 20, [1970, 1, 1]), _get(s, 8)),
                arrival=_iso(_get(s, 21, [1970, 1, 1]), _get(s, 10)),
                duration=_get(s, 11, 0),
                flight_number=f"{_get(fn, 0, '')}{_get(fn, 1, '')}",
                airline=_get(fn, 3, ""),
                aircraft=_get(s, 17, ""),
            ))
        if not segments:
            continue

        # Città degli scali: Google le fornisce nel campo 13 dell'itinerario.
        cities = {
            _get(l, 1): _get(l, 5, "") for l in (_get(flight, 13, []) or []) if _get(l, 1)
        }
        layovers = []
        for a, b in zip(segments, segments[1:]):
            arr = datetime.fromisoformat(a.arrival)
            dep = datetime.fromisoformat(b.departure)
            layovers.append(Layover(
                airport=a.destination,
                city=cities.get(a.destination, a.destination_name),
                minutes=int((dep - arr).total_seconds() // 60),
                overnight=dep.date() > arr.date(),
            ))

        it = Itinerary(
            origin=origin,
            destination=destination,
            date=date,
            price=price,
            currency=currency,
            airlines=list(_get(flight, 1, [])),
            segments=segments,
            layovers=layovers,
            duration=_get(flight, 9, 0) or sum(s.duration for s in segments) + sum(l.minutes for l in layovers),
            booking_url=booking_url,
        )
        prev = results.get(it.key)
        if prev is None or (it.price is not None and (prev.price is None or it.price < prev.price)):
            results[it.key] = it
    return list(results.values())


def extract_payload(html: str) -> list:
    script = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if script is None:
        raise FlightSearchError("risposta di Google inattesa (pagina di consenso o blocco)")
    js = script.text()
    data = js.split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        return []
    return json.loads(data)


@dataclass(frozen=True)
class GoogleHints:
    """Filtri passati direttamente a Google per avere più risultati pertinenti."""

    max_stops: int | None = None
    earliest_departure_hour: int | None = None
    latest_departure_hour: int | None = None
    earliest_arrival_hour: int | None = None
    latest_arrival_hour: int | None = None
    min_layover_minutes: int | None = None
    max_layover_minutes: int | None = None


def search_one_way(origin: str, destination: str, date: str, adults: int = 1,
                   hints: GoogleHints | None = None) -> list[Itinerary]:
    """Cerca i voli di sola andata origin→destination in una data (bloccante)."""
    hints = hints or GoogleHints()
    q = create_query(
        flights=[FlightQuery(
            date=date,
            from_airport=origin,
            to_airport=destination,
            max_stops=hints.max_stops,
            earliest_departure_hour=hints.earliest_departure_hour,
            latest_departure_hour=hints.latest_departure_hour,
            earliest_arrival_hour=hints.earliest_arrival_hour,
            latest_arrival_hour=hints.latest_arrival_hour,
            min_layover_minutes=hints.min_layover_minutes,
            max_layover_minutes=hints.max_layover_minutes,
        )],
        trip="one-way",
        passengers=Passengers(adults=adults),
        language=settings.language,
        currency=settings.currency,
    )
    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, timeout=30)
    try:
        res = client.get(GOOGLE_FLIGHTS_URL, params=q.params(), headers={"Cookie": CONSENT_COOKIE})
    except Exception as exc:  # errori di rete
        raise FlightSearchError(f"errore di rete: {exc}") from exc
    if res.status_code != 200:
        raise FlightSearchError(f"Google ha risposto {res.status_code}")
    payload = extract_payload(res.text)
    if not payload:
        return []
    return parse_payload(
        payload,
        origin=origin,
        destination=destination,
        date=date,
        currency=settings.currency,
        booking_url=q.url(),
    )


def shift_date(date: str, days: int) -> str:
    return (datetime.fromisoformat(date) + timedelta(days=days)).date().isoformat()
