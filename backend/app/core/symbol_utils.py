"""Symbol Resolution & URL Safety Utilities for XM Global MT5."""

import urllib.parse
from sqlalchemy.orm import Session
from backend.app.db.models import TradingPairBot


def resolve_broker_symbol(symbol: str, db: Session) -> str:
    """
    Safely resolve client symbols to canonical XM MT5 broker symbols.
    Handles URL decoding (e.g. 'GOLD%23' -> 'GOLD#') and unencoded '#' fragment loss
    (e.g. 'GOLD' -> 'GOLD#') by checking registered TradingPairBot rows.
    """
    if not symbol:
        return "GOLD#"

    # Decode potential URL encodings (%23 -> #)
    unquoted = urllib.parse.unquote_plus(symbol).strip().upper()

    # 1. Exact match against database
    exact = db.query(TradingPairBot).filter(TradingPairBot.symbol == unquoted).first()
    if exact:
        return exact.symbol

    # 2. Try with '#' suffix
    with_hash = f"{unquoted}#"
    pair_hash = db.query(TradingPairBot).filter(TradingPairBot.symbol == with_hash).first()
    if pair_hash:
        return pair_hash.symbol

    # 3. Try stripped '#' suffix
    stripped = unquoted.rstrip("#")
    pair_stripped = db.query(TradingPairBot).filter(TradingPairBot.symbol == stripped).first()
    if pair_stripped:
        return pair_stripped.symbol

    # 4. Standard XM Ultra Low 2-Pair default (Gold & Bitcoin only)
    clean_base = unquoted.rstrip("#")
    if clean_base in ("GOLD", "XAUUSD"):
        return "GOLD#"
    if clean_base in ("BTCUSD", "BTC"):
        return "BTCUSD#"

    return f"{clean_base}#" if not unquoted.endswith("#") else unquoted

