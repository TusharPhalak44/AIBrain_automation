"""Active Trade Protection & Dynamic Position Management Engine.

Runs every 15 seconds to enforce:
1. Auto-Breakeven at +1.0R: Moves stop-loss to Entry + (spread + 0.05 * SL_distance) so a +1R winner never reverses to a loss.
2. 50% Partial Scale-Out at +1.5R: Takes 50% off table, sets status = 'PARTIAL_TP1', and trails remaining volume behind +1.0R structure toward TP2.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.session import SessionLocal
from backend.app.db.models import TradeLedger, TradingPairBot
from backend.app.mt5_bridge.connector import mt5_connector
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel
from backend.app.api.websocket import manager

logger = logging.getLogger(__name__)


class PositionManager:
    """Monitors live active positions and executes institutional trade protection rules."""

    def __init__(self):
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def manage_active_positions(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """
        Inspect all OPEN / PARTIAL_TP1 positions in MT5 and apply:
        1. Auto-Breakeven (+1.0R)
        2. Partial scale-out + trailing stop (+1.5R)
        """
        import MetaTrader5 as mt5

        if not mt5_connector.is_connected:
            return []

        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        actions_taken = []

        try:
            open_trades = (
                db.query(TradeLedger)
                .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1"]))
                .all()
            )

            if not open_trades:
                return []

            def _inspect_and_modify():
                if not mt5.terminal_info():
                    return []

                live_positions = mt5.positions_get()
                if not live_positions:
                    return []

                pos_map = {p.ticket: p for p in live_positions}
                modifications = []

                for trade in open_trades:
                    pos = pos_map.get(trade.position_id)
                    if not pos:
                        continue

                    entry_p = float(pos.price_open)
                    cur_p = float(pos.price_current)
                    cur_sl = float(pos.sl)
                    cur_tp = float(pos.tp)
                    initial_sl = float(trade.sl)
                    initial_sl_dist = abs(entry_p - initial_sl) if initial_sl > 0 else 0.0

                    if initial_sl_dist <= 0:
                        continue

                    sym = pos.symbol
                    info = mt5.symbol_info(sym)
                    digits = getattr(info, "digits", 2)
                    vol_min = getattr(info, "volume_min", 0.01)
                    vol_step = getattr(info, "volume_step", 0.01)

                    tick = mt5.symbol_info_tick(sym)
                    spread_price = (tick.ask - tick.bid) if tick else (0.01 if digits == 2 else 0.0001)

                    is_buy = trade.direction == "BUY"
                    current_move = (cur_p - entry_p) if is_buy else (entry_p - cur_p)
                    current_r = current_move / initial_sl_dist

                    # -------------------------------------------------------------
                    # RULE 1: Auto-Breakeven at +1.0R
                    # -------------------------------------------------------------
                    be_buffer = spread_price + (0.05 * initial_sl_dist)
                    target_be_sl = round(entry_p + be_buffer if is_buy else entry_p - be_buffer, digits)

                    should_move_be = False
                    if current_r >= 1.0:
                        if is_buy and (cur_sl < target_be_sl):
                            should_move_be = True
                        elif not is_buy and (cur_sl == 0.0 or cur_sl > target_be_sl):
                            should_move_be = True

                    if should_move_be:
                        req = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "position": pos.ticket,
                            "symbol": sym,
                            "sl": target_be_sl,
                            "tp": cur_tp,
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == 10009:
                            modifications.append({
                                "action": "AUTO_BREAKEVEN",
                                "trade_id": trade.id,
                                "ticket": pos.ticket,
                                "symbol": sym,
                                "new_sl": target_be_sl,
                                "current_r": round(current_r, 2),
                            })
                            cur_sl = target_be_sl

                    # -------------------------------------------------------------
                    # RULE 2: 60% Partial Scale-Out + Trail at +1.5R (Micro-Lot Safe)
                    # -------------------------------------------------------------
                    if current_r >= 1.5 and trade.status == "OPEN":
                        # Micro-Lot Tier: cannot split min volume (e.g. 0.01 lot) -> lock +0.50R SL
                        if pos.volume <= vol_min:
                            lock_buffer = 0.50 * initial_sl_dist
                            lock_sl = round(entry_p + lock_buffer if is_buy else entry_p - lock_buffer, digits)
                            should_lock = False
                            if is_buy and cur_sl < lock_sl:
                                should_lock = True
                            elif not is_buy and (cur_sl == 0.0 or cur_sl > lock_sl):
                                should_lock = True

                            if should_lock:
                                sl_req = {
                                    "action": mt5.TRADE_ACTION_SLTP,
                                    "position": pos.ticket,
                                    "symbol": sym,
                                    "sl": lock_sl,
                                    "tp": cur_tp,
                                }
                                res_lock = mt5.order_send(sl_req)
                                if res_lock and res_lock.retcode == 10009:
                                    modifications.append({
                                        "action": "MICRO_LOT_PROFIT_LOCK",
                                        "trade_id": trade.id,
                                        "ticket": pos.ticket,
                                        "symbol": sym,
                                        "new_sl": lock_sl,
                                        "current_r": round(current_r, 2),
                                    })
                        else:
                            # Standard Tier: Close 60% volume snapped cleanly to volume_step
                            target_close = round((pos.volume * 0.60) / vol_step) * vol_step
                            target_close = round(target_close, 2)
                            rem_vol = round(pos.volume - target_close, 2)
                            if rem_vol < vol_min:
                                target_close = round(pos.volume - vol_min, 2)

                            if target_close >= vol_min:
                                filling = mt5.ORDER_FILLING_IOC
                                if info and hasattr(info, "filling_mode"):
                                    fm = info.filling_mode
                                    if fm & 2:
                                        filling = mt5.ORDER_FILLING_IOC
                                    elif fm & 1:
                                        filling = mt5.ORDER_FILLING_FOK
                                    else:
                                        filling = mt5.ORDER_FILLING_RETURN

                                close_action = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
                                close_price = tick.bid if is_buy else tick.ask

                                close_req = {
                                    "action": mt5.TRADE_ACTION_DEAL,
                                    "position": pos.ticket,
                                    "symbol": sym,
                                    "volume": float(target_close),
                                    "type": close_action,
                                    "price": round(close_price, digits),
                                    "deviation": 20,
                                    "magic": pos.magic,
                                    "type_filling": filling,
                                    "comment": "PARTIAL_TP1_60PCT",
                                }
                                c_res = mt5.order_send(close_req)
                                if c_res and c_res.retcode == 10009:
                                    # Trail stop behind +1.0R structure
                                    trail_buffer = 1.0 * initial_sl_dist
                                    trail_sl = round(entry_p + trail_buffer if is_buy else entry_p - trail_buffer, digits)

                                    sl_req = {
                                        "action": mt5.TRADE_ACTION_SLTP,
                                        "position": pos.ticket,
                                        "symbol": sym,
                                        "sl": trail_sl,
                                        "tp": cur_tp,
                                    }
                                    mt5.order_send(sl_req)

                                    modifications.append({
                                        "action": "PARTIAL_SCALE_OUT_60",
                                        "trade_id": trade.id,
                                        "ticket": pos.ticket,
                                        "symbol": sym,
                                        "volume_closed": float(target_close),
                                        "remaining_volume": float(round(pos.volume - target_close, 2)),
                                        "trailed_sl": trail_sl,
                                        "current_r": round(current_r, 2),
                                    })

                return modifications

            actions_taken = await mt5_actor.run_position(_inspect_and_modify)

            # Update DB for modified trades
            if actions_taken:
                for act in actions_taken:
                    tid = act.get("trade_id")
                    t_row = db.query(TradeLedger).filter_by(id=tid).first()
                    if not t_row:
                        continue

                    if act["action"] == "AUTO_BREAKEVEN":
                        t_row.sl = Decimal(str(act["new_sl"]))
                        logger.info(f"Auto-Breakeven executed for trade #{tid} ({act['symbol']}) at {act['new_sl']} (+{act['current_r']}R)")
                        await manager.broadcast({
                            "type": "SL_MOVED_BREAKEVEN",
                            "trade_id": tid,
                            "symbol": act["symbol"],
                            "ticket": act["ticket"],
                            "new_sl": act["new_sl"],
                            "current_r": act["current_r"],
                            "timestamp_ist": to_ist_str(now_utc()),
                        })
                        try:
                            from backend.app.ai_brain.telegram_notifier import telegram_notifier
                            asyncio.create_task(
                                telegram_notifier.notify_breakeven_locked(
                                    ticket=act["ticket"],
                                    symbol=act["symbol"],
                                    direction=t_row.direction,
                                    entry_price=float(t_row.entry_price),
                                    new_sl=float(act["new_sl"]),
                                    current_r=float(act.get("current_r", 1.0)),
                                    next_target=float(t_row.tp1 or t_row.tp2 or 0.0),
                                )
                            )
                        except Exception as te:
                            logger.debug(f"Breakeven Telegram alert note: {te}")
                    elif act["action"] == "MICRO_LOT_PROFIT_LOCK":
                        t_row.sl = Decimal(str(act["new_sl"]))
                        logger.info(f"Micro-lot +0.50R profit lock executed for trade #{tid} ({act['symbol']}) at {act['new_sl']}")
                        await manager.broadcast({
                            "type": "SL_MOVED_PROFIT_LOCK",
                            "trade_id": tid,
                            "symbol": act["symbol"],
                            "ticket": act["ticket"],
                            "new_sl": act["new_sl"],
                            "current_r": act["current_r"],
                            "timestamp_ist": to_ist_str(now_utc()),
                        })
                    elif act["action"] in ("PARTIAL_SCALE_OUT_50", "PARTIAL_SCALE_OUT_60"):
                        t_row.status = "PARTIAL_TP1"
                        t_row.lots = Decimal(str(act["remaining_volume"]))
                        t_row.sl = Decimal(str(act["trailed_sl"]))
                        logger.info(f"Partial TP1 scale-out executed for trade #{tid} ({act['symbol']}) at +{act['current_r']}R. Rem: {act['remaining_volume']} lots.")
                        await manager.broadcast({
                            "type": "PARTIAL_TP_EXECUTED",
                            "trade_id": tid,
                            "symbol": act["symbol"],
                            "ticket": act["ticket"],
                            "volume_closed": act["volume_closed"],
                            "remaining_volume": act["remaining_volume"],
                            "trailed_sl": act["trailed_sl"],
                            "current_r": act["current_r"],
                            "timestamp_ist": to_ist_str(now_utc()),
                        })
                        try:
                            from backend.app.ai_brain.telegram_notifier import telegram_notifier
                            # Estimate realized profit on banked volume
                            vol_closed = float(act["volume_closed"])
                            entry_f = float(t_row.entry_price)
                            # Current market price is approximately trailed_sl or entry + 1.5R
                            init_risk = abs(entry_f - float(t_row.sl)) if t_row.sl else 1.0
                            gain = 1.5 * init_risk
                            # Fallback approximate pnl = gain * volume * contract_size
                            spec = get_symbol_spec(act["symbol"]) if "get_symbol_spec" in globals() else None
                            c_size = spec.contract_size if spec else 100.0
                            realized_approx = round(gain * vol_closed * c_size, 2)
                            asyncio.create_task(
                                telegram_notifier.notify_partial_tp1(
                                    ticket=act["ticket"],
                                    symbol=act["symbol"],
                                    direction=t_row.direction,
                                    volume_closed=vol_closed,
                                    remaining_volume=float(act["remaining_volume"]),
                                    realized_pnl=realized_approx,
                                    trailed_sl=float(act["trailed_sl"]),
                                    tp2=float(t_row.tp2 or 0.0),
                                    current_r=float(act.get("current_r", 1.5)),
                                )
                            )
                        except Exception as te:
                            logger.debug(f"Partial TP1 Telegram alert note: {te}")

                db.commit()

            return actions_taken or []
        except Exception as e:
            logger.debug(f"Position manager check note: {e}")
            return []
        finally:
            if close_db:
                db.close()

    async def _position_management_loop(self) -> None:
        """Loop running manage_active_positions every 15 seconds."""
        logger.info("Active position protection loop started (15s cadence).")
        while self._running:
            try:
                await self.manage_active_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in position management loop: {e}")

            await asyncio.sleep(15.0)

    def start(self) -> None:
        """Start background protection loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._position_management_loop())

    def stop(self) -> None:
        """Stop background protection loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Active position protection loop stopped.")


position_manager = PositionManager()

