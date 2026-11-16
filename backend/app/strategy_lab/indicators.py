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

