import asyncio

import app.search as search
from app.flights import FlightSearchError, Itinerary, Segment, describe_unexpected_page
from app.search import SearchRequest, TripLeg, run_search


def _it(o, d, dt):
    return Itinerary(origin=o, destination=d, date=dt, price=30, currency="EUR", airlines=["X"],
                     segments=[Segment(o, "", d, "", dt + "T10:00", dt + "T12:00", 120, "XX1", "X", "")])


def test_retry_then_success():
    search._cache._data.clear()
    calls = []

    def flaky(o, d, dt, adults, hints):
        calls.append(1)
        if len(calls) == 1:
            raise FlightSearchError("risposta di Google inattesa")
        return [_it(o, d, dt)]

    r = asyncio.run(run_search(SearchRequest(legs=[TripLeg(origins=["MAD"], destinations=["BDS"], date="2027-01-14")]), search_fn=flaky))
    assert len(calls) == 2
    assert r["errors"] == [] and len(r["legs"][0]["itineraries"]) == 1


def test_gives_up_after_retries():
    search._cache._data.clear()
    calls = []

    def broken(o, d, dt, adults, hints):
        calls.append(1)
        raise FlightSearchError("bloccato")

    r = asyncio.run(run_search(SearchRequest(legs=[TripLeg(origins=["MAD"], destinations=["BDS"], date="2027-01-14")]), search_fn=broken))
    assert len(calls) == len(search.RETRY_DELAYS) + 1
    assert "tentativi" in r["errors"][0]["error"]


def test_describe_unexpected_page():
    assert "anti-robot" in describe_unexpected_page("https://www.google.com/sorry/index?continue=x", "")
    assert "anti-robot" in describe_unexpected_page("https://www.google.com/travel/flights", "<p>Our systems have detected unusual traffic</p>")
    assert "cookie" in describe_unexpected_page("https://consent.google.com/m?x", "")
    assert "«Errore»" in describe_unexpected_page("https://www.google.com/travel/flights", "<html><title>Errore</title></html>")
