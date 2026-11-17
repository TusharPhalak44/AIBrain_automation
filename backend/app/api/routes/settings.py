"""Application Settings and Configuration Routes."""

from decimal import Decimal
import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from google import genai

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.crypto_vault import crypto_vault
from backend.app.db.models import AppSettings
from backend.app.db.session import get_db
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor
from backend.app.ai_brain.usage_tracker import record_gemini_usage

router = APIRouter(prefix="/settings", tags=["Application Settings"])


class SettingsUpdateSchema(BaseModel):
    execution_mode: Optional[str] = Field(None, description="AUTO, COPILOT, MONITOR, HALTED")
    gemini_api_key: Optional[str] = Field(None, description="Plain Gemini API Key (or bullet masked)")
    gemini_live_model: Optional[str] = None
    gemini_forensic_model: Optional[str] = None
    global_scan_interval_sec: Optional[int] = None
    scalp_risk_pct: Optional[float] = None
    swing_risk_pct: Optional[float] = None
    max_margin_usage_pct: Optional[float] = None
    daily_dd_limit_pct: Optional[float] = None
    weekly_dd_limit_pct: Optional[float] = None
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_bot_username: Optional[str] = None
    telegram_admin_chat_id: Optional[str] = None
    display_timezone: Optional[str] = None
    broker_tz_offset_sec: Optional[int] = None
    gemini_use_free_tier: Optional[bool] = None


class TestGeminiKeySchema(BaseModel):
    api_key: Optional[str] = None
    model: Optional[str] = "gemini-3.8-flash"


def _serialize_settings(st: AppSettings) -> Dict[str, Any]:
    gemini_plain = crypto_vault.decrypt_secret(st.gemini_api_key_enc) if st.gemini_api_key_enc else ""
    tg_plain = crypto_vault.decrypt_secret(st.telegram_bot_token_enc) if st.telegram_bot_token_enc else ""

    return {
        "id": st.id,
        "active_account_type": st.active_account_type,
        "execution_mode": st.execution_mode,
        "gemini_api_key_masked": crypto_vault.mask_secret(gemini_plain) if gemini_plain else "",
        "has_gemini_api_key": bool(gemini_plain),
        "gemini_live_model": st.gemini_live_model,
        "gemini_forensic_model": st.gemini_forensic_model,
        "global_scan_interval_sec": st.global_scan_interval_sec,
        "scalp_risk_pct": float(st.scalp_risk_pct),
        "swing_risk_pct": float(st.swing_risk_pct),
        "max_margin_usage_pct": float(st.max_margin_usage_pct),
        "daily_dd_limit_pct": float(st.daily_dd_limit_pct),
        "weekly_dd_limit_pct": float(st.weekly_dd_limit_pct),
        "telegram_enabled": st.telegram_enabled,
        "telegram_bot_token_masked": crypto_vault.mask_secret(tg_plain) if tg_plain else "",
        "has_telegram_bot_token": bool(tg_plain),
        "telegram_bot_username": st.telegram_bot_username,
        "telegram_admin_chat_id": st.telegram_admin_chat_id,
        "display_timezone": st.display_timezone,
        "broker_tz_offset_sec": st.broker_tz_offset_sec,
        "gemini_use_free_tier": bool(getattr(st, "gemini_use_free_tier", False)),
        "active_db_target": getattr(st, "active_db_target", "LOCAL_XAMPP"),
        "remote_db_host": getattr(st, "remote_db_host", None),
        "remote_db_port": getattr(st, "remote_db_port", 3306),
        "remote_db_user": getattr(st, "remote_db_user", None),
        "remote_db_name": getattr(st, "remote_db_name", None),
        "updated_at_utc": st.updated_at_utc.isoformat() if st.updated_at_utc else None,
        "updated_at_ist": to_ist_str(st.updated_at_utc) if st.updated_at_utc else "-",
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    """Fetch singleton application settings with masked secrets."""
    st = db.query(AppSettings).filter_by(id=1).first()
    if not st:
        st = AppSettings(id=1, execution_mode="COPILOT")
        db.add(st)
        db.commit()
        db.refresh(st)

    return _serialize_settings(st)


def _apply_settings_update(payload: SettingsUpdateSchema, db: Session) -> AppSettings:
    st = db.query(AppSettings).filter_by(id=1).first()
    if not st:
        st = AppSettings(id=1, execution_mode="COPILOT")
        db.add(st)
        db.commit()

    if payload.execution_mode is not None and payload.execution_mode.strip():
        st.execution_mode = payload.execution_mode.strip().upper()
    if payload.gemini_live_model is not None and payload.gemini_live_model.strip():
        st.gemini_live_model = payload.gemini_live_model.strip()
    if payload.gemini_forensic_model is not None and payload.gemini_forensic_model.strip():
        st.gemini_forensic_model = payload.gemini_forensic_model.strip()
    if payload.global_scan_interval_sec is not None:
        st.global_scan_interval_sec = payload.global_scan_interval_sec
    if payload.scalp_risk_pct is not None:
        st.scalp_risk_pct = Decimal(str(payload.scalp_risk_pct))
    if payload.swing_risk_pct is not None:
        st.swing_risk_pct = Decimal(str(payload.swing_risk_pct))
    if payload.max_margin_usage_pct is not None:
        st.max_margin_usage_pct = Decimal(str(payload.max_margin_usage_pct))
    if payload.daily_dd_limit_pct is not None:
        st.daily_dd_limit_pct = Decimal(str(payload.daily_dd_limit_pct))
    if payload.weekly_dd_limit_pct is not None:
        st.weekly_dd_limit_pct = Decimal(str(payload.weekly_dd_limit_pct))
    if payload.telegram_enabled is not None:
        st.telegram_enabled = payload.telegram_enabled
    if payload.telegram_bot_username is not None:
        st.telegram_bot_username = payload.telegram_bot_username.strip()
    if payload.telegram_admin_chat_id is not None:
        st.telegram_admin_chat_id = payload.telegram_admin_chat_id.strip()
    if payload.display_timezone is not None:
        st.display_timezone = payload.display_timezone.strip()
    if payload.broker_tz_offset_sec is not None:
        st.broker_tz_offset_sec = payload.broker_tz_offset_sec
    if payload.gemini_use_free_tier is not None:
        st.gemini_use_free_tier = payload.gemini_use_free_tier

    # Secret encryption with bullet mask protection
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip():
        clean_key = payload.gemini_api_key.strip()
        if not crypto_vault.is_masked_value(clean_key) and clean_key != "••••••••":
            st.gemini_api_key_enc = crypto_vault.encrypt_secret(clean_key)
            gemini_supervisor.reload_client()

    if payload.telegram_bot_token is not None and payload.telegram_bot_token.strip():
        clean_token = payload.telegram_bot_token.strip()
        if not crypto_vault.is_masked_value(clean_token) and clean_token != "••••••••":
            st.telegram_bot_token_enc = crypto_vault.encrypt_secret(clean_token)

    st.updated_at_utc = now_utc()
    db.commit()
    return st


@router.put("")
@router.post("")
def update_settings(payload: SettingsUpdateSchema, db: Session = Depends(get_db)):
    """Update settings while guaranteeing that masked values NEVER overwrite encrypted secrets."""
    st = _apply_settings_update(payload, db)
    serialized = _serialize_settings(st)
    return {
        "status": "SUCCESS",
        "message": "Settings updated successfully",
        "settings": serialized,
        **serialized,
    }


@router.get("/gemini-models")
def list_gemini_models(db: Session = Depends(get_db)):
    """List available Gemini 3.x models for the configured API key with recommended defaults."""
    st = db.query(AppSettings).filter_by(id=1).first()
    default_models = [
        {"id": "gemini-3.8-flash", "display_name": "Gemini 3.8 Flash (Live Recommended: Sub-Second Latency)"},
        {"id": "gemini-3-flash-preview", "display_name": "Gemini 3 Flash Preview"},
        {"id": "gemini-3.5-flash-lite", "display_name": "Gemini 3.5 Flash Lite (Ultra-Low Latency)"},
        {"id": "gemini-3.1-pro-preview", "display_name": "Gemini 3.1 Pro Preview (Forensic/Pro: Deep Reasoning)"},
    ]

    if not st or not st.gemini_api_key_enc:
        return {"status": "SUCCESS", "models": default_models}

    try:
        key = crypto_vault.decrypt_secret(st.gemini_api_key_enc)
        test_client = genai.Client(api_key=key)
        fetched_models = []
        for m in test_client.models.list():
            name = m.name.replace("models/", "") if hasattr(m, "name") else str(m)
            disp = getattr(m, "display_name", name)
            if "gemini" in name.lower() and ("3" in name.lower() or "flash" in name.lower() or "pro" in name.lower()):
                fetched_models.append({"id": name, "display_name": f"{disp} ({name})"})

        if fetched_models:
            return {"status": "SUCCESS", "models": fetched_models}
    except Exception:
        pass

    return {"status": "SUCCESS", "models": default_models}


@router.post("/test-gemini")
def test_gemini_key(payload: Optional[TestGeminiKeySchema] = None, db: Session = Depends(get_db)):
    """
    Test Gemini API key validity and measure response latency via official google-genai SDK.
    """
    st = db.query(AppSettings).filter_by(id=1).first()
    key_to_test = None

    if payload and payload.api_key and payload.api_key.strip():
        k = payload.api_key.strip()
        if not crypto_vault.is_masked_value(k) and k != "••••••••":
            key_to_test = k

    if not key_to_test and st and st.gemini_api_key_enc:
        key_to_test = crypto_vault.decrypt_secret(st.gemini_api_key_enc)

    if not key_to_test:
        raise HTTPException(
            status_code=400,
            detail={"error": "NO_API_KEY", "message": "No Gemini API key provided or saved in database."},
        )

    raw_model = (payload.model if payload and payload.model else None) or (st.gemini_live_model if st else "gemini-3.8-flash")
    model_to_use = raw_model.replace("models/", "")
    if "2.5" in model_to_use:
        model_to_use = "gemini-3.8-flash"

    # Candidates for fallback
    candidates = [model_to_use, "gemini-3.8-flash", "gemini-3-flash-preview", "gemini-3.1-pro-preview"]
    seen = set()
    ordered_models = []
    for m in candidates:
        if m not in seen:
            seen.add(m)
            ordered_models.append(m)

    test_client = genai.Client(api_key=key_to_test)
    last_err = None

    for candidate_model in ordered_models:
        try:
            t0 = time.perf_counter()
            resp = test_client.models.generate_content(
                model=candidate_model,
                contents="State 'CONNECTED' in one word.",
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            reply_text = resp.text.strip() if resp and resp.text else "CONNECTED"
            try:
                record_gemini_usage(
                    db=db,
                    model_id=candidate_model,
                    call_purpose="KEY_TEST",
                    response=resp,
                    latency_ms=latency_ms,
                    symbol="GLOBAL",
                )
            except Exception:
                pass
            return {
                "status": "SUCCESS",
                "message": f"Successfully verified Gemini API key on model '{candidate_model}' in {latency_ms}ms.",
                "model": candidate_model,
                "latency_ms": latency_ms,
                "response_text": reply_text,
            }
        except Exception as e:
            last_err = e

    raise HTTPException(
        status_code=400,
        detail={
            "error": "GEMINI_TEST_FAILED",
            "message": f"Gemini API verification failed: {str(last_err)}",
        },
    )
