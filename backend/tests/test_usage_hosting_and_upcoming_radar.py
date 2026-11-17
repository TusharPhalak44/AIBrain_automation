"""Comprehensive Integration Tests for Phase 5:
1. Gemini Usage & Billing Analytics Ledger, Rate Cards & Export.
2. MySQL Administration, Remote Hosting Ping, SQL Dump & Settings JSON Backup.
3. Upcoming Trades & Pre-Trigger Setups Radar.
"""

from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.base import Base
from backend.app.db.models import (
    AppSettings,
    MT5AccountProfile,
    TradingPairBot,
    TradeLedger,
    GeminiAnalysisReport,
    GeminiModelRateCard,
    GeminiUsageLedger,
)
from backend.app.db.session import init_db, get_db
from backend.app.ai_brain.usage_tracker import (
    get_model_rate_card,
    calculate_cost,
    record_gemini_usage,
)
from backend.app.api.server import create_app

# Isolated Test Database
TEST_DB_NAME = "xm_trading_v2_test"
TEST_DB_URI = f"mysql+pymysql://root:@127.0.0.1:3306/{TEST_DB_NAME}?charset=utf8mb4"

test_engine = create_engine(TEST_DB_URI, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    """Ensure test database exists and is populated."""
    root_engine = create_engine(settings.mysql_base_uri, isolation_level="AUTOCOMMIT")
    with root_engine.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{TEST_DB_NAME}`;"))
    root_engine.dispose()

    Base.metadata.drop_all(bind=test_engine)
    init_db(bind_engine=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Provide transactional session for test case."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient overriding get_db dependency."""
    app = create_app(enable_lifespan_tasks=False)

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ==============================================================================
# 1. GEMINI USAGE & BILLING TESTS
# ==============================================================================
def test_gemini_usage_cost_calculation():
    """Verify Gemini token pricing math across uncached, cached, and output tokens."""
    # Rate: input $0.75 / 1M, output $3.75 / 1M, cached $0.075 / 1M
    cost = calculate_cost(
        prompt_tokens=1000,
        output_tokens=500,
        thinking_tokens=100,
        cached_tokens=200,
        input_rate=Decimal("0.75"),
        output_rate=Decimal("3.75"),
        cached_rate=Decimal("0.075"),
    )
    # uncached = 1000 - 200 = 800 prompt tokens
    # input_cost = 800 / 1e6 * 0.75 = 0.0006
    # cached_cost = 200 / 1e6 * 0.075 = 0.000015
    # output_cost = (500 + 100) / 1e6 * 3.75 = 0.00225
    # total = 0.0006 + 0.000015 + 0.00225 = 0.002865
    assert cost == Decimal("0.002865")


def test_gemini_usage_ledger_recording_and_free_tier(db_session):
    """Verify record_gemini_usage captures metadata, IST date, and Free Tier toggle."""
    # 1. Record Paid Tier Call
    mock_response = {
        "prompt_token_count": 5000,
        "candidates_token_count": 800,
        "thoughts_token_count": 200,
        "cached_content_token_count": 1000,
    }

    entry = record_gemini_usage(
        db=db_session,
        model_id="gemini-3.8-flash",
        call_purpose="LIVE_SCAN",
        response=mock_response,
        latency_ms=250,
        symbol="GOLD#",
        account_type="DEMO",
        force_free_tier=False,
    )
    assert entry is not None
    assert entry.prompt_tokens == 5000
    assert entry.output_tokens == 800
    assert entry.thinking_tokens == 200
    assert entry.cached_tokens == 1000
    assert entry.billing_tier == "PAID"
    assert entry.estimated_cost_usd > Decimal("0.000000")
    assert entry.ist_date is not None

    # 2. Record Free Tier Call (shadow paid)
    free_entry = record_gemini_usage(
        db=db_session,
        model_id="gemini-3.8-flash",
        call_purpose="MANUAL_SCAN",
        response=mock_response,
        latency_ms=180,
        symbol="BTCUSD#",
        account_type="DEMO",
        force_free_tier=True,
    )
    assert free_entry is not None
    assert free_entry.billing_tier == "FREE"
    assert free_entry.estimated_cost_usd == Decimal("0.000000")


def test_usage_summary_and_export_endpoints(client, db_session):
    """Test GET /api/usage/summary and GET /api/usage/export."""
    # GET summary
    res = client.get("/api/usage/summary?granularity=DAILY&usd_to_inr_rate=86.50")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "totals" in data
    assert data["totals"]["total_calls"] >= 2
    assert "time_series" in data
    assert "by_symbol" in data
    assert "by_model" in data
    assert "recent_calls" in data
    assert len(data["recent_calls"]) >= 2

    # GET export CSV
    res_csv = client.get("/api/usage/export")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "Prompt Tokens" in res_csv.text
    assert "GOLD#" in res_csv.text

    # GET rates & PUT rates
    res_rates = client.get("/api/usage/rates")
    assert res_rates.status_code == 200
    assert len(res_rates.json()["rates"]) >= 5

    res_put_rates = client.put(
        "/api/usage/rates",
        json={
            "rates": [
                {
                    "model_id": "gemini-3.8-flash",
                    "input_per_1m_usd": 0.80,
                    "output_per_1m_usd": 4.00,
                    "cached_per_1m_usd": 0.08,
                    "is_free_tier_eligible": True,
                }
            ],
            "gemini_use_free_tier": True,
        },
    )
    assert res_put_rates.status_code == 200
    assert res_put_rates.json()["status"] == "SUCCESS"


# ==============================================================================
# 2. MYSQL DATABASE ADMIN & EXPORT TESTS
# ==============================================================================
def test_db_admin_status_and_export_sql(client):
    """Test GET /api/db-admin/status and clean phpMyAdmin SQL dump export."""
    res = client.get("/api/db-admin/status")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["is_connected"] is True
    assert data["latency_ms"] >= 0
    assert "table_counts" in data
    assert "app_settings" in data["table_counts"]

    # Test SQL dump export
    res_sql = client.get("/api/db-admin/export-sql")
    assert res_sql.status_code == 200
    assert "application/sql" in res_sql.headers["content-type"]
    sql_text = res_sql.text
    assert "SET FOREIGN_KEY_CHECKS=0;" in sql_text
    assert ("INSERT INTO `app_settings`" in sql_text) or ("REPLACE INTO `app_settings`" in sql_text)
    assert "CREATE TABLE IF NOT EXISTS app_settings" in sql_text
    assert ("INSERT INTO `trading_pair_bots`" in sql_text) or ("REPLACE INTO `trading_pair_bots`" in sql_text)

    # Test settings JSON backup & restore
    res_json_export = client.get("/api/db-admin/export-settings-json")
    assert res_json_export.status_code == 200
    backup_data = res_json_export.json()
    assert "app_settings" in backup_data
    assert "pairs" in backup_data

    res_import = client.post("/api/db-admin/import-settings-json", json=backup_data)
    assert res_import.status_code == 200
    assert res_import.json()["status"] == "SUCCESS"

    # Test switch active target
    res_switch = client.post("/api/db-admin/switch-target?target=LOCAL_XAMPP")
    assert res_switch.status_code == 200
    assert res_switch.json()["active_target"] == "LOCAL_XAMPP"


# ==============================================================================
# 3. UPCOMING TRADES & RADAR TESTS
# ==============================================================================
def test_upcoming_setups_radar(client, db_session):
    """Test GET /api/ai/upcoming-setups and pre-staging limit order into Copilot."""
    # Seed an analysis report with upcoming_setup_json
    upcoming_dict = {
        "watch_bias": "BULLISH_WATCH",
        "setup_mode": "SCALP",
        "trigger_zone_low": 3850.00,
        "trigger_zone_high": 3855.00,
        "planned_entry": 3852.50,
        "planned_sl": 3845.00,
        "planned_tp1": 3863.75,
        "planned_tp2": 3875.00,
        "rr_ratio": 3.0,
        "readiness_pct": 85,
        "trigger_condition": "Wait for M15 liquidity sweep below 3850 followed by FVG close",
        "invalidation_level": 3845.00,
        "expected_window": "Next 1-2 hours",
    }

    report = GeminiAnalysisReport(
        account_type="DEMO",
        symbol="GOLD#",
        scanned_at_utc=now_utc(),
        market_regime="RANGE_SWEEP",
        decision="WAIT",
        recommended_mode="SCALP",
        confidence=Decimal("0.85"),
        entry_price=Decimal("3852.50"),
        stop_loss=Decimal("3845.00"),
        tp1=Decimal("3863.75"),
        tp2=Decimal("3875.00"),
        news_summary="Clear horizon",
        thesis_text="Gold approaching high-probability liquidity sweep zone.",
        execution_status="WAITING",
        upcoming_setup_json=json.dumps(upcoming_dict),
        readiness_pct=85,
        watch_bias="BULLISH_WATCH",
    )
    db_session.add(report)

    # Also seed a staged PLANNED Copilot trade
    staged = TradeLedger(
        account_type="DEMO",
        position_id=0,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="PLANNED",
        lots=Decimal("0.05"),
        initial_lots=Decimal("0.05"),
        entry_price=Decimal("3852.50"),
        sl=Decimal("3845.00"),
        tp1=Decimal("3863.75"),
        tp2=Decimal("3875.00"),
        opened_at_utc=now_utc(),
        ai_analysis_summary="Planned Copilot scalp order",
    )
    db_session.add(staged)
    db_session.commit()

    # Query upcoming setups endpoint
    res = client.get("/api/ai/upcoming-setups")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert "actionable_setups" in data
    assert "watchlist_radar" in data
    assert len(data["actionable_setups"]) >= 1
    assert len(data["watchlist_radar"]) >= 1

    # Check actionable item properties
    act = data["actionable_setups"][0]
    assert act["symbol"] == "GOLD#"
    assert act["direction"] == "BUY"
    assert "distance_points" in act
    assert "in_trigger_zone" in act
    assert act["readiness_pct"] >= 80

    # Check watchlist item properties
    watch = [w for w in data["watchlist_radar"] if w["symbol"] == "GOLD#"]
    assert len(watch) > 0
    w_item = watch[0]
    assert w_item["watch_bias"] == "BULLISH_WATCH"
    assert w_item["readiness_pct"] == 85
    assert w_item["planned_entry"] == 3852.50
    assert w_item["rr_ratio"] == 3.0
    assert "trigger_condition" in w_item
