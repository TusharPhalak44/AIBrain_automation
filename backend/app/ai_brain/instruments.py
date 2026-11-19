"""Multi-Asset High-Liquidity Instrument Universe & MT5 MarketWatch Auto-Resolver.

Re-exports from backend.app.core.instruments for unified SSOT.
"""

from backend.app.core.instruments import (
    InstrumentSpec,
    INSTRUMENT_UNIVERSE,
    ALL_SYMBOLS,
    resolve_mt5_symbol,
    resolve_marketwatch_symbol,
    get_symbol_spec,
    is_symbol_trading_open,
    format_symbol_price,
    get_instruments_by_asset_class,
)

__all__ = [
    "InstrumentSpec",
    "INSTRUMENT_UNIVERSE",
    "ALL_SYMBOLS",
    "resolve_mt5_symbol",
    "resolve_marketwatch_symbol",
    "get_symbol_spec",
    "is_symbol_trading_open",
    "format_symbol_price",
    "get_instruments_by_asset_class",
]
