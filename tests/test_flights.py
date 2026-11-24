import re

import pytest

from app.flights import _time, parse_payload, shift_date

ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


@pytest.fixture
def itineraries(payload_bri_bcn):
    return parse_payload(
        payload_bri_bcn,
        origin="BRI",
        destination="BCN",
        date="2026-12-15",
        currency="EUR",
        booking_url="x",
    )


def test_parse_payload_returns_itineraries(itineraries):
    assert len(itineraries) > 0


def test_itineraries_route_matches_request(itineraries):
    for it in itineraries:
        assert it.segments[0].origin == "BRI"
        assert it.segments[-1].destination == "BCN"
        assert it.origin == "BRI" and it.destination == "BCN"
        assert it.date == "2026-12-15"
        assert it.currency == "EUR"
        assert it.booking_url == "x"


def test_departure_and_arrival_are_iso_minutes(itineraries):
    for it in itineraries:
        assert ISO_MINUTE.match(it.departure), it.departure
        assert ISO_MINUTE.match(it.arrival), it.arrival
        for seg in it.segments:
            assert ISO_MINUTE.match(seg.departure), seg.departure
            assert ISO_MINUTE.match(seg.arrival), seg.arrival


def test_layovers_match_segments(itineraries):
    for it in itineraries:
        assert len(it.layovers) == len(it.segments) - 1
        assert it.stops == len(it.segments) - 1
        for lay in it.layovers:
            assert lay.minutes >= 0


def test_itinerary_keys_are_unique(itineraries):
    keys = [it.key for it in itineraries]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize(
    "value, expected",
    [
        ([8], (8, 0)),
        ([None, 31], (0, 31)),
        (None, (0, 0)),
        ([8, 45], (8, 45)),
        ([], (0, 0)),
    ],
)
def test_time_padding(value, expected):
    assert _time(value) == expected


def test_shift_date_across_year_end():
    assert shift_date("2026-12-31", 1) == "2027-01-01"


def test_shift_date_backwards():
    assert shift_date("2026-01-01", -1) == "2025-12-31"
