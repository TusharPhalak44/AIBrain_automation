"""Trading Pair Bot Settings & Specifications Routes."""

from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.models import TradingPairBot
from backend.app.db.session import get_db

router = APIRouter(prefix="/pairs", tags=["Trading Pairs"])


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
