"""MySQL Database Administration, Remote Hosting, Migration & SQL Dump Hub."""

from datetime import datetime, timezone
from decimal import Decimal
import io
import json
import logging
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.schema import CreateTable
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.crypto_vault import crypto_vault
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
)
from backend.app.db.session import engine as local_engine, get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/db-admin", tags=["Database & Cloud Hosting"])


class DbConnectionPayload(BaseModel):
    host: str = Field(..., description="MySQL host or IP, e.g. sql.mycpanel.com or 127.0.0.1")
    port: int = Field(3306, description="MySQL port")
    user: str = Field(..., description="MySQL username")
    password: str = Field("", description="MySQL password")
    database: str = Field(..., description="Database name")
    sync_data: bool = Field(True, description="Sync local XAMPP tables to remote hosting database")


@router.get("/status")
def get_db_status(db: Session = Depends(get_db)):
    """Inspect active MySQL target, latency, table row counts, and spool status."""
    st = db.query(AppSettings).filter_by(id=1).first()
    active_target = getattr(st, "active_db_target", "LOCAL_XAMPP") if st else "LOCAL_XAMPP"

    # Ping current active database
    latency_ms = 0.0
    server_version = "Unknown"
    is_connected = False
    try:
        t0 = time.perf_counter()
        res = db.execute(text("SELECT VERSION();")).fetchone()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        server_version = str(res[0]) if res else "MySQL"
        is_connected = True
    except Exception as e:
        logger.error(f"Failed to ping active database: {e}")

    # Row counts
    table_counts = {}
    total_rows = 0
    model_list = [
        ("app_settings", AppSettings),
        ("mt5_account_profiles", MT5AccountProfile),
        ("trading_pair_bots", TradingPairBot),
        ("strategy_scripts", StrategyScript),
        ("backtest_runs", BacktestRun),
        ("trade_ledger", TradeLedger),
        ("learned_pair_rules", LearnedPairRule),
        ("telegram_recipients", TelegramRecipient),
        ("system_health_events", SystemHealthEvent),
        ("gemini_analysis_reports", GeminiAnalysisReport),
        ("macro_news_events", MacroNewsEvent),
        ("gemini_model_rate_cards", GeminiModelRateCard),
        ("gemini_usage_ledger", GeminiUsageLedger),
    ]

    for tbl_name, model_cls in model_list:
        try:
            cnt = db.query(model_cls).count()
            table_counts[tbl_name] = cnt
            total_rows += cnt
        except Exception:
            table_counts[tbl_name] = 0

    # Spool health check
    spool_status = {"spool_active": False, "spool_rows": 0, "status": "HEALTHY"}
    try:
        from backend.app.db.spool import offline_spool
        spool_status = {
            "spool_active": True,
            "spool_rows": offline_spool.pending_count(),
            "status": "CLEAR" if offline_spool.pending_count() == 0 else "DRAINING",
        }
    except Exception:
        pass

    remote_pass_saved = bool(st and st.remote_db_pass_enc)

    return {
        "status": "SUCCESS",
        "active_target": active_target,
        "is_connected": is_connected,
        "latency_ms": latency_ms,
        "server_version": server_version,
        "database_name": settings.MYSQL_DATABASE if active_target == "LOCAL_XAMPP" else (st.remote_db_name if st else ""),
        "host": settings.MYSQL_HOST if active_target == "LOCAL_XAMPP" else (st.remote_db_host if st else ""),
        "port": settings.MYSQL_PORT if active_target == "LOCAL_XAMPP" else (st.remote_db_port if st else 3306),
        "total_rows": total_rows,
        "table_counts": table_counts,
        "spool_health": spool_status,
        "remote_profile": {
            "host": st.remote_db_host if st else None,
            "port": st.remote_db_port if st else 3306,
            "user": st.remote_db_user if st else None,
            "database": st.remote_db_name if st else None,
            "has_password": remote_pass_saved,
        },
    }


@router.post("/test-connection")
def test_remote_mysql_connection(payload: DbConnectionPayload):
    """Test remote cPanel/phpMyAdmin MySQL connection without switching active target."""
    user = payload.user.strip()
    pwd = payload.password.strip()
    host = payload.host.strip()
    port = payload.port
    db_name = payload.database.strip()

    # If password empty, check if saved in DB
    if not pwd:
        db = SessionLocal()
        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st and st.remote_db_pass_enc:
                pwd = crypto_vault.decrypt_secret(st.remote_db_pass_enc) or ""
        finally:
            db.close()

    uri = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db_name}?charset=utf8mb4"

    try:
        t0 = time.perf_counter()
        test_eng = create_engine(uri, pool_pre_ping=True, connect_args={"connect_timeout": 7})
        with test_eng.connect() as conn:
            ver = conn.execute(text("SELECT VERSION();")).scalar()
            conn.execute(text("SELECT 1;"))
        test_eng.dispose()
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "status": "SUCCESS",
            "success": True,
            "message": f"Successfully connected to remote MySQL on '{host}:{port}/{db_name}' in {latency_ms}ms.",
            "server_version": str(ver),
            "latency_ms": latency_ms,
        }
    except Exception as e:
        logger.warning(f"Remote MySQL connection test failed: {e}")
        return {
            "status": "ERROR",
            "success": False,
            "message": f"Remote MySQL connection failed: {str(e)}",
            "latency_ms": 0.0,
            "server_version": None,
        }


@router.post("/apply-connection")
def apply_remote_mysql_connection(payload: DbConnectionPayload, db: Session = Depends(get_db)):
    """
    Save remote connection profile, create all tables via Base.metadata.create_all(),
    and optionally synchronize existing data from local XAMPP to remote database.
    """
    user = payload.user.strip()
    pwd = payload.password.strip()
    host = payload.host.strip()
    port = payload.port
    db_name = payload.database.strip()

    st = db.query(AppSettings).filter_by(id=1).first()

    if not pwd and st and st.remote_db_pass_enc:
        pwd = crypto_vault.decrypt_secret(st.remote_db_pass_enc) or ""

    remote_uri = f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db_name}?charset=utf8mb4"

    try:
        remote_eng = create_engine(remote_uri, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        # 1. Verify connection
        with remote_eng.connect() as conn:
            conn.execute(text("SELECT 1;"))

        # 2. Deploy complete schema on remote database
        Base.metadata.create_all(bind=remote_eng)

        synced_counts = {}
        # 3. If requested, sync all local table data to remote
        if payload.sync_data:
            model_list = [
                ("app_settings", AppSettings),
                ("mt5_account_profiles", MT5AccountProfile),
                ("trading_pair_bots", TradingPairBot),
                ("strategy_scripts", StrategyScript),
                ("backtest_runs", BacktestRun),
                ("trade_ledger", TradeLedger),
                ("learned_pair_rules", LearnedPairRule),
                ("telegram_recipients", TelegramRecipient),
                ("system_health_events", SystemHealthEvent),
                ("gemini_analysis_reports", GeminiAnalysisReport),
                ("macro_news_events", MacroNewsEvent),
                ("gemini_model_rate_cards", GeminiModelRateCard),
                ("gemini_usage_ledger", GeminiUsageLedger),
            ]

            RemoteSession = sessionmaker(bind=remote_eng)
            with RemoteSession() as rem_session:
                for tbl_name, model_cls in model_list:
                    local_rows = db.query(model_cls).all()
                    synced_count = 0
                    for row in local_rows:
                        # Extract dict of row attributes
                        row_dict = {
                            c.key: getattr(row, c.key)
                            for c in inspect(model_cls).mapper.column_attrs
                        }
                        # Merge into remote session
                        rem_session.merge(model_cls(**row_dict))
                        synced_count += 1
                    rem_session.commit()
                    synced_counts[tbl_name] = synced_count

        # 4. Save credentials into local AppSettings
        if st:
            st.remote_db_host = host
            st.remote_db_port = port
            st.remote_db_user = user
            st.remote_db_name = db_name
            if payload.password and payload.password.strip():
                st.remote_db_pass_enc = crypto_vault.encrypt_secret(payload.password.strip())
            st.active_db_target = "REMOTE_HOSTED"
            st.updated_at_utc = now_utc()
            db.commit()

        remote_eng.dispose()

        return {
            "status": "SUCCESS",
            "message": f"Successfully initialized and synchronized schema to remote MySQL ({host}:{port}/{db_name}).",
            "active_target": "REMOTE_HOSTED",
            "synced_tables": synced_counts,
        }
    except Exception as e:
        logger.error(f"Failed to apply remote connection: {e}", exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={"error": "REMOTE_APPLY_FAILED", "message": f"Could not initialize remote database: {str(e)}"},
        )


@router.post("/switch-target")
def switch_active_db_target(target: str = "LOCAL_XAMPP", db: Session = Depends(get_db)):
    """Switch active database target between LOCAL_XAMPP and REMOTE_HOSTED."""
    tgt = target.upper().strip()
    if tgt not in ["LOCAL_XAMPP", "REMOTE_HOSTED"]:
        raise HTTPException(status_code=400, detail="Target must be LOCAL_XAMPP or REMOTE_HOSTED.")

    st = db.query(AppSettings).filter_by(id=1).first()
    if st:
        st.active_db_target = tgt
        st.updated_at_utc = now_utc()
        db.commit()

    return {"status": "SUCCESS", "active_target": tgt}


@router.get("/export-sql")
def export_sql_dump(include_history: bool = False, db: Session = Depends(get_db)):
    """
    Generate clean, phpMyAdmin & cPanel compatible SQL dump with CREATE TABLE IF NOT EXISTS
    and REPLACE INTO statements for all xm_trading_v2 tables.
    """
    out = io.StringIO()
    utc_str = now_utc().isoformat()
    ist_str = to_ist_str(now_utc())

    out.write(f"-- =====================================================================\n")
    out.write(f"-- XM TRADING V2 - INSTITUTIONAL SQL DUMP FOR PHPMYADMIN / CPANEL\n")
    out.write(f"-- Generated At UTC: {utc_str} | IST: {ist_str}\n")
    out.write(f"-- Compatible with MySQL 5.7+, MySQL 8.0+, MariaDB 10.3+\n")
    out.write(f"-- =====================================================================\n\n")
    out.write(f"SET FOREIGN_KEY_CHECKS=0;\n")
    out.write(f"SET SQL_MODE='NO_AUTO_VALUE_ON_ZERO';\n")
    out.write(f"SET time_zone = '+00:00';\n\n")

    model_list = [
        ("app_settings", AppSettings),
        ("mt5_account_profiles", MT5AccountProfile),
        ("trading_pair_bots", TradingPairBot),
        ("strategy_scripts", StrategyScript),
        ("backtest_runs", BacktestRun),
        ("trade_ledger", TradeLedger),
        ("learned_pair_rules", LearnedPairRule),
        ("telegram_recipients", TelegramRecipient),
        ("system_health_events", SystemHealthEvent),
        ("gemini_analysis_reports", GeminiAnalysisReport),
        ("macro_news_events", MacroNewsEvent),
        ("gemini_model_rate_cards", GeminiModelRateCard),
        ("gemini_usage_ledger", GeminiUsageLedger),
    ]

    for tbl_name, model_cls in model_list:
        # Generate DDL CREATE TABLE IF NOT EXISTS
        try:
            ddl = str(CreateTable(model_cls.__table__).compile(local_engine)).strip()
            # Replace CREATE TABLE with CREATE TABLE IF NOT EXISTS
            if ddl.startswith("CREATE TABLE "):
                ddl = ddl.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
            out.write(f"-- --------------------------------------------------------\n")
            out.write(f"-- Table schema for `{tbl_name}`\n")
            out.write(f"-- --------------------------------------------------------\n")
            out.write(f"{ddl};\n\n")
        except Exception as ex:
            logger.warning(f"Could not compile CreateTable for {tbl_name}: {ex}")

        # Fetch rows
        query = db.query(model_cls)
        if tbl_name == "gemini_analysis_reports" and not include_history:
            rows = query.order_by(GeminiAnalysisReport.scanned_at_utc.desc()).limit(50).all()
        else:
            rows = query.all()

        columns = [c.key for c in inspect(model_cls).mapper.column_attrs]

        out.write(f"-- Data for `{tbl_name}` ({len(rows)} rows)\n")
        if not rows:
            out.write(f"-- (No rows to insert)\n\n")
            continue

        for r in rows:
            vals = []
            for col in columns:
                val = getattr(r, col)
                if val is None:
                    vals.append("NULL")
                elif isinstance(val, (int, float, Decimal)):
                    vals.append(str(val))
                elif isinstance(val, bool):
                    vals.append("1" if val else "0")
                elif isinstance(val, datetime):
                    vals.append(f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'")
                else:
                    escaped = str(val).replace("\\", "\\\\").replace("'", "''")
                    vals.append(f"'{escaped}'")

            col_names = ", ".join([f"`{c}`" for c in columns])
            val_names = ", ".join(vals)
            out.write(f"REPLACE INTO `{tbl_name}` ({col_names}) VALUES ({val_names});\n")

        out.write("\n")

    out.write(f"SET FOREIGN_KEY_CHECKS=1;\n")
    out.write(f"-- End of SQL Dump\n")

    sql_content = out.getvalue()
    filename = f"xm_trading_v2_dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"

    return Response(
        content=sql_content,
        media_type="application/sql",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export-settings-json")
def export_settings_json(db: Session = Depends(get_db)):
    """Export complete system configuration, pairs, rules, and rate cards as portable JSON backup."""
    st = db.query(AppSettings).filter_by(id=1).first()
    profiles = db.query(MT5AccountProfile).all()
    pairs = db.query(TradingPairBot).all()
    rules = db.query(LearnedPairRule).all()
    strategies = db.query(StrategyScript).all()
    rates = db.query(GeminiModelRateCard).all()

    payload = {
        "version": "2.0",
        "exported_at_utc": now_utc().isoformat(),
        "exported_at_ist": to_ist_str(now_utc()),
        "app_settings": {
            c.key: getattr(st, c.key) for c in inspect(AppSettings).mapper.column_attrs if c.key != "id"
        } if st else {},
        "mt5_profiles": [
            {c.key: getattr(p, c.key) for c in inspect(MT5AccountProfile).mapper.column_attrs}
            for p in profiles
        ],
        "pairs": [
            {c.key: getattr(p, c.key) for c in inspect(TradingPairBot).mapper.column_attrs}
            for p in pairs
        ],
        "rules": [
            {c.key: getattr(r, c.key) for c in inspect(LearnedPairRule).mapper.column_attrs}
            for r in rules
        ],
        "strategies": [
            {c.key: getattr(s, c.key) for c in inspect(StrategyScript).mapper.column_attrs}
            for s in strategies
        ],
        "rate_cards": [
            {c.key: getattr(rc, c.key) for c in inspect(GeminiModelRateCard).mapper.column_attrs}
            for rc in rates
        ],
    }

    # Convert datetimes and decimals to JSON serializable types
    def _sanitize(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, Decimal):
            return float(o)
        raise TypeError

    json_str = json.dumps(payload, indent=2, default=_sanitize)
    filename = f"xm_settings_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import-settings-json")
def import_settings_json(data: Dict[str, Any], db: Session = Depends(get_db)):
    """Restore configuration, pairs, rules, and rate cards from portable JSON backup."""
    imported_counts = {}
    try:
        if "app_settings" in data and isinstance(data["app_settings"], dict):
            st = db.query(AppSettings).filter_by(id=1).first()
            if not st:
                st = AppSettings(id=1)
                db.add(st)
            for k, v in data["app_settings"].items():
                if hasattr(st, k) and k != "id" and v is not None:
                    setattr(st, k, Decimal(str(v)) if isinstance(getattr(st, k), Decimal) else v)
            db.commit()
            imported_counts["app_settings"] = 1

        if "pairs" in data and isinstance(data["pairs"], list):
            cnt = 0
            for p_dict in data["pairs"]:
                sym = p_dict.get("symbol")
                if sym:
                    pair = db.query(TradingPairBot).filter_by(symbol=sym).first()
                    if not pair:
                        pair = TradingPairBot(symbol=sym)
                        db.add(pair)
                    for k, v in p_dict.items():
                        if hasattr(pair, k) and v is not None:
                            setattr(pair, k, Decimal(str(v)) if isinstance(getattr(pair, k), Decimal) else v)
                    cnt += 1
            db.commit()
            imported_counts["pairs"] = cnt

        if "rate_cards" in data and isinstance(data["rate_cards"], list):
            cnt = 0
            for r_dict in data["rate_cards"]:
                mid = r_dict.get("model_id")
                if mid:
                    rc = db.query(GeminiModelRateCard).filter_by(model_id=mid).first()
                    if not rc:
                        rc = GeminiModelRateCard(model_id=mid)
                        db.add(rc)
                    for k, v in r_dict.items():
                        if hasattr(rc, k) and v is not None:
                            setattr(rc, k, Decimal(str(v)) if isinstance(getattr(rc, k), Decimal) else v)
                    cnt += 1
            db.commit()
            imported_counts["rate_cards"] = cnt

        return {
            "status": "SUCCESS",
            "message": "Settings and database parameters successfully imported.",
            "imported": imported_counts,
        }
    except Exception as e:
        logger.error(f"Failed to import settings JSON: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Import failed: {str(e)}")
