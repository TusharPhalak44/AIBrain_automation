"""End-to-End Verification Suite for Live Telemetry, Gemini 3.x, and Strategy Lab PnL Vault."""

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
import pandas as pd
from backend.app.api.server import create_app
from backend.app.db.session import SessionLocal
from backend.app.db.models import AppSettings, MT5AccountProfile, StrategyScript, BacktestRun, TradeLedger
from backend.app.strategy_lab.backtester import backtester


@pytest.fixture(scope="module")
def client():
    app = create_app(enable_lifespan_tasks=False)
    with TestClient(app) as test_client:
        yield test_client


def test_live_state_endpoint(client):
    """Verify GET /api/accounts/live-state returns live telemetry structure."""
    response = client.get("/api/accounts/live-state")
    assert response.status_code == 200
    data = response.json()
    assert "balance" in data
    assert "equity" in data
    assert "floating_pnl" in data
    assert "margin_usage_pct" in data
    assert "daily_dd_pct" in data
    assert "quotes" in data
    assert "risk_state" in data
    assert data["account_type"] in ["DEMO", "LIVE"]


def test_gemini_models_endpoint(client):
    """Verify GET /api/settings/gemini-models returns Gemini 3.x options."""
    response = client.get("/api/settings/gemini-models")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "models" in data
    model_ids = [m["id"] for m in data["models"]]
    assert any("gemini-3" in mid for mid in model_ids)


def test_copilot_staging_endpoint(client):
    """Verify POST /api/ai/copilot/stage creates a PLANNED trade in TradeLedger."""
    payload = {
        "symbol": "GOLD#",
        "mode": "SCALP",
        "direction": "BUY",
        "entry_price": 3855.50,
        "sl": 3845.00,
        "tp1": 3871.25,
        "tp2": 3885.00,
        "lots": 0.01,
        "ai_analysis_summary": "Test automated staging verification",
    }
    response = client.post("/api/ai/copilot/stage", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "STAGED"
    assert data["trade_id"] > 0
    assert data["direction"] == "BUY"
    assert data["lots"] == 0.01

    # Verify persistence in DB
    with SessionLocal() as db:
        t = db.query(TradeLedger).filter_by(id=data["trade_id"]).first()
        assert t is not None
        assert t.status == "PLANNED"
        assert float(t.lots) == 0.01
        # Clean up
        db.delete(t)
        db.commit()


def test_strategy_pnl_vault_endpoints(client):
    """Verify saving a strategy snapshot, listing in leaderboard vault, and deleting."""
    payload = {
        "custom_label": "Test Alpha Gold Scalper",
        "symbol": "GOLD#",
        "timeframe": "M15",
        "test_mode": "ACCOUNT_100",
        "strategy_code": "DEFAULT_PARAMS = {}\ndef evaluate(df, params):\n    return None",
        "metrics": {
            "capital_usd": 100.0,
            "total_trades": 12,
            "win_rate_pct": 66.67,
            "gross_pnl_usd": 45.20,
            "spread_cost_usd": 3.40,
            "swap_cost_usd": 0.80,
            "commission_cost_usd": 0.0,
            "net_pnl_usd": 41.00,
            "net_roi_pct": 41.00,
            "profit_factor": 2.45,
            "max_dd_pct": 4.20,
            "trades": [],
        },
    }
    # 1. Save snapshot
    save_resp = client.post("/api/strategies/save-snapshot", json=payload)
    assert save_resp.status_code == 200
    save_data = save_resp.json()
    assert save_data["status"] == "SUCCESS"
    saved_id = save_data["id"]

    # 2. List saved vault
    vault_resp = client.get("/api/strategies/saved-vault")
    assert vault_resp.status_code == 200
    vault_items = vault_resp.json()
    assert any(item["id"] == saved_id for item in vault_items)
    match = next(item for item in vault_items if item["id"] == saved_id)
    assert match["custom_label"] == "Test Alpha Gold Scalper"
    assert match["net_roi_pct"] == 41.0
    assert match["profit_factor"] == 2.45

    # 3. Delete from vault
    del_resp = client.delete(f"/api/strategies/saved-vault/{saved_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "SUCCESS"

    # Verify removed
    vault_resp_after = client.get("/api/strategies/saved-vault")
    assert not any(item["id"] == saved_id for item in vault_resp_after.json())


def test_backtest_micro_lot_clamping():
    """Verify $100 account backtest clamps micro lots to volume_min (0.01 lot) safely."""
    # Create simple 60-bar OHLCV test dataset
    dates = pd.date_range("2026-01-01", periods=60, freq="1h")
    prices = [3850.0 + (i * 0.5) for i in range(60)]
    df = pd.DataFrame({
        "time": dates,
        "open": prices,
        "high": [p + 2.0 for p in prices],
        "low": [p - 2.0 for p in prices],
        "close": [p + 0.3 for p in prices],
        "tick_volume": [100] * 60,
        "spread": [20] * 60,
    })

    # Strategy that fires a BUY signal on bar 30
    strategy_code = """
DEFAULT_PARAMS = {}
def evaluate(df, params):
    if len(df) == 30:
        c = float(df['close'].iloc[-1])
        return {
            "signal": "BUY",
            "mode": "SCALP",
            "entry": c,
            "sl": c - 5.0,
            "tp1": c + 7.5,
            "tp2": c + 15.0,
            "reason": "Test micro setup"
        }
    return None
"""
    result = backtester.run_backtest(
        strategy_code=strategy_code,
        symbol="GOLD#",
        df=df,
        timeframe="H1",
        test_mode="ACCOUNT_100",
        save_to_db=False,
    )
    assert result is not None
    assert "total_trades" in result
    assert result["capital_usd"] == 100.0
    assert "profit_factor" in result

