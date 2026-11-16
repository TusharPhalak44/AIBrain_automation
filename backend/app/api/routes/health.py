"""Health and System Status API Routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.watchdog import watchdog
from backend.app.db.session import get_db
from backend.app.mt5_bridge.connector import mt5_connector

router = APIRouter(prefix="/health", tags=["System Health"])


@router.get("")
async def get_health(db: Session = Depends(get_db)):
    """Comprehensive health check for DB, MT5 IPC, and Watchdog."""
    # Check MySQL
    db_ok = False
    try:
        res = db.execute(text("SELECT 1")).scalar()
        db_ok = (res == 1)
    except Exception:
        db_ok = False

    return {
        "status": "HEALTHY" if (db_ok and watchdog.db_healthy) else "DEGRADED",
        "current_time_utc": now_utc().isoformat(),
        "current_time_ist": to_ist_str(now_utc()),
        "components": {
            "mysql": {
                "status": "CONNECTED" if db_ok else "DISCONNECTED",
                "watchdog_db_healthy": watchdog.db_healthy,
                "offline_spool_records": len(watchdog.get_spooled_records()),
            },
            "mt5_bridge": {
                "is_connected": mt5_connector.is_connected,
                "active_profile": mt5_connector.connected_account_type,
            },
            "watchdog": {
                "active": watchdog._running,
            },
        },
    }


@router.post("/smoke-check")
async def execute_smoke_check(db: Session = Depends(get_db)):
    """1-Click Comprehensive System Smoke Check across all operational bridges."""
    import time
    from backend.app.db.models import AppSettings, MT5AccountProfile, StrategyScript

    t0 = time.perf_counter()
    results = {}

    # 1. MySQL Health
    try:
        res = db.execute(text("SELECT 1")).scalar()
        st = db.query(AppSettings).filter_by(id=1).first()
        strat_cnt = db.query(StrategyScript).count()
        results["mysql"] = {
            "status": "PASS",
            "message": f"Connected to MySQL xm_trading_v2. {strat_cnt} strategies available.",
        }
    except Exception as e:
        results["mysql"] = {"status": "FAIL", "message": str(e)}

    # 2. MT5 IPC Bridge
    results["mt5_bridge"] = {
        "status": "PASS" if mt5_connector.is_connected else "STANDBY",
        "message": f"Connected ({mt5_connector.connected_account_type})" if mt5_connector.is_connected else "Terminal disconnected",
        "is_connected": mt5_connector.is_connected,
    }

    # 3. Watchdog & Spool
    results["watchdog"] = {
        "status": "PASS",
        "spool_count": len(watchdog.get_spooled_records()),
        "db_healthy": watchdog.db_healthy,
    }

    # 4. Gemini AI Configuration
    try:
        from backend.app.ai_brain.gemini_supervisor import gemini_supervisor
        has_key = bool(st and st.gemini_api_key_enc)
        results["gemini_ai"] = {
            "status": "PASS" if has_key else "STANDBY",
            "message": f"Configured ({st.gemini_live_model})" if has_key else "No API key configured in vault",
            "has_key": has_key,
        }
    except Exception as e:
        results["gemini_ai"] = {"status": "FAIL", "message": str(e)}

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    all_pass = all(v["status"] in ("PASS", "STANDBY") for v in results.values())

    return {
        "status": "HEALTHY" if all_pass else "DEGRADED",
        "elapsed_ms": elapsed_ms,
        "results": results,
        "timestamp_ist": to_ist_str(now_utc()),
    }

