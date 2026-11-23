"""MT5 Account Profiles & Safe Demo/Live Switching Routes."""

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.crypto_vault import crypto_vault
from backend.app.db.models import MT5AccountProfile
from backend.app.db.session import get_db
from backend.app.mt5_bridge.connector import mt5_connector, resolve_terminal_path, CANDIDATE_PATHS

router = APIRouter(prefix="/accounts", tags=["Account Profiles"])


class ProfileUpdateSchema(BaseModel):
    login_id: Optional[Any] = None
    password: Optional[str] = Field(None, description="Plain MT5 password or masked bullets")
    server_name: Optional[str] = None
    terminal_path: Optional[str] = None
    symbol_suffix: Optional[str] = None
    account_currency: Optional[str] = None
    leverage: Optional[int] = None


class ConnectRequestSchema(BaseModel):
    account_type: str = "DEMO"
    login_id: Optional[Any] = None
    password: Optional[str] = None
    server_name: Optional[str] = None
    terminal_path: Optional[str] = None


class SwitchProfileSchema(BaseModel):
    target_account_type: str = Field(..., description="DEMO or LIVE")
    action_on_positions: str = Field("KEEP_EA_PROTECTED", description="KEEP_EA_PROTECTED or FLATTEN_FIRST")
    confirm_token: Optional[str] = Field(None, description="Required for LIVE: 'CONFIRM_LIVE_TRADING'")


def _serialize_profile(p: MT5AccountProfile) -> Dict[str, Any]:
    pwd_plain = crypto_vault.decrypt_secret(p.password_enc) if p.password_enc else ""
    return {
        "account_type": p.account_type,
        "login_id": p.login_id,
        "password_masked": crypto_vault.mask_secret(pwd_plain, is_password=True) if pwd_plain else "",
        "has_password": bool(pwd_plain),
        "server_name": p.server_name,
        "terminal_path": p.terminal_path,
        "symbol_suffix": p.symbol_suffix,
        "account_currency": p.account_currency,
        "leverage": p.leverage,
        "last_balance": float(p.last_balance),
        "last_equity": float(p.last_equity),
        "is_connected": p.is_connected,
        "updated_at_utc": p.updated_at_utc.isoformat() if p.updated_at_utc else None,
        "updated_at_ist": to_ist_str(p.updated_at_utc) if p.updated_at_utc else "-",
    }


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    """List all account profiles."""
    profiles = db.query(MT5AccountProfile).all()
    return [_serialize_profile(p) for p in profiles]


@router.get("/live-state")
async def get_account_live_state():
    """Fetch instantaneous live account, risk, quotes, and scheduler state (REST fallback)."""
    from backend.app.api.websocket import get_live_state
    return await get_live_state()


@router.get("/profiles/{account_type}")
@router.get("/{account_type}")
def get_profile(account_type: str, db: Session = Depends(get_db)):
    """Fetch details for a specific account profile (DEMO or LIVE)."""
    acc_type = account_type.upper()
    if acc_type not in ["DEMO", "LIVE"]:
        raise HTTPException(status_code=400, detail=f"Invalid account type '{account_type}'. Must be 'DEMO' or 'LIVE'.")
    p = db.query(MT5AccountProfile).filter_by(account_type=acc_type).first()
    if not p:
        raise HTTPException(status_code=404, detail=f"Profile '{account_type}' not found")
    return _serialize_profile(p)


def _apply_profile_update(p: MT5AccountProfile, payload: ProfileUpdateSchema, db: Session):
    if payload.login_id is not None:
        val = str(payload.login_id).strip()
        if val.isdigit():
            p.login_id = int(val)
        elif val == "":
            p.login_id = None
    if payload.server_name is not None and payload.server_name.strip():
        p.server_name = payload.server_name.strip()
    if payload.terminal_path is not None and payload.terminal_path.strip():
        p.terminal_path = payload.terminal_path.strip()
    if payload.symbol_suffix is not None:
        p.symbol_suffix = payload.symbol_suffix.strip()
    if payload.account_currency is not None:
        p.account_currency = payload.account_currency.strip()
    if payload.leverage is not None:
        p.leverage = payload.leverage

    if payload.password is not None and payload.password.strip():
        pwd = payload.password.strip()
        # Protect existing password if masked bullets or unchanged
        if not crypto_vault.is_masked_value(pwd) and pwd != "••••••••":
            p.password_enc = crypto_vault.encrypt_secret(pwd)

    p.updated_at_utc = now_utc()
    db.commit()


@router.post("/connect")
@router.post("/test-connect")
async def connect_mt5(payload: Optional[ConnectRequestSchema] = None, db: Session = Depends(get_db)):
    """
    Connect to XM Global MT5 terminal.
    Saves any unsaved form inputs directly to database first, then initializes MT5 actor.
    """
    acc_type = payload.account_type.upper() if payload and payload.account_type else "DEMO"
    p = db.query(MT5AccountProfile).filter_by(account_type=acc_type).first()
    if not p:
        p = MT5AccountProfile(
            account_type=acc_type,
            server_name="XMGlobal-MT5",
            terminal_path=r"C:\Program Files\XM Global MT5\terminal64.exe",
        )
        db.add(p)
        db.commit()

    # If payload provided override inputs, persist them first
    if payload:
        update_schema = ProfileUpdateSchema(
            login_id=payload.login_id,
            password=payload.password,
            server_name=payload.server_name,
            terminal_path=payload.terminal_path,
        )
        _apply_profile_update(p, update_schema, db)

    # Perform MT5 connection
    login_int = int(p.login_id) if p.login_id else None
    plain_pwd = crypto_vault.decrypt_secret(p.password_enc) if p.password_enc else None

    ok, msg = await mt5_connector.connect(
        account_type=acc_type,
        login_override=login_int,
        password_override=plain_pwd,
        server_override=p.server_name,
        terminal_path_override=p.terminal_path,
    )

    if not ok:
        raise HTTPException(
            status_code=400,
            detail={"error": "CONNECT_FAILED", "message": msg},
        )

    return {
        "status": "SUCCESS",
        "message": msg,
        "account_type": acc_type,
        "is_connected": True,
        "balance": float(p.last_balance),
        "equity": float(p.last_equity),
    }


@router.post("/detect-path")
def detect_mt5_path():
    """Auto-detect installed XM MT5 terminal64.exe path on Windows."""
    for p in CANDIDATE_PATHS:
        if Path(p).exists():
            return {
                "status": "SUCCESS",
                "detected_path": p,
                "exists": True,
            }

    # Check settings fallback
    from backend.app.core.config import settings
    default_p = settings.XM_MT5_TERMINAL_PATH
    exists = Path(default_p).exists()
    return {
        "status": "SUCCESS" if exists else "NOT_FOUND",
        "detected_path": default_p,
        "exists": exists,
    }


@router.post("/sync")
@router.post("/sync-symbols")
async def sync_symbols():
    """Sync live specifications from MT5 for all trading pairs."""
    res = await mt5_connector.sync_xm_pair_specs()
    return {"status": "SUCCESS", "pairs": res}


@router.post("/switch")
async def switch_profile(payload: SwitchProfileSchema):
    """Execute guarded transition between DEMO and LIVE trading profiles."""
    ok, result = await mt5_connector.switch_account_profile(
        target_account_type=payload.target_account_type,
        action_on_positions=payload.action_on_positions,
        confirm_token=payload.confirm_token,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return result


@router.put("/profiles/{account_type}")
@router.put("/{account_type}")
@router.post("/{account_type}")
def update_profile(account_type: str, payload: ProfileUpdateSchema, db: Session = Depends(get_db)):
    """Update profile details ensuring masked passwords do not overwrite encrypted storage."""
    acc_type = account_type.upper()
    if acc_type not in ["DEMO", "LIVE"]:
        raise HTTPException(status_code=400, detail=f"Invalid account type '{account_type}'. Must be 'DEMO' or 'LIVE'.")
    p = db.query(MT5AccountProfile).filter_by(account_type=acc_type).first()
    if not p:
        # Create profile row if missing
        p = MT5AccountProfile(
            account_type=acc_type,
            server_name="XMGlobal-MT5",
            terminal_path=r"C:\Program Files\XM Global MT5\terminal64.exe",
        )
        db.add(p)
        db.commit()

    _apply_profile_update(p, payload, db)
    serialized = _serialize_profile(p)
    return {
        "status": "SUCCESS",
        "message": f"Profile {acc_type} updated successfully",
        "profile": serialized,
        **serialized,
    }
