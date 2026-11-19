"""Real-Time 1-Second Live WebSocket Broadcaster."""

import asyncio
import json
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.watchdog import watchdog
from backend.app.core.risk_engine import risk_engine
from backend.app.db.session import SessionLocal
from backend.app.db.models import AppSettings, MT5AccountProfile, TradeLedger
from backend.app.mt5_bridge.connector import mt5_connector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages active live WebSocket subscribers."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return
        payload = json.dumps(message)
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                self.disconnect(connection)


manager = ConnectionManager()


async def get_live_state() -> dict:
    """Gather live account, risk metrics, and pair scheduler state for 1-second broadcast."""
    with SessionLocal() as db:
        st = db.query(AppSettings).filter_by(id=1).first()
        active_type = st.active_account_type if st else "DEMO"
        exec_mode = st.execution_mode if (st and st.execution_mode in ["AUTO", "HALTED"]) else "AUTO"
        profile = db.query(MT5AccountProfile).filter_by(account_type=active_type).first()

        closed_trades = db.query(TradeLedger).filter(
            TradeLedger.account_type == active_type,
            TradeLedger.status == "CLOSED",
        ).all()
        today_net_pnl = sum(float(t.net_pnl) for t in closed_trades)

        planned_records = db.query(TradeLedger).filter(
            TradeLedger.account_type == active_type,
            TradeLedger.status == "PLANNED",
        ).all()
        planned_trades = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "mode": t.mode,
                "direction": t.direction,
                "lots": float(t.lots),
                "entry_price": float(t.entry_price),
                "sl": float(t.sl),
                "tp1": float(t.tp1),
                "tp2": float(t.tp2),
                "ai_analysis_summary": t.ai_analysis_summary,
                "opened_at_ist": to_ist_str(t.opened_at_utc),
            }
            for t in planned_records
        ]

    # Initialize baseline values from stored profile
    balance = float(profile.last_balance) if profile else 0.0
    equity = float(profile.last_equity) if profile else 0.0
    floating_pnl = 0.0
    margin_used = 0.0
    free_margin = 0.0
    leverage = profile.leverage if profile else 1000
    login_id = profile.login_id if profile else None
    server_name = profile.server_name if profile else "XMGlobal-MT5"
    algo_trading_enabled = False
    open_positions = []
    pending_orders = []
    quotes: dict = {}

    is_conn = mt5_connector.is_connected
    if is_conn:
        try:
            open_positions = await mt5_connector.get_open_positions()
            pending_orders = await mt5_connector.get_pending_orders()
            import MetaTrader5 as mt5
            from backend.app.mt5_bridge.mt5_actor import mt5_actor

            def _query_live():
                acc = mt5.account_info()
                term = mt5.terminal_info()
                t_info = None
                if acc:
                    t_info = {
                        "balance": float(acc.balance),
                        "equity": float(acc.equity),
                        "floating_pnl": float(acc.profit),
                        "margin": float(acc.margin),
                        "margin_free": float(acc.margin_free),
                        "leverage": int(acc.leverage),
                        "login": int(acc.login),
                        "server": str(acc.server),
                        "trade_allowed": bool(acc.trade_allowed) and bool(term.trade_allowed if term else True),
                    }

                # Multi-Asset Universe: Stream live quotes for all 14 instruments
                ticks_data = {}
                from backend.app.core.instruments import INSTRUMENT_UNIVERSE
                symbols = list(INSTRUMENT_UNIVERSE.keys())
                for sym in symbols:
                    mt5.symbol_select(sym, True)
                    tick = mt5.symbol_info_tick(sym)
                    info = mt5.symbol_info(sym)
                    if not tick:
                        alt = sym.rstrip("#")
                        mt5.symbol_select(alt, True)
                        tick = mt5.symbol_info_tick(alt)
                        info = mt5.symbol_info(alt)

                    if tick and info:
                        digits = int(info.digits) if info else 2
                        spread_pts = round((tick.ask - tick.bid) * (10 ** digits)) if digits else 0
                        ticks_data[sym] = {
                            "symbol": sym,
                            "bid": float(tick.bid),
                            "ask": float(tick.ask),
                            "spread_points": spread_pts,
                            "time": int(tick.time),
                        }
                    elif info:
                        ticks_data[sym] = {
                            "symbol": sym,
                            "bid": float(info.bid) if info.bid else 0.0,
                            "ask": float(info.ask) if info.ask else 0.0,
                            "spread_points": int(info.spread) if info.spread else 0,
                            "time": 0,
                        }

                return t_info, ticks_data

            live_res = await mt5_actor.run_quote(_query_live)
            if live_res:
                t_info, ticks_data = live_res
                if t_info:
                    balance = t_info["balance"]
                    equity = t_info["equity"]
                    floating_pnl = t_info["floating_pnl"]
                    margin_used = t_info["margin"]
                    free_margin = t_info["margin_free"]
                    leverage = t_info["leverage"]
                    login_id = t_info["login"]
                    server_name = t_info["server"]
                    algo_trading_enabled = t_info["trade_allowed"]

                if ticks_data:
                    quotes = ticks_data

            open_positions = await mt5_connector.get_open_positions()

            # Update DB profile with live numbers so DB stays synced
            if balance > 0:
                with SessionLocal() as db_upd:
                    prof_upd = db_upd.query(MT5AccountProfile).filter_by(account_type=active_type).first()
                    if prof_upd:
                        prof_upd.last_balance = Decimal(str(round(balance, 2)))
                        prof_upd.last_equity = Decimal(str(round(equity, 2)))
                        prof_upd.is_connected = True
                        db_upd.commit()
        except Exception as e:
            logger.debug(f"Telemetry MT5 query error: {e}")

    # Calculate real-time margin usage & drawdown
    margin_usage_pct = 0.0
    daily_dd_pct = 0.0
    weekly_dd_pct = 0.0
    risk_state = "NORMAL"

    if balance > 0:
        dd_val = max(0.0, balance - equity)
        daily_dd_pct = round((dd_val / balance) * 100.0, 2)
        weekly_dd_pct = daily_dd_pct

    if equity > 0 and margin_used > 0:
        margin_usage_pct = round((margin_used / equity) * 100.0, 2)
    elif equity > 0 and open_positions:
        pos_margin = sum(p.get("margin", 0.0) for p in open_positions)
        if pos_margin > 0:
            margin_usage_pct = round((pos_margin / equity) * 100.0, 2)

    if margin_usage_pct >= 18.0 or daily_dd_pct >= 2.5:
        risk_state = "DRAWDOWN_BREACH"

    from backend.app.ai_brain.scheduler import scheduler
    pair_schedules = scheduler.pair_schedules if scheduler else {}

    # Merge schedule countdown into quotes
    for sym, q in quotes.items():
        sched = pair_schedules.get(sym, {})
        q["next_scan_sec"] = sched.get("next_scan_seconds", 60)
        q["ea_heartbeat_ok"] = True

    return {
        "type": "LIVE_TICK",
        "account_type": active_type,
        "active_account_type": active_type,
        "execution_mode": exec_mode,
        "is_connected": is_conn,
        "mt5_connected": is_conn,
        "db_healthy": watchdog.db_healthy,
        "login_id": login_id,
        "server_name": server_name,
        "algo_trading_enabled": algo_trading_enabled,
        "balance": round(balance, 2),
        "equity": round(equity, 2),
        "floating_pnl": round(floating_pnl, 2),
        "realized_daily_pnl": round(today_net_pnl, 2),
        "margin_used": round(margin_used, 2),
        "free_margin": round(free_margin, 2),
        "margin_usage_pct": margin_usage_pct,
        "daily_dd_pct": daily_dd_pct,
        "weekly_dd_pct": weekly_dd_pct,
        "leverage": leverage,
        "risk_state": risk_state,
        "today_closed_net_pnl": round(today_net_pnl, 2),
        "open_positions_count": len(open_positions),
        "open_positions": open_positions,
        "pending_orders_count": len(pending_orders),
        "pending_orders": pending_orders,
        "pair_schedules": pair_schedules,
        "quotes": quotes,
        "timestamp_ist": to_ist_str(now_utc()),
    }


@router.websocket("/ws/live")
async def websocket_live_feed(websocket: WebSocket):
    """Client endpoint subscribing to 1-second live telemetry."""
    await manager.connect(websocket)
    try:
        while True:
            state = await get_live_state()
            await websocket.send_json(state)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.debug(f"WebSocket client disconnected with exception: {e}")
        manager.disconnect(websocket)

