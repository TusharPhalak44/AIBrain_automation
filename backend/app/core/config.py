"""Application Configuration and Environment Settings."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """System settings loaded from environment or .env file."""

    # MySQL Database Settings
    MYSQL_HOST: str = Field(default="127.0.0.1", description="MySQL Host")
    MYSQL_PORT: int = Field(default=3306, description="MySQL Port")
    MYSQL_USER: str = Field(default="root", description="MySQL Username")
    MYSQL_PASSWORD: str = Field(default="", description="MySQL Password")
    MYSQL_DATABASE: str = Field(default="xm_trading_v2", description="MySQL Database")

    # Security
    MASTER_ENCRYPTION_KEY: str = Field(
        default="", description="Fernet 32-byte urlsafe base64 key"
    )

    # Server Settings
    APP_HOST: str = Field(default="127.0.0.1", description="FastAPI Host")
    APP_PORT: int = Field(default=8000, description="FastAPI Port")
    DEBUG: bool = Field(default=False, description="Debug mode")

    # Timezones & Broker Clock Sync
    DISPLAY_TIMEZONE: str = Field(default="Asia/Kolkata", description="UI display timezone")
    BROKER_TZ_OFFSET_SEC: int = Field(
        default=7200, description="Broker server offset vs UTC (e.g., 7200 for GMT+2, 10800 for GMT+3)"
    )

    # MT5 Terminal
    XM_MT5_TERMINAL_PATH: str = Field(
        default=r"C:\Program Files\XM Global MT5\terminal64.exe",
        description="Default MT5 executable path",
    )

    # Telegram Alerting Fallbacks
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Optional Telegram bot token fallback")
    TELEGRAM_CHAT_ID: str = Field(default="", description="Optional Telegram chat ID fallback")

    # Recovery Spool
    MYSQL_SPOOL_PATH: Path = Field(
        default_factory=lambda: DATA_DIR / "mysql_recovery_spool.jsonl"
    )

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def mysql_base_uri(self) -> str:
        """Database server URI without specific database name."""
        auth = self.MYSQL_USER
        if self.MYSQL_PASSWORD:
            auth += f":{self.MYSQL_PASSWORD}"
        return f"mysql+pymysql://{auth}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/"

    @property
    def mysql_database_uri(self) -> str:
        """Full database connection URI."""
        return f"{self.mysql_base_uri}{self.MYSQL_DATABASE}?charset=utf8mb4"


settings = Settings()

