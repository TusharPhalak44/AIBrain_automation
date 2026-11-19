"""Trading Pair Bot Settings & Specifications Routes."""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.core.instruments import (
    INSTRUMENT_UNIVERSE,
    ALL_SYMBOLS,
    resolve_mt5_symbol,
    is_symbol_trading_open,
    get_symbol_spec,
)
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.models import TradingPairBot
from backend.app.db.session import get_db

router = APIRouter(prefix="/pairs", tags=["Trading Pairs"])
instruments_router = APIRouter(prefix="/instruments", tags=["Instruments"])


def _compute_active_session(is_24_7: bool, now_time: Optional[datetime] = None) -> str:
    """Determine current active trading session based on UTC hour."""
    if is_24_7:
        return "24/7 Continuous"
    t = now_time or datetime.now(timezone.utc)
    hour = t.hour
    minute = t.minute
    total_min = hour * 60 + minute

    if 0 <= total_min < 420:
        return "Asian (Tokyo)"
    elif 420 <= total_min < 720:
        return "London Open"
    elif 720 <= total_min < 990:
        return "London/NY Overlap"
    elif 990 <= total_min < 1260:
        return "New York Afternoon"
    else:
        return "Pacific / Rollover"


async def _fetch_instruments_data(db: Session) -> List[Dict[str, Any]]:
    """Assemble all 14 instruments with live MT5 metadata, market state, and DB config."""
    from backend.app.mt5_bridge.mt5_actor import mt5_actor
    from backend.app.mt5_bridge.connector import mt5_connector

    db_pairs = {p.symbol: p for p in db.query(TradingPairBot).all()}

    # Query live ticks from MT5
    def _query_ticks():
        import MetaTrader5 as mt5
        res = {}
        if not mt5.terminal_info():
            return res
        for sym in ALL_SYMBOLS:
            resolved = resolve_mt5_symbol(sym)
            tick = mt5.symbol_info_tick(resolved)
            info = mt5.symbol_info(resolved)
            if tick and info:
                digits = int(info.digits)
                spread = round((tick.ask - tick.bid) * (10 ** digits)) if digits else 0
                res[sym] = {
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "spread_points": int(spread),
                    "resolved_symbol": resolved,
                    "digits": digits,
                    "point": float(info.point),
                    "contract_size": float(info.trade_contract_size),
                    "tick_value": float(info.trade_tick_value),
                }
            elif info:
                res[sym] = {
                    "bid": float(info.bid) if info.bid else 0.0,
                    "ask": float(info.ask) if info.ask else 0.0,
                    "spread_points": int(info.spread) if info.spread else 0,
                    "resolved_symbol": resolved,
                    "digits": int(info.digits),
                    "point": float(info.point),
                    "contract_size": float(info.trade_contract_size),
                    "tick_value": float(info.trade_tick_value),
                }
        return res

    live_ticks: Dict[str, Any] = {}
    if mt5_connector.is_connected:
        try:
            live_ticks = await mt5_actor.run_quote(_query_ticks) or {}
        except Exception:
            live_ticks = {}

    current_utc = now_utc()
    result = []
    for sym, spec in INSTRUMENT_UNIVERSE.items():
        db_p = db_pairs.get(sym)
        live = live_ticks.get(sym, {})
        is_open = is_symbol_trading_open(sym, spec.asset_class, current_utc)
        active_sess = _compute_active_session(spec.is_24_7, current_utc) if is_open else "Market Closed"

        result.append({
            "symbol": sym,
            "display_name": spec.display_name,
            "asset_class": spec.asset_class,
            "base_currency": spec.base_currency,
            "quote_currency": spec.quote_currency,
            "digits": live.get("digits", spec.digits),
            "point": live.get("point", spec.tick_size),
            "contract_size": live.get("contract_size", spec.contract_size),
            "tick_size": spec.tick_size,
            "tick_value": live.get("tick_value", spec.tick_value),
            "volume_min": float(db_p.volume_min) if db_p else spec.volume_min,
            "volume_step": float(db_p.volume_step) if db_p else spec.volume_step,
            "volume_max": spec.volume_max,
            "swap_long": float(db_p.swap_long) if db_p else spec.swap_long,
            "swap_short": float(db_p.swap_short) if db_p else spec.swap_short,
            "bid": live.get("bid", 0.0),
            "ask": live.get("ask", 0.0),
            "spread_points": live.get("spread_points", spec.default_spread_points),
            "default_spread_points": spec.default_spread_points,
            "max_spread_points": db_p.max_spread_points if db_p else spec.max_spread_points,
            "is_market_open": is_open,
            "is_24_7": spec.is_24_7,
            "active_session": active_sess,
            "enabled": db_p.enabled if db_p else True,
            "scalp_enabled": db_p.scalp_enabled if db_p else True,
            "swing_enabled": db_p.swing_enabled if db_p else True,
            "risk_pct_scalp": float(db_p.risk_pct_scalp) if db_p else 1.0,
            "risk_pct_swing": float(db_p.risk_pct_swing) if db_p else 1.5,
            "scan_interval_sec": db_p.scan_interval_sec if db_p else 60,
        })

    return result


@instruments_router.get("")
async def get_all_instruments(db: Session = Depends(get_db)):
    """SSOT endpoint returning all 14 multi-asset trading pairs with live MT5 metadata."""
    return await _fetch_instruments_data(db)


@router.get("/instruments")
async def get_pairs_instruments_alias(db: Session = Depends(get_db)):
    """Alias for /api/instruments returning all 14 multi-asset trading pairs."""
    return await _fetch_instruments_data(db)


class PairUpdateSchema(BaseModel):
    enabled: Optional[bool] = None
    scalp_enabled: Optional[bool] = None
    swing_enabled: Optional[bool] = None
    scan_interval_sec: Optional[int] = None
    risk_pct_scalp: Optional[float] = None
    risk_pct_swing: Optional[float] = None
    max_spread_points: Optional[int] = None


@router.get("")
def list_pairs(db: Session = Depends(get_db)):
    """List all configured trading pair bots."""
    pairs = db.query(TradingPairBot).all()
    res = []
    for p in pairs:
        res.append({
            "symbol": p.symbol,
            "asset_class": p.asset_class,
            "enabled": p.enabled,
            "scalp_enabled": p.scalp_enabled,
            "swing_enabled": p.swing_enabled,
            "scan_interval_sec": p.scan_interval_sec,
            "risk_pct_scalp": float(p.risk_pct_scalp),
            "risk_pct_swing": float(p.risk_pct_swing),
            "max_spread_points": p.max_spread_points,
            "contract_size": float(p.contract_size),
            "tick_size": float(p.tick_size),
            "tick_value": float(p.tick_value),
            "digits": p.digits,
            "stops_level": p.stops_level,
            "volume_min": float(p.volume_min),
            "volume_step": float(p.volume_step),
            "swap_long": float(p.swap_long),
            "swap_short": float(p.swap_short),
            "ea_last_heartbeat_utc": p.ea_last_heartbeat_utc.isoformat() if p.ea_last_heartbeat_utc else None,
            "ea_last_heartbeat_ist": to_ist_str(p.ea_last_heartbeat_utc) if p.ea_last_heartbeat_utc else "-",
        })
    return res


@router.put("/{symbol}")
def update_pair(symbol: str, payload: PairUpdateSchema, db: Session = Depends(get_db)):
    """Update settings for a specific trading pair (handles raw symbol and suffix variant)."""
    resolved = resolve_broker_symbol(symbol, db)
    pair = db.query(TradingPairBot).filter_by(symbol=resolved).first()
    if not pair:
        pair = db.query(TradingPairBot).filter_by(symbol=symbol).first()
    if not pair:
        raise HTTPException(status_code=404, detail=f"Pair '{symbol}' not found")

    if payload.enabled is not None:
        pair.enabled = payload.enabled
    if payload.scalp_enabled is not None:
        pair.scalp_enabled = payload.scalp_enabled
    if payload.swing_enabled is not None:
        pair.swing_enabled = payload.swing_enabled
    if payload.scan_interval_sec is not None:
        pair.scan_interval_sec = payload.scan_interval_sec
    if payload.risk_pct_scalp is not None:
        pair.risk_pct_scalp = Decimal(str(payload.risk_pct_scalp))
    if payload.risk_pct_swing is not None:
        pair.risk_pct_swing = Decimal(str(payload.risk_pct_swing))
    if payload.max_spread_points is not None:
        pair.max_spread_points = payload.max_spread_points

    db.commit()
    return {"status": "SUCCESS", "symbol": symbol, "message": "Pair updated"}


class AssignStrategySchema(BaseModel):
    scalp_strategy_id: Optional[int] = None
    swing_strategy_id: Optional[int] = None


@router.post("/{symbol}/assign-strategy")
def assign_strategy(symbol: str, payload: AssignStrategySchema, db: Session = Depends(get_db)):
    """Assign scalp_strategy_id and/or swing_strategy_id to a TradingPairBot in MySQL."""
    resolved = resolve_broker_symbol(symbol, db)
    pair = db.query(TradingPairBot).filter_by(symbol=resolved).first()
    if not pair:
        pair = db.query(TradingPairBot).filter(
            (TradingPairBot.symbol == symbol) | (TradingPairBot.symbol == f"{symbol}#")
        ).first()
    if not pair:
        raise HTTPException(status_code=404, detail=f"TradingPairBot '{symbol}' not found")

    if payload.scalp_strategy_id is not None:
        pair.scalp_strategy_id = payload.scalp_strategy_id if payload.scalp_strategy_id > 0 else None
    if payload.swing_strategy_id is not None:
        pair.swing_strategy_id = payload.swing_strategy_id if payload.swing_strategy_id > 0 else None

    db.commit()
    return {
        "status": "SUCCESS",
        "symbol": pair.symbol,
        "scalp_strategy_id": pair.scalp_strategy_id,
        "swing_strategy_id": pair.swing_strategy_id,
        "message": f"Strategies assigned to {pair.symbol} successfully.",
    }
