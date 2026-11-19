"""Multi-Asset High-Liquidity Instrument Universe & MT5 MarketWatch Auto-Resolver.

Categorized into:
- FOREX: EURUSD#, USDJPY#, GBPUSD#, USDCAD#, AUDUSD#, GBPJPY#
- COMMODITIES: GOLD#, SILVER#, OILCash#, BRENTCash#
- CRYPTO (24/7): BTCUSD#, ETHUSD#, SOLUSD#, XRPUSD#
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class InstrumentSpec:
    symbol: str
    asset_class: str  # FOREX, COMMODITIES, CRYPTO
    display_name: str
    contract_size: float
    digits: int
    tick_size: float
    tick_value: float
    max_spread_points: int
    is_24_7: bool
    active_sessions: List[str] = field(default_factory=lambda: ["ALL"])
    aliases: List[str] = field(default_factory=list)
    scalp_strategy_id: Optional[int] = 1
    swing_strategy_id: Optional[int] = 3


INSTRUMENT_UNIVERSE: Dict[str, InstrumentSpec] = {
    # === FOREX ===
    "EURUSD#": InstrumentSpec(
        symbol="EURUSD#",
        asset_class="FOREX",
        display_name="EUR/USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        max_spread_points=18,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["EURUSD", "EURUSD.raw", "EURUSDm", "EURUSD#"],
        scalp_strategy_id=2,  # Session Breakout
        swing_strategy_id=3,  # Trend Pullback
    ),
    "USDJPY#": InstrumentSpec(
        symbol="USDJPY#",
        asset_class="FOREX",
        display_name="USD/JPY",
        contract_size=100000.0,
        digits=3,
        tick_size=0.001,
        tick_value=1.0,
        max_spread_points=20,
        is_24_7=False,
        active_sessions=["ASIAN_RANGE", "NY_OVERLAP"],
        aliases=["USDJPY", "USDJPY.raw", "USDJPYm", "USDJPY#"],
        scalp_strategy_id=2,
        swing_strategy_id=3,
    ),
    "GBPUSD#": InstrumentSpec(
        symbol="GBPUSD#",
        asset_class="FOREX",
        display_name="GBP/USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        max_spread_points=25,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["GBPUSD", "GBPUSD.raw", "GBPUSDm", "GBPUSD#"],
        scalp_strategy_id=1,  # Liquidity Sweep + FVG
        swing_strategy_id=3,
    ),
    "USDCAD#": InstrumentSpec(
        symbol="USDCAD#",
        asset_class="FOREX",
        display_name="USD/CAD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        max_spread_points=22,
        is_24_7=False,
        active_sessions=["NY_OVERLAP"],
        aliases=["USDCAD", "USDCAD.raw", "USDCADm", "USDCAD#"],
        scalp_strategy_id=2,
        swing_strategy_id=3,
    ),
    "AUDUSD#": InstrumentSpec(
        symbol="AUDUSD#",
        asset_class="FOREX",
        display_name="AUD/USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        max_spread_points=20,
        is_24_7=False,
        active_sessions=["ASIAN_RANGE", "LONDON_OPEN"],
        aliases=["AUDUSD", "AUDUSD.raw", "AUDUSDm", "AUDUSD#"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),
    "GBPJPY#": InstrumentSpec(
        symbol="GBPJPY#",
        asset_class="FOREX",
        display_name="GBP/JPY",
        contract_size=100000.0,
        digits=3,
        tick_size=0.001,
        tick_value=1.0,
        max_spread_points=35,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["GBPJPY", "GBPJPY.raw", "GBPJPYm", "GBPJPY#"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),

    # === COMMODITIES ===
    "GOLD#": InstrumentSpec(
        symbol="GOLD#",
        asset_class="COMMODITIES",
        display_name="Gold (Spot XAU/USD)",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        max_spread_points=80,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["GOLD", "GOLD#", "XAUUSD", "XAUUSD#", "GOLDm"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),
    "SILVER#": InstrumentSpec(
        symbol="SILVER#",
        asset_class="COMMODITIES",
        display_name="Silver (Spot XAG/USD)",
        contract_size=5000.0,
        digits=3,
        tick_size=0.001,
        tick_value=1.0,
        max_spread_points=45,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["SILVER", "SILVER#", "XAGUSD", "XAGUSD#", "SILVERm"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),
    "OILCash#": InstrumentSpec(
        symbol="OILCash#",
        asset_class="COMMODITIES",
        display_name="WTI Crude Oil Cash",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        max_spread_points=60,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["OILCash", "OILCash#", "USOIL#", "USOIL", "OIL#", "OIL", "USOILCash"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),
    "BRENTCash#": InstrumentSpec(
        symbol="BRENTCash#",
        asset_class="COMMODITIES",
        display_name="Brent Crude Oil Cash",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        max_spread_points=60,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["BRENTCash", "BRENTCash#", "UKOIL#", "UKOIL", "BRENT#", "BRENT", "UKOILCash"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),

    # === CRYPTO (24/7) ===
    "BTCUSD#": InstrumentSpec(
        symbol="BTCUSD#",
        asset_class="CRYPTO",
        display_name="Bitcoin (USD CFD)",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        max_spread_points=6000,
        is_24_7=True,
        active_sessions=["24/7"],
        aliases=["BTCUSD", "BTCUSD#", "BTC#", "BTCUSDm"],
        scalp_strategy_id=4,  # 24/7 Crypto Squeeze
        swing_strategy_id=3,
    ),
    "ETHUSD#": InstrumentSpec(
        symbol="ETHUSD#",
        asset_class="CRYPTO",
        display_name="Ethereum (USD CFD)",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        max_spread_points=800,
        is_24_7=True,
        active_sessions=["24/7"],
        aliases=["ETHUSD", "ETHUSD#", "ETH#", "ETHUSDm"],
        scalp_strategy_id=4,
        swing_strategy_id=3,
    ),
    "SOLUSD#": InstrumentSpec(
        symbol="SOLUSD#",
        asset_class="CRYPTO",
        display_name="Solana (USD CFD)",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        max_spread_points=120,
        is_24_7=True,
        active_sessions=["24/7"],
        aliases=["SOLUSD", "SOLUSD#", "SOL#", "SOLUSDm"],
        scalp_strategy_id=4,
        swing_strategy_id=3,
    ),
    "XRPUSD#": InstrumentSpec(
        symbol="XRPUSD#",
        asset_class="CRYPTO",
        display_name="Ripple (USD CFD)",
        contract_size=1000.0,
        digits=4,
        tick_size=0.0001,
        tick_value=0.1,
        max_spread_points=150,
        is_24_7=True,
        active_sessions=["24/7"],
        aliases=["XRPUSD", "XRPUSD#", "XRP#", "XRPUSDm"],
        scalp_strategy_id=4,
        swing_strategy_id=3,
    ),
}

# Cache of MT5 resolved symbol names e.g. "OILCash#" -> "OILCash" or "USOIL#"
_RESOLVED_MARKETWATCH_SYMBOLS: Dict[str, str] = {}


def resolve_marketwatch_symbol(target_symbol: str) -> str:
    """
    Query MetaTrader 5 terminal to verify symbol exists in MarketWatch.
    Falls back gracefully across suffix variants (e.g. OILCash# -> OILCash -> USOIL# -> USOIL).
    Ensures symbol is selected in MarketWatch via mt5.symbol_select(symbol, True).
    """
    global _RESOLVED_MARKETWATCH_SYMBOLS

    # Return cached resolution if already resolved
    if target_symbol in _RESOLVED_MARKETWATCH_SYMBOLS:
        return _RESOLVED_MARKETWATCH_SYMBOLS[target_symbol]

    spec = INSTRUMENT_UNIVERSE.get(target_symbol)
    aliases_to_try = []

    # Priority 1: Target symbol as requested
    aliases_to_try.append(target_symbol)

    # Priority 2: Configured aliases
    if spec:
        for a in spec.aliases:
            if a not in aliases_to_try:
                aliases_to_try.append(a)

    # Priority 3: Common suffix variations
    clean = target_symbol.rstrip("#")
    variations = [
        clean,
        f"{clean}#",
        f"{clean}m",
        f"{clean}m#",
        f"{clean}.raw",
    ]
    for v in variations:
        if v not in aliases_to_try:
            aliases_to_try.append(v)

    try:
        import MetaTrader5 as mt5
        # Test if MT5 is initialized
        term_info = mt5.terminal_info()
        if term_info is not None:
            for candidate in aliases_to_try:
                sym_info = mt5.symbol_info(candidate)
                if sym_info is not None:
                    # Select in MarketWatch if not visible
                    if not sym_info.visible:
                        mt5.symbol_select(candidate, True)
                    _RESOLVED_MARKETWATCH_SYMBOLS[target_symbol] = candidate
                    logger.info(f"Resolved MarketWatch symbol '{target_symbol}' -> '{candidate}' (visible: {sym_info.visible})")
                    return candidate
    except Exception as e:
        logger.debug(f"MT5 symbol resolution note for {target_symbol}: {e}")

    # Fallback to target_symbol if MT5 not connected or resolution failed
    _RESOLVED_MARKETWATCH_SYMBOLS[target_symbol] = target_symbol
    return target_symbol


def is_symbol_trading_open(symbol: str, asset_class: Optional[str] = None, ref_time_utc: Optional[datetime] = None) -> bool:
    """
    Check if market is currently open for symbol.
    - CRYPTO is open 24/7/365.
    - FOREX and COMMODITIES are closed during weekends:
      From Friday 22:00 UTC through Sunday 22:00 UTC.
    """
    spec = INSTRUMENT_UNIVERSE.get(symbol)
    effective_class = asset_class or (spec.asset_class if spec else "FOREX")

    if effective_class == "CRYPTO":
        return True

    now = ref_time_utc or datetime.now(timezone.utc)
    weekday = now.weekday()  # Monday is 0, Sunday is 6
    hour = now.hour

    # Friday after 22:00 UTC is closed
    if weekday == 4 and hour >= 22:
        return False
    # Saturday is fully closed
    if weekday == 5:
        return False
    # Sunday before 22:00 UTC is closed
    if weekday == 6 and hour < 22:
        return False

    return True


def get_instruments_by_asset_class(asset_class: str) -> List[InstrumentSpec]:
    """Return all instruments belonging to the given asset class (FOREX, COMMODITIES, CRYPTO)."""
    norm = asset_class.upper()
    return [spec for spec in INSTRUMENT_UNIVERSE.values() if spec.asset_class == norm]
