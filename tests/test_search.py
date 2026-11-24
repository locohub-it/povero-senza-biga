import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

import app.search
from app.filters import FlightFilters
from app.flights import FlightSearchError, Itinerary, Segment
from app.search import SearchRequest, TooManyQueries, run_search

DEPART = "2026-12-15"
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


def test_round_trip_queries_all_four_outbound_and_four_inbound_pairs():
    calls: list[tuple[str, str, str]] = []
    req = SearchRequest(
        origins=["NAP", "BRI"],
        destinations=["BCN", "GRO"],
        depart_date=DEPART,
        return_date=RETURN,
    )
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


def test_outbound_sorted_by_price():
    calls: list = []
    prices = {("NAP", "BCN"): 80, ("NAP", "GRO"): 30, ("BRI", "BCN"): 55, ("BRI", "GRO"): 10}
    req = SearchRequest(origins=["NAP", "BRI"], destinations=["BCN", "GRO"], depart_date=DEPART)
    result = run(req, make_fake(calls, prices=prices))

    out_prices = [i["price"] for i in result["outbound"]]
    assert out_prices == sorted(out_prices)
    assert out_prices == [10, 30, 55, 80]
    assert result["combos"] == []  # nessun ritorno richiesto


def test_combos_sorted_by_total_and_respect_min_gap():
    calls: list = []
    prices = {("NAP", "BCN"): 40, ("BRI", "BCN"): 60, ("BCN", "NAP"): 25, ("BCN", "BRI"): 15,
              ("GRO", "NAP"): 70, ("GRO", "BRI"): 90}
    req = SearchRequest(
        origins=["NAP", "BRI"],
        destinations=["BCN", "GRO"],
        depart_date=DEPART,
        return_date=RETURN,
        min_hours_at_destination=3,
    )
    result = run(req, make_fake(calls, prices=prices))

    combos = result["combos"]
    assert combos, "attesi abbinamenti"
    totals = [c["total"] for c in combos]
    assert totals == sorted(totals)

    outs = {o["key"]: o for o in result["outbound"]}
    ins = {i["key"]: i for i in result["inbound"]}
    for c in combos:
        o, i = outs[c["outbound"]], ins[c["inbound"]]
        assert c["total"] == o["price"] + i["price"]
        gap_hours = (datetime.fromisoformat(i["departure"]) - datetime.fromisoformat(o["arrival"])).total_seconds() / 3600
        assert gap_hours >= 3


def test_min_hours_at_destination_excludes_tight_connections():
    # Andata e ritorno stesso giorno: ritorno alle 12:00, andata arriva alle 11:00 -> 1h di margine.
    calls: list = []
    fake = make_fake(calls, in_times=("12:00", "14:00"), inbound_from=("BCN",))
    base = dict(origins=["NAP"], destinations=["BCN"], depart_date=DEPART, return_date=DEPART)

    strict = run(SearchRequest(**base, min_hours_at_destination=3), fake)
    assert strict["combos"] == []

    loose = run(SearchRequest(**base, min_hours_at_destination=0), fake)
    assert len(loose["combos"]) == 1


def test_combos_can_mix_airports():
    calls: list = []
    prices = {("NAP", "BCN"): 10, ("BRI", "GRO"): 10, ("BCN", "NAP"): 10, ("GRO", "BRI"): 10}
    req = SearchRequest(
        origins=["NAP", "BRI"],
        destinations=["BCN", "GRO"],
        depart_date=DEPART,
        return_date=RETURN,
    )
    result = run(req, make_fake(calls, prices=prices))

    flags = {c["same_airports"] for c in result["combos"]}
    assert False in flags  # es. andata NAP→BCN, ritorno GRO→BRI
    assert True in flags   # es. andata NAP→BCN, ritorno BCN→NAP


def test_flex_days_triples_the_dates():
    calls: list = []
    req = SearchRequest(origins=["NAP"], destinations=["BCN"], depart_date=DEPART, flex_days=1)
    result = run(req, make_fake(calls))

    assert {c[2] for c in calls} == {"2026-12-14", "2026-12-15", "2026-12-16"}
    assert len(calls) == 3
    assert result["stats"]["queries"] == 3


def test_too_many_queries_raises():
    calls: list = []
    req = SearchRequest(
        origins=["NAP", "BRI", "MXP", "FCO", "VCE", "BLQ"],
        destinations=["BCN", "GRO", "MAD", "LIS", "CDG", "ORY"],
        depart_date=DEPART,
        return_date=RETURN,
    )
    with pytest.raises(TooManyQueries):
        run(req, make_fake(calls))
    assert calls == []  # rifiutata prima di interrogare Google


def test_failed_leg_is_reported_and_others_still_return():
    calls: list = []
    fake = make_fake(calls, fail={("NAP", "BCN")})
    req = SearchRequest(origins=["NAP", "BRI"], destinations=["BCN"], depart_date=DEPART)
    result = run(req, fake)

    assert len(result["errors"]) == 1
    err = result["errors"][0]
    assert (err["origin"], err["destination"], err["date"]) == ("NAP", "BCN", DEPART)
    assert "503" in err["error"]
    assert [(o["origin"], o["destination"]) for o in result["outbound"]] == [("BRI", "BCN")]


def test_unexpected_exception_is_reported_as_error():
    def broken(origin, destination, date, adults, hints):
        raise KeyError("layout")

    req = SearchRequest(origins=["NAP"], destinations=["BCN"], depart_date=DEPART)
    result = run(req, broken)
    assert len(result["errors"]) == 1
    assert "KeyError" in result["errors"][0]["error"]
    assert result["outbound"] == []


def test_invalid_codes_are_cleaned():
    calls: list = []
    req = SearchRequest(
        origins=[" nap ", "XX1", "BRI", "nap"],
        destinations=["bcn"],
        depart_date=DEPART,
    )
    run(req, make_fake(calls))
    assert {c[0] for c in calls} == {"NAP", "BRI"}
    assert {c[1] for c in calls} == {"BCN"}
    assert len(calls) == 2  # "nap" duplicato rimosso


def test_origin_equal_destination_pairs_are_skipped():
    calls: list = []
    req = SearchRequest(origins=["NAP"], destinations=["NAP", "BCN"], depart_date=DEPART)
    run(req, make_fake(calls))
    assert calls == [("NAP", "BCN", DEPART)]


def test_outbound_filters_are_applied_to_results():
    calls: list = []
    req = SearchRequest(
        origins=["NAP"],
        destinations=["BCN"],
        depart_date=DEPART,
        outbound_filters=FlightFilters(max_price=50),
    )
    fake = make_fake(calls, default_price=80)
    result = run(req, fake)
    assert result["outbound"] == []
    assert result["stats"]["outbound_found"] == 1
    assert result["stats"]["outbound_after_filters"] == 0
