"""Test fixtures.

Every test runs against a temporary data directory with fixture responses, so
the suite never spends live API quota and never touches production storage.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_ENV_FILE", str(tmp_path / "nonexistent.env"))
    monkeypatch.setenv("TRADE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COMTRADE_API_KEY", "test-key-0123456789abcdef")
    monkeypatch.setenv("COMTRADE_API_KEY_SECONDARY", "")
    monkeypatch.setenv("COMTRADE_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("COMTRADE_DAILY_CALL_BUDGET", "20")
    monkeypatch.setenv("COMTRADE_INTERACTIVE_RESERVE", "5")
    monkeypatch.setenv("COMTRADE_GLOBAL_BACKFILL_BUDGET", "3")
    monkeypatch.setenv("COMTRADE_MAX_RECORDS", "10")
    monkeypatch.setenv("COMTRADE_MAX_RETRIES", "2")
    monkeypatch.setenv("COMTRADE_RETRY_BASE_DELAY", "0")
    monkeypatch.setenv("COMTRADE_RETRY_MAX_DELAY", "0")
    monkeypatch.setenv("TRADE_BASE_PATH", "/trade")
    monkeypatch.setenv("USE_FIXTURE_DATA", "false")

    from trade_api import cache, config, state, store

    config.get_settings.cache_clear()
    state.reset_thread_conn()
    cache._cache = None
    if hasattr(store._local, "duck"):
        del store._local.duck
    config.get_settings().ensure_dirs()
    yield
    state.reset_thread_conn()
    config.get_settings.cache_clear()


@pytest.fixture
def settings():
    from trade_api.config import get_settings

    return get_settings()


def comtrade_rows(**overrides):
    """A minimal well-formed Comtrade record."""
    base = {
        "typeCode": "C", "freqCode": "A", "refYear": 2024, "refMonth": 52,
        "period": "2024", "reporterCode": 31, "flowCode": "X", "partnerCode": 0,
        "partner2Code": 0, "classificationCode": "H6", "cmdCode": "TOTAL",
        "customsCode": "C00", "motCode": 0, "qty": 0.0, "netWgt": None,
        "primaryValue": 1000.0, "isReported": True, "isAggregate": True,
        "qtyUnitAbbr": "N/A",
    }
    base.update(overrides)
    return base


def payload(rows, count=None):
    return {"elapsedTime": "0.1 secs", "count": count if count is not None else len(rows),
            "data": rows, "error": ""}
