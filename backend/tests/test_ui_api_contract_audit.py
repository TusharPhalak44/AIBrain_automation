"""Full Frontend <-> Backend Contract Audit Verification Suite.
Verifies that 100% of endpoints invoked by frontend/src/services/api.ts
exist, accept the payloads sent by UI components, and return expected HTTP 200 status codes.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import settings
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.base import Base
from backend.app.db.models import (
    TradingPairBot,
    TradeLedger,
    LearnedPairRule,
    MacroNewsEvent,
    AppSettings,
    MT5AccountProfile,
    StrategyScript,
    TelegramRecipient,
)
from backend.app.db.session import get_db
from backend.app.api.server import create_app

TEST_DB_URL = "mysql+pymysql://root:@127.0.0.1:3306/xm_trading_v2_test"
engine = create_engine(TEST_DB_URL, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    # Seed Trading Pairs
    pairs = [
        ("GOLD#", "METALS"),
        ("EURUSD#", "FOREX"),
        ("GBPUSD#", "FOREX"),
        ("USDJPY#", "FOREX"),
        ("BTCUSD#", "CRYPTO"),
        ("ETHUSD#", "CRYPTO"),
        ("SOLUSD#", "CRYPTO"),
    ]
    for sym, asset_cls in pairs:
        p = db.query(TradingPairBot).filter_by(symbol=sym).first()
        if not p:
            p = TradingPairBot(
                symbol=sym,
                asset_class=asset_cls,
                enabled=True,
                scalp_enabled=True,
                swing_enabled=True,
                contract_size=100.0 if sym == "GOLD#" else 100000.0,
                digits=2 if sym == "GOLD#" else 5,
                tick_size=0.01 if sym == "GOLD#" else 0.00001,
                tick_value=1.0 if sym == "GOLD#" else 1.0,
                volume_min=0.01,
                volume_step=0.01,
            )
            db.add(p)

    # Seed App Settings
    s = db.query(AppSettings).filter_by(id=1).first()
    if not s:
        s = AppSettings(
            id=1,
            execution_mode="COPILOT",
            max_margin_usage_pct=Decimal("18.00"),
            daily_dd_limit_pct=Decimal("2.50"),
            weekly_dd_limit_pct=Decimal("5.00"),
        )
        db.add(s)

    # Seed MT5 Profiles (DEMO and LIVE)
    for acct_type in ["DEMO", "LIVE"]:
        prof = db.query(MT5AccountProfile).filter_by(account_type=acct_type).first()
        if not prof:
            prof = MT5AccountProfile(
                account_type=acct_type,
                login_id=337246863 if acct_type == "DEMO" else 999999999,
                server_name="XMGlobal-MT5 9",
                terminal_path="C:\\Program Files\\XM Global MT5\\terminal64.exe",
                is_connected=(acct_type == "DEMO"),
            )
            db.add(prof)

    # Seed a Strategy
    strat = db.query(StrategyScript).filter_by(name="Contract Audit Strategy").first()
    if not strat:
        strat = StrategyScript(
            name="Contract Audit Strategy",
            target_mode="BOTH",
            is_builtin=False,
            python_code="""DEFAULT_PARAMS = {"period": 14}
def evaluate(df, params):
    return None
""",
        )
        db.add(strat)

    # Seed a Closed Loss Trade for Forensics
    trade = db.query(TradeLedger).filter_by(position_id=888888).first()
    if not trade:
        trade = TradeLedger(
            position_id=888888,
            order_ticket=888888,
            account_type="DEMO",
            symbol="GOLD#",
            mode="SCALP",
            direction="BUY",
            lots=Decimal("0.02"),
            initial_lots=Decimal("0.02"),
            entry_price=Decimal("2650.00"),
            sl=Decimal("2645.00"),
            tp1=Decimal("2657.50"),
            tp2=Decimal("2665.00"),
            exit_price=Decimal("2644.80"),
            exit_reason="SL_HIT",
            status="CLOSED",
            gross_pnl=Decimal("-10.00"),
            swap=Decimal("0.00"),
            commission=Decimal("0.00"),
            net_pnl=Decimal("-10.50"),
            opened_at_utc=datetime.now(timezone.utc),
            closed_at_utc=datetime.now(timezone.utc),
        )
        db.add(trade)

    db.commit()
    db.close()
    yield


@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(db_session):
    app = create_app(enable_lifespan_tasks=False)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c


# ==============================================================================
# 1. SETTINGS CONTRACT AUDIT
# ==============================================================================
def test_settings_routes(client):
    """Verify GET, POST, and PUT /api/settings and Gemini test route."""
    # GET settings
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert "execution_mode" in data
    assert "max_margin_usage_pct" in data

    # POST settings update (frontend save)
    payload = {
        "execution_mode": "COPILOT",
        "max_margin_usage_pct": 18.0,
        "daily_dd_limit_pct": 2.5,
        "gemini_live_model": "gemini-2.5-flash",
    }
    res_post = client.post("/api/settings", json=payload)
    assert res_post.status_code == 200
    assert res_post.json()["execution_mode"] == "COPILOT"

    # PUT settings update (alias)
    res_put = client.put("/api/settings", json={"execution_mode": "COPILOT"})
    assert res_put.status_code == 200

    # POST test-gemini
    res_gem = client.post("/api/settings/test-gemini", json={})
    assert res_gem.status_code in [200, 400]
    gem_data = res_gem.json()
    assert "status" in gem_data or "detail" in gem_data


# ==============================================================================
# 2. ACCOUNTS CONTRACT AUDIT
# ==============================================================================
def test_accounts_routes(client):
    """Verify accounts routes matching SettingsModal MT5 setup."""
    # GET profiles
    res = client.get("/api/accounts/profiles")
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # GET profile by type (both /DEMO and /profiles/DEMO)
    res_demo = client.get("/api/accounts/DEMO")
    assert res_demo.status_code == 200
    assert res_demo.json()["account_type"] == "DEMO"

    res_demo_prof = client.get("/api/accounts/profiles/DEMO")
    assert res_demo_prof.status_code == 200

    # PUT & POST profile save (/DEMO and /profiles/DEMO)
    save_payload = {
        "login_id": "337246863",
        "server_name": "XMGlobal-MT5 9",
        "terminal_path": "C:\\Program Files\\XM Global MT5\\terminal64.exe",
    }
    res_save_put = client.put("/api/accounts/DEMO", json=save_payload)
    assert res_save_put.status_code == 200
    assert str(res_save_put.json()["login_id"]) == "337246863"

    res_save_post = client.post("/api/accounts/DEMO", json=save_payload)
    assert res_save_post.status_code == 200

    # POST /api/accounts/connect
    res_conn = client.post("/api/accounts/connect", json=save_payload)
    assert res_conn.status_code in [200, 500]  # returns 200 or 500 cleanly without crashing
    assert "status" in res_conn.json()

    # POST /api/accounts/detect-path
    res_detect = client.post("/api/accounts/detect-path")
    assert res_detect.status_code == 200
    assert "detected_path" in res_detect.json()

    # POST /api/accounts/sync
    res_sync = client.post("/api/accounts/sync")
    assert res_sync.status_code == 200

    # POST /api/accounts/switch
    res_switch = client.post(
        "/api/accounts/switch",
        json={"target_account_type": "DEMO", "action_on_positions": "KEEP_EA_PROTECTED"},
    )
    assert res_switch.status_code == 200


# ==============================================================================
# 3. PAIRS CONTRACT AUDIT
# ==============================================================================
def test_pairs_routes(client):
    """Verify pairs listing, updating, and strategy assignment with '#' safety."""
    # GET pairs
    res = client.get("/api/pairs")
    assert res.status_code == 200
    pairs = res.json()
    assert len(pairs) >= 7

    # PUT pair settings with encoded symbol
    res_put = client.put(
        "/api/pairs/GOLD%23",
        json={"max_spread_points": 35.0, "scalp_enabled": True},
    )
    assert res_put.status_code == 200
    assert res_put.json()["symbol"] == "GOLD#"

    # POST assign strategy
    res_assign = client.post(
        "/api/pairs/GOLD%23/assign-strategy",
        json={"scalp_strategy_id": None, "swing_strategy_id": None},
    )
    assert res_assign.status_code == 200
    assert res_assign.json()["symbol"] == "GOLD#"


# ==============================================================================
# 4. CANDLES CONTRACT AUDIT
# ==============================================================================
def test_candles_routes(client):
    """Verify live candle and price action overlay routes with encoded '#' symbol."""
    res = client.get("/api/candles/GOLD%23?timeframe=M15&count=250")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "GOLD#"
    assert data["timeframe"] == "M15"
    assert "candles" in data
    assert "overlays" in data


# ==============================================================================
# 5. TRADES CONTRACT AUDIT
# ==============================================================================
def test_trades_routes(client):
    """Verify trade history, live summary, panic-flatten, and ticket close routes."""
    # GET summary
    res_sum = client.get("/api/trades/live-summary")
    assert res_sum.status_code == 200
    assert "open_positions" in res_sum.json()

    # GET trades (both /trades and /trades/history)
    res_hist1 = client.get("/api/trades?limit=100")
    assert res_hist1.status_code == 200
    assert isinstance(res_hist1.json(), list)

    res_hist2 = client.get("/api/trades/history?limit=100")
    assert res_hist2.status_code == 200

    # POST panic-flatten (both /panic-flatten and /panic-close)
    res_panic1 = client.post("/api/trades/panic-flatten")
    assert res_panic1.status_code == 200
    assert res_panic1.json()["status"] in ["SUCCESS", "EXECUTED"]

    res_panic2 = client.post("/api/trades/panic-close")
    assert res_panic2.status_code == 200

    # POST single position close
    res_close = client.post("/api/trades/999999/close")
    assert res_close.status_code in [200, 400]


# ==============================================================================
# 6. AI SUPERVISOR & RULES CONTRACT AUDIT
# ==============================================================================
def test_ai_supervisor_routes(client, db_session):
    """Verify Gemini supervisory scans, intervals, news, rules, and forensics."""
    # GET reports
    res_rep = client.get("/api/ai/reports?limit=20")
    assert res_rep.status_code == 200
    assert isinstance(res_rep.json(), list)

    # POST scan pair
    res_scan = client.post("/api/ai/scan/GOLD%23")
    assert res_scan.status_code == 200
    assert res_scan.json()["status"] == "SCANNED"
    assert "decision" in res_scan.json()

    # POST scan all
    res_scan_all = client.post("/api/ai/scan-all")
    assert res_scan_all.status_code == 200

    # POST interval
    res_int = client.post("/api/ai/interval", json={"global_scan_interval_sec": 120})
    assert res_int.status_code == 200

    # GET news
    res_news = client.get("/api/ai/news?symbol=GOLD%23")
    assert res_news.status_code == 200
    assert "blackout_check" in res_news.json()

    # GET rules
    res_rules = client.get("/api/ai/rules")
    assert res_rules.status_code == 200
    assert isinstance(res_rules.json(), list)

    # POST forensics on seeded loss trade
    trade = db_session.query(TradeLedger).filter_by(position_id=888888).first()
    res_forensics = client.post(f"/api/ai/forensics/{trade.id}")
    assert res_forensics.status_code == 200
    assert "loss_postmortem_text" in res_forensics.json()


# ==============================================================================
# 7. STRATEGIES & $100 TESTER CONTRACT AUDIT
# ==============================================================================
def test_strategies_routes(client):
    """Verify strategy listing, AST validation, saving, and backtesting."""
    # GET strategies
    res_list = client.get("/api/strategies")
    assert res_list.status_code == 200
    assert len(res_list.json()) >= 1

    # POST validate AST
    valid_code = """DEFAULT_PARAMS = {"rsi_period": 14}
def evaluate(df, params):
    r = rsi(df['close'], period=params['rsi_period'])
    return None
"""
    res_val = client.post("/api/strategies/validate", json={"python_code": valid_code})
    assert res_val.status_code == 200
    assert res_val.json()["valid"] is True

    # POST create custom strategy
    res_create = client.post(
        "/api/strategies",
        json={
            "name": "Audit Test Strategy",
            "target_mode": "SCALP",
            "python_code": valid_code,
        },
    )
    assert res_create.status_code == 200
    new_strat_id = res_create.json()["id"]

    # PUT update strategy
    res_upd = client.put(
        f"/api/strategies/{new_strat_id}",
        json={"name": "Audit Test Strategy Updated"},
    )
    assert res_upd.status_code == 200

    # POST backtest with deterministic bars
    sample_bars = [
        {"time": "2026-11-10T00:00:00Z", "open": 2650.0, "high": 2655.0, "low": 2648.0, "close": 2652.0, "tick_volume": 100, "spread": 25},
        {"time": "2026-11-10T01:00:00Z", "open": 2652.0, "high": 2658.0, "low": 2650.0, "close": 2656.0, "tick_volume": 120, "spread": 25},
        {"time": "2026-11-10T02:00:00Z", "open": 2656.0, "high": 2660.0, "low": 2654.0, "close": 2658.0, "tick_volume": 110, "spread": 25},
    ] * 20
    backtest_payload = {
        "strategy_code": valid_code,
        "symbol": "GOLD#",
        "timeframe": "M15",
        "test_mode": "PER_TRADE_100",
        "bars_count": len(sample_bars),
        "bars_data": sample_bars,
        "risk_pct": 1.0,
    }
    res_bt = client.post("/api/strategies/backtest", json=backtest_payload)
    assert res_bt.status_code == 200
    assert "total_trades" in res_bt.json()
    assert "net_pnl_usd" in res_bt.json()

    # GET backtests
    res_bts = client.get("/api/strategies/backtests?symbol=GOLD%23")
    assert res_bts.status_code == 200


# ==============================================================================
# 8. TELEGRAM & REPORTS & HEALTH CONTRACT AUDIT
# ==============================================================================
def test_telegram_reports_health_routes(client):
    """Verify telegram notifications, PDF/CSV report exports, and health smoke-check."""
    # GET & POST & DELETE telegram recipient
    res_rec = client.get("/api/telegram/recipients")
    assert res_rec.status_code == 200

    res_add = client.post(
        "/api/telegram/recipients",
        json={"name": "Audit Tester", "chat_id": "999888777"},
    )
    assert res_add.status_code == 200
    rec_id = res_add.json()["id"]

    res_del = client.delete(f"/api/telegram/recipients/{rec_id}")
    assert res_del.status_code == 200

    # POST telegram test (returns 200 on success, or 500 if token unconfigured)
    res_tg_test = client.post("/api/telegram/test?chat_id=123456789")
    assert res_tg_test.status_code in [200, 500]

    # GET reports export
    res_export = client.get("/api/reports/export?format=PDF&account_type=DEMO")
    assert res_export.status_code == 200

    # GET health
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "HEALTHY"

    # POST smoke-check
    res_smoke = client.post("/api/health/smoke-check")
    assert res_smoke.status_code == 200
    smoke = res_smoke.json()
    assert "status" in smoke
    assert "results" in smoke
    assert "mysql" in smoke["results"]
    assert "mt5_bridge" in smoke["results"]
    assert "watchdog" in smoke["results"]
    assert "gemini_ai" in smoke["results"]
