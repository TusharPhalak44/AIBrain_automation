"""Tests for SSOT 14-Pair Universe, /api/instruments endpoint, decimal precision, and manual execution."""

from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from backend.app.api.server import app
from backend.app.core.instruments import (
    INSTRUMENT_UNIVERSE,
    ALL_SYMBOLS,
    get_symbol_spec,
    format_symbol_price,
    is_symbol_trading_open,
    resolve_mt5_symbol,
)
from backend.app.strategy_lab.backtester import TIMEFRAME_MAP
from backend.app.strategy_lab.xm_fee_model import xm_fee_engine


@pytest.fixture
def client():
    return TestClient(app)


def test_ssot_14pair_universe_specifications():
    """Verify exact 14 high-liquidity XM instruments exist with correct specifications."""
    assert len(INSTRUMENT_UNIVERSE) == 14
    assert len(ALL_SYMBOLS) == 14

    # FOREX (6)
    forex_pairs = ["EURUSD#", "USDJPY#", "GBPUSD#", "USDCAD#", "AUDUSD#", "GBPJPY#"]
    for sym in forex_pairs:
        spec = INSTRUMENT_UNIVERSE[sym]
        assert spec.asset_class == "FOREX"
        assert not spec.is_24_7
        assert spec.contract_size == 100000.0
        if "JPY" in sym:
            assert spec.digits == 3
            assert spec.tick_size == 0.001
        else:
            assert spec.digits == 5
            assert spec.tick_size == 0.00001

    # COMMODITIES (4)
    commodities = ["GOLD#", "SILVER#", "OILCash#", "BRENTCash#"]
    for sym in commodities:
        spec = INSTRUMENT_UNIVERSE[sym]
        assert spec.asset_class == "COMMODITIES"
        assert not spec.is_24_7
    assert INSTRUMENT_UNIVERSE["GOLD#"].digits == 2
    assert INSTRUMENT_UNIVERSE["GOLD#"].contract_size == 100.0
    assert INSTRUMENT_UNIVERSE["SILVER#"].digits == 3
    assert INSTRUMENT_UNIVERSE["SILVER#"].contract_size == 5000.0
    assert INSTRUMENT_UNIVERSE["OILCash#"].digits == 2
    assert INSTRUMENT_UNIVERSE["OILCash#"].contract_size == 100.0
    assert INSTRUMENT_UNIVERSE["BRENTCash#"].digits == 2
    assert INSTRUMENT_UNIVERSE["BRENTCash#"].contract_size == 100.0

    # CRYPTO (4)
    crypto_pairs = ["BTCUSD#", "ETHUSD#", "SOLUSD#", "XRPUSD#"]
    for sym in crypto_pairs:
        spec = INSTRUMENT_UNIVERSE[sym]
        assert spec.asset_class == "CRYPTO"
        assert spec.is_24_7
    assert INSTRUMENT_UNIVERSE["BTCUSD#"].digits == 2
    assert INSTRUMENT_UNIVERSE["ETHUSD#"].digits == 2
    assert INSTRUMENT_UNIVERSE["SOLUSD#"].digits == 2
    assert INSTRUMENT_UNIVERSE["XRPUSD#"].digits == 4


def test_symbol_price_formatting_precision():
    """Verify format_symbol_price formats prices to exact symbol digits without floating jitter."""
    assert format_symbol_price("EURUSD#", 1.084523) == "1.08452"
    assert format_symbol_price("USDJPY#", 154.3204) == "154.320"
    assert format_symbol_price("GOLD#", 2650.5) == "2650.50"
    assert format_symbol_price("SILVER#", 31.4567) == "31.457"
    assert format_symbol_price("OILCash#", 71.4) == "71.40"
    assert format_symbol_price("BTCUSD#", 94520.1) == "94520.10"
    assert format_symbol_price("XRPUSD#", 0.61452) == "0.6145"


def test_weekend_trading_hours_gating():
    """Verify Forex/Commodities are closed on weekend while Crypto remains 24/7."""
    # Saturday 12:00 UTC
    sat_utc = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert not is_symbol_trading_open("EURUSD#", ref_time_utc=sat_utc)
    assert not is_symbol_trading_open("GOLD#", ref_time_utc=sat_utc)
    assert not is_symbol_trading_open("OILCash#", ref_time_utc=sat_utc)
    assert is_symbol_trading_open("BTCUSD#", ref_time_utc=sat_utc)
    assert is_symbol_trading_open("ETHUSD#", ref_time_utc=sat_utc)
    assert is_symbol_trading_open("XRPUSD#", ref_time_utc=sat_utc)

    # Tuesday 14:00 UTC (Market open for all)
    tue_utc = datetime(2026, 11, 24, 14, 0, tzinfo=timezone.utc)
    assert is_symbol_trading_open("EURUSD#", ref_time_utc=tue_utc)
    assert is_symbol_trading_open("GOLD#", ref_time_utc=tue_utc)
    assert is_symbol_trading_open("BTCUSD#", ref_time_utc=tue_utc)


def test_get_instruments_endpoint(client):
    """Verify GET /api/instruments and /api/pairs/instruments return all 14 pairs with full metadata."""
    resp = client.get("/api/instruments")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 14

    symbols = [item["symbol"] for item in data]
    assert "EURUSD#" in symbols
    assert "GOLD#" in symbols
    assert "BTCUSD#" in symbols
    assert "XRPUSD#" in symbols

    # Test alias route
    alias_resp = client.get("/api/pairs/instruments")
    assert alias_resp.status_code == 200
    assert len(alias_resp.json()) == 14


def test_backtester_timeframes_support():
    """Verify backtester supports all standard timeframes including M30."""
    assert "M1" in TIMEFRAME_MAP
    assert "M5" in TIMEFRAME_MAP
    assert "M15" in TIMEFRAME_MAP
    assert "M30" in TIMEFRAME_MAP
    assert TIMEFRAME_MAP["M30"] == 30
    assert "H1" in TIMEFRAME_MAP
    assert "H4" in TIMEFRAME_MAP
    assert "D1" in TIMEFRAME_MAP


def test_fee_engine_all_14_instruments():
    """Verify XM fee model has accurate fallback specs for all 14 instruments."""
    for sym in ALL_SYMBOLS:
        spec = xm_fee_engine.get_symbol_spec(sym)
        assert spec.contract_size > 0
        assert spec.tick_size > 0
        assert spec.digits in (2, 3, 4, 5)


def test_manual_order_execution_validation(client):
    """Verify POST /api/trades/execute enforces mandatory hard SL and rejects invalid parameters."""
    # Zero / negative SL rejected
    res = client.post(
        "/api/trades/execute",
        json={
            "symbol": "GOLD#",
            "order_type": "BUY",
            "lots": 0.01,
            "sl": 0.0,
        },
    )
    assert res.status_code == 400
    assert "MANDATORY_SL_REQUIRED" in res.text or "greater than 0" in res.text
