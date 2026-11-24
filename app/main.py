from __future__ import annotations

import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .config import settings
from .filters import FlightFilters, parse_hhmm
from .search import MAX_TRIP_LEGS, SearchRequest, TooManyQueries, TripLeg, run_search
from .stays import stay_links

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
AIRPORTS_FILE = Path(__file__).resolve().parent / "data" / "airports.json"

app = FastAPI(title="Povero e senza biga", docs_url=None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.middleware("http")(auth.auth_middleware)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------- aeroporti ----------

def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


@lru_cache
def airports() -> list[dict]:
    data = json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))
    for a in data:
        a["_s"] = _norm(f"{a['iata']} {a['name']} {a['city']} {a['country']}")
    return data


@lru_cache
def airports_by_iata() -> dict[str, dict]:
    return {a["iata"]: a for a in airports()}


def _public(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.startswith("_")}


@app.get("/api/airports")
def search_airports(q: str = Query("", max_length=60), limit: int = Query(12, le=50)):
    q = _norm(q.strip())
    if not q:
        return []
    exact, starts, contains = [], [], []
    for a in airports():
        if a["iata"].lower() == q:
            exact.append(a)
        elif _norm(a["city"]).startswith(q) or _norm(a["name"]).startswith(q):
            starts.append(a)
        elif q in a["_s"]:
            contains.append(a)
    rank = {"L": 0, "M": 1, "S": 2}
    starts.sort(key=lambda a: rank.get(a["size"], 3))
    contains.sort(key=lambda a: rank.get(a["size"], 3))
    return [_public(a) for a in (exact + starts + contains)[:limit]]


@app.get("/api/airports/{iata}")
def get_airport(iata: str):
    a = airports_by_iata().get(iata.upper())
    if not a:
        raise HTTPException(404, "aeroporto sconosciuto")
    return _public(a)


# ---------- voli ----------

class FiltersIn(BaseModel):
    depart_from: str | None = None  # "HH:MM"
    depart_to: str | None = None
    arrive_from: str | None = None
    arrive_to: str | None = None
    max_stops: int | None = Field(None, ge=0, le=3)
    min_layover: int | None = Field(None, ge=0, description="minuti")
    max_layover: int | None = Field(None, ge=0, description="minuti")
    long_layover_only: bool = False
    long_layover_threshold: int = Field(360, ge=60, description="minuti")
    max_price: int | None = Field(None, ge=0)
    max_duration: int | None = Field(None, ge=0, description="minuti")

    def to_filters(self) -> FlightFilters:
        return FlightFilters(
            depart_from=parse_hhmm(self.depart_from),
            depart_to=parse_hhmm(self.depart_to),
            arrive_from=parse_hhmm(self.arrive_from),
            arrive_to=parse_hhmm(self.arrive_to),
            max_stops=self.max_stops,
            min_layover=self.min_layover,
            max_layover=self.max_layover,
            long_layover_only=self.long_layover_only,
            long_layover_threshold=self.long_layover_threshold,
            max_price=self.max_price,
            max_duration=self.max_duration,
        )


class LegIn(BaseModel):
    origins: list[str] = Field(default_factory=list, max_length=6)  # vuoto = arrivi della tappa precedente
    destinations: list[str] = Field(..., min_length=1, max_length=6)
    date: str
    filters: FiltersIn = Field(default_factory=FiltersIn)


class SearchIn(BaseModel):
    legs: list[LegIn] = Field(..., min_length=1, max_length=MAX_TRIP_LEGS)
    flex_days: int = Field(0, ge=0, le=3)
    adults: int = Field(1, ge=1, le=9)
    min_hours_at_destination: int = Field(3, ge=0, le=72)


@app.post("/api/search")
async def api_search(body: SearchIn):
    try:
        req = SearchRequest(
            legs=[
                TripLeg(origins=l.origins, destinations=l.destinations, date=l.date, filters=l.filters.to_filters())
                for l in body.legs
            ],
            flex_days=body.flex_days,
            adults=body.adults,
            min_hours_at_destination=body.min_hours_at_destination,
        )
        result = await run_search(req)
    except TooManyQueries as exc:
        raise HTTPException(422, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # arricchisci con nomi città degli aeroporti coinvolti
    codes: set[str] = set()
    for leg in result["legs"]:
        codes.update(leg["origins"]); codes.update(leg["destinations"])
        for it in leg["itineraries"]:
            for s in it["segments"]:
                codes.update((s["origin"], s["destination"]))
    by = airports_by_iata()
    result["airports"] = {c: _public(by[c]) for c in codes if c in by}
    return result


# ---------- alloggi ----------

@app.get("/api/stays")
def api_stays(
    city: Annotated[str, Query(min_length=1, max_length=80)],
    checkin: str,
    checkout: str,
    guests: int = Query(1, ge=1, le=9),
    max_price: int = Query(40, ge=1, le=1000),
    country: str = "",
    continent: str = "",
):
    if not continent and country:
        continent = next((a.get("continent", "") for a in airports() if a["country"] == country), "")
    return stay_links(city, checkin, checkout, guests, max_price, settings.currency, country, continent)


# ---------- pagine ----------

@app.get("/api/me")
def api_me():
    """Dice al frontend se il sito è protetto da password (per mostrare «Esci»)."""
    return {"auth_required": bool(settings.app_password)}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "favicon.svg")


LOGIN_PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Povero e senza biga · accesso</title>
<link rel="stylesheet" href="/static/style.css"></head><body class="login">
<form method="post" action="/login" class="login-box"><h1>Povero e senza biga</h1>
<p>Password condivisa</p>{error}<input type="password" name="password" autofocus required>
<button type="submit">Entra</button></form></body></html>"""


@app.get("/login", include_in_schema=False)
def login_page():
    if not settings.app_password:
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(LOGIN_PAGE.format(error=""))


@app.post("/login", include_in_schema=False)
def login(password: Annotated[str, Form()]):
    if not auth.check_password(password):
        return HTMLResponse(
            LOGIN_PAGE.format(error='<p class="error">Password sbagliata</p>'), status_code=401
        )
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.COOKIE_NAME, auth.make_token(), max_age=auth.MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.get("/logout", include_in_schema=False)
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp
