"""Fixture condivise. I test sono offline: nessuna chiamata di rete."""

import dataclasses
import json
from pathlib import Path

import pytest

import app.auth
import app.main

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_app_password(monkeypatch):
    """Il sito è aperto per default: APP_PASSWORD dell'ambiente non deve influire sui test."""
    monkeypatch.setattr(app.auth, "settings", dataclasses.replace(app.auth.settings, app_password=""))
    monkeypatch.setattr(app.main, "settings", dataclasses.replace(app.main.settings, app_password=""))


@pytest.fixture
def payload_bri_bcn():
    return json.loads((FIXTURES / "payload_bri_bcn.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_search_response():
    return json.loads((FIXTURES / "sample_search_response.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _no_retry_wait(monkeypatch):
    """Nei test i nuovi tentativi non aspettano."""
    import app.search
    monkeypatch.setattr(app.search, "RETRY_DELAYS", (0, 0))
