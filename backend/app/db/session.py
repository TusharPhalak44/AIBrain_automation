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
        pool_recycle=1800,
        pool_size=10,
        max_overflow=20,
    )


# Primary application engine and session factory
auto_bootstrap_database()
engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(bind_engine=None) -> None:
    """Create all tables and seed default settings and profiles if missing."""
    eng = bind_engine or engine
    Base.metadata.create_all(bind=eng)

    session_cls = sessionmaker(bind=eng)
    with session_cls() as session:
        # Seed AppSettings singleton (id=1)
        existing_settings = session.query(AppSettings).filter(AppSettings.id == 1).first()
        if not existing_settings:
            default_settings = AppSettings(
                id=1,
                active_account_type="DEMO",
                execution_mode="MONITOR",
                gemini_live_model="gemini-3.8-flash",
                gemini_forensic_model="gemini-3.1-pro-preview",
                global_scan_interval_sec=300,
                display_timezone=settings.DISPLAY_TIMEZONE,
                broker_tz_offset_sec=settings.BROKER_TZ_OFFSET_SEC,
            )
            session.add(default_settings)
        else:
            # Auto-migrate retired gemini-2.5 models to Gemini 3.x
            changed = False
            if "gemini-2.5" in existing_settings.gemini_live_model:
                existing_settings.gemini_live_model = "gemini-3.8-flash"
                changed = True
            if "gemini-2.5" in existing_settings.gemini_forensic_model or "gemini-2.0" in existing_settings.gemini_forensic_model:
                existing_settings.gemini_forensic_model = "gemini-3.1-pro-preview"
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

        # Seed default XM Global pairs (strictly no Indian/US equity feeds)
        default_pairs = [
            ("GOLD#", "METAL", 35, 100.0, 0.01, 1.0, 2),
            ("EURUSD#", "FOREX", 15, 100000.0, 0.00001, 1.0, 5),
            ("GBPUSD#", "FOREX", 18, 100000.0, 0.00001, 1.0, 5),
            ("USDJPY#", "FOREX", 16, 100000.0, 0.001, 0.67, 3),
            ("BTCUSD#", "CRYPTO", 45, 1.0, 0.01, 0.01, 2),
            ("ETHUSD#", "CRYPTO", 40, 1.0, 0.01, 0.01, 2),
            ("SOLUSD#", "CRYPTO", 50, 1.0, 0.01, 0.01, 2),
        ]
        for sym, aclass, max_spread, csize, tsize, tval, dig in default_pairs:
            pair = session.query(TradingPairBot).filter_by(symbol=sym).first()
            if not pair:
                session.add(
                    TradingPairBot(
                        symbol=sym,
                        asset_class=aclass,
                        enabled=True,
                        scalp_enabled=True,
                        swing_enabled=True,
                        max_spread_points=max_spread,
                        contract_size=csize,
                        tick_size=tsize,
                        tick_value=tval,
                        digits=dig,
                    )
                )

        session.commit()

        # Seed 4 built-in starter strategies
        try:
            from backend.app.strategy_lab.builtin_strategies import seed_builtin_strategies
            seed_builtin_strategies(session)
        except Exception as e:
            logger.warning(f"Could not auto-seed built-in strategies: {e}")

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

