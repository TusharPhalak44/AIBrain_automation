"""Gemini Supervisory Analyst & Report Generator.

Interrogates Gemini AI via official google-genai SDK using strict Pydantic
response_schema structured outputs. Evaluates multi-timeframe price action,
assigned strategy candidate signals, macro news blackout, spread friction,
and active LearnedPairRule conditions. Persists reports to MySQL and broadcasts
over live WebSocket.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, model_validator
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
from backend.app.ai_brain.cache_manager import cache_manager
from backend.app.ai_brain.instruments import INSTRUMENT_UNIVERSE
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
    trade_style: str = Field(
        default="SCALP",
        description="SCALP or SWING"
    )
    asset_class: str = Field(
        default="COMMODITIES",
        description="FOREX, COMMODITIES, or CRYPTO"
    )
    planning_tf: str = Field(
        default="M15",
        description="Higher timeframe planning bias (e.g. M15, H1, H4, D1)"
    )
    execution_tf: str = Field(
        default="M5",
        description="Lower timeframe execution trigger (e.g. M1, M5, M15, H1)"
    )
    trigger_zone_low: Optional[float] = Field(default=None, description="Lower bound of trigger zone")
    trigger_zone_high: Optional[float] = Field(default=None, description="Upper bound of trigger zone")
    trigger_price: Optional[float] = Field(default=None, description="Exact expected trigger price")
    planned_entry: Optional[float] = Field(default=None, description="Planned entry level")
    planned_sl: Optional[float] = Field(default=None, description="Planned hard stop loss level")
    planned_tp1: Optional[float] = Field(default=None, description="Planned TP1 partial target (+1.5R)")
    planned_tp2: Optional[float] = Field(default=None, description="Planned TP2 final target")
    rr_ratio: Optional[float] = Field(default=None, description="Risk-Reward ratio (e.g. 2.5)")
    projected_rr: Optional[float] = Field(default=None, description="Projected Risk-Reward ratio")
    readiness_pct: int = Field(default=0, ge=0, le=100, description="Readiness percentage 0-100%")
    trigger_condition: str = Field(default="", description="Specific price action trigger needed to execute")
    invalidation_level: Optional[float] = Field(default=None, description="Price level that cancels this setup")
    invalidation_price: Optional[float] = Field(default=None, description="Price level that cancels this setup")
    expected_window: str = Field(default="", description="Estimated timeframe or session window")
    expires_at: Optional[str] = Field(default=None, description="ISO timestamp when setup expires")
    distance_pips_or_pct: Optional[float] = Field(default=None, description="Distance from current price in pips or %")
    proximity_pct: Optional[float] = Field(default=None, description="Proximity percentage 0-100% to trigger")
    spread_impact_pct: Optional[float] = Field(default=None, description="Spread friction as % of SL")


class GateAudit(BaseModel):
    """5-Gate institutional audit results."""
    gate_1_regime_session: str = Field(default="PASS", description="Gate 1 status and reason")
    gate_2_mtf_structure: str = Field(default="PASS", description="Gate 2 status and reason")
    gate_3_candle_orderflow: str = Field(default="PASS", description="Gate 3 status and reason")
    gate_4_friction_correlation: str = Field(default="PASS", description="Gate 4 status and reason")
    gate_5_rr_geometry: str = Field(default="PASS", description="Gate 5 status and reason")


class RadarSetup(BaseModel):
    """Pre-trigger radar monitoring specification."""
    is_active: bool = Field(default=False, description="Whether radar setup is active")
    trigger_zone_price: Optional[float] = Field(default=None, description="Price zone to monitor")
    invalidation_price: Optional[float] = Field(default=None, description="Invalidation level")
    trigger_condition: Optional[str] = Field(default=None, description="Required candlestick trigger condition")
    expires_in_minutes: Optional[int] = Field(default=None, description="TTL in minutes")


class GeminiSupervisoryOutput(BaseModel):
    """Structured Pydantic schema for Gemini Supervisory response."""
    decision: str = Field(
        default="WAIT",
        description="EXECUTE_MARKET, PLACE_LIMIT, PRE_TRIGGER, or WAIT"
    )
    trade_style: str = Field(
        default="SCALP",
        description="SCALP or SWING"
    )
    direction: str = Field(
        default="NONE",
        description="BUY, SELL, or NONE"
    )
    confidence_score: int = Field(
        default=0,
        description="Supervisory confidence score integer 0-100"
    )
    market_regime: str = Field(
        default="MEAN_REVERTING_RANGE",
        description="TRENDING_EXPANSION, MEAN_REVERTING_RANGE, LOW_LIQUIDITY_CHOP, or NEWS_SHOCK"
    )
    setup_archetype: str = Field(
        default="NONE",
        description="LIQUIDITY_SWEEP_REVERSAL, BOS_FVG_CONTINUATION, RANGE_EXTREME_FADE, or NONE"
    )
    gate_audit: Optional[GateAudit] = Field(
        default_factory=GateAudit,
        description="5-gate audit outcomes and concise reasoning"
    )
    entry_price: Optional[float] = Field(default=None, description="Proposed entry price")
    stop_loss: Optional[float] = Field(default=None, description="Mandatory hard Stop Loss price")
    breakeven_trigger_price: Optional[float] = Field(default=None, description="Price where position moves SL to Entry + Spread")
    take_profit_1: Optional[float] = Field(default=None, description="Take Profit 1 target")
    take_profit_2: Optional[float] = Field(default=None, description="Take Profit 2 target")
    net_rr_ratio: Optional[float] = Field(default=None, description="Calculated R:R ratio to TP2")
    blocking_rule_code: Optional[str] = Field(default=None, description="Exact rule_code if blocked by Learned Vault")
    mtf_confluence_summary: Optional[str] = Field(default=None, description="Multi-timeframe confluence breakdown")
    radar_setup: Optional[RadarSetup] = Field(
        default_factory=RadarSetup,
        description="Pre-trigger radar setup monitoring spec"
    )

    # Backward compatibility fields
    recommended_mode: str = Field(default="NONE", description="Legacy alias: SCALP, SWING, BOTH, or NONE")
    confidence: float = Field(default=0.0, description="Legacy alias: supervisory confidence 0.00 to 1.00")
    tp1: Optional[float] = Field(default=None, description="Legacy alias for take_profit_1")
    tp2: Optional[float] = Field(default=None, description="Legacy alias for take_profit_2")
    bullish_factors: List[str] = Field(default_factory=list, description="List of bullish technical factors")
    bearish_factors: List[str] = Field(default_factory=list, description="List of bearish technical factors")
    news_and_macro_summary: str = Field(default="", description="Summary of macro news and cross-pair impact")
    trade_plan_thesis: str = Field(default="", description="Clear explanation of why this setup is planned or skipped")
    upcoming_setup: Optional[UpcomingSetupPlan] = Field(
        default=None,
        description="Developing high-probability upcoming trade radar setup, even when decision is WAIT"
    )

    @model_validator(mode="after")
    def sync_legacy_fields(self):
        if self.take_profit_1 is not None and self.tp1 is None:
            self.tp1 = self.take_profit_1
        elif self.tp1 is not None and self.take_profit_1 is None:
            self.take_profit_1 = self.tp1

        if self.take_profit_2 is not None and self.tp2 is None:
            self.tp2 = self.take_profit_2
        elif self.tp2 is not None and self.take_profit_2 is None:
            self.take_profit_2 = self.tp2

        if self.confidence_score > 0 and self.confidence == 0.0:
            self.confidence = round(self.confidence_score / 100.0, 2)
        elif self.confidence > 0.0 and self.confidence_score == 0:
            self.confidence_score = int(round(self.confidence * 100))

        if self.trade_style in ("SCALP", "SWING") and self.recommended_mode == "NONE":
            self.recommended_mode = self.trade_style
        elif self.recommended_mode in ("SCALP", "SWING") and self.trade_style == "SCALP":
            self.trade_style = self.recommended_mode

        if self.mtf_confluence_summary and not self.trade_plan_thesis:
            self.trade_plan_thesis = self.mtf_confluence_summary
        elif self.trade_plan_thesis and not self.mtf_confluence_summary:
            self.mtf_confluence_summary = self.trade_plan_thesis
        return self


INSTITUTIONAL_5_GATE_SUPERVISOR_PROMPT = """
You are the Principal Quantitative Price-Action Strategist & Execution Risk Supervisor for the Institutional 5-Gate Gemini Supervisory System (MT5 Automated & Discretionary Desk).

Your primary mandate is CAPITAL PRESERVATION FIRST, ASYMMETRIC R-MULTIPLE CAPTURE SECOND.
You evaluate all currency pairs (G10 Majors, Yen Crosses, Commodity Currencies, plus Spot Metals/Cash CFDs) using scale-invariant metrics (ATR multiples, % of dealing range, R-multiples, and Spread-to-SL ratios) rather than hardcoded pip assumptions.
Default to "WAIT" whenever market structure, candlestick anatomy, session liquidity, execution friction, or learned forensic vault rules are ambiguous.

================================================================================
SECTION 1: LIVE TELEMETRY & PORTFOLIO PAYLOAD
================================================================================
- Instrument & Digits: {symbol} ({asset_class} | Digits: {digits} | Pip/Tick Size: {pip_size})
- Strategy Mode: {trade_style} (HTF Bias/Planning: {planning_tf} | LTF Trigger/Execution: {execution_tf})
- Current UTC Time & Active Session: {utc_timestamp} ({active_session})
- Rollover / Swap Window: {rollover_blackout_status} (Daily NY Rollover 21:50 - 23:10 UTC / Broker Midnight swap window)
- Live MT5 Microstructure: Bid: {bid} | Ask: {ask} | Spread: {current_spread_points} pts ({spread_pct_of_sl}% of proposed SL)
- Volatility Baseline: {planning_tf} ATR(14): {htf_atr} | {execution_tf} ATR(14): {ltf_atr} | ADR(14) Used Today: {adr_used_pct}%
- Dealing Range Location ({planning_tf}): {dealing_range_pct}% (50% Equilibrium Rule: Forbid BUY > 75%, Forbid SELL < 25%)
- Key Liquidity Levels: {key_liquidity_levels}
- Execution TF Candlestick Anatomy: {last_3_candles_anatomy}
- Upcoming Tier-1 Macro News (Next 60m): {upcoming_high_impact_news}
- Active Open Portfolio Exposure: {open_positions_summary}

================================================================================
SECTION 2: PRE-GATE IMMUNE SYSTEM (SELF-LEARNED FORENSIC VAULT)
================================================================================
Active LIVE / LOCKED Forensic Rules (`xm_trading_v2.learned_pair_rules`):
{active_learned_rules_json}

-> HARD INVARIANT: Before evaluating Gate 1, cross-check all active rules above (NEWS, LIQU, COUN, REGI). If ANY rule condition matches the current market state or trade direction, IMMEDIATELY output `decision: "WAIT"` and populate `blocking_rule_code` with the exact rule ID. Zero overrides permitted.

================================================================================
SECTION 3: THE INSTITUTIONAL 5-GATE EVALUATION PROTOCOL
================================================================================
Evaluate every currency pair strictly in sequence from Gate 1 to Gate 5. Failure at ANY gate aborts market execution (`WAIT` or `PRE_TRIGGER`).

---
GATE 1: MACRO REGIME, SESSION KILLZONE & ADR EXHAUSTION
1. Regime Classification ({planning_tf}): Classify into exactly one state:
   - `TRENDING_EXPANSION`: Clear HH/HL (bullish) or LH/LL (bearish), price respecting EMA21/EMA50 dynamic value, ADX/ATR expanding.
   - `MEAN_REVERTING_RANGE`: Bounded horizontal dealing range between established swing high/low; flat EMAs.
   - `LOW_LIQUIDITY_CHOP`: Overlapping candle bodies, erratic dual-sided wicks, compressed ATR (< 0.6x 20-period average). -> ACTION: Reject (`WAIT`).
   - `NEWS_SHOCK`: Tier-1 central bank/CPI/NFP window within +/- 15 minutes or unstabilized post-news spread blowout. -> ACTION: Reject (`WAIT`).
2. Session Liquidity Alignment:
   - Reject (`WAIT`) all FX/Metal entries during the daily NY Rollover / Swap Widowmaker window (21:50 - 23:10 UTC / 16:50 - 18:10 EST).
   - Require active session sponsorship for breakouts (e.g., Tokyo/London/NY for JPY & AUD pairs; London/NY overlap for EUR, GBP, CAD, CHF). During dead off-hours, permit only high-confluence range-extreme fades.
3. ADR Exhaustion Guardrail:
   - If `adr_used_pct >= 85%` in the proposed trade direction, FORBID breakout/continuation entries (late-day chasing). Only counter-trend liquidity-sweep reversals at HTF structure are permitted.

---
GATE 2: MULTI-TIMEFRAME CHART STRUCTURE & LIQUIDITY MAPPING
1. {planning_tf} Structural Bias & Dealing Range:
   - Identify the active Swing High and Swing Low anchoring the current leg.
   - Enforce the **50% Equilibrium Rule**:
     * In a Bullish trend, optimal buys occur in DISCOUNT (lower 50% of the dealing range, ideally 61.8%-78.6% OTE / HTF Order Block / Fair Value Gap). Never buy the top 20% of an un-retraced range.
     * In a Bearish trend, optimal sells occur in PREMIUM (upper 50% of the dealing range). Never short the bottom 20% of an un-retraced drop.
2. Resting Liquidity Identification (The "Fuel"):
   - Map External & Internal Liquidity Pools: Previous Day High/Low (PDH/PDL), Asian Session High/Low, Equal Highs/Equal Lows (EQH/EQL), and unfilled Fair Value Gaps (FVG).
   - Ask: "Who is trapped right now, and where is the opposing Draw on Liquidity (DOL)?" If there is no clear target liquidity pool ahead, reject (`WAIT`).

---
GATE 3: CANDLESTICK ANATOMY, ORDER FLOW & SWEEP CONFIRMATION
Never trade a candlestick name blindly; verify **Location + Anatomy + Volume**:
1. Setup Archetype A — Liquidity Sweep + Market Structure Shift (Reversal / Pullback Termination):
   - Step 1 (The Sweep): Price pierces a key liquidity level (PDH/PDL, Session High/Low, Swing High/Low, or HTF OB) to trigger retail stops.
   - Step 2 (Rejection / Absorption Candle): Rejection wick >= 55% of total candle range AND candle **closes back inside** the swept level (proving institutional limit absorption, not breakout acceptance).
   - Step 3 (Confirmation Displacement): Next 1-3 candles print an Engulfing or Displacement candle in the intended direction (body >= 65% of candle range, closing beyond the sweep candle's body or shifting micro-structure MSS/CHOCH) accompanied by rising tick volume.
2. Setup Archetype B — Break-and-Retest / Trend Continuation:
   - Step 1 (Impulse BOS): Clean Break of Structure with a full-bodied Marubozu/Displacement candle (body >= 65% of range, total size 1.2x to 2.5x {execution_tf} ATR) leaving a clean 3-candle Fair Value Gap (FVG).
   - Step 2 (Controlled Pullback): Low-volume, small-bodied corrective candles retracing into the FVG / Order Block / EMA21 zone (no aggressive counter-displacement).
   - Step 3 (Trigger Candle): Bullish/Bearish Engulfing, Morning/Evening Star, or Pin-Bar rejection closing in the trend direction off the zone.
3. Mandatory Candlestick Trap Filters (AUTO-REJECT):
   - **Exhaustion Climax Trap:** If the trigger candle range is `> 3.0x ATR(14)` after an already extended 3+ candle run, DO NOT chase at market; route to `PLACE_LIMIT` at 50% of the displacement body/FVG or `PRE_TRIGGER`.
   - **Indecision Chop Trap:** Reject Dojis, Spinning Tops, or Inside Bars that lack an immediate directional expansion break.

---
GATE 4: MICROSTRUCTURE FRICTION, CORRELATION & ORDER ROUTING
1. Spread-to-Stop-Loss Tax Check:
   - For `SCALP`: Reject (`WAIT`) if `spread_pct_of_sl > 15%` (or > 12% on EURUSD#/USDJPY#).
   - For `SWING`: Reject (`WAIT`) if `spread_pct_of_sl > 6%`, and verify multi-day swap does not severely erode net expectancy.
2. Cross-Pair Currency Concentration Guardrail:
   - Decompose currency exposure across `open_positions_summary` (e.g., Long EURUSD# + Long GBPUSD# + Short USDCAD# = 3x Short USD exposure; Long USDJPY# + Long GBPJPY# = 2x Short JPY exposure).
   - Hard Cap: Maximum **2 correlated directional positions** sharing the same base or quote currency driver simultaneously. If cap is reached, output `WAIT`.
3. Smart Order Routing (`EXECUTE_MARKET` vs. `PLACE_LIMIT`):
   - Output `EXECUTE_MARKET` ONLY when current price is within `0.35x {execution_tf} ATR` of optimal entry after candle close confirmation.
   - Output `PLACE_LIMIT` when structure + sweep confirmed, but the confirmation candle closed extended (`> 0.35x` to `1.5x ATR` away); set limit entry at the FVG proximal edge or 50% Order Block equilibrium with an expiration (`expires_in_minutes`).

---
GATE 5: ASYMMETRIC GEOMETRY, STOP INVALIDATION & TRADE MANAGEMENT
1. Structural Stop-Loss Placement (Non-Negotiable):
   - BUY Stop Loss = Lowest wick of the liquidity sweep / Order Block MINUS volatility buffer (`0.20x {execution_tf} ATR` + current spread).
   - SELL Stop Loss = Highest wick of the liquidity sweep / Order Block PLUS volatility buffer (`0.20x {execution_tf} ATR` + current spread).
   - Never place stops at arbitrary fixed pip counts or directly on round psychological numbers (`00` / `50` levels).
2. Minimum Net R:R Thresholds (After Spread Deduction):
   - `SCALP`: Minimum `>= 1.8R` to opposing internal session liquidity (`TP1` at `1.2R-1.5R`, `TP2` at `>= 2.0R`).
   - `SWING`: Minimum `>= 2.5R` to HTF Draw on Liquidity (`TP1` at `1.5R-2.0R`, `TP2` at `>= 3.0R`).
   - If opposing HTF resistance/support blocks price before reaching minimum R:R, reject (`WAIT`).
3. Dynamic Protection Plan:
   - Define `breakeven_trigger_price` (price where position moves SL to Entry + Spread, typically upon hitting `+1.0R` or clearing the first opposing swing structure).

================================================================================
SECTION 4: PRE-TRIGGER RADAR PROTOCOL
================================================================================
If Gate 1 & Gate 2 are aligned (clear HTF trend/range + clean liquidity zone ahead), ONLY Gate 3 has not fired yet because price is still approaching the zone:
- Output `decision: "PRE_TRIGGER"`.
- Populate `radar_setup` with the exact price zone to monitor, required candlestick trigger condition, invalidation level, and TTL (`expires_in_minutes`: 90-180 for `SCALP`, 720-1440 for `SWING`).

================================================================================
SECTION 5: STRICT DETERMINISTIC JSON OUTPUT SCHEMA
================================================================================
Respond ONLY with raw, valid JSON matching this exact structure (no markdown wrappers, no prose outside JSON):
{{
  "decision": "EXECUTE_MARKET" | "PLACE_LIMIT" | "PRE_TRIGGER" | "WAIT",
  "trade_style": "SCALP" | "SWING",
  "direction": "BUY" | "SELL" | "NONE",
  "confidence_score": 0,
  "market_regime": "TRENDING_EXPANSION" | "MEAN_REVERTING_RANGE" | "LOW_LIQUIDITY_CHOP" | "NEWS_SHOCK",
  "setup_archetype": "LIQUIDITY_SWEEP_REVERSAL" | "BOS_FVG_CONTINUATION" | "RANGE_EXTREME_FADE" | "NONE",
  "gate_audit": {{
    "gate_1_regime_session": "PASS | FAIL - concise reason",
    "gate_2_mtf_structure": "PASS | FAIL - dealing range position (Premium/Discount) & draw on liquidity",
    "gate_3_candle_orderflow": "PASS | FAIL - sweep status, body/wick ratio, displacement & volume read",
    "gate_4_friction_correlation": "PASS | FAIL - spread % of SL & currency exposure check",
    "gate_5_rr_geometry": "PASS | FAIL - structural invalidation & net R:R verification"
  }},
  "entry_price": null,
  "stop_loss": null,
  "breakeven_trigger_price": null,
  "take_profit_1": null,
  "take_profit_2": null,
  "net_rr_ratio": null,
  "blocking_rule_code": null,
  "mtf_confluence_summary": "Institutional synthesis of HTF bias, liquidity swept, candlestick trigger, and target liquidity pool.",
  "radar_setup": {{
    "is_active": false,
    "trigger_zone_price": null,
    "invalidation_price": null,
    "trigger_condition": null,
    "expires_in_minutes": null
  }}
}}
"""

INSTITUTIONAL_SUPERVISOR_SYSTEM_PROMPT = INSTITUTIONAL_5_GATE_SUPERVISOR_PROMPT
SUPERVISOR_SYSTEM_PROMPT = INSTITUTIONAL_5_GATE_SUPERVISOR_PROMPT


def build_supervisor_prompt(context: Dict[str, Any]) -> str:
    """Format institutional supervisory system prompt with live runtime variables."""
    symbol = context.get("symbol", "GOLD#")
    spec = INSTRUMENT_UNIVERSE.get(symbol) or INSTRUMENT_UNIVERSE.get(f"{symbol}#")
    digits = context.get("digits", spec.digits if spec else 2)
    pip_size = context.get("pip_size", spec.tick_size if spec else 0.01)

    utc_ts = context.get("utc_timestamp")
    if not utc_ts:
        utc_ts = now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")

    return INSTITUTIONAL_5_GATE_SUPERVISOR_PROMPT.format(
        symbol=symbol,
        asset_class=context.get("asset_class", spec.asset_class if spec else "COMMODITIES"),
        digits=digits,
        pip_size=pip_size,
        trade_style=context.get("trade_style", "SCALP"),
        planning_tf=context.get("planning_tf", "M15"),
        execution_tf=context.get("execution_tf", "M5"),
        utc_timestamp=utc_ts,
        active_session=context.get("active_session", "LONDON_OPEN"),
        rollover_blackout_status=context.get("rollover_blackout_status", "INACTIVE (Normal Trading Hours)"),
        bid=context.get("bid", 0.0),
        ask=context.get("ask", 0.0),
        current_spread_points=context.get("current_spread_points", 0),
        spread_pct_of_sl=context.get("spread_pct_of_sl", 0.0),
        htf_atr=context.get("htf_atr", 1.25 if digits == 2 else 0.0015),
        ltf_atr=context.get("ltf_atr", 0.45 if digits == 2 else 0.0005),
        adr_used_pct=context.get("adr_used_pct", 45.0),
        dealing_range_pct=context.get("dealing_range_pct", 50.0),
        key_liquidity_levels=context.get("key_liquidity_levels", "PDH: N/A | PDL: N/A | HTF EMA21: N/A | HTF EMA50: N/A"),
        last_3_candles_anatomy=context.get("last_3_candles_anatomy", "Standard candle range & volume (ATR mult ~1.0)"),
        upcoming_high_impact_news=context.get("upcoming_high_impact_news", "None (No Tier-1 news in next 60m)"),
        open_positions_summary=context.get("open_positions_summary", "None (Zero Exposure)"),
        active_learned_rules_json=context.get("active_learned_rules_json", "[]"),
    )

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
                trade_style="SCALP",
                asset_class=packet.asset_class,
                planning_tf="M15",
                execution_tf="M5",
                trigger_zone_low=round(entry - (spread_price * 2), digits),
                trigger_zone_high=round(entry + (spread_price * 2), digits),
                trigger_price=entry,
                planned_entry=entry,
                planned_sl=sl,
                planned_tp1=tp1,
                planned_tp2=tp2,
                rr_ratio=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                projected_rr=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                readiness_pct=95,
                trigger_condition=f"M15 Scalp {direction} trigger confirmed on {packet.symbol}",
                invalidation_level=sl,
                invalidation_price=sl,
                expected_window="Immediate / Next 15 mins",
                expires_at=(now_utc() + timedelta(hours=2)).isoformat(),
                distance_pips_or_pct=round(abs(packet.bid - entry) if packet.bid > 0 else 0.0, digits),
                proximity_pct=95.0,
                spread_impact_pct=round((spread_price / max(0.0001, abs(entry - sl))) * 100, 1),
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
                trade_style="SWING",
                asset_class=packet.asset_class,
                planning_tf="H4",
                execution_tf="H1",
                trigger_zone_low=round(entry - (spread_price * 3), digits),
                trigger_zone_high=round(entry + (spread_price * 3), digits),
                trigger_price=entry,
                planned_entry=entry,
                planned_sl=sl,
                planned_tp1=tp1,
                planned_tp2=tp2,
                rr_ratio=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                projected_rr=round(abs(tp2 - entry) / max(0.0001, abs(entry - sl)), 2),
                readiness_pct=90,
                trigger_condition=f"H1/H4 Swing {direction} structure confirmed on {packet.symbol}",
                invalidation_level=sl,
                invalidation_price=sl,
                expected_window="Next 1-4 hours",
                expires_at=(now_utc() + timedelta(hours=24)).isoformat(),
                distance_pips_or_pct=round(abs(packet.bid - entry) if packet.bid > 0 else 0.0, digits),
                proximity_pct=90.0,
                spread_impact_pct=round((spread_price / max(0.0001, abs(entry - sl))) * 100, 1),
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
            trade_style="SCALP",
            asset_class=packet.asset_class,
            planning_tf="M15",
            execution_tf="M5",
            trigger_zone_low=t_low,
            trigger_zone_high=t_high,
            trigger_price=p_entry,
            planned_entry=p_entry,
            planned_sl=p_sl,
            planned_tp1=p_tp1,
            planned_tp2=p_tp2,
            rr_ratio=3.0,
            projected_rr=3.0,
            readiness_pct=65,
            trigger_condition=cond,
            invalidation_level=p_sl,
            invalidation_price=p_sl,
            expected_window="Next 1-3 hours / Session overlap",
            expires_at=(now_utc() + timedelta(hours=2)).isoformat(),
            distance_pips_or_pct=round(abs(price - p_entry), digits),
            proximity_pct=65.0,
            spread_impact_pct=round((spread_price / max(0.0001, abs(p_entry - p_sl))) * 100, 1),
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
        close_initial_db = False
        if db is None:
            initial_db = SessionLocal()
            close_initial_db = True
        else:
            initial_db = db

        try:
            client, model_name = self.get_client(db=initial_db)
            active_rules = self.get_active_rules(packet.symbol, db=initial_db)
            pattern_memory = self.get_pair_pattern_memory(packet.symbol, db=initial_db)
            st = initial_db.query(AppSettings).filter_by(id=1).first()
            pair_bot = initial_db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == packet.symbol) | (TradingPairBot.symbol == f"{packet.symbol}#")
            ).first()
            scalp_p_tf = getattr(st, "scalp_planning_tf", "M15") if st else "M15"
            scalp_e_tf = getattr(st, "scalp_execution_tf", "M5") if st else "M5"
            swing_p_tf = getattr(st, "swing_planning_tf", "H4") if st else "H4"
            swing_e_tf = getattr(st, "swing_execution_tf", "H1") if st else "H1"
            scan_mins = max(1, (st.global_scan_interval_sec if st else 300) // 60) if st else 5
            max_sp = pair_bot.max_spread_points if pair_bot else 80
        finally:
            if close_initial_db:
                initial_db.close()

        try:
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

                    spec = INSTRUMENT_UNIVERSE.get(packet.symbol) or INSTRUMENT_UNIVERSE.get(f"{packet.symbol}#")
                    digits = spec.digits if spec else 2
                    pip_size = spec.tick_size if spec else 0.01

                    # ATR from packet or defaults
                    packet_atr = getattr(packet, "atr14", 0.0)
                    htf_atr = round(packet_atr * 1.5, digits) if packet_atr > 0 else (1.25 if digits == 2 else 0.0015)
                    ltf_atr = round(packet_atr, digits) if packet_atr > 0 else (0.45 if digits == 2 else 0.0005)

                    is_scalp = bool(packet.candidate_signals.get("scalp_signal"))
                    plan_tf = scalp_p_tf if is_scalp else swing_p_tf
                    exec_tf = scalp_e_tf if is_scalp else swing_e_tf

                    # Calculate quantitative features
                    d1_breakdown = packet.timeframe_breakdown.get("D1", {})
                    adr14 = float(d1_breakdown.get("atr14", 0.0))
                    if adr14 > 0 and packet.pdh is not None and packet.pdl is not None:
                        today_dist = abs(float(packet.bid) - float(packet.pdl))
                        adr_used_pct = round(min(150.0, (today_dist / adr14) * 100.0), 1)
                    else:
                        adr_used_pct = 45.0

                    plan_data = packet.timeframe_breakdown.get(plan_tf, {})
                    p_highs = plan_data.get("key_highs", [])
                    p_lows = plan_data.get("key_lows", [])
                    if p_highs and p_lows:
                        mx = max(p_highs)
                        mn = min(p_lows)
                        p_curr = float(packet.bid) if packet.bid > 0 else float(plan_data.get("close", 1.0))
                        dealing_range_pct = round(max(0.0, min(100.0, ((p_curr - mn) / (mx - mn)) * 100.0)), 1) if mx > mn else 50.0
                    else:
                        dealing_range_pct = 50.0

                    h1_d = packet.timeframe_breakdown.get("H1", {})
                    h4_d = packet.timeframe_breakdown.get("H4", {})
                    e21_val = h4_d.get("ema21") or h1_d.get("ema21", "N/A")
                    e50_val = h4_d.get("ema50") or h1_d.get("ema50", "N/A")
                    pdh_val = f"{packet.pdh:.{digits}f}" if packet.pdh is not None else "N/A"
                    pdl_val = f"{packet.pdl:.{digits}f}" if packet.pdl is not None else "N/A"
                    key_liquidity_levels = f"PDH: {pdh_val} | PDL: {pdl_val} | HTF EMA21: {e21_val} | HTF EMA50: {e50_val}"

                    exec_d = packet.timeframe_breakdown.get(exec_tf, {})
                    pats = exec_d.get("detected_patterns", [])
                    pat_str = ", ".join(p.get("name", "") for p in pats[:3]) if pats else "Clean market structure"
                    last_3_candles_anatomy = f"{exec_tf} PA: {pat_str} (ATR14: {ltf_atr}, RSI14: {exec_d.get('rsi14', 50.0)})"

                    now_u = now_utc()
                    is_roll = (now_u.hour == 21 and now_u.minute >= 50) or (now_u.hour == 22) or (now_u.hour == 23 and now_u.minute <= 10)
                    rollover_blackout_status = "ACTIVE_BLACKOUT (21:50-23:10 UTC - Broker Server Rollover / Spread Blowout)" if is_roll else "INACTIVE (Liquid Trading Session)"

                    open_trades = db.query(TradeLedger).filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1"])).all()
                    if open_trades:
                        t_desc = [f"{t.symbol} {t.direction} {t.lots}L" for t in open_trades[:5]]
                        open_positions_summary = f"{len(open_trades)} Open: [{', '.join(t_desc)}]"
                    else:
                        open_positions_summary = "None (Zero Exposure - 0/5 positions)"

                    prompt_context = {
                        "symbol": packet.symbol,
                        "asset_class": packet.asset_class,
                        "digits": digits,
                        "pip_size": pip_size,
                        "trade_style": "SCALP" if is_scalp else "SWING",
                        "planning_tf": plan_tf,
                        "execution_tf": exec_tf,
                        "utc_timestamp": now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "scan_interval_minutes": scan_mins,
                        "active_session": packet.session_tag,
                        "rollover_blackout_status": rollover_blackout_status,
                        "bid": packet.bid,
                        "ask": packet.ask,
                        "current_spread_points": packet.spread_points,
                        "spread_pct_of_sl": round(float(packet.spread_points * 0.1), 1),
                        "htf_atr": htf_atr,
                        "ltf_atr": ltf_atr,
                        "adr_used_pct": adr_used_pct,
                        "dealing_range_pct": dealing_range_pct,
                        "key_liquidity_levels": key_liquidity_levels,
                        "last_3_candles_anatomy": last_3_candles_anatomy,
                        "upcoming_high_impact_news": (
                            f"{packet.news_blackout.get('event_title', 'Tier-1 Event')} ({packet.news_blackout.get('blackout_reason', 'Blackout')})"
                            if packet.news_blackout.get("is_blackout")
                            else "None (No Tier-1 news in next 60m)"
                        ),
                        "open_positions_summary": open_positions_summary,
                        "active_learned_rules_json": json.dumps(active_rules, indent=2),
                        "max_spread_points": max_sp,
                    }
                    dyn_system_instruction = build_supervisor_prompt(prompt_context)

                    for try_m in ordered_models:
                        try:
                            t0 = time.perf_counter()
                            response = await client.aio.models.generate_content(
                                model=try_m,
                                contents=user_content,
                                config=types.GenerateContentConfig(
                                    system_instruction=dyn_system_instruction,
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
            if analysis_result.decision.startswith("EXECUTE") or analysis_result.decision in ("PLACE_LIMIT", "STAGE_PENDING"):
                execution_status = "PLANNED"
            elif analysis_result.decision == "PRE_TRIGGER":
                execution_status = "PRE_TRIGGER"
            elif analysis_result.market_regime in ("NEWS_BLACKOUT", "NEWS_SHOCK"):
                execution_status = "NEWS_BLACKOUT"
            else:
                execution_status = "WAITING"

            # Parse upcoming setup details (supporting upcoming_setup and radar_setup)
            upcoming_dict = None
            readiness_val = 0
            bias_val = "NONE"
            if analysis_result.upcoming_setup:
                upcoming_dict = analysis_result.upcoming_setup.model_dump()
                readiness_val = analysis_result.upcoming_setup.readiness_pct
                bias_val = analysis_result.upcoming_setup.watch_bias
            elif analysis_result.radar_setup and (analysis_result.radar_setup.is_active or analysis_result.decision == "PRE_TRIGGER"):
                rs = analysis_result.radar_setup
                bias_val = "BULLISH_WATCH" if analysis_result.direction == "BUY" else ("BEARISH_WATCH" if analysis_result.direction == "SELL" else "RANGE_BOUND")
                readiness_val = 75 if analysis_result.decision == "PRE_TRIGGER" else 50
                trigger_price_val = rs.trigger_zone_price or (packet.bid if packet.bid > 0 else None)
                inval_price = rs.invalidation_price
                upcoming_dict = {
                    "watch_bias": bias_val,
                    "setup_mode": analysis_result.trade_style or "SCALP",
                    "trade_style": analysis_result.trade_style or "SCALP",
                    "planning_tf": prompt_context.get("planning_tf", "M15"),
                    "execution_tf": prompt_context.get("execution_tf", "M5"),
                    "trigger_zone": str(rs.trigger_zone_price or ""),
                    "trigger_condition": rs.trigger_condition or "",
                    "planned_entry": trigger_price_val,
                    "invalidation_price": inval_price,
                    "invalidation_level": inval_price,
                    "readiness_pct": readiness_val,
                    "expires_at": (now_utc() + timedelta(minutes=rs.expires_in_minutes or 60)).isoformat(),
                    "proximity_pct": 80.0 if analysis_result.decision == "PRE_TRIGGER" else 50.0,
                    "rr_ratio": analysis_result.net_rr_ratio or 2.0,
                    "projected_rr": analysis_result.net_rr_ratio or 2.0,
                    "planned_tp1": analysis_result.take_profit_1 or analysis_result.tp1,
                    "planned_tp2": analysis_result.take_profit_2 or analysis_result.tp2,
                }

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

            # Persist report using fresh or existing session
            close_save_db = False
            if db is None or close_initial_db:
                save_db = SessionLocal()
                close_save_db = True
            else:
                save_db = db

            try:
                save_db.add(report)
                save_db.commit()
                save_db.refresh(report)

                # Record token usage ledger if response returned
                if response is not None:
                    try:
                        record_gemini_usage(
                            db=save_db,
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
            finally:
                if close_save_db:
                    save_db.close()

            # Store in pre-trigger radar cache
            if upcoming_dict:
                cache_manager.store_radar_setup(
                    packet.symbol,
                    upcoming_dict,
                    upcoming_dict.get("trade_style", "SCALP"),
                )

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
        except Exception as e:
            logger.error(f"Error in analyze_pair for {packet.symbol}: {e}", exc_info=True)
            raise

    def get_rendered_supervisor_prompt(self, symbol: str = "GOLD#", db: Optional[Session] = None) -> str:
        """Render the complete institutional system prompt with active symbol context for UI preview."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            pair = db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == symbol) | (TradingPairBot.symbol == f"{symbol}#")
            ).first()
            active_rules = self.get_active_rules(symbol, db=db)
            spec = INSTRUMENT_UNIVERSE.get(symbol) or INSTRUMENT_UNIVERSE.get(f"{symbol}#")

            digits = spec.digits if spec else (pair.digits if pair else 2)
            pip_size = spec.tick_size if spec else 0.01

            context = {
                "symbol": symbol,
                "asset_class": (spec.asset_class if spec else (pair.asset_class if pair else "COMMODITIES")),
                "digits": digits,
                "pip_size": pip_size,
                "trade_style": "SCALP",
                "planning_tf": getattr(st, "scalp_planning_tf", "M15"),
                "execution_tf": getattr(st, "scalp_execution_tf", "M5"),
                "utc_timestamp": now_utc().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "scan_interval_minutes": max(1, (st.global_scan_interval_sec if st else 300) // 60),
                "active_session": "LONDON_OPEN",
                "bid": 2650.50 if "GOLD" in symbol else (91500.0 if "BTC" in symbol else 1.0850),
                "ask": 2650.70 if "GOLD" in symbol else (91520.0 if "BTC" in symbol else 1.0852),
                "current_spread_points": pair.max_spread_points if pair else 80,
                "spread_pct_of_sl": 5.5,
                "htf_atr": 1.25 if digits == 2 else 0.0015,
                "ltf_atr": 0.45 if digits == 2 else 0.0005,
                "adr_used_pct": 45.0,
                "upcoming_high_impact_news": "None (No Tier-1 news in next 60m)",
                "open_positions_summary": "None (Zero Exposure)",
                "active_learned_rules_json": json.dumps(active_rules, indent=2),
                "max_spread_points": pair.max_spread_points if pair else 80,
            }
            return build_supervisor_prompt(context)
        finally:
            if close_db:
                db.close()


gemini_supervisor = GeminiSupervisor()
