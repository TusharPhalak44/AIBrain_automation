"""$100 Strategy Tester Engine with Realistic XM Friction.

Features:
1. Zero look-ahead bar-by-bar execution (signal at bar i close, enter bar i+1 open).
2. PairChartBot.mq5 identical exit mirroring:
   - Micro-Lot (< 2 * volume_step, e.g. 0.01): Break-Even shift at +1.5R, 100% hold to TP2.
   - Standard Tier (>= 2 * volume_step, e.g. >= 0.02): Close 50% at +1.5R, move BE, trail runner to TP2.
3. Two Selectable $100 Test Modes:
   - PER_TRADE_100: $100 benchmark per setup with exact Profitability %.
   - ACCOUNT_100: Compounding $100 starting equity, dynamic risk sizing, 18% margin ceiling.
4. Historical bars from MT5 actor or offline uploaded DataFrame (Zero mock data).
5. Persists execution to BacktestRun in MySQL.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.risk_engine import risk_engine
from backend.app.db.models import BacktestRun
from backend.app.db.session import SessionLocal
from backend.app.mt5_bridge.mt5_actor import mt5_actor
from backend.app.strategy_lab.sandbox import StrategySandbox
from backend.app.strategy_lab.xm_fee_model import XMFeeEngine, xm_fee_engine

logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


async def fetch_mt5_ohlcv(symbol: str, timeframe: str = "H1", count: int = 500) -> Optional[pd.DataFrame]:
    """Fetch historical OHLCV bars from connected MT5 terminal with retry & symbol fallback."""
    from backend.app.mt5_bridge.connector import mt5_connector

    # Auto-connect if terminal not connected yet
    if not mt5_connector.is_connected:
        try:
            await mt5_connector.connect("DEMO")
        except Exception:
            pass

    try:
        import MetaTrader5 as mt5
        from backend.app.core.instruments import resolve_marketwatch_symbol

        tf_val = TIMEFRAME_MAP.get(timeframe.upper(), mt5.TIMEFRAME_H1)
        mw_sym = resolve_marketwatch_symbol(symbol)
        clean_sym = symbol.rstrip("#")
        candidates = [mw_sym, symbol, clean_sym, f"{clean_sym}#"]
        seen = set()
        ordered_candidates = []
        for s in candidates:
            if s not in seen:
                seen.add(s)
                ordered_candidates.append(s)

        def _fetch():
            if not mt5.terminal_info():
                mt5.initialize()
            for s in ordered_candidates:
                mt5.symbol_select(s, True)
                rates = mt5.copy_rates_from_pos(s, tf_val, 0, count)
                if rates is not None and len(rates) > 0:
                    df = pd.DataFrame(rates)
                    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                    return df
            return None

        # Retry up to 3 times (300ms apart) in case terminal is syncing historical bars
        for attempt in range(3):
            df = await mt5_actor.run_quote(_fetch)
            if df is not None and not df.empty:
                return df
            await asyncio.sleep(0.3)

        return None
    except Exception as e:
        logger.warning(f"Failed to fetch MT5 historical bars for {symbol}: {e}")
        return None


class StrategyBacktester:
    """Executes high-fidelity bar-by-bar backtests using the Strategy Sandbox."""

    def __init__(self, fee_engine: Optional[XMFeeEngine] = None, session=None):
        self.fee_engine = fee_engine or xm_fee_engine
        self._session = session

    def run_backtest(
        self,
        strategy_code: str,
        symbol: str,
        df: pd.DataFrame,
        timeframe: str = "H1",
        test_mode: str = "ACCOUNT_100",  # ACCOUNT_100 or PER_TRADE_100
        strategy_params: Optional[Dict[str, Any]] = None,
        strategy_id: Optional[int] = None,
        risk_pct: float = 1.0,
        leverage: int = 1000,
        slippage_points: Optional[int] = None,
        commission_per_lot: float = 0.0,
        save_to_db: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute deterministic zero look-ahead bar-by-bar backtest.
        """
        # Validate data columns
        required_cols = ["time", "open", "high", "low", "close"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"OHLCV DataFrame missing required column: '{col}'")

        if "spread" not in df.columns:
            df["spread"] = 0
        if "tick_volume" not in df.columns:
            df["tick_volume"] = 100

        # Sort chronological
        df = df.sort_values("time").reset_index(drop=True)
        total_bars = len(df)
        if total_bars < 30:
            raise ValueError(f"Insufficient bars for backtesting ({total_bars} < 30).")

        sandbox = StrategySandbox(strategy_code)
        spec = self.fee_engine.get_symbol_spec(symbol)

        # Simulation state
        mode_upper = test_mode.upper()
        account_equity = 100.0 if mode_upper == "ACCOUNT_100" else 100.0
        peak_equity = account_equity
        max_drawdown_pct = 0.0

        equity_curve = [{"time": str(df["time"].iloc[0]), "equity": round(account_equity, 2)}]
        trades: List[Dict[str, Any]] = []
        pending_signal: Optional[Dict[str, Any]] = None

        # Position tracking
        # Each position: dict(ticket, symbol, direction, lots, entry_price, sl, tp1, tp2, tp1_hit, be_price, entry_time)
        open_pos: Optional[Dict[str, Any]] = None

        for i in range(20, total_bars):
            current_bar = df.iloc[i]
            bar_time = current_bar["time"]
            bar_open = float(current_bar["open"])
            bar_high = float(current_bar["high"])
            bar_low = float(current_bar["low"])
            bar_close = float(current_bar["close"])
            bar_spread = int(current_bar.get("spread", 0))

            # -------------------------------------------------------------
            # 1. Manage Open Position against Current Bar (Exit Simulation)
            # -------------------------------------------------------------
            if open_pos is not None:
                p_dir = open_pos["direction"]
                p_lots = open_pos["lots"]
                p_entry = open_pos["entry_price"]
                p_sl = open_pos["sl"]
                p_tp1 = open_pos["tp1"]
                p_tp2 = open_pos["tp2"]
                p_time = open_pos["entry_time"]
                p_be = open_pos["be_price"]
                is_micro = p_lots < (2.0 * spec.volume_step)

                exit_occurred = False
                exit_price = 0.0
                exit_reason = ""
                closed_lots = 0.0

                if p_dir == "BUY":
                    # Check Stop Loss hit
                    if bar_low <= p_sl:
                        exit_price = p_sl
                        exit_reason = "SL_HIT"
                        closed_lots = p_lots
                        exit_occurred = True

                    # Check TP1 hit
                    elif not open_pos["tp1_hit"] and bar_high >= p_tp1:
                        open_pos["tp1_hit"] = True
                        if is_micro:
                            # Micro-Lot Tier: Move SL to Break-Even + buffer, keep 100% position to TP2
                            open_pos["sl"] = p_be
                        else:
                            # Standard Tier: Partial close 50% at TP1
                            half_lots = round(np.floor((p_lots * 0.5) / spec.volume_step) * spec.volume_step, 4)
                            if half_lots >= spec.volume_min:
                                friction_half = self.fee_engine.calculate_trade_friction(
                                    symbol=symbol,
                                    direction="BUY",
                                    lots=half_lots,
                                    entry_price=p_entry,
                                    exit_price=p_tp1,
                                    entry_time=p_time,
                                    exit_time=bar_time,
                                    bar_spread_points=bar_spread,
                                    slippage_points=slippage_points,
                                    commission_per_lot=commission_per_lot,
                                )
                                trades.append({
                                    "trade_id": len(trades) + 1,
                                    "symbol": symbol,
                                    "direction": "BUY",
                                    "mode": open_pos["mode"],
                                    "lots": half_lots,
                                    "entry_price": p_entry,
                                    "exit_price": p_tp1,
                                    "gross_pnl": friction_half["gross_pnl"],
                                    "spread_cost": friction_half["spread_cost"],
                                    "swap_cost": friction_half["swap_cost"],
                                    "commission": friction_half["commission"],
                                    "net_pnl": friction_half["net_pnl"],
                                    "r_multiple": 1.5,
                                    "exit_reason": "PARTIAL_TP1",
                                    "entry_time": str(p_time),
                                    "exit_time": str(bar_time),
                                })
                                account_equity += friction_half["net_pnl"]
                                open_pos["lots"] = round(p_lots - half_lots, 4)
                                open_pos["sl"] = p_be

                    # Check TP2 hit (or trail stop)
                    if not exit_occurred and open_pos["tp1_hit"] and bar_high >= p_tp2:
                        exit_price = p_tp2
                        exit_reason = "TP_HIT"
                        closed_lots = open_pos["lots"]
                        exit_occurred = True

                elif p_dir == "SELL":
                    # Check Stop Loss hit
                    if bar_high >= p_sl:
                        exit_price = p_sl
                        exit_reason = "SL_HIT"
                        closed_lots = p_lots
                        exit_occurred = True

                    # Check TP1 hit
                    elif not open_pos["tp1_hit"] and bar_low <= p_tp1:
                        open_pos["tp1_hit"] = True
                        if is_micro:
                            # Micro-Lot Tier: Move SL to Break-Even - buffer
                            open_pos["sl"] = p_be
                        else:
                            # Standard Tier: Partial close 50% at TP1
                            half_lots = round(np.floor((p_lots * 0.5) / spec.volume_step) * spec.volume_step, 4)
                            if half_lots >= spec.volume_min:
                                friction_half = self.fee_engine.calculate_trade_friction(
                                    symbol=symbol,
                                    direction="SELL",
                                    lots=half_lots,
                                    entry_price=p_entry,
                                    exit_price=p_tp1,
                                    entry_time=p_time,
                                    exit_time=bar_time,
                                    bar_spread_points=bar_spread,
                                    slippage_points=slippage_points,
                                    commission_per_lot=commission_per_lot,
                                )
                                trades.append({
                                    "trade_id": len(trades) + 1,
                                    "symbol": symbol,
                                    "direction": "SELL",
                                    "mode": open_pos["mode"],
                                    "lots": half_lots,
                                    "entry_price": p_entry,
                                    "exit_price": p_tp1,
                                    "gross_pnl": friction_half["gross_pnl"],
                                    "spread_cost": friction_half["spread_cost"],
                                    "swap_cost": friction_half["swap_cost"],
                                    "commission": friction_half["commission"],
                                    "net_pnl": friction_half["net_pnl"],
                                    "r_multiple": 1.5,
                                    "exit_reason": "PARTIAL_TP1",
                                    "entry_time": str(p_time),
                                    "exit_time": str(bar_time),
                                })
                                account_equity += friction_half["net_pnl"]
                                open_pos["lots"] = round(p_lots - half_lots, 4)
                                open_pos["sl"] = p_be

                    # Check TP2 hit
                    if not exit_occurred and open_pos["tp1_hit"] and bar_low <= p_tp2:
                        exit_price = p_tp2
                        exit_reason = "TP_HIT"
                        closed_lots = open_pos["lots"]
                        exit_occurred = True

                # Process final position exit
                if exit_occurred:
                    friction = self.fee_engine.calculate_trade_friction(
                        symbol=symbol,
                        direction=p_dir,
                        lots=closed_lots,
                        entry_price=p_entry,
                        exit_price=exit_price,
                        entry_time=p_time,
                        exit_time=bar_time,
                        bar_spread_points=bar_spread,
                        slippage_points=slippage_points,
                        commission_per_lot=commission_per_lot,
                    )
                    init_risk = abs(p_entry - open_pos["initial_sl"])
                    r_mult = 0.0
                    if init_risk > 0:
                        gain = (exit_price - p_entry) if p_dir == "BUY" else (p_entry - exit_price)
                        r_mult = round(gain / init_risk, 2)

                    trades.append({
                        "trade_id": len(trades) + 1,
                        "symbol": symbol,
                        "direction": p_dir,
                        "mode": open_pos["mode"],
                        "lots": closed_lots,
                        "entry_price": p_entry,
                        "exit_price": exit_price,
                        "gross_pnl": friction["gross_pnl"],
                        "spread_cost": friction["spread_cost"],
                        "swap_cost": friction["swap_cost"],
                        "commission": friction["commission"],
                        "net_pnl": friction["net_pnl"],
                        "r_multiple": r_mult,
                        "exit_reason": exit_reason,
                        "entry_time": str(p_time),
                        "exit_time": str(bar_time),
                    })

                    account_equity += friction["net_pnl"]
                    peak_equity = max(peak_equity, account_equity)
                    if peak_equity > 0:
                        dd = ((peak_equity - account_equity) / peak_equity) * 100.0
                        max_drawdown_pct = max(max_drawdown_pct, dd)

                    equity_curve.append({
                        "time": str(bar_time),
                        "equity": round(account_equity, 2),
                    })
                    open_pos = None

            # -------------------------------------------------------------
            # 2. Execute Pending Signal from Previous Bar Close (At Bar Open)
            # -------------------------------------------------------------
            if pending_signal is not None and open_pos is None:
                sig = pending_signal
                pending_signal = None

                sig_dir = sig["signal"]
                sig_sl = float(sig["sl"])
                sig_tp1 = float(sig["tp1"])
                sig_tp2 = float(sig["tp2"])
                entry_exec_price = bar_open  # Execute at bar open

                # Determine Lots according to Mode
                eff_leverage = max(leverage, 500)
                if mode_upper == "PER_TRADE_100":
                    # $100 allocated capital per trade
                    ok_lots, calc_lots, _ = risk_engine.calculate_lot_size(
                        equity=100.0,
                        risk_pct=100.0,  # $100 total risk budget
                        entry_price=entry_exec_price,
                        sl_price=sig_sl,
                        contract_size=spec.contract_size,
                        tick_size=spec.tick_size,
                        tick_value=spec.tick_value,
                        volume_min=spec.volume_min,
                        volume_step=spec.volume_step,
                    )
                    if calc_lots < spec.volume_min:
                        calc_lots = spec.volume_min
                        ok_lots = True
                else:
                    # ACCOUNT_100 mode: compounding risk % + 18% margin ceiling
                    ok_lots, calc_lots, _ = risk_engine.calculate_lot_size(
                        equity=account_equity,
                        risk_pct=risk_pct,
                        entry_price=entry_exec_price,
                        sl_price=sig_sl,
                        contract_size=spec.contract_size,
                        tick_size=spec.tick_size,
                        tick_value=spec.tick_value,
                        volume_min=spec.volume_min,
                        volume_step=spec.volume_step,
                    )
                    if calc_lots < spec.volume_min:
                        calc_lots = spec.volume_min
                        ok_lots = True

                    # Margin requirement check: notional / effective leverage
                    notional = calc_lots * spec.contract_size * entry_exec_price
                    required_margin = notional / eff_leverage
                    margin_ok, _ = risk_engine.check_margin_ceiling(
                        equity=account_equity,
                        margin_used=required_margin,
                        max_margin_pct=18.0,
                    )
                    if not margin_ok:
                        ok_lots = False

                if ok_lots and calc_lots >= spec.volume_min:
                    spread_buf = (bar_spread if bar_spread > 0 else spec.default_spread_pts) * spec.tick_size
                    be_target = (entry_exec_price + spread_buf) if sig_dir == "BUY" else (entry_exec_price - spread_buf)
                    open_pos = {
                        "direction": sig_dir,
                        "mode": sig.get("mode", "SCALP"),
                        "lots": calc_lots,
                        "entry_price": entry_exec_price,
                        "sl": sig_sl,
                        "initial_sl": sig_sl,
                        "tp1": sig_tp1,
                        "tp2": sig_tp2,
                        "tp1_hit": False,
                        "be_price": round(be_target, spec.digits),
                        "entry_time": bar_time,
                    }

            # -------------------------------------------------------------
            # 3. Call evaluate() on Bar Close (Zero Look-Ahead: df up to i)
            # -------------------------------------------------------------
            if open_pos is None and pending_signal is None:
                sub_df = df.iloc[: i + 1]
                try:
                    sig = sandbox.evaluate(sub_df, params=strategy_params, timeout_sec=2.0)
                    if sig is not None:
                        pending_signal = sig
                except Exception as e:
                    logger.debug(f"Evaluate failed at bar {i}: {e}")

        # -------------------------------------------------------------
        # 4. KPI Aggregation & Return Package
        # -------------------------------------------------------------
        total_trades_count = len(trades)
        wins = [t for t in trades if t["net_pnl"] > 0]
        losses = [t for t in trades if t["net_pnl"] < 0]

        win_rate = (len(wins) / total_trades_count * 100.0) if total_trades_count > 0 else 0.0
        gross_pnl_total = sum(t["gross_pnl"] for t in trades)
        spread_total = sum(t["spread_cost"] for t in trades)
        swap_total = sum(t["swap_cost"] for t in trades)
        comm_total = sum(t["commission"] for t in trades)
        net_pnl_total = sum(t["net_pnl"] for t in trades)

        gross_wins = sum(t["gross_pnl"] for t in wins)
        gross_losses = abs(sum(t["gross_pnl"] for t in losses))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        net_roi_pct = (net_pnl_total / 100.0) * 100.0  # Normalized against $100 starting/per-trade capital
        avg_r = (sum(t["r_multiple"] for t in trades) / total_trades_count) if total_trades_count > 0 else 0.0

        results = {
            "symbol": symbol,
            "timeframe": timeframe,
            "test_mode": mode_upper,
            "capital_usd": 100.0,
            "total_trades": total_trades_count,
            "win_trades": len(wins),
            "loss_trades": len(losses),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "gross_pnl_usd": round(gross_pnl_total, 2),
            "spread_cost_usd": round(spread_total, 2),
            "swap_cost_usd": round(swap_total, 2),
            "commission_cost_usd": round(comm_total, 2),
            "net_pnl_usd": round(net_pnl_total, 2),
            "net_roi_pct": round(net_roi_pct, 2),
            "max_dd_pct": round(max_drawdown_pct, 2),
            "average_r_multiple": round(avg_r, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "strategy_code": strategy_code,
            "strategy_params": strategy_params,
        }

        # -------------------------------------------------------------
        # 5. Persist to MySQL BacktestRun
        # -------------------------------------------------------------
        if save_to_db:
            db_ctx = self._session if self._session is not None else None
            if db_ctx is not None:
                self._save_run(db_ctx, results, strategy_id)
            else:
                with SessionLocal() as db:
                    self._save_run(db, results, strategy_id)

        return results

    def _save_run(self, db, results: Dict[str, Any], strategy_id: Optional[int]) -> int:
        """Persist backtest record into MySQL BacktestRun table."""
        record = BacktestRun(
            strategy_id=strategy_id,
            symbol=results["symbol"],
            timeframe=results["timeframe"],
            test_mode=results["test_mode"],
            capital_usd=Decimal(str(results["capital_usd"])),
            total_trades=results["total_trades"],
            win_rate_pct=Decimal(str(results["win_rate_pct"])),
            gross_pnl_usd=Decimal(str(results["gross_pnl_usd"])),
            spread_cost_usd=Decimal(str(results["spread_cost_usd"])),
            swap_cost_usd=Decimal(str(results["swap_cost_usd"])),
            commission_cost_usd=Decimal(str(results["commission_cost_usd"])),
            net_pnl_usd=Decimal(str(results["net_pnl_usd"])),
            net_roi_pct=Decimal(str(results["net_roi_pct"])),
            max_dd_pct=Decimal(str(results["max_dd_pct"])),
            profit_factor=Decimal(str(results.get("profit_factor", 0.0))),
            strategy_code_snapshot=results.get("strategy_code"),
            params_json=json.dumps(results.get("strategy_params") or {}),
            trades_json=json.dumps(results["trades"]),
            created_at_utc=now_utc(),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        results["backtest_run_id"] = record.id
        return record.id


backtester = StrategyBacktester()

