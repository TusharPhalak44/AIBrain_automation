"""Institutional Non-Blocking Telegram Notification Engine & Template Suite.

Strictly HTML parse mode (parse_mode="HTML") - zero MarkdownV2.
Dynamic escaping, instrument-specific decimal precision, IST timestamps,
in-memory TTL anti-spam deduplication, and non-blocking fire-and-forget delivery.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import html
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import httpx

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.config import settings
from backend.app.core.crypto_vault import crypto_vault
from backend.app.core.instruments import format_symbol_price, get_symbol_spec

logger = logging.getLogger(__name__)


def _escape(text: Any) -> str:
    """Safely escape text for Telegram HTML parse mode."""
    if text is None:
        return ""
    return html.escape(str(text))


def _strip_html(text: str) -> str:
    """Strip basic HTML tags for fallback plain text messaging."""
    return re.sub(r"<[^>]*>", "", text)


class TelegramNotifier:
    """Institutional-grade, async, non-blocking Telegram alerting engine."""

    _instance: Optional["TelegramNotifier"] = None

    def __new__(cls) -> "TelegramNotifier":
        if cls._instance is None:
            cls._instance = super(TelegramNotifier, cls).__new__(cls)
            cls._instance._init_state()
        return cls._instance

    def _init_state(self) -> None:
        # In-memory deduplication cache: event_key -> expire_timestamp
        self._sent_events: Dict[str, float] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    def clear_cache(self) -> None:
        """Purge expired and active event deduplication keys."""
        self._sent_events.clear()
        logger.info("Telegram notifier deduplication cache cleared.")

    def _prune_expired_cache(self) -> None:
        """Prune expired event deduplication entries."""
        now = time.time()
        expired = [k for k, exp in self._sent_events.items() if exp < now]
        for k in expired:
            self._sent_events.pop(k, None)

    def is_duplicate(self, event_key: str) -> bool:
        """Check if an event_key has already been delivered within its active TTL window."""
        self._prune_expired_cache()
        exp = self._sent_events.get(event_key)
        if exp is not None and exp > time.time():
            return True
        return False

    def record_event(self, event_key: str, ttl_seconds: float = 300.0) -> None:
        """Record an event_key with expiration timestamp."""
        self._sent_events[event_key] = time.time() + ttl_seconds

    # --------------------------------------------------------------------------
    # Credentials & Configuration Resolver
    # --------------------------------------------------------------------------
    def get_config(self) -> Dict[str, Any]:
        """Load current decrypted Telegram credentials and category preference flags."""
        from backend.app.db.session import SessionLocal
        from backend.app.db.models import AppSettings

        cfg: Dict[str, Any] = {
            "enabled": True,
            "bot_token": settings.TELEGRAM_BOT_TOKEN or "",
            "bot_username": "",
            "chat_id": settings.TELEGRAM_CHAT_ID or "",
            "thread_id": None,
            "notify_pre_trigger": True,
            "notify_executions": True,
            "notify_be_and_partials": True,
            "notify_closures": True,
            "notify_system_alerts": True,
            "silent_pre_trigger": True,
            "has_token": False,
        }

        try:
            with SessionLocal() as db:
                st = db.query(AppSettings).filter_by(id=1).first()
                if st:
                    cfg["enabled"] = bool(st.telegram_enabled)
                    if st.telegram_bot_token_enc:
                        decrypted = crypto_vault.decrypt_secret(st.telegram_bot_token_enc)
                        if decrypted:
                            cfg["bot_token"] = decrypted
                    if st.telegram_bot_username:
                        cfg["bot_username"] = st.telegram_bot_username
                    if st.telegram_admin_chat_id:
                        cfg["chat_id"] = st.telegram_admin_chat_id
                    if st.telegram_thread_id:
                        cfg["thread_id"] = st.telegram_thread_id
                    cfg["notify_pre_trigger"] = bool(st.telegram_notify_pre_trigger)
                    cfg["notify_executions"] = bool(st.telegram_notify_executions)
                    cfg["notify_be_and_partials"] = bool(st.telegram_notify_be_and_partials)
                    cfg["notify_closures"] = bool(st.telegram_notify_closures)
                    cfg["notify_system_alerts"] = bool(st.telegram_notify_system_alerts)
                    cfg["silent_pre_trigger"] = bool(st.telegram_silent_pre_trigger)
        except Exception as e:
            logger.debug(f"Could not load AppSettings for Telegram: {e}")

        cfg["has_token"] = bool(cfg["bot_token"])
        return cfg

    # --------------------------------------------------------------------------
    # Non-Blocking Low-Level HTTP Dispatcher with Retry and Fallback
    # --------------------------------------------------------------------------
    async def _send_raw_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        thread_id: Optional[str] = None,
        silent: bool = False,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send message via Telegram Bot API with 429 rate limit retry and 400 fallback."""
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if thread_id:
            try:
                payload["message_thread_id"] = int(thread_id)
            except ValueError:
                pass
        if silent:
            payload["disable_notification"] = True

        client = httpx.AsyncClient(timeout=8.0)
        try:
            for attempt in range(2):
                try:
                    res = await client.post(url, json=payload)
                    if res.status_code == 200:
                        return True

                    if res.status_code == 429:
                        # Rate limit: respect retry_after
                        retry_after = 1.0
                        try:
                            body = res.json()
                            retry_after = float(body.get("parameters", {}).get("retry_after", 1.0))
                        except Exception:
                            pass
                        logger.warning(f"Telegram 429 Rate Limit. Sleeping {retry_after}s before retry.")
                        await asyncio.sleep(min(retry_after, 5.0))
                        continue

                    if res.status_code == 400 and parse_mode == "HTML":
                        # Bad request likely due to unclosed HTML tag: fallback to plain text
                        logger.warning(
                            f"Telegram 400 Bad Request with HTML parse mode ({res.text}). Retrying plain text."
                        )
                        payload["text"] = _strip_html(text)
                        payload.pop("parse_mode", None)
                        fallback_res = await client.post(url, json=payload)
                        return fallback_res.status_code == 200

                    logger.warning(f"Telegram sendMessage failed [{res.status_code}]: {res.text}")
                    return False
                except (httpx.TimeoutException, httpx.NetworkError) as net_err:
                    logger.warning(f"Telegram network attempt {attempt + 1} error: {net_err}")
                    if attempt == 0:
                        await asyncio.sleep(0.5)
                        continue
                    return False
        finally:
            await client.aclose()
        return False

    async def dispatch_html(
        self,
        html_message: str,
        category: str = "SYSTEM",
        silent: bool = False,
        event_key: Optional[str] = None,
        ttl_seconds: float = 300.0,
    ) -> bool:
        """
        Non-blocking dispatch: checks active config, evaluates category toggle,
        enforces anti-spam deduplication, and sends to admin chat + active recipients.
        """
        # Deduplication check
        if event_key:
            if self.is_duplicate(event_key):
                logger.debug(f"Telegram notification deduplicated and skipped: {event_key}")
                return False
            self.record_event(event_key, ttl_seconds)

        cfg = self.get_config()
        if not cfg["enabled"] or not cfg["bot_token"]:
            logger.debug(f"Telegram alert skipped: bot disabled or no token ({category}).")
            return False

        # Category check
        if category == "PRE_TRIGGER" and not cfg["notify_pre_trigger"]:
            return False
        if category in ("EXECUTION", "LIMIT") and not cfg["notify_executions"]:
            return False
        if category in ("BREAKEVEN", "PARTIAL") and not cfg["notify_be_and_partials"]:
            return False
        if category == "CLOSE" and not cfg["notify_closures"]:
            return False
        if category == "SYSTEM" and not cfg["notify_system_alerts"]:
            return False

        token = cfg["bot_token"]
        thread_id = cfg.get("thread_id")

        # Collect target chat IDs: admin chat_id + any active DB TelegramRecipient
        target_chats: List[str] = []
        if cfg.get("chat_id"):
            target_chats.append(str(cfg["chat_id"]))

        try:
            from backend.app.db.session import SessionLocal
            from backend.app.db.models import TelegramRecipient

            with SessionLocal() as db:
                query = db.query(TelegramRecipient).filter_by(is_active=True)
                if category == "PRE_TRIGGER":
                    query = query.filter_by(receive_setups=True)
                elif category in ("EXECUTION", "LIMIT", "BREAKEVEN", "PARTIAL", "CLOSE"):
                    query = query.filter_by(receive_executions=True)
                elif category == "SYSTEM":
                    query = query.filter_by(receive_reports=True)

                for r in query.all():
                    if r.chat_id and str(r.chat_id) not in target_chats:
                        target_chats.append(str(r.chat_id))
        except Exception as e:
            logger.debug(f"Could not load additional Telegram recipients: {e}")

        if not target_chats:
            logger.debug("No active Telegram chat IDs registered to receive message.")
            return False

        # Fire and forget: send to all target chats concurrently
        tasks = [
            self._send_raw_message(
                token=token,
                chat_id=cid,
                text=html_message,
                thread_id=thread_id,
                silent=silent,
                parse_mode="HTML",
            )
            for cid in target_chats
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return any(isinstance(r, bool) and r for r in results)

    def dispatch_fire_and_forget(
        self,
        html_message: str,
        category: str = "SYSTEM",
        silent: bool = False,
        event_key: Optional[str] = None,
        ttl_seconds: float = 300.0,
    ) -> None:
        """Synchronously enqueue non-blocking async dispatch so caller never waits."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.dispatch_html(
                    html_message=html_message,
                    category=category,
                    silent=silent,
                    event_key=event_key,
                    ttl_seconds=ttl_seconds,
                )
            )
        except RuntimeError:
            # No running event loop in current thread
            asyncio.run(
                self.dispatch_html(
                    html_message=html_message,
                    category=category,
                    silent=silent,
                    event_key=event_key,
                    ttl_seconds=ttl_seconds,
                )
            )

    # ==========================================================================
    # TEMPLATE 1: Pre-Trigger Setup Radar
    # ==========================================================================
    async def notify_pre_trigger_setup(
        self,
        symbol: str,
        trade_style: str,  # "SCALP" | "SWING"
        direction: str,  # "BUY" | "SELL"
        trigger_zone_price: float,
        invalidation_price: float,
        trigger_condition: str,
        readiness_pct: int = 75,
        time_to_trigger_est: str = "15-45m",
        confluence_factors: Optional[List[str]] = None,
        thesis: Optional[str] = None,
        silent: Optional[bool] = None,
    ) -> bool:
        """
        Radar alert for developing high-probability trade setups before trigger fires.
        Deduplication key: RADAR:{symbol}:{trade_style}:{direction}:{rounded_trigger}
        TTL: 90m (Scalp) / 6h (Swing).
        """
        spec = get_symbol_spec(symbol)
        digits = spec.digits if spec else 2
        asset_class = spec.asset_class if spec else "CFD"
        rounded_zone = round(trigger_zone_price, max(0, digits - 1))

        ttl = 5400.0 if trade_style.upper() == "SCALP" else 21600.0
        event_key = f"RADAR:{symbol.upper()}:{trade_style.upper()}:{direction.upper()}:{rounded_zone}"

        cfg = self.get_config()
        is_silent = silent if silent is not None else cfg.get("silent_pre_trigger", True)

        style_icon = "⚡" if trade_style.upper() == "SCALP" else "🌊"
        sentiment_badge = "🟢 <b>ONLY BUY</b>" if direction.upper() == "BUY" else "🔴 <b>ONLY SELL</b>"

        # Readiness progress bar (e.g. [■■■■■■■□□□] 75%)
        filled_blocks = min(10, max(1, round(readiness_pct / 10)))
        bar = "■" * filled_blocks + "□" * (10 - filled_blocks)

        p_trigger = format_symbol_price(symbol, trigger_zone_price)
        p_inval = format_symbol_price(symbol, invalidation_price)

        confluence_lines = ""
        if confluence_factors:
            confluence_lines = "\n• " + "\n• ".join([_escape(c) for c in confluence_factors[:4]])

        rationale_block = ""
        if thesis:
            rationale_block = f"\n<blockquote>💡 {_escape(thesis)}</blockquote>"

        msg = (
            f"📡 <b>PRE-TRIGGER SETUP RADAR</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Instrument:</b> <code>{_escape(symbol)}</code> ({_escape(asset_class)})\n"
            f"• <b>Execution Mode:</b> {style_icon} <b>{_escape(trade_style.upper())}</b>\n"
            f"• <b>HTF Sentiment Lock:</b> {sentiment_badge}\n"
            f"• <b>Trigger Watch Zone:</b> <code>{p_trigger}</code>\n"
            f"• <b>Structural Invalidation:</b> <code>{p_inval}</code>\n"
            f"• <b>Trigger Condition:</b> <i>{_escape(trigger_condition)}</i>\n"
            f"• <b>Readiness:</b> <code>[{bar}] {readiness_pct}%</code> (Est. {time_to_trigger_est})\n"
            f"• <b>Radar Alert Time:</b> {to_ist_str(now_utc())}"
            f"{confluence_lines}"
            f"{rationale_block}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="PRE_TRIGGER",
            silent=is_silent,
            event_key=event_key,
            ttl_seconds=ttl,
        )

    # ==========================================================================
    # TEMPLATE 2: Trade Executed (Live Market Order or Limit Placed)
    # ==========================================================================
    async def notify_trade_executed(
        self,
        ticket: int,
        symbol: str,
        mode: str,  # "SCALP" | "SWING"
        direction: str,  # "BUY" | "SELL"
        lots: float,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        cash_risk: float,
        risk_pct: float,
        spread_points: int = 12,
        is_limit_order: bool = False,
        order_type_str: Optional[str] = None,
        confidence: float = 0.85,
        gate_summary: Optional[Dict[str, bool]] = None,
        ai_summary: Optional[str] = None,
    ) -> bool:
        """
        Alert for newly filled market order or staged pending limit order.
        Includes exact 5-Gate Pass summary, risk $, risk %, and institutional R:R targets.
        """
        event_key = f"EXEC:{ticket}"
        spec = get_symbol_spec(symbol)
        digits = spec.digits if spec else 2

        dir_upper = direction.upper()
        if is_limit_order:
            header = f"⏳ <b>PENDING LIMIT ORDER PLACED</b>"
            action_desc = f"<code>{_escape(order_type_str or f'{dir_upper}_LIMIT')}</code>"
        elif dir_upper == "BUY":
            header = f"🟢 <b>LIVE BUY EXECUTED</b>"
            action_desc = f"<b>BUY MARKET</b>"
        else:
            header = f"🔴 <b>LIVE SELL EXECUTED</b>"
            action_desc = f"<b>SELL MARKET</b>"

        mode_icon = "⚡" if mode.upper() == "SCALP" else "🌊"

        p_entry = format_symbol_price(symbol, entry_price)
        p_sl = format_symbol_price(symbol, sl)
        p_tp1 = format_symbol_price(symbol, tp1)
        p_tp2 = format_symbol_price(symbol, tp2)

        # Compute Breakeven level (+1.0R)
        risk_dist = abs(entry_price - sl) if sl > 0 else 0.0
        if dir_upper == "BUY":
            be_trigger = entry_price + risk_dist
        else:
            be_trigger = entry_price - risk_dist
        p_be = format_symbol_price(symbol, be_trigger)

        # Estimate R:R
        rr_str = "1 : 2.50"
        if risk_dist > 0:
            tp1_r = abs(tp1 - entry_price) / risk_dist if tp1 > 0 else 1.5
            tp2_r = abs(tp2 - entry_price) / risk_dist if tp2 > 0 else 3.0
            blended_r = (tp1_r * 0.60) + (tp2_r * 0.40)
            rr_str = f"1 : {blended_r:.2f}"

        # 5-Gate Pass Summary formatting
        g = gate_summary or {
            "G1_htf_alignment": True,
            "G2_liquidity_sweep": True,
            "G3_fvg_confluence": True,
            "G4_risk_volatility": True,
            "G5_spread_session": True,
        }
        g1 = "✅" if g.get("G1_htf_alignment", True) else "❌"
        g2 = "✅" if g.get("G2_liquidity_sweep", True) else "❌"
        g3 = "✅" if g.get("G3_fvg_confluence", True) else "❌"
        g4 = "✅" if g.get("G4_risk_volatility", True) else "❌"
        g5 = "✅" if g.get("G5_spread_session", True) else "❌"

        rationale_block = ""
        if ai_summary:
            rationale_block = f"\n<blockquote>🧠 <b>AI Thesis:</b> {_escape(ai_summary)}</blockquote>"

        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code> | {mode_icon} <b>{_escape(mode.upper())}</b>\n"
            f"• <b>Pair:</b> <code>{_escape(symbol)}</code> ({action_desc})\n"
            f"• <b>Volume:</b> <code>{lots:.2f} lots</code> | <b>Risk:</b> <code>${cash_risk:.2f} ({risk_pct:.2f}%)</code>\n"
            f"• <b>Live Spread:</b> <code>{spread_points} pts</code> | <b>Confidence:</b> <code>{confidence*100:.0f}%</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Entry Price:</b> <code>{p_entry}</code>\n"
            f"• <b>Hard SL:</b> <code>{p_sl}</code> (Swing S/R)\n"
            f"• <b>Auto-BE Trigger:</b> <code>{p_be}</code> (+1.0R Lock)\n"
            f"• <b>TP1 (60%):</b> <code>{p_tp1}</code> (Nearby Swing)\n"
            f"• <b>TP2 (40%):</b> <code>{p_tp2}</code> (HTF Target)\n"
            f"• <b>Blended Net R:R:</b> <b>{rr_str}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>5-Gate Verification Audit:</b>\n"
            f"{g1} G1: HTF Alignment | {g2} G2: Liquidity Sweep\n"
            f"{g3} G3: FVG / Order Flow | {g4} G4: Volatility Sizing\n"
            f"{g5} G5: Spread & Session Windows\n"
            f"• <b>Executed Time:</b> {to_ist_str(now_utc())}"
            f"{rationale_block}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="EXECUTION" if not is_limit_order else "LIMIT",
            event_key=event_key,
            ttl_seconds=86400.0,
        )

    # ==========================================================================
    # TEMPLATE 3: Limit Filled or Expired
    # ==========================================================================
    async def notify_limit_filled_or_expired(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        action: str,  # "FILLED" | "EXPIRED" | "CANCELLED"
        fill_price: Optional[float] = None,
        lots: Optional[float] = None,
        sl: Optional[float] = None,
        tp1: Optional[float] = None,
        tp2: Optional[float] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Alert when resting limit order fills into a live position or expires."""
        event_key = f"LIMIT_{action.upper()}:{ticket}"
        p_fill = format_symbol_price(symbol, fill_price) if fill_price else "-"
        p_sl = format_symbol_price(symbol, sl) if sl else "-"
        p_tp1 = format_symbol_price(symbol, tp1) if tp1 else "-"
        p_tp2 = format_symbol_price(symbol, tp2) if tp2 else "-"

        if action.upper() == "FILLED":
            header = f"⚡ <b>PENDING LIMIT FILLED</b>"
            status_desc = f"<b>Position LIVE</b>"
            body = (
                f"• <b>Fill Price:</b> <code>{p_fill}</code>\n"
                f"• <b>Volume:</b> <code>{lots:.2f} lots</code>\n"
                f"• <b>Hard SL:</b> <code>{p_sl}</code>\n"
                f"• <b>Targets:</b> TP1 <code>{p_tp1}</code> | TP2 <code>{p_tp2}</code>\n"
            )
        else:
            header = f"⌛ <b>LIMIT ORDER {action.upper()}</b>"
            status_desc = f"<b>Order Closed</b>"
            body = f"• <b>Reason:</b> <i>{_escape(reason or 'Structure invalidated before fill')}</i>\n"

        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code>\n"
            f"• <b>Pair:</b> <code>{_escape(symbol)}</code> (<b>{_escape(direction.upper())}</b>)\n"
            f"• <b>Status:</b> {status_desc}\n"
            f"{body}"
            f"• <b>Event Time:</b> {to_ist_str(now_utc())}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="LIMIT",
            event_key=event_key,
            ttl_seconds=86400.0,
        )

    # ==========================================================================
    # TEMPLATE 4: Breakeven Locked (+1.0R)
    # ==========================================================================
    async def notify_breakeven_locked(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        entry_price: float,
        new_sl: float,
        current_r: float = 1.0,
        next_target: Optional[float] = None,
    ) -> bool:
        """Alert when position reaches +1.0R and SL is shifted to Entry + Buffer."""
        event_key = f"BE:{ticket}"
        p_entry = format_symbol_price(symbol, entry_price)
        p_sl = format_symbol_price(symbol, new_sl)
        p_target = format_symbol_price(symbol, next_target) if next_target else "-"

        msg = (
            f"🔒 <b>BREAKEVEN LOCKED (+1.0R)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code>\n"
            f"• <b>Pair:</b> <code>{_escape(symbol)}</code> (<b>{_escape(direction.upper())}</b>)\n"
            f"• <b>Original Entry:</b> <code>{p_entry}</code>\n"
            f"• <b>Guaranteed SL:</b> <code>{p_sl}</code> (Entry + Spread Buffer)\n"
            f"• <b>Current Milestone:</b> <b>+{current_r:.2f}R Gain Reached</b>\n"
            f"• <b>Risk Status:</b> 🛡️ <b>100% Risk Free (Zero Loss Guaranteed)</b>\n"
            f"• <b>Next Target (TP1/TP2):</b> <code>{p_target}</code>\n"
            f"• <b>Locked Time:</b> {to_ist_str(now_utc())}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="BREAKEVEN",
            event_key=event_key,
            ttl_seconds=86400.0,
        )

    # ==========================================================================
    # TEMPLATE 5: Partial TP1 Hit (60% Banked)
    # ==========================================================================
    async def notify_partial_tp1(
        self,
        ticket: int,
        symbol: str,
        direction: str,
        volume_closed: float,
        remaining_volume: float,
        realized_pnl: float,
        trailed_sl: float,
        tp2: float,
        current_r: float = 1.5,
    ) -> bool:
        """Alert when TP1 is struck, 60% banked, and runner SL trailed in profit."""
        event_key = f"TP1:{ticket}"
        p_sl = format_symbol_price(symbol, trailed_sl)
        p_tp2 = format_symbol_price(symbol, tp2)

        msg = (
            f"💰 <b>TP1 HIT — 60% PROFIT BANKED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code>\n"
            f"• <b>Pair:</b> <code>{_escape(symbol)}</code> (<b>{_escape(direction.upper())}</b>)\n"
            f"• <b>Realized Partial Profit:</b> <b>+${realized_pnl:.2f}</b> (+{current_r:.2f}R)\n"
            f"• <b>Volume Closed:</b> <code>{volume_closed:.2f} lots (60%)</code>\n"
            f"• <b>Remaining Runner:</b> <code>{remaining_volume:.2f} lots (40%)</code>\n"
            f"• <b>Runner Stop:</b> <code>{p_sl}</code> (Trailed in Green)\n"
            f"• <b>Final Target (TP2):</b> <code>{p_tp2}</code>\n"
            f"• <b>Banked Time:</b> {to_ist_str(now_utc())}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="PARTIAL",
            event_key=event_key,
            ttl_seconds=86400.0,
        )

    # ==========================================================================
    # TEMPLATE 6: Trade Closed (Full PnL, Fees, R-Multiple & Scorecard)
    # ==========================================================================
    async def notify_trade_closed(
        self,
        ticket: int,
        symbol: str,
        mode: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        gross_pnl: float,
        commission: float,
        swap: float,
        net_pnl: float,
        r_multiple: float,
        exit_reason: str,
        hold_duration_str: str = "42m",
        prior_partial_pnl: float = 0.0,
        today_scorecard: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Alert on final position closure. Aggregates any prior TP1 profit + final deals,
        exact fees (spread/swap/comm), true exit reason, and running today's scorecard.
        """
        event_key = f"CLOSE:{ticket}"
        p_entry = format_symbol_price(symbol, entry_price)
        p_exit = format_symbol_price(symbol, exit_price)

        total_trade_net = net_pnl + prior_partial_pnl
        is_win = total_trade_net > 0.0
        pnl_emoji = "🏆" if is_win else ("⚪" if abs(total_trade_net) < 0.10 else "🔴")
        pnl_sign = "+" if total_trade_net >= 0 else ""

        # Friendly reason label
        reason_label = exit_reason.replace("_", " ").upper()
        if "TP" in exit_reason.upper() or "TRAIL" in exit_reason.upper():
            header = f"{pnl_emoji} <b>TRADE CLOSED | PROFIT TARGET / TRAIL WIN</b>"
        elif "SL" in exit_reason.upper() or "STOP_OUT" in exit_reason.upper():
            header = f"{pnl_emoji} <b>TRADE CLOSED | STOP LOSS HIT</b>"
        elif "MANUAL" in exit_reason.upper():
            header = f"{pnl_emoji} <b>TRADE CLOSED | MANUAL / MOBILE EXIT</b>"
        else:
            header = f"{pnl_emoji} <b>TRADE CLOSED | {reason_label}</b>"

        # Forensic notice if SL hit
        forensic_note = ""
        if not is_win and "SL" in exit_reason.upper():
            forensic_note = "\n<i>🧠 Forensic Learner: Automated postmortem and rule calibration queued.</i>\n"

        partial_note = ""
        if prior_partial_pnl > 0.0:
            partial_note = f"\n• <b>Prior TP1 Banked:</b> <code>+${prior_partial_pnl:.2f}</code> (Total Net: <b>${total_trade_net:.2f}</b>)"

        # Scorecard block
        sc = today_scorecard or self._get_today_scorecard()
        wins = sc.get("wins", 0)
        losses = sc.get("losses", 0)
        tot = wins + losses
        win_rate = (wins / tot * 100.0) if tot > 0 else 0.0
        today_net = sc.get("net_pnl", 0.0)
        t_sign = "+" if today_net >= 0 else ""
        open_pos = sc.get("open_positions", 0)

        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Ticket:</b> <code>#{ticket}</code> | <b>{_escape(mode.upper())} {_escape(direction.upper())}</b>\n"
            f"• <b>Pair:</b> <code>{_escape(symbol)}</code>\n"
            f"• <b>Entry ➔ Exit:</b> <code>{p_entry}</code> ➔ <code>{p_exit}</code>\n"
            f"• <b>Hold Time:</b> <code>{_escape(hold_duration_str)}</code> | <b>Reason:</b> <code>{_escape(reason_label)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Gross PnL:</b> <code>${gross_pnl:.2f}</code>\n"
            f"• <b>Commission:</b> <code>${commission:.2f}</code> | <b>Swap:</b> <code>${swap:.2f}</code>\n"
            f"• <b>Final Trade Net:</b> <b>{pnl_sign}${total_trade_net:.2f} ({r_multiple:+.2f}R)</b>"
            f"{partial_note}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>📊 Today's Running Scorecard:</b>\n"
            f"• <b>W/L:</b> <code>{wins}W / {losses}L</code> (<b>{win_rate:.1f}%</b> Win Rate)\n"
            f"• <b>Today Realized Net:</b> <b>{t_sign}${today_net:.2f}</b>\n"
            f"• <b>Active Open Positions:</b> <code>{open_pos}/5</code>\n"
            f"• <b>Closed Time:</b> {to_ist_str(now_utc())}"
            f"{forensic_note}"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="CLOSE",
            event_key=event_key,
            ttl_seconds=86400.0,
        )

    async def notify_trade_closed_from_deal(
        self,
        trade: Any,
        deal_summary: Dict[str, Any],
    ) -> bool:
        """Adapter method for deal_reconciler: extracts trade + deal metrics and alerts."""
        if trade is None and not deal_summary:
            return False

        ticket = getattr(trade, "position_id", None) or deal_summary.get("position_id", 0)
        symbol = getattr(trade, "symbol", None) or deal_summary.get("symbol", "")
        mode = getattr(trade, "mode", "SCALP")
        direction = getattr(trade, "direction", "BUY")

        entry_price = float(getattr(trade, "entry_price", 0.0) or 0.0)
        exit_price = float(deal_summary.get("exit_price", 0.0) or 0.0)
        gross_pnl = float(deal_summary.get("gross_pnl", 0.0) or 0.0)
        commission = float(deal_summary.get("commission", 0.0) or 0.0)
        swap = float(deal_summary.get("swap", 0.0) or 0.0)
        net_pnl = float(deal_summary.get("net_pnl", 0.0) or 0.0)
        r_mult = float(getattr(trade, "r_multiple", 0.0) or 0.0)
        exit_reason = deal_summary.get("exit_reason", getattr(trade, "exit_reason", "MANUAL"))

        # Calculate hold duration
        hold_str = "45m"
        opened_at = getattr(trade, "opened_at_utc", None)
        closed_at = getattr(trade, "closed_at_utc", None)
        if opened_at and closed_at:
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=timezone.utc)
            duration_sec = max(0, int((closed_at - opened_at).total_seconds()))
            mins = duration_sec // 60
            hours = mins // 60
            days = hours // 24
            if days > 0:
                hold_str = f"{days}d {hours % 24}h"
            elif hours > 0:
                hold_str = f"{hours}h {mins % 60}m"
            else:
                hold_str = f"{max(1, mins)}m"

        return await self.notify_trade_closed(
            ticket=int(ticket),
            symbol=str(symbol),
            mode=str(mode),
            direction=str(direction),
            entry_price=entry_price,
            exit_price=exit_price,
            gross_pnl=gross_pnl,
            commission=commission,
            swap=swap,
            net_pnl=net_pnl,
            r_multiple=r_mult,
            exit_reason=str(exit_reason),
            hold_duration_str=hold_str,
        )

    # ==========================================================================
    # TEMPLATE 7: System Guardrail / Vault Alert
    # ==========================================================================
    async def notify_system_guardrail(
        self,
        alert_type: str,  # "CIRCUIT_BREAKER" | "RULE_PROMOTED" | "CACHE_HYGIENE"
        title: str,
        details: str,
        action_taken: str,
        severity: str = "WARNING",  # "INFO" | "WARNING" | "CRITICAL"
    ) -> bool:
        """Alert on system guardrail triggers, rule promotions, or vault events."""
        event_key = f"GUARDRAIL:{alert_type}:{title[:20]}"
        icon = "🚨" if severity == "CRITICAL" else ("⚠️" if severity == "WARNING" else "ℹ️")

        msg = (
            f"{icon} <b>GUARDRAIL / VAULT ALERT | {_escape(alert_type.upper())}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Event:</b> <b>{_escape(title)}</b>\n"
            f"• <b>Severity:</b> <code>{_escape(severity.upper())}</code>\n"
            f"• <b>Action Taken:</b> <b>{_escape(action_taken)}</b>\n"
            f"• <b>Timestamp:</b> {to_ist_str(now_utc())}\n\n"
            f"<blockquote>{_escape(details)}</blockquote>"
        )

        return await self.dispatch_html(
            html_message=msg,
            category="SYSTEM",
            event_key=event_key,
            ttl_seconds=1800.0,
        )

    # ==========================================================================
    # TEMPLATE 8: Startup Batch Reconciliation Summary (Anti-Spam)
    # ==========================================================================
    async def notify_reconciliation_batch(
        self,
        reconciled_count: int,
        total_net_pnl: float,
        open_remaining: int,
    ) -> bool:
        """Single consolidated summary when startup reconciles > 1 orphaned trades."""
        if reconciled_count <= 0:
            return False

        pnl_str = f"+${total_net_pnl:.2f}" if total_net_pnl >= 0 else f"-${abs(total_net_pnl):.2f}"
        msg = (
            f"🔄 <b>MT5 RECONCILIATION SUMMARY</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Orphaned Trades Reconciled:</b> <code>{reconciled_count}</code>\n"
            f"• <b>Aggregated Net PnL:</b> <b>{pnl_str}</b>\n"
            f"• <b>Active Positions In Sync:</b> <code>{open_remaining}</code>\n"
            f"• <b>Anti-Spam Guard:</b> <i>Individual historical close alerts suppressed.</i>\n"
            f"• <b>Reconciled At:</b> {to_ist_str(now_utc())}"
        )
        return await self.dispatch_html(
            html_message=msg,
            category="SYSTEM",
            event_key=f"RECONCILE_BATCH_{reconciled_count}",
            ttl_seconds=300.0,
        )

    # --------------------------------------------------------------------------
    # Helper: Fetch Today's Scorecard from DB
    # --------------------------------------------------------------------------
    def _get_today_scorecard(self) -> Dict[str, Any]:
        """Fetch today's realized wins/losses, net PnL, and current open position count."""
        res: Dict[str, Any] = {"wins": 0, "losses": 0, "net_pnl": 0.0, "open_positions": 0}
        try:
            from backend.app.db.session import SessionLocal
            from backend.app.db.models import TradeLedger

            now = now_utc()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            with SessionLocal() as db:
                closed = (
                    db.query(TradeLedger)
                    .filter(
                        TradeLedger.status == "CLOSED",
                        TradeLedger.closed_at_utc >= today_start,
                    )
                    .all()
                )
                wins = sum(1 for t in closed if (t.net_pnl or 0) > 0)
                losses = sum(1 for t in closed if (t.net_pnl or 0) < 0)
                net = sum(float(t.net_pnl or 0) for t in closed)

                open_cnt = (
                    db.query(TradeLedger)
                    .filter(TradeLedger.status.in_(["OPEN", "PARTIAL_TP1"]))
                    .count()
                )
                res["wins"] = wins
                res["losses"] = losses
                res["net_pnl"] = round(net, 2)
                res["open_positions"] = open_cnt
        except Exception as e:
            logger.debug(f"Could not compute today scorecard: {e}")
        return res


# Global singleton instance
telegram_notifier = TelegramNotifier()
