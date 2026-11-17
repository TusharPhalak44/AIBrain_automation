"""Complete SQLAlchemy 2.0 MySQL Schema Models for xm_trading_v2."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base
from backend.app.core.clock_sync import now_utc


class AppSettings(Base):
    """Singleton application-wide settings and risk lock thresholds (id=1)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    active_account_type: Mapped[str] = mapped_column(
        String(8), default="DEMO", nullable=False
    )  # DEMO or LIVE
    execution_mode: Mapped[str] = mapped_column(
        String(16), default="MONITOR", nullable=False
    )  # AUTO, COPILOT, MONITOR, HALTED

    # AI Configuration (Gemini)
    gemini_api_key_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gemini_live_model: Mapped[str] = mapped_column(
        String(64), default="gemini-3.8-flash", nullable=False
    )
    gemini_forensic_model: Mapped[str] = mapped_column(
        String(64), default="gemini-3.1-pro-preview", nullable=False
    )
    global_scan_interval_sec: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    # Hard Risk Locks (Below AI layer)
    scalp_risk_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.50"), nullable=False
    )
    swing_risk_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("1.00"), nullable=False
    )
    max_margin_usage_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("18.00"), nullable=False
    )
    daily_dd_limit_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("2.50"), nullable=False
    )
    weekly_dd_limit_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("5.00"), nullable=False
    )

    # Telegram Reporting & Bot
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    telegram_bot_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    telegram_bot_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_admin_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Timezones
    display_timezone: Mapped[str] = mapped_column(
        String(32), default="Asia/Kolkata", nullable=False
    )
    broker_tz_offset_sec: Mapped[int] = mapped_column(
        Integer, default=7200, nullable=False
    )  # Dynamic broker UTC offset (e.g. 7200 = GMT+2)

    # Gemini Usage & Free Tier Switch
    gemini_use_free_tier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Remote MySQL Hosting & Backup Hub
    remote_db_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    remote_db_port: Mapped[Optional[int]] = mapped_column(Integer, default=3306, nullable=True)
    remote_db_user: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    remote_db_pass_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    remote_db_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    active_db_target: Mapped[str] = mapped_column(
        String(16), default="LOCAL_XAMPP", nullable=False
    )  # LOCAL_XAMPP or REMOTE_HOSTED

    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class MT5AccountProfile(Base):
    """MT5 Profile configurations strictly partitioned for DEMO and LIVE accounts."""

    __tablename__ = "mt5_account_profiles"

    account_type: Mapped[str] = mapped_column(
        String(8), primary_key=True
    )  # DEMO or LIVE
    login_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    server_name: Mapped[str] = mapped_column(
        String(128), default="XMGlobal-MT5", nullable=False
    )
    terminal_path: Mapped[str] = mapped_column(
        String(512),
        default=r"C:\Program Files\XM Global MT5\terminal64.exe",
        nullable=False,
    )
    symbol_suffix: Mapped[str] = mapped_column(
        String(16), default="#", nullable=False
    )  # '#' for XM Ultra Low, '' for Standard, 'm#' for Micro
    account_currency: Mapped[str] = mapped_column(
        String(8), default="USD", nullable=False
    )
    leverage: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    last_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    last_equity: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class TradingPairBot(Base):
    """Trading pair specifications and per-pair bot parameters."""

    __tablename__ = "trading_pair_bots"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g., GOLD#, EURUSD#, BTCUSD#
    asset_class: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # METAL, FOREX, CRYPTO
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scalp_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    swing_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scan_interval_sec: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    scalp_strategy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    swing_strategy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    risk_pct_scalp: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.50"), nullable=False
    )
    risk_pct_swing: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("1.00"), nullable=False
    )
    max_spread_points: Mapped[int] = mapped_column(Integer, default=35, nullable=False)

    # Broker Instrument Specs (populated from MT5 symbol_info)
    contract_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("100.0000"), nullable=False
    )
    tick_size: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("0.010000"), nullable=False
    )
    tick_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), default=Decimal("1.000000"), nullable=False
    )
    digits: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    stops_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    volume_min: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0.0100"), nullable=False
    )
    volume_step: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0.0100"), nullable=False
    )
    swap_long: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0.0000"), nullable=False
    )
    swap_short: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), default=Decimal("0.0000"), nullable=False
    )
    three_day_swap_day: Mapped[int] = mapped_column(
        Integer, default=3, nullable=False
    )  # 3 = Wednesday
    ea_last_heartbeat_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class StrategyScript(Base):
    """User-defined or built-in Python Strategy Sandbox scripts."""

    __tablename__ = "strategy_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_mode: Mapped[str] = mapped_column(
        String(16), default="BOTH", nullable=False
    )  # SCALP, SWING, BOTH
    python_code: Mapped[str] = mapped_column(Text, nullable=False)
    default_params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class BacktestRun(Base):
    """Backtesting results with realistic fee and slippage accounting."""

    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    test_mode: Mapped[str] = mapped_column(
        String(32), default="ACCOUNT_100", nullable=False
    )  # ACCOUNT_100, PER_TRADE_100
    capital_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("100.00"), nullable=False
    )
    total_trades: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    gross_pnl_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    spread_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    swap_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    commission_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    net_pnl_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    net_roi_pct: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    max_dd_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    profit_factor: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    is_saved_bookmark: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    custom_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    strategy_code_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    params_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trades_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class TradeLedger(Base):
    """Central ledger for all planned, open, and closed positions."""

    __tablename__ = "trade_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_type: Mapped[str] = mapped_column(
        String(8), default="DEMO", nullable=False, index=True
    )  # DEMO or LIVE
    position_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )  # MT5 Position ID
    order_ticket: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    magic_number: Mapped[int] = mapped_column(
        Integer, default=1001, nullable=False, index=True
    )  # 1001 = SCALP, 2001 = SWING, 0 = MANUAL
    mode: Mapped[str] = mapped_column(
        String(16), default="SCALP", nullable=False
    )  # SCALP, SWING, MANUAL
    direction: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY or SELL
    status: Mapped[str] = mapped_column(
        String(16), default="OPEN", nullable=False, index=True
    )  # PLANNED, PENDING, OPEN, PARTIAL_TP1, CLOSED

    lots: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )  # Current remaining lots
    initial_lots: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False
    )  # Initial entry lots
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    sl: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tp1: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    tp2: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)

    entry_spread_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    slippage_points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    gross_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    commission: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    swap: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    net_pnl: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )

    r_multiple: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    mae_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    mfe_r: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # TP_HIT, SL_HIT, TRAIL_SL, MANUAL_MOBILE, KILL_SWITCH

    strategy_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    entry_order_type: Mapped[str] = mapped_column(
        String(16), default="MARKET", nullable=False
    )  # MARKET, LIMIT
    detected_patterns_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ai_analysis_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    loss_postmortem_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    opened_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )
    closed_at_utc: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PairPatternMemory(Base):
    """Per-pair price-action pattern scorecard and self-learning memory (GOLD# vs BTCUSD# isolated)."""

    __tablename__ = "pair_pattern_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # GOLD# or BTCUSD#
    mode: Mapped[str] = mapped_column(String(16), default="SCALP", nullable=False)  # SCALP or SWING
    pattern_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_tag: Mapped[str] = mapped_column(String(32), default="ALL", nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    avg_r_multiple: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    net_pnl_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="NEUTRAL", nullable=False
    )  # PROVEN_EDGE, NEUTRAL, BLOCKED_TRAP
    last_ai_lesson: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class LearnedPairRule(Base):
    """Self-learning JSON filter rules produced by offline AI postmortems."""

    __tablename__ = "learned_pair_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # SCALP or SWING
    status: Mapped[str] = mapped_column(
        String(16), default="CANDIDATE", nullable=False
    )  # CANDIDATE, LIVE, LOCKED, DEPRECATED
    condition_json: Mapped[str] = mapped_column(Text, nullable=False)
    action_json: Mapped[str] = mapped_column(Text, nullable=False)
    origin_loss_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    backtest_net_improvement_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), nullable=False
    )
    profit_factor_before: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    profit_factor_after: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    net_r_delta: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    winners_preserved_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100.00"), nullable=False
    )
    avoided_losses_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    trigger_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recent_profit_factor: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), nullable=False
    )
    shadow_scorecard_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class TelegramRecipient(Base):
    """Subscribers authorized to receive setup cards, executions, and reports."""

    __tablename__ = "telegram_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, index=True
    )
    chat_id: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    receive_setups: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    receive_executions: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    receive_reports: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    invite_token: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class SystemHealthEvent(Base):
    """Operational audit log for safety bridges, disconnects, and recon events."""

    __tablename__ = "system_health_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_time_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False, index=True
    )
    account_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(16), default="INFO", nullable=False
    )  # INFO, WARNING, ERROR, CRITICAL
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GeminiAnalysisReport(Base):
    """Supervisory AI market structure, regime analysis and trade plan thesis."""

    __tablename__ = "gemini_analysis_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_type: Mapped[str] = mapped_column(
        String(8), default="DEMO", nullable=False, index=True
    )  # DEMO or LIVE
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    scanned_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False, index=True
    )
    market_regime: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # TRENDING_UP, TRENDING_DOWN, RANGE_SWEEP, HIGH_VOLATILITY_CHOP, NEWS_BLACKOUT
    decision: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # EXECUTE_SCALP, EXECUTE_SWING, EXECUTE_BOTH, STAGE_PENDING, WAIT
    recommended_mode: Mapped[str] = mapped_column(
        String(16), default="NONE", nullable=False
    )  # SCALP, SWING, BOTH, NONE
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 2), default=Decimal("0.00"), nullable=False
    )  # 0.00 to 1.00
    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    stop_loss: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    tp1: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    tp2: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    news_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thesis_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_status: Mapped[str] = mapped_column(
        String(32), default="PLANNED", nullable=False
    )  # EXECUTED, PLANNED, WAITING, NEWS_BLACKOUT, REJECTED, MONITOR_ONLY
    raw_snapshot_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    upcoming_setup_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    readiness_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    watch_bias: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)


class MacroNewsEvent(Base):
    """High-impact economic calendar events and Tier-1 blackout schedule."""

    __tablename__ = "macro_news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_time_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False, index=True)  # USD, EUR, GBP, JPY
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    impact: Mapped[str] = mapped_column(
        String(16), default="HIGH", nullable=False
    )  # HIGH, MEDIUM, LOW
    forecast: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    previous: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    actual: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False
    )


class GeminiModelRateCard(Base):
    """Configurable rate card for Gemini token pricing and Free Tier eligibility."""

    __tablename__ = "gemini_model_rate_cards"

    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    input_per_1m_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0.7500"), nullable=False
    )
    output_per_1m_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("3.7500"), nullable=False
    )
    cached_per_1m_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("0.0750"), nullable=False
    )
    is_free_tier_eligible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class GeminiUsageLedger(Base):
    """Detailed token consumption and USD cost accounting ledger for all Gemini API invocations."""

    __tablename__ = "gemini_usage_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, nullable=False, index=True
    )
    ist_date: Mapped[str] = mapped_column(
        String(10), nullable=False, index=True
    )  # YYYY-MM-DD in Asia/Kolkata
    account_type: Mapped[str] = mapped_column(
        String(8), default="DEMO", nullable=False
    )  # DEMO or LIVE
    symbol: Mapped[str] = mapped_column(
        String(32), default="GLOBAL", nullable=False
    )  # e.g. GOLD#, EURUSD#, GLOBAL
    model_id: Mapped[str] = mapped_column(String(64), nullable=False)
    call_purpose: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # LIVE_SCAN, MANUAL_SCAN, SL_FORENSICS, RULE_VALIDATION, KEY_TEST
    billing_tier: Mapped[str] = mapped_column(
        String(16), default="PAID", nullable=False
    )  # PAID or FREE
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    thinking_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), default=Decimal("0.000000"), nullable=False
    )
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    report_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

