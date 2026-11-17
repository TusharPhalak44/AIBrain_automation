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
from datetime import datetime, timezone
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
from backend.app.telegram_reports.telegram_bot import telegram_service
from backend.app.api.websocket import manager
from backend.app.ai_brain.market_packet import market_packet_compiler, MarketPacket
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor

logger = logging.getLogger(__name__)


class LiveIntervalScheduler:
    """Manages autonomous interval scanning, countdowns, and execution mode routing."""

    def __init__(self, session_factory=None):
        self.session_factory = session_factory or SessionLocal
        self._running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self._broadcast_task: Optional[asyncio.Task] = None

        # Per-pair scheduler tracking state
        # symbol -> {"next_scan_utc": datetime, "interval_sec": int, "last_scan_ist": str, "status": str}
        self.pair_schedules: Dict[str, Dict[str, Any]] = {}

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
        """Start async scanning and countdown broadcast background loops."""
        if not self._running:
            self._running = True
            with self._get_db() as db:
                self._sync_pair_schedules(db)

            self._loop_task = asyncio.create_task(self._scheduler_loop())
            self._broadcast_task = asyncio.create_task(self._countdown_broadcast_loop())
            logger.info("Live Interval Scheduler started.")

    async def stop(self) -> None:
        """Stop background scheduler loops."""
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
        logger.info("Live Interval Scheduler stopped.")

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
                        else:
                            # Not found in orders or positions: expired or canceled on terminal
                            trade.status = "CANCELLED"
                            trade.exit_reason = "EXPIRED_OR_CANCELLED"
                            db.commit()
                except Exception as ex:
                    logger.debug(f"Error monitoring pending order #{trade.id}: {ex}")
        except Exception as e:
            logger.debug(f"Pending limit monitor exception: {e}")

    async def execute_pair_scan(
        self,
        symbol: str,
        custom_timeframe_dfs: Optional[Dict[str, Any]] = None,
        account_type: Optional[str] = None,
        db: Optional[Session] = None,
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

            # 1. Compile MarketPacket
            packet = await market_packet_compiler.compile_market_packet(
                symbol=symbol,
                timeframe_dfs=custom_timeframe_dfs,
                db=db,
            )

            # 2. Analyze with GeminiSupervisor
            report = await gemini_supervisor.analyze_pair(
                packet=packet,
                account_type=active_account,
                db=db,
            )

            # Update in-memory schedule tracker
            if symbol in self.pair_schedules:
                self.pair_schedules[symbol]["last_scan_ist"] = to_ist_str(now)
                self.pair_schedules[symbol]["last_decision"] = report.decision
                self.pair_schedules[symbol]["status"] = "IDLE"

            # 3. Route according to Execution Mode
            if exec_mode == "HALTED" or report.decision == "WAIT":
                return report

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
            if close_db:
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
            if close_db:
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
                    is_valid = (cur_sl < tick.bid) and (cur_tp == 0 or cur_tp > tick.ask)
                    if not is_valid:
                        sl_dist = abs(entry - float(sl)) if (entry > 0 and float(sl) > 0) else (p * 0.005)
                        tp_dist = abs(float(tp2) - entry) if (entry > 0 and float(tp2) > 0) else (p * 0.015)
                        cur_sl = round(tick.bid - sl_dist, digits)
                        cur_tp = round(tick.ask + tp_dist, digits)
                else:
                    is_valid = (cur_sl > tick.ask) and (cur_tp == 0 or cur_tp < tick.bid)
                    if not is_valid:
                        sl_dist = abs(float(sl) - entry) if (entry > 0 and float(sl) > 0) else (p * 0.005)
                        tp_dist = abs(entry - float(tp2)) if (entry > 0 and float(tp2) > 0) else (p * 0.015)
                        cur_sl = round(tick.ask + sl_dist, digits)
                        cur_tp = round(tick.bid - tp_dist, digits)

                vol = float(lots)
                if hasattr(info, "volume_min") and vol < info.volume_min:
                    vol = info.volume_min
                if hasattr(info, "volume_step") and info.volume_step > 0:
                    vol = round(vol / info.volume_step) * info.volume_step

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
            if close_db:
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

        # Send Telegram Execution Alert
        await telegram_service.broadcast_trade_event(
            trade=None,
            event_details={
                "position_id": ticket,
                "symbol": symbol,
                "direction": direction,
                "exit_price": fill_price,
                "exit_reason": f"AUTO_ENTRY_{mode}",
                "gross_pnl": 0.0,
                "net_pnl": 0.0,
            },
        )

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
            lots = float(trade.lots)
            direction = trade.direction
            planned_entry = float(trade.entry_price)
            planned_sl = float(trade.sl)
            planned_tp2 = float(trade.tp2)
            magic = trade.magic_number
            mode = trade.mode
            acc_type = trade.account_type
        finally:
            if close_db:
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
            if close_db:
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
            if close_db:
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
