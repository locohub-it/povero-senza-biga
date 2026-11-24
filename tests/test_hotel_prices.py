from datetime import date

from fastapi.testclient import TestClient

import app.main as main
from app.hotel_prices import HotelSearchError, build_query, parse_hotels


def record(name, nightly, total, dates=((2026, 12, 3), (2026, 12, 10), 7)):
    (y1, m1, d1), (y2, m2, d2), n = dates
    offers = [None, [[225, 0], None, None, "EUR", [[y1, m1, d1], [y2, m2, d2], n, 1]],
              [None, [f"{nightly} €", None, nightly + 0.3, None, nightly], None, None, ["/travel/clk"], None, None, None,
                     [[y1, m1, d1], [y2, m2, d2], n, 1], [f"{total} €"]]]
    r = [None, name, [[41.38, 2.16], [[["Via X"]]]], ["Hotel a 2 stelle", 2], None, None, offers,
         [[4.4, 688]], None, "0x1", None, ["Ostello con terrazza"], ["https://img/x.jpg", 150, 92], None]
    return r


def test_parse_hotels_reads_prices_and_skips_other_dates():
    data = [[{"1": [record("Pars Hostel", 52, 365)]},
             {"2": [record("Altro", 30, 30, dates=((2026, 11, 24), (2026, 11, 25), 1))]}]]
    out = parse_hotels(data, "Barcelona", date(2026, 12, 3), date(2026, 12, 10))
    assert len(out) == 1
    h = out[0]
    assert (h["name"], h["price"], h["total"], h["rating"], h["reviews"]) == ("Pars Hostel", 52, 365, 4.4, 688)
    assert h["type"] == "Hotel a 2 stelle" and h["image"] == "https://img/x.jpg"
    assert h["url"].startswith("https://www.google.com/travel/search?q=Pars+Hostel+Barcelona")


def test_build_query():
    q = build_query("hotel economici {city}", "Barcelona", date(2026, 12, 3), date(2026, 12, 10), 2, "Spain")
    assert q == "hotel economici Barcelona, Spain dal 3 dicembre 2026 al 10 dicembre 2026 per 2 adulti"
    assert build_query("hotel economici {city}", "Milano", date(2026, 12, 3), date(2026, 12, 10), 1, "Italy").startswith("hotel economici Milano dal")


def test_api_stay_prices(monkeypatch):
    monkeypatch.setattr(main, "search_stays", lambda *a: {"items": [{"name": "X", "price": 30}], "nights": 7})
    c = TestClient(main.app)
    r = c.get("/api/stays/prices", params={"city": "Milano", "checkin": "2026-12-03", "checkout": "2026-12-10"})
    assert r.status_code == 200 and r.json()["items"][0]["price"] == 30
    assert c.get("/api/stays/prices", params={"city": "Milano", "checkin": "x", "checkout": "2026-12-10"}).status_code == 400

    def boom(*a):
        raise HotelSearchError("pagina cambiata")
    monkeypatch.setattr(main, "search_stays", boom)
    assert c.get("/api/stays/prices", params={"city": "Milano", "checkin": "2026-12-03", "checkout": "2026-12-10"}).status_code == 502
