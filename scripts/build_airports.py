#!/usr/bin/env python3
"""Build app/data/airports.json from the OurAirports open dataset.

Keeps scheduled-service airports with a 3-letter IATA code and a large,
medium or small airport type, and writes a compact JSON array sorted by
type (large, medium, small) and then by name.
"""

import csv
import io
import json
import re
import urllib.request
from pathlib import Path

BASE_URL = "https://davidmegginson.github.io/ourairports-data/"
AIRPORTS_URL = BASE_URL + "airports.csv"
COUNTRIES_URL = BASE_URL + "countries.csv"

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "app" / "data" / "airports.json"

TYPE_ORDER = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
SIZE_CODE = {"large_airport": "L", "medium_airport": "M", "small_airport": "S"}
IATA_RE = re.compile(r"^[A-Z]{3}$")


def download_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "airports-json-builder/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode("utf-8")


def load_countries(text: str) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(text))
    return {row["code"]: row["name"] for row in reader}


def build_records(airports_text: str, country_names: dict[str, str]) -> list[dict]:
    reader = csv.DictReader(io.StringIO(airports_text))
    records = []
    for row in reader:
        if row.get("scheduled_service") != "yes":
            continue
        iata = row.get("iata_code", "")
        if not IATA_RE.match(iata):
            continue
        airport_type = row.get("type", "")
        if airport_type not in TYPE_ORDER:
            continue
        if not row.get("latitude_deg") or not row.get("longitude_deg"):
            continue
        cc = row.get("iso_country", "")
        records.append(
            {
                "iata": iata,
                "name": row.get("name", ""),
                "city": row.get("municipality", ""),
                "country": country_names.get(cc, ""),
                "cc": cc,
                "continent": row.get("continent", ""),
                "lat": round(float(row["latitude_deg"]), 4),
                "lon": round(float(row["longitude_deg"]), 4),
                "size": SIZE_CODE[airport_type],
                "_type": airport_type,
            }
        )
    records.sort(key=lambda r: (TYPE_ORDER[r["_type"]], r["name"]))
    for r in records:
        del r["_type"]
    return records


def main() -> None:
    countries = load_countries(download_text(COUNTRIES_URL))
    airports = build_records(download_text(AIRPORTS_URL), countries)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(airports, fh, separators=(",", ":"), ensure_ascii=False)

    print(f"Wrote {len(airports)} airports to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
