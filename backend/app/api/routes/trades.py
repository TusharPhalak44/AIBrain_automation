"""Trades, Live Summary & Execution Routes."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.core.instruments import resolve_mt5_symbol, get_symbol_spec, format_symbol_price
from backend.app.core.risk_engine import risk_engine
from backend.app.db.models import TradeLedger, AppSettings, MT5AccountProfile
from backend.app.db.session import get_db
from backend.app.mt5_bridge.connector import mt5_connector
from backend.app.mt5_bridge.mt5_actor import mt5_actor, PriorityLevel

router = APIRouter(prefix="/trades", tags=["Trades & Execution"])


class ExecuteOrderSchema(BaseModel):
    symbol: str = Field(..., description="Target instrument e.g. GOLD#, EURUSD#, BTCUSD#")
    order_type: str = Field(..., description="'BUY' or 'SELL'")
    lots: float = Field(0.01, ge=0.01, le=100.0, description="Volume in lots")
    sl: float = Field(..., description="Mandatory hard stop-loss price (Zero-Naked Invariant)")
    tp: Optional[float] = Field(None, description="Optional take-profit price")
    comment: Optional[str] = Field("Manual Portal Execution", description="Order comment")


@router.post("/execute")
async def execute_manual_order(payload: ExecuteOrderSchema, db: Session = Depends(get_db)):
    """Execute manual BUY or SELL order with mandatory hard broker SL and risk checks."""
    if payload.sl <= 0:
        raise HTTPException(status_code=400, detail="MANDATORY_SL_REQUIRED: Stop-loss must be strictly greater than 0.")

    import MetaTrader5 as mt5

    if not mt5_connector.is_connected:
        raise HTTPException(status_code=503, detail="MT5 terminal is disconnected. Cannot execute trade.")

    target_sym = resolve_mt5_symbol(payload.symbol)
    spec = get_symbol_spec(payload.symbol)

    def _send():
        if not mt5.terminal_info():
            return False, "MT5 terminal not initialized", None

        mt5.symbol_select(target_sym, True)
        tick = mt5.symbol_info_tick(target_sym)
        info = mt5.symbol_info(target_sym)

        if not tick or not info:
            return False, f"Could not retrieve live price tick for {target_sym}", None

        is_buy = payload.order_type.upper() == "BUY"
        price = tick.ask if is_buy else tick.bid
        order_action = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        # Geometry validation
        if is_buy and payload.sl >= price:
            return False, f"Invalid BUY geometry: SL ({payload.sl}) must be strictly below current Ask ({price})", None
        if not is_buy and payload.sl <= price:
            return False, f"Invalid SELL geometry: SL ({payload.sl}) must be strictly above current Bid ({price})", None

        # Build order request
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": target_sym,
            "volume": float(payload.lots),
            "type": order_action,
            "price": float(price),
            "sl": float(payload.sl),
            "tp": float(payload.tp) if payload.tp and payload.tp > 0 else 0.0,
            "deviation": 20,
            "magic": 999999,  # Manual execution magic
            "comment": payload.comment or "Manual Portal V2",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Try IOC then RETURN if broker requires
        res = mt5.order_send(req)
        if res and res.retcode != mt5.TRADE_RETCODE_DONE:
            req["type_filling"] = mt5.ORDER_FILLING_RETURN
            res = mt5.order_send(req)

        if res is None:
            return False, "Order send returned None from MT5", None

        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return True, "Executed successfully", {
                "order": res.order,
                "deal": res.deal,
                "volume": res.volume,
                "price": res.price,
            }
        else:
            return False, f"MT5 order rejected (retcode {res.retcode}): {res.comment}", None

    ok, msg, res_data = await mt5_actor.execute(PriorityLevel.P1_POSITIONS, _send)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "ORDER_REJECTED", "message": msg})

    return {
        "status": "SUCCESS",
        "symbol": target_sym,
        "order_type": payload.order_type.upper(),
        "lots": payload.lots,
        "executed_price": res_data.get("price") if res_data else None,
        "ticket": res_data.get("order") if res_data else None,
        "message": msg,
        "timestamp_ist": to_ist_str(now_utc()),
    }


@router.get("/live-summary")
async def get_live_summary(db: Session = Depends(get_db)):
    """Fetch live trading state, margin usage %, floating PnL, and today's closed PnL."""
    st = db.query(AppSettings).filter_by(id=1).first()
    active_type = st.active_account_type if st else "DEMO"
    profile = db.query(MT5AccountProfile).filter_by(account_type=active_type).first()

    open_positions = []
    if mt5_connector.is_connected:
        open_positions = await mt5_connector.get_open_positions()

    floating_pnl = sum(p.get("profit", 0.0) for p in open_positions)
    margin_used = sum(p.get("margin", 0.0) for p in open_positions) if open_positions else 0.0

    # Closed trades today
    closed_trades = db.query(TradeLedger).filter(
        TradeLedger.account_type == active_type,
        TradeLedger.status == "CLOSED",
    ).all()
    today_net_pnl = sum(float(t.net_pnl) for t in closed_trades)
    today_gross_pnl = sum(float(t.gross_pnl) for t in closed_trades)
    today_fees = sum(float(t.commission + t.swap) for t in closed_trades)

    balance = float(profile.last_balance) if profile else 0.0
    equity = float(profile.last_equity) if profile else 0.0
    margin_usage_pct = (margin_used / equity * 100.0) if equity > 0 else 0.0

    return {
        "active_account_type": active_type,
        "is_connected": mt5_connector.is_connected,
        "balance": balance,
        "equity": equity,
        "floating_pnl": round(floating_pnl, 2),
        "margin_used": round(margin_used, 2),
        "margin_usage_pct": round(margin_usage_pct, 2),
        "margin_ceiling_pct": float(st.max_margin_usage_pct) if st else 18.0,
        "daily_dd_limit_pct": float(st.daily_dd_limit_pct) if st else 2.5,
        "today_closed_net_pnl": round(today_net_pnl, 2),
        "today_closed_gross_pnl": round(today_gross_pnl, 2),
        "today_fees_drag": round(today_fees, 2),
        "open_positions_count": len(open_positions),
        "open_positions": open_positions,
        "timestamp_utc": now_utc().isoformat(),
        "timestamp_ist": to_ist_str(now_utc()),
    }


def _serialize_trade(t: TradeLedger) -> Dict[str, Any]:
    return {
        "id": t.id,
        "account_type": t.account_type,
        "position_id": t.position_id,
        "symbol": t.symbol,
        "magic_number": t.magic_number,
        "mode": t.mode,
        "direction": t.direction,
        "status": t.status,
        "lots": float(t.lots),
        "entry_price": float(t.entry_price),
        "exit_price": float(t.exit_price) if t.exit_price else None,
        "sl": float(t.sl),
        "tp1": float(t.tp1),
        "tp2": float(t.tp2),
        "gross_pnl": float(t.gross_pnl),
        "commission": float(t.commission),
        "swap": float(t.swap),
        "net_pnl": float(t.net_pnl),
        "r_multiple": float(t.r_multiple) if t.r_multiple else None,
        "exit_reason": t.exit_reason,
        "loss_postmortem_text": t.loss_postmortem_text,
        "ai_analysis_summary": t.ai_analysis_summary,
        "opened_at_utc": t.opened_at_utc.isoformat() if t.opened_at_utc else None,
        "closed_at_utc": t.closed_at_utc.isoformat() if t.closed_at_utc else None,
        "opened_at_ist": to_ist_str(t.opened_at_utc),
        "closed_at_ist": to_ist_str(t.closed_at_utc) if t.closed_at_utc else "-",
    }


@router.get("")
@router.get("/history")
def get_trade_history(
    account_type: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    """Fetch closed and active trades from TradeLedger."""
    query = db.query(TradeLedger)
    if account_type:
        query = query.filter(TradeLedger.account_type == account_type.upper())
    if symbol:
        clean = symbol.rstrip("#")
        query = query.filter(
            (TradeLedger.symbol == symbol)
            | (TradeLedger.symbol == clean)
            | (TradeLedger.symbol == f"{clean}#")
        )
    trades = query.order_by(TradeLedger.opened_at_utc.desc()).limit(limit).all()
    return [_serialize_trade(t) for t in trades]


@router.post("/panic-close")
@router.post("/panic-flatten")
async def execute_panic_close():
    """Emergency flatten all active open positions across the MT5 terminal."""
    closed_cnt, errors = await mt5_connector.emergency_flatten_all()
    return {
        "status": "EXECUTED",
        "positions_closed": closed_cnt,
        "errors": errors,
        "timestamp_ist": to_ist_str(now_utc()),
    }


@router.post("/{ticket}/close")
async def close_trade_by_ticket(ticket: int):
    """1-click close for a specific open MT5 position."""
    ok, msg = await mt5_connector.close_single_position(ticket)
    if not ok:
        raise HTTPException(status_code=400, detail={"error": "CLOSE_FAILED", "message": msg})
    return {"status": "SUCCESS", "message": msg, "ticket": ticket}
