"""Pytest Configuration and Isolated Test Database Fixtures."""

import os
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from backend.app.core.config import settings
from backend.app.db.base import Base
from backend.app.db.session import auto_bootstrap_database, init_db

TEST_DB_NAME = "xm_trading_v2_test"


@pytest.fixture(scope="session")
def test_engine():
    """Ensure isolated test database exists and create all tables."""
    auto_bootstrap_database(TEST_DB_NAME)
    test_uri = f"{settings.mysql_base_uri}{TEST_DB_NAME}?charset=utf8mb4"
    engine = create_engine(test_uri, pool_pre_ping=True)
    Base.metadata.create_all(bind=engine)
    init_db(bind_engine=engine)
    yield engine
    # Optional cleanup on session teardown
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Provide a fresh isolated database session for each test."""
    session_factory = sessionmaker(bind=test_engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def temp_spool_file(tmp_path):
    """Provide an isolated temporary spool file path."""
    return tmp_path / "test_mysql_recovery_spool.jsonl"


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    """Ensure singleton scheduler state does not leak between tests."""
    from backend.app.ai_brain.scheduler import scheduler
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None
    scheduler.circuit_breaker_reason = None
    yield
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None
    scheduler.circuit_breaker_reason = None

