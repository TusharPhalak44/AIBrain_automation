"""XM Global Brokerage Fee, Contract Specs & Friction Engine.

Accurately models:
1. Exact instrument specs from MySQL (or XM Ultra Low defaults).
2. Bid/Ask spread deduction based on historical bar spread.
3. Realistic execution slippage (Metals/Forex vs Crypto CFDs).
4. Overnight swap with Wednesday 3x triple-swap accounting.
5. Zero commission for XM Ultra Low / Standard accounts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, Optional, Tuple
from backend.app.core.clock_sync import get_broker_time
from backend.app.db.session import SessionLocal
from backend.app.db.models import TradingPairBot

logger = logging.getLogger(__name__)

# Accurate XM Ultra Low (#) / Standard Fallback Defaults
XM_FALLBACK_SPECS: Dict[str, Dict[str, Any]] = {
    "GOLD#": {
        "asset_class": "METAL",
        "contract_size": 100.0,
        "tick_size": 0.01,
        "tick_value": 1.0,
        "digits": 2,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -27.50,
        "swap_short": 14.20,
        "three_day_swap_day": 2,  # Wednesday (Python weekday 2)
        "default_slippage_pts": 2,
        "default_spread_pts": 25,
    },
    "EURUSD#": {
        "asset_class": "FOREX",
        "contract_size": 100000.0,
        "tick_size": 0.00001,
        "tick_value": 1.0,
        "digits": 5,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -6.80,
        "swap_short": 2.10,
        "three_day_swap_day": 2,
        "default_slippage_pts": 2,
        "default_spread_pts": 12,
    },
    "GBPUSD#": {
        "asset_class": "FOREX",
        "contract_size": 100000.0,
        "tick_size": 0.00001,
        "tick_value": 1.0,
        "digits": 5,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -4.50,
        "swap_short": -1.20,
        "three_day_swap_day": 2,
        "default_slippage_pts": 2,
        "default_spread_pts": 15,
    },
    "USDJPY#": {
        "asset_class": "FOREX",
        "contract_size": 100000.0,
        "tick_size": 0.001,
        "tick_value": 0.67,
        "digits": 3,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": 10.50,
        "swap_short": -18.00,
        "three_day_swap_day": 2,
        "default_slippage_pts": 2,
        "default_spread_pts": 14,
    },
    "BTCUSD#": {
        "asset_class": "CRYPTO",
        "contract_size": 1.0,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "digits": 2,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -15.00,
        "swap_short": -15.00,
        "three_day_swap_day": 2,
        "default_slippage_pts": 15,
        "default_spread_pts": 35,
    },
    "ETHUSD#": {
        "asset_class": "CRYPTO",
        "contract_size": 1.0,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "digits": 2,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -12.00,
        "swap_short": -12.00,
        "three_day_swap_day": 2,
        "default_slippage_pts": 15,
        "default_spread_pts": 30,
    },
    "SOLUSD#": {
        "asset_class": "CRYPTO",
        "contract_size": 1.0,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "digits": 2,
        "volume_min": 0.01,
        "volume_step": 0.01,
        "swap_long": -10.00,
        "swap_short": -10.00,
        "three_day_swap_day": 2,
        "default_slippage_pts": 15,
        "default_spread_pts": 40,
    },
}


@dataclass
class SymbolSpec:
    symbol: str
    asset_class: str
    contract_size: float
    tick_size: float
    tick_value: float
    digits: int
    volume_min: float
    volume_step: float
    swap_long: float
    swap_short: float
    three_day_swap_day: int
    default_slippage_pts: int
    default_spread_pts: int


class XMFeeEngine:
    """Calculates realistic XM trading costs, swap, spread, and net PnL."""

    def __init__(self, session=None):
        self._session = session

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        """Load instrument specs from MySQL TradingPairBot or fallback defaults."""
        sym = symbol.upper()
        # Check fallback dict first for default values
        fallback = XM_FALLBACK_SPECS.get(sym) or XM_FALLBACK_SPECS.get(f"{sym}#") or XM_FALLBACK_SPECS.get("GOLD#")

        db_ctx = self._session if self._session is not None else None
        if db_ctx is not None:
            pair = db_ctx.query(TradingPairBot).filter(
                (TradingPairBot.symbol == sym) | (TradingPairBot.symbol == f"{sym}#")
            ).first()
        else:
            with SessionLocal() as db:
                pair = db.query(TradingPairBot).filter(
                    (TradingPairBot.symbol == sym) | (TradingPairBot.symbol == f"{sym}#")
                ).first()

        if pair:
            return SymbolSpec(
                symbol=pair.symbol,
                asset_class=pair.asset_class,
                contract_size=float(pair.contract_size),
                tick_size=float(pair.tick_size),
                tick_value=float(pair.tick_value),
                digits=pair.digits,
                volume_min=float(pair.volume_min),
                volume_step=float(pair.volume_step),
                swap_long=float(pair.swap_long) if float(pair.swap_long) != 0.0 else fallback["swap_long"],
                swap_short=float(pair.swap_short) if float(pair.swap_short) != 0.0 else fallback["swap_short"],
                three_day_swap_day=2 if pair.three_day_swap_day in (2, 3) else pair.three_day_swap_day,
                default_slippage_pts=15 if pair.asset_class == "CRYPTO" else 2,
                default_spread_pts=int(pair.max_spread_points * 0.6) if pair.max_spread_points else fallback["default_spread_pts"],
            )

        # Fallback if pair not yet seeded
        return SymbolSpec(
            symbol=sym,
            asset_class=fallback["asset_class"],
            contract_size=fallback["contract_size"],
            tick_size=fallback["tick_size"],
            tick_value=fallback["tick_value"],
            digits=fallback["digits"],
            volume_min=fallback["volume_min"],
            volume_step=fallback["volume_step"],
            swap_long=fallback["swap_long"],
            swap_short=fallback["swap_short"],
            three_day_swap_day=fallback["three_day_swap_day"],
            default_slippage_pts=fallback["default_slippage_pts"],
            default_spread_pts=fallback["default_spread_pts"],
        )

    def calculate_swap(
        self,
        symbol_spec: SymbolSpec,
        direction: str,
        lots: float,
        entry_time: datetime,
        exit_time: datetime,
        broker_offset_sec: int = 7200,
    ) -> float:
        """
        Calculate total overnight swap cost.
        Applies swap per lot per night crossing 00:00 broker server time.
        Applies 3x swap multiplier on three_day_swap_day (Wednesday, weekday=2).
        """
        if exit_time <= entry_time or lots <= 0:
            return 0.0

        # Convert timestamps to broker server time perspective
        broker_entry = get_broker_time(entry_time, offset_sec=broker_offset_sec)
        broker_exit = get_broker_time(exit_time, offset_sec=broker_offset_sec)

        # Find first midnight crossing after entry
        current_midnight = broker_entry.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        swap_rate_per_lot = symbol_spec.swap_long if direction.upper() == "BUY" else symbol_spec.swap_short
        total_swap = 0.0

        while current_midnight <= broker_exit:
            # Check day of the week for 3x triple swap
            # Wednesday night crossing to Thursday: weekday 2
            multiplier = 3.0 if current_midnight.weekday() == symbol_spec.three_day_swap_day else 1.0
            nightly_swap = swap_rate_per_lot * lots * multiplier
            total_swap += nightly_swap
            current_midnight += timedelta(days=1)

        return round(total_swap, 2)

    def calculate_trade_friction(
        self,
        symbol: str,
        direction: str,
        lots: float,
        entry_price: float,
        exit_price: float,
        entry_time: datetime,
        exit_time: datetime,
        bar_spread_points: int = 0,
        slippage_points: Optional[int] = None,
        commission_per_lot: float = 0.0,
        broker_offset_sec: int = 7200,
    ) -> Dict[str, float]:
        """
        Compute comprehensive fee-adjusted trade accounting:
        - Gross PnL
        - Spread Cost
        - Slippage Cost
        - Swap Cost
        - Commission
        - Net Realized PnL
        """
        spec = self.get_symbol_spec(symbol)
        dir_mult = 1.0 if direction.upper() == "BUY" else -1.0

        # 1. Gross Price Delta PnL
        price_diff = (exit_price - entry_price) * dir_mult
        ticks = price_diff / spec.tick_size
        gross_pnl = ticks * spec.tick_value * lots

        # 2. Spread Cost
        spread_pts = bar_spread_points if bar_spread_points > 0 else spec.default_spread_pts
        spread_price = spread_pts * spec.tick_size
        spread_cost = (spread_pts * spec.tick_value) * lots

        # 3. Slippage Cost (entry + exit friction)
        slip_pts = slippage_points if slippage_points is not None else spec.default_slippage_pts
        slippage_cost = (slip_pts * 2 * spec.tick_value) * lots

        # 4. Overnight Swap Cost
        swap_cost = self.calculate_swap(
            symbol_spec=spec,
            direction=direction,
            lots=lots,
            entry_time=entry_time,
            exit_time=exit_time,
            broker_offset_sec=broker_offset_sec,
        )

        # 5. Commission Cost ($0 default on XM Ultra Low)
        comm_cost = commission_per_lot * lots

        # Net Realized PnL = Gross - Spread - Slippage + Swap - Commission
        net_pnl = gross_pnl - spread_cost - slippage_cost + swap_cost - comm_cost

        return {
            "gross_pnl": round(gross_pnl, 2),
            "spread_cost": round(spread_cost, 2),
            "slippage_cost": round(slippage_cost, 2),
            "swap_cost": round(swap_cost, 2),
            "commission": round(comm_cost, 2),
            "net_pnl": round(net_pnl, 2),
            "spread_points": spread_pts,
            "slippage_points": slip_pts,
        }


xm_fee_engine = XMFeeEngine()

