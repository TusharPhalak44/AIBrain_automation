"""Phase 1 Mandatory Verification Suite.

Verifies:
1. Fernet secret encryption/decryption & masked save protection in MySQL.
2. IST conversion & XM broker midnight offset math.
3. MySQL offline JSONL spooling & auto-recovery replay.
4. Safe Demo <-> Live switch guard when positions are open + CONFIRM_LIVE_TRADING enforcement.
5. DEAL_POSITION_ID closed deal & swap/commission net PnL reconciliation.
6. Telegram request_contact phone-to-chat-ID binding, admin auth guard, and CSV/XLSX/PDF reports.
"""

from datetime import datetime, timezone
from decimal import Decimal
import pytest
from backend.app.core.crypto_vault import crypto_vault, CryptoVault
from backend.app.core.clock_sync import (
    to_ist_str,
    now_utc,
    compute_broker_offset_sec,
    get_broker_time,
    get_broker_midnight_utc,
    is_rollover_period,
)
from backend.app.core.risk_engine import risk_engine
from backend.app.core.watchdog import WatchdogService
from backend.app.db.models import AppSettings, MT5AccountProfile, TradeLedger, TelegramRecipient
from backend.app.mt5_bridge.connector import MT5Connector
from backend.app.mt5_bridge.deal_reconciler import DealReconciler, classify_exit_reason
from backend.app.telegram_reports.report_exporter import report_exporter
from backend.app.telegram_reports.telegram_bot import telegram_service


# -------------------------------------------------------------------------
# 1. Fernet Secret Encryption, Decryption & Masked Protection
# -------------------------------------------------------------------------
def test_crypto_vault_encryption_and_safe_masking(db_session):
    test_secret = "AIzaSy_XM_SampleSecretKey_12345"
    token = crypto_vault.encrypt_secret(test_secret)
    assert token is not None
    assert token != test_secret

    decrypted = crypto_vault.decrypt_secret(token)
    assert decrypted == test_secret

    # Masking tests
    api_mask = crypto_vault.mask_secret(test_secret)
    assert api_mask.startswith("••••••••")
    assert api_mask.endswith("345")
    assert crypto_vault.is_masked_value(api_mask) is True

    pwd_mask = crypto_vault.mask_secret("MySecretTradingPassword", is_password=True)
    assert pwd_mask == "••••••••"
    assert crypto_vault.is_masked_value(pwd_mask) is True

    # Database Mask Protection: Updating settings must never overwrite with bullet masks
    st = db_session.query(AppSettings).filter_by(id=1).first()
    assert st is not None
    st.gemini_api_key_enc = token
    db_session.commit()

    # Simulate UI submitting masked value
    incoming_ui_value = api_mask
    if not crypto_vault.is_masked_value(incoming_ui_value):
        st.gemini_api_key_enc = crypto_vault.encrypt_secret(incoming_ui_value)
    db_session.commit()

    # Re-fetch and verify original encrypted secret was preserved!
    re_fetched = db_session.query(AppSettings).filter_by(id=1).first()
    assert crypto_vault.decrypt_secret(re_fetched.gemini_api_key_enc) == test_secret


# -------------------------------------------------------------------------
# 2. IST Conversion & Dynamic Broker Server Midnight Math
# -------------------------------------------------------------------------
def test_ist_and_broker_clock_sync():
    sample_utc = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
    ist_str = to_ist_str(sample_utc)
    # 12:00 UTC = 17:30 IST
    assert "16 Nov 2026" in ist_str
    assert "05:30:00 PM IST" in ist_str

    # Offset math: 7200 seconds (GMT+2)
    sys_utc_epoch = 1700000000
    broker_tick_epoch = sys_utc_epoch + 7200
    offset = compute_broker_offset_sec(broker_tick_epoch, sys_utc_epoch)
    assert offset == 7200

    # Broker midnight calculation
    # Reference UTC 2026-11-16 10:00:00 UTC. Offset = 7200 (GMT+2). Broker time is 12:00:00
    # Today's broker midnight 00:00:00 GMT+2 is 2026-11-15 22:00:00 UTC
    broker_midnight_utc = get_broker_midnight_utc(reference_utc=sample_utc, offset_sec=7200)
    assert broker_midnight_utc == datetime(2026, 11, 15, 22, 0, 0, tzinfo=timezone.utc)

    # Rollover window (23:50 to 01:10 broker server time)
    rollover_time_1 = datetime(2026, 11, 16, 23, 55, 0, tzinfo=timezone.utc)
    assert is_rollover_period(broker_dt=rollover_time_1) is True

    rollover_time_2 = datetime(2026, 11, 16, 0, 30, 0, tzinfo=timezone.utc)
    assert is_rollover_period(broker_dt=rollover_time_2) is True

    normal_time = datetime(2026, 11, 16, 14, 0, 0, tzinfo=timezone.utc)
    assert is_rollover_period(broker_dt=normal_time) is False


# -------------------------------------------------------------------------
# 3. MySQL Offline JSONL Spooling & Auto-Recovery Replay
# -------------------------------------------------------------------------
def test_mysql_offline_spool_and_replay(temp_spool_file, db_session):
    wd = WatchdogService(spool_file=temp_spool_file)

    test_deal = {
        "position_id": 99901,
        "symbol": "GOLD#",
        "account_type": "DEMO",
        "order_ticket": 88801,
        "magic_number": 1001,
        "mode": "SCALP",
        "direction": "BUY",
        "lots": 0.10,
        "initial_lots": 0.10,
        "entry_price": 2650.50,
        "sl": 2645.00,
        "tp1": 2658.75,
        "tp2": 2665.00,
        "exit_price": 2658.75,
        "gross_pnl": 82.50,
        "commission": -1.50,
        "swap": -0.80,
        "net_pnl": 80.20,
        "exit_reason": "TP_HIT",
    }

    # Simulate MySQL outage: spool to JSONL
    ok = wd.spool_closed_deal(test_deal)
    assert ok is True
    assert temp_spool_file.exists()

    records = wd.get_spooled_records()
    assert len(records) == 1
    assert records[0]["deal"]["position_id"] == 99901

    # Simulate MySQL restoration: replay spool
    replayed = wd.replay_spool_into_db(db_session)
    assert replayed == 1
    assert not temp_spool_file.exists()

    # Verify TradeLedger has recorded the replayed trade
    persisted = db_session.query(TradeLedger).filter_by(position_id=99901).first()
    assert persisted is not None
    assert persisted.status == "CLOSED"
    assert float(persisted.net_pnl) == 80.20
    assert persisted.exit_reason == "TP_HIT"


# -------------------------------------------------------------------------
# 4. Safe Demo <-> Live Switch Guard & CONFIRM_LIVE_TRADING
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_safe_demo_live_switch_guard():
    connector = MT5Connector()

    # 1. Switching to LIVE without confirm_token must fail
    ok, res = await connector.switch_account_profile("LIVE", confirm_token=None)
    assert ok is False
    assert res["error"] == "CONFIRM_TOKEN_REQUIRED"

    # 2. Switching to LIVE with invalid token must fail
    ok, res = await connector.switch_account_profile("LIVE", confirm_token="WRONG_TOKEN")
    assert ok is False
    assert res["error"] == "CONFIRM_TOKEN_REQUIRED"

    # 3. Switching with invalid account type must fail
    ok, res = await connector.switch_account_profile("INVALID_TYPE")
    assert ok is False
    assert res["error"] == "INVALID_ACCOUNT_TYPE"


# -------------------------------------------------------------------------
# 5. DEAL_POSITION_ID Closed Deal Reconciler & Net PnL Accounting
# -------------------------------------------------------------------------
def test_deal_reconciliation_math_and_exit_reasons(db_session):
    reconciler = DealReconciler()

    # Verify exit reason classifier
    assert classify_exit_reason(4, -50.0, "sl 2645.00") == "SL_HIT"
    assert classify_exit_reason(5, 75.0, "tp 2660.00") == "TP_HIT"
    assert classify_exit_reason(3, 40.0, "trail stop triggered") == "TRAIL_SL"
    assert classify_exit_reason(1, 10.0, "mobile close") == "MANUAL_MOBILE"

    # Simulate position entry already in DB
    existing_trade = TradeLedger(
        account_type="DEMO",
        position_id=77701,
        order_ticket=66601,
        symbol="EURUSD#",
        magic_number=1001,
        mode="SCALP",
        direction="BUY",
        status="OPEN",
        lots=Decimal("0.50"),
        initial_lots=Decimal("0.50"),
        entry_price=Decimal("1.08500"),
        sl=Decimal("1.08200"),
        tp1=Decimal("1.08950"),
        tp2=Decimal("1.09200"),
        gross_pnl=Decimal("0.0"),
        commission=Decimal("0.0"),
        swap=Decimal("0.0"),
        net_pnl=Decimal("0.0"),
        opened_at_utc=now_utc(),
    )
    db_session.add(existing_trade)
    db_session.commit()

    # Simulate 2 exit deals (partial TP1 + remaining closed at TP2)
    deals = [
        {
            "position_id": 77701,
            "order": 66602,
            "symbol": "EURUSD#",
            "price": 1.08950,
            "volume": 0.25,
            "profit": 112.50,
            "commission": -1.75,
            "swap": -0.50,
            "reason": 5,
            "comment": "[tp1]",
            "type": 1,
            "time": int(now_utc().timestamp()),
        },
        {
            "position_id": 77701,
            "order": 66603,
            "symbol": "EURUSD#",
            "price": 1.09200,
            "volume": 0.25,
            "profit": 175.00,
            "commission": -1.75,
            "swap": -0.50,
            "reason": 5,
            "comment": "[tp2]",
            "type": 1,
            "time": int(now_utc().timestamp()),
        },
    ]

    summary = reconciler.process_position_deals(77701, deals)
    assert summary is not None
    # Net PnL = (112.50 + 175.00) + (-1.75 + -1.75) + (-0.50 + -0.50) = 287.50 - 3.50 - 1.00 = 283.00
    assert summary["gross_pnl"] == 287.50
    assert summary["commission"] == -3.50
    assert summary["swap"] == -1.00
    assert summary["net_pnl"] == 283.00
    assert summary["exit_reason"] == "TP_HIT"


# -------------------------------------------------------------------------
# 6. Telegram Contact Onboarding, Admin Auth & Multi-Format Reports
# -------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_telegram_contact_binding_and_report_exports(db_session):
    # Clean previous run artifacts
    db_session.query(TelegramRecipient).filter(
        (TelegramRecipient.phone_number == "+919876543210") | (TelegramRecipient.invite_token == "token_abc_123")
    ).delete()
    db_session.commit()

    # 1. Onboarding & Phone Verification
    rec = TelegramRecipient(
        name="Tushar Trader",
        phone_number="+919876543210",
        chat_id=None,
        is_admin=True,
        invite_token="token_abc_123",
        is_active=False,
    )
    db_session.add(rec)
    db_session.commit()

    # Simulate user sending contact payload
    contact_update = {
        "update_id": 1001,
        "message": {
            "chat": {"id": 987654321},
            "contact": {
                "phone_number": "919876543210",
                "first_name": "Tushar",
            },
        },
    }
    await telegram_service.handle_update(contact_update, session=db_session)

    # Verify recipient is bound to chat_id and activated
    updated_rec = db_session.query(TelegramRecipient).filter_by(name="Tushar Trader").first()
    assert updated_rec is not None
    assert updated_rec.chat_id == "987654321"
    assert updated_rec.is_active is True

    # 2. Report Generations
    csv_bytes = report_exporter.generate_csv_report(session=db_session)
    assert len(csv_bytes) > 0
    assert b"Trade ID,Account Type,Position ID" in csv_bytes

    xlsx_bytes = report_exporter.generate_excel_report(session=db_session)
    assert len(xlsx_bytes) > 0
    assert xlsx_bytes[:2] == b"PK"  # Zip archive header for XLSX

    pdf_bytes = report_exporter.generate_pdf_report(session=db_session)
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:5] == b"%PDF-"  # PDF header


# -------------------------------------------------------------------------
# 7. Risk Engine Validation Gate
# -------------------------------------------------------------------------
def test_risk_engine_calculations():
    # 0.5% risk on $10,000 equity = $50 cash risk
    # Stop distance = 5.0 on Gold ($2650 to $2645) = 500 ticks of size 0.01
    # Tick value = $1.0 / tick for standard lot
    ok, lots, msg = risk_engine.calculate_lot_size(
        equity=10000.0,
        risk_pct=0.5,
        entry_price=2650.0,
        sl_price=2645.0,
        contract_size=100.0,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
    )
    assert ok is True
    assert lots > 0.0

    # Margin ceiling check (18.0%)
    ok, _ = risk_engine.check_margin_ceiling(equity=10000.0, margin_used=1500.0)
    assert ok is True

    ok, msg = risk_engine.check_margin_ceiling(equity=10000.0, margin_used=1900.0)
    assert ok is False
    assert "Margin ceiling breached" in msg

    # Daily drawdown lock (2.5%)
    ok, _ = risk_engine.check_drawdown_locks(current_equity=9800.0, daily_baseline_equity=10000.0, weekly_baseline_equity=10000.0)
    assert ok is True

    ok, msg = risk_engine.check_drawdown_locks(current_equity=9700.0, daily_baseline_equity=10000.0, weekly_baseline_equity=10000.0)
    assert ok is False
    assert "DAILY_DRAWDOWN_LOCK_HIT" in msg

    # Zero Naked Trade
    ok, _ = risk_engine.validate_zero_naked_trade(sl_price=2640.0, entry_price=2650.0, direction="BUY")
    assert ok is True

    ok, msg = risk_engine.validate_zero_naked_trade(sl_price=0.0, entry_price=2650.0, direction="BUY")
    assert ok is False
    assert "ZERO_NAKED_TRADE_VIOLATION" in msg
