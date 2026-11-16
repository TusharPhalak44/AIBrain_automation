"""Fernet Secret Encryption, Decryption, and Masking Vault."""

import os
import re
from pathlib import Path
from typing import Optional
from cryptography.fernet import Fernet
from backend.app.core.config import BASE_DIR, settings

ENV_FILE = BASE_DIR / ".env"
MASK_CHAR = "•"


class CryptoVault:
    """Manages symmetric Fernet encryption for secrets stored in MySQL."""

    def __init__(self, key: Optional[str] = None):
        self._key = key or os.getenv("MASTER_ENCRYPTION_KEY") or settings.MASTER_ENCRYPTION_KEY
        if not self._key:
            self._key = self._auto_generate_and_save_key()
        self._fernet = Fernet(self._key.encode() if isinstance(self._key, str) else self._key)

    @classmethod
    def _auto_generate_and_save_key(cls) -> str:
        """Generate a new Fernet key and save it to the .env file."""
        new_key = Fernet.generate_key().decode()
        settings.MASTER_ENCRYPTION_KEY = new_key

        if not ENV_FILE.exists():
            with open(ENV_FILE, "w", encoding="utf-8") as f:
                f.write(f"MASTER_ENCRYPTION_KEY={new_key}\n")
        else:
            content = ENV_FILE.read_text(encoding="utf-8")
            if "MASTER_ENCRYPTION_KEY=" in content:
                content = re.sub(
                    r"MASTER_ENCRYPTION_KEY=.*",
                    f"MASTER_ENCRYPTION_KEY={new_key}",
                    content,
                )
            else:
                content += f"\nMASTER_ENCRYPTION_KEY={new_key}\n"
            ENV_FILE.write_text(content, encoding="utf-8")

        return new_key

    def encrypt_secret(self, plain_text: Optional[str]) -> Optional[str]:
        """Encrypt plain text into Fernet base64 token string."""
        if not plain_text:
            return None
        return self._fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")

    def decrypt_secret(self, cipher_token: Optional[str]) -> Optional[str]:
        """Decrypt Fernet base64 token back into plain text string."""
        if not cipher_token:
            return None
        try:
            return self._fernet.decrypt(cipher_token.encode("utf-8")).decode("utf-8")
        except Exception:
            # Return None if corrupted or key mismatch
            return None

    @staticmethod
    def is_masked_value(value: Optional[str]) -> bool:
        """Check if incoming string is a bullet-masked display string."""
        if not value:
            return False
        return MASK_CHAR in value or "•••" in value

    @staticmethod
    def mask_secret(plain_text: Optional[str], is_password: bool = False) -> str:
        """
        Mask a secret string for safe UI representation.
        - Passwords: fully masked as 8 bullets.
        - API keys: 8 bullets followed by the last 3 visible characters.
        """
        if not plain_text:
            return ""
        if is_password or len(plain_text) <= 6:
            return MASK_CHAR * 8
        return f"{MASK_CHAR * 8}{plain_text[-3:]}"


crypto_vault = CryptoVault()

