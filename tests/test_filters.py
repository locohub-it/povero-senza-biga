import pytest

from app.filters import FlightFilters, in_window, parse_hhmm
from app.flights import Itinerary, Layover, Segment


def seg(dep: str, arr: str, *, origin="NAP", destination="BCN", n=1) -> Segment:
    return Segment(
        origin=origin,
        origin_name=f"{origin} airport",
        destination=destination,
        destination_name=f"{destination} airport",
        departure=dep,
        arrival=arr,
        duration=60,
        flight_number=f"FR{n}",
        airline="Ryanair",
        aircraft="",
    )


def layover(minutes: int, airport: str = "MXP") -> Layover:
    return Layover(airport=airport, city=airport, minutes=minutes, overnight=False)


def make_it(segments: list[Segment], *, price=100, duration=0, layovers=None) -> Itinerary:
    """Costruisce un itinerario a mano. Gli scali, se non passati, sono vuoti (nonstop) o neutri."""
    if layovers is None:
        layovers = [layover(120, segments[i].destination) for i in range(len(segments) - 1)]
    return Itinerary(
        origin=segments[0].origin,
        destination=segments[-1].destination,
        date=segments[0].departure[:10],
        price=price,
        currency="EUR",
        airlines=["Ryanair"],
        segments=segments,
        layovers=layovers,
        duration=duration or 120,
        booking_url="",
    )


def nonstop(dep: str = "2026-12-15T09:00", arr: str = "2026-12-15T11:00", price=100) -> Itinerary:
    return make_it([seg(dep, arr)], price=price, layovers=[])


# ---------- helpers ----------

def test_parse_hhmm():
    assert parse_hhmm("08:30") == 510
    assert parse_hhmm("00:00") == 0
    assert parse_hhmm("24:00") == 1440
    assert parse_hhmm("") is None
    assert parse_hhmm(None) is None


@pytest.mark.parametrize("bad", ["25:00", "12:99x", "24:01"])
def test_parse_hhmm_rejects_invalid(bad):
    with pytest.raises(ValueError):
        parse_hhmm(bad)


def test_in_window_normal_range():
    assert in_window(9 * 60, 8 * 60, 10 * 60)
    assert not in_window(11 * 60, 8 * 60, 10 * 60)
    assert not in_window(7 * 60, 8 * 60, 10 * 60)


def test_in_window_wrapping_range():
    start, end = parse_hhmm("22:00"), parse_hhmm("06:00")
    assert in_window(parse_hhmm("23:00"), start, end)
    assert in_window(parse_hhmm("02:00"), start, end)
    assert not in_window(parse_hhmm("12:00"), start, end)


def test_in_window_open_ends():
    assert in_window(5, None, None)
    assert in_window(100, 90, None)
    assert not in_window(80, 90, None)
    assert in_window(100, None, 120)
    assert not in_window(130, None, 120)


# ---------- FlightFilters.accepts ----------

def test_arrive_to_rejects_just_after_midnight_next_day():
    f = FlightFilters(arrive_to=parse_hhmm("20:00"))
    assert not f.accepts(nonstop(arr="2026-12-16T00:25"))


def test_arrive_to_rejects_arrival_after_limit():
    f = FlightFilters(arrive_to=parse_hhmm("20:00"))
    assert not f.accepts(nonstop(arr="2026-12-15T21:00"))


def test_arrive_to_accepts_arrival_before_limit():
    f = FlightFilters(arrive_to=parse_hhmm("20:00"))
    assert f.accepts(nonstop(arr="2026-12-15T19:30"))


def test_depart_window():
    f = FlightFilters(depart_from=parse_hhmm("08:00"), depart_to=parse_hhmm("10:00"))
    assert f.accepts(nonstop(dep="2026-12-15T09:00", arr="2026-12-15T11:00"))
    assert not f.accepts(nonstop(dep="2026-12-15T11:00", arr="2026-12-15T13:00"))


def test_max_stops():
    two_stops = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=1),
        seg("2026-12-15T08:00", "2026-12-15T09:00", origin="MXP", destination="FCO", n=2),
        seg("2026-12-15T10:00", "2026-12-15T11:00", origin="FCO", destination="BCN", n=3),
    ])
    one_stop = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=4),
        seg("2026-12-15T08:00", "2026-12-15T09:00", origin="MXP", destination="BCN", n=5),
    ])
    f = FlightFilters(max_stops=1)
    assert f.accepts(one_stop)
    assert f.accepts(nonstop())
    assert not f.accepts(two_stops)


def test_max_price_accepts_at_limit_and_rejects_above():
    f = FlightFilters(max_price=100)
    assert f.accepts(nonstop(price=100))
    assert not f.accepts(nonstop(price=101))


def test_max_price_rejects_unknown_price():
    f = FlightFilters(max_price=100)
    assert not f.accepts(nonstop(price=None))


def test_no_max_price_accepts_unknown_price():
    assert FlightFilters().accepts(nonstop(price=None))


def test_min_layover_applies_to_every_layover():
    it = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=1),
        seg("2026-12-15T08:00", "2026-12-15T09:00", origin="MXP", destination="BCN", n=2),
    ], layovers=[layover(45)])
    assert not FlightFilters(min_layover=60).accepts(it)
    assert FlightFilters(min_layover=45).accepts(it)


def test_max_layover_applies_to_every_layover():
    it = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=1),
        seg("2026-12-15T12:00", "2026-12-15T13:00", origin="MXP", destination="BCN", n=2),
    ], layovers=[layover(300)])
    assert not FlightFilters(max_layover=240).accepts(it)
    assert FlightFilters(max_layover=300).accepts(it)


def test_long_layover_only_threshold_360():
    f = FlightFilters(long_layover_only=True, long_layover_threshold=360)
    long_it = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=1),
        seg("2026-12-15T20:00", "2026-12-15T21:00", origin="MXP", destination="BCN", n=2),
    ], layovers=[layover(13 * 60)])
    short_it = make_it([
        seg("2026-12-15T06:00", "2026-12-15T07:00", origin="NAP", destination="MXP", n=3),
        seg("2026-12-15T09:00", "2026-12-15T10:00", origin="MXP", destination="BCN", n=4),
    ], layovers=[layover(2 * 60)])
    assert f.accepts(long_it)
    assert not f.accepts(short_it)
    assert not f.accepts(nonstop())


def test_max_duration():
    f = FlightFilters(max_duration=180)
    assert f.accepts(make_it([seg("2026-12-15T09:00", "2026-12-15T11:00")], duration=120, layovers=[]))
    assert not f.accepts(make_it([seg("2026-12-15T09:00", "2026-12-15T13:00")], duration=240, layovers=[]))


# ---------- google_hints ----------

def test_google_hints_depart_window_rounds_to_hours():
    f = FlightFilters(depart_from=parse_hhmm("06:30"), depart_to=parse_hhmm("20:15"))
    h = f.google_hints()
    assert h.earliest_departure_hour == 6
    assert h.latest_departure_hour == 21  # ceil(20.25) = 21, cap 23


def test_google_hints_latest_hour_capped_at_23():
    f = FlightFilters(depart_to=parse_hhmm("23:30"))
    assert f.google_hints().latest_departure_hour == 23


def test_google_hints_wrapping_window_is_not_passed():
    f = FlightFilters(depart_from=parse_hhmm("22:00"), depart_to=parse_hhmm("06:00"))
    h = f.google_hints()
    assert h.earliest_departure_hour is None
    assert h.latest_departure_hour is None


def test_google_hints_wrapping_arrival_window_is_not_passed():
    f = FlightFilters(arrive_from=parse_hhmm("22:00"), arrive_to=parse_hhmm("06:00"))
    h = f.google_hints()
    assert h.earliest_arrival_hour is None
    assert h.latest_arrival_hour is None


def test_google_hints_long_layover_sets_min_layover_to_threshold():
    f = FlightFilters(long_layover_only=True, long_layover_threshold=360)
    assert f.google_hints().min_layover_minutes == 360


def test_google_hints_passes_stops_and_plain_min_layover():
    f = FlightFilters(max_stops=1, min_layover=60, max_layover=240)
    h = f.google_hints()
    assert h.max_stops == 1
    assert h.min_layover_minutes == 60
    assert h.max_layover_minutes == 240
