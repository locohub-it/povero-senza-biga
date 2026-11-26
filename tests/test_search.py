import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.search
from app.filters import FlightFilters
from app.flights import FlightSearchError, Itinerary, Segment
from app.search import SearchRequest, TooManyQueries, TripLeg, run_search

DEPART = "2026-12-15"
MID = "2026-12-17"
RETURN = "2026-12-20"


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    app.search._cache._data.clear()
    # Niente attese casuali tra le query: i test restano veloci.
    monkeypatch.setattr(app.search, "random", SimpleNamespace(uniform=lambda a, b: 0.0))
    yield
    app.search._cache._data.clear()


def make_itin(origin, destination, date, price, dep_hm="09:00", arr_hm="11:00") -> Itinerary:
    flight_number = f"{origin}{destination}{date}{dep_hm}".replace(":", "")
    seg = Segment(
        origin=origin,
        origin_name=origin,
        destination=destination,
        destination_name=destination,
        departure=f"{date}T{dep_hm}",
        arrival=f"{date}T{arr_hm}",
        duration=120,
        flight_number=flight_number,
        airline="Vueling",
        aircraft="",
    )
    return Itinerary(
        origin=origin,
        destination=destination,
        date=date,
        price=price,
        currency="EUR",
        airlines=["Vueling"],
        segments=[seg],
        layovers=[],
        duration=120,
        booking_url="",
    )


def make_fake(calls, *, prices=None, fail=(), default_price=100,
              out_times=("09:00", "11:00"), in_times=("18:00", "20:00"),
              inbound_from=("BCN", "GRO")):
    """search_fn finto: registra le chiamate e restituisce un volo per tratta.

    Il prezzo dipende dalla tratta (origin, destination); le tratte in `fail` sollevano errore.
    Gli orari dipendono dal verso: le tratte che partono da `inbound_from` sono ritorni.
    """
    prices = prices or {}

    def fake(origin, destination, date, adults, hints):
        calls.append((origin, destination, date))
        if (origin, destination) in fail:
            raise FlightSearchError(f"Google ha risposto 503 per {origin}-{destination}")
        price = prices.get((origin, destination), default_price)
        # Il verso si riconosce dall'aeroporto di partenza: il ritorno parte da BCN/GRO.
        dep, arr = in_times if origin in inbound_from else out_times
        return [make_itin(origin, destination, date, price, dep, arr)]

    return fake


def run(req: SearchRequest, fake):
    return asyncio.run(run_search(req, search_fn=fake))


def round_trip(outbound_origins, outbound_dests, back_dests, depart=DEPART, back=RETURN):
    return SearchRequest(legs=[
        TripLeg(origins=outbound_origins, destinations=outbound_dests, date=depart),
        TripLeg(destinations=back_dests, date=back),
    ])


def test_round_trip_queries_all_four_outbound_and_four_inbound_pairs():
    calls: list[tuple[str, str, str]] = []
    req = round_trip(["NAP", "BRI"], ["BCN", "GRO"], ["NAP", "BRI"])
    result = run(req, make_fake(calls))

    out_calls = {c for c in calls if c[2] == DEPART}
    in_calls = {c for c in calls if c[2] == RETURN}
    assert out_calls == {("NAP", "BCN", DEPART), ("NAP", "GRO", DEPART),
                         ("BRI", "BCN", DEPART), ("BRI", "GRO", DEPART)}
    assert in_calls == {("BCN", "NAP", RETURN), ("BCN", "BRI", RETURN),
                        ("GRO", "NAP", RETURN), ("GRO", "BRI", RETURN)}
    assert len(calls) == 8
    assert result["stats"]["queries"] == 8
    assert result["errors"] == []
    assert [leg["index"] for leg in result["legs"]] == [0, 1]


def test_leg_without_origins_starts_from_previous_destinations():
    calls: list = []
    req = round_trip(["NAP"], ["BCN", "GRO"], ["NAP"])
    result = run(req, make_fake(calls))

    assert result["legs"][1]["origins"] == ["BCN", "GRO"]
    assert result["legs"][1]["destinations"] == ["NAP"]
    assert {c[:2] for c in calls if c[2] == RETURN} == {("BCN", "NAP"), ("GRO", "NAP")}


def test_itineraries_sorted_by_price_within_leg():
    calls: list = []
    prices = {("NAP", "BCN"): 80, ("NAP", "GRO"): 30, ("BRI", "BCN"): 55, ("BRI", "GRO"): 10}
    req = SearchRequest(legs=[TripLeg(origins=["NAP", "BRI"], destinations=["BCN", "GRO"], date=DEPART)])
    result = run(req, make_fake(calls, prices=prices))

    out_prices = [i["price"] for i in result["legs"][0]["itineraries"]]
    assert out_prices == sorted(out_prices)
    assert out_prices == [10, 30, 55, 80]
    assert result["combos"] == []  # una sola tappa: nessun abbinamento


def test_combos_sorted_by_total_and_respect_min_gap():
    calls: list = []
    prices = {("NAP", "BCN"): 40, ("BRI", "BCN"): 60, ("BCN", "NAP"): 25, ("BCN", "BRI"): 15,
              ("GRO", "NAP"): 70, ("GRO", "BRI"): 90}
    req = round_trip(["NAP", "BRI"], ["BCN", "GRO"], ["NAP", "BRI"])
    req.min_hours_at_destination = 3
    result = run(req, make_fake(calls, prices=prices))

    combos = result["combos"]
    assert combos, "attesi abbinamenti"
    totals = [c["total"] for c in combos]
    assert totals == sorted(totals)

    out_items = {i["key"]: i for i in result["legs"][0]["itineraries"]}
    in_items = {i["key"]: i for i in result["legs"][1]["itineraries"]}
    for c in combos:
        o, i = out_items[c["keys"][0]], in_items[c["keys"][1]]
        assert c["total"] == o["price"] + i["price"]
        gap_hours = (datetime.fromisoformat(i["departure"]) - datetime.fromisoformat(o["arrival"])).total_seconds() / 3600
        assert gap_hours >= 3


def test_min_hours_at_destination_excludes_tight_connections():
    # Andata e ritorno stesso giorno: ritorno alle 12:00, andata arriva alle 11:00 -> 1h di margine.
    calls: list = []
    fake = make_fake(calls, in_times=("12:00", "14:00"), inbound_from=("BCN",))

    def same_day(min_hours):
        return SearchRequest(
            legs=[TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART),
                  TripLeg(destinations=["NAP"], date=DEPART)],
            min_hours_at_destination=min_hours,
        )

    strict = run(same_day(3), fake)
    assert strict["combos"] == []

    loose = run(same_day(0), fake)
    assert len(loose["combos"]) == 1


def test_combos_can_mix_airports_and_flag_it():
    calls: list = []
    prices = {("NAP", "BCN"): 10, ("BRI", "GRO"): 10, ("BCN", "NAP"): 10, ("GRO", "BRI"): 10}
    req = round_trip(["NAP", "BRI"], ["BCN", "GRO"], ["NAP", "BRI"])
    result = run(req, make_fake(calls, prices=prices))

    flags = {tuple(c["same_airport_connections"]) for c in result["combos"]}
    assert (False,) in flags  # es. andata NAP→BCN, ritorno GRO→BRI
    assert (True,) in flags   # es. andata NAP→BCN, ritorno BCN→NAP


def test_three_leg_trip_returns_home_with_multicity_link():
    # A->B->C->A: NAP→BCN, BCN→GRO, GRO→NAP. Il fake trova voli per ogni coppia.
    calls: list = []
    req = SearchRequest(legs=[
        TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART),
        TripLeg(destinations=["GRO"], date=MID),
        TripLeg(destinations=["NAP"], date=RETURN),
    ])
    result = run(req, make_fake(calls))

    assert len(calls) == 3
    assert result["stats"]["queries"] == 3
    assert result["errors"] == []
    assert result["combos"], "attesa almeno una combinazione"
    for c in result["combos"]:
        assert len(c["keys"]) == 3
        assert c["returns_home"] is True
        assert c["nights"] == [2, 3]
        assert c["same_airport_connections"] == [True, True]
        assert c["links"][0]["label"].startswith("Multi-città")


def test_leg_without_flights_means_no_combos():
    calls: list = []
    base = make_fake(calls)

    def no_flights_from_bcn(origin, destination, date, adults, hints):
        if origin == "BCN":
            calls.append((origin, destination, date))
            return []
        return base(origin, destination, date, adults, hints)

    result = run(round_trip(["NAP"], ["BCN"], ["NAP"]), no_flights_from_bcn)

    assert result["legs"][0]["found"] == 1
    assert result["legs"][1]["found"] == 0
    assert result["combos"] == []


def test_leg_dates_out_of_order_raise_value_error():
    calls: list = []
    req = SearchRequest(legs=[
        TripLeg(origins=["NAP"], destinations=["BCN"], date=RETURN),
        TripLeg(destinations=["NAP"], date=DEPART),
    ])
    with pytest.raises(ValueError):
        run(req, make_fake(calls))
    assert calls == []


def test_more_than_five_legs_raises_value_error():
    calls: list = []
    req = SearchRequest(legs=[TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART) for _ in range(6)])
    with pytest.raises(ValueError):
        run(req, make_fake(calls))
    assert calls == []


def test_empty_legs_raise_value_error():
    with pytest.raises(ValueError):
        run(SearchRequest(legs=[]), make_fake([]))


def test_flex_days_triples_the_dates():
    calls: list = []
    req = SearchRequest(legs=[TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART)], flex_days=1)
    result = run(req, make_fake(calls))

    assert {c[2] for c in calls} == {"2026-12-14", "2026-12-15", "2026-12-16"}
    assert len(calls) == 3
    assert result["stats"]["queries"] == 3


def test_too_many_queries_raises():
    calls: list = []
    req = round_trip(
        ["NAP", "BRI", "MXP", "FCO", "VCE", "BLQ"],
        ["BCN", "GRO", "MAD", "LIS", "CDG", "ORY"],
        ["NAP", "BRI", "MXP", "FCO", "VCE", "BLQ"],
    )
    with pytest.raises(TooManyQueries):
        run(req, make_fake(calls))
    assert calls == []  # rifiutata prima di interrogare Google


def test_failed_query_is_reported_and_others_still_return():
    calls: list = []
    fake = make_fake(calls, fail={("NAP", "BCN")})
    req = SearchRequest(legs=[TripLeg(origins=["NAP", "BRI"], destinations=["BCN"], date=DEPART)])
    result = run(req, fake)

    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert (err["origin"], err["destination"], err["date"]) == ("NAP", "BCN", DEPART)
    assert "503" in err["error"]
    assert [(i["origin"], i["destination"]) for i in result["legs"][0]["itineraries"]] == [("BRI", "BCN")]


def test_unexpected_exception_is_reported_as_error():
    def broken(origin, destination, date, adults, hints):
        raise KeyError("layout")

    req = SearchRequest(legs=[TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART)])
    result = run(req, broken)
    assert len(result["errors"]) == 1
    assert "KeyError" in result["errors"][0]["error"]
    assert result["legs"][0]["itineraries"] == []


def test_invalid_codes_are_cleaned():
    calls: list = []
    req = SearchRequest(legs=[TripLeg(origins=[" nap ", "XX1", "BRI", "nap"], destinations=["bcn"], date=DEPART)])
    run(req, make_fake(calls))
    assert {c[0] for c in calls} == {"NAP", "BRI"}
    assert {c[1] for c in calls} == {"BCN"}
    assert len(calls) == 2  # "nap" duplicato rimosso


def test_origin_equal_destination_pairs_are_skipped():
    calls: list = []
    req = SearchRequest(legs=[TripLeg(origins=["NAP"], destinations=["NAP", "BCN"], date=DEPART)])
    run(req, make_fake(calls))
    assert calls == [("NAP", "BCN", DEPART)]


def test_leg_filters_are_applied_to_results():
    calls: list = []
    req = SearchRequest(legs=[
        TripLeg(origins=["NAP"], destinations=["BCN"], date=DEPART, filters=FlightFilters(max_price=50)),
    ])
    fake = make_fake(calls, default_price=80)
    result = run(req, fake)
    leg = result["legs"][0]
    assert leg["itineraries"] == []
    assert leg["found"] == 1
    assert leg["after_filters"] == 0


def test_failed_leg_does_not_block_other_legs_in_combos():
    calls: list = []
    fake = make_fake(calls, fail={("BCN", "NAP")})
    result = run(round_trip(["NAP"], ["BCN"], ["NAP"]), fake)

    assert len(result["errors"]) == 1
    assert len(result["legs"][0]["itineraries"]) == 1
    assert result["legs"][1]["itineraries"] == []
    assert result["combos"] == []


def test_max_total_price_limits_whole_trip():
    # andata 30 o 60, ritorno 25: budget 60 → solo NAP-BCN (30) + BCN-NAP (25)
    calls: list = []
    prices = {("NAP", "BCN"): 30, ("BRI", "BCN"): 60, ("BCN", "NAP"): 25, ("BCN", "BRI"): 25}
    req = round_trip(["NAP", "BRI"], ["BCN"], ["NAP", "BRI"])
    req.max_total_price = 60
    result = run(req, make_fake(calls, prices=prices))
    assert result["combos"] and all(c["total"] <= 60 for c in result["combos"])
    assert {c["total"] for c in result["combos"]} == {55}
    assert result["stats"]["cheapest_over_budget"] is None


def test_max_total_price_reports_cheapest_when_nothing_fits():
    calls: list = []
    req = round_trip(["NAP"], ["BCN"], ["NAP"])
    req.max_total_price = 40
    result = run(req, make_fake(calls, prices={("NAP", "BCN"): 30, ("BCN", "NAP"): 25}))
    assert result["combos"] == []
    assert result["stats"]["cheapest_over_budget"] == 55
    # i singoli voli sotto il budget restano visibili
    assert len(result["legs"][0]["itineraries"]) == 1


def test_max_total_price_hides_flights_above_budget():
    calls: list = []
    req = round_trip(["NAP"], ["BCN"], ["NAP"])
    req.max_total_price = 50
    result = run(req, make_fake(calls, prices={("NAP", "BCN"): 70, ("BCN", "NAP"): 20}))
    assert result["legs"][0]["itineraries"] == []
    assert result["legs"][0]["found"] == 1
