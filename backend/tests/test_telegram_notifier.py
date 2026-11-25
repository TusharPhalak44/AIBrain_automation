"""Comprehensive Test Suite for Institutional Non-Blocking Telegram Notification Engine."""

import asyncio
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from backend.app.ai_brain.telegram_notifier import (
    TelegramNotifier,
    telegram_notifier,
    _escape,
    _strip_html,
)
from backend.app.core.instruments import format_symbol_price
from backend.app.api.server import create_app
from backend.app.db.session import SessionLocal
from backend.app.db.models import AppSettings


@pytest.fixture(scope="module")
def app_client():
    app = create_app(enable_lifespan_tasks=False)
    with TestClient(app) as client:
        yield client


class TestTelegramNotifierCore:
    """Core tests for formatting, escaping, deduplication, and templates."""

    def test_html_escaping_and_stripping(self):
        """Verify dynamic strings with special chars (#, <, >, &, quotes) are safely escaped."""
        raw = "GOLD# <BUY> & 'SELL' \"WIN\""
        escaped = _escape(raw)
        assert "&lt;BUY&gt;" in escaped
        assert "&amp;" in escaped
        assert "GOLD#" in escaped  # Hash symbol is preserved unescaped in HTML

        # Strip HTML fallback
        html_str = "<b>BOLD</b> <code>CODE</code> <a href='#'>LINK</a>"
        stripped = _strip_html(html_str)
        assert stripped == "BOLD CODE LINK"

    def test_instrument_specific_price_formatting(self):
        """Verify exact digits precision across Forex, Metals, and Crypto CFDs."""
        # Forex 5 digits
        assert format_symbol_price("EURUSD#", 1.054321) == "1.05432"
        assert format_symbol_price("GBPUSD#", 1.261234) == "1.26123"

        # Forex JPY & Metals 3 digits
        assert format_symbol_price("USDJPY#", 154.3456) == "154.346"
        assert format_symbol_price("GBPJPY#", 195.1234) == "195.123"
        assert format_symbol_price("SILVER#", 31.4567) == "31.457"

        # Crypto XRP 4 digits
        assert format_symbol_price("XRPUSD#", 1.45678) == "1.4568"

        # Metals, Oil & Crypto 2 digits
        assert format_symbol_price("GOLD#", 2645.2) == "2645.20"
        assert format_symbol_price("OILCash#", 71.4) == "71.40"
        assert format_symbol_price("BTCUSD#", 94500.5) == "94500.50"
        assert format_symbol_price("ETHUSD#", 3420.0) == "3420.00"

    def test_in_memory_event_deduplication(self):
        """Verify TTL cache blocks duplicate events within window and clears properly."""
        notifier = TelegramNotifier()
        notifier.clear_cache()

        event_key = "RADAR:GOLD#:SCALP:BUY:2645.0"
        assert not notifier.is_duplicate(event_key)

        # Record with 10s TTL
        notifier.record_event(event_key, ttl_seconds=10.0)
        assert notifier.is_duplicate(event_key)

        # Expired TTL check
        notifier._sent_events[event_key] = 0.0  # Force past expiration
        assert not notifier.is_duplicate(event_key)

        # Clear cache check
        notifier.record_event("EXEC:12345", ttl_seconds=60.0)
        assert notifier.is_duplicate("EXEC:12345")
        notifier.clear_cache()
        assert not notifier.is_duplicate("EXEC:12345")

    @pytest.mark.asyncio
    async def test_notify_pre_trigger_setup_template(self):
        """Verify TEMPLATE 1: Pre-Trigger Setup Radar HTML structure."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            html_message = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            category = kwargs.get("category") or (args[1] if len(args) > 1 else "PRE_TRIGGER")
            silent = kwargs.get("silent") or (args[2] if len(args) > 2 else False)
            event_key = kwargs.get("event_key") or (args[3] if len(args) > 3 else None)
            captured_messages.append({
                "msg": html_message,
                "cat": category,
                "silent": silent,
                "key": event_key,
            })
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_pre_trigger_setup(
                symbol="GOLD#",
                trade_style="SCALP",
                direction="BUY",
                trigger_zone_price=2645.50,
                invalidation_price=2638.00,
                trigger_condition="Asian Low Sweep & M5 Bullish FVG Inversion Close",
                readiness_pct=80,
                time_to_trigger_est="15-30m",
                confluence_factors=["HTF Bullish", "Session Low Cleared"],
                thesis="Expecting expansion toward London High.",
                silent=True,
            )
            assert ok is True
            assert len(captured_messages) == 1
            item = captured_messages[0]
            assert item["cat"] == "PRE_TRIGGER"
            assert item["silent"] is True
            assert "PRE-TRIGGER SETUP RADAR" in item["msg"]
            assert "<code>GOLD#</code>" in item["msg"]
            assert "<code>2645.50</code>" in item["msg"]
            assert "<code>2638.00</code>" in item["msg"]
            assert "[■■■■■■■■□□] 80%" in item["msg"]
            assert "<blockquote>💡 Expecting expansion toward London High.</blockquote>" in item["msg"]

    @pytest.mark.asyncio
    async def test_notify_trade_executed_template(self):
        """Verify TEMPLATE 2: Trade Executed with 5-Gate pass summary and levels."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "EXECUTION")
            key = kwargs.get("event_key") or (args[3] if len(args) > 3 else None)
            captured_messages.append({"msg": msg, "cat": cat, "key": key})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_trade_executed(
                ticket=98124012,
                symbol="EURUSD#",
                mode="SCALP",
                direction="BUY",
                lots=0.25,
                entry_price=1.05420,
                sl=1.05180,
                tp1=1.05780,
                tp2=1.06200,
                cash_risk=60.00,
                risk_pct=0.50,
                spread_points=12,
                confidence=0.88,
                ai_summary="Displacement candle confirmed off demand zone.",
            )
            assert ok is True
            assert len(captured_messages) == 1
            item = captured_messages[0]
            assert item["cat"] == "EXECUTION"
            assert item["key"] == "EXEC:98124012"
            assert "LIVE BUY EXECUTED" in item["msg"]
            assert "<code>#98124012</code>" in item["msg"]
            assert "<code>1.05420</code>" in item["msg"]
            assert "<code>1.05180</code>" in item["msg"]
            assert "<code>1.05780</code>" in item["msg"]
            assert "<code>1.06200</code>" in item["msg"]
            assert "5-Gate Verification Audit:" in item["msg"]
            assert "✅ G1: HTF Alignment" in item["msg"]
            assert "✅ G2: Liquidity Sweep" in item["msg"]

    @pytest.mark.asyncio
    async def test_notify_breakeven_locked_template(self):
        """Verify TEMPLATE 4: Breakeven Locked (+1.0R)."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "BREAKEVEN")
            captured_messages.append({"msg": msg, "cat": cat})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_breakeven_locked(
                ticket=98124012,
                symbol="BTCUSD#",
                direction="BUY",
                entry_price=94500.00,
                new_sl=94520.00,
                current_r=1.05,
                next_target=96200.00,
            )
            assert ok is True
            assert len(captured_messages) == 1
            msg = captured_messages[0]["msg"]
            assert "BREAKEVEN LOCKED (+1.0R)" in msg
            assert "<code>94500.00</code>" in msg
            assert "<code>94520.00</code>" in msg
            assert "100% Risk Free" in msg

    @pytest.mark.asyncio
    async def test_notify_partial_tp1_template(self):
        """Verify TEMPLATE 5: Partial TP1 Hit (60% banked)."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "PARTIAL")
            captured_messages.append({"msg": msg, "cat": cat})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_partial_tp1(
                ticket=98124012,
                symbol="GOLD#",
                direction="BUY",
                volume_closed=0.09,
                remaining_volume=0.06,
                realized_pnl=76.95,
                trailed_sl=2648.50,
                tp2=2668.50,
                current_r=1.50,
            )
            assert ok is True
            msg = captured_messages[0]["msg"]
            assert "TP1 HIT — 60% PROFIT BANKED" in msg
            assert "+$76.95" in msg
            assert "0.09 lots (60%)" in msg
            assert "0.06 lots (40%)" in msg

    @pytest.mark.asyncio
    async def test_notify_trade_closed_template(self):
        """Verify TEMPLATE 6: Trade Closed with full fees and scorecard."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "CLOSE")
            captured_messages.append({"msg": msg, "cat": cat})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_trade_closed(
                ticket=98124012,
                symbol="GOLD#",
                mode="SCALP",
                direction="BUY",
                entry_price=2648.20,
                exit_price=2668.50,
                gross_pnl=304.50,
                commission=0.00,
                swap=-2.15,
                net_pnl=302.35,
                r_multiple=3.54,
                exit_reason="TP2_HIT",
                hold_duration_str="1h 14m",
                prior_partial_pnl=76.95,
                today_scorecard={"wins": 4, "losses": 1, "net_pnl": 412.80, "open_positions": 2},
            )
            assert ok is True
            msg = captured_messages[0]["msg"]
            assert "TRADE CLOSED | PROFIT TARGET / TRAIL WIN" in msg
            assert "+$379.30" in msg  # 302.35 + 76.95
            assert "Prior TP1 Banked:" in msg
            assert "4W / 1L" in msg
            assert "80.0%" in msg and "Win Rate" in msg

    @pytest.mark.asyncio
    async def test_notify_system_guardrail_template(self):
        """Verify TEMPLATE 7: System Guardrail / Vault Alert."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "SYSTEM")
            captured_messages.append({"msg": msg, "cat": cat})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_system_guardrail(
                alert_type="CIRCUIT_BREAKER",
                title="Daily Drawdown -3.00% Limit Tripped",
                details="Losses reached -3.15%. All scanning paused until 00:05 UTC.",
                action_taken="Autonomous Order Entry HALTED",
                severity="CRITICAL",
            )
            assert ok is True
            msg = captured_messages[0]["msg"]
            assert "GUARDRAIL / VAULT ALERT | CIRCUIT_BREAKER" in msg
            assert "🚨" in msg
            assert "Autonomous Order Entry HALTED" in msg

    @pytest.mark.asyncio
    async def test_notify_reconciliation_batch_template(self):
        """Verify TEMPLATE 8: Startup Batch Reconciliation Summary."""
        captured_messages = []

        async def mock_dispatch(*args, **kwargs):
            msg = kwargs.get("html_message") or (args[0] if len(args) > 0 else "")
            cat = kwargs.get("category") or (args[1] if len(args) > 1 else "SYSTEM")
            captured_messages.append({"msg": msg, "cat": cat})
            return True

        with patch.object(telegram_notifier, "dispatch_html", side_effect=mock_dispatch):
            ok = await telegram_notifier.notify_reconciliation_batch(
                reconciled_count=85,
                total_net_pnl=-1250.40,
                open_remaining=2,
            )
            assert ok is True
            msg = captured_messages[0]["msg"]
            assert "MT5 RECONCILIATION SUMMARY" in msg
            assert "<code>85</code>" in msg
            assert "-$1250.40" in msg
            assert "Anti-Spam Guard:" in msg


class TestTelegramEndpoints:
    """REST API route tests for Telegram configuration and test template previews."""

    def test_get_telegram_config(self, app_client):
        res = app_client.get("/api/ai-brain/telegram/config")
        assert res.status_code == 200
        data = res.json()
        assert "enabled" in data
        assert "bot_token_masked" in data
        assert "admin_chat_id" in data
        assert "notify_pre_trigger" in data
        assert "notify_executions" in data
        assert "notify_be_and_partials" in data
        assert "notify_closures" in data
        assert "notify_system_alerts" in data
        assert "silent_pre_trigger" in data

    def test_patch_telegram_config(self, app_client):
        payload = {
            "notify_pre_trigger": True,
            "silent_pre_trigger": False,
            "notify_executions": True,
        }
        res = app_client.patch("/api/ai-brain/telegram/config", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["notify_pre_trigger"] is True
        assert data["silent_pre_trigger"] is False
        assert data["notify_executions"] is True

    def test_post_telegram_test_preview(self, app_client):
        """Verify test template dispatcher with mock Telegram response."""
        with patch.object(telegram_notifier, "_send_raw_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True

            for template_type in ["SETUP", "EXECUTION", "LIMIT", "BE", "TP1", "CLOSE", "GUARDRAIL"]:
                res = app_client.post(
                    "/api/ai-brain/telegram/test",
                    json={"template_type": template_type, "symbol": "GOLD#"},
                )
                assert res.status_code == 200, f"Failed for {template_type}: {res.text}"
                data = res.json()
                assert data["status"] == "SUCCESS"
                assert data["template_type"] == template_type
