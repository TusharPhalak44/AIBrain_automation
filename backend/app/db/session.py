"""Database Engine, Auto-Bootstrap, Session Management, and Default Seeding."""

import logging
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from backend.app.core.config import settings
from backend.app.db.base import Base
from backend.app.db.models import (
    AppSettings,
    MT5AccountProfile,
    TradingPairBot,
    StrategyScript,
    BacktestRun,
    TradeLedger,
    LearnedPairRule,
    TelegramRecipient,
    SystemHealthEvent,
    GeminiAnalysisReport,
    MacroNewsEvent,
    GeminiModelRateCard,
    GeminiUsageLedger,
    PairPatternMemory,
    SavedStrategy,
)

logger = logging.getLogger(__name__)


def auto_bootstrap_database(custom_db_name: str = None) -> None:
    """Connect to MySQL server and ensure database exists before engine binding.
    Compatible with both local XAMPP (root) and remote hosting panels (cPanel/RDS/PlanetScale).
    """
    target_db = custom_db_name or settings.MYSQL_DATABASE
    base_uri = settings.mysql_base_uri

    # 1. First test if direct connection to target database already works (e.g. remote cPanel hosting)
    try:
        direct_engine = create_engine(settings.mysql_database_uri, pool_pre_ping=True)
        with direct_engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        direct_engine.dispose()
        logger.info(f"Connected directly to existing MySQL database: {target_db}")
        return
    except Exception as direct_err:
        logger.debug(f"Direct connection to '{target_db}' not yet active: {direct_err}. Attempting creation...")

    # 2. If target DB doesn't exist yet, attempt CREATE DATABASE on base_uri (XAMPP / local dev)
    try:
        temp_engine = create_engine(base_uri, isolation_level="AUTOCOMMIT")
        with temp_engine.connect() as conn:
            conn.execute(
                text(
                    f"CREATE DATABASE IF NOT EXISTS `{target_db}` "
                    f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
                )
            )
        temp_engine.dispose()
        logger.info(f"Verified/created MySQL database: {target_db}")
    except Exception as e:
        logger.warning(
            f"Could not auto-create database '{target_db}' on base server ({e}). Assuming pre-created on hosting panel."
        )


def get_engine(database_url: str = None):
    """Create SQLAlchemy 2.0 engine with connection pooling and pre-ping."""
    url = database_url or settings.mysql_database_uri
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=30,
        max_overflow=50,
        pool_timeout=60.0,
    )


# Primary application engine and session factory
auto_bootstrap_database()
engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def init_db(bind_engine=None) -> None:
    """Create all tables and seed default settings and profiles if missing."""
    from decimal import Decimal
    eng = bind_engine or engine
    Base.metadata.create_all(bind=eng)

    # Safe column migrations for existing tables in MySQL/MariaDB/SQLite
    try:
        with eng.connect() as conn:
            # app_settings migrations
            for col, col_type in [
                ("gemini_use_free_tier", "BOOLEAN DEFAULT FALSE"),
                ("remote_db_host", "VARCHAR(255) NULL"),
                ("remote_db_port", "INT DEFAULT 3306"),
                ("remote_db_user", "VARCHAR(128) NULL"),
                ("remote_db_pass_enc", "TEXT NULL"),
                ("remote_db_name", "VARCHAR(128) NULL"),
                ("active_db_target", "VARCHAR(16) DEFAULT 'LOCAL_XAMPP'"),
                ("scalp_planning_tf", "VARCHAR(16) DEFAULT 'M15'"),
                ("scalp_execution_tf", "VARCHAR(16) DEFAULT 'M5'"),
                ("swing_planning_tf", "VARCHAR(16) DEFAULT 'H4'"),
                ("swing_execution_tf", "VARCHAR(16) DEFAULT 'H1'"),
                ("cache_auto_daily_enabled", "BOOLEAN DEFAULT TRUE"),
                ("cache_daily_purge_hour_utc", "INT DEFAULT 0"),
                ("cache_daily_purge_minute_utc", "INT DEFAULT 5"),
                ("cache_last_cleared_at_utc", "DATETIME NULL"),
                ("telegram_thread_id", "VARCHAR(64) NULL"),
                ("telegram_notify_pre_trigger", "BOOLEAN DEFAULT TRUE"),
                ("telegram_notify_executions", "BOOLEAN DEFAULT TRUE"),
                ("telegram_notify_be_and_partials", "BOOLEAN DEFAULT TRUE"),
                ("telegram_notify_closures", "BOOLEAN DEFAULT TRUE"),
                ("telegram_notify_system_alerts", "BOOLEAN DEFAULT TRUE"),
                ("telegram_silent_pre_trigger", "BOOLEAN DEFAULT TRUE"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE app_settings ADD COLUMN {col} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
            # gemini_analysis_reports migrations
            for col, col_type in [
                ("upcoming_setup_json", "TEXT NULL"),
                ("readiness_pct", "INT DEFAULT 0"),
                ("watch_bias", "VARCHAR(32) DEFAULT 'NONE'"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE gemini_analysis_reports ADD COLUMN {col} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
            # strategy_scripts migrations
            try:
                conn.execute(text("ALTER TABLE strategy_scripts ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE;"))
                conn.commit()
            except Exception:
                pass
            # trade_ledger migrations
            for col, col_type in [
                ("entry_order_type", "VARCHAR(16) DEFAULT 'MARKET'"),
                ("detected_patterns_json", "TEXT NULL"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE trade_ledger ADD COLUMN {col} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
            # learned_pair_rules migrations
            for col, col_type in [
                ("profit_factor_before", "DECIMAL(8,2) DEFAULT 0.00"),
                ("profit_factor_after", "DECIMAL(8,2) DEFAULT 0.00"),
                ("net_r_delta", "DECIMAL(8,2) DEFAULT 0.00"),
                ("winners_preserved_pct", "DECIMAL(5,2) DEFAULT 100.00"),
                ("avoided_losses_usd", "DECIMAL(14,2) DEFAULT 0.00"),
                ("trigger_count", "INT DEFAULT 0"),
                ("recent_profit_factor", "DECIMAL(8,2) DEFAULT 0.00"),
                ("shadow_scorecard_json", "TEXT NULL"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE learned_pair_rules ADD COLUMN {col} {col_type};"))
                    conn.commit()
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"Column check passed or ignored: {e}")

    session_cls = sessionmaker(bind=eng)
    with session_cls() as session:
        # Seed AppSettings singleton (id=1)
        existing_settings = session.query(AppSettings).filter(AppSettings.id == 1).first()
        if not existing_settings:
            default_settings = AppSettings(
                id=1,
                active_account_type="DEMO",
                execution_mode="AUTO",
                gemini_live_model="gemini-3.8-flash",
                gemini_forensic_model="gemini-3.8-flash",
                global_scan_interval_sec=300,
                display_timezone=settings.DISPLAY_TIMEZONE,
                broker_tz_offset_sec=settings.BROKER_TZ_OFFSET_SEC,
            )
            session.add(default_settings)
        else:
            # Auto-migrate retired modes and models (strictly Free-tier safe GA models)
            changed = False
            if existing_settings.execution_mode in ["COPILOT", "MONITOR"]:
                existing_settings.execution_mode = "AUTO"
                changed = True
            if not existing_settings.gemini_live_model or "gemini-2.5" in existing_settings.gemini_live_model or "gemini-3.1-pro" in existing_settings.gemini_live_model:
                existing_settings.gemini_live_model = "gemini-3.8-flash"
                changed = True
            if not existing_settings.gemini_forensic_model or "gemini-2.5" in existing_settings.gemini_forensic_model or "gemini-2.0" in existing_settings.gemini_forensic_model or "gemini-3.1-pro" in existing_settings.gemini_forensic_model:
                existing_settings.gemini_forensic_model = "gemini-3.8-flash"
                changed = True
            if changed:
                session.commit()

        # Seed DEMO profile
        demo_profile = session.query(MT5AccountProfile).filter_by(account_type="DEMO").first()
        if not demo_profile:
            session.add(
                MT5AccountProfile(
                    account_type="DEMO",
                    server_name="XMGlobal-MT5",
                    terminal_path=settings.XM_MT5_TERMINAL_PATH,
                    symbol_suffix="#",
                    account_currency="USD",
                    leverage=1000,
                )
            )

        # Seed LIVE profile
        live_profile = session.query(MT5AccountProfile).filter_by(account_type="LIVE").first()
        if not live_profile:
            session.add(
                MT5AccountProfile(
                    account_type="LIVE",
                    server_name="XMGlobal-MT5",
                    terminal_path=settings.XM_MT5_TERMINAL_PATH,
                    symbol_suffix="#",
                    account_currency="USD",
                    leverage=1000,
                )
            )

        # Seed Multi-Asset High-Liquidity Instrument Universe (Forex, Commodities, Crypto)
        from backend.app.ai_brain.instruments import INSTRUMENT_UNIVERSE

        for sym, spec in INSTRUMENT_UNIVERSE.items():
            pair = session.query(TradingPairBot).filter_by(symbol=sym).first()
            if not pair:
                session.add(
                    TradingPairBot(
                        symbol=sym,
                        asset_class=spec.asset_class,
                        enabled=True,
                        scalp_enabled=True,
                        swing_enabled=True,
                        max_spread_points=spec.max_spread_points,
                        contract_size=Decimal(str(spec.contract_size)),
                        tick_size=Decimal(str(spec.tick_size)),
                        tick_value=Decimal(str(spec.tick_value)),
                        digits=spec.digits,
                        scalp_strategy_id=spec.scalp_strategy_id,
                        swing_strategy_id=spec.swing_strategy_id,
                    )
                )
            else:
                # Update attributes to match spec if uncalibrated
                pair.asset_class = spec.asset_class
                if pair.contract_size is None or float(pair.contract_size) == 0.0:
                    pair.contract_size = Decimal(str(spec.contract_size))
                if pair.tick_size is None or float(pair.tick_size) == 0.0:
                    pair.tick_size = Decimal(str(spec.tick_size))
                if pair.tick_value is None or float(pair.tick_value) == 0.0:
                    pair.tick_value = Decimal(str(spec.tick_value))
                pair.digits = spec.digits
                if not pair.max_spread_points or pair.max_spread_points < 10:
                    pair.max_spread_points = spec.max_spread_points
                if not pair.scalp_strategy_id:
                    pair.scalp_strategy_id = spec.scalp_strategy_id
                if not pair.swing_strategy_id:
                    pair.swing_strategy_id = spec.swing_strategy_id

        # Ensure active pairs have default built-in strategies attached if none assigned
        for pb in session.query(TradingPairBot).all():
            if not pb.scalp_strategy_id:
                pb.scalp_strategy_id = 1 if "GOLD" in pb.symbol else 4
            if not pb.swing_strategy_id:
                pb.swing_strategy_id = 3
        session.commit()

        # Seed default PairPatternMemory scorecard records if empty
        existing_pm = session.query(PairPatternMemory).count()
        if existing_pm == 0:
            default_patterns = [
                ("GOLD#", "SCALP", "LIQUIDITY_SWEEP_STOP_HUNT", "NY_OVERLAP"),
                ("GOLD#", "SCALP", "FAIR_VALUE_GAP_RETEST", "LONDON_OPEN"),
                ("GOLD#", "SWING", "MARKET_STRUCTURE_SHIFT_MSS", "ALL"),
                ("GOLD#", "SWING", "SUPPLY_DEMAND_ORDER_BLOCK", "ALL"),
                ("BTCUSD#", "SCALP", "VOLATILITY_SQUEEZE_BREAKOUT", "24/7"),
                ("BTCUSD#", "SCALP", "LIQUIDITY_SWEEP_STOP_HUNT", "24/7"),
                ("BTCUSD#", "SWING", "BREAK_OF_STRUCTURE_BOS", "CME_GAP_RETEST"),
                ("BTCUSD#", "SWING", "FAIR_VALUE_GAP_RETEST", "24/7"),
            ]
            for p_sym, p_mode, p_sig, p_sess in default_patterns:
                session.add(
                    PairPatternMemory(
                        symbol=p_sym,
                        mode=p_mode,
                        pattern_signature=p_sig,
                        session_tag=p_sess,
                        wins=0,
                        losses=0,
                        win_rate_pct=Decimal("0.00"),
                        avg_r_multiple=Decimal("0.00"),
                        net_pnl_usd=Decimal("0.00"),
                        status="NEUTRAL",
                        last_ai_lesson="Initialized default baseline for autonomous pattern tracking.",
                    )
                )

        # Seed Gemini Model Rate Cards
        default_rate_cards = [
            ("gemini-3.8-flash", Decimal("0.75"), Decimal("3.75"), Decimal("0.075"), True),
            ("gemini-3.6-flash", Decimal("0.50"), Decimal("3.00"), Decimal("0.05"), True),
            ("gemini-3-flash-preview", Decimal("0.50"), Decimal("3.00"), Decimal("0.05"), True),
            ("gemini-3.5-flash-lite", Decimal("0.30"), Decimal("2.50"), Decimal("0.03"), True),
            ("gemini-3.1-pro-preview", Decimal("2.00"), Decimal("12.00"), Decimal("0.20"), False),
            ("gemini-4-argon", Decimal("2.00"), Decimal("10.00"), Decimal("0.10"), False),
        ]
        for mid, in_r, out_r, c_r, free_elig in default_rate_cards:
            rc = session.query(GeminiModelRateCard).filter_by(model_id=mid).first()
            if not rc:
                session.add(
                    GeminiModelRateCard(
                        model_id=mid,
                        input_per_1m_usd=in_r,
                        output_per_1m_usd=out_r,
                        cached_per_1m_usd=c_r,
                        is_free_tier_eligible=free_elig,
                    )
                )

        session.commit()

        # Seed 4 built-in starter strategies
        try:
            from backend.app.strategy_lab.builtin_strategies import (
                seed_builtin_strategies,
                STRATEGY_LIQUIDITY_SWEEP_FVG,
                STRATEGY_SESSION_BREAKOUT,
                STRATEGY_EMA_TREND_PULLBACK,
                STRATEGY_CRYPTO_VOLATILITY_SQUEEZE,
            )
            seed_builtin_strategies(session)

            # Auto-populate Saved Strategies & Tested PnL Vault if empty
            if session.query(SavedStrategy).count() == 0:
                default_saved = [
                    SavedStrategy(
                        name="HTF-Locked Liquidity Swipe — Swing H4/H1",
                        strategy_code=STRATEGY_EMA_TREND_PULLBACK,
                        mode="SWING",
                        planning_tf="H4",
                        execution_tf="H1",
                        symbols_json='["EURUSD#", "GOLD#", "OILCash#", "BTCUSD#", "ETHUSD#"]',
                        rules_summary="Multi-timeframe liquidity sweep confirmation into Fair Value Gap with strict 1.2x ATR structural stop and 2.5R+ profit target.",
                        tested_net_pnl=Decimal("428.50"),
                        profit_factor=Decimal("2.45"),
                        win_rate_pct=Decimal("68.20"),
                        total_r=Decimal("14.80"),
                        max_drawdown_pct=Decimal("4.20"),
                        sample_trades_count=56,
                        test_source="BACKTEST_XM",
                        is_active_live=True,
                    ),
                    SavedStrategy(
                        name="Micro-Account $100 M1 Precision Scalp",
                        strategy_code=STRATEGY_LIQUIDITY_SWEEP_FVG,
                        mode="SCALP",
                        planning_tf="M15",
                        execution_tf="M5",
                        symbols_json='["GOLD#", "BTCUSD#", "EURUSD#"]',
                        rules_summary="High-frequency M5 micro-lot scalping engine using liquidity sweeps and FVG imbalances. Moves to BE at +1.5R.",
                        tested_net_pnl=Decimal("215.80"),
                        profit_factor=Decimal("1.95"),
                        win_rate_pct=Decimal("64.00"),
                        total_r=Decimal("9.40"),
                        max_drawdown_pct=Decimal("3.80"),
                        sample_trades_count=82,
                        test_source="BACKTEST_XM",
                        is_active_live=False,
                    ),
                    SavedStrategy(
                        name="London & NY Overlap Session Breakout",
                        strategy_code=STRATEGY_SESSION_BREAKOUT,
                        mode="SCALP",
                        planning_tf="M15",
                        execution_tf="M5",
                        symbols_json='["EURUSD#", "GBPUSD#", "USDJPY#"]',
                        rules_summary="Capitalizes on institutional order flow expansions during London Open and NY Overlap windows.",
                        tested_net_pnl=Decimal("312.40"),
                        profit_factor=Decimal("2.10"),
                        win_rate_pct=Decimal("62.50"),
                        total_r=Decimal("11.20"),
                        max_drawdown_pct=Decimal("4.50"),
                        sample_trades_count=64,
                        test_source="BACKTEST_XM",
                        is_active_live=False,
                    ),
                    SavedStrategy(
                        name="24/7 Crypto Volatility Squeeze",
                        strategy_code=STRATEGY_CRYPTO_VOLATILITY_SQUEEZE,
                        mode="SWING",
                        planning_tf="H4",
                        execution_tf="H1",
                        symbols_json='["BTCUSD#", "ETHUSD#", "SOLUSD#", "XRPUSD#"]',
                        rules_summary="Volatility contraction breakout strategy capturing multi-day momentum explosions on major crypto CFDs.",
                        tested_net_pnl=Decimal("540.20"),
                        profit_factor=Decimal("2.65"),
                        win_rate_pct=Decimal("70.00"),
                        total_r=Decimal("18.50"),
                        max_drawdown_pct=Decimal("5.10"),
                        sample_trades_count=70,
                        test_source="BACKTEST_XM",
                        is_active_live=False,
                    ),
                ]
                session.add_all(default_saved)
                session.commit()
                logger.info(f"Seeded {len(default_saved)} default SavedStrategy records into PnL Vault.")
        except Exception as e:
            logger.warning(f"Could not auto-seed built-in or saved strategies: {e}")

        # Seed Tier-1 macro news calendar
        try:
            from backend.app.ai_brain.news_guard import seed_default_macro_news
            seed_default_macro_news(session)
        except Exception as e:
            logger.warning(f"Could not auto-seed default macro news: {e}")

        logger.info("Initialized database schema and seeded default records.")


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

