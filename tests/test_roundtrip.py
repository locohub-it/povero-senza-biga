from app.flights import Itinerary, Segment
from app.roundtrip import carrier_codes, roundtrip_links, same_carrier
from app.search import build_combos, price_calendar


def it(o, d, dep, fn, price=20, arr=None, airline="X"):
    arr = arr or dep
    return Itinerary(origin=o, destination=d, date=dep[:10], price=price, currency="EUR", airlines=[airline],
                     segments=[Segment(o, "", d, "", dep, arr, 100, fn, airline, "")])


def test_carrier_codes():
    assert carrier_codes(it("BDS", "MXP", "2026-12-25T08:35", "U22862")) == {"U2"}


def test_same_carrier():
    a = it("BDS", "MXP", "2026-12-25T08:35", "U22862")
    b = it("MXP", "BDS", "2027-01-03T07:00", "U22863")
    c = it("MXP", "BRI", "2027-01-03T08:15", "FR123")
    assert same_carrier(a, b) == {"U2"}
    assert same_carrier(a, c) is None
    # gruppo Ryanair: Malta Air (AL) e Ryanair (FR) si prenotano insieme
    assert same_carrier(it("BRI", "BGY", "2026-12-25T06:00", "FR1"), it("BGY", "BRI", "2027-01-03T06:50", "AL4132"))


def test_roundtrip_links_same_airports_same_airline():
    links = roundtrip_links(it("BRI", "BGY", "2026-12-25T06:00", "FR1"), it("BGY", "BRI", "2027-01-03T06:50", "FR2"), 1)
    labels = [l["label"] for l in links]
    assert labels[0] == "Prenota A/R su Ryanair"
    assert "dateOut=2026-12-25" in links[0]["url"] and "dateIn=2027-01-03" in links[0]["url"]
    assert "originIata=BRI" in links[0]["url"] and "destinationIata=BGY" in links[0]["url"]
    assert links[1]["url"].startswith("https://www.google.com/travel/flights/search?tfs=")


def test_roundtrip_links_different_airports_empty():
    assert roundtrip_links(it("BDS", "MXP", "2026-12-25T08:35", "U21"), it("MXP", "BRI", "2027-01-03T08:15", "U22"), 1) == []


def test_roundtrip_links_mixed_airlines_only_google():
    links = roundtrip_links(it("BDS", "MXP", "2026-12-25T08:35", "U21"), it("MXP", "BDS", "2027-01-03T08:15", "FR2"), 1)
    assert len(links) == 1 and links[0]["label"] == "A/R su Google Flights"


def test_build_combos_adds_links():
    outs = [it("BDS", "MXP", "2026-12-25T08:35", "U21", price=20, arr="2026-12-25T10:20")]
    ins = [it("MXP", "BDS", "2027-01-03T07:00", "U22", price=20)]
    c = build_combos(outs, ins, 3, 10)[0]
    assert c["total"] == 40 and c["same_airline"] and c["roundtrip_links"]


def test_price_calendar():
    items = [
        it("NAP", "BCN", "2026-12-14T09:00", "VY1", price=50),
        it("BRI", "BCN", "2026-12-14T10:00", "FR1", price=30),
        it("NAP", "BCN", "2026-12-15T09:00", "VY2", price=25),
    ]
    cal = price_calendar(items, ["2026-12-13", "2026-12-14", "2026-12-15"])
    assert [d["price"] for d in cal] == [None, 30, 25]
    assert cal[1]["route"] == "BRI-BCN" and cal[1]["count"] == 2
