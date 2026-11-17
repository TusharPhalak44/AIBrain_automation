"""Pre-Vetted Vectorized Indicator Helpers for Strategy Lab.

Injected into the strategy execution sandbox:
- atr(df, period=14)
- ema(series, period)
- rsi(series, period=14)
- swing_highs(df, left=3, right=3) & swing_lows(df, left=3, right=3)
- detect_fvg(df)
- detect_liquidity_sweep(df, lookback=20)
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Wilder's True Range and Average True Range (ATR).
    TR = max(High - Low, abs(High - PrevClose), abs(Low - PrevClose))
    """
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Wilder smoothing equivalent to EMA with alpha = 1 / period
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's Relative Strength Index (RSI).
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()

    # Avoid division by zero
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi_series = 100.0 - (100.0 / (1.0 + rs))
    return rsi_series.fillna(50.0)


def swing_highs(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.Series:
    """
    Detect swing highs.
    Returns a Series of high prices where a swing high occurs, with NaN elsewhere.
    A bar at index k is a swing high if its high exceeds the preceding 'left' bars
    and succeeding 'right' bars.
    """
    high = df["high"]
    n = len(df)
    result = pd.Series(np.nan, index=df.index, dtype=float)

    for i in range(left, n - right):
        current = high.iloc[i]
        is_high = True
        for l in range(1, left + 1):
            if high.iloc[i - l] >= current:
                is_high = False
                break
        if is_high:
            for r in range(1, right + 1):
                if high.iloc[i + r] >= current:
                    is_high = False
                    break
        if is_high:
            result.iloc[i] = current

    return result


def swing_lows(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.Series:
    """
    Detect swing lows.
    Returns a Series of low prices where a swing low occurs, with NaN elsewhere.
    """
    low = df["low"]
    n = len(df)
    result = pd.Series(np.nan, index=df.index, dtype=float)

    for i in range(left, n - right):
        current = low.iloc[i]
        is_low = True
        for l in range(1, left + 1):
            if low.iloc[i - l] <= current:
                is_low = False
                break
        if is_low:
            for r in range(1, right + 1):
                if low.iloc[i + r] <= current:
                    is_low = False
                    break
        if is_low:
            result.iloc[i] = current

    return result


def detect_fvg(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect 3-candle Fair Value Gap (FVG) imbalances.
    - Bullish FVG: Candle 1 High < Candle 3 Low (buying gap)
    - Bearish FVG: Candle 1 Low > Candle 3 High (selling gap)

    Returns DataFrame with columns:
    - 'fvg_bullish': bool
    - 'fvg_bearish': bool
    - 'fvg_top': float price ceiling of gap
    - 'fvg_bottom': float price floor of gap
    """
    high = df["high"]
    low = df["low"]

    c1_high = high.shift(2)
    c3_low = low
    c1_low = low.shift(2)
    c3_high = high

    bullish_gap = c3_low > c1_high
    bearish_gap = c1_low > c3_high

    fvg_df = pd.DataFrame(index=df.index)
    fvg_df["fvg_bullish"] = bullish_gap.fillna(False)
    fvg_df["fvg_bearish"] = bearish_gap.fillna(False)
    fvg_df["fvg_top"] = np.where(bullish_gap, c3_low, np.where(bearish_gap, c1_low, np.nan))
    fvg_df["fvg_bottom"] = np.where(bullish_gap, c1_high, np.where(bearish_gap, c3_high, np.nan))

    return fvg_df


def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    Detect Liquidity Sweeps (wick beyond range high/low with close back inside).
    Returns pd.Series:
     1  = Bullish Sweep (Sell-side liquidity swept: swept range low, closed above)
    -1  = Bearish Sweep (Buy-side liquidity swept: swept range high, closed below)
     0  = No sweep detected
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Rolling range prior to current candle
    prior_high = high.shift(1).rolling(window=lookback).max()
    prior_low = low.shift(1).rolling(window=lookback).min()

    bullish_sweep = (low < prior_low) & (close > prior_low)
    bearish_sweep = (high > prior_high) & (close < prior_high)

    sweep_series = pd.Series(0, index=df.index, dtype=int)
    sweep_series[bullish_sweep] = 1
    sweep_series[bearish_sweep] = -1

    return sweep_series


def detect_candlestick_reversals(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Detect Pin Bar Rejections (Hammer / Shooting Star) and Bullish/Bearish Engulfing candles.
    Returns list of active reversal patterns detected on recent candles.
    """
    if len(df) < 5:
        return []

    patterns = []
    c = df.iloc[-1]
    prev = df.iloc[-2]

    c_open, c_high, c_low, c_close = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
    p_open, p_high, p_low, p_close = float(prev["open"]), float(prev["high"]), float(prev["low"]), float(prev["close"])

    body = abs(c_close - c_open)
    rng = max(c_high - c_low, 0.00001)
    upper_wick = c_high - max(c_open, c_close)
    lower_wick = min(c_open, c_close) - c_low

    # 1. Bullish Pin Bar / Hammer (long lower wick, rejection of lows)
    if lower_wick >= 2.0 * max(body, rng * 0.1) and upper_wick <= 0.4 * rng:
        patterns.append({
            "pattern": "PIN_BAR_REJECTION",
            "direction": "BULLISH",
            "key_level": round(c_low, 5),
            "rejection_wick": round(lower_wick, 5),
            "details": f"Bullish hammer rejection at low {c_low:.2f}",
        })

    # 2. Bearish Pin Bar / Shooting Star (long upper wick, rejection of highs)
    if upper_wick >= 2.0 * max(body, rng * 0.1) and lower_wick <= 0.4 * rng:
        patterns.append({
            "pattern": "PIN_BAR_REJECTION",
            "direction": "BEARISH",
            "key_level": round(c_high, 5),
            "rejection_wick": round(upper_wick, 5),
            "details": f"Bearish shooting star rejection at high {c_high:.2f}",
        })

    # 3. Bullish Engulfing (Green body completely engulfs previous Red body)
    if p_close < p_open and c_close > c_open:
        if c_close >= p_open and c_open <= p_close and body > abs(p_close - p_open):
            patterns.append({
                "pattern": "BULLISH_ENGULFING",
                "direction": "BULLISH",
                "key_level": round(c_low, 5),
                "details": f"Bullish engulfing candle overcoming previous red candle ({p_open:.2f} -> {c_close:.2f})",
            })

    # 4. Bearish Engulfing (Red body completely engulfs previous Green body)
    if p_close > p_open and c_close < c_open:
        if c_close <= p_open and c_open >= p_close and body > abs(p_close - p_open):
            patterns.append({
                "pattern": "BEARISH_ENGULFING",
                "direction": "BEARISH",
                "key_level": round(c_high, 5),
                "details": f"Bearish engulfing candle overcoming previous green candle ({p_open:.2f} -> {c_close:.2f})",
            })

    return patterns


def detect_market_structure_shift(df: pd.DataFrame, lookback: int = 15) -> List[Dict[str, Any]]:
    """
    Detect Market Structure Shifts (MSS) & Break of Structure (BOS) via displacement body close.
    """
    if len(df) < lookback + 5:
        return []

    patterns = []
    sh = swing_highs(df, left=2, right=2)
    sl = swing_lows(df, left=2, right=2)

    recent_sh = sh.dropna().iloc[-3:] if len(sh.dropna()) >= 1 else pd.Series()
    recent_sl = sl.dropna().iloc[-3:] if len(sl.dropna()) >= 1 else pd.Series()

    last_close = float(df["close"].iloc[-1])
    last_open = float(df["open"].iloc[-1])
    atr_val = float(atr(df, 14).iloc[-1]) if len(df) >= 14 else 1.0

    # Bullish MSS / BOS: Candle close decisively breaks above recent swing high with displacement
    if not recent_sh.empty:
        prev_swing_h = float(recent_sh.iloc[-1])
        if last_close > prev_swing_h and (last_close - last_open) >= 0.7 * atr_val:
            patterns.append({
                "pattern": "MARKET_STRUCTURE_SHIFT_MSS",
                "direction": "BULLISH",
                "key_level": prev_swing_h,
                "displacement": round(last_close - last_open, 5),
                "details": f"Bullish MSS displacement body close above swing high {prev_swing_h:.2f}",
            })

    # Bearish MSS / BOS: Candle close decisively breaks below recent swing low with displacement
    if not recent_sl.empty:
        prev_swing_l = float(recent_sl.iloc[-1])
        if last_close < prev_swing_l and (last_open - last_close) >= 0.7 * atr_val:
            patterns.append({
                "pattern": "MARKET_STRUCTURE_SHIFT_MSS",
                "direction": "BEARISH",
                "key_level": prev_swing_l,
                "displacement": round(last_open - last_close, 5),
                "details": f"Bearish MSS displacement body close below swing low {prev_swing_l:.2f}",
            })

    return patterns


def detect_order_blocks(df: pd.DataFrame, lookback: int = 20) -> List[Dict[str, Any]]:
    """
    Detect institutional Order Blocks (OB) preceding explosive displacement moves.
    """
    if len(df) < 10:
        return []

    obs = []
    atr_val = float(atr(df, 14).iloc[-1]) if len(df) >= 14 else 1.0
    n = len(df)

    # Search backwards for the most recent unmitigated Order Blocks
    for i in range(max(1, n - lookback), n - 2):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]

        c1_open, c1_close = float(c1["open"]), float(c1["close"])
        c1_high, c1_low = float(c1["high"]), float(c1["low"])

        # Bullish OB: Bearish candle (c1) followed by strong multi-candle displacement upward
        if c1_close < c1_open:
            displacement = float(c3["close"]) - c1_open
            if displacement >= 1.5 * atr_val:
                # Check mitigation: has price subsequently traded completely below c1_low?
                subsequent_lows = df["low"].iloc[i + 3:] if i + 3 < n else pd.Series()
                mitigated = (subsequent_lows < c1_low).any() if not subsequent_lows.empty else False
                if not mitigated:
                    obs.append({
                        "pattern": "SUPPLY_DEMAND_ORDER_BLOCK",
                        "direction": "BULLISH",
                        "zone_low": round(c1_low, 5),
                        "zone_high": round(c1_high, 5),
                        "details": f"Bullish Demand Order Block [{c1_low:.2f} - {c1_high:.2f}]",
                    })

        # Bearish OB: Bullish candle (c1) followed by strong multi-candle displacement downward
        if c1_close > c1_open:
            displacement = c1_open - float(c3["close"])
            if displacement >= 1.5 * atr_val:
                subsequent_highs = df["high"].iloc[i + 3:] if i + 3 < n else pd.Series()
                mitigated = (subsequent_highs > c1_high).any() if not subsequent_highs.empty else False
                if not mitigated:
                    obs.append({
                        "pattern": "SUPPLY_DEMAND_ORDER_BLOCK",
                        "direction": "BEARISH",
                        "zone_low": round(c1_low, 5),
                        "zone_high": round(c1_high, 5),
                        "details": f"Bearish Supply Order Block [{c1_low:.2f} - {c1_high:.2f}]",
                    })

    # Return the 2 most recent active unmitigated Order Blocks
    return obs[-2:] if obs else []


def detect_volatility_squeeze(df: pd.DataFrame, period: int = 20) -> List[Dict[str, Any]]:
    """
    Detect Volatility Squeeze (Bollinger Bands contracting inside Keltner Channel) and Squeeze Breakout.
    """
    if len(df) < period + 5:
        return []

    close = df["close"]
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()

    # Bollinger Bands 2.0 std
    bb_upper = ma + (2.0 * std)
    bb_lower = ma - (2.0 * std)

    # Keltner Channel 1.5 ATR
    atr_series = atr(df, period)
    kc_upper = ma + (1.5 * atr_series)
    kc_lower = ma - (1.5 * atr_series)

    # Squeeze is on when BB is inside KC
    squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)
    is_squeeze_now = bool(squeeze_on.iloc[-1])
    was_squeeze_prev = bool(squeeze_on.iloc[-2]) if len(squeeze_on) >= 2 else False

    patterns = []
    last_close = float(close.iloc[-1])

    if is_squeeze_now:
        patterns.append({
            "pattern": "VOLATILITY_SQUEEZE_BREAKOUT",
            "direction": "NEUTRAL",
            "key_level": round(float(ma.iloc[-1]), 5),
            "details": f"Active volatility compression squeeze (BB inside Keltner). Explosive breakout impending.",
        })
    elif was_squeeze_prev and not is_squeeze_now:
        # Fired breakout!
        direction = "BULLISH" if last_close > float(ma.iloc[-1]) else "BEARISH"
        patterns.append({
            "pattern": "VOLATILITY_SQUEEZE_BREAKOUT",
            "direction": direction,
            "key_level": round(last_close, 5),
            "details": f"Squeeze expansion breakout fired {direction}!",
        })

    return patterns


def scan_all_price_action_patterns(
    df: pd.DataFrame,
    timeframe: str = "M15",
    pdh: Optional[float] = None,
    pdl: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Orchestrate multi-pattern pure price-action detection across candlestick arrays.
    Returns structured pattern findings with timeframes, direction, and key levels.
    """
    if df is None or len(df) < 5:
        return []

    all_patterns = []

    # 1. Candlestick reversals (Pin bar, Engulfing)
    for p in detect_candlestick_reversals(df):
        p["timeframe"] = timeframe
        all_patterns.append(p)

    # 2. Market Structure Shifts & BOS
    for p in detect_market_structure_shift(df):
        p["timeframe"] = timeframe
        all_patterns.append(p)

    # 3. Supply/Demand Order Blocks
    for p in detect_order_blocks(df):
        p["timeframe"] = timeframe
        all_patterns.append(p)

    # 4. Volatility Squeeze
    for p in detect_volatility_squeeze(df):
        p["timeframe"] = timeframe
        all_patterns.append(p)

    # 5. Liquidity sweeps of PDH / PDL or range
    sweeps = detect_liquidity_sweep(df, lookback=20)
    if not sweeps.empty and sweeps.iloc[-1] != 0:
        sweep_val = int(sweeps.iloc[-1])
        c_low = float(df["low"].iloc[-1])
        c_high = float(df["high"].iloc[-1])
        if sweep_val == 1:
            all_patterns.append({
                "pattern": "LIQUIDITY_SWEEP_STOP_HUNT",
                "timeframe": timeframe,
                "direction": "BULLISH",
                "key_level": round(pdl if pdl and pdl > 0 else c_low, 5),
                "details": f"Sell-side liquidity sweep rejection on {timeframe} at {c_low:.2f}",
            })
        elif sweep_val == -1:
            all_patterns.append({
                "pattern": "LIQUIDITY_SWEEP_STOP_HUNT",
                "timeframe": timeframe,
                "direction": "BEARISH",
                "key_level": round(pdh if pdh and pdh > 0 else c_high, 5),
                "details": f"Buy-side liquidity sweep rejection on {timeframe} at {c_high:.2f}",
            })

    # 6. Fair Value Gap retest
    fvg_df = detect_fvg(df)
    if not fvg_df.empty and len(fvg_df) >= 3:
        cur_close = float(df["close"].iloc[-1])
        # Check if recent candle touches into an active FVG
        for k in range(-5, -1):
            if k >= -len(fvg_df):
                if fvg_df["fvg_bullish"].iloc[k]:
                    top = float(fvg_df["fvg_top"].iloc[k])
                    bot = float(fvg_df["fvg_bottom"].iloc[k])
                    if bot <= cur_close <= top:
                        all_patterns.append({
                            "pattern": "FAIR_VALUE_GAP_RETEST",
                            "timeframe": timeframe,
                            "direction": "BULLISH",
                            "zone_low": bot,
                            "zone_high": top,
                            "details": f"Price actively testing bullish Fair Value Gap zone [{bot:.2f} - {top:.2f}]",
                        })
                        break
                elif fvg_df["fvg_bearish"].iloc[k]:
                    top = float(fvg_df["fvg_top"].iloc[k])
                    bot = float(fvg_df["fvg_bottom"].iloc[k])
                    if bot <= cur_close <= top:
                        all_patterns.append({
                            "pattern": "FAIR_VALUE_GAP_RETEST",
                            "timeframe": timeframe,
                            "direction": "BEARISH",
                            "zone_low": bot,
                            "zone_high": top,
                            "details": f"Price actively testing bearish Fair Value Gap zone [{bot:.2f} - {top:.2f}]",
                        })
                        break

    return all_patterns


