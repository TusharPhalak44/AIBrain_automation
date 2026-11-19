"""Symbol Resolution & URL Safety Utilities for XM Global MT5."""

import urllib.parse
from sqlalchemy.orm import Session
from backend.app.db.models import TradingPairBot
from backend.app.ai_brain.instruments import INSTRUMENT_UNIVERSE

XM_ACTIVE_SYMBOLS = list(INSTRUMENT_UNIVERSE.keys())


def resolve_broker_symbol(symbol: str, db: Session) -> str:
    """
    Safely resolve client symbols to canonical XM MT5 broker symbols.
    Handles URL decoding (e.g. 'GOLD%23' -> 'GOLD#') and unencoded '#' fragment loss
    (e.g. 'GOLD' -> 'GOLD#') by checking registered TradingPairBot rows and INSTRUMENT_UNIVERSE aliases.
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

    # 4. Check INSTRUMENT_UNIVERSE aliases
    for canon_sym, spec in INSTRUMENT_UNIVERSE.items():
        if unquoted in spec.aliases or stripped in spec.aliases or with_hash in spec.aliases:
            return canon_sym

    return f"{stripped}#" if not unquoted.endswith("#") else unquoted

