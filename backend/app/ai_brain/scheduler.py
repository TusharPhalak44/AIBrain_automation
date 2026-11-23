"""Live Interval Execution Scheduler, Risk Routing & Telegram Dispatcher.

Coordinates:
1. Live per-pair countdown scheduler respecting individual & global scan intervals.
2. 1-second WebSocket broadcast of countdowns, live status, and trade events.
3. Execution Mode Routing (AUTO, COPILOT, MONITOR, HALTED).
4. Deterministic Risk Engine gating (lot sizing, margin ceiling, DD locks, zero-naked-trade).
5. Live order dispatch via mt5_actor (Magic 1001 for Scalp, 2001 for Swing).
6. Telegram card alerts for approved setups and trade executions.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.risk_engine import risk_engine
from backend.app.db.session import SessionLocal
from backend.app.db.models import (
    AppSettings,
    MT5AccountProfile,
    TradingPairBot,
    TradeLedger,
    GeminiAnalysisReport,
)
from backend.app.mt5_bridge.connector import mt5_connector
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel
from backend.app.mt5_bridge.deal_reconciler import reconcile_open_trades_with_mt5
from backend.app.ai_brain.position_manager import position_manager
from backend.app.telegram_reports.telegram_bot import telegram_service
from backend.app.api.websocket import manager
from backend.app.ai_brain.market_packet import market_packet_compiler, MarketPacket
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor
from backend.app.ai_brain.instruments import is_symbol_trading_open
from backend.app.ai_brain.cache_manager import cache_manager

logger = logging.getLogger(__name__)

# Correlation Buckets & FX Currencies
CRUDE_SYMBOLS = {"OILCASH", "BRENTCASH"}
METALS_SYMBOLS = {"GOLD", "SILVER", "XAUUSD", "XAGUSD"}
CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"}
FX_CURRENCIES = ["EUR", "GBP", "USD", "JPY", "AUD", "CAD", "NZD", "CHF"]


def decompose_fx_symbol(symbol: str, direction: str) -> Optional[Tuple[str, str, str, str]]:
    """
    Decompose FX pair into base, quote, long_ccy, short_ccy.
    Returns (base, quote, long_ccy, short_ccy) or None if not an FX pair.
    """
    clean = symbol.rstrip("#").upper()
    for base in FX_CURRENCIES:
        if clean.startswith(base):
            quote = clean[len(base):]
            if quote in FX_CURRENCIES:
                if direction.upper() in ("BUY", "LONG"):
                    return base, quote, base, quote
                else:
                    return base, quote, quote, base
    return None


class LiveIntervalScheduler:
    """Manages autonomous interval scanning, countdowns, and execution mode routing."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or SessionLocal
        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None
        self._protection_task: Optional[asyncio.Task] = None
        self._reconcile_task: Optional[asyncio.Task] = None

        # Per-pair scheduler tracking state
        # symbol -> {"next_scan_utc": datetime, "interval_sec": int, "last_scan_ist": str, "status": str}
        self.pair_schedules: Dict[str, Dict[str, Any]] = {}

        # Candle-close gate tracking: (base_sym, mode, execution_tf) -> last_scanned_candle_time
        self._last_scanned_candle_time: Dict[Tuple[str, str, str], Any] = {}

        # Daily Drawdown Circuit Breaker state
        self.circuit_breaker_tripped: bool = False
        self.circuit_breaker_until_utc: Optional[datetime] = None
        self.circuit_breaker_reason: Optional[str] = None

    def _get_db(self) -> Session:
        return self.session_factory()

    def _sync_pair_schedules(self, db: Session) -> None:
        """Synchronize in-memory scheduler state with TradingPairBot and AppSettings."""
        st = db.query(AppSettings).filter_by(id=1).first()
        global_interval = st.global_scan_interval_sec if st else 300
        now = now_utc()

        pairs = db.query(TradingPairBot).filter_by(enabled=True).all()
        active_symbols = set()

        for p in pairs:
            sym = p.symbol
            active_symbols.add(sym)
            interval = p.scan_interval_sec if p.scan_interval_sec and p.scan_interval_sec > 0 else global_interval

            if sym not in self.pair_schedules:
                self.pair_schedules[sym] = {
                    "symbol": sym,
                    "interval_sec": interval,
                    "next_scan_utc": now,  # Scan immediately on initial boot
                    "last_scan_ist": "Never",
                    "status": "WAITING",
                    "last_decision": "NONE",
                }
            else:
                self.pair_schedules[sym]["interval_sec"] = interval

        # Remove deleted/disabled pairs
        for sym in list(self.pair_schedules.keys()):
            if sym not in active_symbols:
                del self.pair_schedules[sym]

    async def start(self) -> None:
        """Start async scanning, countdown broadcast, trade protection, and reconciliation background loops."""
        if not self._running:
            self._running = True
            with self._get_db() as db:
                self._sync_pair_schedules(db)

            self._loop_task = asyncio.create_task(self._scheduler_loop())
            self._broadcast_task = asyncio.create_task(self._countdown_broadcast_loop())
            self._protection_task = asyncio.create_task(self._protection_loop())
            self._reconcile_task = asyncio.create_task(self._reconcile_loop())
            logger.info("Live Interval Scheduler, Protection & Reconciliation loops started.")

    async def stop(self) -> None:
        """Stop background scheduler loops."""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
        if self._protection_task and not self._protection_task.done():
            self._protection_task.cancel()
        if self._reconcile_task and not self._reconcile_task.done():
            self._reconcile_task.cancel()
        logger.info("Live Interval Scheduler stopped.")

    async def _protection_loop(self) -> None:
        """Run position protection (Auto-BE + Partial Scale-Out) every 15 seconds."""
        logger.info("Active trade protection background loop started (15s cadence).")
        while self._running:
            try:
                with self._get_db() as db:
                    await position_manager.manage_active_positions(db)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Protection loop note: {e}")
            await asyncio.sleep(15.0)

    async def _reconcile_loop(self) -> None:
        """Run MT5 open trade reconciliation every 60 seconds."""
        logger.info("MT5 deal reconciliation background loop started (60s cadence).")
        while self._running:
            try:
                with self._get_db() as db:
                    reconcile_open_trades_with_mt5(db)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Reconciliation loop note: {e}")
            await asyncio.sleep(60.0)

    async def _countdown_broadcast_loop(self) -> None:
        """Broadcast live per-pair countdown telemetry every second on /ws/live."""
        while self._running:
            try:
                now = now_utc()
                countdowns = []

                for sym, sched in list(self.pair_schedules.items()):
                    next_scan = sched.get("next_scan_utc", now)
                    secs_rem = max(0, int((next_scan - now).total_seconds()))
                    countdowns.append({
                        "symbol": sym,
                        "seconds_remaining": secs_rem,
                        "interval_sec": sched.get("interval_sec", 60),
                        "last_scan_ist": sched.get("last_scan_ist", "Never"),
                        "status": sched.get("status", "WAITING"),
                        "last_decision": sched.get("last_decision", "NONE"),
                    })

                await manager.broadcast({
                    "type": "INTERVAL_COUNTDOWNS",
                    "timestamp_ist": to_ist_str(now),
                    "countdowns": countdowns,
                })
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in countdown broadcast loop: {e}")

            await asyncio.sleep(1.0)

    async def _scheduler_loop(self) -> None:
        """Continuously inspect per-pair scan timers and trigger analysis."""
        while self._running:
            try:
                now = now_utc()
                with self._get_db() as db:
                    self._sync_pair_schedules(db)
                    st = db.query(AppSettings).filter_by(id=1).first()
                    exec_mode = st.execution_mode if st else "MONITOR"
                    active_acc = st.active_account_type if st else "DEMO"

                    if exec_mode == "AUTO":
                        await self._monitor_pending_limit_orders(db, active_acc)

                    # Automated Daily Cache Hygiene Check
                    if getattr(st, "cache_auto_daily_enabled", True):
                        purge_hr = getattr(st, "cache_daily_purge_hour_utc", 0)
                        purge_min = getattr(st, "cache_daily_purge_minute_utc", 5)
                        last_cl = getattr(st, "cache_last_cleared_at_utc", None)
                        if last_cl is not None and last_cl.tzinfo is None:
                            last_cl = last_cl.replace(tzinfo=timezone.utc)
                        should_purge = False
                        if now.hour == purge_hr and now.minute >= purge_min:
                            if last_cl is None or (now - last_cl).total_seconds() > 72000:
                                should_purge = True
                        if should_purge:
                            cache_manager.purge_stale_entries(reason="SCHEDULED_DAILY_PURGE", db=db)

                if exec_mode == "HALTED":
                    for sched in self.pair_schedules.values():
                        sched["status"] = "HALTED"
                    await asyncio.sleep(2.0)
                    continue

                for sym, sched in list(self.pair_schedules.items()):
                    if now >= sched.get("next_scan_utc", now):
                        sched["status"] = "ANALYZING"
                        # Run scan for this pair
                        asyncio.create_task(self.execute_pair_scan(sym))
                        # Reset next scan time
                        interval = sched.get("interval_sec", 60)
                        sched["next_scan_utc"] = now + asyncio.timedelta(seconds=interval) if hasattr(asyncio, "timedelta") else now + (now_utc() - now)
                        from datetime import timedelta
                        sched["next_scan_utc"] = now + timedelta(seconds=interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")

            await asyncio.sleep(1.0)

    async def _monitor_pending_limit_orders(self, db: Session, active_account: str) -> None:
        """Monitor resting pending limit orders: detect broker fills, cancel if structure invalidated, or expire."""
        try:
            pending_trades = (
                db.query(TradeLedger)
                .filter_by(account_type=active_account.upper(), status="PENDING")
                .all()
            )
            if not pending_trades:
                return

            if not mt5_connector.is_connected:
                return

            import MetaTrader5 as mt5

            for trade in pending_trades:
                try:
                    order_ticket = trade.order_ticket or trade.position_id
                    sym = trade.symbol
                    clean_sym = sym.rstrip("#")
                    candidates = [sym, clean_sym, f"{clean_sym}#"]
                    actual_sym = None
                    tick = None

                    for s in candidates:
                        inf = mt5.symbol_info(s)
                        if inf is not None:
                            actual_sym = s
                            tick = mt5.symbol_info_tick(s)
                            break

                    if not actual_sym or not tick:
                        continue

                    # Check if order is still resting in MT5 pending orders
                    mt5_orders = mt5.orders_get(ticket=order_ticket)
                    if mt5_orders and len(mt5_orders) > 0:
                        sl_val = float(trade.sl)
                        direction = trade.direction
                        invalidated = False

                        if direction == "BUY" and sl_val > 0 and tick.bid <= sl_val:
                            invalidated = True
                        elif direction == "SELL" and sl_val > 0 and tick.ask >= sl_val:
                            invalidated = True

                        if invalidated:
                            logger.info(
                                f"Invalidating resting {direction} limit #{order_ticket} on {sym}: "
                                f"price breached SL {sl_val} before fill."
                            )
                            del_req = {
                                "action": mt5.TRADE_ACTION_REMOVE,
                                "order": order_ticket,
                            }
                            mt5.order_send(del_req)
                            trade.status = "CANCELLED"
                            trade.exit_reason = "STRUCTURE_INVALIDATED_BEFORE_FILL"
                            db.commit()
                            try:
                                from backend.app.ai_brain.telegram_notifier import telegram_notifier
                                asyncio.create_task(
                                    telegram_notifier.notify_limit_filled_or_expired(
                                        ticket=order_ticket,
                                        symbol=sym,
                                        direction=direction,
                                        action="CANCELLED",
                                        reason="Structure invalidated before fill (price reached SL)",
                                    )
                                )
                            except Exception as te:
                                logger.debug(f"Limit cancelled Telegram alert note: {te}")
                            continue
                    else:
                        # Order not in pending orders: check if it became an open position
                        positions = mt5.positions_get(ticket=order_ticket)
                        if positions and len(positions) > 0:
                            pos = positions[0]
                            trade.status = "OPEN"
                            trade.position_id = pos.ticket
                            trade.entry_price = Decimal(str(pos.price_open))
                            trade.opened_at_utc = now_utc()
                            db.commit()
                            logger.info(f"Resting limit #{order_ticket} filled on broker at {pos.price_open}! Position OPEN.")
                            await manager.broadcast({
                                "type": "POSITION_OPENED",
                                "trade_id": trade.id,
                                "symbol": sym,
                                "ticket": pos.ticket,
                                "direction": trade.direction,
                                "lots": float(trade.lots),
                                "entry_price": float(pos.price_open),
                                "sl": float(trade.sl),
                                "tp2": float(trade.tp2),
                            })
                            try:
                                from backend.app.ai_brain.telegram_notifier import telegram_notifier
                                asyncio.create_task(
                                    telegram_notifier.notify_limit_filled_or_expired(
                                        ticket=pos.ticket,
                                        symbol=sym,
                                        direction=trade.direction,
                                        action="FILLED",
                                        fill_price=float(pos.price_open),
                                        lots=float(trade.lots),
                                        sl=float(trade.sl),
                                        tp1=float(trade.tp1 or 0.0),
                                        tp2=float(trade.tp2 or 0.0),
                                    )
                                )
                            except Exception as te:
                                logger.debug(f"Limit filled Telegram alert note: {te}")
                        else:
                            # Not found in orders or positions: expired or canceled on terminal
                            trade.status = "CANCELLED"
                            trade.exit_reason = "EXPIRED_OR_CANCELLED"
                            db.commit()
                            try:
                                from backend.app.ai_brain.telegram_notifier import telegram_notifier
                                asyncio.create_task(
                                    telegram_notifier.notify_limit_filled_or_expired(
                                        ticket=order_ticket,
                                        symbol=sym,
                                        direction=trade.direction,
                                        action="EXPIRED",
                                        reason="Expired or cancelled on MT5 terminal",
                                    )
                                )
                            except Exception as te:
                                logger.debug(f"Limit expired Telegram alert note: {te}")
                except Exception as ex:
                    logger.debug(f"Error monitoring pending order #{trade.id}: {ex}")
        except Exception as e:
            logger.debug(f"Pending limit monitor exception: {e}")

    def _check_symbol_open_position_lock(self, symbol: str, db: Session) -> Tuple[bool, str]:
        """
        Strict 1-Position-Per-Symbol Lock (Zero Stacking, Zero Self-Hedging):
        Normalizes base_sym = symbol.rstrip('#').upper().
        Checks live MT5 positions & orders PLUS MySQL TradeLedger records.
        If >= 1 open position or pending order exists in ANY mode (SCALP, SWING, MANUAL)
        or ANY direction (BUY, SELL), blocks new entries immediately.
        """
        base_sym = symbol.rstrip("#").upper()

        # 1. Check live MT5 broker positions & pending orders
        if mt5_connector.is_connected:
            try:
                import MetaTrader5 as mt5
                live_positions = mt5.positions_get()
                if live_positions:
                    for p in live_positions:
                        if p.symbol.rstrip("#").upper() == base_sym:
                            return (
                                False,
                                f"SKIP_POSITION_ALREADY_OPEN: Live MT5 position #{p.ticket} already active on {base_sym} ({p.type} {p.volume} lots)",
                            )

                live_orders = mt5.orders_get()
                if live_orders:
                    for o in live_orders:
                        if o.symbol.rstrip("#").upper() == base_sym:
                            return (
                                False,
                                f"SKIP_POSITION_ALREADY_OPEN: Resting MT5 order #{o.ticket} already exists on {base_sym}",
                            )
            except Exception as e:
                logger.debug(f"MT5 position check error: {e}")

        # 2. Check MySQL TradeLedger
        active_db_trades = (
            db.query(TradeLedger)
            .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1", "PENDING"]))
            .all()
        )
        for t in active_db_trades:
            if t.symbol.rstrip("#").upper() == base_sym:
                return (
                    False,
                    f"SKIP_POSITION_ALREADY_OPEN: Trade #{t.id} ({t.status} {t.direction} {t.mode}) already recorded on {base_sym}",
                )

        return True, "OK"

    def _check_candle_close_gate(
        self,
        symbol: str,
        mode: str,
        execution_tf: str,
        candle_time: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """
        Candle-Close Execution Gate:
        Ensures a symbol is evaluated only once per newly closed candle on its assigned execution_tf,
        preventing intra-minute spam / tick chasing.
        """
        base_sym = symbol.rstrip("#").upper()
        key = (base_sym, mode.upper(), execution_tf.upper())

        if candle_time is None:
            return True, "OK"

        last_time = self._last_scanned_candle_time.get(key)
        if last_time is not None and candle_time <= last_time:
            return (
                False,
                f"SKIP_CANDLE_ALREADY_SCANNED: Candle {candle_time} already scanned on {base_sym} {execution_tf}",
            )

        return True, "OK"

    def _check_post_exit_cooldown(self, symbol: str, mode: str, db: Session) -> Tuple[bool, str]:
        """
        Mandatory Post-Exit Cooldown Timer:
        If last closed trade exit_reason was SL_HIT, MANUAL_MOBILE, MANUAL_TERMINAL, STOP_OUT, or MARGIN_STOP_OUT:
        - 30 minutes for SCALP
        - 240 minutes (4 hours) for SWING
        """
        base_sym = symbol.rstrip("#").upper()
        cooldown_sec = 1800 if mode.upper() == "SCALP" else 14400

        recent_trades = (
            db.query(TradeLedger)
            .filter(TradeLedger.status == "CLOSED")
            .order_by(TradeLedger.closed_at_utc.desc())
            .limit(50)
            .all()
        )

        last_for_sym = None
        for t in recent_trades:
            if t.symbol.rstrip("#").upper() == base_sym:
                last_for_sym = t
                break

        if last_for_sym and last_for_sym.closed_at_utc:
            reason = last_for_sym.exit_reason or ""
            if reason in ("SL_HIT", "MANUAL_MOBILE", "MANUAL_TERMINAL", "STOP_OUT", "MARGIN_STOP_OUT"):
                closed_at = last_for_sym.closed_at_utc
                if closed_at.tzinfo is None:
                    closed_at = closed_at.replace(tzinfo=timezone.utc)
                now = now_utc()
                elapsed = (now - closed_at).total_seconds()
                if elapsed < cooldown_sec:
                    rem_sec = int(cooldown_sec - elapsed)
                    return (
                        False,
                        f"COOLDOWN_ACTIVE: {base_sym} in cooldown after {reason} ({rem_sec}s remaining for {mode})",
                    )

        return True, "OK"

    def _check_portfolio_and_correlation_caps(
        self,
        symbol: str,
        direction: str,
        proposed_risk_pct: float,
        db: Session,
    ) -> Tuple[bool, str]:
        """
        Enforce Portfolio Ceilings & Cross-Asset Correlation Buckets:
        1. Max 5 concurrent global open positions.
        2. Max 2.50% total open portfolio risk.
        3. Energy Crude: Max 1 open position total across OILCash# and BRENTCash#.
        4. Precious Metals: Max 1 open position in the same direction across GOLD# and SILVER#.
        5. Crypto: Max 2 open positions total across BTCUSD#, ETHUSD#, SOLUSD#, XRPUSD#.
        6. FX Currency Exposure: Max 2 directionally identical exposures to any single currency.
        """
        base_sym = symbol.rstrip("#").upper()

        # Query all open trades in DB
        open_trades = (
            db.query(TradeLedger)
            .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1", "PENDING"]))
            .all()
        )

        # Global position ceiling
        if len(open_trades) >= 5:
            return False, f"PORTFOLIO_CAP_REACHED: Global limit of 5 concurrent open positions reached ({len(open_trades)} active)"

        # Global risk ceiling
        total_open_risk = sum(0.50 for _ in open_trades)  # standard 0.50% baseline risk per trade
        if total_open_risk + proposed_risk_pct > 2.50 + 1e-4:
            return (
                False,
                f"PORTFOLIO_RISK_CAP_BREACHED: Open risk ({total_open_risk:.2f}%) + proposed ({proposed_risk_pct:.2f}%) exceeds 2.50% ceiling",
            )

        # 1. Crude Energy Group
        if base_sym in CRUDE_SYMBOLS:
            for t in open_trades:
                if t.symbol.rstrip("#").upper() in CRUDE_SYMBOLS:
                    return (
                        False,
                        f"CORRELATION_LIMIT_ENERGY: Max 1 open position across OILCash# and BRENTCash# (Trade #{t.id} {t.symbol} is active)",
                    )

        # 2. Precious Metals Group
        if base_sym in METALS_SYMBOLS:
            for t in open_trades:
                if t.symbol.rstrip("#").upper() in METALS_SYMBOLS and t.direction.upper() == direction.upper():
                    return (
                        False,
                        f"CORRELATION_LIMIT_METALS: Max 1 open position in same direction ({direction}) for Metals (Trade #{t.id} {t.symbol} {t.direction} is active)",
                    )

        # 3. Crypto Group
        if base_sym in CRYPTO_SYMBOLS:
            crypto_count = sum(1 for t in open_trades if t.symbol.rstrip("#").upper() in CRYPTO_SYMBOLS)
            if crypto_count >= 2:
                return (
                    False,
                    f"CORRELATION_LIMIT_CRYPTO: Max 2 concurrent open positions for Crypto ({crypto_count} active)",
                )

        # 4. FX Currency Exposure
        proposed_fx = decompose_fx_symbol(symbol, direction)
        if proposed_fx:
            _, _, p_long, p_short = proposed_fx
            long_counts: Dict[str, int] = {c: 0 for c in FX_CURRENCIES}
            short_counts: Dict[str, int] = {c: 0 for c in FX_CURRENCIES}

            for t in open_trades:
                decomp = decompose_fx_symbol(t.symbol, t.direction)
                if decomp:
                    _, _, t_long, t_short = decomp
                    if t_long in long_counts:
                        long_counts[t_long] += 1
                    if t_short in short_counts:
                        short_counts[t_short] += 1

            if long_counts.get(p_long, 0) >= 2:
                return (
                    False,
                    f"FX_CORRELATION_LIMIT: Adding {direction} {symbol} creates >2 Long exposures for {p_long} ({long_counts[p_long]} active)",
                )
            if short_counts.get(p_short, 0) >= 2:
                return (
                    False,
                    f"FX_CORRELATION_LIMIT: Adding {direction} {symbol} creates >2 Short exposures for {p_short} ({short_counts[p_short]} active)",
                )

        return True, "OK"

    def _check_daily_drawdown_circuit_breaker(self, db: Session) -> Tuple[bool, str]:
        """
        Daily Drawdown Circuit Breaker:
        If (today_realized_pnl + floating_pnl) <= -3.0% of starting equity OR
        4 consecutive SL_HIT trades occur today:
        Pause autonomous entries until 00:05 UTC next day.
        """
        now = now_utc()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check existing active trip
        if self.circuit_breaker_tripped:
            if self.circuit_breaker_until_utc and now < self.circuit_breaker_until_utc:
                return (
                    False,
                    f"CIRCUIT_BREAKER_ACTIVE: Tripped until {to_ist_str(self.circuit_breaker_until_utc)}: {self.circuit_breaker_reason}",
                )
            else:
                self.circuit_breaker_tripped = False
                self.circuit_breaker_reason = None
                self.circuit_breaker_until_utc = None

        # Fetch closed trades today
        today_closed = (
            db.query(TradeLedger)
            .filter(
                TradeLedger.status == "CLOSED",
                TradeLedger.closed_at_utc >= today_start,
            )
            .all()
        )
        realized_today = sum(float(t.net_pnl or 0.0) for t in today_closed)

        floating_today = 0.0
        if mt5_connector.is_connected:
            try:
                import MetaTrader5 as mt5
                pos = mt5.positions_get()
                if pos:
                    floating_today = sum(float(p.profit + p.swap) for p in pos)
            except Exception:
                pass

        net_today = realized_today + floating_today

        profile = db.query(MT5AccountProfile).filter_by(account_type="DEMO").first()
        baseline_equity = float(profile.last_equity) if profile and profile.last_equity > 0 else 10000.0

        if baseline_equity > 0:
            dd_pct = (net_today / baseline_equity) * 100.0
            if dd_pct <= -3.0:
                self.circuit_breaker_tripped = True
                self.circuit_breaker_until_utc = today_start + timedelta(days=1, minutes=5)
                self.circuit_breaker_reason = f"Daily drawdown {dd_pct:.2f}% breached -3.00% equity limit"
                logger.critical(f"Daily Drawdown Circuit Breaker Tripped! {self.circuit_breaker_reason}")
                try:
                    from backend.app.ai_brain.telegram_notifier import telegram_notifier
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        telegram_notifier.notify_system_guardrail(
                            alert_type="CIRCUIT_BREAKER",
                            title="Daily Drawdown Circuit Breaker Tripped",
                            details=self.circuit_breaker_reason,
                            action_taken="Autonomous Order Entry Paused until 00:05 UTC next day",
                            severity="CRITICAL",
                        )
                    )
                except Exception as te:
                    logger.debug(f"Circuit breaker Telegram alert note: {te}")
                return False, f"CIRCUIT_BREAKER_TRIPPED: {self.circuit_breaker_reason}"

        # 4 consecutive SL_HIT check
        consecutive_sl = 0
        sorted_today = sorted(
            today_closed,
            key=lambda t: t.closed_at_utc or today_start,
            reverse=True,
        )
        for t in sorted_today:
            if t.exit_reason == "SL_HIT":
                consecutive_sl += 1
            else:
                break

        if consecutive_sl >= 4:
            self.circuit_breaker_tripped = True
            self.circuit_breaker_until_utc = today_start + timedelta(days=1, minutes=5)
            self.circuit_breaker_reason = f"4 consecutive SL_HIT trades today ({consecutive_sl} in a row)"
            logger.critical(f"Daily Drawdown Circuit Breaker Tripped! {self.circuit_breaker_reason}")
            try:
                from backend.app.ai_brain.telegram_notifier import telegram_notifier
                loop = asyncio.get_running_loop()
                loop.create_task(
                    telegram_notifier.notify_system_guardrail(
                        alert_type="CIRCUIT_BREAKER",
                        title="4 Consecutive SL Hit Breaker Tripped",
                        details=self.circuit_breaker_reason,
                        action_taken="Autonomous Order Entry Paused until 00:05 UTC next day",
                        severity="CRITICAL",
                    )
                )
            except Exception as te:
                logger.debug(f"Circuit breaker Telegram alert note: {te}")
            return False, f"CIRCUIT_BREAKER_TRIPPED: {self.circuit_breaker_reason}"

        return True, "OK"

    def get_guardrail_status(self, db: Session) -> Dict[str, Any]:
        """Telemetry snapshot for frontend risk guardrails bar."""
        now = now_utc()
        open_trades = (
            db.query(TradeLedger)
            .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1", "PENDING"]))
            .all()
        )
        open_count = len(open_trades)
        total_risk_pct = round(open_count * 0.50, 2)

        # Check circuit breaker
        is_tripped = bool(self.circuit_breaker_tripped and self.circuit_breaker_until_utc and now < self.circuit_breaker_until_utc)

        # Check active cooldowns
        cooldowns: Dict[str, str] = {}
        for sym in list(self.pair_schedules.keys()):
            ok_scalp, msg_scalp = self._check_post_exit_cooldown(sym, "SCALP", db)
            if not ok_scalp:
                cooldowns[sym] = msg_scalp

        return {
            "open_positions_count": open_count,
            "max_positions_limit": 5,
            "open_risk_pct": total_risk_pct,
            "max_risk_limit_pct": 2.50,
            "circuit_breaker": {
                "status": "PAUSED" if is_tripped else "HEALTHY",
                "tripped": is_tripped,
                "reason": self.circuit_breaker_reason if is_tripped else None,
                "until_ist": to_ist_str(self.circuit_breaker_until_utc) if is_tripped and self.circuit_breaker_until_utc else None,
            },
            "cooldowns": cooldowns,
        }

    async def execute_pair_scan(
        self,
        symbol: str,
        custom_timeframe_dfs: Optional[Dict[str, Any]] = None,
        account_type: Optional[str] = None,
        db: Optional[Session] = None,
        bypass_circuit_breaker: bool = False,
    ) -> Optional[GeminiAnalysisReport]:
        """
        Execute full supervisory scan for a pair:
        1. Compile MarketPacket
        2. Analyze with GeminiSupervisor
        3. Route through Execution Mode (AUTO, COPILOT, MONITOR, HALTED)
        """
        now = now_utc()
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            active_account = account_type or (st.active_account_type if st else "DEMO")
            exec_mode = st.execution_mode if st else "MONITOR"

            pair = db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == symbol) | (TradingPairBot.symbol == f"{symbol}#")
            ).first()

            profile = db.query(MT5AccountProfile).filter_by(account_type=active_account).first()
            equity = float(profile.last_equity) if profile and profile.last_equity > 0 else 1000.0

            if not pair:
                logger.warning(f"Scan aborted: Pair '{symbol}' not found in database.")
                return None

            check_mode = "SCALP" if pair.scalp_enabled else "SWING"

            # Weekend Check: Skip FOREX and COMMODITIES when markets are closed, keep CRYPTO 24/7
            if not is_symbol_trading_open(symbol, pair.asset_class, now):
                if symbol in self.pair_schedules:
                    self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                    self.pair_schedules[symbol]["last_decision"] = "WEEKEND_CLOSED"
                    self.pair_schedules[symbol]["status"] = "WEEKEND_CLOSED"
                logger.debug(f"Skipping scan for {symbol} ({pair.asset_class}): Market closed for weekend.")
                return None

            # 1. Strict 1-Position-Per-Symbol Lock (Zero Stacking, Zero Self-Hedging)
            if not bypass_circuit_breaker:
                lock_ok, lock_msg = self._check_symbol_open_position_lock(symbol, db)
                if not lock_ok:
                    if symbol in self.pair_schedules:
                        self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                        self.pair_schedules[symbol]["last_decision"] = "SKIP_POSITION_ALREADY_OPEN"
                        self.pair_schedules[symbol]["status"] = "POS_OPEN"
                    logger.info(f"Skipping scan for {symbol}: {lock_msg}")
                    return None

            # 2. Daily Drawdown Circuit Breaker
            if not bypass_circuit_breaker:
                cb_ok, cb_msg = self._check_daily_drawdown_circuit_breaker(db)
                if not cb_ok:
                    if symbol in self.pair_schedules:
                        self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                        self.pair_schedules[symbol]["last_decision"] = "CIRCUIT_BREAKER_ACTIVE"
                        self.pair_schedules[symbol]["status"] = "CIRCUIT_BREAKER"
                    logger.warning(f"Scan aborted for {symbol}: {cb_msg}")
                    return None

            # 3. Post-Exit Cooldown Gate
            if not bypass_circuit_breaker:
                cd_ok, cd_msg = self._check_post_exit_cooldown(symbol, check_mode, db)
                if not cd_ok:
                    if symbol in self.pair_schedules:
                        self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                        self.pair_schedules[symbol]["last_decision"] = "COOLDOWN_ACTIVE"
                        self.pair_schedules[symbol]["status"] = "COOLDOWN"
                    logger.info(f"Skipping scan for {symbol}: {cd_msg}")
                    return None

            # 4. Compile MarketPacket
            packet = await market_packet_compiler.compile_market_packet(
                symbol=symbol,
                timeframe_dfs=custom_timeframe_dfs,
                db=db,
            )

            # 5. Candle-Close Execution Gate (Zero Intra-Minute Spam)
            exec_tf = getattr(st, "scalp_execution_tf", "M5") if pair.scalp_enabled else getattr(st, "swing_execution_tf", "H1")
            candle_time = None
            if custom_timeframe_dfs and exec_tf in custom_timeframe_dfs:
                c_df = custom_timeframe_dfs[exec_tf]
                if len(c_df) >= 2:
                    candle_time = c_df.iloc[-2]["time"]
            elif packet and hasattr(packet, "timestamp_utc"):
                candle_time = packet.timestamp_utc

            if not bypass_circuit_breaker:
                gate_ok, gate_msg = self._check_candle_close_gate(symbol, check_mode, exec_tf, candle_time)
                if not gate_ok:
                    if symbol in self.pair_schedules:
                        self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                        self.pair_schedules[symbol]["last_decision"] = "SKIP_CANDLE_ALREADY_SCANNED"
                        self.pair_schedules[symbol]["status"] = "WAITING_CANDLE"
                    logger.debug(f"Skipping scan for {symbol}: {gate_msg}")
                    return None

            if candle_time is not None:
                self._last_scanned_candle_time[(symbol.rstrip("#").upper(), check_mode.upper(), exec_tf.upper())] = candle_time

            # Release DB connection before async network calls (Gemini AI inference)
            if close_db and db:
                db.close()
                db = None

            # 6. Analyze with GeminiSupervisor
            report = await gemini_supervisor.analyze_pair(
                packet=packet,
                account_type=active_account,
                db=None,
            )

            # Check for upcoming setup radar alert (Pre-Trigger Setup Radar)
            if report and (report.upcoming_setup_json or getattr(report, "readiness_pct", 0) >= 60 or report.decision == "PRE_TRIGGER"):
                try:
                    import json
                    from backend.app.ai_brain.telegram_notifier import telegram_notifier
                    up = json.loads(report.upcoming_setup_json) if report.upcoming_setup_json else {}
                    t_zone = float(up.get("trigger_zone_price") or report.entry_price or (packet.bid if packet else 0.0))
                    inv_zone = float(up.get("invalidation_price") or report.stop_loss or (t_zone * 0.99))
                    if t_zone > 0:
                        t_cond = up.get("trigger_condition") or "Confluence zone tap & M5 FVG close"
                        readiness = getattr(report, "readiness_pct", 0) or up.get("readiness_pct") or 75
                        conf_factors = up.get("confluence_factors") or []
                        t_style = up.get("setup_mode") or up.get("trade_style") or ("SCALP" if "SCALP" in report.decision else "SWING")
                        dir_val = "BUY" if inv_zone < t_zone else "SELL"
                        if up.get("watch_bias"):
                            if "BULLISH" in up["watch_bias"]:
                                dir_val = "BUY"
                            elif "BEARISH" in up["watch_bias"]:
                                dir_val = "SELL"
                        asyncio.create_task(
                            telegram_notifier.notify_pre_trigger_setup(
                                symbol=symbol,
                                trade_style=t_style,
                                direction=dir_val,
                                trigger_zone_price=t_zone,
                                invalidation_price=inv_zone,
                                trigger_condition=t_cond,
                                readiness_pct=int(readiness),
                                confluence_factors=conf_factors,
                                thesis=report.thesis_text,
                            )
                        )
                except Exception as te:
                    logger.debug(f"Pre-trigger radar alert dispatch note for {symbol}: {te}")

            # Update in-memory schedule tracker
            if symbol in self.pair_schedules:
                self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                self.pair_schedules[symbol]["last_decision"] = report.decision
                self.pair_schedules[symbol]["status"] = "IDLE"

            # 3. Route according to Execution Mode
            if exec_mode == "HALTED" or report.decision == "WAIT":
                return report

            # Re-acquire DB connection for post-analysis routing
            if close_db and db is None:
                db = self._get_db()

            if exec_mode == "MONITOR":
                logger.info(f"MONITOR Mode: Recorded analysis report #{report.id} for {symbol}. No broker orders.")
                r = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
                if r:
                    r.execution_status = "MONITOR_ONLY"
                    db.commit()
                return report

            # Candidate trade approved for execution or staging
            if report.decision.startswith("EXECUTE"):
                mode = "SCALP" if "SCALP" in report.decision else "SWING"
                magic = 1001 if mode == "SCALP" else 2001

                entry = float(report.entry_price) if report.entry_price else packet.bid
                sl = float(report.stop_loss) if report.stop_loss else 0.0
                tp1 = float(report.tp1) if report.tp1 else 0.0
                tp2 = float(report.tp2) if report.tp2 else 0.0
                direction = "BUY" if sl < entry else "SELL"

                risk_pct = float(pair.risk_pct_scalp if mode == "SCALP" else pair.risk_pct_swing)

                # Re-verify strict 1-position lock right before execution
                lock_ok, lock_msg = self._check_symbol_open_position_lock(symbol, db)
                if not lock_ok:
                    logger.warning(f"Final pre-execution lock rejected setup on {symbol}: {lock_msg}")
                    r = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
                    if r:
                        r.execution_status = "POSITION_ALREADY_OPEN"
                        r.thesis_text = f"Rejected: {lock_msg}"
                        db.commit()
                    return report

                # Correlation Group & Portfolio Cap Check
                cap_ok, cap_msg = self._check_portfolio_and_correlation_caps(
                    symbol=symbol,
                    direction=direction,
                    proposed_risk_pct=risk_pct,
                    db=db,
                )
                if not cap_ok:
                    logger.warning(f"Portfolio/Correlation cap rejected setup on {symbol}: {cap_msg}")
                    r = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
                    if r:
                        r.execution_status = "CAP_REJECTED"
                        r.thesis_text = f"Rejected: {cap_msg}"
                        db.commit()
                    return report

                # Hard Pre-Order Math & Geometry Validation
                digits = int(pair.digits) if pair and pair.digits else 2
                spread_price = (packet.ask - packet.bid) if (packet and packet.ask > 0 and packet.bid > 0) else (packet.spread_points * (0.01 if digits == 2 else 0.0001))
                atr14 = 0.0
                if packet:
                    m15 = packet.timeframe_breakdown.get("M15") if hasattr(packet, "timeframe_breakdown") else None
                    if m15 and isinstance(m15, dict) and m15.get("atr14"):
                        atr14 = float(m15["atr14"])
                if atr14 <= 0:
                    atr14 = 3.0 if "GOLD" in symbol.upper() else (300.0 if "BTC" in symbol.upper() else 0.0015)

                geom_ok, geom_msg = risk_engine.validate_trade_geometry_and_rr(
                    direction=direction,
                    entry=entry,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    mode=mode,
                    current_spread_price=spread_price,
                    ltf_atr_14=atr14,
                )
                if not geom_ok:
                    logger.warning(f"Geometry/RR gate rejected setup on {symbol}: {geom_msg}")
                    r = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
                    if r:
                        r.execution_status = "GEOMETRY_REJECTED"
                        r.thesis_text = f"Rejected: {geom_msg}"
                        db.commit()
                    return report

                # Risk Engine Gating
                ok, lots, risk_msg = risk_engine.calculate_lot_size(
                    equity=equity,
                    risk_pct=risk_pct,
                    entry_price=entry,
                    sl_price=sl,
                    contract_size=float(pair.contract_size),
                    tick_size=float(pair.tick_size),
                    tick_value=float(pair.tick_value),
                    volume_min=float(pair.volume_min),
                    volume_step=float(pair.volume_step),
                )

                if not ok:
                    logger.warning(f"Risk gate rejected setup on {symbol}: {risk_msg}")
                    r = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
                    if r:
                        r.execution_status = "RISK_REJECTED"
                        r.thesis_text = f"Rejected by Risk Engine: {risk_msg}"
                        db.commit()
                    return report

                # Spread filter check
                spread_ok, spread_msg = risk_engine.check_spread_filter(packet.spread_points, pair.max_spread_points)
                if not spread_ok:
                    logger.warning(f"Spread filter rejected setup on {symbol}: {spread_msg}")
                    return report

                # Zero naked trade validation
                naked_ok, naked_msg = risk_engine.validate_zero_naked_trade(sl, entry, direction)
                if not naked_ok:
                    logger.warning(f"Zero naked trade guard rejected setup on {symbol}: {naked_msg}")
                    return report

                # Check LIVE Learned Rules Gate
                from backend.app.ai_brain.forensic_learner import forensic_learner
                is_rule_blocked, rule_block_reason = forensic_learner.check_live_rules_filter(symbol, mode, direction, db)
                if is_rule_blocked:
                    logger.info(f"Setup on {symbol} blocked by learned rule: {rule_block_reason}")
                    report.execution_status = "BLOCKED_BY_LEARNED_RULE"
                    report.thesis_text = f"{report.thesis_text or ''} | [RULE FILTER] {rule_block_reason}"
                    db.commit()
                    return report

                # Route by mode: Strictly Autonomous AUTO Execution (Market or Resting Limit)
                await self._dispatch_auto_order(
                    report=report,
                    symbol=symbol,
                    mode=mode,
                    magic=magic,
                    direction=direction,
                    lots=lots,
                    entry=entry,
                    sl=sl,
                    tp1=tp1,
                    tp2=tp2,
                    account_type=active_account,
                    packet=packet,
                    db=db,
                )

            return report
        finally:
            if close_db and db:
                db.close()

    async def _stage_copilot_setup(
        self,
        report: GeminiAnalysisReport,
        symbol: str,
        mode: str,
        magic: int,
        direction: str,
        lots: float,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        account_type: str,
        db: Optional[Session] = None,
    ) -> None:
        """Stage a PLANNED setup in TradeLedger (for manual/backward-compatible workflows)."""
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        try:
            trade = TradeLedger(
                account_type=account_type.upper(),
                position_id=0,
                order_ticket=0,
                symbol=symbol,
                magic_number=magic,
                mode=mode,
                direction=direction,
                status="PLANNED",
                entry_order_type="MARKET",
                lots=Decimal(str(lots)),
                initial_lots=Decimal(str(lots)),
                entry_price=Decimal(str(entry)),
                sl=Decimal(str(sl)),
                tp1=Decimal(str(tp1)),
                tp2=Decimal(str(tp2)),
                opened_at_utc=now_utc(),
                ai_analysis_summary=report.thesis_text,
            )
            db.add(trade)
            db.commit()
        finally:
            if close_db and db:
                db.close()

    async def _dispatch_auto_order(
        self,
        report: GeminiAnalysisReport,
        symbol: str,
        mode: str,
        magic: int,
        direction: str,
        lots: float,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        account_type: str,
        packet: Optional[MarketPacket] = None,
        db: Optional[Session] = None,
        is_limit_order: bool = False,
    ) -> None:
        """
        Autonomous execution engine:
        1. Checks Anti-Chase Drift Guard: if live market price has drifted > 0.15 * ATR(14) away
           from entry, converts execution into a resting BUY_LIMIT / SELL_LIMIT at entry.
        2. Otherwise executes direct BUY_MARKET / SELL_MARKET via TRADE_ACTION_DEAL.
        3. Saves TradeLedger with entry_order_type ("MARKET" vs "LIMIT"), detected_patterns_json,
           hard SL, and dual TP.
        """
        logger.info(f"AUTO Mode: Processing {direction} order for {symbol} ({lots} lots)...")

        # Resolve equity and risk_pct
        equity = 1000.0
        risk_pct = 0.50
        if db:
            prof = db.query(MT5AccountProfile).filter_by(account_type=account_type.upper()).first()
            if prof and prof.last_equity > 0:
                equity = float(prof.last_equity)
            p_bot = db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == symbol) | (TradingPairBot.symbol == f"{symbol}#")
            ).first()
            if p_bot:
                risk_pct = float(p_bot.risk_pct_scalp if mode == "SCALP" else p_bot.risk_pct_swing)

        ticket = 0
        fill_price = entry
        final_sl = float(sl)
        final_tp = float(tp2)

        # Calculate ATR(14) from packet for drift detection
        atr14 = 0.0
        patterns_json = "[]"
        if packet:
            m15 = packet.timeframe_breakdown.get("M15") if hasattr(packet, "timeframe_breakdown") else None
            if m15 and isinstance(m15, dict) and m15.get("atr14"):
                atr14 = float(m15["atr14"])
            if hasattr(packet, "detected_patterns") and packet.detected_patterns:
                patterns_json = json.dumps(packet.detected_patterns)

        if atr14 <= 0:
            atr14 = 3.0 if "GOLD" in symbol.upper() else (300.0 if "BTC" in symbol.upper() else 0.0015)

        # Attempt live MT5 broker order send if connected
        if mt5_connector.is_connected:
            import MetaTrader5 as mt5

            def _send_order():
                nonlocal is_limit_order
                clean_sym = symbol.rstrip("#")
                candidates = [symbol, clean_sym, f"{clean_sym}#"]
                actual_sym = None
                info = None
                tick = None

                for s in candidates:
                    inf = mt5.symbol_info(s)
                    if inf is not None:
                        actual_sym = s
                        info = inf
                        mt5.symbol_select(s, True)
                        tick = mt5.symbol_info_tick(s)
                        break

                if not actual_sym or not tick or (tick.ask <= 0 and tick.bid <= 0):
                    return None, f"Could not obtain live quotes for '{symbol}' from MT5 broker."

                digits = getattr(info, "digits", 2)
                p = tick.ask if direction == "BUY" else tick.bid

                # Smart Anti-Chase Drift Guard
                drift = abs(p - entry)
                max_drift = 0.15 * atr14
                if drift > max_drift:
                    is_limit_order = True
                    logger.info(
                        f"Smart Anti-Chase Guard: Price drifted {drift:.4f} > {max_drift:.4f} (0.15*ATR) on {symbol}. "
                        f"Converting from MARKET to resting LIMIT order at {entry}."
                    )

                filling = mt5.ORDER_FILLING_IOC
                if info and hasattr(info, "filling_mode"):
                    fm = info.filling_mode
                    if fm & 2:
                        filling = mt5.ORDER_FILLING_IOC
                    elif fm & 1:
                        filling = mt5.ORDER_FILLING_FOK
                    else:
                        filling = mt5.ORDER_FILLING_RETURN

                cur_sl = float(sl)
                cur_tp = float(tp2)

                if direction == "BUY":
                    if cur_sl >= tick.bid or (cur_tp > 0 and cur_tp <= tick.ask):
                        return None, f"Order rejected: BUY prices invalid against live quote (Bid {tick.bid}, Ask {tick.ask}, SL {cur_sl}, TP {cur_tp})"
                else:
                    if cur_sl <= tick.ask or (cur_tp > 0 and cur_tp >= tick.bid):
                        return None, f"Order rejected: SELL prices invalid against live quote (Bid {tick.bid}, Ask {tick.ask}, SL {cur_sl}, TP {cur_tp})"

                # Universal MT5 tick_value lot sizing & $50 dollar risk cap
                tick_size = getattr(info, "trade_tick_size", 0.01)
                tick_val = getattr(info, "trade_tick_value", 1.0)
                vol_min = getattr(info, "volume_min", 0.01)
                vol_max = getattr(info, "volume_max", 100.0)
                vol_step = getattr(info, "volume_step", 0.01)

                sl_dist = abs(entry - cur_sl)
                ticks_at_risk = (sl_dist / tick_size) if tick_size > 0 else 1.0
                loss_per_lot = ticks_at_risk * tick_val

                cash_risk = min(float(equity) * (float(risk_pct) / 100.0), 50.0)

                if loss_per_lot > 0:
                    raw_lots = cash_risk / loss_per_lot
                    step_dec = Decimal(str(vol_step))
                    lots_dec = (Decimal(str(raw_lots)) // step_dec) * step_dec
                    calc_lots = float(lots_dec)
                    if calc_lots < vol_min:
                        min_risk = loss_per_lot * vol_min
                        if min_risk <= cash_risk * 1.5:
                            vol = vol_min
                        else:
                            return None, f"Min lot {vol_min} risk (${min_risk:.2f}) exceeds 1.5x risk budget (${cash_risk:.2f})"
                    else:
                        vol = min(calc_lots, vol_max)
                else:
                    vol = vol_min

                if is_limit_order:
                    # Place Pending Limit Order
                    order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
                    req = {
                        "action": mt5.TRADE_ACTION_PENDING,
                        "symbol": actual_sym,
                        "volume": float(vol),
                        "type": order_type,
                        "price": round(entry, digits),
                        "sl": round(cur_sl, digits),
                        "tp": round(cur_tp, digits),
                        "type_filling": filling,
                        "magic": magic,
                        "comment": f"AUTO_LIMIT_{mode}",
                    }
                else:
                    # Place Market Order
                    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
                    req = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": actual_sym,
                        "volume": float(vol),
                        "type": order_type,
                        "price": round(p, digits),
                        "sl": round(cur_sl, digits),
                        "tp": round(cur_tp, digits),
                        "deviation": 20,
                        "type_filling": filling,
                        "magic": magic,
                        "comment": f"AUTO_{mode}",
                    }

                try:
                    res = mt5.order_send(req)
                    return res, cur_sl, cur_tp
                except Exception as ex:
                    return None, f"MT5 order_send exception: {str(ex)}"

            try:
                outcome = await mt5_actor.run_position(_send_order)
            except Exception as e:
                logger.error(f"AUTO Order actor exception: {e}", exc_info=True)
                outcome = None

            if isinstance(outcome, tuple) and len(outcome) == 3:
                res, final_sl, final_tp = outcome
                if res and res.retcode == 10009:  # TRADE_RETCODE_DONE
                    ticket = res.order
                    fill_price = res.price if not is_limit_order else entry
                else:
                    err_msg = res.comment if res else "Order send failed"
                    logger.error(f"AUTO Order failed on broker: {err_msg} (retcode: {getattr(res, 'retcode', 'N/A')})")
                    return
            else:
                logger.error(f"AUTO Order failed on broker: {outcome}")
                return
        else:
            ticket = int(datetime.now(timezone.utc).timestamp() * 1000) % 100000000

        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        status_val = "PENDING" if is_limit_order else "OPEN"
        entry_type_val = "LIMIT" if is_limit_order else "MARKET"

        try:
            trade = TradeLedger(
                account_type=account_type.upper(),
                position_id=ticket,
                order_ticket=ticket,
                symbol=symbol,
                magic_number=magic,
                mode=mode,
                direction=direction,
                status=status_val,
                entry_order_type=entry_type_val,
                detected_patterns_json=patterns_json,
                lots=Decimal(str(lots)),
                initial_lots=Decimal(str(lots)),
                entry_price=Decimal(str(fill_price)),
                sl=Decimal(str(final_sl)),
                tp1=Decimal(str(tp1)),
                tp2=Decimal(str(final_tp)),
                opened_at_utc=now_utc(),
                ai_analysis_summary=report.thesis_text,
            )
            db.add(trade)

            rep = db.query(GeminiAnalysisReport).filter_by(id=report.id).first()
            if rep:
                rep.execution_status = "EXECUTED" if not is_limit_order else "PENDING_LIMIT"

            db.commit()
            trade_id = trade.id
        finally:
            if close_db and db:
                db.close()

        # Broadcast WebSocket event
        if is_limit_order:
            await manager.broadcast({
                "type": "PENDING_ORDER_PLACED",
                "trade_id": trade_id,
                "order_ticket": ticket,
                "symbol": symbol,
                "direction": direction,
                "order_type": f"{direction}_LIMIT",
                "price": fill_price,
                "sl": final_sl,
                "tp2": final_tp,
                "lots": lots,
                "timestamp_ist": to_ist_str(now_utc()),
            })
        else:
            await manager.broadcast({
                "type": "POSITION_OPENED",
                "trade_id": trade_id,
                "symbol": symbol,
                "ticket": ticket,
                "direction": direction,
                "lots": lots,
                "entry_price": fill_price,
                "sl": final_sl,
                "tp2": final_tp,
            })

        # Send Rich Institutional Telegram Execution Alert
        try:
            from backend.app.ai_brain.telegram_notifier import telegram_notifier
            cash_r = float(equity * (risk_pct / 100.0))
            conf_val = float(report.confidence) if (report and report.confidence is not None) else 0.85
            ai_text = report.thesis_text if report else "Algorithmic confluence trigger verified."
            spread_pts = packet.spread_points if packet else 12
            asyncio.create_task(
                telegram_notifier.notify_trade_executed(
                    ticket=ticket,
                    symbol=symbol,
                    mode=mode,
                    direction=direction,
                    lots=lots,
                    entry_price=fill_price,
                    sl=final_sl,
                    tp1=tp1,
                    tp2=final_tp,
                    cash_risk=cash_r,
                    risk_pct=risk_pct,
                    spread_points=spread_pts,
                    is_limit_order=is_limit_order,
                    order_type_str=f"{direction}_LIMIT" if is_limit_order else None,
                    confidence=conf_val,
                    ai_summary=ai_text,
                )
            )
        except Exception as te:
            logger.debug(f"Execution Telegram alert note: {te}")

    async def approve_copilot_setup(self, trade_id: int, db: Optional[Session] = None) -> Tuple[bool, str]:
        """User 1-click execution of a staged PLANNED setup."""
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        try:
            trade = db.query(TradeLedger).filter_by(id=trade_id, status="PLANNED").first()
            if not trade:
                return False, f"Staged setup #{trade_id} not found or already processed."

            sym = trade.symbol
            # Check 1-position lock before approving copilot setup
            lock_ok, lock_msg = self._check_symbol_open_position_lock(sym, db)
            if not lock_ok:
                return False, f"Copilot execution blocked: {lock_msg}"

            lots = float(trade.lots)
            direction = trade.direction
            planned_entry = float(trade.entry_price)
            planned_sl = float(trade.sl)
            planned_tp2 = float(trade.tp2)
            magic = trade.magic_number
            mode = trade.mode
            acc_type = trade.account_type
        finally:
            if close_db and db:
                db.close()

        ticket = 0
        fill_price = planned_entry
        final_sl = planned_sl
        final_tp = planned_tp2

        if mt5_connector.is_connected:
            import MetaTrader5 as mt5

            def _send():
                clean_sym = sym.rstrip("#")
                candidates = [sym, clean_sym, f"{clean_sym}#"]
                actual_sym = None
                info = None
                tick = None

                for s in candidates:
                    inf = mt5.symbol_info(s)
                    if inf is not None:
                        actual_sym = s
                        info = inf
                        mt5.symbol_select(s, True)
                        tick = mt5.symbol_info_tick(s)
                        break

                if not actual_sym or not tick or (tick.ask <= 0 and tick.bid <= 0):
                    return None, f"Could not obtain live quotes for '{sym}' from MT5 broker."

                p = tick.ask if direction == "BUY" else tick.bid
                order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

                filling = mt5.ORDER_FILLING_IOC
                if info and hasattr(info, "filling_mode"):
                    fm = info.filling_mode
                    if fm & 2:
                        filling = mt5.ORDER_FILLING_IOC
                    elif fm & 1:
                        filling = mt5.ORDER_FILLING_FOK
                    else:
                        filling = mt5.ORDER_FILLING_RETURN

                digits = getattr(info, "digits", 2)
                cur_sl = planned_sl
                cur_tp = planned_tp2

                if direction == "BUY":
                    is_valid = (cur_sl < tick.bid) and (cur_tp == 0 or cur_tp > tick.ask)
                    if not is_valid:
                        sl_dist = abs(planned_entry - planned_sl) if (planned_entry > 0 and planned_sl > 0) else (p * 0.005)
                        tp_dist = abs(planned_tp2 - planned_entry) if (planned_entry > 0 and planned_tp2 > 0) else (p * 0.015)
                        cur_sl = round(tick.bid - sl_dist, digits)
                        cur_tp = round(tick.ask + tp_dist, digits)
                else:
                    is_valid = (cur_sl > tick.ask) and (cur_tp == 0 or cur_tp < tick.bid)
                    if not is_valid:
                        sl_dist = abs(planned_sl - planned_entry) if (planned_entry > 0 and planned_sl > 0) else (p * 0.005)
                        tp_dist = abs(planned_entry - planned_tp2) if (planned_entry > 0 and planned_tp2 > 0) else (p * 0.015)
                        cur_sl = round(tick.ask + sl_dist, digits)
                        cur_tp = round(tick.bid - tp_dist, digits)

                vol = float(lots)
                if hasattr(info, "volume_min") and vol < info.volume_min:
                    vol = info.volume_min
                if hasattr(info, "volume_step") and info.volume_step > 0:
                    vol = round(vol / info.volume_step) * info.volume_step

                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": actual_sym,
                    "volume": float(vol),
                    "type": order_type,
                    "price": round(p, digits),
                    "sl": round(cur_sl, digits),
                    "tp": round(cur_tp, digits),
                    "deviation": 20,
                    "type_filling": filling,
                    "magic": magic,
                    "comment": f"COPILOT_{mode}",
                }
                try:
                    res = mt5.order_send(req)
                    return res, cur_sl, cur_tp
                except Exception as ex:
                    return None, f"MT5 order_send exception: {str(ex)}"

            try:
                outcome = await mt5_actor.run_position(_send)
            except Exception as e:
                logger.error(f"Error in mt5_actor executing Copilot trade: {e}", exc_info=True)
                return False, f"MT5 execution exception: {str(e)}"

            if isinstance(outcome, tuple) and len(outcome) == 3:
                res, final_sl, final_tp = outcome
                if res and res.retcode == 10009:  # TRADE_RETCODE_DONE
                    ticket = res.order
                    fill_price = res.price
                else:
                    comment = res.comment if res else "Unknown broker error"
                    code = res.retcode if res else "N/A"
                    return False, f"Broker rejected order: {comment} (retcode: {code})"
            elif isinstance(outcome, tuple) and len(outcome) == 2:
                _, err_msg = outcome
                return False, f"Broker rejected order: {err_msg}"
            else:
                return False, "Failed to execute order on MT5 broker."
        else:
            ticket = int(datetime.now(timezone.utc).timestamp() * 1000) % 100000000

        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        try:
            t = db.query(TradeLedger).filter_by(id=trade_id).first()
            if t:
                t.position_id = ticket
                t.order_ticket = ticket
                t.status = "OPEN"
                t.entry_price = Decimal(str(fill_price))
                t.sl = Decimal(str(final_sl))
                t.tp2 = Decimal(str(final_tp))
                t.opened_at_utc = now_utc()
                db.commit()
        finally:
            if close_db and db:
                db.close()

        # Broadcast POSITION_OPENED to all UI clients via WebSocket
        try:
            await manager.broadcast({
                "type": "POSITION_OPENED",
                "trade_id": trade_id,
                "symbol": sym,
                "ticket": ticket,
                "direction": direction,
                "lots": lots,
                "entry_price": fill_price,
                "sl": final_sl,
                "tp2": final_tp,
            })
        except Exception as e:
            logger.warning(f"Could not broadcast POSITION_OPENED: {e}")

        # Send Telegram Execution Alert for Copilot Trade
        try:
            from backend.app.ai_brain.telegram_notifier import telegram_notifier
            tp1_val = float(trade.tp1 or fill_price)
            cash_r = float(lots * abs(fill_price - final_sl) * 100.0) if final_sl else 50.0
            asyncio.create_task(
                telegram_notifier.notify_trade_executed(
                    ticket=ticket,
                    symbol=sym,
                    mode=trade.mode or "SWING",
                    direction=direction,
                    lots=lots,
                    entry_price=fill_price,
                    sl=final_sl,
                    tp1=tp1_val,
                    tp2=final_tp,
                    cash_risk=cash_r,
                    risk_pct=0.50,
                    spread_points=12,
                    confidence=0.90,
                    ai_summary="Copilot manual execution confirmed by operator.",
                )
            )
        except Exception as te:
            logger.debug(f"Copilot Telegram alert note: {te}")

        return True, f"Successfully executed Copilot trade #{ticket} on {sym} ({lots} lots at {fill_price})."

    async def reject_copilot_setup(self, trade_id: int, db: Optional[Session] = None) -> Tuple[bool, str]:
        """User dismissal of a staged PLANNED setup."""
        close_db = False
        if db is None:
            db = self._get_db()
            close_db = True

        try:
            trade = db.query(TradeLedger).filter_by(id=trade_id, status="PLANNED").first()
            if not trade:
                return False, f"Staged setup #{trade_id} not found."
            trade.status = "REJECTED"
            db.commit()
        finally:
            if close_db and db:
                db.close()

        return True, f"Dismissed Copilot setup #{trade_id}."

    def update_intervals(
        self,
        global_interval_sec: Optional[int] = None,
        pair_intervals: Optional[Dict[str, int]] = None,
    ) -> None:
        """Update scan intervals in MySQL and reset in-memory countdown timers."""
        with self._get_db() as db:
            if global_interval_sec and global_interval_sec > 0:
                st = db.query(AppSettings).filter_by(id=1).first()
                if st:
                    st.global_scan_interval_sec = global_interval_sec

            if pair_intervals:
                for sym, val in pair_intervals.items():
                    p = db.query(TradingPairBot).filter(
                        (TradingPairBot.symbol == sym) | (TradingPairBot.symbol == f"{sym}#")
                    ).first()
                    if p:
                        p.scan_interval_sec = val

            db.commit()
            self._sync_pair_schedules(db)

        # Reset next scan time immediately
        now = now_utc()
        for sym, sched in self.pair_schedules.items():
            sched["next_scan_utc"] = now


scheduler = LiveIntervalScheduler()
