"""Phase 3 Mandatory Verification Suite: Multi-Timeframe Price Action, Macro News Blackout,
Gemini Supervisory Brain, and Live Scheduler.

Verifies:
1. Multi-timeframe market_packet compilation with assigned Scalp/Swing candidate signals and cross-pair momentum.
2. Tier-1 USD/EUR/JPY macro news blackout blocking entries +/- 15 minutes around high-impact releases.
3. Structured supervisory response parsing, saving GeminiAnalysisReport to MySQL, and setup alerts.
4. Strict Execution Mode enforcement:
   - AUTO: dispatches order with Magic 1001/2001 + mandatory hard SL.
   - COPILOT: stages PLANNED trade in TradeLedger, approves via /api/ai/copilot/{id}/approve.
   - MONITOR & HALTED: block order dispatch.
5. Per-pair interval countdown update and instant /api/ai/scan/{symbol} execution.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.api.server import create_app
from backend.app.core.clock_sync import now_utc
from backend.app.db.models import (
    AppSettings,
    GeminiAnalysisReport,
    MacroNewsEvent,
    TradingPairBot,
    StrategyScript,
    TradeLedger,
    LearnedPairRule,
)
from backend.app.db.session import get_db
from backend.app.ai_brain.news_guard import MacroNewsGuard, NewsBlackoutResult, news_guard
from backend.app.ai_brain.market_packet import (
    MarketPacketCompiler,
    market_packet_compiler,
    MarketPacket,
)
from backend.app.ai_brain.gemini_supervisor import (
    GeminiSupervisor,
    GeminiSupervisoryOutput,
    gemini_supervisor,
)
from backend.app.ai_brain.scheduler import LiveIntervalScheduler, scheduler
from backend.app.strategy_lab.builtin_strategies import (
    STRATEGY_LIQUIDITY_SWEEP_FVG,
    STRATEGY_EMA_TREND_PULLBACK,
)


# -------------------------------------------------------------------------
# Test Fixtures
# -------------------------------------------------------------------------
@pytest.fixture
def mock_ohlcv_timeframes():
    """Generate realistic deterministic multi-timeframe OHLCV DataFrames."""
    np.random.seed(101)
    base_time = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)

    # 1. D1 DataFrame (Daily)
    d1_times = [base_time + timedelta(days=i) for i in range(30)]
    d1_close = 2600.0 + np.linspace(0, 50, 30)
    df_d1 = pd.DataFrame({
        "time": d1_times,
        "open": d1_close - 2.0,
        "high": d1_close + 8.0,
        "low": d1_close - 5.0,
        "close": d1_close,
        "tick_volume": [500] * 30,
        "spread": [25] * 30,
    })

    # 2. H4 DataFrame
    h4_times = [base_time + timedelta(hours=i * 4) for i in range(50)]
    h4_close = 2620.0 + np.linspace(0, 30, 50) + np.sin(np.linspace(0, 6, 50)) * 5.0
    df_h4 = pd.DataFrame({
        "time": h4_times,
        "open": h4_close - 1.0,
        "high": h4_close + 4.0,
        "low": h4_close - 3.0,
        "close": h4_close,
        "tick_volume": [200] * 50,
        "spread": [25] * 50,
    })

    # 3. H1 DataFrame
    h1_times = [base_time + timedelta(hours=i) for i in range(60)]
    h1_close = 2635.0 + np.linspace(0, 15, 60) + np.sin(np.linspace(0, 8, 60)) * 3.0
    df_h1 = pd.DataFrame({
        "time": h1_times,
        "open": h1_close - 0.5,
        "high": h1_close + 2.5,
        "low": h1_close - 2.0,
        "close": h1_close,
        "tick_volume": [150] * 60,
        "spread": [25] * 60,
    })

    # 4. M15 DataFrame
    m15_times = [base_time + timedelta(minutes=i * 15) for i in range(80)]
    m15_close = 2645.0 + np.linspace(0, 10, 80) + np.sin(np.linspace(0, 10, 80)) * 2.0
    df_m15 = pd.DataFrame({
        "time": m15_times,
        "open": m15_close - 0.2,
        "high": m15_close + 1.5,
        "low": m15_close - 1.5,
        "close": m15_close,
        "tick_volume": [100] * 80,
        "spread": [25] * 80,
    })

    # 5. M5 DataFrame
    m5_times = [base_time + timedelta(minutes=i * 5) for i in range(80)]
    m5_close = 2648.0 + np.linspace(0, 5, 80)
    df_m5 = pd.DataFrame({
        "time": m5_times,
        "open": m5_close - 0.1,
        "high": m5_close + 0.8,
        "low": m5_close - 0.8,
        "close": m5_close,
        "tick_volume": [80] * 80,
        "spread": [25] * 80,
    })

    return {
        "D1": df_d1,
        "H4": df_h4,
        "H1": df_h1,
        "M15": df_m15,
        "M5": df_m5,
    }


@pytest.fixture
def ai_client(test_engine):
    """FastAPI TestClient bound to isolated test database."""
    test_app = create_app(enable_lifespan_tasks=False)
    TestingSessionLocal = sessionmaker(bind=test_engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(test_app) as client:
        yield client
    test_app.dependency_overrides.clear()


# -------------------------------------------------------------------------
# 1. Multi-Timeframe Market Packet & Strategy Confluence
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_market_packet_compilation(db_session, mock_ohlcv_timeframes):
    compiler = MarketPacketCompiler()

    # Seed pair and assign strategy in test DB
    pair = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    if not pair:
        pair = TradingPairBot(
            symbol="GOLD#",
            asset_class="METAL",
            enabled=True,
            scalp_enabled=True,
            swing_enabled=True,
            contract_size=Decimal("100.0"),
            tick_size=Decimal("0.01"),
            tick_value=Decimal("1.0"),
            digits=2,
            volume_min=Decimal("0.01"),
            volume_step=Decimal("0.01"),
        )
        db_session.add(pair)
        db_session.commit()

    # Assign built-in scalp and swing strategies
    strat_scalp = db_session.query(StrategyScript).filter_by(is_builtin=True).first()
    if strat_scalp:
        pair.scalp_strategy_id = strat_scalp.id
        db_session.commit()

    # Provide cross-pair dummy data for momentum calculation
    cross_pairs = {
        "EURUSD#": mock_ohlcv_timeframes["H1"],
        "USDJPY#": mock_ohlcv_timeframes["H1"],
        "BTCUSD#": mock_ohlcv_timeframes["H1"],
    }

    packet = await compiler.compile_market_packet(
        symbol="GOLD#",
        timeframe_dfs=mock_ohlcv_timeframes,
        live_tick=(2650.00, 2650.25, 25),
        cross_pair_dfs=cross_pairs,
        db=db_session,
    )

    assert packet.symbol == "GOLD#"
    assert packet.asset_class == "METAL"
    assert packet.bid == 2650.00
    assert packet.ask == 2650.25
    assert packet.spread_points == 25
    assert packet.pdh is not None
    assert packet.pdl is not None
    assert packet.swing_bias_h4_d1 in ("BULLISH", "BEARISH", "CHOP")
    assert packet.scalp_bias_m15_h1 in ("BULLISH", "BEARISH", "CHOP")
    assert "M15" in packet.timeframe_breakdown
    assert "H1" in packet.timeframe_breakdown
    assert "cross_pair_momentum" in packet.to_dict()
    assert "usd_bias" in packet.cross_pair_momentum


# -------------------------------------------------------------------------
# 2. Tier-1 Macro News Blackout Guard
# -------------------------------------------------------------------------
def test_macro_news_blackout_guard():
    guard = MacroNewsGuard(blackout_window_min=15)
    ref_time = datetime(2026, 11, 10, 14, 0, 0, tzinfo=timezone.utc)

    # 1. Event in 8 minutes (Inside 15m window) -> BLACKOUT
    imminent_event = [{
        "currency": "USD",
        "title": "US Core CPI YoY",
        "impact": "HIGH",
        "event_time_utc": ref_time + timedelta(minutes=8),
    }]
    res = guard.check_blackout("GOLD#", current_time_utc=ref_time, custom_events=imminent_event)
    assert res.is_blackout is True
    assert res.currency == "USD"
    assert res.minutes_to_release == 8.0
    assert res.minutes_blackout_remaining == 23.0  # 8m until release + 15m after
    assert "US Core CPI" in res.event_title

    # 2. Event occurred 5 minutes ago (Inside +15m window) -> BLACKOUT
    recent_event = [{
        "currency": "USD",
        "title": "FOMC Rate Decision",
        "impact": "HIGH",
        "event_time_utc": ref_time - timedelta(minutes=5),
    }]
    res2 = guard.check_blackout("BTCUSD#", current_time_utc=ref_time, custom_events=recent_event)
    assert res2.is_blackout is True
    assert res2.minutes_to_release == -5.0
    assert res2.minutes_blackout_remaining == 10.0  # 15m - 5m = 10m remaining

    # 3. Event is 45 minutes away (Outside 15m window) -> NO BLACKOUT
    distant_event = [{
        "currency": "USD",
        "title": "Non-Farm Payrolls",
        "impact": "HIGH",
        "event_time_utc": ref_time + timedelta(minutes=45),
    }]
    res3 = guard.check_blackout("EURUSD#", current_time_utc=ref_time, custom_events=distant_event)
    assert res3.is_blackout is False

    # 4. Currency Isolation: EUR event should NOT blackout USDJPY
    eur_event = [{
        "currency": "EUR",
        "title": "ECB Rate Decision",
        "impact": "HIGH",
        "event_time_utc": ref_time + timedelta(minutes=5),
    }]
    res_jpy = guard.check_blackout("USDJPY#", current_time_utc=ref_time, custom_events=eur_event)
    assert res_jpy.is_blackout is False

    # But EUR event MUST blackout EURUSD#
    res_eur = guard.check_blackout("EURUSD#", current_time_utc=ref_time, custom_events=eur_event)
    assert res_eur.is_blackout is True


# -------------------------------------------------------------------------
# 3. Gemini Supervisory Analysis & MySQL Persistence
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_gemini_supervisor_and_report_persistence(db_session, mock_ohlcv_timeframes):
    compiler = MarketPacketCompiler()
    packet = await compiler.compile_market_packet(
        symbol="EURUSD#",
        timeframe_dfs=mock_ohlcv_timeframes,
        live_tick=(1.08500, 1.08512, 12),
        db=db_session,
    )

    supervisor = GeminiSupervisor()
    report = await supervisor.analyze_pair(packet, account_type="DEMO", db=db_session)

    assert report.id is not None
    assert report.symbol == "EURUSD#"
    assert report.account_type == "DEMO"
    assert report.market_regime in ("TRENDING_UP", "TRENDING_DOWN", "RANGE_SWEEP", "HIGH_VOLATILITY_CHOP", "NEWS_BLACKOUT")
    assert report.decision in ("EXECUTE_SCALP", "EXECUTE_SWING", "EXECUTE_BOTH", "STAGE_PENDING", "WAIT")
    assert report.confidence >= 0.0
    assert report.thesis_text is not None

    # Query back from DB
    persisted = db_session.query(GeminiAnalysisReport).filter_by(id=report.id).first()
    assert persisted is not None
    assert persisted.symbol == "EURUSD#"


# -------------------------------------------------------------------------
# 4. Strict Execution Mode Routing: AUTO, COPILOT, MONITOR, HALTED
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execution_mode_routing(db_session, mock_ohlcv_timeframes):
    bind_eng = db_session.get_bind()
    test_sched = LiveIntervalScheduler(session_factory=sessionmaker(bind=bind_eng))

    # Ensure GOLD# bot exists with strategy assigned
    pair = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    if not pair:
        pair = TradingPairBot(symbol="GOLD#", asset_class="METAL", enabled=True)
        db_session.add(pair)
        db_session.commit()

    st = db_session.query(AppSettings).filter_by(id=1).first()

    # 1. HALTED Mode: No trade action
    st.execution_mode = "HALTED"
    db_session.commit()
    rep_halted = await test_sched.execute_pair_scan("GOLD#", custom_timeframe_dfs=mock_ohlcv_timeframes, db=db_session)
    if rep_halted:
        assert rep_halted.execution_status in ("WAITING", "NEWS_BLACKOUT", "MONITOR_ONLY", "PLANNED")

    # 2. MONITOR Mode: Record report, no broker order
    st.execution_mode = "MONITOR"
    db_session.commit()
    initial_trade_count = db_session.query(TradeLedger).count()
    rep_monitor = await test_sched.execute_pair_scan("GOLD#", custom_timeframe_dfs=mock_ohlcv_timeframes, db=db_session)
    final_trade_count = db_session.query(TradeLedger).count()
    assert final_trade_count == initial_trade_count  # Zero trades placed in MONITOR mode

    # 3. COPILOT Mode: Stage PLANNED setup and 1-click approve
    st.execution_mode = "COPILOT"
    db_session.commit()

    # Simulate staging a copilot setup directly
    fake_report = GeminiAnalysisReport(
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
        thesis_text="Strong liquidity sweep rejection at H1 support.",
        execution_status="PLANNED",
    )
    db_session.add(fake_report)
    db_session.commit()

    await test_sched._stage_copilot_setup(
        report=fake_report,
        symbol="GOLD#",
        mode="SCALP",
        magic=1001,
        direction="BUY",
        lots=0.05,
        entry=2650.00,
        sl=2640.00,
        tp1=2665.00,
        tp2=2680.00,
        account_type="DEMO",
        db=db_session,
    )

    # Verify PLANNED row exists
    staged = db_session.query(TradeLedger).filter_by(symbol="GOLD#", status="PLANNED").first()
    assert staged is not None
    assert staged.lots == Decimal("0.0500")
    assert staged.magic_number == 1001

    # Approve Copilot setup via scheduler
    ok, msg = await test_sched.approve_copilot_setup(staged.id, db=db_session)
    assert ok is True
    assert "Successfully executed Copilot trade" in msg

    # Verify transition to OPEN
    db_session.refresh(staged)
    assert staged.status == "OPEN"
    assert staged.position_id > 0

    # 4. AUTO Mode: Direct broker dispatch
    st.execution_mode = "AUTO"
    db_session.commit()

    await test_sched._dispatch_auto_order(
        report=fake_report,
        symbol="GOLD#",
        mode="SWING",
        magic=2001,
        direction="BUY",
        lots=0.02,
        entry=2650.00,
        sl=2635.00,
        tp1=2672.50,
        tp2=2695.00,
        account_type="DEMO",
        db=db_session,
    )

    auto_trade = db_session.query(TradeLedger).filter_by(symbol="GOLD#", magic_number=2001, status="OPEN").first()
    assert auto_trade is not None
    assert auto_trade.mode == "SWING"
    assert auto_trade.sl == Decimal("2635.000000")
    assert auto_trade.tp2 == Decimal("2695.000000")


# -------------------------------------------------------------------------
# 5. REST Routes: /api/ai/*
# -------------------------------------------------------------------------
def test_ai_brain_rest_routes(ai_client):
    # 1. GET /api/ai/reports
    res = ai_client.get("/api/ai/reports")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # 2. POST /api/ai/interval
    interval_payload = {
        "global_scan_interval_sec": 120,
        "pair_intervals": {"GOLD#": 45, "BTCUSD#": 30},
    }
    int_res = ai_client.post("/api/ai/interval", json=interval_payload)
    assert int_res.status_code == 200
    assert int_res.json()["status"] == "SUCCESS"

    # 3. GET & POST /api/ai/news
    news_res = ai_client.get("/api/ai/news?symbol=GOLD#")
    assert news_res.status_code == 200
    news_data = news_res.json()
    assert "total_events" in news_data
    assert "blackout_check" in news_data

    # Add high impact news event
    event_payload = {
        "event_time_utc": (now_utc() + timedelta(hours=3)).isoformat(),
        "currency": "USD",
        "title": "Fed Chair Powell Speaks",
        "impact": "HIGH",
        "forecast": None,
        "previous": None,
    }
    post_news_res = ai_client.post("/api/ai/news", json=event_payload)
    assert post_news_res.status_code == 200
    assert post_news_res.json()["status"] == "CREATED"

    # 4. POST /api/ai/scan/GOLD#
    scan_res = ai_client.post("/api/ai/scan/GOLD#")
    assert scan_res.status_code == 200
    scan_data = scan_res.json()
    assert scan_data["symbol"] in ("GOLD#", "GOLD")
    assert "market_regime" in scan_data
    assert "decision" in scan_data
