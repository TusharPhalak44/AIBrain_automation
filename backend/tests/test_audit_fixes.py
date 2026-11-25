"""Comprehensive Verification Gate for Audit Bug Fixes.

Validates:
1. Strict 1-Position-Per-Symbol Lock & Self-Hedging Block (SCALP vs SWING, zero stacking).
2. Correlation Group Caps (Crude Energy max 1, Metals max 1 same dir, Crypto max 2, FX currency exposure max 2).
3. Daily Drawdown Circuit Breaker (-3.00% equity limit & 4 consecutive SL_HIT).
4. Post-Exit Cooldown (30m SCALP, 240m SWING after SL_HIT or manual stop).
5. Hard Pre-Order Math Validation (Direction sanity, min SL distance 1.2*ATR, Net R:R floor 1.8/2.5).
6. Universal MT5 tick_value lot sizing & $50 dollar risk cap (solving SOLUSD# 0/12 inverted R:R).
7. Deal reconciler ENUM_DEAL_REASON mapping & broker timezone offset normalization (Bug C +2h fix).
8. Forensic learner SL guard (only true >=80% SL hits trigger postmortems; cleanup deprecated rules).
9. REST routes (/api/ai-brain/reconcile-mt5, /api/ai-brain/risk-guardrails, /api/pairs/{symbol}/assign-strategy).
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient

from backend.app.core.clock_sync import now_utc, broker_epoch_to_utc, to_ist_str
from backend.app.core.risk_engine import risk_engine
from backend.app.db.models import (
    TradeLedger,
    TradingPairBot,
    AppSettings,
    MT5AccountProfile,
    LearnedPairRule,
    StrategyScript,
)
from backend.app.ai_brain.scheduler import scheduler, decompose_fx_symbol
from backend.app.ai_brain.forensic_learner import forensic_learner
from backend.app.mt5_bridge.deal_reconciler import classify_exit_reason, reconcile_open_trades_with_mt5
from backend.app.api.server import create_app


def test_symbol_open_position_lock(db_session):
    """Test 1: 1-Position Lock prevents duplicate orders on same instrument in any mode or direction."""
    # Clean active trades for OILCash
    db_session.query(TradeLedger).filter(
        TradeLedger.symbol.like("%OILCash%")
    ).delete(synchronize_session=False)
    db_session.commit()

    # Verify no open position initially
    ok, msg = scheduler._check_symbol_open_position_lock("OILCash#", db_session)
    assert ok is True
    assert msg == "OK"

    # Insert an open trade
    trade = TradeLedger(
        account_type="DEMO",
        position_id=990001,
        order_ticket=990001,
        symbol="OILCash#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.10"),
        initial_lots=Decimal("0.10"),
        entry_price=Decimal("72.50"),
        sl=Decimal("71.50"),
        tp1=Decimal("74.50"),
        tp2=Decimal("75.50"),
        opened_at_utc=now_utc(),
    )
    db_session.add(trade)
    db_session.commit()

    # Lock must reject subsequent calls on OILCash# or OILCash (without #)
    ok_hash, msg_hash = scheduler._check_symbol_open_position_lock("OILCash#", db_session)
    assert ok_hash is False
    assert "SKIP_POSITION_ALREADY_OPEN" in msg_hash

    ok_nohash, msg_nohash = scheduler._check_symbol_open_position_lock("OILCash", db_session)
    assert ok_nohash is False
    assert "SKIP_POSITION_ALREADY_OPEN" in msg_nohash

    # Different symbol without open positions must be allowed
    ok_gold, msg_gold = scheduler._check_symbol_open_position_lock("GOLD#", db_session)
    assert ok_gold is True


def test_self_hedging_and_multi_mode_block(db_session):
    """Test 2: Never allow SCALP and SWING to open opposite directions on the same symbol."""
    # Open SWING SELL on ETHUSD#
    db_session.query(TradeLedger).filter(TradeLedger.symbol.like("%ETHUSD%")).delete(synchronize_session=False)
    db_session.commit()

    trade = TradeLedger(
        account_type="DEMO",
        position_id=990002,
        order_ticket=990002,
        symbol="ETHUSD#",
        magic_number=2001,
        mode="SWING",
        direction="SELL",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.05"),
        initial_lots=Decimal("0.05"),
        entry_price=Decimal("3100.00"),
        sl=Decimal("3200.00"),
        tp1=Decimal("2900.00"),
        tp2=Decimal("2800.00"),
        opened_at_utc=now_utc(),
    )
    db_session.add(trade)
    db_session.commit()

    # Attempting to scan or enter SCALP BUY must be rejected by symbol lock
    ok, msg = scheduler._check_symbol_open_position_lock("ETHUSD#", db_session)
    assert ok is False
    assert "SKIP_POSITION_ALREADY_OPEN" in msg


def test_correlation_group_caps(db_session):
    """Test 3: Enforce correlation group caps for Crude, Metals, Crypto, and FX."""
    # Wipe open trades
    db_session.query(TradeLedger).filter(
        TradeLedger.status.in_(["OPEN", "PARTIAL_TP1", "PENDING"])
    ).delete(synchronize_session=False)
    db_session.commit()

    # 1. Crude Energy: Max 1 position across OILCash# and BRENTCash#
    t_oil = TradeLedger(
        account_type="DEMO",
        position_id=990010,
        order_ticket=990010,
        symbol="OILCash#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.05"),
        initial_lots=Decimal("0.05"),
        entry_price=Decimal("70.00"),
        sl=Decimal("69.00"),
        tp1=Decimal("72.00"),
        tp2=Decimal("73.00"),
        opened_at_utc=now_utc(),
    )
    db_session.add(t_oil)
    db_session.commit()

    ok_brent, msg_brent = scheduler._check_portfolio_and_correlation_caps("BRENTCash#", "BUY", 0.50, db_session)
    assert ok_brent is False
    assert "CORRELATION_LIMIT_ENERGY" in msg_brent

    # 2. Precious Metals: Max 1 position in same direction across GOLD# and SILVER#
    t_gold = TradeLedger(
        account_type="DEMO",
        position_id=990011,
        order_ticket=990011,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("2600.00"),
        sl=Decimal("2585.00"),
        tp1=Decimal("2630.00"),
        tp2=Decimal("2645.00"),
        opened_at_utc=now_utc(),
    )
    db_session.add(t_gold)
    db_session.commit()

    # Same direction BUY SILVER# must be blocked
    ok_silv_buy, msg_silv_buy = scheduler._check_portfolio_and_correlation_caps("SILVER#", "BUY", 0.50, db_session)
    assert ok_silv_buy is False
    assert "CORRELATION_LIMIT_METALS" in msg_silv_buy

    # Opposite direction SELL SILVER# is allowed
    ok_silv_sell, _ = scheduler._check_portfolio_and_correlation_caps("SILVER#", "SELL", 0.50, db_session)
    assert ok_silv_sell is True

    # 3. Crypto: Max 2 concurrent open positions across BTCUSD#, ETHUSD#, SOLUSD#, XRPUSD#
    t_btc = TradeLedger(
        account_type="DEMO",
        position_id=990012,
        order_ticket=990012,
        symbol="BTCUSD#",
        magic_number=2001,
        mode="SWING",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("90000.00"),
        sl=Decimal("88000.00"),
        tp1=Decimal("94000.00"),
        tp2=Decimal("96000.00"),
        opened_at_utc=now_utc(),
    )
    t_eth = TradeLedger(
        account_type="DEMO",
        position_id=990013,
        order_ticket=990013,
        symbol="ETHUSD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.05"),
        initial_lots=Decimal("0.05"),
        entry_price=Decimal("3100.00"),
        sl=Decimal("3050.00"),
        tp1=Decimal("3200.00"),
        tp2=Decimal("3250.00"),
        opened_at_utc=now_utc(),
    )
    db_session.add_all([t_btc, t_eth])
    db_session.commit()

    # 3rd crypto (SOLUSD#) must be blocked
    ok_sol, msg_sol = scheduler._check_portfolio_and_correlation_caps("SOLUSD#", "BUY", 0.50, db_session)
    assert ok_sol is False
    assert "CORRELATION_LIMIT_CRYPTO" in msg_sol

    # 4. FX Currency Exposure: Max 2 directionally identical exposures
    # Decompose helper check
    res = decompose_fx_symbol("EURUSD#", "BUY")
    assert res == ("EUR", "USD", "EUR", "USD")  # Long EUR, Short USD
    res_sell = decompose_fx_symbol("EURUSD#", "SELL")
    assert res_sell == ("EUR", "USD", "USD", "EUR")  # Long USD, Short EUR

    # Clean DB and setup 2 Short-USD trades: BUY EURUSD# and BUY GBPUSD#
    db_session.query(TradeLedger).filter(
        TradeLedger.status.in_(["OPEN", "PARTIAL_TP1", "PENDING"])
    ).delete(synchronize_session=False)
    db_session.commit()

    t_eur = TradeLedger(
        account_type="DEMO",
        position_id=990020,
        order_ticket=990020,
        symbol="EURUSD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.10"),
        initial_lots=Decimal("0.10"),
        entry_price=Decimal("1.0500"),
        sl=Decimal("1.0450"),
        tp1=Decimal("1.0600"),
        tp2=Decimal("1.0650"),
        opened_at_utc=now_utc(),
    )
    t_gbp = TradeLedger(
        account_type="DEMO",
        position_id=990021,
        order_ticket=990021,
        symbol="GBPUSD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        entry_order_type="MARKET",
        lots=Decimal("0.10"),
        initial_lots=Decimal("0.10"),
        entry_price=Decimal("1.2500"),
        sl=Decimal("1.2450"),
        tp1=Decimal("1.2600"),
        tp2=Decimal("1.2650"),
        opened_at_utc=now_utc(),
    )
    db_session.add_all([t_eur, t_gbp])
    db_session.commit()

    # Attempting 3rd Short USD trade via BUY AUDUSD# must be blocked
    ok_aud_buy, msg_aud_buy = scheduler._check_portfolio_and_correlation_caps("AUDUSD#", "BUY", 0.50, db_session)
    assert ok_aud_buy is False
    assert "FX_CORRELATION_LIMIT" in msg_aud_buy
    assert "USD" in msg_aud_buy

    # But SELL AUDUSD# (Long USD) is allowed
    ok_aud_sell, _ = scheduler._check_portfolio_and_correlation_caps("AUDUSD#", "SELL", 0.50, db_session)
    assert ok_aud_sell is True


def test_daily_drawdown_circuit_breaker(db_session):
    """Test 4: Circuit breaker trips on -3.0% daily drawdown or 4 consecutive SL_HIT."""
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None
    scheduler.circuit_breaker_reason = None

    now = now_utc()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Clean today's closed trades
    db_session.query(TradeLedger).filter(
        TradeLedger.status == "CLOSED",
        TradeLedger.closed_at_utc >= today_start,
    ).delete(synchronize_session=False)
    db_session.commit()

    # Ensure profile equity exists
    prof = db_session.query(MT5AccountProfile).filter_by(account_type="DEMO").first()
    if not prof:
        prof = MT5AccountProfile(account_type="DEMO", last_equity=Decimal("10000.00"))
        db_session.add(prof)
    else:
        prof.last_equity = Decimal("10000.00")
    db_session.commit()

    # 1. Healthy state
    ok, msg = scheduler._check_daily_drawdown_circuit_breaker(db_session)
    assert ok is True
    assert msg == "OK"

    # 2. Add loss exceeding -3.00% (-$350 on $10,000 equity)
    loss_trade = TradeLedger(
        account_type="DEMO",
        position_id=990030,
        order_ticket=990030,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.50"),
        initial_lots=Decimal("0.50"),
        entry_price=Decimal("2650.00"),
        exit_price=Decimal("2640.00"),
        sl=Decimal("2640.00"),
        tp1=Decimal("2670.00"),
        tp2=Decimal("2680.00"),
        gross_pnl=Decimal("-350.00"),
        net_pnl=Decimal("-350.00"),
        exit_reason="SL_HIT",
        opened_at_utc=today_start + timedelta(hours=1),
        closed_at_utc=today_start + timedelta(hours=2),
    )
    db_session.add(loss_trade)
    db_session.commit()

    ok_trip, msg_trip = scheduler._check_daily_drawdown_circuit_breaker(db_session)
    assert ok_trip is False
    assert "CIRCUIT_BREAKER_TRIPPED" in msg_trip
    assert scheduler.circuit_breaker_tripped is True

    # Reset breaker for consecutive SL test
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None
    db_session.query(TradeLedger).filter(
        TradeLedger.status == "CLOSED",
        TradeLedger.closed_at_utc >= today_start,
    ).delete(synchronize_session=False)
    db_session.commit()

    # Add 4 consecutive small SL_HIT trades today (-$5 each)
    for i in range(4):
        sl_t = TradeLedger(
            account_type="DEMO",
            position_id=990040 + i,
            order_ticket=990040 + i,
            symbol="EURUSD#",
            magic_number=1001,
            mode="SCALP",
            direction="BUY",
            status="CLOSED",
            entry_order_type="MARKET",
            lots=Decimal("0.01"),
            initial_lots=Decimal("0.01"),
            entry_price=Decimal("1.0800"),
            exit_price=Decimal("1.0790"),
            sl=Decimal("1.0790"),
            tp1=Decimal("1.0820"),
            tp2=Decimal("1.0830"),
            gross_pnl=Decimal("-5.00"),
            net_pnl=Decimal("-5.00"),
            exit_reason="SL_HIT",
            opened_at_utc=today_start + timedelta(hours=i + 1),
            closed_at_utc=today_start + timedelta(hours=i + 1, minutes=10),
        )
        db_session.add(sl_t)
    db_session.commit()

    ok_streak, msg_streak = scheduler._check_daily_drawdown_circuit_breaker(db_session)
    assert ok_streak is False
    assert "4 consecutive SL_HIT" in msg_streak
    assert scheduler.circuit_breaker_tripped is True

    # Clean up breaker state
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None


def test_post_exit_cooldown(db_session):
    """Test 5: Mandatory cooldown timer blocks entries after SL_HIT or manual stop."""
    now = now_utc()
    db_session.query(TradeLedger).filter(TradeLedger.symbol.like("%GOLD%")).delete(synchronize_session=False)
    db_session.commit()

    # Closed 10 minutes ago with SL_HIT
    t_closed = TradeLedger(
        account_type="DEMO",
        position_id=990050,
        order_ticket=990050,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("2600.00"),
        exit_price=Decimal("2590.00"),
        sl=Decimal("2590.00"),
        tp1=Decimal("2620.00"),
        tp2=Decimal("2630.00"),
        gross_pnl=Decimal("-10.00"),
        net_pnl=Decimal("-10.00"),
        exit_reason="SL_HIT",
        opened_at_utc=now - timedelta(minutes=20),
        closed_at_utc=now - timedelta(minutes=10),
    )
    db_session.add(t_closed)
    db_session.commit()

    # SCALP has 30m cooldown: 10m elapsed -> 20m remaining -> blocked
    ok_scalp, msg_scalp = scheduler._check_post_exit_cooldown("GOLD#", "SCALP", db_session)
    assert ok_scalp is False
    assert "COOLDOWN_ACTIVE" in msg_scalp
    assert "GOLD" in msg_scalp

    # SWING has 240m cooldown: blocked
    ok_swing, msg_swing = scheduler._check_post_exit_cooldown("GOLD#", "SWING", db_session)
    assert ok_swing is False
    assert "COOLDOWN_ACTIVE" in msg_swing

    # Move closed_at to 40 minutes ago (past 30m SCALP cooldown)
    t_closed.closed_at_utc = now - timedelta(minutes=40)
    db_session.commit()

    ok_scalp_ready, _ = scheduler._check_post_exit_cooldown("GOLD#", "SCALP", db_session)
    assert ok_scalp_ready is True


def test_trade_geometry_and_net_rr():
    """Test 6: Reject inverted R:R, tight noise stops, and incorrect geometry."""
    # 1. Directional sanity: BUY with sl >= entry must fail
    ok, msg = risk_engine.validate_trade_geometry_and_rr(
        direction="BUY",
        entry=100.0,
        sl=105.0,
        tp1=110.0,
        tp2=120.0,
        mode="SCALP",
        current_spread_price=0.02,
        ltf_atr_14=1.0,
    )
    assert ok is False
    assert "Invalid BUY geometry" in msg

    # 2. Inverted R:R bug test (the SOLUSD# bug where TP1 distance was 0.62x SL distance):
    # Entry 135.0, SL 133.50 (SL dist 1.50), TP1 136.0 (TP dist 1.00) -> 0.67:1 R:R
    ok_inv, msg_inv = risk_engine.validate_trade_geometry_and_rr(
        direction="BUY",
        entry=135.0,
        sl=133.50,
        tp1=136.00,
        tp2=137.00,
        mode="SCALP",
        current_spread_price=0.05,
        ltf_atr_14=1.0,
    )
    assert ok_inv is False
    assert "Net R:R ratio" in msg_inv
    assert "1.8" in msg_inv

    # 3. Minimum Structural SL distance: SL tighter than 1.2 * ATR(14) placed in noise
    ok_noise, msg_noise = risk_engine.validate_trade_geometry_and_rr(
        direction="BUY",
        entry=100.0,
        sl=99.5,  # 0.50 SL dist
        tp1=102.0,
        tp2=104.0,
        mode="SCALP",
        current_spread_price=0.01,
        ltf_atr_14=1.0,  # 1.2 * ATR = 1.20 > 0.50
    )
    assert ok_noise is False
    assert "Stop placed in noise" in msg_noise

    # 4. Valid trade passing all gates (>= 1.8R net after spread)
    ok_valid, msg_valid = risk_engine.validate_trade_geometry_and_rr(
        direction="BUY",
        entry=100.0,
        sl=98.5,  # 1.50 SL dist >= 1.2 * 1.0
        tp1=103.0,  # 3.00 TP dist, net 2.98 / 1.50 = 1.98R >= 1.8R
        tp2=105.0,
        mode="SCALP",
        current_spread_price=0.02,
        ltf_atr_14=1.0,
    )
    assert ok_valid is True
    assert msg_valid == "OK"


def test_solusd_lot_sizing_and_risk_cap():
    """Test 7: SOLUSD# position sizing strictly capped at $50 cash risk."""
    ok, lots, msg = risk_engine.calculate_lot_size(
        equity=24500.0,  # Demo account equity
        risk_pct=0.50,  # Intended 0.50% = $122.50
        entry_price=135.0,
        sl_price=133.50,  # $1.50 SL distance
        contract_size=1.0,
        tick_size=0.01,
        tick_value=0.01,
        volume_min=0.01,
        volume_step=0.01,
        max_dollar_risk=50.0,  # Hard $50 cap
    )
    assert ok is True
    # Stop distance = 1.50, ticks = 150, tick_value = 0.01 -> loss_per_lot = $1.50
    # Capped cash risk = $50.00 -> lots = 50.00 / 1.50 = 33.33 lots
    assert lots == 33.33
    # Verify exact loss at stop: 33.33 * 1.50 = $49.995 <= $50.00
    actual_loss = lots * 1.50
    assert actual_loss <= 50.0


def test_deal_reconciler_timezone_and_reason_mapping():
    """Test 8: Exact MT5 deal reason mapping and broker timezone normalization (Cyprus EET offset)."""
    # Deal reason classifications
    assert classify_exit_reason(4, profit=-15.0) == "SL_HIT"
    assert classify_exit_reason(4, profit=25.0) == "TRAIL_SL"
    assert classify_exit_reason(5, profit=50.0) == "TP_HIT"
    assert classify_exit_reason(1, profit=-5.0) == "MANUAL_MOBILE"
    assert classify_exit_reason(0, profit=0.0) == "MANUAL_TERMINAL"
    assert classify_exit_reason(6, profit=-100.0) == "MARGIN_STOP_OUT"

    # Broker timezone normalization
    # XM MT5 returns Cyprus time (+7200s ahead of UTC).
    # broker_epoch_to_utc() subtracts the broker offset.
    broker_epoch = 1700007200  # 7200s ahead
    utc_dt = broker_epoch_to_utc(broker_epoch, offset_sec=7200)
    assert int(utc_dt.timestamp()) == 1700000000

    # Ensure IST string conversion produces accurate time without double +2h offset
    ist_str = to_ist_str(utc_dt)
    assert "IST" in ist_str


def test_forensic_learner_sl_guard_and_clean_poisoned_rules(db_session):
    """Test 9: Forensic learner guards against false SL hits and cleans poisoned rules."""
    # 1. Guard check: manual close should not trigger postmortem
    t_manual = TradeLedger(
        account_type="DEMO",
        position_id=990080,
        order_ticket=990080,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("2600.00"),
        exit_price=Decimal("2598.00"),
        sl=Decimal("2580.00"),
        tp1=Decimal("2620.00"),
        tp2=Decimal("2630.00"),
        gross_pnl=Decimal("-2.00"),
        net_pnl=Decimal("-2.00"),
        exit_reason="MANUAL_MOBILE",
        opened_at_utc=now_utc() - timedelta(minutes=20),
        closed_at_utc=now_utc() - timedelta(minutes=10),
    )
    db_session.add(t_manual)
    db_session.commit()

    res_manual = forensic_learner.run_sl_hit_postmortem(trade_id=t_manual.id, db=db_session)
    assert res_manual is None

    # 2. Guard check: trade labeled SL_HIT but closed at only 10% of SL distance (<80%)
    t_fake_sl = TradeLedger(
        account_type="DEMO",
        position_id=990081,
        order_ticket=990081,
        symbol="GOLD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("2600.00"),
        exit_price=Decimal("2598.00"),  # 2.0 / 20.0 = 10% of SL distance
        sl=Decimal("2580.00"),
        tp1=Decimal("2620.00"),
        tp2=Decimal("2630.00"),
        gross_pnl=Decimal("-2.00"),
        net_pnl=Decimal("-2.00"),
        exit_reason="SL_HIT",
        opened_at_utc=now_utc() - timedelta(minutes=20),
        closed_at_utc=now_utc() - timedelta(minutes=10),
    )
    db_session.add(t_fake_sl)
    db_session.commit()

    res_fake_sl = forensic_learner.run_sl_hit_postmortem(trade_id=t_fake_sl.id, db=db_session)
    assert res_fake_sl is None

    # 3. Clean poisoned rules function
    # Insert a fake rule linked to a non-SL trade
    bogus_trade = TradeLedger(
        account_type="DEMO",
        position_id=990099,
        order_ticket=990099,
        symbol="EURUSD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="CLOSED",
        entry_order_type="MARKET",
        lots=Decimal("0.01"),
        initial_lots=Decimal("0.01"),
        entry_price=Decimal("1.0800"),
        exit_price=Decimal("1.0798"),  # closed immediately
        sl=Decimal("1.0750"),
        tp1=Decimal("1.0850"),
        tp2=Decimal("1.0900"),
        gross_pnl=Decimal("-0.20"),
        net_pnl=Decimal("-0.20"),
        exit_reason="MANUAL_MOBILE",
        opened_at_utc=now_utc() - timedelta(hours=1),
        closed_at_utc=now_utc() - timedelta(minutes=50),
    )
    db_session.add(bogus_trade)
    db_session.commit()

    bogus_rule = LearnedPairRule(
        rule_code="TEST_BOGUS_RULE",
        symbol="EURUSD#",
        mode="SCALP",
        status="LIVE",
        origin_loss_ids_json=json.dumps([bogus_trade.id]),
        condition_json=json.dumps({"filter": "TEST"}),
        action_json=json.dumps({"action": "BLOCK_ALL"}),
    )
    db_session.add(bogus_rule)
    db_session.commit()

    # Run cleanup
    clean_res = forensic_learner.clean_poisoned_rules(db_session)
    assert clean_res["deprecated_count"] >= 1

    # Verify rule was deprecated
    updated_rule = db_session.query(LearnedPairRule).filter_by(rule_code="TEST_BOGUS_RULE").first()
    assert updated_rule.status == "DEPRECATED"


def test_rest_endpoints_guardrails_and_assign():
    """Test 10: Verify REST routes respond cleanly."""
    app = create_app(enable_lifespan_tasks=False)
    client = TestClient(app)

    # 1. /api/ai-brain/risk-guardrails
    resp_gr = client.get("/api/ai-brain/risk-guardrails")
    assert resp_gr.status_code == 200
    data_gr = resp_gr.json()
    assert "open_positions_count" in data_gr
    assert "max_positions_limit" in data_gr
    assert data_gr["max_positions_limit"] == 5
    assert "circuit_breaker" in data_gr
    assert "cooldowns" in data_gr

    # 2. /api/ai-brain/reconcile-mt5
    resp_rec = client.post("/api/ai-brain/reconcile-mt5")
    assert resp_rec.status_code == 200
    data_rec = resp_rec.json()
    assert "status" in data_rec
    assert "reconciled_count" in data_rec

    # 3. /api/pairs/{symbol}/assign-strategy
    resp_assign = client.post(
        "/api/pairs/GOLD%23/assign-strategy",
        json={
            "scalp_strategy_id": 1,
            "mode": "SCALP",
            "planning_tf": "M15",
            "execution_tf": "M5",
        },
    )
    assert resp_assign.status_code == 200
    data_assign = resp_assign.json()
    assert data_assign["status"] == "SUCCESS"
    assert data_assign["scalp_strategy_id"] == 1
    assert data_assign["scalp_enabled"] is True


def test_saved_strategies_and_tested_pnl_vault(db_session):
    """Test 11: Verify SavedStrategy model, default seed records, and REST endpoints."""
    from backend.app.db.models import SavedStrategy
    from backend.app.db.session import get_db

    app = create_app(enable_lifespan_tasks=False)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    # 1. GET /api/ai-brain/saved-strategies
    resp_list = client.get("/api/ai-brain/saved-strategies")
    assert resp_list.status_code == 200
    strats = resp_list.json()
    assert len(strats) >= 4
    first = strats[0]
    assert "tested_net_pnl" in first
    assert "profit_factor" in first
    assert "win_rate_pct" in first
    assert "total_r" in first
    assert "max_drawdown_pct" in first
    assert "is_active_live" in first

    # 2. POST /api/ai-brain/saved-strategies (AST validation guard)
    bad_code = "import os\nos.system('calc')"
    resp_bad = client.post(
        "/api/ai-brain/saved-strategies",
        json={
            "name": "Malicious Strategy",
            "strategy_code": bad_code,
            "mode": "SCALP",
        },
    )
    assert resp_bad.status_code == 400
    assert "AST Security validation failed" in resp_bad.json()["detail"]

    # 3. POST /api/ai-brain/saved-strategies (Valid strategy)
    good_code = '''DEFAULT_PARAMS = {"period": 14}
def evaluate(df, params):
    if len(df) < 20: return None
    c = float(df["close"].iloc[-1])
    return {"signal": "BUY", "mode": "SCALP", "entry": c, "sl": c - 2.0, "tp1": c + 3.0, "tp2": c + 6.0, "reason": "Test ok"}
'''
    resp_good = client.post(
        "/api/ai-brain/saved-strategies",
        json={
            "name": "Test Verified FVG Scalp",
            "strategy_code": good_code,
            "mode": "SCALP",
            "planning_tf": "M15",
            "execution_tf": "M5",
            "symbols": ["GOLD#", "BTCUSD#"],
            "rules_summary": "Test automated scalp rule",
            "tested_net_pnl": 350.50,
            "profit_factor": 2.25,
            "win_rate_pct": 65.0,
            "total_r": 12.5,
            "max_drawdown_pct": 3.9,
            "sample_trades_count": 45,
            "test_source": "BACKTEST_XM",
        },
    )
    assert resp_good.status_code == 200
    good_data = resp_good.json()
    assert good_data["status"] == "SUCCESS"
    saved_id = good_data["strategy"]["id"]

    # 4. POST /api/ai-brain/saved-strategies/{id}/apply
    resp_apply = client.post(
        f"/api/ai-brain/saved-strategies/{saved_id}/apply",
        json={"symbols": ["GOLD#", "BTCUSD#"], "mode": "SCALP"},
    )
    assert resp_apply.status_code == 200
    apply_data = resp_apply.json()
    assert apply_data["status"] == "SUCCESS"
    assert "GOLD#" in apply_data["applied_pairs"] or "GOLD" in apply_data["applied_pairs"]

    # Verify DB persistence
    db_session.expire_all()
    gold_bot = db_session.query(TradingPairBot).filter(
        (TradingPairBot.symbol == "GOLD#") | (TradingPairBot.symbol == "GOLD")
    ).first()
    assert gold_bot is not None
    assert gold_bot.scalp_strategy_id == apply_data["script_id"]
    assert gold_bot.scalp_enabled is True

    # 5. DELETE /api/ai-brain/saved-strategies/{id}
    resp_del = client.delete(f"/api/ai-brain/saved-strategies/{saved_id}")
    assert resp_del.status_code == 200
    assert resp_del.json()["status"] == "SUCCESS"


def test_swing_and_scalp_rule_enforcement_in_supervisor(db_session):
    """Test 12: Verify get_active_rules strips # cleanly and swing_sig blocks when active rules match."""
    from backend.app.db.models import LearnedPairRule
    from backend.app.ai_brain.gemini_supervisor import gemini_supervisor
    from backend.app.ai_brain.market_packet import MarketPacket

    # Clean existing test rules for USDJPY
    db_session.query(LearnedPairRule).filter(
        LearnedPairRule.symbol.like("%USDJPY%")
    ).delete(synchronize_session=False)
    db_session.commit()

    # Create active LIVE swing rule blocking BUY
    rule = LearnedPairRule(
        rule_code="TEST_SWING_BLOCK_USDJPY",
        symbol="USDJPY#",
        mode="SWING",
        status="LIVE",
        condition_json=json.dumps({"filter_action": "BLOCK_BUY", "indicator": "ema_trend"}),
        action_json=json.dumps({"action": "WAIT"}),
    )
    db_session.add(rule)
    db_session.commit()

    # get_active_rules must find it querying 'USDJPY' or 'USDJPY#'
    rules_with_hash = gemini_supervisor.get_active_rules("USDJPY#", db_session)
    assert len(rules_with_hash) >= 1
    assert any(r["rule_code"] == "TEST_SWING_BLOCK_USDJPY" for r in rules_with_hash)

    rules_no_hash = gemini_supervisor.get_active_rules("USDJPY", db_session)
    assert len(rules_no_hash) >= 1
    assert any(r["rule_code"] == "TEST_SWING_BLOCK_USDJPY" for r in rules_no_hash)

    # Test supervision fallback blocking swing BUY when higher-timeframe trend is opposite
    packet = MarketPacket(
        symbol="USDJPY#",
        asset_class="FOREX",
        timestamp_utc=now_utc().isoformat(),
        timestamp_ist=to_ist_str(now_utc()),
        bid=152.500,
        ask=152.510,
        spread_points=10,
        pdh=153.000,
        pdl=151.000,
        swing_bias_h4_d1="BEARISH",  # Opposite to BUY
        scalp_bias_m15_h1="CHOP",
        timeframe_breakdown={},
        candidate_signals={},
        cross_pair_momentum={},
        news_blackout={"is_blackout": False},
    )

    swing_sig = {
        "strategy_id": 999,
        "strategy_name": "Test Swing",
        "signal": "BUY",
        "mode": "SWING",
        "entry": 152.500,
        "sl": 151.500,
        "tp1": 154.500,
        "tp2": 156.000,
        "reason": "Breakout",
    }
    packet.candidate_signals = {"swing_signal": swing_sig}

    output = gemini_supervisor._fallback_deterministic_supervision(
        packet=packet,
        active_rules=rules_with_hash,
    )

    assert output.decision == "WAIT"
    assert "Blocked by rule TEST_SWING_BLOCK_USDJPY" in output.trade_plan_thesis

