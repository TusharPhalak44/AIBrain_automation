"""Multi-Timeframe Price Action & Cross-Pair Context Packet Compiler.

Compiles:
1. Multi-timeframe price action bars (M5, M15, H1, H4, D1).
2. Deterministic structural context: EMA(21/50/200) trend alignment, ATR(14), RSI(14),
   Support/Resistance levels (swing_highs/lows), Fair Value Gaps (FVG), Liquidity Sweeps,
   and Previous Day High/Low (PDH/PDL).
3. Assigned Scalp and Swing sandbox strategy signals.
4. Cross-pair USD and Crypto momentum snapshot across XM Global instruments.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.session import SessionLocal
from backend.app.db.models import TradingPairBot, StrategyScript
from backend.app.mt5_bridge.connector import mt5_connector
from backend.app.mt5_bridge.mt5_actor import mt5_actor
from backend.app.strategy_lab.indicators import (
    atr,
    ema,
    rsi,
    swing_highs,
    swing_lows,
    detect_fvg,
    detect_liquidity_sweep,
    scan_all_price_action_patterns,
)
from backend.app.strategy_lab.sandbox import StrategySandbox
from backend.app.ai_brain.news_guard import news_guard, NewsBlackoutResult
from backend.app.ai_brain.instruments import (
    INSTRUMENT_UNIVERSE,
    resolve_marketwatch_symbol,
    is_symbol_trading_open,
)
from backend.app.ai_brain.cache_manager import cache_manager

logger = logging.getLogger(__name__)

# Multi-Asset High-Liquidity Universe (Forex, Commodities, Crypto)
XM_ACTIVE_SYMBOLS = list(INSTRUMENT_UNIVERSE.keys())

TIMEFRAME_MAP = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "H1": 16385,
    "H4": 16388,
    "D1": 16408,
}


@dataclass
class TimeframeAnalysis:
    timeframe: str
    bias: str  # BULLISH, BEARISH, CHOP
    close: float
    ema21: float
    ema50: float
    ema200: Optional[float]
    rsi14: float
    atr14: float
    key_highs: List[float] = field(default_factory=list)
    key_lows: List[float] = field(default_factory=list)
    recent_fvgs: List[Dict[str, Any]] = field(default_factory=list)
    recent_sweeps: List[Dict[str, Any]] = field(default_factory=list)
    detected_patterns: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MarketPacket:
    symbol: str
    asset_class: str
    timestamp_utc: str
    timestamp_ist: str
    bid: float
    ask: float
    spread_points: int
    pdh: Optional[float]
    pdl: Optional[float]
    swing_bias_h4_d1: str  # BULLISH, BEARISH, CHOP
    scalp_bias_m15_h1: str  # BULLISH, BEARISH, CHOP
    timeframe_breakdown: Dict[str, Any]
    candidate_signals: Dict[str, Any]  # scalp_signal, swing_signal
    cross_pair_momentum: Dict[str, Any]
    news_blackout: Dict[str, Any]
    detected_patterns: List[Dict[str, Any]] = field(default_factory=list)
    session_tag: str = "ALL"
    rollover_spread_guard_active: bool = False
    cme_gap_status: Optional[str] = None
    intermarket_liquidity_impulse: str = "NEUTRAL"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MarketPacketCompiler:
    """Collects multi-timeframe bars, calculates indicator structures, and compiles packets."""

    async def fetch_timeframe_bars(
        self,
        symbol: str,
        timeframe: str = "H1",
        count: int = 150,
    ) -> Optional[pd.DataFrame]:
        """Pull live historical bars from connected MT5 terminal with symbol suffix fallback."""
        cache_key = f"{symbol}_{timeframe}_{count}"
        cached_df = cache_manager.get_df(cache_key, max_age_seconds=15)
        if cached_df is not None:
            return cached_df

        if not mt5_connector.is_connected:
            return None

        try:
            import MetaTrader5 as mt5

            tf_val = TIMEFRAME_MAP.get(timeframe.upper(), mt5.TIMEFRAME_H1)
            resolved_sym = resolve_marketwatch_symbol(symbol)
            clean_sym = symbol.rstrip("#")
            candidates = [resolved_sym, symbol, clean_sym, f"{clean_sym}#"]
            seen = set()
            ordered_candidates = [s for s in candidates if not (s in seen or seen.add(s))]

            def _fetch():
                if not mt5.terminal_info():
                    mt5.initialize()
                for s in ordered_candidates:
                    mt5.symbol_select(s, True)
                    rates = mt5.copy_rates_from_pos(s, tf_val, 0, count)
                    if rates is not None and len(rates) > 0:
                        df = pd.DataFrame(rates)
                        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                        return df
                return None

            result_df = await mt5_actor.run_quote(_fetch)
            if result_df is not None:
                cache_manager.store_df(cache_key, result_df)
            return result_df
        except Exception as e:
            logger.debug(f"Failed to fetch MT5 historical bars for {symbol} ({timeframe}): {e}")
            return None

    async def fetch_live_tick(self, symbol: str) -> Tuple[float, float, int]:
        """Fetch current bid, ask, and spread points from MT5 with symbol suffix fallback."""
        if not mt5_connector.is_connected:
            return 0.0, 0.0, 0

        try:
            import MetaTrader5 as mt5

            resolved_sym = resolve_marketwatch_symbol(symbol)
            clean_sym = symbol.rstrip("#")
            candidates = [resolved_sym, symbol, clean_sym, f"{clean_sym}#"]
            seen = set()
            ordered_candidates = [s for s in candidates if not (s in seen or seen.add(s))]

            def _get_tick():
                if not mt5.terminal_info():
                    mt5.initialize()
                for s in ordered_candidates:
                    mt5.symbol_select(s, True)
                    tick = mt5.symbol_info_tick(s)
                    info = mt5.symbol_info(s)
                    if tick and info:
                        digits = int(info.digits) if info else 2
                        spread = int(info.spread) if info and info.spread else (round((tick.ask - tick.bid) * (10 ** digits)) if digits else 0)
                        return float(tick.bid), float(tick.ask), int(spread)
                    elif info and info.bid and info.ask:
                        return float(info.bid), float(info.ask), int(info.spread if info.spread else 0)
                return 0.0, 0.0, 0

            return await mt5_actor.run_quote(_get_tick)
        except Exception:
            return 0.0, 0.0, 0

    def analyze_single_timeframe(self, df: pd.DataFrame, timeframe_label: str) -> TimeframeAnalysis:
        """Calculate technical indicators, S/R zones, FVGs, sweeps, and EMA bias on a DataFrame."""
        if df is None or len(df) < 5:
            return TimeframeAnalysis(
                timeframe=timeframe_label,
                bias="NEUTRAL",
                close=0.0,
                ema21=0.0,
                ema50=0.0,
                ema200=None,
                rsi14=50.0,
                atr14=0.0,
            )

        c = df["close"]
        current_close = float(c.iloc[-1])

        # Indicator calculations
        ema21_series = ema(c, 21)
        ema50_series = ema(c, 50)
        e21 = float(ema21_series.iloc[-1])
        e50 = float(ema50_series.iloc[-1])

        e200 = None
        if len(df) >= 200:
            ema200_series = ema(c, 200)
            e200 = float(ema200_series.iloc[-1])

        # Bias determination
        if e200 is not None:
            if current_close > e21 > e50 > e200:
                bias = "BULLISH"
            elif current_close < e21 < e50 < e200:
                bias = "BEARISH"
            else:
                bias = "CHOP"
        else:
            if current_close > e21 > e50:
                bias = "BULLISH"
            elif current_close < e21 < e50:
                bias = "BEARISH"
            else:
                bias = "CHOP"

        # RSI & ATR
        rsi_series = rsi(c, 14)
        current_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 and not pd.isna(rsi_series.iloc[-1]) else 50.0

        atr_series = atr(df, 14)
        current_atr = float(atr_series.iloc[-1]) if len(atr_series) > 0 and not pd.isna(atr_series.iloc[-1]) else 0.0

        # S/R Levels (swing highs & lows)
        highs = swing_highs(df, left=3, right=3).dropna().tail(3).tolist()
        lows = swing_lows(df, left=3, right=3).dropna().tail(3).tolist()

        # FVGs
        fvg_df = detect_fvg(df)
        recent_fvgs = []
        if fvg_df is not None and not fvg_df.empty:
            active_fvg = fvg_df[fvg_df["fvg_bullish"] | fvg_df["fvg_bearish"]].tail(3)
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

        # Liquidity Sweeps
        sweep_series = detect_liquidity_sweep(df, lookback=15)
        recent_sweeps = []
        if sweep_series is not None and not sweep_series.empty:
            active_sweeps = sweep_series[sweep_series != 0].tail(2)
            for idx, val in active_sweeps.items():
                s_type = "BULLISH_SWEEP" if val == 1 else "BEARISH_SWEEP"
                level = float(df["low"].loc[idx]) if val == 1 else float(df["high"].loc[idx])
                recent_sweeps.append({
                    "type": s_type,
                    "level": round(level, 5),
                })

        # Analyze single timeframe price action patterns
        patterns = scan_all_price_action_patterns(df, timeframe=timeframe_label)

        return TimeframeAnalysis(
            timeframe=timeframe_label,
            bias=bias,
            close=current_close,
            ema21=round(e21, 5),
            ema50=round(e50, 5),
            ema200=round(e200, 5) if e200 is not None else None,
            rsi14=round(current_rsi, 2),
            atr14=round(current_atr, 5),
            key_highs=[round(h, 5) for h in highs],
            key_lows=[round(l, 5) for l in lows],
            recent_fvgs=recent_fvgs,
            recent_sweeps=recent_sweeps,
            detected_patterns=patterns,
        )

    def extract_pdh_pdl(self, df_d1: Optional[pd.DataFrame]) -> Tuple[Optional[float], Optional[float]]:
        """Extract Previous Day High and Low from D1 dataframe."""
        if df_d1 is None or len(df_d1) < 2:
            return None, None
        prev_bar = df_d1.iloc[-2]
        return float(prev_bar["high"]), float(prev_bar["low"])

    def evaluate_candidate_signals(
        self,
        symbol: str,
        df_m15: Optional[pd.DataFrame],
        df_h1: Optional[pd.DataFrame],
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate pair's assigned scalp and swing strategies in StrategySandbox.
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        signals = {"scalp_signal": None, "swing_signal": None}

        try:
            pair = db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == symbol) | (TradingPairBot.symbol == f"{symbol}#")
            ).first()

            if not pair:
                return signals

            # 1. Scalp Strategy
            if pair.scalp_enabled and pair.scalp_strategy_id and df_m15 is not None and len(df_m15) >= 20:
                strat = db.query(StrategyScript).filter_by(id=pair.scalp_strategy_id).first()
                if strat:
                    try:
                        sandbox = StrategySandbox(strat.python_code)
                        params = json.loads(strat.default_params_json) if strat.default_params_json else {}
                        sig = sandbox.evaluate(df_m15, params=params)
                        if sig and sig.get("signal"):
                            signals["scalp_signal"] = {
                                "strategy_id": strat.id,
                                "strategy_name": strat.name,
                                "signal": sig.get("signal"),
                                "mode": sig.get("mode", "SCALP"),
                                "entry": sig.get("entry"),
                                "sl": sig.get("sl"),
                                "tp1": sig.get("tp1"),
                                "tp2": sig.get("tp2"),
                                "reason": sig.get("reason"),
                            }
                    except Exception as e:
                        logger.warning(f"Error evaluating Scalp Strategy #{strat.id} for {symbol}: {e}")

            # 2. Swing Strategy
            target_swing_df = df_h1 if df_h1 is not None and len(df_h1) >= 20 else df_m15
            if pair.swing_enabled and pair.swing_strategy_id and target_swing_df is not None and len(target_swing_df) >= 20:
                strat = db.query(StrategyScript).filter_by(id=pair.swing_strategy_id).first()
                if strat:
                    try:
                        sandbox = StrategySandbox(strat.python_code)
                        params = json.loads(strat.default_params_json) if strat.default_params_json else {}
                        sig = sandbox.evaluate(target_swing_df, params=params)
                        if sig and sig.get("signal"):
                            signals["swing_signal"] = {
                                "strategy_id": strat.id,
                                "strategy_name": strat.name,
                                "signal": sig.get("signal"),
                                "mode": sig.get("mode", "SWING"),
                                "entry": sig.get("entry"),
                                "sl": sig.get("sl"),
                                "tp1": sig.get("tp1"),
                                "tp2": sig.get("tp2"),
                                "reason": sig.get("reason"),
                            }
                    except Exception as e:
                        logger.warning(f"Error evaluating Swing Strategy #{strat.id} for {symbol}: {e}")

            return signals
        finally:
            if close_db:
                db.close()

    def compile_cross_pair_snapshot(
        self,
        provided_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict[str, Any]:
        """
        Build compact Cross-Pair Context Snapshot for Gold vs Bitcoin USD-liquidity & risk impulse.
        """
        results: Dict[str, Dict[str, float]] = {}

        for sym in XM_ACTIVE_SYMBOLS:
            df = None
            if provided_data and sym in provided_data:
                df = provided_data[sym]
            elif provided_data and sym.rstrip("#") in provided_data:
                df = provided_data[sym.rstrip("#")]

            if df is not None and len(df) >= 4:
                curr_c = float(df["close"].iloc[-1])
                c_1h = float(df["close"].iloc[-2])
                c_4h = float(df["close"].iloc[-4]) if len(df) >= 5 else c_1h

                pct_1h = round(((curr_c - c_1h) / c_1h) * 100.0, 2)
                pct_4h = round(((curr_c - c_4h) / c_4h) * 100.0, 2)
                results[sym] = {"pct_1h": pct_1h, "pct_4h": pct_4h, "close": curr_c}
            else:
                results[sym] = {"pct_1h": 0.0, "pct_4h": 0.0, "close": 0.0}

        gold_pct = results.get("GOLD#", {}).get("pct_1h", 0.0)
        btc_pct = results.get("BTCUSD#", {}).get("pct_1h", 0.0)

        # Cross-asset USD liquidity impulse
        if gold_pct > 0.15 and btc_pct > 0.3:
            impulse = "DOLLAR_DEVAL_EXPANSION"
        elif gold_pct < -0.15 and btc_pct < -0.3:
            impulse = "LIQUIDITY_DRAIN_CRUNCH"
        elif gold_pct > 0.2 and btc_pct < -0.2:
            impulse = "FLIGHT_TO_SAFETY_METALS"
        elif btc_pct > 0.5 and abs(gold_pct) < 0.1:
            impulse = "SPECULATIVE_RISK_ON_CRYPTO"
        else:
            impulse = "NEUTRAL"

        return {
            "gold_pct_1h": gold_pct,
            "btc_pct_1h": btc_pct,
            "intermarket_liquidity_impulse": impulse,
            "usd_bias": "WEAK_USD" if impulse == "DOLLAR_DEVAL_EXPANSION" else ("STRONG_USD" if impulse == "LIQUIDITY_DRAIN_CRUNCH" else "NEUTRAL"),
            "pairs": results,
        }

    async def compile_market_packet(
        self,
        symbol: str,
        timeframe_dfs: Optional[Dict[str, pd.DataFrame]] = None,
        live_tick: Optional[Tuple[float, float, int]] = None,
        cross_pair_dfs: Optional[Dict[str, pd.DataFrame]] = None,
        db: Optional[Session] = None,
    ) -> MarketPacket:
        """
        Produce a complete, structured MarketPacket for the Gemini Supervisory Brain.
        """
        # Determine asset class
        clean_sym = symbol.upper()
        if "GOLD" in clean_sym or "XAU" in clean_sym:
            asset_class = "METAL"
        elif "BTC" in clean_sym or "ETH" in clean_sym or "SOL" in clean_sym:
            asset_class = "CRYPTO"
        else:
            asset_class = "FOREX"

        # Gather timeframes
        dfs = timeframe_dfs or {}
        required_tfs = ["M5", "M15", "H1", "H4", "D1"]
        for tf in required_tfs:
            if tf not in dfs:
                fetched = await self.fetch_timeframe_bars(symbol, tf)
                if fetched is not None:
                    dfs[tf] = fetched

        # Gather tick
        if live_tick is not None:
            bid, ask, spread = live_tick
        else:
            bid, ask, spread = await self.fetch_live_tick(symbol)

        # Fallback pricing from highest timeframe if tick is unavailable
        if bid <= 0.0:
            for tf_key in ("M15", "H1", "M5", "H4", "D1"):
                if tf_key in dfs and len(dfs[tf_key]) > 0:
                    c = float(dfs[tf_key]["close"].iloc[-1])
                    bid, ask, spread = c, c + 0.25, 25
                    break

        # Analyze each timeframe
        tf_analyses: Dict[str, Any] = {}
        all_detected_patterns: List[Dict[str, Any]] = []

        for tf, df_tf in dfs.items():
            analysis = self.analyze_single_timeframe(df_tf, tf)
            tf_analyses[tf] = asdict(analysis)
            if analysis.detected_patterns:
                all_detected_patterns.extend(analysis.detected_patterns)

        # Structural high/lows
        pdh, pdl = self.extract_pdh_pdl(dfs.get("D1"))

        # Bias composites
        h4_bias = tf_analyses.get("H4", {}).get("bias", "CHOP")
        d1_bias = tf_analyses.get("D1", {}).get("bias", "CHOP")
        swing_bias = (
            "BULLISH" if h4_bias == "BULLISH" and d1_bias == "BULLISH"
            else "BEARISH" if h4_bias == "BEARISH" and d1_bias == "BEARISH"
            else h4_bias if h4_bias in ("BULLISH", "BEARISH") else "CHOP"
        )

        m15_bias = tf_analyses.get("M15", {}).get("bias", "CHOP")
        h1_bias = tf_analyses.get("H1", {}).get("bias", "CHOP")
        scalp_bias = (
            "BULLISH" if m15_bias == "BULLISH" and h1_bias == "BULLISH"
            else "BEARISH" if m15_bias == "BEARISH" and h1_bias == "BEARISH"
            else m15_bias if m15_bias in ("BULLISH", "BEARISH") else "CHOP"
        )

        # Candidate signals
        candidate_signals = self.evaluate_candidate_signals(
            symbol=symbol,
            df_m15=dfs.get("M15"),
            df_h1=dfs.get("H1"),
            db=db,
        )

        # Cross pair momentum
        cross_pair_mom = self.compile_cross_pair_snapshot(provided_data=cross_pair_dfs)

        # Macro news status
        news_status = news_guard.check_blackout(symbol)

        now = now_utc()

        # Session tag calibration
        hour_utc = now.hour
        minute_utc = now.minute
        time_decimal = hour_utc + (minute_utc / 60.0)

        if asset_class == "CRYPTO":
            session_tag = "CRYPTO_24_7"
            cme_gap_status = "TRACKED"
            rollover_spread_guard_active = False
        else:
            # Gold Session awareness
            if 0.0 <= time_decimal < 7.0:
                session_tag = "ASIAN_RANGE"
            elif 7.0 <= time_decimal < 11.0:
                session_tag = "LONDON_OPEN"
            elif 12.5 <= time_decimal < 16.5:
                session_tag = "NY_OVERLAP"
            elif 16.5 <= time_decimal < 21.0:
                session_tag = "NY_AFTERNOON"
            else:
                session_tag = "OFF_HOURS_ROLLOVER"

            cme_gap_status = None
            # Daily broker rollover spread guard (23:50-01:05 server time ~ 21:50-23:05 UTC)
            rollover_spread_guard_active = (
                (hour_utc == 21 and minute_utc >= 50)
                or (hour_utc == 22)
                or (hour_utc == 23 and minute_utc <= 5)
            )

        impulse = cross_pair_mom.get("intermarket_liquidity_impulse", "NEUTRAL")

        return MarketPacket(
            symbol=symbol,
            asset_class=asset_class,
            timestamp_utc=now.isoformat(),
            timestamp_ist=to_ist_str(now),
            bid=round(bid, 5),
            ask=round(ask, 5),
            spread_points=spread,
            pdh=round(pdh, 5) if pdh is not None else None,
            pdl=round(pdl, 5) if pdl is not None else None,
            swing_bias_h4_d1=swing_bias,
            scalp_bias_m15_h1=scalp_bias,
            timeframe_breakdown=tf_analyses,
            candidate_signals=candidate_signals,
            cross_pair_momentum=cross_pair_mom,
            news_blackout=news_status.to_dict(),
            detected_patterns=all_detected_patterns,
            session_tag=session_tag,
            rollover_spread_guard_active=rollover_spread_guard_active,
            cme_gap_status=cme_gap_status,
            intermarket_liquidity_impulse=impulse,
        )


market_packet_compiler = MarketPacketCompiler()
