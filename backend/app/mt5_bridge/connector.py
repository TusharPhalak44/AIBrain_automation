"""MT5 Terminal Connector, Pair Specs Synchronizer & Demo/Live Guard."""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from backend.app.core.config import settings
from backend.app.core.crypto_vault import crypto_vault
from backend.app.core.clock_sync import now_utc
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel

logger = logging.getLogger(__name__)

# Fallback known paths for XM MT5
CANDIDATE_PATHS = [
    r"C:\Program Files\XM Global MT5\terminal64.exe",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
]


def resolve_terminal_path(profile_path: Optional[str] = None) -> str:
    """Find installed MT5 terminal binary path."""
    if profile_path and Path(profile_path).exists():
        return profile_path
    for p in CANDIDATE_PATHS:
        if Path(p).exists():
            return p
    return settings.XM_MT5_TERMINAL_PATH


class MT5Connector:
    """Manages connection, synchronization, and safe Demo/Live switching."""

    def __init__(self):
        self.connected_account_type: Optional[str] = None
        self.is_connected: bool = False

    async def connect(
        self,
        account_type: str = "DEMO",
        login_override: Optional[int] = None,
        password_override: Optional[str] = None,
        server_override: Optional[str] = None,
        terminal_path_override: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Connect and authenticate to MT5 terminal for specified account profile."""
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import MT5AccountProfile
        import MetaTrader5 as mt5

        with SessionLocal() as db:
            profile = db.query(MT5AccountProfile).filter_by(account_type=account_type.upper()).first()
            if not profile:
                return False, f"Account profile '{account_type}' not found in database."

            term_path_candidate = terminal_path_override or profile.terminal_path
            terminal_path = resolve_terminal_path(term_path_candidate)
            login = login_override if login_override is not None else (int(profile.login_id) if profile.login_id else None)
            server = server_override or profile.server_name
            password = password_override or (crypto_vault.decrypt_secret(profile.password_enc) if profile.password_enc else None)

        if not Path(terminal_path).exists():
            return False, f"MT5 terminal executable not found at: {terminal_path}"

        def _do_init():
            kwargs = {"path": terminal_path, "timeout": 60000}
            if login and password and server:
                kwargs["login"] = int(login)
                kwargs["password"] = password
                kwargs["server"] = server

            ok = mt5.initialize(**kwargs)
            if not ok:
                err = mt5.last_error()
                # If login failed or terminal already running, retry attaching without explicit login
                if "login" in kwargs:
                    logger.info("Retrying MT5 initialize without credentials to attach to active terminal...")
                    ok = mt5.initialize(path=terminal_path, timeout=60000)

            if not ok:
                err = mt5.last_error()
                return False, f"MT5 initialize failed: {err}"

            # Verify terminal account info
            acc_info = mt5.account_info()
            if not acc_info:
                err = mt5.last_error()
                return False, f"MT5 account_info failed: {err}"

            return True, acc_info

        success, result = await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _do_init)

        if not success:
            logger.error(f"MT5 connect failed for {account_type}: {result}")
            return False, str(result)

        acc_info = result
        self.connected_account_type = account_type.upper()
        self.is_connected = True

        # Update profile stats in MySQL
        with SessionLocal() as db:
            profile = db.query(MT5AccountProfile).filter_by(account_type=account_type.upper()).first()
            if profile:
                profile.is_connected = True
                profile.last_balance = Decimal(str(acc_info.balance))
                profile.last_equity = Decimal(str(acc_info.equity))
                profile.leverage = int(acc_info.leverage)
                profile.login_id = int(acc_info.login)
                profile.updated_at_utc = now_utc()
                db.commit()

        # Synchronize XM symbol specs in background
        try:
            await self.sync_xm_pair_specs()
        except Exception as se:
            logger.warning(f"Post-connect symbol sync error: {se}")

        logger.info(f"MT5 successfully connected to {account_type} profile (Login: {acc_info.login}, Balance: ${acc_info.balance:.2f}).")
        return True, f"Connected to {account_type} (Login: {acc_info.login}, Server: {acc_info.server})"

    async def disconnect(self) -> bool:
        """Gracefully disconnect from MT5."""
        import MetaTrader5 as mt5
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import MT5AccountProfile

        def _do_shutdown():
            mt5.shutdown()
            return True

        await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _do_shutdown)

        if self.connected_account_type:
            with SessionLocal() as db:
                profile = db.query(MT5AccountProfile).filter_by(account_type=self.connected_account_type).first()
                if profile:
                    profile.is_connected = False
                    profile.updated_at_utc = now_utc()
                    db.commit()

        self.is_connected = False
        self.connected_account_type = None
        logger.info("MT5 disconnected.")
        return True

    async def get_open_positions(self) -> List[Dict[str, Any]]:
        """Query currently active positions on connected MT5 terminal."""
        import MetaTrader5 as mt5

        def _query():
            positions = mt5.positions_get()
            if positions is None:
                return []
            res = []
            for p in positions:
                res.append({
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "magic": p.magic,
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit": p.profit,
                    "swap": p.swap,
                })
            return res

        return await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _query)

    async def emergency_flatten_all(self) -> Tuple[int, List[str]]:
        """Emergency panic close for all open positions across all symbols."""
        import MetaTrader5 as mt5

        def _flatten():
            positions = mt5.positions_get()
            if not positions:
                return 0, []

            closed_count = 0
            errors = []
            for pos in positions:
                tick = mt5.symbol_info_tick(pos.symbol)
                if not tick:
                    errors.append(f"No tick for {pos.symbol}")
                    continue

                close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "position": pos.ticket,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "price": close_price,
                    "deviation": 20,
                    "magic": pos.magic,
                    "comment": "PANIC_CLOSE",
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    closed_count += 1
                else:
                    err_msg = res.comment if res else str(mt5.last_error())
                    errors.append(f"Failed to close #{pos.ticket}: {err_msg}")

            return closed_count, errors

        return await mt5_actor.execute(PriorityLevel.P0_EMERGENCY, _flatten)

    async def close_single_position(self, ticket: int) -> Tuple[bool, str]:
        """Close a specific open position by ticket."""
        import MetaTrader5 as mt5

        def _close():
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False, f"Position #{ticket} not found on MT5 terminal."

            pos = positions[0]
            tick = mt5.symbol_info_tick(pos.symbol)
            if not tick:
                return False, f"No live quote available for {pos.symbol}"

            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            close_price = tick.bid if pos.type == mt5.ORDER_TYPE_BUY else tick.ask

            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": close_type,
                "price": close_price,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "Portal 1-Click Close",
            }
            res = mt5.order_send(req)
            if not res or res.retcode != mt5.TRADE_RETCODE_DONE:
                err = res.comment if res else str(mt5.last_error())
                return False, f"Close failed: retcode={res.retcode if res else 'None'} ({err})"
            return True, f"Position #{ticket} closed successfully at {close_price}."

        return await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _close)

    async def switch_account_profile(
        self,
        target_account_type: str,
        action_on_positions: str = "KEEP_EA_PROTECTED",
        confirm_token: Optional[str] = None,
    ) -> Tuple[bool, Dict[str, Any]]:
        """
        Safely transition between DEMO and LIVE profiles.
        Enforces:
        1. Open positions check and user acknowledgment.
        2. Strict CONFIRM_LIVE_TRADING token requirement when transitioning to LIVE.
        """
        target = target_account_type.upper()
        if target not in ("DEMO", "LIVE"):
            return False, {"error": "INVALID_ACCOUNT_TYPE", "message": "Must be DEMO or LIVE"}

        # Strict token guard for LIVE switch
        if target == "LIVE" and confirm_token != "CONFIRM_LIVE_TRADING":
            return False, {
                "error": "CONFIRM_TOKEN_REQUIRED",
                "message": "Switching to LIVE requires explicit confirm_token='CONFIRM_LIVE_TRADING'.",
            }

        # Check existing positions on currently open terminal
        if self.is_connected:
            open_positions = await self.get_open_positions()
            if open_positions:
                if action_on_positions not in ("KEEP_EA_PROTECTED", "FLATTEN_FIRST"):
                    return False, {
                        "warning": "OPEN_POSITIONS_DETECTED",
                        "open_count": len(open_positions),
                        "positions": open_positions,
                        "message": (
                            f"{len(open_positions)} open positions exist on the terminal. "
                            "You must specify action_on_positions='KEEP_EA_PROTECTED' or 'FLATTEN_FIRST'."
                        ),
                    }

                if action_on_positions == "FLATTEN_FIRST":
                    flattened, errors = await self.emergency_flatten_all()
                    logger.warning(f"Flattened {flattened} positions prior to profile switch. Errors: {errors}")

            # Disconnect previous profile
            await self.disconnect()

        # Connect to new profile
        ok, msg = await self.connect(target)
        if not ok:
            return False, {"error": "CONNECTION_FAILED", "message": msg}

        # Update singleton AppSettings active_account_type
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import AppSettings

        with SessionLocal() as db:
            settings_rec = db.query(AppSettings).filter_by(id=1).first()
            if settings_rec:
                settings_rec.active_account_type = target
                settings_rec.updated_at_utc = now_utc()
                db.commit()

        return True, {
            "status": "SUCCESS",
            "active_account_type": target,
            "message": f"Successfully switched to {target} trading profile.",
        }

    async def sync_xm_pair_specs(self) -> Dict[str, Any]:
        """
        Read real live symbol specs from connected XM MT5 terminal
        and sync them to TradingPairBot table in MySQL.
        """
        import MetaTrader5 as mt5
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import TradingPairBot

        def _read_specs():
            with SessionLocal() as db:
                pairs = db.query(TradingPairBot).all()
                results = {}
                for pair in pairs:
                    sym = pair.symbol
                    mt5.symbol_select(sym, True)
                    info = mt5.symbol_info(sym)
                    if not info:
                        # Auto-fallback between Ultra Low (#) and Standard symbol naming
                        alt_sym = sym.rstrip("#") if sym.endswith("#") else f"{sym}#"
                        mt5.symbol_select(alt_sym, True)
                        info = mt5.symbol_info(alt_sym)
                        if info:
                            sym = alt_sym

                    if not info:
                        results[pair.symbol] = {"status": "NOT_FOUND"}
                        continue

                    pair.contract_size = Decimal(str(getattr(info, "trade_contract_size", 100.0)))
                    pair.tick_size = Decimal(str(getattr(info, "trade_tick_size", 0.01)))
                    pair.tick_value = Decimal(str(getattr(info, "trade_tick_value", 1.0)))
                    pair.digits = int(getattr(info, "digits", 2))
                    pair.stops_level = int(getattr(info, "trade_stops_level", getattr(info, "stops_level", 0)))
                    pair.volume_min = Decimal(str(getattr(info, "volume_min", 0.01)))
                    pair.volume_step = Decimal(str(getattr(info, "volume_step", 0.01)))
                    pair.swap_long = Decimal(str(getattr(info, "swap_long", 0.0)))
                    pair.swap_short = Decimal(str(getattr(info, "swap_short", 0.0)))
                    pair.three_day_swap_day = int(getattr(info, "swap_rollover3days", 2))

                    results[pair.symbol] = {
                        "status": "SYNCED",
                        "broker_symbol": sym,
                        "contract_size": float(getattr(info, "trade_contract_size", 100.0)),
                        "tick_size": float(getattr(info, "trade_tick_size", 0.01)),
                        "tick_value": float(getattr(info, "trade_tick_value", 1.0)),
                        "volume_min": float(getattr(info, "volume_min", 0.01)),
                        "volume_step": float(getattr(info, "volume_step", 0.01)),
                        "digits": int(getattr(info, "digits", 2)),
                    }
                db.commit()
                return results

        return await mt5_actor.execute(PriorityLevel.P2_QUOTES_HISTORY, _read_specs)


mt5_connector = MT5Connector()

