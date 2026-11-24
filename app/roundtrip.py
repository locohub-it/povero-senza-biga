"""Link per prenotare andata e ritorno insieme, quando la combinazione lo permette."""

from __future__ import annotations

from urllib.parse import urlencode

from fast_flights import FlightQuery, Passengers, create_query

from .config import settings
from .flights import Itinerary

# Codici IATA delle compagnie del gruppo Ryanair (Malta Air, Buzz, Lauda vendono come FR)
RYANAIR_CODES = {"FR", "RK", "AL", "RR", "OE"}


def carrier_codes(it: Itinerary) -> set[str]:
    """Codici compagnia di tutti i segmenti (dal numero di volo, es. 'FR4132' -> 'FR')."""
    return {s.flight_number[:2] for s in it.segments if len(s.flight_number) > 2}


def same_carrier(o: Itinerary, i: Itinerary) -> set[str] | None:
    """Se andata e ritorno sono della stessa compagnia restituisce i suoi codici, altrimenti None."""
    co, ci = carrier_codes(o), carrier_codes(i)
    if not co or not ci:
        return None
    if co == ci and len(co) == 1:
        return co
    if co | ci <= RYANAIR_CODES:
        return co | ci
    return None


def google_roundtrip_url(o: Itinerary, i: Itinerary, adults: int, airlines: set[str] | None) -> str:
    """Ricerca Google Flights andata e ritorno con aeroporti, date e (se c'è) compagnia già impostati."""
    out_date, in_date = o.departure[:10], i.departure[:10]
    q = create_query(
        flights=[
            FlightQuery(date=out_date, from_airport=o.origin, to_airport=o.destination,
                        airlines=sorted(airlines) if airlines else None),
            FlightQuery(date=in_date, from_airport=i.origin, to_airport=i.destination,
                        airlines=sorted(airlines) if airlines else None),
        ],
        trip="round-trip",
        passengers=Passengers(adults=adults),
        language=settings.language,
        currency=settings.currency,
    )
    return q.url()


def ryanair_roundtrip_url(o: Itinerary, i: Itinerary, adults: int) -> str:
    return "https://www.ryanair.com/it/it/trip/flights/select?" + urlencode({
        "adults": adults, "teens": 0, "children": 0, "infants": 0,
        "dateOut": o.departure[:10], "dateIn": i.departure[:10],
        "isConnectedFlight": "false", "discount": 0, "isReturn": "true", "promoCode": "",
        "originIata": o.origin, "destinationIata": o.destination,
    })


def roundtrip_links(o: Itinerary, i: Itinerary, adults: int) -> list[dict]:
    """Link A/R per una combinazione. Vuoto se gli aeroporti non sono gli stessi all'andata e al ritorno."""
    if not (o.origin == i.destination and o.destination == i.origin):
        return []
    carrier = same_carrier(o, i)
    links: list[dict] = []
    direct = all(len(x.segments) == 1 for x in (o, i))
    if carrier and carrier <= RYANAIR_CODES and direct:
        links.append({"label": "Prenota A/R su Ryanair", "url": ryanair_roundtrip_url(o, i, adults)})
    links.append({
        "label": "A/R su Google Flights" if not carrier else "A/R stessa compagnia su Google Flights",
        "url": google_roundtrip_url(o, i, adults, carrier),
    })
    return links


def same_carrier_chain(chain: list[Itinerary]) -> set[str] | None:
    """Codici compagnia se tutti i voli della catena sono della stessa compagnia (o gruppo Ryanair)."""
    codes = [carrier_codes(it) for it in chain]
    if not all(codes):
        return None
    union = set().union(*codes)
    if len(union) == 1 or union <= RYANAIR_CODES:
        return union
    return None


def google_multicity_url(chain: list[Itinerary], adults: int, airlines: set[str] | None) -> str:
    q = create_query(
        flights=[
            FlightQuery(date=it.departure[:10], from_airport=it.origin, to_airport=it.destination,
                        airlines=sorted(airlines) if airlines else None)
            for it in chain
        ],
        trip="multi-city",
        passengers=Passengers(adults=adults),
        language=settings.language,
        currency=settings.currency,
    )
    return q.url()


def chain_links(chain: list[Itinerary], adults: int) -> list[dict]:
    """Link per prenotare più tappe insieme.

    - 2 tappe che tornano agli stessi aeroporti: andata e ritorno (anche Ryanair diretto).
    - più tappe con aeroporti che combaciano: multi-città su Google Flights.
    - aeroporti che non combaciano: nessun link (sono biglietti separati).
    """
    if len(chain) == 2:
        links = roundtrip_links(chain[0], chain[1], adults)
        if links:
            return links
    if len(chain) >= 2 and all(a.destination == b.origin for a, b in zip(chain, chain[1:])):
        carrier = same_carrier_chain(chain)
        return [{
            "label": "Multi-città stessa compagnia su Google Flights" if carrier else "Multi-città su Google Flights",
            "url": google_multicity_url(chain, adults, carrier),
        }]
    return []
