"""Historical Deals Reconciler & Net PnL Accounting Service.

Groups MT5 closed deals by position_id, reconciles fees (spread, commission, swap),
updates TradeLedger, dispatches notifications, and spools offline if MySQL is unavailable.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
from backend.app.core.clock_sync import now_utc
from backend.app.core.watchdog import watchdog
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel

logger = logging.getLogger(__name__)


def classify_exit_reason(reason_code: int, profit: float, comment: str = "") -> str:
    """Classify MT5 DEAL_REASON into standard portal exit reason."""
    # Standard MT5 Reason codes:
    # 0 = CLIENT, 1 = MOBILE, 2 = WEB, 3 = EXPERT, 4 = SL, 5 = TP, 6 = SO
    if reason_code == 4 or "sl" in comment.lower():
        return "SL_HIT"
    elif reason_code == 5 or "tp" in comment.lower():
        return "TP_HIT"
    elif "trail" in comment.lower():
        return "TRAIL_SL"
    elif "panic" in comment.lower() or "kill" in comment.lower():
        return "KILL_SWITCH"
    elif reason_code in (0, 1, 2):
        return "MANUAL_MOBILE"
    elif reason_code == 3:
        return "TRAIL_SL" if profit > 0 else "SL_HIT"
    return "MANUAL_MOBILE"


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
        exit_reason = classify_exit_reason(reason_code, total_gross, comment)
        close_time_epoch = last_deal.get("time", int(now_utc().timestamp()))
        closed_at = datetime.fromtimestamp(close_time_epoch, tz=timezone.utc)

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
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import TradeLedger

        try:
            with SessionLocal() as db:
                trade = db.query(TradeLedger).filter_by(position_id=pos_id).first()
                if trade:
                    if trade.status != "CLOSED":
                        trade.status = "CLOSED"
                        trade.exit_price = Decimal(str(exit_price))
                        trade.gross_pnl = Decimal(str(round(total_gross, 2)))
                        trade.commission = Decimal(str(round(total_comm, 2)))
                        trade.swap = Decimal(str(round(total_swap, 2)))
                        trade.net_pnl = Decimal(str(round(total_net, 2)))
                        trade.exit_reason = exit_reason
                        trade.closed_at_utc = closed_at

                        # Calculate R-Multiple if initial risk is known
                        initial_risk = abs(trade.entry_price - trade.sl) if trade.sl > 0 else Decimal("0")
                        if initial_risk > 0:
                            gain_price = (exit_price - float(trade.entry_price)) if trade.direction == "BUY" else (float(trade.entry_price) - exit_price)
                            r_mult = gain_price / float(initial_risk)
                            trade.r_multiple = Decimal(str(round(r_mult, 2)))

                        db.commit()
                        logger.info(f"Reconciled trade #{pos_id}: Net PnL ${total_net:.2f} ({exit_reason})")

                        # Trigger SL-hit forensic learner post-mortem hook
                        if exit_reason == "SL_HIT":
                            try:
                                from backend.app.ai_brain.forensic_learner import forensic_learner
                                forensic_learner.run_sl_hit_postmortem(trade.id, db)
                            except Exception as fe:
                                logger.warning(f"Error running SL postmortem for trade #{trade.id}: {fe}")

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

