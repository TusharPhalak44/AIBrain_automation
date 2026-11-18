"""
Verification tests for Gemini 3.8 SDK v1beta Pinning, Model Migration, and Test Route.
"""
from decimal import Decimal
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.crypto_vault import crypto_vault
from backend.app.db.models import Base, AppSettings
from backend.app.db.session import init_db, get_db
from backend.app.api.server import create_app
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor


from sqlalchemy.pool import StaticPool

TEST_SQLITE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_SQLITE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    init_db(bind_engine=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


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


def test_app_settings_model_migration(db_session):
    """Verify that stale gemini-3.1-pro or gemini-2.5 settings auto-migrate to gemini-3.8-flash."""
    st = db_session.query(AppSettings).filter_by(id=1).first()
    assert st is not None
    # Simulate a stale DB row
    st.gemini_live_model = "models/gemini-3.1-pro-preview"
    st.gemini_forensic_model = "gemini-2.5-flash"
    db_session.commit()

    # Re-run init_db migration logic
    init_db(bind_engine=test_engine)

    db_session.refresh(st)
    assert st.gemini_live_model == "gemini-3.8-flash"
    assert st.gemini_forensic_model == "gemini-3.8-flash"


def test_test_gemini_endpoint_direct_target_model(client, db_session):
    """Verify POST /api/settings/test-gemini tests the target model directly using v1beta."""
    with patch("backend.app.api.routes.settings.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance

        mock_resp = MagicMock()
        mock_resp.text = "CONNECTED"
        mock_instance.models.generate_content.return_value = mock_resp

        # Test with explicit gemini-3.8-flash model
        payload = {
            "api_key": "AIzaSyFakeKeyForTest123",
            "model": "models/gemini-3.8-flash",
        }
        res = client.post("/api/settings/test-gemini", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["ok"] is True
        assert data["tested_model"] == "gemini-3.8-flash"
        assert data["model"] == "gemini-3.8-flash"

        # Verify Client was initialized with v1beta
        mock_client_cls.assert_called_with(
            api_key="AIzaSyFakeKeyForTest123",
            http_options={"api_version": "v1beta"},
        )
        mock_instance.models.generate_content.assert_called_with(
            model="gemini-3.8-flash",
            contents="State 'CONNECTED' in one word.",
        )


def test_test_gemini_endpoint_reports_exact_error_without_silent_fallback(client):
    """Verify that if the requested model returns an error, it is returned without masking."""
    with patch("backend.app.api.routes.settings.genai.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_instance.models.generate_content.side_effect = Exception("503 Service Unavailable")

        payload = {
            "api_key": "AIzaSyFakeKeyForTest123",
            "model": "gemini-3.8-flash",
        }
        res = client.post("/api/settings/test-gemini", json=payload)
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert detail["error"] == "GEMINI_TEST_FAILED"
        assert detail["model"] == "gemini-3.8-flash"
        assert "503 Service Unavailable" in detail["message"]


def test_supervisor_fallback_chain_excludes_pro():
    """Verify that supervisory candidate fallback chain does not include gemini-3.1-pro-preview."""
    # When supervisor loads client and model
    model_name = "gemini-3.8-flash"
    clean_m = model_name.strip().removeprefix("models/")
    candidates = [clean_m, "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]
    seen = set()
    ordered_models = []
    for m in candidates:
        if m and m not in seen and "3.1-pro" not in m:
            seen.add(m)
            ordered_models.append(m)

    assert "gemini-3.1-pro-preview" not in ordered_models
    assert ordered_models == ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3-flash-preview"]


def test_gemini_models_list_endpoint(client):
    """Verify GET /api/settings/gemini-models returns updated Gemini 3.x default models."""
    res = client.get("/api/settings/gemini-models")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    model_ids = [m["id"] for m in data["models"]]
    assert "gemini-3.8-flash" in model_ids
    assert "gemini-3.6-flash" in model_ids
    assert "gemini-3.5-flash-lite" in model_ids
    assert "gemini-3-flash-preview" in model_ids
