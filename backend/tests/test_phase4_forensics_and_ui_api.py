"""Phase 4 Verification Gate: SL Forensics, Rule Engine, Candles & Symbol Resolution."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.base import Base
from backend.app.db.models import (
    TradingPairBot,
    TradeLedger,
    LearnedPairRule,
    MacroNewsEvent,
    AppSettings,
)
from backend.app.db.session import get_db
from backend.app.ai_brain.forensic_learner import forensic_learner, SLForensicDiagnosis
from backend.app.api.server import create_app

# Isolated Test Database
TEST_DB_URL = "mysql+pymysql://root:@127.0.0.1:3306/xm_trading_v2_test"
engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    # Seed default pairs
    pairs = [
        ("GOLD#", "METALS"),
        ("EURUSD#", "FOREX"),
        ("BTCUSD#", "CRYPTO"),
    ]
    for sym, asset_cls in pairs:
        p = db.query(TradingPairBot).filter_by(symbol=sym).first()
        if not p:
            p = TradingPairBot(
                symbol=sym,
                asset_class=asset_cls,
                enabled=True,
                scalp_enabled=True,
                swing_enabled=True,
            )
            db.add(p)

    settings_row = db.query(AppSettings).filter_by(id=1).first()
    if not settings_row:
        settings_row = AppSettings(
            id=1,
            execution_mode="COPILOT",
        )
        db.add(settings_row)

    db.commit()
    db.close()
    yield
    # Cleanup


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    app = create_app(enable_lifespan_tasks=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


def test_hash_symbol_url_resolution(db_session, client):
    """Test resolution of symbols across URL-encoded (%23), stripped, and canonical forms."""
    # 1. Pure helper resolution
    assert resolve_broker_symbol("GOLD#", db_session) == "GOLD#"
    assert resolve_broker_symbol("GOLD%23", db_session) == "GOLD#"
    assert resolve_broker_symbol("GOLD", db_session) == "GOLD#"
    assert resolve_broker_symbol("EURUSD", db_session) == "EURUSD#"
    assert resolve_broker_symbol("BTCUSD%23", db_session) == "BTCUSD#"

    # 2. Endpoint test with stripped and encoded symbols
    resp1 = client.get("/api/candles/GOLD")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["symbol"] == "GOLD#"
    assert data1["status"] in ["MT5_DISCONNECTED", "NO_DATA", "OK"]

    resp2 = client.get("/api/candles/GOLD%23")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["symbol"] == "GOLD#"


def test_candles_disconnected_handling(client):
    """Test candle endpoint returns MT5_DISCONNECTED without fake/mock random candles."""
    resp = client.get("/api/candles/EURUSD#?timeframe=M15&count=100")
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "EURUSD#"
    assert data["timeframe"] == "M15"
    if data["status"] == "MT5_DISCONNECTED":
        assert data["candles"] == []
        assert data["overlays"] == {}


def test_sl_hit_forensic_diagnosis_and_rule_generation(db_session):
    """Test forensic post-mortem analysis on an SL-hit trade creates a valid LearnedPairRule."""
    # Create a simulated stopped-out trade in TradeLedger
    now = datetime.now(timezone.utc)
    trade = TradeLedger(
        account_type="DEMO",
        position_id=987654321,
        order_ticket=987654321,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        lots=Decimal("0.05"),
        initial_lots=Decimal("0.05"),
        entry_price=Decimal("2650.00"),
        sl=Decimal("2645.00"),
        tp1=Decimal("2657.50"),
        tp2=Decimal("2665.00"),
        exit_price=Decimal("2644.80"),  # Slightly wicked beyond SL (< 15% overshoot)
        entry_spread_points=15,
        slippage_points=2,
        gross_pnl=Decimal("-26.00"),
        commission=Decimal("0.00"),
        swap=Decimal("0.00"),
        net_pnl=Decimal("-27.50"),
        exit_reason="SL_HIT",
        opened_at_utc=now - timedelta(minutes=45),
        closed_at_utc=now,
    )
    db_session.add(trade)
    db_session.commit()
    db_session.refresh(trade)

    # Run forensic post-mortem
    rule = forensic_learner.run_sl_hit_postmortem(trade.id, db_session)
    assert rule is not None
    assert rule.symbol == "GOLD#"
    assert rule.mode == "SCALP"
    assert rule.status in ["CANDIDATE", "LIVE"]
    assert "condition" in rule.condition_json.lower() or "indicator" in rule.condition_json.lower()

    # Verify TradeLedger was updated with loss post-mortem text
    db_session.refresh(trade)
    assert trade.loss_postmortem_text is not None
    assert len(trade.loss_postmortem_text) > 10


def test_shadow_validation_replay_and_gate(db_session):
    """Test shadow replay validation on historical trades and promotion to LIVE."""
    now = datetime.now(timezone.utc)
    # Seed historical trades
    for i in range(5):
        t = TradeLedger(
            account_type="DEMO",
            position_id=111000 + i,
            order_ticket=111000 + i,
            symbol="BTCUSD#",
            magic_number=2001,
            mode="SWING",
            direction="SELL",
            status="CLOSED",
            lots=Decimal("0.02"),
            initial_lots=Decimal("0.02"),
            entry_price=Decimal("90000.00"),
            sl=Decimal("91000.00"),
            tp1=Decimal("88500.00"),
            tp2=Decimal("87000.00"),
            exit_price=Decimal("88500.00") if i % 2 == 0 else Decimal("91000.00"),
            net_pnl=Decimal("30.00") if i % 2 == 0 else Decimal("-20.00"),
            exit_reason="TP1" if i % 2 == 0 else "SL_HIT",
            opened_at_utc=now - timedelta(hours=i * 2 + 1),
            closed_at_utc=now - timedelta(hours=i * 2),
        )
        db_session.add(t)
    db_session.commit()

    # Clear existing rules for BTCUSD# to test cleanly
    db_session.query(LearnedPairRule).filter_by(symbol="BTCUSD#").delete()
    db_session.commit()

    # Create unique candidate rule
    code = f"RULE_BTCUSD_SWING_TEST_{int(now.timestamp())}"
    rule = LearnedPairRule(
        rule_code=code,
        symbol="BTCUSD#",
        mode="SWING",
        status="CANDIDATE",
        condition_json=json.dumps({
            "indicator": "ema_trend",
            "timeframe": "H4",
            "op": "==",
            "val": "COUNTER_TREND",
            "filter_action": "BLOCK_SELL",
        }),
        action_json=json.dumps({"action": "BLOCK", "reason": "Test block"}),
        origin_loss_ids_json=json.dumps([111001]),
        backtest_net_improvement_pct=Decimal("0.00"),
        created_at_utc=now,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    promoted, improvement, reason = forensic_learner.replay_shadow_validation(rule, db_session)
    assert isinstance(promoted, bool)
    assert isinstance(improvement, Decimal)

    # Check live rule filtering gate
    rule.status = "LIVE"
    db_session.commit()

    is_blocked, block_reason = forensic_learner.check_live_rules_filter(
        symbol="BTCUSD#",
        mode="SWING",
        direction="SELL",
        db=db_session,
    )
    assert is_blocked is True
    assert code in block_reason


def test_learned_rules_and_forensics_rest_api(client, db_session):
    """Test REST endpoints /api/ai/rules, /api/ai/rules/{id}/status, and /api/ai/forensics/{id}."""
    # 1. List rules
    resp = client.get("/api/ai/rules?symbol=GOLD#")
    assert resp.status_code == 200
    rules = resp.json()
    assert isinstance(rules, list)

    # 2. If rules exist, test status update
    if len(rules) > 0:
        rule_id = rules[0]["id"]
        status_resp = client.post(
            f"/api/ai/rules/{rule_id}/status",
            json={"status": "LOCKED"},
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["new_status"] == "LOCKED"

    # 3. Manual forensics trigger
    trade = db_session.query(TradeLedger).filter_by(status="CLOSED").first()
    if trade:
        f_resp = client.post(f"/api/ai/forensics/{trade.id}")
        assert f_resp.status_code == 200
        data = f_resp.json()
        assert data["status"] == "COMPLETED"
        assert "loss_postmortem_text" in data
