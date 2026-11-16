"""Official Telegram Bot Service with Contact Onboarding, Trade Cards & Admin Controls."""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.crypto_vault import crypto_vault

logger = logging.getLogger(__name__)

Tuple_Config = Tuple[Optional[str], Optional[str], Optional[str]]


class TelegramService:
    """Async Telegram Bot client supporting 1-click contact onboarding and two-way admin commands."""

    def __init__(self):
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._last_update_id: int = 0
        self.http_client: Optional[httpx.AsyncClient] = None

    def _get_bot_config(self) -> Tuple_Config:
        """Fetch active decrypted bot token and admin chat ID from MySQL."""
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import AppSettings

        with SessionLocal() as db:
            st = db.query(AppSettings).filter_by(id=1).first()
            if not st or not st.telegram_enabled or not st.telegram_bot_token_enc:
                return None, None, None
            token = crypto_vault.decrypt_secret(st.telegram_bot_token_enc)
            return token, st.telegram_admin_chat_id, st.telegram_bot_username

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a message to a specific Telegram chat."""
        token, _, _ = self._get_bot_config()
        if not token:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to send Telegram message to {chat_id}: {e}")
            return False

    async def send_document(
        self,
        chat_id: str,
        document_bytes: bytes,
        filename: str,
        caption: Optional[str] = None,
    ) -> bool:
        """Upload and send a file attachment (PDF/CSV/XLSX) to a Telegram chat."""
        token, _, _ = self._get_bot_config()
        if not token:
            return False

        url = f"https://api.telegram.org/bot{token}/sendDocument"
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"

        files = {"document": (filename, document_bytes)}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(url, data=data, files=files)
                return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to send Telegram document to {chat_id}: {e}")
            return False

    async def broadcast_setup_alert(self, setup_data: Dict[str, Any]) -> int:
        """Broadcast an upcoming trade setup card to all registered setup recipients."""
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import TelegramRecipient

        card = (
            f"🎯 <b>NEW TRADE SETUP DETECTED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Pair:</b> <code>{setup_data.get('symbol')}</code>\n"
            f"• <b>Mode:</b> <b>{setup_data.get('mode', 'SCALP')}</b> (Magic {setup_data.get('magic', 1001)})\n"
            f"• <b>Direction:</b> <b>{setup_data.get('direction', 'BUY')}</b>\n"
            f"• <b>Entry:</b> <code>{setup_data.get('entry_price')}</code>\n"
            f"• <b>Hard SL:</b> <code>{setup_data.get('sl')}</code>\n"
            f"• <b>TP1 (1.5R):</b> <code>{setup_data.get('tp1')}</code>\n"
            f"• <b>TP2:</b> <code>{setup_data.get('tp2')}</code>\n"
            f"• <b>Volume:</b> <code>{setup_data.get('lots')} lots</code>\n"
            f"• <b>Risk:</b> <code>${setup_data.get('cash_risk', 0.0):.2f}</code>\n"
            f"• <b>Time:</b> {to_ist_str(now_utc())}\n\n"
            f"🧠 <b>AI Rationale:</b>\n"
            f"<i>{setup_data.get('ai_summary', 'Algorithmic confluence trigger verified.')}</i>"
        )

        sent_count = 0
        with SessionLocal() as db:
            recipients = (
                db.query(TelegramRecipient)
                .filter(TelegramRecipient.is_active.is_(True), TelegramRecipient.receive_setups.is_(True))
                .all()
            )
            for r in recipients:
                if r.chat_id:
                    ok = await self.send_message(r.chat_id, card)
                    if ok:
                        sent_count += 1
        return sent_count

    async def broadcast_trade_event(self, trade: Any, event_details: Dict[str, Any]) -> int:
        """Broadcast closed or partial trade event card with fees and net PnL."""
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import TelegramRecipient

        net_pnl = float(event_details.get("net_pnl", 0.0))
        pnl_emoji = "🟢" if net_pnl >= 0 else "🔴"
        reason = event_details.get("exit_reason", "MANUAL")

        card = (
            f"{pnl_emoji} <b>TRADE CLOSED | {reason}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Position ID:</b> <code>#{event_details.get('position_id')}</code>\n"
            f"• <b>Pair:</b> <code>{event_details.get('symbol')}</code>\n"
            f"• <b>Exit Price:</b> <code>{event_details.get('exit_price')}</code>\n"
            f"• <b>Gross PnL:</b> <code>${event_details.get('gross_pnl', 0.0):.2f}</code>\n"
            f"• <b>Commission:</b> <code>${event_details.get('commission', 0.0):.2f}</code>\n"
            f"• <b>Swap:</b> <code>${event_details.get('swap', 0.0):.2f}</code>\n"
            f"• <b>Net PnL:</b> <b>${net_pnl:.2f}</b>\n"
            f"• <b>Closed Time:</b> {to_ist_str(now_utc())}\n"
        )

        sent_count = 0
        with SessionLocal() as db:
            recipients = (
                db.query(TelegramRecipient)
                .filter(TelegramRecipient.is_active.is_(True), TelegramRecipient.receive_executions.is_(True))
                .all()
            )
            for r in recipients:
                if r.chat_id:
                    ok = await self.send_message(r.chat_id, card)
                    if ok:
                        sent_count += 1
        return sent_count

    async def handle_update(self, update: Dict[str, Any], session: Optional[Any] = None) -> None:
        """Process inbound Telegram update (command or contact submission)."""
        msg = update.get("message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = str(chat.get("id"))
        text = msg.get("text", "").strip()
        contact = msg.get("contact")

        from backend.app.db.session import SessionLocal
        from backend.app.db.models import TelegramRecipient, AppSettings, TradeLedger

        # 1. Handle Contact Verification Button Response
        if contact:
            phone = str(contact.get("phone_number", "")).strip().replace(" ", "").replace("+", "")
            if session is not None:
                rec = session.query(TelegramRecipient).filter(
                    TelegramRecipient.phone_number.like(f"%{phone[-10:]}%")
                ).first()
                if rec:
                    rec.chat_id = chat_id
                    rec.is_active = True
                    session.commit()
                    await self.send_message(
                        chat_id,
                        f"✅ <b>Phone Verified Successfully!</b>\nWelcome <b>{rec.name}</b>.",
                    )
                    return
            else:
                with SessionLocal() as db:
                    rec = (
                        db.query(TelegramRecipient)
                        .filter(
                            TelegramRecipient.phone_number.like(f"%{phone[-10:]}%")
                        )
                        .first()
                    )
                    if rec:
                        rec.chat_id = chat_id
                        rec.is_active = True
                        db.commit()
                        await self.send_message(
                            chat_id,
                            f"✅ <b>Phone Verified Successfully!</b>\nWelcome <b>{rec.name}</b>.",
                            reply_markup={"remove_keyboard": True},
                        )
                        logger.info(f"Verified Telegram contact: {rec.name} -> Chat ID {chat_id}")
                        return
                    else:
                        await self.send_message(
                            chat_id,
                            "⚠️ Your phone number was received, but no matching invitation was found in the portal settings.",
                        )
                        return

        # 2. Handle /start <invite_token>
        if text.startswith("/start"):
            parts = text.split()
            if len(parts) > 1:
                token = parts[1].strip()
                with SessionLocal() as db:
                    rec = db.query(TelegramRecipient).filter_by(invite_token=token).first()
                    if rec:
                        keyboard = {
                            "keyboard": [[{"text": "📱 Verify & Share Phone Contact", "request_contact": True}]],
                            "resize_keyboard": True,
                            "one_time_keyboard": True,
                        }
                        await self.send_message(
                            chat_id,
                            f"👋 Hello <b>{rec.name}</b>!\nTo activate real-time trade alerts on this device, please tap below to verify your phone number:",
                            reply_markup=keyboard,
                        )
                        return

            await self.send_message(
                chat_id,
                "🤖 <b>XM Global MT5 Trading Portal Bot</b>\nAvailable commands:\n• /pnl - Live Account Stats\n• /open - Open Positions\n• /report - Today's Trade Tear-Sheet\n• /panic_close - Emergency Flatten",
            )
            return

        # 3. Check Admin Authorization for Execution Commands
        is_admin = False
        with SessionLocal() as db:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st and st.telegram_admin_chat_id == chat_id:
                is_admin = True
            else:
                rec = db.query(TelegramRecipient).filter_by(chat_id=chat_id, is_admin=True).first()
                if rec:
                    is_admin = True

        if not is_admin:
            await self.send_message(chat_id, "⛔ <i>Unauthorized. This command is restricted to administrators.</i>")
            return

        # 4. Two-Way Admin Commands
        if text == "/pnl":
            from backend.app.mt5_bridge.connector import mt5_connector
            import MetaTrader5 as mt5

            acc_info = mt5.account_info() if mt5_connector.is_connected else None
            if not acc_info:
                await self.send_message(chat_id, "⚠️ MT5 Terminal is currently <b>DISCONNECTED</b>.")
                return

            with SessionLocal() as db:
                today_trades = (
                    db.query(TradeLedger)
                    .filter(TradeLedger.status == "CLOSED")
                    .all()
                )
                today_pnl = sum(float(t.net_pnl) for t in today_trades)

            pnl_msg = (
                f"📊 <b>LIVE ACCOUNT STATUS</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"• <b>Login:</b> <code>{acc_info.login}</code>\n"
                f"• <b>Server:</b> <code>{acc_info.server}</code>\n"
                f"• <b>Balance:</b> <code>${acc_info.balance:.2f}</code>\n"
                f"• <b>Equity:</b> <code>${acc_info.equity:.2f}</code>\n"
                f"• <b>Margin:</b> <code>${acc_info.margin:.2f}</code>\n"
                f"• <b>Free Margin:</b> <code>${acc_info.margin_free:.2f}</code>\n"
                f"• <b>Closed Net PnL:</b> <b>${today_pnl:.2f}</b>\n"
                f"• <b>Time:</b> {to_ist_str(now_utc())}"
            )
            await self.send_message(chat_id, pnl_msg)

        elif text == "/open":
            from backend.app.mt5_bridge.connector import mt5_connector

            positions = await mt5_connector.get_open_positions()
            if not positions:
                await self.send_message(chat_id, "ℹ️ No open positions currently active.")
                return

            lines = ["📋 <b>OPEN POSITIONS</b>\n━━━━━━━━━━━━━━━━━━"]
            for p in positions:
                lines.append(
                    f"• <b>{p['symbol']}</b> {p['type']} {p['volume']} lots | PnL: ${p['profit']:.2f} (SL: {p['sl']})"
                )
            await self.send_message(chat_id, "\n".join(lines))

        elif text == "/report":
            from backend.app.telegram_reports.report_exporter import report_exporter

            pdf_bytes = report_exporter.generate_pdf_report()
            filename = f"Trade_Report_{datetime.now().strftime('%Y%m%d')}.pdf"
            await self.send_document(chat_id, pdf_bytes, filename, caption="📄 Today's Performance Tear-Sheet")

        elif text == "/panic_close":
            from backend.app.mt5_bridge.connector import mt5_connector

            closed_cnt, errs = await mt5_connector.emergency_flatten_all()
            await self.send_message(
                chat_id,
                f"🚨 <b>PANIC CLOSE EXECUTED</b>\nFlattened {closed_cnt} positions. Errors: {len(errs)}",
            )

    async def polling_loop(self) -> None:
        """Background Telegram update poll loop."""
        logger.info("Telegram polling loop started.")
        while self._running:
            token, _, _ = self._get_bot_config()
            if not token:
                await asyncio.sleep(5)
                continue

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, params={"offset": self._last_update_id + 1, "timeout": 10})
                    if resp.status_code == 200:
                        data = resp.json()
                        for update in data.get("result", []):
                            self._last_update_id = update["update_id"]
                            await self.handle_update(update)
            except Exception as e:
                logger.debug(f"Telegram polling tick error: {e}")

            await asyncio.sleep(2)

    def start(self) -> None:
        """Start Telegram bot background polling."""
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self.polling_loop())

    def stop(self) -> None:
        """Stop Telegram bot polling."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("Telegram polling stopped.")


telegram_service = TelegramService()
