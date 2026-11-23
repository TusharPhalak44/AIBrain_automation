"""Built-In Starter Strategies for XM MT5 (Forex Majors, Gold, BTC, ETH, SOL).

Codified into 4 pre-vetted StrategyScript models:
1. Liquidity Sweep + FVG Reversal (SCALP)
2. London & NY Session Breakout (SCALP)
3. H1/H4 EMA Trend Pullback + ATR (SWING)
4. 24/7 Crypto Volatility Squeeze (BOTH)
"""

from typing import Any, Dict, List

STRATEGY_LIQUIDITY_SWEEP_FVG = '''DEFAULT_PARAMS = {
    "sweep_lookback": 20,
    "atr_period": 14,
    "atr_sl_mult": 1.2,
    "rr_tp1": 2.0,
    "rr_tp2": 3.5,
}

def evaluate(df, params):
    """
    Liquidity Sweep + Fair Value Gap (FVG) Reversal Strategy (SCALP).
    Identifies high-probability market structure reversals when smart money
    sweeps liquidity pools beyond key swing points and fills an imbalance.
    """
    if len(df) < params.get("sweep_lookback", 20) + 5:
        return None

    # Calculate indicators via injected helpers
    sweeps = detect_liquidity_sweep(df, lookback=params.get("sweep_lookback", 20))
    fvg = detect_fvg(df)
    atr_vals = atr(df, period=params.get("atr_period", 14))

    last_idx = df.index[-1]
    current_close = float(df["close"].iloc[-1])
    current_low = float(df["low"].iloc[-1])
    current_high = float(df["high"].iloc[-1])
    current_atr = float(atr_vals.iloc[-1])

    recent_sweep = int(sweeps.iloc[-1])
    if recent_sweep == 0 and len(sweeps) >= 2:
        # Check if swept 1 bar prior
        recent_sweep = int(sweeps.iloc[-2])

    has_bull_fvg = bool(fvg["fvg_bullish"].iloc[-1] or fvg["fvg_bullish"].iloc[-2])
    has_bear_fvg = bool(fvg["fvg_bearish"].iloc[-1] or fvg["fvg_bearish"].iloc[-2])

    sl_buffer = current_atr * params.get("atr_sl_mult", 1.2)
    rr_tp1 = max(2.0, float(params.get("rr_tp1", 2.0)))
    rr_tp2 = max(3.5, float(params.get("rr_tp2", 3.5)))

    # Bullish Setup: Sell-side liquidity sweep + Bullish reversal/FVG
    if recent_sweep == 1 and (has_bull_fvg or current_close > float(df["open"].iloc[-1])):
        entry = current_close
        sl = round(current_low - sl_buffer, 5)
        risk = entry - sl
        if risk > 0:
            tp1 = round(entry + (risk * rr_tp1), 5)
            tp2 = round(entry + (risk * rr_tp2), 5)
            return {
                "signal": "BUY",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Sell-side sweep confirmed with bullish FVG imbalance fill.",
            }

    # Bearish Setup: Buy-side liquidity sweep + Bearish reversal/FVG
    elif recent_sweep == -1 and (has_bear_fvg or current_close < float(df["open"].iloc[-1])):
        entry = current_close
        sl = round(current_high + sl_buffer, 5)
        risk = sl - entry
        if risk > 0:
            tp1 = round(entry - (risk * rr_tp1), 5)
            tp2 = round(entry - (risk * rr_tp2), 5)
            return {
                "signal": "SELL",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Buy-side sweep confirmed with bearish FVG imbalance fill.",
            }

    return None
'''


STRATEGY_SESSION_BREAKOUT = '''DEFAULT_PARAMS = {
    "session_range_bars": 12,
    "atr_period": 14,
    "rr_tp1": 2.0,
    "rr_tp2": 3.0,
}

def evaluate(df, params):
    """
    London & NY Session Breakout Strategy (SCALP).
    Identifies momentum expansion when price breaks out of the pre-session
    range during peak institutional volume windows.
    """
    lookback = params.get("session_range_bars", 12)
    if len(df) < lookback + 5:
        return None

    range_slice = df.iloc[-lookback-1 : -1]
    range_high = float(range_slice["high"].max())
    range_low = float(range_slice["low"].min())
    range_mid = (range_high + range_low) / 2.0

    current_close = float(df["close"].iloc[-1])
    current_open = float(df["open"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])

    atr_vals = atr(df, period=params.get("atr_period", 14))
    current_atr = float(atr_vals.iloc[-1])
    rr_tp1 = max(2.0, float(params.get("rr_tp1", 2.0)))
    rr_tp2 = max(3.0, float(params.get("rr_tp2", 3.0)))

    # Bullish Breakout above range high
    if prev_close <= range_high and current_close > range_high:
        entry = current_close
        sl = round(range_mid, 5)
        risk = entry - sl
        if risk > current_atr * 0.5:
            tp1 = round(entry + (risk * rr_tp1), 5)
            tp2 = round(entry + (risk * rr_tp2), 5)
            return {
                "signal": "BUY",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Institutional session range high breakout expansion.",
            }

    # Bearish Breakout below range low
    elif prev_close >= range_low and current_close < range_low:
        entry = current_close
        sl = round(range_mid, 5)
        risk = sl - entry
        if risk > current_atr * 0.5:
            tp1 = round(entry - (risk * rr_tp1), 5)
            tp2 = round(entry - (risk * rr_tp2), 5)
            return {
                "signal": "SELL",
                "mode": "SCALP",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Institutional session range low breakout expansion.",
            }

    return None
'''


STRATEGY_EMA_TREND_PULLBACK = '''DEFAULT_PARAMS = {
    "fast_ema": 21,
    "slow_ema": 50,
    "atr_period": 14,
    "atr_sl_mult": 1.5,
    "rr_tp1": 2.8,
    "rr_tp2": 4.5,
}

def evaluate(df, params):
    """
    H1/H4 EMA Trend Pullback + ATR Strategy (SWING).
    Trades institutional trend continuation when price pulls back into the dynamic
    value zone of EMA21 / EMA50 and prints an ATR-confirmed price rejection.
    """
    if len(df) < params.get("slow_ema", 50) + 10:
        return None

    close_series = df["close"]
    fast = ema(close_series, params.get("fast_ema", 21))
    slow = ema(close_series, params.get("slow_ema", 50))
    atr_vals = atr(df, params.get("atr_period", 14))

    curr_close = float(close_series.iloc[-1])
    curr_low = float(df["low"].iloc[-1])
    curr_high = float(df["high"].iloc[-1])
    curr_fast = float(fast.iloc[-1])
    curr_slow = float(slow.iloc[-1])
    curr_atr = float(atr_vals.iloc[-1])

    sl_dist = curr_atr * params.get("atr_sl_mult", 1.5)
    rr_tp1 = max(2.8, float(params.get("rr_tp1", 2.8)))
    rr_tp2 = max(4.5, float(params.get("rr_tp2", 4.5)))

    # Uptrend Condition: Fast EMA > Slow EMA and price pulled back to Fast EMA
    if curr_fast > curr_slow and curr_low <= curr_fast and curr_close > curr_fast:
        entry = curr_close
        sl = round(curr_low - sl_dist, 5)
        risk = entry - sl
        if risk > 0:
            tp1 = round(entry + (risk * rr_tp1), 5)
            tp2 = round(entry + (risk * rr_tp2), 5)
            return {
                "signal": "BUY",
                "mode": "SWING",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Uptrend EMA value zone pullback rejection confirmed.",
            }

    # Downtrend Condition: Fast EMA < Slow EMA and price pulled back to Fast EMA
    elif curr_fast < curr_slow and curr_high >= curr_fast and curr_close < curr_fast:
        entry = curr_close
        sl = round(curr_high + sl_dist, 5)
        risk = sl - entry
        if risk > 0:
            tp1 = round(entry - (risk * rr_tp1), 5)
            tp2 = round(entry - (risk * rr_tp2), 5)
            return {
                "signal": "SELL",
                "mode": "SWING",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Downtrend EMA value zone pullback rejection confirmed.",
            }

    return None
'''


STRATEGY_CRYPTO_VOLATILITY_SQUEEZE = '''DEFAULT_PARAMS = {
    "bollinger_period": 20,
    "bollinger_std": 2.0,
    "rsi_period": 14,
    "atr_period": 14,
    "rr_tp1": 2.0,
    "rr_tp2": 3.5,
}

def evaluate(df, params):
    """
    24/7 Crypto Volatility Squeeze Strategy (BOTH Scalp & Swing).
    Specifically tuned for 24/7 crypto CFDs (BTCUSD#, ETHUSD#, SOLUSD#).
    Detects volatility compression squeezes followed by explosive expansion impulses.
    """
    period = params.get("bollinger_period", 20)
    if len(df) < period + 10:
        return None

    close = df["close"]
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper_band = sma + (params.get("bollinger_std", 2.0) * std)
    lower_band = sma - (params.get("bollinger_std", 2.0) * std)

    rsi_vals = rsi(close, params.get("rsi_period", 14))
    atr_vals = atr(df, params.get("atr_period", 14))

    curr_close = float(close.iloc[-1])
    curr_upper = float(upper_band.iloc[-1])
    curr_lower = float(lower_band.iloc[-1])
    curr_rsi = float(rsi_vals.iloc[-1])
    curr_atr = float(atr_vals.iloc[-1])

    prev_close = float(close.iloc[-2])
    prev_upper = float(upper_band.iloc[-2])
    prev_lower = float(lower_band.iloc[-2])

    rr_tp1_mult = max(2.0, float(params.get("rr_tp1", 2.0)))
    rr_tp2_mult = max(3.5, float(params.get("rr_tp2", 3.5)))

    # Bullish Volatility Expansion
    if prev_close <= prev_upper and curr_close > curr_upper and curr_rsi > 55.0:
        entry = curr_close
        sl = round(curr_close - (1.5 * curr_atr), 5)
        risk = entry - sl
        if risk > 0:
            tp1 = round(entry + (risk * rr_tp1_mult), 5)
            tp2 = round(entry + (risk * rr_tp2_mult), 5)
            return {
                "signal": "BUY",
                "mode": "SWING",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Crypto upper volatility squeeze expansion breakout with RSI momentum.",
            }

    # Bearish Volatility Expansion
    elif prev_close >= prev_lower and curr_close < curr_lower and curr_rsi < 45.0:
        entry = curr_close
        sl = round(curr_close + (1.5 * curr_atr), 5)
        risk = sl - entry
        if risk > 0:
            tp1 = round(entry - (risk * rr_tp1_mult), 5)
            tp2 = round(entry - (risk * rr_tp2_mult), 5)
            return {
                "signal": "SELL",
                "mode": "SWING",
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "tp2": tp2,
                "reason": "Crypto lower volatility squeeze expansion breakdown with RSI momentum.",
            }

    return None
'''


BUILTIN_STRATEGIES: List[Dict[str, Any]] = [
    {
        "name": "Liquidity Sweep + FVG Reversal",
        "description": "Exploits institutional liquidity sweeps past key range highs/lows with 3-candle Fair Value Gap imbalance entries.",
        "target_mode": "SCALP",
        "python_code": STRATEGY_LIQUIDITY_SWEEP_FVG,
        "default_params_json": '{"sweep_lookback": 20, "atr_period": 14, "atr_sl_mult": 1.2, "rr_tp1": 2.0, "rr_tp2": 3.5}',
        "is_builtin": True,
    },
    {
        "name": "London & NY Session Breakout",
        "description": "Momentum expansion strategy capturing session open breakouts of pre-session consolidation ranges.",
        "target_mode": "SCALP",
        "python_code": STRATEGY_SESSION_BREAKOUT,
        "default_params_json": '{"session_range_bars": 12, "atr_period": 14, "rr_tp1": 2.0, "rr_tp2": 3.0}',
        "is_builtin": True,
    },
    {
        "name": "H1/H4 EMA Trend Pullback + ATR",
        "description": "Higher-timeframe swing trend continuation strategy trading EMA21/50 dynamic value zone rejections.",
        "target_mode": "SWING",
        "python_code": STRATEGY_EMA_TREND_PULLBACK,
        "default_params_json": '{"fast_ema": 21, "slow_ema": 50, "atr_period": 14, "atr_sl_mult": 1.5, "rr_tp1": 2.8, "rr_tp2": 4.5}',
        "is_builtin": True,
    },
    {
        "name": "24/7 Crypto Volatility Squeeze",
        "description": "Tailored for 24/7 Crypto CFDs (BTC, ETH, SOL) identifying explosive volatility breakouts from Bollinger compression squeezes.",
        "target_mode": "BOTH",
        "python_code": STRATEGY_CRYPTO_VOLATILITY_SQUEEZE,
        "default_params_json": '{"bollinger_period": 20, "bollinger_std": 2.0, "rsi_period": 14, "atr_period": 14, "rr_tp1": 2.8, "rr_tp2": 4.5}',
        "is_builtin": True,
    },
]


def seed_builtin_strategies(session) -> int:
    """Seed the 4 built-in starter strategies into StrategyScript table if missing, or update them."""
    from backend.app.db.models import StrategyScript
    from backend.app.core.clock_sync import now_utc

    seeded_count = 0
    for strat in BUILTIN_STRATEGIES:
        existing = session.query(StrategyScript).filter_by(name=strat["name"]).first()
        if not existing:
            script = StrategyScript(
                name=strat["name"],
                description=strat["description"],
                target_mode=strat["target_mode"],
                python_code=strat["python_code"],
                default_params_json=strat["default_params_json"],
                is_builtin=True,
                created_at_utc=now_utc(),
            )
            session.add(script)
            seeded_count += 1
        else:
            existing.python_code = strat["python_code"]
            existing.default_params_json = strat["default_params_json"]
            existing.target_mode = strat["target_mode"]
            seeded_count += 1
            seeded_count += 1

    if seeded_count > 0:
        session.commit()
    return seeded_count

