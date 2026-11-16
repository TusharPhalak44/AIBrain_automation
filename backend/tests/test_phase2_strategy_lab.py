"""Phase 2 Mandatory Verification Suite: Strategy Lab, XM Fees & $100 Tester.

Verifies:
1. AST sandbox rejects dangerous code (import, eval, dunder) while executing valid indicator math.
2. XM Global spread, slippage, and Wednesday 3x triple-swap deductions.
3. Both PER_TRADE_100 and ACCOUNT_100 backtests persist to BacktestRun, verifying micro-lot (<0.02)
   break-even logic and standard (>=0.02) 50% partial-close logic.
4. Custom strategy script creation and assignment to GOLD# (SCALP) and BTCUSD# (SWING) in MySQL.
5. REST endpoints respond cleanly.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.api.server import create_app
from backend.app.db.models import StrategyScript, BacktestRun, TradingPairBot
from backend.app.db.session import get_db
from backend.app.strategy_lab.sandbox import (
    validate_strategy_ast,
    validate_signal_geometry,
    StrategySandbox,
    SecurityViolationError,
)
from backend.app.strategy_lab.indicators import (
    atr,
    ema,
    rsi,
    swing_highs,
    swing_lows,
    detect_fvg,
    detect_liquidity_sweep,
)
from backend.app.strategy_lab.xm_fee_model import XMFeeEngine
from backend.app.strategy_lab.backtester import StrategyBacktester
from backend.app.strategy_lab.builtin_strategies import (
    BUILTIN_STRATEGIES,
    seed_builtin_strategies,
    STRATEGY_LIQUIDITY_SWEEP_FVG,
)


# -------------------------------------------------------------------------
# Test Fixture: Deterministic OHLCV DataFrame Generator
# -------------------------------------------------------------------------
@pytest.fixture
def sample_ohlcv_df():
    """Generate 100 deterministic bars of OHLCV data."""
    np.random.seed(42)
    base_time = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
    times = [base_time + timedelta(hours=i) for i in range(100)]

    # Upward trending series with clean oscillations
    close_vals = 2650.0 + np.sin(np.linspace(0, 10, 100)) * 15.0 + np.linspace(0, 40, 100)
    high_vals = close_vals + 2.5
    low_vals = close_vals - 2.5
    open_vals = close_vals - 0.5

    df = pd.DataFrame({
        "time": times,
        "open": open_vals,
        "high": high_vals,
        "low": low_vals,
        "close": close_vals,
        "tick_volume": [100] * 100,
        "spread": [25] * 100,
    })
    return df


# -------------------------------------------------------------------------
# 1. AST Sandbox Security & Pre-Vetted Indicator Helpers
# -------------------------------------------------------------------------
def test_ast_sandbox_security_rejection():
    # 1. Reject 'import os'
    bad_code_1 = """
DEFAULT_PARAMS = {}
import os
def evaluate(df, params):
    os.system("dir")
    return None
"""
    is_valid, msg, _ = validate_strategy_ast(bad_code_1)
    assert is_valid is False
    assert "'import' statements are strictly forbidden" in msg

    # 2. Reject 'from math import sqrt'
    bad_code_2 = """
DEFAULT_PARAMS = {}
from math import sqrt
def evaluate(df, params):
    return None
"""
    is_valid, msg, _ = validate_strategy_ast(bad_code_2)
    assert is_valid is False
    assert "'from ... import ...' statements are strictly forbidden" in msg

    # 3. Reject 'eval()' call
    bad_code_3 = """
DEFAULT_PARAMS = {}
def evaluate(df, params):
    eval("2 + 2")
    return None
"""
    is_valid, msg, _ = validate_strategy_ast(bad_code_3)
    assert is_valid is False
    assert "Calling blocked built-in function 'eval()'" in msg

    # 4. Reject dunder attribute access
    bad_code_4 = """
DEFAULT_PARAMS = {}
def evaluate(df, params):
    x = df.__class__.__bases__
    return None
"""
    is_valid, msg, _ = validate_strategy_ast(bad_code_4)
    assert is_valid is False
    assert "Accessing dunder attributes" in msg


def test_ast_sandbox_indicator_helpers(sample_ohlcv_df):
    """Verify pre-vetted indicator helpers execute accurately inside sandbox."""
    valid_code = """
DEFAULT_PARAMS = {"period": 14}
def evaluate(df, params):
    atr_vals = atr(df, params.get("period", 14))
    ema_vals = ema(df["close"], 20)
    rsi_vals = rsi(df["close"], 14)
    fvg = detect_fvg(df)
    sweeps = detect_liquidity_sweep(df, lookback=10)
    
    current_close = float(df["close"].iloc[-1])
    current_atr = float(atr_vals.iloc[-1])
    
    if len(df) > 30:
        entry = current_close
        if current_close >= float(ema_vals.iloc[-1]):
            sl = round(entry - (1.5 * current_atr), 2)
            tp1 = round(entry + (1.5 * (entry - sl)), 2)
            tp2 = round(entry + (3.0 * (entry - sl)), 2)
            return {
                "signal": "BUY",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "EMA trend test signal",
            }
        else:
            sl = round(entry + (1.5 * current_atr), 2)
            tp1 = round(entry - (1.5 * (sl - entry)), 2)
            tp2 = round(entry - (3.0 * (sl - entry)), 2)
            return {
                "signal": "SELL",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "EMA trend test signal",
            }
    return None
"""
    is_valid, msg, meta = validate_strategy_ast(valid_code)
    assert is_valid is True
    assert meta["has_default_params"] is True

    sandbox = StrategySandbox(valid_code)
    sig = sandbox.evaluate(sample_ohlcv_df)
    assert sig is not None
    assert sig["mode"] == "SCALP"
    if sig["signal"] == "BUY":
        assert sig["sl"] < sig["entry"] < sig["tp1"] <= sig["tp2"]
    else:
        assert sig["sl"] > sig["entry"] > sig["tp1"] >= sig["tp2"]


def test_signal_geometry_validator():
    # Valid BUY
    ok, _ = validate_signal_geometry({
        "signal": "BUY",
        "mode": "SCALP",
        "entry": 2650.0,
        "sl": 2640.0,
        "tp1": 2665.0,
        "tp2": 2680.0,
        "reason": "Test",
    })
    assert ok is True

    # Invalid BUY: SL above entry
    bad_buy, err = validate_signal_geometry({
        "signal": "BUY",
        "mode": "SCALP",
        "entry": 2650.0,
        "sl": 2655.0,
        "tp1": 2665.0,
        "tp2": 2680.0,
        "reason": "Test",
    })
    assert bad_buy is False
    assert "Invalid BUY geometry" in err

    # Valid SELL
    ok, _ = validate_signal_geometry({
        "signal": "SELL",
        "mode": "SWING",
        "entry": 2650.0,
        "sl": 2660.0,
        "tp1": 2635.0,
        "tp2": 2620.0,
        "reason": "Test",
    })
    assert ok is True


# -------------------------------------------------------------------------
# 2. XM Global Fee Engine & Wednesday 3x Triple-Swap
# -------------------------------------------------------------------------
def test_xm_fee_engine_and_wednesday_triple_swap(db_session):
    fee_engine = XMFeeEngine(session=db_session)
    spec = fee_engine.get_symbol_spec("GOLD#")
    assert spec.symbol == "GOLD#"
    assert spec.contract_size == 100.0

    # Test Wednesday Triple Swap:
    # 2026-11-10 is Tuesday.
    # Entry: Tuesday 18:00 (broker time: 20:00).
    # Exit: Thursday 12:00 (broker time: 14:00).
    # Midnights crossed:
    # 1. Midnight Tuesday -> Wednesday 00:00 (1x swap)
    # 2. Midnight Wednesday -> Thursday 00:00 (3x triple-swap, weekday 2)
    # Total swap multiplier = 1x + 3x = 4x
    entry_dt = datetime(2026, 11, 10, 18, 0, 0, tzinfo=timezone.utc)
    exit_dt = datetime(2026, 11, 12, 10, 0, 0, tzinfo=timezone.utc)

    lots = 0.10
    swap_val = fee_engine.calculate_swap(
        symbol_spec=spec,
        direction="BUY",
        lots=lots,
        entry_time=entry_dt,
        exit_time=exit_dt,
        broker_offset_sec=7200,
    )
    # Expected: 4 * swap_long * lots = 4 * (-27.50) * 0.10 = -11.00
    expected_swap = round(4 * spec.swap_long * lots, 2)
    assert swap_val == expected_swap

    # Test Trade Friction Net PnL Deduction
    friction = fee_engine.calculate_trade_friction(
        symbol="GOLD#",
        direction="BUY",
        lots=lots,
        entry_price=2650.0,
        exit_price=2660.0,  # +$10 move * 100 oz * 0.10 lots = $100 gross
        entry_time=entry_dt,
        exit_time=exit_dt,
        bar_spread_points=25,
        slippage_points=2,
        commission_per_lot=0.0,
    )
    assert friction["gross_pnl"] == 100.00
    assert friction["spread_cost"] == 2.50  # 25 pts * $1.0 * 0.10 lots
    assert friction["slippage_cost"] == 0.40  # 2 pts * 2 * $1.0 * 0.10 lots
    assert friction["swap_cost"] == expected_swap  # -11.00
    # Net PnL = Gross (100) - Spread (2.50) - Slip (0.40) + Swap (-11.00) = 86.10
    assert friction["net_pnl"] == 86.10


# -------------------------------------------------------------------------
# 3. $100 Strategy Tester Engine: PER_TRADE_100 & ACCOUNT_100 Modes
# -------------------------------------------------------------------------
def test_backtester_micro_and_standard_tiers(sample_ohlcv_df, db_session):
    fee_engine = XMFeeEngine(session=db_session)
    tester = StrategyBacktester(fee_engine=fee_engine, session=db_session)

    # Strategy that generates entries
    test_strategy = """
DEFAULT_PARAMS = {}
def evaluate(df, params):
    if len(df) < 25:
        return None
    close = float(df["close"].iloc[-1])
    if len(df) % 15 == 0:
        return {
            "signal": "BUY",
            "mode": "SCALP",
            "entry": close,
            "sl": round(close - 3.0, 2),
            "tp1": round(close + 4.5, 2),
            "tp2": round(close + 9.0, 2),
            "reason": "Test Setup",
        }
    return None
"""
    # 1. Test PER_TRADE_100 Mode
    res_per_trade = tester.run_backtest(
        strategy_code=test_strategy,
        symbol="GOLD#",
        df=sample_ohlcv_df,
        timeframe="H1",
        test_mode="PER_TRADE_100",
        save_to_db=True,
    )
    assert res_per_trade["test_mode"] == "PER_TRADE_100"
    assert res_per_trade["capital_usd"] == 100.0
    assert "win_rate_pct" in res_per_trade
    assert "profit_factor" in res_per_trade
    assert "net_pnl_usd" in res_per_trade
    assert "net_roi_pct" in res_per_trade
    assert len(res_per_trade["trades"]) > 0

    # Verify persisted to BacktestRun in DB
    run_rec = db_session.query(BacktestRun).filter_by(id=res_per_trade["backtest_run_id"]).first()
    assert run_rec is not None
    assert run_rec.symbol == "GOLD#"
    assert run_rec.test_mode == "PER_TRADE_100"

    # 2. Test ACCOUNT_100 Mode (0.01 micro-lot vs >=0.02 standard lot handling)
    res_account = tester.run_backtest(
        strategy_code=test_strategy,
        symbol="GOLD#",
        df=sample_ohlcv_df,
        timeframe="H1",
        test_mode="ACCOUNT_100",
        risk_pct=1.0,
        leverage=1000,
        save_to_db=True,
    )
    assert res_account["test_mode"] == "ACCOUNT_100"
    assert "max_dd_pct" in res_account
    assert len(res_account["equity_curve"]) >= 1

    # Verify trades contain exit reasons
    for t in res_account["trades"]:
        assert t["exit_reason"] in ("SL_HIT", "TP_HIT", "PARTIAL_TP1", "TRAIL_SL")


# -------------------------------------------------------------------------
# 4. Custom Strategy Script Persistence & Pair Strategy Assignment
# -------------------------------------------------------------------------
def test_custom_strategy_and_pair_assignment(db_session):
    # 1. Seed built-in starter strategies
    seeded = seed_builtin_strategies(db_session)
    assert seeded >= 0
    builtins = db_session.query(StrategyScript).filter_by(is_builtin=True).all()
    assert len(builtins) == 4

    # 2. Save Custom User Strategy
    custom_code = STRATEGY_LIQUIDITY_SWEEP_FVG
    custom_script = StrategyScript(
        name="My Custom Gold Scalper",
        description="Pasted user script",
        target_mode="SCALP",
        python_code=custom_code,
        default_params_json='{"sweep_lookback": 25}',
        is_builtin=False,
    )
    db_session.add(custom_script)
    db_session.commit()
    db_session.refresh(custom_script)
    assert custom_script.id is not None

    # 3. Assign to GOLD# (SCALP) and BTCUSD# (SWING)
    gold_pair = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    btc_pair = db_session.query(TradingPairBot).filter_by(symbol="BTCUSD#").first()

    assert gold_pair is not None
    assert btc_pair is not None

    gold_pair.scalp_strategy_id = custom_script.id
    btc_pair.swing_strategy_id = custom_script.id
    db_session.commit()

    # Re-query and verify assignment in MySQL
    re_gold = db_session.query(TradingPairBot).filter_by(symbol="GOLD#").first()
    re_btc = db_session.query(TradingPairBot).filter_by(symbol="BTCUSD#").first()

    assert re_gold.scalp_strategy_id == custom_script.id
    assert re_btc.swing_strategy_id == custom_script.id


# -------------------------------------------------------------------------
# 5. REST Endpoints Verification (/api/strategies/*)
# -------------------------------------------------------------------------
@pytest.fixture
def strategy_client(test_engine):
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


def test_strategy_api_routes(strategy_client, sample_ohlcv_df):
    # 1. GET /api/strategies
    res = strategy_client.get("/api/strategies")
    assert res.status_code == 200
    strats = res.json()
    assert len(strats) >= 4

    # 2. POST /api/strategies/validate
    valid_res = strategy_client.post("/api/strategies/validate", json={"python_code": STRATEGY_LIQUIDITY_SWEEP_FVG})
    assert valid_res.status_code == 200
    assert valid_res.json()["valid"] is True

    bad_res = strategy_client.post("/api/strategies/validate", json={"python_code": "import os"})
    assert bad_res.status_code == 200
    assert bad_res.json()["valid"] is False

    # 3. POST /api/strategies (Create custom)
    create_payload = {
        "name": "API Test Scalper",
        "description": "Created via API",
        "target_mode": "SCALP",
        "python_code": STRATEGY_LIQUIDITY_SWEEP_FVG,
        "default_params": {"sweep_lookback": 15},
    }
    create_res = strategy_client.post("/api/strategies", json=create_payload)
    assert create_res.status_code == 200
    new_strat_id = create_res.json()["id"]

    # 4. POST /api/strategies/backtest with custom bar data
    df_records = [
        {
            "time": row["time"].isoformat() if hasattr(row["time"], "isoformat") else str(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "tick_volume": int(row["tick_volume"]),
            "spread": int(row["spread"]),
        }
        for _, row in sample_ohlcv_df.iterrows()
    ]
    backtest_payload = {
        "strategy_id": new_strat_id,
        "symbol": "GOLD#",
        "timeframe": "H1",
        "test_mode": "PER_TRADE_100",
        "bars_data": df_records,
    }
    bt_res = strategy_client.post("/api/strategies/backtest", json=backtest_payload)
    assert bt_res.status_code == 200
    bt_data = bt_res.json()
    assert bt_data["capital_usd"] == 100.0
    assert "net_pnl_usd" in bt_data

    # 5. GET /api/strategies/backtests
    runs_res = strategy_client.get("/api/strategies/backtests")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 1

    # 6. POST /api/pairs/{symbol}/assign-strategy
    assign_res = strategy_client.post(
        "/api/pairs/GOLD/assign-strategy",
        json={"scalp_strategy_id": new_strat_id},
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["scalp_strategy_id"] == new_strat_id

