import dataclasses

import pytest
from fastapi.testclient import TestClient

import app.auth
import app.main
from app.main import app as fastapi_app

VALID_SEARCH = {
    "legs": [{"origins": ["NAP"], "destinations": ["BCN"], "date": "2026-12-15"}],
}

ROUND_TRIP = {
    "legs": [
        {"origins": ["NAP", "BRI"], "destinations": ["BCN", "GRO"], "date": "2026-12-15"},
        {"destinations": ["NAP", "BRI"], "date": "2026-12-20"},
    ],
}


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture
def locked(monkeypatch):
    """Attiva la password per i test di autenticazione (il default dei test è sito aperto)."""
    monkeypatch.setattr(app.auth, "settings", dataclasses.replace(app.auth.settings, app_password="pw"))
    monkeypatch.setattr(app.main, "settings", dataclasses.replace(app.main.settings, app_password="pw"))


# ---------- health e aeroporti ----------

def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_airports_search_by_iata_ranks_exact_first(client):
    r = client.get("/api/airports", params={"q": "NAP"})
    assert r.status_code == 200
    assert r.json()[0]["iata"] == "NAP"


def test_airports_search_by_city_name(client):
    r = client.get("/api/airports", params={"q": "napoli"})
    assert r.status_code == 200
    assert "NAP" in [a["iata"] for a in r.json()]


def test_airports_search_empty_query_returns_empty_list(client):
    r = client.get("/api/airports", params={"q": "   "})
    assert r.status_code == 200
    assert r.json() == []


def test_airport_by_code(client):
    r = client.get("/api/airports/BCN")
    assert r.status_code == 200
    assert r.json()["iata"] == "BCN"
    assert not any(k.startswith("_") for k in r.json())


def test_airport_by_code_is_case_insensitive(client):
    assert client.get("/api/airports/bcn").status_code == 200


def test_unknown_airport_is_404(client):
    assert client.get("/api/airports/ZZZ").status_code == 404


# ---------- alloggi ----------

def test_stays_returns_five_providers(client):
    r = client.get("/api/stays", params={
        "city": "Barcellona", "checkin": "2026-12-15", "checkout": "2026-12-18",
    })
    assert r.status_code == 200
    links = r.json()
    assert len(links) == 5
    providers = {link["provider"] for link in links}
    assert {"Hostelworld", "Booking.com", "Airbnb"} <= providers


def test_stays_booking_url_sorted_by_price(client):
    links = client.get("/api/stays", params={
        "city": "Barcellona", "checkin": "2026-12-15", "checkout": "2026-12-18",
    }).json()
    booking = next(l for l in links if l["provider"] == "Booking.com")
    assert "order=price" in booking["url"]


def test_stays_airbnb_url_filters_private_room(client):
    links = client.get("/api/stays", params={
        "city": "Barcellona", "checkin": "2026-12-15", "checkout": "2026-12-18",
    }).json()
    airbnb = next(l for l in links if l["provider"] == "Airbnb")
    assert "Private+room" in airbnb["url"] or "Private%20room" in airbnb["url"]


def test_stays_requires_city(client):
    r = client.get("/api/stays", params={"city": "", "checkin": "2026-12-15", "checkout": "2026-12-18"})
    assert r.status_code == 422


# ---------- ricerca voli ----------

def test_search_returns_result_from_run_search(client, monkeypatch):
    seen = {}

    async def fake_run_search(req):
        seen["req"] = req
        return {
            "legs": [], "combos": [], "errors": [],
            "stats": {"queries": 1},
        }

    monkeypatch.setattr(app.main, "run_search", fake_run_search)
    r = client.post("/api/search", json=VALID_SEARCH)
    assert r.status_code == 200
    body = r.json()
    assert body["legs"] == [] and body["combos"] == []
    assert body["stats"] == {"queries": 1}
    assert body["airports"] == {}
    leg = seen["req"].legs[0]
    assert leg.origins == ["NAP"]
    assert leg.destinations == ["BCN"]
    assert leg.date == "2026-12-15"


def test_search_round_trip_passes_all_legs_to_run_search(client, monkeypatch):
    seen = {}

    async def fake_run_search(req):
        seen["req"] = req
        return {"legs": [], "combos": [], "errors": [], "stats": {}}

    monkeypatch.setattr(app.main, "run_search", fake_run_search)
    assert client.post("/api/search", json=ROUND_TRIP).status_code == 200
    legs = seen["req"].legs
    assert len(legs) == 2
    assert legs[1].origins == []  # vuoto: parte dagli arrivi della tappa precedente
    assert legs[1].destinations == ["NAP", "BRI"]
    assert legs[1].date == "2026-12-20"


def test_search_enriches_airports_from_results(client, monkeypatch):
    async def fake_run_search(req):
        segment = {"origin": "NAP", "destination": "BCN"}
        item = {"origin": "NAP", "destination": "BCN", "segments": [segment]}
        leg = {"index": 0, "origins": ["NAP"], "destinations": ["BCN"], "itineraries": [item]}
        return {"legs": [leg], "combos": [], "errors": [], "stats": {}}

    monkeypatch.setattr(app.main, "run_search", fake_run_search)
    body = client.post("/api/search", json=VALID_SEARCH).json()
    assert set(body["airports"]) == {"NAP", "BCN"}


def test_search_invalid_time_is_400(client):
    payload = {"legs": [{**VALID_SEARCH["legs"][0], "filters": {"arrive_to": "25:99"}}]}
    r = client.post("/api/search", json=payload)
    assert r.status_code == 400


def test_search_first_leg_without_origins_is_400(client):
    payload = {"legs": [{"origins": [], "destinations": ["BCN"], "date": "2026-12-15"}]}
    assert client.post("/api/search", json=payload).status_code == 400


def test_search_leg_dates_out_of_order_is_400(client):
    payload = {"legs": [
        {"origins": ["NAP"], "destinations": ["BCN"], "date": "2026-12-20"},
        {"destinations": ["NAP"], "date": "2026-12-15"},
    ]}
    assert client.post("/api/search", json=payload).status_code == 400


def test_search_requires_legs(client):
    r = client.post("/api/search", json={"legs": []})
    assert r.status_code == 422


def test_search_rejects_more_than_five_legs(client):
    leg = {"origins": ["NAP"], "destinations": ["BCN"], "date": "2026-12-15"}
    r = client.post("/api/search", json={"legs": [leg] * 6})
    assert r.status_code == 422


def test_search_leg_requires_destinations(client):
    r = client.post("/api/search", json={"legs": [{"origins": ["NAP"], "destinations": [], "date": "2026-12-15"}]})
    assert r.status_code == 422


# ---------- autenticazione ----------

def test_api_requires_login_when_password_set(locked):
    with TestClient(fastapi_app) as c:
        r = c.post("/api/search", json=VALID_SEARCH)
    assert r.status_code == 401


def test_healthz_stays_public_when_password_set(locked):
    with TestClient(fastapi_app) as c:
        assert c.get("/healthz").status_code == 200


def test_page_redirects_to_login_when_password_set(locked):
    with TestClient(fastapi_app) as c:
        r = c.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_login_with_wrong_password_is_401(locked):
    with TestClient(fastapi_app) as c:
        r = c.post("/login", data={"password": "sbagliata"}, follow_redirects=False)
    assert r.status_code == 401
    assert "Password sbagliata" in r.text


def test_login_with_right_password_sets_cookie_and_grants_access(locked):
    with TestClient(fastapi_app) as c:
        r = c.post("/login", data={"password": "pw"}, follow_redirects=False)
        assert r.status_code == 303
        assert app.auth.COOKIE_NAME in r.cookies or app.auth.COOKIE_NAME in c.cookies
        assert c.get("/").status_code == 200
