"""Trades, Live Summary & Execution Routes."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.db.models import TradeLedger, AppSettings, MT5AccountProfile
from backend.app.db.session import get_db
from backend.app.mt5_bridge.connector import mt5_connector

router = APIRouter(prefix="/trades", tags=["Trades & Execution"])


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
