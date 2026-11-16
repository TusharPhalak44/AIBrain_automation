"""FastAPI REST Endpoints Verification Suite."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker
from backend.app.api.server import create_app
from backend.app.db.session import get_db


@pytest.fixture
def client(test_engine):
    """Provide a TestClient with thread-safe session dependency override to isolated test db."""
    test_app = create_app(enable_lifespan_tasks=False)
    TestingSessionLocal = sessionmaker(bind=test_engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app.dependency_overrides[get_db] = _override_get_db
    with TestClient(test_app) as test_client:
        yield test_client
    test_app.dependency_overrides.clear()


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "components" in data
    assert "mysql" in data["components"]


def test_settings_endpoints(client):
    # GET settings
    res = client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == 1
    assert "gemini_api_key_masked" in data

    # PUT settings
    update_payload = {
        "execution_mode": "COPILOT",
        "scalp_risk_pct": 0.75,
        "swing_risk_pct": 1.25,
    }
    put_res = client.put("/api/settings", json=update_payload)
    assert put_res.status_code == 200

    # Verify updated
    get_res = client.get("/api/settings")
    updated_data = get_res.json()
    assert updated_data["execution_mode"] == "COPILOT"
    assert updated_data["scalp_risk_pct"] == 0.75
    assert updated_data["swing_risk_pct"] == 1.25


def test_accounts_endpoints(client):
    # List profiles
    res = client.get("/api/accounts/profiles")
    assert res.status_code == 200
    profiles = res.json()
    assert len(profiles) >= 2
    types = [p["account_type"] for p in profiles]
    assert "DEMO" in types
    assert "LIVE" in types

    # Safe switch to LIVE without confirm token should return 400
    switch_res = client.post("/api/accounts/switch", json={"target_account_type": "LIVE"})
    assert switch_res.status_code == 400
    assert switch_res.json()["detail"]["error"] == "CONFIRM_TOKEN_REQUIRED"


def test_pairs_endpoints(client):
    # List pairs
    res = client.get("/api/pairs")
    assert res.status_code == 200
    pairs = res.json()
    symbols = [p["symbol"] for p in pairs]
    assert "GOLD#" in symbols
    assert "BTCUSD#" in symbols

    # Update pair
    upd_res = client.put("/api/pairs/GOLD#", json={"max_spread_points": 40})
    assert upd_res.status_code == 200


def test_trades_endpoints(client):
    res = client.get("/api/trades/live-summary")
    assert res.status_code == 200
    data = res.json()
    assert "margin_usage_pct" in data
    assert "balance" in data
    assert "floating_pnl" in data


def test_reports_export_endpoints(client):
    # CSV export
    res_csv = client.get("/api/reports/export?format=CSV")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]

    # PDF export
    res_pdf = client.get("/api/reports/export?format=PDF")
    assert res_pdf.status_code == 200
    assert "application/pdf" in res_pdf.headers["content-type"]
    assert res_pdf.content.startswith(b"%PDF-")


def test_telegram_recipient_endpoints(client):
    # Create recipient
    create_payload = {
        "name": "Jane Doe",
        "phone_number": "+1234567890",
        "is_admin": False,
    }
    post_res = client.post("/api/telegram/recipients", json=create_payload)
    assert post_res.status_code == 200
    rec_data = post_res.json()
    rec_id = rec_data["id"]
    assert "invite_token" in rec_data

    # List recipients
    list_res = client.get("/api/telegram/recipients")
    assert list_res.status_code == 200
    recs = list_res.json()
    assert any(r["id"] == rec_id for r in recs)

    # Delete recipient
    del_res = client.delete(f"/api/telegram/recipients/{rec_id}")
    assert del_res.status_code == 200
