"""Watchdog & Offline Spooling Service.

1. Windows OS Sleep Inhibition via SetThreadExecutionState.
2. 5-second async heartbeat checking MySQL and MT5 terminal health.
3. Offline JSONL Deal Spooling when MySQL is disconnected.
4. Auto-replay of spooled deals into MySQL upon recovery.
"""

import asyncio
import ctypes
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from backend.app.core.config import settings, DATA_DIR
from backend.app.core.clock_sync import now_utc

logger = logging.getLogger(__name__)

# Windows Execution State Flags
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


def inhibit_windows_sleep(enable: bool = True) -> bool:
    """Inhibit or restore Windows sleep mode to prevent desktop sleep during trading."""
    if sys.platform != "win32":
        return False
    try:
        flags = ES_CONTINUOUS
        if enable:
            flags |= ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
        result = ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return result != 0
    except Exception as e:
        logger.warning(f"Failed to set Windows thread execution state: {e}")
        return False


class WatchdogService:
    """Monitors system health, blocks sleep, and handles offline disaster recovery."""

    def __init__(self, spool_file: Optional[Path] = None):
        self.spool_path = spool_file or settings.MYSQL_SPOOL_PATH
        self.db_healthy: bool = True
        self.mt5_healthy: bool = False
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.cached_telegram_token: Optional[str] = None
        self.cached_admin_chat_id: Optional[str] = None

    def spool_closed_deal(self, deal_data: Dict[str, Any]) -> bool:
        """
        Buffer an emergency closed-deal reconciliation record to JSONL
        when MySQL is unreachable.
        """
        try:
            self.spool_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "spooled_at_utc": now_utc().isoformat(),
                "deal": deal_data,
            }
            with open(self.spool_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            logger.warning(f"Spooled deal to emergency offline buffer: {deal_data.get('position_id')}")
            return True
        except Exception as e:
            logger.error(f"Failed to spool deal to disk: {e}")
            return False

    def get_spooled_records(self) -> List[Dict[str, Any]]:
        """Read all pending spooled records from disk."""
        if not self.spool_path.exists():
            return []
        records = []
        try:
            with open(self.spool_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except Exception as e:
            logger.error(f"Error reading spool file: {e}")
        return records

    def clear_spool(self) -> None:
        """Clear the spool file after successful database replay."""
        try:
            if self.spool_path.exists():
                self.spool_path.unlink()
                logger.info("Emergency offline deal spool cleared.")
        except Exception as e:
            logger.error(f"Error clearing spool file: {e}")

    def replay_spool_into_db(self, session) -> int:
        """
        Replay spooled deal records into the database upon connection restoration.
        Returns the count of successfully processed records.
        """
        from backend.app.db.models import TradeLedger

        records = self.get_spooled_records()
        if not records:
            return 0

        replayed_count = 0
        try:
            for item in records:
                deal = item.get("deal", {})
                pos_id = deal.get("position_id")
                if not pos_id:
                    continue

                # Check if position already exists in TradeLedger
                existing = session.query(TradeLedger).filter_by(position_id=pos_id).first()
                if existing:
                    existing.status = "CLOSED"
                    existing.exit_price = deal.get("exit_price")
                    existing.gross_pnl = deal.get("gross_pnl", 0.0)
                    existing.commission = deal.get("commission", 0.0)
                    existing.swap = deal.get("swap", 0.0)
                    existing.net_pnl = deal.get("net_pnl", 0.0)
                    existing.exit_reason = deal.get("exit_reason", "MANUAL_MOBILE")
                    existing.closed_at_utc = now_utc()
                else:
                    new_trade = TradeLedger(
                        account_type=deal.get("account_type", "DEMO"),
                        position_id=pos_id,
                        order_ticket=deal.get("order_ticket"),
                        symbol=deal.get("symbol", "UNKNOWN"),
                        magic_number=deal.get("magic_number", 0),
                        mode=deal.get("mode", "MANUAL"),
                        direction=deal.get("direction", "BUY"),
                        status="CLOSED",
                        lots=deal.get("lots", 0.01),
                        initial_lots=deal.get("initial_lots", 0.01),
                        entry_price=deal.get("entry_price", 0.0),
                        sl=deal.get("sl", 0.0),
                        tp1=deal.get("tp1", 0.0),
                        tp2=deal.get("tp2", 0.0),
                        exit_price=deal.get("exit_price"),
                        gross_pnl=deal.get("gross_pnl", 0.0),
                        commission=deal.get("commission", 0.0),
                        swap=deal.get("swap", 0.0),
                        net_pnl=deal.get("net_pnl", 0.0),
                        exit_reason=deal.get("exit_reason", "MANUAL_MOBILE"),
                        opened_at_utc=now_utc(),
                        closed_at_utc=now_utc(),
                    )
                    session.add(new_trade)
                replayed_count += 1

            session.commit()
            self.clear_spool()
            logger.info(f"Replayed {replayed_count} spooled deals into MySQL successfully.")
            return replayed_count
        except Exception as e:
            session.rollback()
            logger.error(f"Failed to replay spool into database: {e}")
            return 0

    async def check_mysql(self) -> bool:
        """Check MySQL responsiveness with a lightweight SELECT 1 query."""
        from backend.app.db.session import engine

        loop = asyncio.get_running_loop()

        def _ping():
            with engine.connect() as conn:
                res = conn.execute(text("SELECT 1")).scalar()
                return res == 1

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _ping), timeout=3.0)
        except Exception:
            return False

    async def check_mt5(self) -> bool:
        """Check MT5 terminal connection state."""
        try:
            import MetaTrader5 as mt5

            loop = asyncio.get_running_loop()
            term_info = await loop.run_in_executor(None, mt5.terminal_info)
            return term_info is not None and getattr(term_info, "connected", False)
        except Exception:
            return False

    async def heartbeat_loop(self) -> None:
        """Continuous 5-second asynchronous watchdog pulse."""
        logger.info("Watchdog heartbeat loop started.")
        inhibit_windows_sleep(True)

        while self._running:
            try:
                # 1. Check MySQL
                prev_db = self.db_healthy
                self.db_healthy = await self.check_mysql()

                if not self.db_healthy and prev_db:
                    logger.critical("ALERT: MySQL connection lost! Offline deal spooling engaged.")
                    # In production, dispatch emergency alert via Telegram using cached token

                elif self.db_healthy and not prev_db:
                    logger.info("ALERT RECOVERED: MySQL reconnected! Initiating offline spool replay.")
                    from backend.app.db.session import SessionLocal

                    with SessionLocal() as session:
                        self.replay_spool_into_db(session)

                # 2. Check MT5
                self.mt5_healthy = await self.check_mt5()

            except Exception as e:
                logger.error(f"Error in watchdog heartbeat pulse: {e}")

            await asyncio.sleep(5)

    def start(self) -> None:
        """Start background watchdog loop."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self.heartbeat_loop())

    def stop(self) -> None:
        """Stop background watchdog loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        inhibit_windows_sleep(False)
        logger.info("Watchdog heartbeat stopped.")


watchdog = WatchdogService()

