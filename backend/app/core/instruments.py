"""Centralized Single Source of Truth (SSOT) 14-Pair Instrument Registry & Auto-Resolver.

Supports the exact 14 high-liquidity XM Ultra Low / Cash CFD instruments:
- FOREX (6): EURUSD# (5 digits), USDJPY# (3 digits), GBPUSD# (5 digits), USDCAD# (5 digits), AUDUSD# (5 digits), GBPJPY# (3 digits)
- COMMODITIES (4): GOLD# (2 digits), SILVER# (3 digits), OILCash# (2 digits), BRENTCash# (2 digits)
- CRYPTO 24/7 (4): BTCUSD# (2 digits), ETHUSD# (2 digits), SOLUSD# (2 digits), XRPUSD# (4 digits)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class InstrumentSpec:
    symbol: str
    asset_class: str  # FOREX, COMMODITIES, CRYPTO
    display_name: str
    base_currency: str
    quote_currency: str
    contract_size: float
    digits: int
    tick_size: float
    tick_value: float
    volume_min: float
    volume_step: float
    volume_max: float
    swap_long: float
    swap_short: float
    three_day_swap_day: int  # 2 = Wednesday
    default_spread_points: int
    max_spread_points: int
    default_slippage_points: int
    is_24_7: bool
    active_sessions: List[str] = field(default_factory=lambda: ["ALL"])
    aliases: List[str] = field(default_factory=list)
    scalp_strategy_id: Optional[int] = 1
    swing_strategy_id: Optional[int] = 3


# 14 High-Liquidity XM Ultra Low & Cash CFD Instruments
INSTRUMENT_UNIVERSE: Dict[str, InstrumentSpec] = {
    # =========================================================================
    # FOREX (6)
    # =========================================================================
    "EURUSD#": InstrumentSpec(
        symbol="EURUSD#",
        asset_class="FOREX",
        display_name="EUR/USD",
        base_currency="EUR",
        quote_currency="USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-6.80,
        swap_short=2.10,
        three_day_swap_day=2,
        default_spread_points=12,
        max_spread_points=18,
        default_slippage_points=2,
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
        base_currency="USD",
        quote_currency="JPY",
        contract_size=100000.0,
        digits=3,
        tick_size=0.001,
        tick_value=0.67,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=10.50,
        swap_short=-18.00,
        three_day_swap_day=2,
        default_spread_points=14,
        max_spread_points=20,
        default_slippage_points=2,
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
        base_currency="GBP",
        quote_currency="USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-4.50,
        swap_short=-1.20,
        three_day_swap_day=2,
        default_spread_points=15,
        max_spread_points=25,
        default_slippage_points=2,
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
        base_currency="USD",
        quote_currency="CAD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=0.74,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=3.20,
        swap_short=-7.90,
        three_day_swap_day=2,
        default_spread_points=16,
        max_spread_points=22,
        default_slippage_points=2,
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
        base_currency="AUD",
        quote_currency="USD",
        contract_size=100000.0,
        digits=5,
        tick_size=0.00001,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-3.10,
        swap_short=0.80,
        three_day_swap_day=2,
        default_spread_points=14,
        max_spread_points=20,
        default_slippage_points=2,
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
        base_currency="GBP",
        quote_currency="JPY",
        contract_size=100000.0,
        digits=3,
        tick_size=0.001,
        tick_value=0.67,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=14.80,
        swap_short=-22.40,
        three_day_swap_day=2,
        default_spread_points=22,
        max_spread_points=35,
        default_slippage_points=2,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["GBPJPY", "GBPJPY.raw", "GBPJPYm", "GBPJPY#"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),

    # =========================================================================
    # COMMODITIES (4)
    # =========================================================================
    "GOLD#": InstrumentSpec(
        symbol="GOLD#",
        asset_class="COMMODITIES",
        display_name="Gold (Spot XAU/USD)",
        base_currency="XAU",
        quote_currency="USD",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-27.50,
        swap_short=14.20,
        three_day_swap_day=2,
        default_spread_points=25,
        max_spread_points=80,
        default_slippage_points=2,
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
        base_currency="XAG",
        quote_currency="USD",
        contract_size=5000.0,
        digits=3,
        tick_size=0.001,
        tick_value=5.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=50.0,
        swap_long=-12.40,
        swap_short=4.50,
        three_day_swap_day=2,
        default_spread_points=28,
        max_spread_points=45,
        default_slippage_points=2,
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
        base_currency="OIL",
        quote_currency="USD",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-8.50,
        swap_short=2.10,
        three_day_swap_day=2,
        default_spread_points=35,
        max_spread_points=60,
        default_slippage_points=3,
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
        base_currency="BRENT",
        quote_currency="USD",
        contract_size=100.0,
        digits=2,
        tick_size=0.01,
        tick_value=1.0,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=100.0,
        swap_long=-8.90,
        swap_short=1.80,
        three_day_swap_day=2,
        default_spread_points=35,
        max_spread_points=60,
        default_slippage_points=3,
        is_24_7=False,
        active_sessions=["LONDON_OPEN", "NY_OVERLAP"],
        aliases=["BRENTCash", "BRENTCash#", "UKOIL#", "UKOIL", "BRENT#", "BRENT", "UKOILCash"],
        scalp_strategy_id=1,
        swing_strategy_id=3,
    ),

    # =========================================================================
    # CRYPTO 24/7 (4)
    # =========================================================================
    "BTCUSD#": InstrumentSpec(
        symbol="BTCUSD#",
        asset_class="CRYPTO",
        display_name="Bitcoin (USD CFD)",
        base_currency="BTC",
        quote_currency="USD",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=10.0,
        swap_long=-15.00,
        swap_short=-15.00,
        three_day_swap_day=2,
        default_spread_points=2500,
        max_spread_points=6000,
        default_slippage_points=15,
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
        base_currency="ETH",
        quote_currency="USD",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=50.0,
        swap_long=-12.00,
        swap_short=-12.00,
        three_day_swap_day=2,
        default_spread_points=350,
        max_spread_points=800,
        default_slippage_points=15,
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
        base_currency="SOL",
        quote_currency="USD",
        contract_size=1.0,
        digits=2,
        tick_size=0.01,
        tick_value=0.01,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=200.0,
        swap_long=-10.00,
        swap_short=-10.00,
        three_day_swap_day=2,
        default_spread_points=60,
        max_spread_points=120,
        default_slippage_points=15,
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
        base_currency="XRP",
        quote_currency="USD",
        contract_size=1000.0,
        digits=4,
        tick_size=0.0001,
        tick_value=0.10,
        volume_min=0.01,
        volume_step=0.01,
        volume_max=500.0,
        swap_long=-8.00,
        swap_short=-8.00,
        three_day_swap_day=2,
        default_spread_points=80,
        max_spread_points=150,
        default_slippage_points=10,
        is_24_7=True,
        active_sessions=["24/7"],
        aliases=["XRPUSD", "XRPUSD#", "XRP#", "XRPUSDm"],
        scalp_strategy_id=4,
        swing_strategy_id=3,
    ),
}

ALL_SYMBOLS: List[str] = list(INSTRUMENT_UNIVERSE.keys())

# Cache of MT5 resolved symbol names e.g. "OILCash#" -> "OILCash" or "USOIL#"
_RESOLVED_MT5_SYMBOLS: Dict[str, str] = {}


def resolve_mt5_symbol(target_symbol: str) -> str:
    """
    Query MetaTrader 5 terminal to verify symbol exists in MarketWatch.
    Falls back gracefully across suffix variants (e.g. OILCash# -> OILCash -> USOIL# -> USOIL).
    Ensures symbol is selected in MarketWatch via mt5.symbol_select(symbol, True).
    """
    global _RESOLVED_MT5_SYMBOLS

    if not target_symbol:
        return "GOLD#"

    clean = target_symbol.strip()
    if clean in _RESOLVED_MT5_SYMBOLS:
        return _RESOLVED_MT5_SYMBOLS[clean]

    spec = INSTRUMENT_UNIVERSE.get(clean) or INSTRUMENT_UNIVERSE.get(f"{clean}#")
    aliases_to_try: List[str] = [clean]

    if spec:
        for a in spec.aliases:
            if a not in aliases_to_try:
                aliases_to_try.append(a)

    stripped = clean.rstrip("#")
    variations = [
        stripped,
        f"{stripped}#",
        f"{stripped}m",
        f"{stripped}m#",
        f"{stripped}.raw",
    ]
    for v in variations:
        if v not in aliases_to_try:
            aliases_to_try.append(v)

    try:
        import MetaTrader5 as mt5
        term_info = mt5.terminal_info()
        if term_info is not None:
            for candidate in aliases_to_try:
                sym_info = mt5.symbol_info(candidate)
                if sym_info is not None:
                    if not sym_info.visible:
                        mt5.symbol_select(candidate, True)
                    _RESOLVED_MT5_SYMBOLS[clean] = candidate
                    logger.info(f"Resolved MT5 symbol '{clean}' -> '{candidate}' (digits: {sym_info.digits})")
                    return candidate
    except Exception as e:
        logger.debug(f"MT5 symbol resolution note for {clean}: {e}")

    _RESOLVED_MT5_SYMBOLS[clean] = clean
    return clean


# Backwards compatibility alias
resolve_marketwatch_symbol = resolve_mt5_symbol


def get_symbol_spec(symbol: str) -> InstrumentSpec:
    """Safely fetch InstrumentSpec with alias and fallback handling."""
    if not symbol:
        return INSTRUMENT_UNIVERSE["GOLD#"]

    clean = symbol.strip().upper()
    if clean in INSTRUMENT_UNIVERSE:
        return INSTRUMENT_UNIVERSE[clean]

    with_hash = f"{clean}#"
    if with_hash in INSTRUMENT_UNIVERSE:
        return INSTRUMENT_UNIVERSE[with_hash]

    stripped = clean.rstrip("#")
    if stripped in INSTRUMENT_UNIVERSE:
        return INSTRUMENT_UNIVERSE[stripped]

    # Search by alias
    for spec in INSTRUMENT_UNIVERSE.values():
        if clean in spec.aliases or stripped in spec.aliases or with_hash in spec.aliases:
            return spec

    # Default fallback
    return INSTRUMENT_UNIVERSE["GOLD#"]


def is_symbol_trading_open(
    symbol: str, asset_class: Optional[str] = None, ref_time_utc: Optional[datetime] = None
) -> bool:
    """
    Check if market is currently open for symbol.
    - CRYPTO is open 24/7/365.
    - FOREX and COMMODITIES are closed during weekends:
      From Friday 22:00 UTC through Sunday 22:00 UTC.
    """
    spec = get_symbol_spec(symbol)
    effective_class = (asset_class or (spec.asset_class if spec else "FOREX")).upper()

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


def format_symbol_price(symbol: str, price: Optional[float]) -> str:
    """Format price with exact decimal digits for the symbol."""
    if price is None:
        return "-"
    spec = get_symbol_spec(symbol)
    digits = spec.digits if spec else 2
    try:
        return f"{float(price):.{digits}f}"
    except (ValueError, TypeError):
        return "-"


def get_instruments_by_asset_class(asset_class: str) -> List[InstrumentSpec]:
    """Return all instruments belonging to the given asset class (FOREX, COMMODITIES, CRYPTO)."""
    norm = asset_class.upper()
    return [spec for spec in INSTRUMENT_UNIVERSE.values() if spec.asset_class == norm]

