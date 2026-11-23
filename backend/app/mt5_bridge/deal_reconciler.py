"""Historical Deals Reconciler & Net PnL Accounting Service.

Groups MT5 closed deals by position_id, reconciles fees (spread, commission, swap),
updates TradeLedger, dispatches notifications, and spools offline if MySQL is unavailable.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, broker_epoch_to_utc, compute_broker_offset_sec
from backend.app.core.watchdog import watchdog
from backend.app.db.session import SessionLocal
from backend.app.db.models import TradeLedger
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel
from backend.app.mt5_bridge.connector import mt5_connector

logger = logging.getLogger(__name__)


def classify_exit_reason(
    reason_code: int,
    profit: float,
    comment: str = "",
    entry_price: float = 0.0,
    exit_price: float = 0.0,
    direction: str = "BUY",
) -> str:
    """Classify MT5 ENUM_DEAL_REASON into standard portal exit reason."""
    c_lower = (comment or "").lower()
    if "panic" in c_lower or "kill" in c_lower:
        return "KILL_SWITCH"

    # MT5 ENUM_DEAL_REASON mapping:
    # 0 = DEAL_REASON_CLIENT
    # 1 = DEAL_REASON_MOBILE
    # 2 = DEAL_REASON_WEB
    # 3 = DEAL_REASON_EXPERT
    # 4 = DEAL_REASON_SL
    # 5 = DEAL_REASON_TP
    # 6 = DEAL_REASON_SO
    if reason_code == 4 or "sl" in c_lower:
        if profit > 0.01:
            return "TRAIL_SL"
        if direction == "BUY" and exit_price > entry_price and entry_price > 0:
            return "TRAIL_SL"
        if direction == "SELL" and exit_price < entry_price and entry_price > 0:
            return "TRAIL_SL"
        return "SL_HIT"
    elif reason_code == 5 or "tp" in c_lower:
        return "TP_HIT"
    elif reason_code == 1:
        return "MANUAL_MOBILE"
    elif reason_code in (0, 2):
        return "MANUAL_TERMINAL"
    elif reason_code == 3:
        if "trail" in c_lower:
            return "TRAIL_SL"
        return "AUTO_RULE_EXIT"
    elif reason_code == 6:
        return "MARGIN_STOP_OUT"

    return "MANUAL_MOBILE"


def reconcile_open_trades_with_mt5(db: Optional[Session] = None) -> Dict[str, Any]:
    """
    Deterministic reconciliation between live MT5 positions and MySQL TradeLedger.
    
    1. Fetches all live MT5 positions.
    2. For every TradeLedger row with status in ('OPEN', 'PARTIAL_TP1'):
       If position_id is NO LONGER active in live MT5:
       - Query mt5.history_deals_get(position=position_id)
       - If closing deal located: backfill exact exit_price, gross_pnl, commission, swap,
         net_pnl, r_multiple, corrected closed_at_utc (without +2h offset), true exit_reason,
         and set status = 'CLOSED'.
       - If no closing deals exist in current account history (e.g. mobile close or disconnected session),
         mark status = 'CLOSED', exit_reason = 'MANUAL_MOBILE', exit_price = entry_price, closed_at_utc = now.
    """
    import MetaTrader5 as mt5

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        if not mt5.terminal_info():
            if not mt5.initialize():
                return {"status": "SKIPPED", "reason": "MT5 terminal offline", "reconciled_count": 0}

        # 1. Fetch live open positions from MT5
        live_positions = mt5.positions_get()
        live_pos_ids = {p.ticket for p in live_positions} if live_positions else set()

        # 2. Fetch all DB trades marked OPEN or PARTIAL_TP1
        open_db_trades = (
            db.query(TradeLedger)
            .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1"]))
            .all()
        )

        reconciled_trades = []
        offset_sec = compute_broker_offset_sec()

        for trade in open_db_trades:
            pos_id = trade.position_id
            if pos_id in live_pos_ids:
                # Still truly open on broker
                continue

            # Position is NO LONGER open on broker -> must reconcile and close
            deals = mt5.history_deals_get(position=pos_id)
            exit_deals = [d for d in deals if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_INOUT)] if deals else []

            if exit_deals:
                total_gross = sum(d.profit for d in deals)
                total_comm = sum(d.commission for d in deals)
                total_swap = sum(d.swap for d in deals)
                total_net = total_gross + total_comm + total_swap

                last_deal = exit_deals[-1]
                exit_price = float(last_deal.price)
                reason_code = getattr(last_deal, "reason", 0)
                comment = getattr(last_deal, "comment", "")

                exit_reason = classify_exit_reason(
                    reason_code=reason_code,
                    profit=total_gross,
                    comment=comment,
                    entry_price=float(trade.entry_price),
                    exit_price=exit_price,
                    direction=trade.direction,
                )

                closed_at = broker_epoch_to_utc(last_deal.time, offset_sec)
                opened = trade.opened_at_utc
                if opened and opened.tzinfo is None:
                    opened = opened.replace(tzinfo=timezone.utc)
                if opened and closed_at < opened:
                    closed_at = opened + timedelta(seconds=1)
                now = now_utc()
                if closed_at > now:
                    closed_at = now

                # R-multiple calculation
                initial_risk = abs(trade.entry_price - trade.sl) if trade.sl > 0 else Decimal("0")
                r_mult = Decimal("0.00")
                if initial_risk > 0:
                    gain_price = (exit_price - float(trade.entry_price)) if trade.direction == "BUY" else (float(trade.entry_price) - exit_price)
                    r_mult = Decimal(str(round(gain_price / float(initial_risk), 2)))

                trade.status = "CLOSED"
                trade.exit_price = Decimal(str(exit_price))
                trade.gross_pnl = Decimal(str(round(total_gross, 2)))
                trade.commission = Decimal(str(round(total_comm, 2)))
                trade.swap = Decimal(str(round(total_swap, 2)))
                trade.net_pnl = Decimal(str(round(total_net, 2)))
                trade.r_multiple = r_mult
                trade.exit_reason = exit_reason
                trade.closed_at_utc = closed_at

                reconciled_trades.append({
                    "id": trade.id,
                    "position_id": pos_id,
                    "symbol": trade.symbol,
                    "exit_price": exit_price,
                    "net_pnl": total_net,
                    "exit_reason": exit_reason,
                    "closed_at": closed_at.isoformat(),
                })
            else:
                # No closing deal found in history (e.g. from previous account session or mobile close)
                trade.status = "CLOSED"
                trade.exit_reason = "MANUAL_MOBILE"
                opened = trade.opened_at_utc
                if opened and opened.tzinfo is None:
                    opened = opened.replace(tzinfo=timezone.utc)
                now = now_utc()
                fallback_closed_at = opened + timedelta(minutes=15) if opened else now
                if fallback_closed_at > now:
                    fallback_closed_at = now
                trade.closed_at_utc = fallback_closed_at
                trade.exit_price = trade.entry_price
                trade.gross_pnl = Decimal("0.00")
                trade.commission = Decimal("0.00")
                trade.swap = Decimal("0.00")
                trade.net_pnl = Decimal("0.00")
                trade.r_multiple = Decimal("0.00")

                reconciled_trades.append({
                    "id": trade.id,
                    "position_id": pos_id,
                    "symbol": trade.symbol,
                    "exit_price": float(trade.entry_price),
                    "net_pnl": 0.0,
                    "exit_reason": "MANUAL_MOBILE",
                    "closed_at": fallback_closed_at.isoformat(),
                })

        db.commit()
        logger.info(f"reconcile_open_trades_with_mt5: successfully reconciled {len(reconciled_trades)} orphaned trades. Open remaining in DB: {len(live_pos_ids)}")

        # If multiple orphaned trades were reconciled (e.g. startup catchup), dispatch consolidated summary to avoid spam
        if len(reconciled_trades) > 1:
            try:
                from backend.app.ai_brain.telegram_notifier import telegram_notifier
                total_net = sum(t.get("net_pnl", 0.0) for t in reconciled_trades)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        telegram_notifier.notify_reconciliation_batch(
                            reconciled_count=len(reconciled_trades),
                            total_net_pnl=total_net,
                            open_remaining=len(live_pos_ids),
                        )
                    )
                except RuntimeError:
                    pass
            except Exception as te:
                logger.debug(f"Could not dispatch startup reconciliation Telegram summary: {te}")

        return {
            "status": "SUCCESS",
            "reconciled_count": len(reconciled_trades),
            "reconciled_trades": reconciled_trades,
            "open_remaining_count": len(live_pos_ids),
        }
    except Exception as e:
        logger.error(f"Error in reconcile_open_trades_with_mt5: {e}", exc_info=True)
        return {"status": "ERROR", "message": str(e), "reconciled_count": 0}
    finally:
        if close_db:
            db.close()


class DealReconciler:
    """Monitors MT5 deal history and reconciles closed trades with TradeLedger."""

    def __init__(self):
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.telegram_notifier: Optional[Any] = None

    async def reconcile_recent_deals(self, days: int = 7) -> List[Dict[str, Any]]:
        """Fetch closed deals from MT5 history and reconcile with MySQL TradeLedger."""
        import MetaTrader5 as mt5

        from_date = datetime.now(timezone.utc) - timedelta(days=days)
        to_date = datetime.now(timezone.utc) + timedelta(days=1)

        def _fetch():
            deals = mt5.history_deals_get(from_date, to_date)
            if deals is None:
                return []
            return [d._asdict() for d in deals]

        raw_deals = await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _fetch)
        if not raw_deals:
            return []

        # Group exit deals (ENTRY_OUT or ENTRY_INOUT) by position_id
        closed_groups: Dict[int, List[Dict[str, Any]]] = {}
        for d in raw_deals:
            # 1 = DEAL_ENTRY_OUT, 2 = DEAL_ENTRY_INOUT
            if d.get("entry") in (1, 2):
                pos_id = d.get("position_id")
                if pos_id:
                    closed_groups.setdefault(pos_id, []).append(d)

        reconciled = []
        for pos_id, deals in closed_groups.items():
            res = self.process_position_deals(pos_id, deals)
            if res:
                reconciled.append(res)

        return reconciled

    def process_position_deals(self, pos_id: int, deals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Aggregate multiple partial exit deals for a single position_id."""
        if not deals:
            return None

        total_gross = sum(d.get("profit", 0.0) for d in deals)
        total_comm = sum(d.get("commission", 0.0) for d in deals)
        total_swap = sum(d.get("swap", 0.0) for d in deals)
        total_net = total_gross + total_comm + total_swap

        last_deal = deals[-1]
        exit_price = last_deal.get("price", 0.0)
        symbol = last_deal.get("symbol", "")
        magic = last_deal.get("magic", 0)
        reason_code = last_deal.get("reason", 0)
        comment = last_deal.get("comment", "")
        close_time_epoch = last_deal.get("time", int(now_utc().timestamp()))
        closed_at = broker_epoch_to_utc(close_time_epoch)
        now = now_utc()
        if closed_at > now:
            closed_at = now

        # We will determine initial entry from trade record in DB
        exit_reason = classify_exit_reason(
            reason_code=reason_code,
            profit=total_gross,
            comment=comment,
            exit_price=exit_price,
        )

        deal_summary = {
            "position_id": pos_id,
            "symbol": symbol,
            "magic_number": magic,
            "exit_price": exit_price,
            "gross_pnl": total_gross,
            "commission": total_comm,
            "swap": total_swap,
            "net_pnl": total_net,
            "exit_reason": exit_reason,
            "closed_at_utc": closed_at.isoformat(),
        }

        # If MySQL is unhealthy, spool offline record to disk immediately!
        if not watchdog.db_healthy:
            watchdog.spool_closed_deal(deal_summary)
            return deal_summary

        # Update MySQL TradeLedger
        try:
            with SessionLocal() as db:
                trade = db.query(TradeLedger).filter_by(position_id=pos_id).first()
                if trade:
                    # Update exit reason with full trade context
                    exit_reason = classify_exit_reason(
                        reason_code=reason_code,
                        profit=total_gross,
                        comment=comment,
                        entry_price=float(trade.entry_price),
                        exit_price=exit_price,
                        direction=trade.direction,
                    )
                    deal_summary["exit_reason"] = exit_reason

                    if trade.status != "CLOSED":
                        trade.status = "CLOSED"
                        trade.exit_price = Decimal(str(exit_price))
                        trade.gross_pnl = Decimal(str(round(total_gross, 2)))
                        trade.commission = Decimal(str(round(total_comm, 2)))
                        trade.swap = Decimal(str(round(total_swap, 2)))
                        trade.net_pnl = Decimal(str(round(total_net, 2)))
                        trade.exit_reason = exit_reason

                        opened = trade.opened_at_utc
                        if opened and opened.tzinfo is None:
                            opened = opened.replace(tzinfo=timezone.utc)
                        if opened and closed_at < opened:
                            closed_at = opened + timedelta(seconds=1)
                        trade.closed_at_utc = closed_at

                        # Calculate R-Multiple if initial risk is known
                        initial_risk = abs(trade.entry_price - trade.sl) if trade.sl > 0 else Decimal("0")
                        if initial_risk > 0:
                            gain_price = (exit_price - float(trade.entry_price)) if trade.direction == "BUY" else (float(trade.entry_price) - exit_price)
                            r_mult = gain_price / float(initial_risk)
                            trade.r_multiple = Decimal(str(round(r_mult, 2)))

                        db.commit()
                        logger.info(f"Reconciled trade #{pos_id}: Net PnL ${total_net:.2f} ({exit_reason})")

                        # Trigger closed-loop pattern learning & SL-hit postmortem hooks
                        try:
                            from backend.app.ai_brain.forensic_learner import forensic_learner
                            forensic_learner.update_pattern_memory_on_trade_close(trade.id, db)
                            if exit_reason == "SL_HIT":
                                forensic_learner.run_sl_hit_postmortem(trade.id, db)
                        except Exception as fe:
                            logger.warning(f"Error updating pattern memory or running SL postmortem for trade #{trade.id}: {fe}")

                        # Dispatch Telegram alert if notifier configured
                        if self.telegram_notifier:
                            asyncio.create_task(
                                self.telegram_notifier(trade, deal_summary)
                            )
                else:
                    # External or manual trade not previously recorded
                    new_trade = TradeLedger(
                        account_type="DEMO",
                        position_id=pos_id,
                        order_ticket=last_deal.get("order", pos_id),
                        symbol=symbol,
                        magic_number=magic,
                        mode="SCALP" if magic == 1001 else ("SWING" if magic == 2001 else "MANUAL"),
                        direction="BUY" if last_deal.get("type") == 0 else "SELL",
                        status="CLOSED",
                        lots=Decimal(str(last_deal.get("volume", 0.01))),
                        initial_lots=Decimal(str(last_deal.get("volume", 0.01))),
                        entry_price=Decimal(str(exit_price)),
                        sl=Decimal("0.0"),
                        tp1=Decimal("0.0"),
                        tp2=Decimal("0.0"),
                        exit_price=Decimal(str(exit_price)),
                        gross_pnl=Decimal(str(round(total_gross, 2))),
                        commission=Decimal(str(round(total_comm, 2))),
                        swap=Decimal(str(round(total_swap, 2))),
                        net_pnl=Decimal(str(round(total_net, 2))),
                        exit_reason=exit_reason,
                        opened_at_utc=closed_at,
                        closed_at_utc=closed_at,
                    )
                    db.add(new_trade)
                    db.commit()

        except Exception as e:
            logger.error(f"Failed to commit reconciled trade #{pos_id} to MySQL: {e}")
            watchdog.spool_closed_deal(deal_summary)

        return deal_summary

    async def reconciliation_loop(self) -> None:
        """Periodic background reconciliation loop (every 10 seconds)."""
        logger.info("Deal reconciler background loop started.")
        while self._running:
            try:
                await self.reconcile_recent_deals(days=3)
            except Exception as e:
                logger.error(f"Error in deal reconciler loop: {e}")
            await asyncio.sleep(10)

    def start(self) -> None:
        """Start periodic background reconciler."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self.reconciliation_loop())

    def stop(self) -> None:
        """Stop background reconciler."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Deal reconciler stopped.")


deal_reconciler = DealReconciler()

