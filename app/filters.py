"""Filtri sugli itinerari: fasce orarie, scali, prezzo."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .flights import GoogleHints, Itinerary


def parse_hhmm(value: str | None) -> int | None:
    """'08:30' -> 510 minuti dalla mezzanotte. None/'' -> None."""
    if not value:
        return None
    hh, _, mm = value.partition(":")
    minutes = int(hh) * 60 + int(mm or 0)
    if not 0 <= minutes <= 24 * 60:
        raise ValueError(f"orario non valido: {value}")
    return minutes


def in_window(minute_of_day: int, start: int | None, end: int | None) -> bool:
    """Vero se l'orario cade nella fascia. Supporta fasce a cavallo della mezzanotte (22:00-06:00)."""
    if start is None and end is None:
        return True
    if start is None:
        return minute_of_day <= end
    if end is None:
        return minute_of_day >= start
    if start <= end:
        return start <= minute_of_day <= end
    return minute_of_day >= start or minute_of_day <= end


# Se si indica solo "arrivo entro X", gli arrivi prima di quest'ora (notte fonda) sono esclusi.
EARLIEST_SENSIBLE_ARRIVAL = 5 * 60


def _minute_of_day(iso: str) -> int:
    hh, mm = iso[11:16].split(":")
    return int(hh) * 60 + int(mm)


@dataclass(frozen=True)
class FlightFilters:
    depart_from: int | None = None  # minuti dalla mezzanotte
    depart_to: int | None = None
    arrive_from: int | None = None
    arrive_to: int | None = None
    max_stops: int | None = None
    min_layover: int | None = None  # minuti, per OGNI scalo (coincidenze sicure)
    max_layover: int | None = None  # minuti, per OGNI scalo
    long_layover_only: bool = False  # almeno uno scalo >= long_layover_threshold
    long_layover_threshold: int = 6 * 60
    max_price: int | None = None
    max_duration: int | None = None  # minuti totali

    def accepts(self, it: Itinerary) -> bool:
        if not in_window(_minute_of_day(it.departure), self.depart_from, self.depart_to):
            return False
        arrive_from = self.arrive_from
        if arrive_from is None and self.arrive_to is not None:
            # "Arrivo entro le 20" non deve far passare un arrivo alle 00:25 del giorno dopo.
            arrive_from = EARLIEST_SENSIBLE_ARRIVAL
        if not in_window(_minute_of_day(it.arrival), arrive_from, self.arrive_to):
            return False
        if self.max_stops is not None and it.stops > self.max_stops:
            return False
        if self.max_price is not None and (it.price is None or it.price > self.max_price):
            return False
        if self.max_duration is not None and it.duration > self.max_duration:
            return False
        for lay in it.layovers:
            if self.min_layover is not None and lay.minutes < self.min_layover:
                return False
            if self.max_layover is not None and lay.minutes > self.max_layover:
                return False
        if self.long_layover_only and not any(
            l.minutes >= self.long_layover_threshold for l in it.layovers
        ):
            return False
        return True

    def google_hints(self) -> GoogleHints:
        """Traduce i filtri in parametri per Google (a grana oraria, quindi larghi).

        Il filtro preciso al minuto viene poi applicato da `accepts`.
        Le fasce a cavallo della mezzanotte non vengono passate a Google.
        """

        def bounds(start: int | None, end: int | None) -> tuple[int | None, int | None]:
            if start is not None and end is not None and start > end:
                return None, None
            lo = start // 60 if start is not None else None
            hi = min(23, math.ceil(end / 60)) if end is not None else None
            return lo, hi

        dep_lo, dep_hi = bounds(self.depart_from, self.depart_to)
        arr_lo, arr_hi = bounds(self.arrive_from, self.arrive_to)
        return GoogleHints(
            max_stops=self.max_stops,
            earliest_departure_hour=dep_lo,
            latest_departure_hour=dep_hi,
            earliest_arrival_hour=arr_lo,
            latest_arrival_hour=arr_hi,
            min_layover_minutes=self.long_layover_threshold if self.long_layover_only else self.min_layover,
            max_layover_minutes=self.max_layover,
        )
