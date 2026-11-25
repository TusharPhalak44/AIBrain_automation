"""Live Candlestick Feed & Institutional Price-Action Overlays Endpoint."""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
import pandas as pd

from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.session import get_db
from backend.app.db.models import TradeLedger
from backend.app.mt5_bridge.connector import mt5_connector
from backend.app.strategy_lab.backtester import fetch_mt5_ohlcv
from backend.app.strategy_lab.indicators import swing_highs, swing_lows, detect_fvg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candles", tags=["Candles & Chart Feeds"])


@router.get("/{symbol}")
async def get_candles_and_overlays(
    symbol: str,
    timeframe: str = Query("M15", description="Candle timeframe: M1, M5, M15, H1, H4, D1"),
    count: int = Query(250, ge=10, le=1000, description="Number of bars to fetch"),
    db: Session = Depends(get_db),
):
    """
    Fetch live OHLCV candlestick bars and institutional technical overlays for TradingView charts.
    Strictly ZERO mock/fake fallback candles:
    If MT5 is offline/disconnected, returns MT5_DISCONNECTED status cleanly.
    """
    resolved_sym = resolve_broker_symbol(symbol, db)
    tf_upper = timeframe.upper()

    # 1. Check MT5 connection status
    if not mt5_connector.is_connected:
        return {
            "status": "MT5_DISCONNECTED",
            "symbol": resolved_sym,
            "timeframe": tf_upper,
            "candles": [],
            "overlays": {},
            "message": f"MT5 terminal is disconnected. Live candles for {resolved_sym} are unavailable.",
        }

    # 2. Fetch live OHLCV bars from MT5
    df = await fetch_mt5_ohlcv(resolved_sym, tf_upper, count)
    if df is None or df.empty:
        return {
            "status": "NO_DATA",
            "symbol": resolved_sym,
            "timeframe": tf_upper,
            "candles": [],
            "overlays": {},
            "message": f"No candle data returned from MT5 for {resolved_sym} on {tf_upper}.",
        }

    # 3. Format candles for TradingView Lightweight Charts (Unix timestamp in seconds, strictly ascending & unique)
    candles_by_time: Dict[int, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        ts_val = row["time"]
        if hasattr(ts_val, "timestamp"):
            ts_sec = int(ts_val.timestamp())
        else:
            ts_sec = int(ts_val)

        candles_by_time[ts_sec] = {
            "time": ts_sec,
            "open": round(float(row["open"]), 5),
            "high": round(float(row["high"]), 5),
            "low": round(float(row["low"]), 5),
            "close": round(float(row["close"]), 5),
            "volume": float(row.get("tick_volume", row.get("volume", 0.0))),
        }

    candles: List[Dict[str, Any]] = [candles_by_time[k] for k in sorted(candles_by_time.keys())]

    # 4. Compute price-action overlays
    highs = swing_highs(df, left=3, right=3).dropna().tail(5).tolist()
    lows = swing_lows(df, left=3, right=3).dropna().tail(5).tolist()

    # PDH / PDL (Previous Day High / Low)
    pdh, pdl = None, None
    try:
        d1_df = await fetch_mt5_ohlcv(resolved_sym, "D1", 5)
        if d1_df is not None and len(d1_df) >= 2:
            prev_day = d1_df.iloc[-2]
            pdh = float(prev_day["high"])
            pdl = float(prev_day["low"])
    except Exception:
        pass

    # Fair Value Gaps (FVGs)
    recent_fvgs: List[Dict[str, Any]] = []
    try:
        fvg_df = detect_fvg(df)
        if fvg_df is not None and not fvg_df.empty:
            active_fvg = fvg_df[fvg_df["fvg_bullish"] | fvg_df["fvg_bearish"]].tail(5)
            for _, r in active_fvg.iterrows():
                f_type = "BULLISH_FVG" if r["fvg_bullish"] else "BEARISH_FVG"
                top = float(r["fvg_top"]) if not pd.isna(r["fvg_top"]) else 0.0
                bottom = float(r["fvg_bottom"]) if not pd.isna(r["fvg_bottom"]) else 0.0
                recent_fvgs.append({
                    "type": f_type,
                    "top": round(top, 5),
                    "bottom": round(bottom, 5),
                    "size": round(abs(top - bottom), 5),
                })
    except Exception as e:
        logger.warning(f"FVG calculation error for {resolved_sym}: {e}")

    # Active / Planned trades from TradeLedger for chart price lines
    clean_sym = resolved_sym.rstrip("#")
    trades = (
        db.query(TradeLedger)
        .filter(
            (TradeLedger.symbol == resolved_sym) | (TradeLedger.symbol == clean_sym),
            TradeLedger.status.in_(["OPEN", "PLANNED"]),
        )
        .all()
    )

    trade_overlays: List[Dict[str, Any]] = []
    for t in trades:
        trade_overlays.append({
            "id": t.id,
            "position_id": t.position_id,
            "magic_number": t.magic_number,
            "mode": t.mode,
            "direction": t.direction,
            "status": t.status,
            "lots": float(t.lots),
            "entry_price": float(t.entry_price),
            "sl": float(t.sl),
            "tp1": float(t.tp1),
            "tp2": float(t.tp2),
            "opened_at_utc": t.opened_at_utc.isoformat() if t.opened_at_utc else None,
        })

    overlays = {
        "swing_highs": [round(float(h), 5) for h in highs],
        "swing_lows": [round(float(l), 5) for l in lows],
        "pdh": round(pdh, 5) if pdh is not None else None,
        "pdl": round(pdl, 5) if pdl is not None else None,
        "fvgs": recent_fvgs,
        "trades": trade_overlays,
    }

    return {
        "status": "OK",
        "symbol": resolved_sym,
        "timeframe": tf_upper,
        "candles": candles,
        "overlays": overlays,
    }

