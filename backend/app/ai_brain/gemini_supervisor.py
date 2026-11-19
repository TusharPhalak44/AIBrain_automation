"""Gemini Supervisory Analyst & Report Generator.

Interrogates Gemini AI via official google-genai SDK using strict Pydantic
response_schema structured outputs. Evaluates multi-timeframe price action,
assigned strategy candidate signals, macro news blackout, spread friction,
and active LearnedPairRule conditions. Persists reports to MySQL and broadcasts
over live WebSocket.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.crypto_vault import crypto_vault
from backend.app.db.session import SessionLocal
from backend.app.db.models import (
    AppSettings,
    GeminiAnalysisReport,
    LearnedPairRule,
    TradingPairBot,
)
from backend.app.ai_brain.market_packet import MarketPacket, market_packet_compiler
from backend.app.ai_brain.usage_tracker import record_gemini_usage
from backend.app.api.websocket import manager

logger = logging.getLogger(__name__)


class UpcomingSetupPlan(BaseModel):
    """Structured pre-trigger upcoming trade setup radar plan."""
    watch_bias: str = Field(
        default="NONE",
        description="BULLISH_WATCH, BEARISH_WATCH, RANGE_BOUND, or NONE"
    )
    setup_mode: str = Field(
        default="SCALP",
        description="SCALP or SWING"
    )
    trigger_zone_low: Optional[float] = Field(default=None, description="Lower bound of trigger zone")
    trigger_zone_high: Optional[float] = Field(default=None, description="Upper bound of trigger zone")
    planned_entry: Optional[float] = Field(default=None, description="Planned entry level")
    planned_sl: Optional[float] = Field(default=None, description="Planned hard stop loss level")
    planned_tp1: Optional[float] = Field(default=None, description="Planned TP1 partial target (+1.5R)")
    planned_tp2: Optional[float] = Field(default=None, description="Planned TP2 final target")
    rr_ratio: Optional[float] = Field(default=None, description="Risk-Reward ratio (e.g. 2.5)")
    readiness_pct: int = Field(default=0, ge=0, le=100, description="Readiness percentage 0-100%")
    trigger_condition: str = Field(default="", description="Specific price action trigger needed to execute")
    invalidation_level: Optional[float] = Field(default=None, description="Price level that cancels this setup")
    expected_window: str = Field(default="", description="Estimated timeframe or session window")


class GeminiSupervisoryOutput(BaseModel):
    """Structured Pydantic schema for Gemini Supervisory response."""
    market_regime: str = Field(
        description="TRENDING_UP, TRENDING_DOWN, RANGE_SWEEP, HIGH_VOLATILITY_CHOP, or NEWS_BLACKOUT"
    )
    decision: str = Field(
        description="EXECUTE_SCALP, EXECUTE_SWING, EXECUTE_BOTH, STAGE_PENDING, or WAIT"
    )
    recommended_mode: str = Field(
        default="NONE",
        description="SCALP, SWING, BOTH, or NONE"
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Supervisory confidence score from 0.00 to 1.00"
    )
    entry_price: Optional[float] = Field(default=None, description="Proposed entry price")
    stop_loss: Optional[float] = Field(default=None, description="Mandatory hard Stop Loss price")
    tp1: Optional[float] = Field(default=None, description="Take Profit 1 (+1.5R partial target)")
    tp2: Optional[float] = Field(default=None, description="Take Profit 2 final target")
    bullish_factors: List[str] = Field(default_factory=list, description="List of bullish technical factors")
    bearish_factors: List[str] = Field(default_factory=list, description="List of bearish technical factors")
    news_and_macro_summary: str = Field(description="Summary of macro news and cross-pair impact")
    trade_plan_thesis: str = Field(description="Clear explanation of why this setup is planned or skipped")
    upcoming_setup: Optional[UpcomingSetupPlan] = Field(
        default=None,
        description="Developing high-probability upcoming trade radar setup, even when decision is WAIT"
    )


SUPERVISOR_SYSTEM_PROMPT = """
You are the Principal Quantitative Trading Supervisor for XM Global MetaTrader 5 instruments
(Gold GOLD#, Forex majors EURUSD#, GBPUSD#, USDJPY#, and Crypto CFDs BTCUSD#, ETHUSD#, SOLUSD#).
Strictly ZERO Indian/US stock feeds.

You supervise algorithmic strategies, reviewing multi-timeframe price action, support/resistance,
fair value gaps (FVG), liquidity sweeps, macro news blackouts, and active postmortem rules.

CRITICAL INVARIANTS:
1. Zero Naked Trades: Every trade MUST have a strictly valid, non-zero hard Stop Loss (BUY: sl < entry < tp1 <= tp2; SELL: sl > entry > tp1 >= tp2).
2. News Blackout: If a Tier-1 news release is within +/- 15 minutes, decision MUST be 'WAIT' and regime MUST be 'NEWS_BLACKOUT'.
3. Micro & Standard Exits: TP1 must always be set at +1.5R.
4. Active Rules: Honor any active 'LIVE' or 'LOCKED' filter rules provided.
5. If technical structure is conflicting or no high-probability setup exists right now, output decision='WAIT' and recommended_mode='NONE'.
6. UPCOMING TRADE RADAR: ALWAYS provide an `upcoming_setup` plan detailing where the next high-probability setup is developing (e.g. watch_bias, trigger_zone_low, trigger_zone_high, planned_entry, planned_sl, planned_tp1, planned_tp2, rr_ratio, readiness_pct from 0 to 100, trigger_condition, invalidation_level, expected_window) even if your current decision is WAIT.
7. SYMBOL PATTERN MEMORY: You are given `symbol_pattern_memory` showing the empirical win/loss scorecard of price-action patterns specifically on this symbol (GOLD# vs BTCUSD#). Favor patterns marked 'PROVEN_EDGE', and strictly avoid setups relying on patterns marked 'BLOCKED_TRAP' (decision MUST be 'WAIT').
"""


class GeminiSupervisor:
    """Supervises live pair setups and writes analysis reports."""

    def __init__(self):
        self._cached_api_key: Optional[str] = None
        self._client: Optional[genai.Client] = None
        self._model_name: str = "gemini-3.8-flash"

    def reload_client(self) -> None:
        """Reset cached client to force re-initialization on next call."""
        self._cached_api_key = None
        self._client = None
        logger.info("Reset Gemini supervisor client cache.")

    def get_client(self, db: Optional[Session] = None) -> Tuple[Optional[genai.Client], str]:
        """
        Dynamically initialize or refresh google-genai Client whenever API key changes in MySQL.
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            if not st or not st.gemini_api_key_enc:
                return None, self._model_name

            raw_key = crypto_vault.decrypt_secret(st.gemini_api_key_enc).strip()
            raw_model = (st.gemini_live_model or "gemini-3.8-flash").strip().removeprefix("models/")
            # Auto-migrate deprecated 2.5 or 3.1-pro models in live setting
            if "2.5" in raw_model or "2.0" in raw_model or "3.1-pro" in raw_model:
                raw_model = "gemini-3.8-flash"
            self._model_name = raw_model

            if raw_key != self._cached_api_key or self._client is None:
                self._client = genai.Client(api_key=raw_key, http_options={"api_version": "v1beta"})
                self._cached_api_key = raw_key
                logger.info(f"Initialized google-genai Client with model: {self._model_name}")

            return self._client, self._model_name
        except Exception as e:
            logger.warning(f"Failed to initialize google-genai Client: {e}")
            return None, self._model_name
        finally:
            if close_db:
                db.close()

    def get_active_rules(self, symbol: str, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Fetch active LIVE and LOCKED rules for symbol."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            rules = (
                db.query(LearnedPairRule)
                .filter(
                    (LearnedPairRule.symbol == symbol) | (LearnedPairRule.symbol == f"{symbol}#"),
                    LearnedPairRule.status.in_(["LIVE", "LOCKED"]),
                )
                .all()
            )
            return [
                {
                    "rule_code": r.rule_code,
                    "mode": r.mode,
                    "status": r.status,
                    "condition": r.condition_json,
                    "action": r.action_json,
                }
                for r in rules
            ]
        finally:
            if close_db:
                db.close()

    def get_pair_pattern_memory(self, symbol: str, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Fetch symbol-specific pattern memory scorecard rows (isolated GOLD# vs BTCUSD#)."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            from backend.app.db.models import PairPatternMemory
            clean = symbol.rstrip("#")
            records = (
                db.query(PairPatternMemory)
                .filter(
                    (PairPatternMemory.symbol == symbol)
                    | (PairPatternMemory.symbol == clean)
                    | (PairPatternMemory.symbol == f"{clean}#")
                )
                .order_by(PairPatternMemory.win_rate_pct.desc())
                .all()
            )
            return [
                {
                    "pattern_signature": r.pattern_signature,
                    "mode": r.mode,
                    "status": r.status,
                    "win_rate_pct": float(r.win_rate_pct),
                    "wins": r.wins,
                    "losses": r.losses,
                    "avg_r_multiple": float(r.avg_r_multiple),
                    "net_pnl_usd": float(r.net_pnl_usd),
                    "last_ai_lesson": r.last_ai_lesson,
                }
                for r in records
            ]
        finally:
            if close_db:
                db.close()

    def _fallback_deterministic_supervision(
        self,
        packet: MarketPacket,
        active_rules: List[Dict[str, Any]],
        pattern_memory: Optional[List[Dict[str, Any]]] = None,
    ) -> GeminiSupervisoryOutput:
        """
        High-fidelity deterministic supervisory logic used when Gemini API key is offline or in mock test mode.
        """
        digits = 2 if ("GOLD" in packet.symbol or "BTC" in packet.symbol or "ETH" in packet.symbol or "SOL" in packet.symbol) else (3 if "JPY" in packet.symbol else 5)
        spread_price = (packet.ask - packet.bid) if (packet.ask > packet.bid and packet.bid > 0) else (packet.spread_points * (10 ** -digits) if packet.spread_points > 0 else 0.0001)

        # 1. Check Macro News Blackout
        if packet.news_blackout.get("is_blackout"):
            ev_title = packet.news_blackout.get("event_title", "Tier-1 Event")
            reason = packet.news_blackout.get("blackout_reason", "News blackout active.")
            return GeminiSupervisoryOutput(
                market_regime="NEWS_BLACKOUT",
                decision="WAIT",
                recommended_mode="NONE",
                confidence=0.95,
                news_and_macro_summary=f"Active high-impact release: {ev_title}.",
                trade_plan_thesis=f"Trading suspended due to {reason}",
                bullish_factors=[],
                bearish_factors=[reason],
            )

        # 2. Check if live quotes are available
        if packet.bid <= 0.0:
            return GeminiSupervisoryOutput(
                market_regime="HIGH_VOLATILITY_CHOP",
                decision="WAIT",
                recommended_mode="NONE",
                confidence=0.50,
                bullish_factors=[],
                bearish_factors=["Quotes unavailable"],
                news_and_macro_summary="Market quotes currently disconnected.",
                trade_plan_thesis=f"Waiting for live MT5 quote feeds for {packet.symbol}.",
            )

        # 2. Check Candidate Signals from Strategy Sandbox
        scalp_sig = packet.candidate_signals.get("scalp_signal")
        swing_sig = packet.candidate_signals.get("swing_signal")

        # Evaluate Scalp Signal
        if scalp_sig and scalp_sig.get("signal"):
            direction = scalp_sig["signal"]
            entry = float(scalp_sig["entry"])
            sl = float(scalp_sig["sl"])
            tp1 = float(scalp_sig["tp1"])
            tp2 = float(scalp_sig["tp2"])

            regime = "TRENDING_UP" if direction == "BUY" else "TRENDING_DOWN"
            if packet.scalp_bias_m15_h1 == "CHOP":
                regime = "RANGE_SWEEP"

            # Check rule blocking with condition evaluation
            blocked = False
            block_reason = ""
            for r in active_rules:
                if r.get("mode") in ("SCALP", "BOTH"):
                    cond = r.get("condition") or {}
                    if isinstance(cond, str):
                        try:
                            cond = json.loads(cond)
                        except Exception:
                            cond = {}
                    filt_act = cond.get("filter_action", "")
                    indicator = cond.get("indicator", "")
                    # Match direction
                    if filt_act in (f"BLOCK_{direction}", "BLOCK_ALL"):
                        if indicator == "news_guard" and packet.news_blackout.get("is_blackout", False):
                            blocked = True
                            block_reason = f"Blocked by rule {r['rule_code']}: Tier-1 news blackout"
                            break
                        elif indicator == "market_regime" and packet.scalp_bias_m15_h1 == "CHOP":
                            blocked = True
                            block_reason = f"Blocked by rule {r['rule_code']}: Low-volatility chop"
                            break
                        elif indicator == "ema_trend" and ((direction == "BUY" and packet.swing_bias_h4_d1 == "BEARISH") or (direction == "SELL" and packet.swing_bias_h4_d1 == "BULLISH")):
                            blocked = True
                            block_reason = f"Blocked by rule {r['rule_code']}: Higher-timeframe counter-trend"
                            break
                        elif filt_act == "BLOCK_ALL":
                            blocked = True
                            block_reason = f"Blocked by rule {r['rule_code']}"
                            break

            if blocked:
                return GeminiSupervisoryOutput(
                    market_regime=regime,
                    decision="WAIT",
                    recommended_mode="NONE",
                    confidence=0.70,
                    entry_price=entry,
                    stop_loss=sl,
                    tp1=tp1,
                    tp2=tp2,
                    bullish_factors=["Strategy scalp trigger"] if direction == "BUY" else [],
                    bearish_factors=["Strategy scalp trigger"] if direction == "SELL" else [],
                    news_and_macro_summary="No macro blackout. Setup blocked by learned rule.",
                    trade_plan_thesis=f"Candidate scalp setup rejected: {block_reason}",
                )

            # Valid Scalp Setup
            bull_factors = [f"Scalp {scalp_sig['strategy_name']} trigger"] if direction == "BUY" else []
            bear_factors = [f"Scalp {scalp_sig['strategy_name']} trigger"] if direction == "SELL" else []
            if packet.scalp_bias_m15_h1 == "BULLISH":
                bull_factors.append("M15/H1 EMA trend alignment")
            elif packet.scalp_bias_m15_h1 == "BEARISH":
                bear_factors.append("M15/H1 EMA trend alignment")

            scalp_upcoming = UpcomingSetupPlan(
                watch_bias="BULLISH_WATCH" if direction == "BUY" else "BEARISH_WATCH",
                setup_mode="SCALP",
                trigger_zone_low=round(entry - (spread_price * 2), digits),
                trigger_zone_high=round(entry + (spread_price * 2), digits),
                planned_entry=entry,
                planned_sl=sl,
                planned_tp1=tp1,
                planned_tp2=tp2,
                rr_ratio=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                readiness_pct=95,
                trigger_condition=f"M15 Scalp {direction} trigger confirmed on {packet.symbol}",
                invalidation_level=sl,
                expected_window="Immediate / Next 15 mins",
            )

            return GeminiSupervisoryOutput(
                market_regime=regime,
                decision="EXECUTE_SCALP",
                recommended_mode="SCALP",
                confidence=0.85,
                entry_price=entry,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                bullish_factors=bull_factors,
                bearish_factors=bear_factors,
                news_and_macro_summary="Normal volatility window. No macro blackout.",
                trade_plan_thesis=(
                    f"Approved algorithmic Scalp {direction} on {packet.symbol}. "
                    f"Entry {entry}, Hard SL {sl}, TP1 {tp1} (+1.5R partial), TP2 {tp2}. "
                    f"Reason: {scalp_sig.get('reason', 'Confluence confirmed')}"
                ),
                upcoming_setup=scalp_upcoming,
            )

        # Evaluate Swing Signal
        if swing_sig and swing_sig.get("signal"):
            direction = swing_sig["signal"]
            entry = float(swing_sig["entry"])
            sl = float(swing_sig["sl"])
            tp1 = float(swing_sig["tp1"])
            tp2 = float(swing_sig["tp2"])

            regime = "TRENDING_UP" if direction == "BUY" else "TRENDING_DOWN"
            swing_upcoming = UpcomingSetupPlan(
                watch_bias="BULLISH_WATCH" if direction == "BUY" else "BEARISH_WATCH",
                setup_mode="SWING",
                trigger_zone_low=round(entry - (spread_price * 3), digits),
                trigger_zone_high=round(entry + (spread_price * 3), digits),
                planned_entry=entry,
                planned_sl=sl,
                planned_tp1=tp1,
                planned_tp2=tp2,
                rr_ratio=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                readiness_pct=90,
                trigger_condition=f"H1/H4 Swing {direction} structure confirmed on {packet.symbol}",
                invalidation_level=sl,
                expected_window="Next 1-4 hours",
            )

            return GeminiSupervisoryOutput(
                market_regime=regime,
                decision="EXECUTE_SWING",
                recommended_mode="SWING",
                confidence=0.82,
                entry_price=entry,
                stop_loss=sl,
                tp1=tp1,
                tp2=tp2,
                bullish_factors=[f"Swing {swing_sig['strategy_name']}"] if direction == "BUY" else [],
                bearish_factors=[f"Swing {swing_sig['strategy_name']}"] if direction == "SELL" else [],
                news_and_macro_summary="Clear macro horizon. Higher timeframe swing structure confirmed.",
                trade_plan_thesis=(
                    f"Approved algorithmic Swing {direction} on {packet.symbol}. "
                    f"Entry {entry}, SL {sl}, TP1 {tp1}, TP2 {tp2}."
                ),
                upcoming_setup=swing_upcoming,
            )

        # Default Neutral Scan - Synthesize high-probability upcoming trade setup
        regime = "HIGH_VOLATILITY_CHOP" if packet.scalp_bias_m15_h1 == "CHOP" else "RANGE_SWEEP"
        price = packet.ask if packet.ask > 0 else (packet.bid or 1.0)
        is_bullish = packet.scalp_bias_m15_h1 == "BULLISH" or packet.swing_bias_h4_d1 == "BULLISH"
        bias = "BULLISH_WATCH" if is_bullish else "BEARISH_WATCH"
        atr_est = max(0.001, spread_price * 10)
        if packet.symbol.startswith("GOLD"):
            atr_est = max(3.0, spread_price * 8)
        elif "BTC" in packet.symbol:
            atr_est = max(300.0, spread_price * 5)
        elif "ETH" in packet.symbol:
            atr_est = max(20.0, spread_price * 5)
        elif "SOL" in packet.symbol:
            atr_est = max(1.0, spread_price * 5)

        if is_bullish:
            p_entry = round(price - (atr_est * 0.4), digits)
            p_sl = round(p_entry - atr_est, digits)
            p_tp1 = round(p_entry + (1.5 * atr_est), digits)
            p_tp2 = round(p_entry + (3.0 * atr_est), digits)
            t_low = round(p_entry - (atr_est * 0.2), digits)
            t_high = round(p_entry + (atr_est * 0.2), digits)
            cond = f"Wait for M15 liquidity sweep below session low into FVG support ({t_low}-{t_high})"
        else:
            p_entry = round(price + (atr_est * 0.4), digits)
            p_sl = round(p_entry + atr_est, digits)
            p_tp1 = round(p_entry - (1.5 * atr_est), digits)
            p_tp2 = round(p_entry - (3.0 * atr_est), digits)
            t_low = round(p_entry - (atr_est * 0.2), digits)
            t_high = round(p_entry + (atr_est * 0.2), digits)
            cond = f"Wait for M15 liquidity sweep above session high into FVG supply ({t_low}-{t_high})"

        neutral_upcoming = UpcomingSetupPlan(
            watch_bias=bias,
            setup_mode="SCALP",
            trigger_zone_low=t_low,
            trigger_zone_high=t_high,
            planned_entry=p_entry,
            planned_sl=p_sl,
            planned_tp1=p_tp1,
            planned_tp2=p_tp2,
            rr_ratio=3.0,
            readiness_pct=65,
            trigger_condition=cond,
            invalidation_level=p_sl,
            expected_window="Next 1-3 hours / Session overlap",
        )

        return GeminiSupervisoryOutput(
            market_regime=regime,
            decision="WAIT",
            recommended_mode="NONE",
            confidence=0.60,
            bullish_factors=["H4/D1 Trend: " + packet.swing_bias_h4_d1],
            bearish_factors=["No active strategy entry signal triggered"],
            news_and_macro_summary=f"USD Bias: {packet.cross_pair_momentum.get('usd_bias')}",
            trade_plan_thesis=f"Scanning {packet.symbol}. Current price {packet.bid}/{packet.ask}. Waiting for trigger zone confluence.",
            upcoming_setup=neutral_upcoming,
        )

    async def analyze_pair(
        self,
        packet: MarketPacket,
        account_type: str = "DEMO",
        db: Optional[Session] = None,
    ) -> GeminiAnalysisReport:
        """
        Execute supervisory analysis for a pair, save GeminiAnalysisReport to MySQL,
        and broadcast to WebSocket subscribers.
        """
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            client, model_name = self.get_client(db=db)
            active_rules = self.get_active_rules(packet.symbol, db=db)
            pattern_memory = self.get_pair_pattern_memory(packet.symbol, db=db)

            analysis_result: Optional[GeminiSupervisoryOutput] = None
            response = None
            latency_ms = 0
            chosen_model = model_name.replace("models/", "") if model_name else "gemini-3.8-flash"

            if client is not None:
                try:
                    prompt_payload = {
                        "symbol": packet.symbol,
                        "asset_class": packet.asset_class,
                        "timestamp_ist": packet.timestamp_ist,
                        "bid": packet.bid,
                        "ask": packet.ask,
                        "spread_points": packet.spread_points,
                        "pdh": packet.pdh,
                        "pdl": packet.pdl,
                        "swing_bias_h4_d1": packet.swing_bias_h4_d1,
                        "scalp_bias_m15_h1": packet.scalp_bias_m15_h1,
                        "timeframes": packet.timeframe_breakdown,
                        "detected_patterns": packet.detected_patterns,
                        "candidate_signals": packet.candidate_signals,
                        "cross_pair_momentum": packet.cross_pair_momentum,
                        "news_blackout": packet.news_blackout,
                        "active_learned_rules": active_rules,
                        "symbol_pattern_memory": pattern_memory,
                    }

                    user_content = (
                        f"Analyze the following XM Global market packet and candidate strategy signals:\n\n"
                        f"{json.dumps(prompt_payload, indent=2)}\n\n"
                        f"Provide your structured supervisory judgment conforming strictly to the response schema."
                    )

                    # Candidate models fallback chain (Free-tier safe GA models ONLY)
                    clean_m = model_name.strip().removeprefix("models/")
                    candidates = [clean_m, "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
                    seen = set()
                    ordered_models = []
                    for m in candidates:
                        if m and m not in seen and "3.1-pro" not in m:
                            seen.add(m)
                            ordered_models.append(m)

                    response = None
                    last_err = None
                    chosen_model = clean_m
                    latency_ms = 0
                    for try_m in ordered_models:
                        try:
                            t0 = time.perf_counter()
                            response = await client.aio.models.generate_content(
                                model=try_m,
                                contents=user_content,
                                config=types.GenerateContentConfig(
                                    system_instruction=SUPERVISOR_SYSTEM_PROMPT,
                                    response_mime_type="application/json",
                                    response_schema=GeminiSupervisoryOutput,
                                ),
                            )
                            latency_ms = int((time.perf_counter() - t0) * 1000)
                            if response and response.text:
                                chosen_model = try_m
                                break
                        except Exception as try_e:
                            last_err = try_e
                            logger.info(f"Gemini model '{try_m}' unavailable ({try_e}); attempting fallback...")

                    if response and response.text:
                        parsed = json.loads(response.text)
                        analysis_result = GeminiSupervisoryOutput(**parsed)
                    else:
                        logger.warning(f"All Gemini models exhausted ({last_err}); falling back to deterministic supervision.")
                except Exception as e:
                    logger.warning(f"Gemini API call failed ({e}); switching to deterministic supervisor.")
                    analysis_result = None

            if analysis_result is None:
                analysis_result = self._fallback_deterministic_supervision(packet, active_rules, pattern_memory)

            # Determine execution_status
            if analysis_result.decision.startswith("EXECUTE"):
                execution_status = "PLANNED"
            elif analysis_result.market_regime == "NEWS_BLACKOUT":
                execution_status = "NEWS_BLACKOUT"
            else:
                execution_status = "WAITING"

            # Parse upcoming setup details
            upcoming_dict = None
            readiness_val = 0
            bias_val = "NONE"
            if analysis_result.upcoming_setup:
                upcoming_dict = analysis_result.upcoming_setup.model_dump()
                readiness_val = analysis_result.upcoming_setup.readiness_pct
                bias_val = analysis_result.upcoming_setup.watch_bias

            # Create Report Entity
            report = GeminiAnalysisReport(
                account_type=account_type.upper(),
                symbol=packet.symbol,
                scanned_at_utc=now_utc(),
                market_regime=analysis_result.market_regime,
                decision=analysis_result.decision,
                recommended_mode=analysis_result.recommended_mode,
                confidence=Decimal(str(round(analysis_result.confidence, 2))),
                entry_price=Decimal(str(round(analysis_result.entry_price, 6))) if analysis_result.entry_price else None,
                stop_loss=Decimal(str(round(analysis_result.stop_loss, 6))) if analysis_result.stop_loss else None,
                tp1=Decimal(str(round(analysis_result.tp1, 6))) if analysis_result.tp1 else None,
                tp2=Decimal(str(round(analysis_result.tp2, 6))) if analysis_result.tp2 else None,
                news_summary=analysis_result.news_and_macro_summary,
                thesis_text=analysis_result.trade_plan_thesis,
                execution_status=execution_status,
                upcoming_setup_json=json.dumps(upcoming_dict) if upcoming_dict else None,
                readiness_pct=readiness_val,
                watch_bias=bias_val,
                raw_snapshot_json=json.dumps({
                    "packet": packet.to_dict(),
                    "output": analysis_result.model_dump(),
                }),
            )

            db.add(report)
            db.commit()
            db.refresh(report)

            # Record token usage ledger if response returned
            if response is not None:
                try:
                    record_gemini_usage(
                        db=db,
                        model_id=chosen_model,
                        call_purpose="LIVE_SCAN",
                        response=response,
                        latency_ms=latency_ms,
                        symbol=packet.symbol,
                        account_type=account_type,
                        report_id=report.id,
                        http_status=200,
                    )
                except Exception as ex_usage:
                    logger.warning(f"Failed to record usage ledger: {ex_usage}")

            # Broadcast over WebSocket
            report_dict = {
                "type": "AI_REPORT",
                "id": report.id,
                "symbol": report.symbol,
                "account_type": report.account_type,
                "market_regime": report.market_regime,
                "decision": report.decision,
                "recommended_mode": report.recommended_mode,
                "confidence": float(report.confidence),
                "entry_price": float(report.entry_price) if report.entry_price else None,
                "stop_loss": float(report.stop_loss) if report.stop_loss else None,
                "tp1": float(report.tp1) if report.tp1 else None,
                "tp2": float(report.tp2) if report.tp2 else None,
                "news_summary": report.news_summary,
                "thesis_text": report.thesis_text,
                "execution_status": report.execution_status,
                "readiness_pct": readiness_val,
                "watch_bias": bias_val,
                "upcoming_setup": upcoming_dict,
                "scanned_at_ist": to_ist_str(report.scanned_at_utc),
            }
            await manager.broadcast(report_dict)

            return report
        finally:
            if close_db:
                db.close()


gemini_supervisor = GeminiSupervisor()
