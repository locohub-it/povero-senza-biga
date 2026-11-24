"""Link di ricerca già filtrati per alloggi economici (ostelli, B&B, stanze private)."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, urlencode

# Booking.com: codici tipo struttura
BOOKING_HOSTEL = 203
BOOKING_BNB = 208
BOOKING_GUEST_HOUSE = 216
BOOKING_HOMESTAY = 222

HOSTELWORLD_CONTINENTS = {
    "EU": "europe", "AS": "asia", "NA": "north-america", "SA": "south-america",
    "AF": "africa", "OC": "oceania",
}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def hostelworld_url(city: str, country: str, continent: str) -> str:
    cont = HOSTELWORLD_CONTINENTS.get(continent.upper())
    if cont and country:
        return f"https://www.hostelworld.com/st/hostels/{cont}/{slugify(country)}/{slugify(city)}/"
    return "https://www.google.com/search?" + urlencode({"q": f"hostelworld ostelli {city}"})


def airbnb_place(city: str, country: str) -> str:
    """Airbnb usa '--' al posto della virgola nel percorso (es. Barcelona--Spain)."""
    parts = [p for p in (city, country) if p]
    return "--".join(quote(p.replace("/", " ")) for p in parts)


def stay_links(city: str, checkin: str, checkout: str, guests: int = 1,
               max_price: int = 40, currency: str = "EUR", country: str = "",
               continent: str = "") -> list[dict]:
    """Restituisce una lista di {provider, label, url, note} per la città data.

    `max_price` è il budget per notte (per l'intera sistemazione).
    """
    place = f"{city}, {country}" if country else city
    links: list[dict] = []

    links.append({
        "provider": "Hostelworld",
        "label": "Ostelli",
        "note": "letti in camerata (inserisci le date sul sito)",
        "url": hostelworld_url(city, country, continent),
    })

    nflt = ";".join([
        f"ht_id={BOOKING_HOSTEL}",
        f"ht_id={BOOKING_BNB}",
        f"ht_id={BOOKING_GUEST_HOUSE}",
        f"ht_id={BOOKING_HOMESTAY}",
        f"price={currency}-min-{max_price}-1",
    ])
    links.append({
        "provider": "Booking.com",
        "label": "Ostelli, B&B, affittacamere",
        "note": f"solo strutture economiche, max {max_price} {currency}/notte, prezzo crescente",
        "url": "https://www.booking.com/searchresults.it.html?" + urlencode({
            "ss": place,
            "checkin": checkin,
            "checkout": checkout,
            "group_adults": guests,
            "no_rooms": 1,
            "group_children": 0,
            "order": "price",
            "nflt": nflt,
            "selected_currency": currency,
        }),
    })

    links.append({
        "provider": "Airbnb",
        "label": "Stanze private",
        "note": f"stanza privata in casa, max {max_price} {currency}/notte",
        "url": f"https://www.airbnb.it/s/{airbnb_place(city, country)}/homes?" + urlencode([
            ("checkin", checkin),
            ("checkout", checkout),
            ("adults", guests),
            ("room_types[]", "Private room"),
            ("price_max", max_price),
            ("price_filter_input_type", 0),
            ("currency", currency),
        ], quote_via=quote),
    })

    links.append({
        "provider": "Google Hotels",
        "label": "Ostelli e B&B su Google",
        "note": "confronto prezzi tra più siti",
        "url": "https://www.google.com/travel/search?" + urlencode({
            "q": f"ostelli e b&b economici {city}",
            "hl": "it",
            "curr": currency,
        }),
    })

    links.append({
        "provider": "Couchsurfing",
        "label": "Divano gratis",
        "note": "ospitalità gratuita da locali (serve profilo)",
        "url": "https://www.couchsurfing.com/places?" + urlencode({"query": city}),
    })

    return links
