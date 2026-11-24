from fastapi.testclient import TestClient

import app.main as main
from app.date_prices import DatePricesError


def test_date_prices_ok(monkeypatch):
    calls = []

    def fake(o, d, start, end, adults):
        calls.append((o, d, start, end, adults))
        return {"2026-12-10": 15, "2026-12-11": 40}

    monkeypatch.setattr(main, "fetch_date_prices", fake)
    r = TestClient(main.app).get("/api/date-prices", params={
        "origins": "mxp", "destinations": "BRI,BDS,XX1", "start": "2026-12-01", "end": "2027-01-30", "adults": 2})
    assert r.status_code == 200
    assert r.json()["prices"] == {"2026-12-10": 15, "2026-12-11": 40}
    assert calls == [(["MXP"], ["BRI", "BDS"], "2026-12-01", "2027-01-30", 2)]


def test_date_prices_bad_input(monkeypatch):
    monkeypatch.setattr(main, "fetch_date_prices", lambda *a: {})
    c = TestClient(main.app)
    assert c.get("/api/date-prices", params={"origins": "123", "destinations": "BRI", "start": "2026-12-01", "end": "2026-12-30"}).status_code == 400
    assert c.get("/api/date-prices", params={"origins": "MXP", "destinations": "BRI", "start": "domani", "end": "2026-12-30"}).status_code == 400


def test_date_prices_upstream_error(monkeypatch):
    def boom(*a):
        raise DatePricesError("rate limit")

    monkeypatch.setattr(main, "fetch_date_prices", boom)
    r = TestClient(main.app).get("/api/date-prices", params={"origins": "MXP", "destinations": "BRI", "start": "2026-12-01", "end": "2026-12-30"})
    assert r.status_code == 502


def test_parse_calendar_response():
    from app.date_prices import parse_calendar_response
    inner = '[[null,[[1,2,3]],0,"x","y"],[["2026-12-01",null,[[null,25],"tok"],1],["2026-12-02",null,[[null,16],"tok"],1],["2026-12-03",null,[null,"tok"],1]]]'
    import json
    text = ")]}'\n\n" + json.dumps([["wrb.fr", None, inner, None, None, None, "generic"], ["di", 46], ["af.httprm", 46, "x", 1]])
    assert parse_calendar_response(text) == {"2026-12-01": 25, "2026-12-02": 16}
    error = ")]}'\n\n" + json.dumps([["wrb.fr", None, None, None, None, [13, None, []]]])
    assert parse_calendar_response(error) == {}
