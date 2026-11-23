"""Telegram Recipient Management & Notification Testing Routes."""

import secrets
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.db.models import TelegramRecipient, AppSettings
from backend.app.db.session import get_db
from backend.app.telegram_reports.telegram_bot import telegram_service

router = APIRouter(prefix="/telegram", tags=["Telegram Integration"])


class RecipientCreateSchema(BaseModel):
    name: str = Field(..., description="Recipient Name")
    phone_number: Optional[str] = Field(None, description="Contact Phone Number")
    chat_id: Optional[str] = Field(None, description="Telegram Chat ID (if known)")
    is_admin: bool = Field(False, description="Has admin control privileges")
    receive_setups: bool = True
    receive_executions: bool = True
    receive_reports: bool = True


@router.get("/recipients")
def list_recipients(db: Session = Depends(get_db)):
    """List all registered Telegram alert recipients."""
    st = db.query(AppSettings).filter_by(id=1).first()
    bot_username = st.telegram_bot_username if st else ""

    recs = db.query(TelegramRecipient).all()
    res = []
    for r in recs:
        invite_link = f"https://t.me/{bot_username}?start={r.invite_token}" if (bot_username and r.invite_token) else None
        res.append({
            "id": r.id,
            "name": r.name,
            "phone_number": r.phone_number,
            "chat_id": r.chat_id,
            "is_admin": r.is_admin,
            "receive_setups": r.receive_setups,
            "receive_executions": r.receive_executions,
            "receive_reports": r.receive_reports,
            "invite_token": r.invite_token,
            "invite_link": invite_link,
            "is_active": r.is_active,
            "created_at_ist": to_ist_str(r.created_at_utc),
        })
    return res


@router.post("/recipients")
def create_recipient(payload: RecipientCreateSchema, db: Session = Depends(get_db)):
    """Register a new recipient and generate 1-click Telegram invite token."""
    invite_token = secrets.token_urlsafe(16)
    rec = TelegramRecipient(
        name=payload.name,
        phone_number=payload.phone_number,
        chat_id=payload.chat_id,
        is_admin=payload.is_admin,
        receive_setups=payload.receive_setups,
        receive_executions=payload.receive_executions,
        receive_reports=payload.receive_reports,
        invite_token=invite_token,
        is_active=True,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    st = db.query(AppSettings).filter_by(id=1).first()
    bot_username = st.telegram_bot_username if st else ""
    invite_link = f"https://t.me/{bot_username}?start={invite_token}" if bot_username else None

    return {
        "id": rec.id,
        "name": rec.name,
        "invite_token": invite_token,
        "invite_link": invite_link,
        "message": "Recipient registered successfully",
    }


@router.delete("/recipients/{recipient_id}")
def delete_recipient(recipient_id: int, db: Session = Depends(get_db)):
    """Remove a recipient."""
    rec = db.query(TelegramRecipient).filter_by(id=recipient_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Recipient not found")
    db.delete(rec)
    db.commit()
    return {"status": "SUCCESS", "message": f"Recipient #{recipient_id} deleted"}


@router.get("/config")
def get_telegram_config_route(db: Session = Depends(get_db)):
    """Fetch current Telegram alert configuration and category toggle flags."""
    from backend.app.api.routes.ai_brain import get_telegram_config
    return get_telegram_config(db)


@router.patch("/config")
def update_telegram_config_route(payload: dict, db: Session = Depends(get_db)):
    """Update Telegram bot credentials and alert category subscription toggles."""
    from backend.app.api.routes.ai_brain import update_telegram_config, TelegramConfigUpdateSchema
    schema = TelegramConfigUpdateSchema(**payload)
    return update_telegram_config(schema, db)


@router.post("/test")
async def test_telegram_message(
    chat_id: Optional[str] = None,
    template_type: Optional[str] = None,
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Dispatch a test message to verify Telegram bot connectivity (supports template_type preview)."""
    from backend.app.api.routes.ai_brain import send_telegram_test_preview, TelegramTestSchema
    schema = TelegramTestSchema(
        template_type=template_type or "EXECUTION",
        symbol=symbol or "GOLD#",
        chat_id=chat_id,
    )
    return await send_telegram_test_preview(schema, db)

