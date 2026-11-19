"""FastAPI Application Server Factory and Lifecycle Management."""

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.watchdog import watchdog
from backend.app.db.session import init_db
from backend.app.mt5_bridge.mt5_actor import mt5_actor
from backend.app.mt5_bridge.deal_reconciler import deal_reconciler
from backend.app.telegram_reports.telegram_bot import telegram_service
from backend.app.ai_brain.scheduler import scheduler
from backend.app.api.routes import (
    health,
    settings as settings_route,
    accounts,
    pairs,
    trades,
    reports,
    telegram,
    strategies,
    ai_brain,
    candles,
    usage_analytics,
    db_admin,
)
from backend.app.api import websocket

# Setup logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("XMTradingPortal")


def create_app(enable_lifespan_tasks: bool = True) -> FastAPI:
    """Create and configure FastAPI instance."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Initializing XM Global MT5 Trading Portal V2...")
        try:
            init_db()
        except Exception as e:
            logger.error(f"Database initialization error on startup: {e}")

        if enable_lifespan_tasks:
            await mt5_actor.start()
            watchdog.start()
            deal_reconciler.start()
            deal_reconciler.telegram_notifier = telegram_service.broadcast_trade_event
            telegram_service.start()
            await scheduler.start()

            # Auto-hydrate MT5 terminal connection from saved MySQL profile on boot
            try:
                from pathlib import Path
                from backend.app.db.session import SessionLocal
                from backend.app.db.models import MT5AccountProfile, AppSettings
                from backend.app.mt5_bridge.connector import mt5_connector
                with SessionLocal() as db_session:
                    st = db_session.query(AppSettings).filter_by(id=1).first()
                    active_acc = st.active_account_type if st else "DEMO"
                    prof = db_session.query(MT5AccountProfile).filter_by(account_type=active_acc).first()
                    if prof and prof.terminal_path and Path(prof.terminal_path).exists():
                        logger.info(f"Auto-hydrating MT5 connection for profile '{active_acc}' on server start...")
                        asyncio.create_task(mt5_connector.connect(active_acc))
            except Exception as e:
                logger.warning(f"MT5 startup auto-connect skipped: {e}")

            logger.info("All background safety bridges and services active.")

        yield

        if enable_lifespan_tasks:
            logger.info("Shutting down background services...")
            await scheduler.stop()
            telegram_service.stop()
            deal_reconciler.stop()
            watchdog.stop()
            await mt5_actor.stop()
            logger.info("Shutdown complete.")

    app = FastAPI(
        title="XM Global MT5 V2 Trading Portal API",
        description="Streamlined deterministic algorithmic trading portal for Forex Majors, Gold, BTC, ETH, and SOL.",
        version="2.0.0",
        lifespan=lifespan,
    )

    # Enable CORS for frontend Vite development
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register API Routers
    app.include_router(health.router, prefix="/api")
    app.include_router(settings_route.router, prefix="/api")
    app.include_router(accounts.router, prefix="/api")
    app.include_router(pairs.router, prefix="/api")
    app.include_router(pairs.instruments_router, prefix="/api")
    app.include_router(trades.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(telegram.router, prefix="/api")
    app.include_router(strategies.router, prefix="/api")
    app.include_router(ai_brain.router, prefix="/api")
    app.include_router(ai_brain.brain_router, prefix="/api")
    app.include_router(candles.router, prefix="/api")
    app.include_router(usage_analytics.router, prefix="/api")
    app.include_router(db_admin.router, prefix="/api")
    app.include_router(websocket.router)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.app.api.server:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
