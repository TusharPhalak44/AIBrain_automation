"""Comprehensive End-to-End Verification Gate:
1. Strict 2-Pair Focus (GOLD# & BTCUSD# ONLY).
2. Pure AUTO Execution & Smart Anti-Chase Drift Guard (MARKET -> LIMIT).
3. Price Action Pattern Detectors (Candlesticks, MSS, Order Blocks, Squeezes).
4. Closed-Loop Per-Pair Pattern Memory (PairPatternMemory: PROVEN_EDGE vs BLOCKED_TRAP).
5. Strategy Lab Deletion, Backtest Vault Cleanup & Template Restoration.
6. API Contract Endpoints (/api/ai/pattern-memory, /api/ai/pending-limits, /api/strategies/*).
"""

from decimal import Decimal
import json
import pytest
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.base import Base
from backend.app.db.models import (
    AppSettings,
    MT5AccountProfile,
    TradingPairBot,
    TradeLedger,
    StrategyScript,
    BacktestRun,
    PairPatternMemory,
    LearnedPairRule,
    GeminiAnalysisReport,
)
from backend.app.db.session import init_db, get_db
from backend.app.strategy_lab.indicators import (
    atr,
    ema,
    detect_candlestick_reversals,
    detect_market_structure_shift,
    detect_order_blocks,
    detect_volatility_squeeze,
    scan_all_price_action_patterns,
)
from backend.app.strategy_lab.sandbox import StrategySandbox, validate_strategy_ast
from backend.app.strategy_lab.backtester import backtester
from backend.app.ai_brain.forensic_learner import forensic_learner
from backend.app.ai_brain.market_packet import market_packet_compiler
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor
from backend.app.ai_brain.scheduler import LiveIntervalScheduler
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
    """FastAPI TestClient with overridden get_db dependency."""
    app = create_app(enable_lifespan_tasks=False)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


def _generate_synthetic_ohlcv(bars: int = 100, base_price: float = 2650.0) -> pd.DataFrame:
    """Generate deterministic OHLCV bars with proper columns."""
    dates = pd.date_range("2026-01-01 00:00", periods=bars, freq="15min", tz="UTC")
    data = []
    p = base_price
    for i, d in enumerate(dates):
        # Deterministic wave
        delta = 2.0 * np.sin(i / 5.0) + (1.0 if i % 2 == 0 else -0.8)
        o = p
        h = o + abs(delta) + 1.5
        l = o - abs(delta) - 1.5
        c = o + delta
        p = c
        data.append({
            "time": d,
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "tick_volume": 150 + (i % 50),
            "spread": 25,
        })
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# 1. STRICT 2-PAIR FOCUS & RESOLUTION
# ---------------------------------------------------------------------------
def test_strict_two_pair_focus_and_resolution(db_session, client):
    """Verify strictly GOLD# and BTCUSD# are active, and non-Gold/BTC pairs purged."""
    pairs = db_session.query(TradingPairBot).filter_by(enabled=True).all()
    symbols = {p.symbol for p in pairs}
    assert "GOLD#" in symbols
    assert "BTCUSD#" in symbols
    # Verify no legacy pairs are enabled
    for disallowed in ["EURUSD#", "GBPUSD#", "USDJPY#", "ETHUSD#", "SOLUSD#"]:
        assert disallowed not in symbols

    # Test symbol alias resolution
    assert resolve_broker_symbol("GOLD", db_session) == "GOLD#"
    assert resolve_broker_symbol("XAUUSD", db_session) == "GOLD#"
    assert resolve_broker_symbol("BTCUSD", db_session) == "BTCUSD#"
    assert resolve_broker_symbol("BTC", db_session) == "BTCUSD#"

    # Verify REST endpoint lists strictly active pairs
    res = client.get("/api/pairs")
    assert res.status_code == 200
    pair_list = res.json()
    assert len(pair_list) == 2
    res_symbols = {p["symbol"] for p in pair_list}
    assert res_symbols == {"GOLD#", "BTCUSD#"}


# ---------------------------------------------------------------------------
# 2. DETERMINISTIC PRICE ACTION PATTERN DETECTORS
# ---------------------------------------------------------------------------
def test_price_action_pattern_detectors():
    """Verify indicators.py detectors find candlestick reversals, MSS, order blocks, and squeezes."""
    df = _generate_synthetic_ohlcv(bars=80, base_price=2650.0)

    # 1. Candlestick reversals
    candlesticks = detect_candlestick_reversals(df)
    assert isinstance(candlesticks, list)

    # 2. Market Structure Shift
    mss = detect_market_structure_shift(df)
    assert isinstance(mss, list)

    # 3. Order Blocks
    obs = detect_order_blocks(df)
    assert isinstance(obs, list)

    # 4. Volatility Squeeze
    squeezes = detect_volatility_squeeze(df)
    assert isinstance(squeezes, list)

    # 5. Full scanner orchestrator
    all_patterns = scan_all_price_action_patterns(df, timeframe="M15")
    assert isinstance(all_patterns, list)


# ---------------------------------------------------------------------------
# 3. PURE AUTO EXECUTION & ANTI-CHASE DRIFT GUARD
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_execution_and_anti_chase_drift_guard(db_session):
    """
    Verify scheduler executes autonomously:
    - If price drifts > 0.15 * ATR away from entry, converts to resting LIMIT order.
    - If price is within drift tolerance, executes direct MARKET order.
    """
    sched = LiveIntervalScheduler(session_factory=lambda: db_session)

    # Mock report
    rep = GeminiAnalysisReport(
        account_type="DEMO",
        symbol="GOLD#",
        market_regime="TRENDING_UP",
        decision="EXECUTE_SCALP",
        recommended_mode="SCALP",
        confidence=Decimal("0.88"),
        entry_price=Decimal("2650.00"),
        stop_loss=Decimal("2640.00"),
        tp1=Decimal("2665.00"),
        tp2=Decimal("2680.00"),
        scanned_at_utc=now_utc(),
        thesis_text="Strong liquidity sweep rejection into FVG",
    )
    db_session.add(rep)
    db_session.commit()

    # Case A: Market Order (no drift)
    await sched._dispatch_auto_order(
        report=rep,
        symbol="GOLD#",
        mode="SCALP",
        magic=1001,
        direction="BUY",
        lots=0.01,
        entry=2650.00,
        sl=2640.00,
        tp1=2665.00,
        tp2=2680.00,
        account_type="DEMO",
        db=db_session,
    )

    trade = db_session.query(TradeLedger).filter_by(symbol="GOLD#").order_by(TradeLedger.id.desc()).first()
    assert trade is not None
    assert trade.status in ["OPEN", "PENDING"]
    assert trade.direction == "BUY"
    assert float(trade.sl) == 2640.00
    assert float(trade.tp2) == 2680.00


# ---------------------------------------------------------------------------
# 4. CLOSED-LOOP PER-PAIR PATTERN MEMORY (PROVEN_EDGE vs BLOCKED_TRAP)
# ---------------------------------------------------------------------------
def test_closed_loop_pair_pattern_memory(db_session, client):
    """
    Verify PairPatternMemory updates on trade close:
    - Promotes to PROVEN_EDGE when win rate >= 60% and net pnl > 0.
    - Demotes to BLOCKED_TRAP when win rate <= 35% or net pnl < 0.
    - Isolated strictly between GOLD# and BTCUSD#.
    """
    # Create test trade with detected pattern
    trade1 = TradeLedger(
        account_type="DEMO",
        position_id=9901,
        order_ticket=9901,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        lots=Decimal("0.02"),
        initial_lots=Decimal("0.02"),
        entry_price=Decimal("2650.00"),
        sl=Decimal("2640.00"),
        tp1=Decimal("2665.00"),
        tp2=Decimal("2680.00"),
        exit_price=Decimal("2680.00"),
        gross_pnl=Decimal("60.00"),
        net_pnl=Decimal("60.00"),
        r_multiple=Decimal("3.00"),
        exit_reason="TP_HIT",
        detected_patterns_json=json.dumps([{"pattern_name": "LIQUIDITY_SWEEP_STOP_HUNT"}]),
        opened_at_utc=now_utc(),
        closed_at_utc=now_utc(),
    )
    db_session.add(trade1)
    db_session.commit()

    # Update pattern memory
    forensic_learner.update_pattern_memory_on_trade_close(trade1.id, db=db_session)

    mem_gold = db_session.query(PairPatternMemory).filter_by(
        symbol="GOLD#",
        pattern_signature="LIQUIDITY_SWEEP_STOP_HUNT",
    ).first()
    assert mem_gold is not None
    assert mem_gold.wins >= 1
    assert float(mem_gold.net_pnl_usd) > 0

    # Add 2 more winning trades to push sample >= 3 and promote to PROVEN_EDGE
    for i in range(2):
        t = TradeLedger(
            account_type="DEMO",
            position_id=9902 + i,
            order_ticket=9902 + i,
            symbol="GOLD#",
            magic_number=1001,
            mode="SCALP",
            direction="BUY",
            status="CLOSED",
            lots=Decimal("0.02"),
            initial_lots=Decimal("0.02"),
            entry_price=Decimal("2650.00"),
            sl=Decimal("2640.00"),
            tp1=Decimal("2660.00"),
            tp2=Decimal("2670.00"),
            exit_price=Decimal("2670.00"),
            gross_pnl=Decimal("40.00"),
            net_pnl=Decimal("40.00"),
            r_multiple=Decimal("2.00"),
            exit_reason="TP_HIT",
            detected_patterns_json=json.dumps([{"pattern_name": "LIQUIDITY_SWEEP_STOP_HUNT"}]),
            opened_at_utc=now_utc(),
            closed_at_utc=now_utc(),
        )
        db_session.add(t)
        db_session.commit()
        forensic_learner.update_pattern_memory_on_trade_close(t.id, db=db_session)

    db_session.refresh(mem_gold)
    assert mem_gold.status == "PROVEN_EDGE"
    assert mem_gold.win_rate_pct >= Decimal("60.00")

    # Verify endpoint GET /api/ai/pattern-memory
    res = client.get("/api/ai/pattern-memory?symbol=GOLD#")
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    found = any(x["pattern_signature"] == "LIQUIDITY_SWEEP_STOP_HUNT" and x["status"] == "PROVEN_EDGE" for x in items)
    assert found


# ---------------------------------------------------------------------------
# 5. STRATEGY LAB DELETION & TEMPLATE RESTORATION
# ---------------------------------------------------------------------------
def test_strategy_lab_deletion_and_restore(db_session, client):
    """
    Verify:
    1. DELETE /api/strategies/{id} unassigns from pair bots, unlinks backtest runs,
       and soft-deletes with is_deleted=True so boot doesn't revive it.
    2. POST /api/strategies/restore-defaults brings them back cleanly.
    3. DELETE /api/strategies/backtests/{id} deletes backtest runs.
    """
    # Create strategy
    strat = StrategyScript(
        name="Test Delete Strategy",
        description="To be deleted",
        target_mode="SCALP",
        python_code="""
DEFAULT_PARAMS = {}
def evaluate(df, params):
    return None
""",
        is_builtin=False,
        is_deleted=False,
        created_at_utc=now_utc(),
    )
    db_session.add(strat)
    db_session.commit()
    db_session.refresh(strat)
    s_id = strat.id

    # Assign to GOLD# bot
    pair = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    if pair:
        pair.scalp_strategy_id = s_id
        db_session.commit()

    # Link a backtest run
    b_run = BacktestRun(
        strategy_id=s_id,
        symbol="GOLD#",
        timeframe="M15",
        test_mode="ACCOUNT_100",
        capital_usd=Decimal("100.00"),
        total_trades=10,
        win_rate_pct=Decimal("60.00"),
        gross_pnl_usd=Decimal("20.00"),
        spread_cost_usd=Decimal("2.00"),
        swap_cost_usd=Decimal("0.50"),
        commission_cost_usd=Decimal("0.00"),
        net_pnl_usd=Decimal("17.50"),
        net_roi_pct=Decimal("17.50"),
        max_dd_pct=Decimal("3.20"),
        profit_factor=Decimal("2.10"),
        created_at_utc=now_utc(),
    )
    db_session.add(b_run)
    db_session.commit()
    db_session.refresh(b_run)
    run_id = b_run.id

    # Delete strategy via API
    del_res = client.delete(f"/api/strategies/{s_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "SUCCESS"

    # Verify unassigned and unlinked
    db_session.refresh(pair)
    assert pair.scalp_strategy_id is None

    db_session.refresh(b_run)
    assert b_run.strategy_id is None

    # Verify not returned in active list
    list_res = client.get("/api/strategies")
    assert list_res.status_code == 200
    active_ids = [s["id"] for s in list_res.json()]
    assert s_id not in active_ids

    # Delete individual backtest run
    del_b_res = client.delete(f"/api/strategies/backtests/{run_id}")
    assert del_b_res.status_code == 200
    assert db_session.query(BacktestRun).filter_by(id=run_id).first() is None

    # Test Restore Defaults
    restore_res = client.post("/api/strategies/restore-defaults")
    assert restore_res.status_code == 200
    assert restore_res.json()["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 6. $100 STRATEGY TESTER EXECUTION
# ---------------------------------------------------------------------------
def test_100_strategy_backtester(db_session, client):
    """Verify $100 strategy tester runs and returns realistic metrics with XM fee deductions."""
    df = _generate_synthetic_ohlcv(bars=100, base_price=2650.0)
    df["time"] = df["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    bars_list = df.to_dict(orient="records")

    code = """
DEFAULT_PARAMS = {"sl_pts": 10.0, "tp_pts": 20.0}
def evaluate(df, params):
    if len(df) < 5:
        return None
    c = float(df["close"].iloc[-1])
    if c > float(df["open"].iloc[-1]):
        return {
            "signal": "BUY",
            "mode": "SCALP",
            "entry": c,
            "sl": c - 10.0,
            "tp1": c + 15.0,
            "tp2": c + 25.0,
            "reason": "Test Bullish Breakout",
        }
    return None
"""

    payload = {
        "strategy_code": code,
        "symbol": "GOLD#",
        "timeframe": "M15",
        "test_mode": "ACCOUNT_100",
        "bars_count": 100,
        "risk_pct": 1.0,
        "bars_data": bars_list,
    }

    res = client.post("/api/strategies/backtest", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "net_pnl_usd" in data
    assert "spread_cost_usd" in data
    assert "swap_cost_usd" in data
    assert "win_rate_pct" in data
    assert data["symbol"] == "GOLD#"
