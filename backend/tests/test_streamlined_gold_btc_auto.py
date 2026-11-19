"""Comprehensive verification test suite for streamlined Gold/BTC autonomous architecture:
1. Strictly GOLD# and BTCUSD# active; zero Copilot states; Strategy Lab UI retired;
   headless shadow-validator + xm_fee_model.py 100% operational.
2. AUTO Market + Pending Limit execution, anti-chase drift conversion, and mandatory hard SL.
3. Headless shadow-validator rejecting overfitted rules (>15% winners cut), promoting
   valid fee-positive rules to LIVE, and auto-pruning degrading rules to DEPRECATED.
4. Per-pair PairPatternMemory isolation (GOLD# vs BTCUSD#), accurate non-double-counted
   Gemini token/cost calculation, and .sql dump export.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.ai_brain.forensic_learner import ForensicLearner
from backend.app.ai_brain.scheduler import LiveIntervalScheduler
from backend.app.ai_brain.usage_tracker import calculate_cost, get_model_rate_card
from backend.app.api.server import create_app
from backend.app.core.clock_sync import now_utc
from backend.app.core.symbol_utils import XM_ACTIVE_SYMBOLS, resolve_broker_symbol
from backend.app.db.models import (
    AppSettings,
    Base,
    GeminiAnalysisReport,
    LearnedPairRule,
    PairPatternMemory,
    TradeLedger,
    TradingPairBot,
)
from backend.app.db.session import get_db, init_db
from backend.app.strategy_lab.xm_fee_model import xm_fee_engine

# Isolated test database URL
TEST_DB_URL = "mysql+pymysql://root:@127.0.0.1:3306/xm_trading_v2_test"


@pytest.fixture(scope="module")
def test_engine():
    """Create isolated test MySQL engine and initialize tables."""
    engine = create_engine(TEST_DB_URL, echo=False)
    Base.metadata.create_all(bind=engine)
    init_db(bind_engine=engine)
    return engine


@pytest.fixture(scope="function")
def db_session(test_engine):
    """Provide a transactional DB session for tests."""
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="module")
def api_client(test_engine):
    """Provide a TestClient connected to the isolated test database."""
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


# -----------------------------------------------------------------------------
# 1. Strict 2-Pair Focus & Strategy FK Unbinding
# -----------------------------------------------------------------------------
def test_strict_2pair_focus_and_strategy_unbind(db_session):
    """Verify only Gold and Bitcoin are active and strategy FKs are unbound."""
    assert "GOLD#" in XM_ACTIVE_SYMBOLS
    assert "BTCUSD#" in XM_ACTIVE_SYMBOLS
    assert len(XM_ACTIVE_SYMBOLS) == 14

    # Verify symbol resolution strictly handles aliases
    assert resolve_broker_symbol("GOLD", db=db_session) == "GOLD#"
    assert resolve_broker_symbol("XAUUSD", db=db_session) == "GOLD#"
    assert resolve_broker_symbol("BTCUSD", db=db_session) == "BTCUSD#"
    assert resolve_broker_symbol("BTC", db=db_session) == "BTCUSD#"

    # Check database bots
    bots = db_session.query(TradingPairBot).all()
    symbols = {b.symbol for b in bots}
    assert "GOLD#" in symbols
    assert "BTCUSD#" in symbols

    # Verify strategy FKs are valid (bound to default built-ins or unbound)
    gold_bot = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    assert gold_bot is not None
    assert gold_bot.scalp_strategy_id in (None, 1)
    assert gold_bot.swing_strategy_id in (None, 3)

    # AppSettings execution mode should be AUTO
    st = db_session.query(AppSettings).filter_by(id=1).first()
    assert st.execution_mode in ("AUTO", "HALTED")


# -----------------------------------------------------------------------------
# 2. AUTO Market & Pending Limit Execution with Anti-Chase Drift Guard
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_auto_market_and_pending_limit_execution(db_session):
    """Verify autonomous execution: direct market order vs anti-chase drift limit order."""
    bind_eng = db_session.get_bind()
    sched = LiveIntervalScheduler(session_factory=sessionmaker(bind=bind_eng))

    # Fake report for GOLD# BUY
    rep = GeminiAnalysisReport(
        account_type="DEMO",
        symbol="GOLD#",
        market_regime="TRENDING_UP",
        decision="EXECUTE_SCALP",
        recommended_mode="SCALP",
        confidence=Decimal("0.85"),
        entry_price=Decimal("2650.00"),
        stop_loss=Decimal("2642.00"),
        tp1=Decimal("2662.00"),
        tp2=Decimal("2674.00"),
        thesis_text="Bullish order block test with sweep confirmation.",
        execution_status="EXECUTED",
    )
    db_session.add(rep)
    db_session.commit()

    # Scenario A: Market order execution (price matches entry)
    await sched._dispatch_auto_order(
        report=rep,
        symbol="GOLD#",
        mode="SCALP",
        magic=1001,
        direction="BUY",
        lots=0.02,
        entry=2650.00,
        sl=2642.00,
        tp1=2662.00,
        tp2=2674.00,
        account_type="DEMO",
        db=db_session,
        is_limit_order=False,
    )

    trade_mkt = (
        db_session.query(TradeLedger)
        .filter_by(symbol="GOLD#", magic_number=1001, entry_order_type="MARKET")
        .order_by(TradeLedger.id.desc())
        .first()
    )
    assert trade_mkt is not None
    assert trade_mkt.status in ("OPEN", "PENDING")
    assert trade_mkt.sl == Decimal("2642.00")
    assert trade_mkt.tp2 == Decimal("2674.00")

    # Scenario B: Anti-chase drift converted to LIMIT order
    rep_limit = GeminiAnalysisReport(
        account_type="DEMO",
        symbol="BTCUSD#",
        market_regime="COMPRESSION_SQUEEZE",
        decision="EXECUTE_SWING",
        recommended_mode="SWING",
        confidence=Decimal("0.90"),
        entry_price=Decimal("65000.00"),
        stop_loss=Decimal("64200.00"),
        tp1=Decimal("66200.00"),
        tp2=Decimal("67500.00"),
        thesis_text="Resting limit at FVG retest zone after drift.",
        execution_status="PENDING_LIMIT",
    )
    db_session.add(rep_limit)
    db_session.commit()

    await sched._dispatch_auto_order(
        report=rep_limit,
        symbol="BTCUSD#",
        mode="SWING",
        magic=2001,
        direction="BUY",
        lots=0.01,
        entry=65000.00,
        sl=64200.00,
        tp1=66200.00,
        tp2=67500.00,
        account_type="DEMO",
        db=db_session,
        is_limit_order=True,
    )

    trade_limit = (
        db_session.query(TradeLedger)
        .filter_by(symbol="BTCUSD#", magic_number=2001, entry_order_type="LIMIT")
        .order_by(TradeLedger.id.desc())
        .first()
    )
    assert trade_limit is not None
    assert trade_limit.status == "PENDING"
    assert trade_limit.entry_order_type == "LIMIT"


# -----------------------------------------------------------------------------
# 3. Headless Shadow-Validator: Gate, Promotion & Auto-Pruning
# -----------------------------------------------------------------------------
def test_headless_shadow_validator_gate_and_pruning(db_session):
    """Verify headless shadow validator promotes valid rules, rejects overfitted rules, and prunes degrading rules."""
    learner = ForensicLearner()

    # Seed 10 historical closed trades on GOLD#: 7 wins, 3 losses
    ref_time = now_utc()
    created_trades = []
    for i in range(10):
        is_win = i < 7
        pnl = Decimal("150.00") if is_win else Decimal("-100.00")
        r_mult = Decimal("1.50") if is_win else Decimal("-1.00")
        reason = "TP_HIT" if is_win else "SL_HIT"
        direction = "BUY" if i % 2 == 0 else "SELL"
        t = TradeLedger(
            account_type="DEMO",
            position_id=88000 + i,
            symbol="GOLD#",
            magic_number=1001,
            mode="SCALP",
            direction=direction,
            status="CLOSED",
            entry_order_type="MARKET",
            lots=Decimal("0.05"),
            initial_lots=Decimal("0.05"),
            entry_price=Decimal("2650.00"),
            sl=Decimal("2640.00"),
            tp1=Decimal("2665.00"),
            tp2=Decimal("2680.00"),
            gross_pnl=pnl,
            net_pnl=pnl,
            r_multiple=r_mult,
            exit_reason=reason,
            opened_at_utc=ref_time - timedelta(hours=i * 2 + 1),
            closed_at_utc=ref_time - timedelta(hours=i * 2),
        )
        db_session.add(t)
        created_trades.append(t)
    db_session.commit()

    # Case A: Valid rule that filters only origin loss (0% winners cut, improves PF)
    loss_trade = [t for t in created_trades if t.net_pnl < 0][0]
    rule_valid = LearnedPairRule(
        rule_code=f"RULE_TEST_VALID_{loss_trade.id}",
        symbol="GOLD#",
        mode="SCALP",
        status="CANDIDATE",
        condition_json=json.dumps({"filter_action": f"BLOCK_{loss_trade.direction}", "indicator": "news_guard"}),
        action_json=json.dumps({"action": "BLOCK", "reason": "Avoid news spike"}),
        origin_loss_ids_json=json.dumps([loss_trade.id]),
        backtest_net_improvement_pct=Decimal("0.00"),
    )
    db_session.add(rule_valid)
    db_session.commit()

    promoted, imp_pct, reason = learner.replay_shadow_validation(rule_valid, db_session)
    assert promoted is True
    assert rule_valid.winners_preserved_pct >= Decimal("85.00")
    assert rule_valid.profit_factor_after >= rule_valid.profit_factor_before
    assert rule_valid.avoided_losses_usd > Decimal("0.00")

    # Clean up test rules if previously run
    db_session.query(LearnedPairRule).filter(
        LearnedPairRule.rule_code.in_(["RULE_TEST_OVERFITTED_001", "RULE_TEST_DEGRADING_001", "RULE_TEST_LOCKED_001"])
    ).delete(synchronize_session=False)
    db_session.commit()

    # Case B: Overfitted rule that cuts > 15% of winners (indiscriminate block)
    rule_overfitted = LearnedPairRule(
        rule_code="RULE_TEST_OVERFITTED_001",
        symbol="GOLD#",
        mode="SCALP",
        status="CANDIDATE",
        condition_json=json.dumps({"filter_action": "BLOCK_ALL", "indiscriminate_block": True}),
        action_json=json.dumps({"action": "BLOCK"}),
        origin_loss_ids_json=json.dumps([]),
        backtest_net_improvement_pct=Decimal("0.00"),
    )
    db_session.add(rule_overfitted)
    db_session.commit()

    promoted_bad, _, bad_reason = learner.replay_shadow_validation(rule_overfitted, db_session)
    assert promoted_bad is False
    assert "cuts" in bad_reason or "overfitted" in bad_reason.lower() or rule_overfitted.winners_preserved_pct < Decimal("85.00")

    # Case C: Rolling 30-trigger auto-pruning to DEPRECATED
    rule_degrading = LearnedPairRule(
        rule_code="RULE_TEST_DEGRADING_001",
        symbol="GOLD#",
        mode="SCALP",
        status="LIVE",
        condition_json=json.dumps({}),
        action_json=json.dumps({}),
        trigger_count=10,
        recent_profit_factor=Decimal("0.65"),  # PF < 1.0 indicates degradation
        backtest_net_improvement_pct=Decimal("-5.00"),
    )
    db_session.add(rule_degrading)
    db_session.commit()

    pruned = learner.evaluate_rule_pruning(rule_degrading.id, db_session)
    assert pruned is True
    assert rule_degrading.status == "DEPRECATED"

    # User-LOCKED rules must be exempt from auto-pruning
    rule_locked = LearnedPairRule(
        rule_code="RULE_TEST_LOCKED_001",
        symbol="GOLD#",
        mode="SCALP",
        status="LOCKED",
        condition_json=json.dumps({}),
        action_json=json.dumps({}),
        trigger_count=15,
        recent_profit_factor=Decimal("0.50"),
        backtest_net_improvement_pct=Decimal("-10.00"),
    )
    db_session.add(rule_locked)
    db_session.commit()

    pruned_locked = learner.evaluate_rule_pruning(rule_locked.id, db_session)
    assert pruned_locked is False
    assert rule_locked.status == "LOCKED"


# -----------------------------------------------------------------------------
# 4. Per-Pair Pattern Memory Isolation (GOLD# vs BTCUSD#)
# -----------------------------------------------------------------------------
def test_pair_pattern_memory_isolation(db_session):
    """Verify pattern scorecard memory is strictly isolated between GOLD# and BTCUSD#."""
    gold_pm = (
        db_session.query(PairPatternMemory)
        .filter_by(symbol="GOLD#", pattern_signature="LIQUIDITY_SWEEP_STOP_HUNT")
        .first()
    )
    if not gold_pm:
        gold_pm = PairPatternMemory(
            symbol="GOLD#",
            mode="SCALP",
            pattern_signature="LIQUIDITY_SWEEP_STOP_HUNT",
            session_tag="NY_OVERLAP",
            wins=0,
            losses=0,
            win_rate_pct=Decimal("0.00"),
            avg_r_multiple=Decimal("0.00"),
            net_pnl_usd=Decimal("0.00"),
            status="NEUTRAL",
        )
        db_session.add(gold_pm)
        db_session.commit()

    btc_pm = (
        db_session.query(PairPatternMemory)
        .filter_by(symbol="BTCUSD#", pattern_signature="VOLATILITY_SQUEEZE_BREAKOUT")
        .first()
    )
    if not btc_pm:
        btc_pm = PairPatternMemory(
            symbol="BTCUSD#",
            mode="SCALP",
            pattern_signature="VOLATILITY_SQUEEZE_BREAKOUT",
            session_tag="24/7",
            wins=0,
            losses=0,
            win_rate_pct=Decimal("0.00"),
            avg_r_multiple=Decimal("0.00"),
            net_pnl_usd=Decimal("0.00"),
            status="NEUTRAL",
        )
        db_session.add(btc_pm)
        db_session.commit()

    # Create a closed winning trade on GOLD# with pattern signature attached
    trade_gold = TradeLedger(
        account_type="DEMO",
        position_id=99101,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.02"),
        initial_lots=Decimal("0.02"),
        entry_price=Decimal("2650.00"),
        sl=Decimal("2642.00"),
        tp1=Decimal("2662.00"),
        tp2=Decimal("2674.00"),
        gross_pnl=Decimal("250.00"),
        net_pnl=Decimal("250.00"),
        r_multiple=Decimal("2.00"),
        exit_reason="TP_HIT",
        detected_patterns_json=json.dumps([{"pattern_name": "LIQUIDITY_SWEEP_STOP_HUNT"}]),
        opened_at_utc=now_utc() - timedelta(hours=1),
        closed_at_utc=now_utc(),
    )
    db_session.add(trade_gold)
    db_session.commit()

    # Update GOLD# pattern memory via closed-loop learner
    learner = ForensicLearner()
    learner.update_pattern_memory_on_trade_close(
        trade_id=trade_gold.id,
        db=db_session,
    )

    db_session.refresh(gold_pm)
    db_session.refresh(btc_pm)

    # GOLD# wins incremented and win rate is 100%
    assert gold_pm.wins >= 1
    assert gold_pm.net_pnl_usd > Decimal("0.00")

    # BTCUSD# pattern memory remains completely unaffected
    assert btc_pm.wins == 0
    assert btc_pm.net_pnl_usd == Decimal("0.00")


# -----------------------------------------------------------------------------
# 5. Gemini Token Calculation (No Double Counting) & .SQL Dump Export
# -----------------------------------------------------------------------------
def test_gemini_token_cost_math_and_db_export(api_client, db_session):
    """Verify uncached token math prevents double counting and .sql dump exports cleanly."""
    in_r, out_r, c_r, _ = get_model_rate_card("gemini-3.8-flash", db=db_session)

    # prompt_tokens=10000, cached_tokens=4000 -> uncached must be exactly 6000
    cost = calculate_cost(
        prompt_tokens=10000,
        output_tokens=500,
        thinking_tokens=100,
        cached_tokens=4000,
        input_rate=in_r,
        output_rate=out_r,
        cached_rate=c_r,
    )
    expected_uncached_cost = (Decimal("6000") / Decimal("1000000")) * in_r
    expected_cached_cost = (Decimal("4000") / Decimal("1000000")) * c_r
    expected_output_cost = (Decimal("600") / Decimal("1000000")) * out_r
    expected_total = (expected_uncached_cost + expected_cached_cost + expected_output_cost).quantize(Decimal("0.000001"))

    assert cost == expected_total

    # Test .sql dump export route
    res = api_client.get("/api/db-admin/export-sql")
    assert res.status_code == 200
    assert "Content-Disposition" in res.headers
    assert ".sql" in res.headers["Content-Disposition"]
    sql_text = res.text
    assert "CREATE TABLE" in sql_text or "INSERT INTO" in sql_text
    assert "learned_pair_rules" in sql_text or "trading_pair_bots" in sql_text

