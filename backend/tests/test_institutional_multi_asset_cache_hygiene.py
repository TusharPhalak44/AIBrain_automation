"""Comprehensive Verification Suite for Multi-Asset Expansion, Cache Hygiene & Institutional Supervisor.

Verifies:
1. Multi-Asset Instrument Universe (14 Pairs across Forex, Commodities, Crypto 24/7).
2. MarketWatch Symbol Suffix Resolution & Weekend Trading Gating.
3. Daily Cache Hygiene Engine (purging DFs, expired radar TTL, buffers; preserving DB rules & trades).
4. Categorized Upcoming Pre-Trigger Radar (Scalp vs Swing schema & endpoints).
5. Dynamic AI Scanning Intervals & Timeframe Matrix Hot-Reload.
6. Institutional 5-Gate Gemini Supervisory System Prompt Builder & Preview.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.db.base import Base
from backend.app.db.models import (
    AppSettings,
    TradingPairBot,
    LearnedPairRule,
    TradeLedger,
    GeminiAnalysisReport,
)
from backend.app.ai_brain.instruments import (
    INSTRUMENT_UNIVERSE,
    resolve_marketwatch_symbol,
    is_symbol_trading_open,
    get_instruments_by_asset_class,
)
from backend.app.ai_brain.cache_manager import cache_manager
from backend.app.ai_brain.gemini_supervisor import (
    gemini_supervisor,
    build_supervisor_prompt,
    INSTITUTIONAL_SUPERVISOR_SYSTEM_PROMPT,
    UpcomingSetupPlan,
    GeminiSupervisoryOutput,
)
from backend.app.ai_brain.market_packet import MarketPacket
from fastapi.testclient import TestClient
from backend.app.api.server import app


# Isolated test database fixture
@pytest.fixture(scope="module")
def test_db_session():
    from backend.app.db.session import auto_bootstrap_database, init_db
    auto_bootstrap_database("xm_trading_v2_test")
    test_db_url = f"{settings.mysql_base_uri.rstrip('/')}/xm_trading_v2_test"
    engine = create_engine(test_db_url, pool_pre_ping=True)
    init_db(bind_engine=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed singleton AppSettings if needed
    st = session.query(AppSettings).filter_by(id=1).first()
    if not st:
        session.add(
            AppSettings(
                id=1,
                execution_mode="AUTO",
                active_account_type="DEMO",
                global_scan_interval_sec=300,
                scalp_planning_tf="M15",
                scalp_execution_tf="M5",
                swing_planning_tf="H4",
                swing_execution_tf="H1",
                cache_auto_daily_enabled=True,
                cache_daily_purge_hour_utc=0,
                cache_daily_purge_minute_utc=5,
            )
        )
        session.commit()

    yield session
    session.close()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# =============================================================================
# 1. Multi-Asset Instrument Universe & Weekend Gating
# =============================================================================
def test_multi_asset_instrument_universe():
    """Verify 14 instruments across Forex, Commodities, and Crypto."""
    assert len(INSTRUMENT_UNIVERSE) == 14

    forex = get_instruments_by_asset_class("FOREX")
    assert len(forex) == 6
    forex_syms = {f.symbol for f in forex}
    assert forex_syms == {"EURUSD#", "USDJPY#", "GBPUSD#", "USDCAD#", "AUDUSD#", "GBPJPY#"}

    commodities = get_instruments_by_asset_class("COMMODITIES")
    assert len(commodities) == 4
    comm_syms = {c.symbol for c in commodities}
    assert comm_syms == {"GOLD#", "SILVER#", "OILCash#", "BRENTCash#"}

    crypto = get_instruments_by_asset_class("CRYPTO")
    assert len(crypto) == 4
    crypto_syms = {c.symbol for c in crypto}
    assert crypto_syms == {"BTCUSD#", "ETHUSD#", "SOLUSD#", "XRPUSD#"}

    # Verify Crypto is strictly 24/7 while Forex/Commodities are not
    for c in crypto:
        assert c.is_24_7 is True
    for f in forex:
        assert f.is_24_7 is False
    for m in commodities:
        assert m.is_24_7 is False


def test_marketwatch_symbol_resolution_and_aliases():
    """Verify alias and suffix resolution for broker variations."""
    # Commodity aliases
    oil_spec = INSTRUMENT_UNIVERSE["OILCash#"]
    assert "OILCash" in oil_spec.aliases
    assert "USOIL#" in oil_spec.aliases
    assert "USOIL" in oil_spec.aliases

    brent_spec = INSTRUMENT_UNIVERSE["BRENTCash#"]
    assert "BRENTCash" in brent_spec.aliases
    assert "UKOIL#" in brent_spec.aliases

    gold_spec = INSTRUMENT_UNIVERSE["GOLD#"]
    assert "XAUUSD" in gold_spec.aliases
    assert "XAUUSD#" in gold_spec.aliases

    # Test resolver function fallback
    resolved = resolve_marketwatch_symbol("OILCash#")
    assert resolved in ("OILCash#", "OILCash", "USOIL#", "USOIL")


def test_weekend_trading_gating():
    """Verify Crypto scans 24/7 on weekends while Forex and Commodities are skipped."""
    # A Saturday at 14:00 UTC (Saturday = weekday 5)
    sat_utc = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc)
    # A Tuesday at 14:00 UTC (Tuesday = weekday 1)
    tue_utc = datetime(2026, 11, 24, 14, 0, 0, tzinfo=timezone.utc)

    # Forex & Commodities should be closed on Saturday
    assert is_symbol_trading_open("EURUSD#", "FOREX", ref_time_utc=sat_utc) is False
    assert is_symbol_trading_open("GOLD#", "COMMODITIES", ref_time_utc=sat_utc) is False
    assert is_symbol_trading_open("OILCash#", "COMMODITIES", ref_time_utc=sat_utc) is False

    # Crypto MUST remain open 24/7 on Saturday
    assert is_symbol_trading_open("BTCUSD#", "CRYPTO", ref_time_utc=sat_utc) is True
    assert is_symbol_trading_open("ETHUSD#", "CRYPTO", ref_time_utc=sat_utc) is True
    assert is_symbol_trading_open("SOLUSD#", "CRYPTO", ref_time_utc=sat_utc) is True

    # On Tuesday, all markets are open
    assert is_symbol_trading_open("EURUSD#", "FOREX", ref_time_utc=tue_utc) is True
    assert is_symbol_trading_open("GOLD#", "COMMODITIES", ref_time_utc=tue_utc) is True
    assert is_symbol_trading_open("BTCUSD#", "CRYPTO", ref_time_utc=tue_utc) is True


# =============================================================================
# 2. Daily Cache Hygiene Engine & Endpoints
# =============================================================================
def test_cache_hygiene_purge_and_db_immutability(test_db_session):
    """Verify cache purge clears in-memory buffers while strictly preserving MySQL rules & trades."""
    # 1. Insert test records in MySQL (must NOT be touched)
    test_rule = LearnedPairRule(
        rule_code="RULE_IMMUNE_TEST_001",
        symbol="GOLD#",
        mode="SCALP",
        status="LIVE",
        condition_json=json.dumps({"indicator": "spread"}),
        action_json=json.dumps({"action": "BLOCK"}),
        backtest_net_improvement_pct=Decimal("12.50"),
    )
    test_db_session.query(LearnedPairRule).filter_by(rule_code="RULE_IMMUNE_TEST_001").delete()
    test_db_session.add(test_rule)
    test_db_session.commit()

    # 2. Populate in-memory cache
    cache_manager.store_df("GOLD#_M5_100", {"dummy": [1, 2, 3]})
    cache_manager.store_df("BTCUSD#_H1_100", {"dummy": [4, 5, 6]})
    cache_manager.store_radar_setup("GOLD#", {"symbol": "GOLD#", "plan": "buy"}, style="SCALP")
    cache_manager.store_radar_setup("BTCUSD#", {"symbol": "BTCUSD#", "plan": "sell"}, style="SWING")
    cache_manager.store_payload("temp_prompt_gold", "Analyze gold price action")
    cache_manager.store_tick("GOLD#", {"bid": 2650.0, "ask": 2650.5})

    status_before = cache_manager.get_status(db=test_db_session)
    assert status_before["cached_entries_count"] >= 5

    # 3. Trigger manual purge
    summary = cache_manager.purge_stale_entries(force_all=True, reason="UNIT_TEST_PURGE", db=test_db_session)
    assert summary["items_cleared"] >= 5
    assert summary["reason"] == "UNIT_TEST_PURGE"

    status_after = cache_manager.get_status(db=test_db_session)
    assert status_after["cached_entries_count"] == 0
    assert status_after["last_cleared_at_utc"] is not None

    # 4. CRITICAL INVARIANT: Verify MySQL LearnedPairRule was untouched!
    saved_rule = test_db_session.query(LearnedPairRule).filter_by(rule_code="RULE_IMMUNE_TEST_001").first()
    assert saved_rule is not None
    assert saved_rule.status == "LIVE"


def test_cache_api_endpoints(client):
    """Verify GET, POST, and PATCH cache management endpoints and /api/ai-brain alias."""
    # Test GET /api/ai/cache/status
    res = client.get("/api/ai/cache/status")
    assert res.status_code == 200
    data = res.json()
    assert "health_badge" in data
    assert "auto_daily_enabled" in data
    assert "cached_entries_count" in data

    # Test POST /api/ai/cache/clear
    res_clear = client.post("/api/ai/cache/clear?force_all=true")
    assert res_clear.status_code == 200
    data_clear = res_clear.json()
    assert data_clear["status"] == "SUCCESS"
    assert "items purged" in data_clear["message"]

    # Test PATCH /api/ai/cache/config
    res_cfg = client.patch("/api/ai/cache/config", json={"auto_daily_enabled": True, "daily_purge_hour_utc": 1})
    assert res_cfg.status_code == 200
    assert res_cfg.json()["config"]["daily_purge_hour_utc"] == 1

    # Test alias: GET /api/ai-brain/cache/status
    res_alias = client.get("/api/ai-brain/cache/status")
    assert res_alias.status_code == 200
    assert res_alias.json()["health_badge"] in ("Healthy", "Purge Due")


# =============================================================================
# 3. Categorized Pre-Trigger Radar (Scalp vs Swing)
# =============================================================================
def test_categorized_radar_api_response(client):
    """Verify /api/ai/upcoming-setups categorizes Scalp vs Swing setups with all required attributes."""
    res = client.get("/api/ai/upcoming-setups")
    assert res.status_code == 200
    data = res.json()

    assert "actionable_setups" in data
    assert "watchlist_radar" in data
    assert "scalp_setups" in data
    assert "swing_setups" in data

    # Check watchlist item schema if items exist
    for item in data["watchlist_radar"]:
        assert "symbol" in item
        assert "asset_class" in item
        assert "trade_style" in item
        assert item["trade_style"] in ("SCALP", "SWING")
        assert "planning_tf" in item
        assert "execution_tf" in item
        assert "trigger_price" in item
        assert "distance_pips_or_pct" in item
        assert "invalidation_price" in item
        assert "projected_rr" in item
        assert "expires_at" in item
        assert "proximity_pct" in item


# =============================================================================
# 4. Dynamic AI Scanning Intervals & Timeframe Matrix Hot-Reload
# =============================================================================
def test_scanner_config_endpoints(client):
    """Verify /api/ai/scanner/config GET and POST hot-reload intervals and timeframe matrix."""
    # Get initial config
    res = client.get("/api/ai/scanner/config")
    assert res.status_code == 200
    cfg = res.json()
    assert "global_scan_interval_sec" in cfg
    assert "scalp_planning_tf" in cfg
    assert "scalp_execution_tf" in cfg
    assert "swing_planning_tf" in cfg
    assert "swing_execution_tf" in cfg
    assert "pairs" in cfg
    assert len(cfg["pairs"]) >= 14

    # Update intervals and timeframe matrix
    update_payload = {
        "global_scan_interval_sec": 180,
        "scalp_planning_tf": "H1",
        "scalp_execution_tf": "M5",
        "swing_planning_tf": "D1",
        "swing_execution_tf": "H4",
    }
    res_up = client.post("/api/ai/scanner/config", json=update_payload)
    assert res_up.status_code == 200
    assert res_up.json()["status"] == "SUCCESS"

    # Verify updated values persisted
    res_after = client.get("/api/ai/scanner/config")
    cfg_after = res_after.json()
    assert cfg_after["global_scan_interval_sec"] == 180
    assert cfg_after["scalp_planning_tf"] == "H1"
    assert cfg_after["swing_planning_tf"] == "D1"

    # Revert to standard 300s
    client.post("/api/ai/scanner/config", json={"global_scan_interval_sec": 300, "scalp_planning_tf": "M15"})


def test_pair_toggle_endpoint(client):
    """Verify per-pair toggle endpoint switches pair bot enabled flag."""
    res = client.post("/api/ai/pairs/SILVER%23/toggle")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "SILVER#" in data["symbol"]


# =============================================================================
# 5. Institutional 5-Gate Gemini Supervisory System Prompt Builder & Preview
# =============================================================================
def test_institutional_prompt_builder_and_preview(client):
    """Verify modular build_supervisor_prompt() formats 5-gate protocol deterministically."""
    context = {
        "symbol": "GOLD#",
        "asset_class": "COMMODITIES",
        "trade_style": "SCALP",
        "planning_tf": "M15",
        "execution_tf": "M5",
        "scan_interval_minutes": 5,
        "active_session": "NY_OVERLAP",
        "bid": 2650.50,
        "ask": 2650.75,
        "current_spread_points": 25,
        "spread_pct_of_sl": 5.0,
        "open_positions_summary": "None (Zero Exposure)",
        "active_learned_rules_json": json.dumps([{"rule_code": "TEST_R1", "action": "BLOCK"}]),
        "max_spread_points": 80,
    }

    prompt = build_supervisor_prompt(context)
    assert "Institutional Quantitative Trading Supervisor" in prompt
    assert "GOLD# (COMMODITIES)" in prompt
    assert "NY_OVERLAP" in prompt
    assert "5-GATE INSTITUTIONAL EVALUATION PROTOCOL" in prompt
    assert "Regime & Volatility Gate" in prompt
    assert "Multi-Timeframe Order Flow Gate" in prompt
    assert "Microstructure & Spread-Friction Gate" in prompt
    assert "Asymmetric R:R Gate" in prompt
    assert "Pattern Edge & Learned Vault Gate" in prompt
    assert "PRE-TRIGGER UPCOMING RADAR GENERATION" in prompt
    assert "TEST_R1" in prompt

    # Verify GET /api/ai/prompt-preview
    res = client.get("/api/ai/prompt-preview?symbol=GOLD#")
    assert res.status_code == 200
    pdata = res.json()
    assert pdata["status"] == "SUCCESS"
    assert "rendered_prompt" in pdata
    assert "5-GATE INSTITUTIONAL EVALUATION PROTOCOL" in pdata["rendered_prompt"]
