"""Hard Deterministic Risk Engine.

Operates BELOW the AI and strategy layers:
1. Dynamic equity-based lot sizing snapped to broker volume steps.
2. 18.0% Max Total Margin Ceiling.
3. 2.5% Daily Drawdown Lock (anchored to broker server 00:00).
4. 5.0% Weekly Drawdown Lock.
5. Max Spread Points Filtering.
6. Zero-Naked-Trade (Mandatory hard broker SL).
"""

from decimal import Decimal, ROUND_FLOOR
from typing import Optional, Tuple


class RiskEngine:
    """Deterministic risk gatekeeper enforcing non-negotiable safety limits."""

    @staticmethod
    def calculate_lot_size(
        equity: float,
        risk_pct: float,
        entry_price: float,
        sl_price: float,
        contract_size: float,
        tick_size: float,
        tick_value: float,
        volume_min: float = 0.01,
        volume_max: float = 100.0,
        volume_step: float = 0.01,
        max_dollar_risk: Optional[float] = 50.0,
    ) -> Tuple[bool, float, str]:
        """
        Calculate dynamically sized lots based on cash at risk and stop distance.
        Formula:
            CashRisk = Equity * (RiskPct / 100) (capped at max_dollar_risk)
            StopDistance = abs(Entry - SL)
            TicksAtRisk = StopDistance / TickSize
            TickValueTotal = TicksAtRisk * TickValue
            Lots = CashRisk / TickValueTotal
        """
        if equity <= 0:
            return False, 0.0, "Account equity is zero or negative."

        if entry_price <= 0 or sl_price <= 0:
            return False, 0.0, "Invalid entry or SL price."

        stop_distance = abs(entry_price - sl_price)
        if stop_distance <= 0:
            return False, 0.0, "Stop distance must be strictly greater than 0."

        if tick_size <= 0 or tick_value <= 0:
            return False, 0.0, "Invalid tick size or tick value."

        cash_risk = equity * (risk_pct / 100.0)
        if max_dollar_risk and max_dollar_risk > 0:
            cash_risk = min(cash_risk, max_dollar_risk)

        ticks_at_risk = stop_distance / tick_size
        cost_per_lot_risk = ticks_at_risk * tick_value

        if cost_per_lot_risk <= 0:
            return False, 0.0, "Invalid risk calculation parameters."

        raw_lots = cash_risk / cost_per_lot_risk

        # Snap down to volume_step
        step_dec = Decimal(str(volume_step))
        lots_dec = (Decimal(str(raw_lots)) // step_dec) * step_dec
        final_lots = float(lots_dec)

        if final_lots < volume_min:
            # Check if volume_min is acceptable within small risk margin
            min_cash_risk = (ticks_at_risk * tick_value) * volume_min
            # Allow minimum volume only if min risk does not exceed 1.5x intended risk
            if min_cash_risk <= cash_risk * 1.5:
                final_lots = volume_min
            else:
                return (
                    False,
                    0.0,
                    f"Calculated lots ({raw_lots:.4f}) below broker min volume ({volume_min}) and exceeds risk tolerance.",
                )

        if final_lots > volume_max:
            final_lots = volume_max

        return True, round(final_lots, 4), "OK"

    @staticmethod
    def check_margin_ceiling(
        equity: float,
        margin_used: float,
        additional_required_margin: float = 0.0,
        max_margin_pct: float = 18.0,
    ) -> Tuple[bool, str]:
        """Verify that total margin usage does not breach the 18.0% ceiling."""
        if equity <= 0:
            return False, "Zero or negative equity."

        total_margin = margin_used + additional_required_margin
        usage_pct = (total_margin / equity) * 100.0

        if usage_pct > max_margin_pct:
            return (
                False,
                f"Margin ceiling breached: {usage_pct:.2f}% > limit {max_margin_pct:.2f}%.",
            )
        return True, "OK"

    @staticmethod
    def check_drawdown_locks(
        current_equity: float,
        daily_baseline_equity: float,
        weekly_baseline_equity: float,
        daily_limit_pct: float = 2.5,
        weekly_limit_pct: float = 5.0,
    ) -> Tuple[bool, str]:
        """
        Verify account equity against daily and weekly baselines.
        Returns False if either drawdown lock is tripped.
        """
        if daily_baseline_equity > 0:
            daily_dd = ((daily_baseline_equity - current_equity) / daily_baseline_equity) * 100.0
            if daily_dd >= daily_limit_pct:
                return (
                    False,
                    f"DAILY_DRAWDOWN_LOCK_HIT: Current daily DD is {daily_dd:.2f}% (Limit: {daily_limit_pct:.2f}%).",
                )

        if weekly_baseline_equity > 0:
            weekly_dd = ((weekly_baseline_equity - current_equity) / weekly_baseline_equity) * 100.0
            if weekly_dd >= weekly_limit_pct:
                return (
                    False,
                    f"WEEKLY_DRAWDOWN_LOCK_HIT: Current weekly DD is {weekly_dd:.2f}% (Limit: {weekly_limit_pct:.2f}%).",
                )

        return True, "OK"

    @staticmethod
    def check_spread_filter(current_spread_points: int, max_spread_points: int) -> Tuple[bool, str]:
        """Reject entry if spread is too wide."""
        if current_spread_points > max_spread_points:
            return (
                False,
                f"SPREAD_TOO_WIDE: Current spread {current_spread_points} pts > max {max_spread_points} pts.",
            )
        return True, "OK"

    @staticmethod
    def validate_zero_naked_trade(sl_price: float, entry_price: float, direction: str) -> Tuple[bool, str]:
        """Ensure mandatory hard broker SL exists and is positioned on the correct side."""
        if sl_price <= 0:
            return False, "ZERO_NAKED_TRADE_VIOLATION: Position must have a non-zero hard Stop Loss."

        if direction.upper() in ("BUY", "LONG") and sl_price >= entry_price:
            return False, "INVALID_SL_BUY: Buy SL must be below entry price."

        if direction.upper() in ("SELL", "SHORT") and sl_price <= entry_price:
            return False, "INVALID_SL_SELL: Sell SL must be above entry price."

        return True, "OK"

    @staticmethod
    def validate_trade_geometry_and_rr(
        direction: str,
        entry: float,
        sl: float,
        tp1: float,
        tp2: float,
        mode: str,
        current_spread_price: float,
        ltf_atr_14: float,
    ) -> Tuple[bool, str]:
        """
        Hard Pre-Order Math & Geometry Validation:
        1. Directional sanity:
           BUY: sl < entry < tp1
           SELL: tp1 < entry < sl
        2. Minimum structural SL distance:
           abs(entry - sl) >= 1.2 * ltf_atr_14
        3. Spread friction check:
           spread / abs(entry - sl) <= 0.15 for SCALP, <= 0.06 for SWING
        4. Hard Net R:R Floor (after spread deduction):
           SCALP: (abs(tp1 - entry) - spread) / abs(entry - sl) >= 1.8
           SWING: (abs(tp1 - entry) - spread) / abs(entry - sl) >= 2.5
        """
        if entry <= 0 or sl <= 0 or tp1 <= 0:
            return False, "Invalid price: entry, SL, and TP1 must be > 0"

        sl_dist = abs(entry - sl)
        if sl_dist <= 0:
            return False, "Zero SL distance"

        # 1. Directional Sanity
        if direction.upper() in ("BUY", "LONG"):
            if not (sl < entry < tp1):
                return False, f"Invalid BUY geometry: require sl ({sl}) < entry ({entry}) < tp1 ({tp1})"
            if tp2 > 0 and tp2 < tp1:
                return False, f"Invalid BUY geometry: require tp1 ({tp1}) <= tp2 ({tp2})"
        else:
            if not (tp1 < entry < sl):
                return False, f"Invalid SELL geometry: require tp1 ({tp1}) < entry ({entry}) < sl ({sl})"
            if tp2 > 0 and tp2 > tp1:
                return False, f"Invalid SELL geometry: require tp2 ({tp2}) <= tp1 ({tp1})"

        # 2. Minimum Structural SL Distance (avoid noise stops)
        if ltf_atr_14 > 0 and sl_dist < (1.2 * ltf_atr_14 - 1e-6):
            return False, f"SL too tight: {sl_dist:.5f} < 1.2 * ATR(14) ({1.2 * ltf_atr_14:.5f}). Stop placed in noise."

        # 3. Spread friction
        max_spread_pct = 0.15 if mode.upper() == "SCALP" else 0.06
        spread_ratio = current_spread_price / sl_dist
        if spread_ratio > max_spread_pct:
            return False, f"Spread friction excessive: spread is {spread_ratio*100:.1f}% of SL (max {max_spread_pct*100:.1f}%)"

        # 4. Hard Net R:R Floor
        tp1_dist = abs(tp1 - entry)
        net_tp_dist = tp1_dist - current_spread_price
        if net_tp_dist <= 0:
            return False, f"Net TP distance non-positive after spread ({net_tp_dist:.5f})"

        net_rr = net_tp_dist / sl_dist
        min_rr = 1.8 if mode.upper() == "SCALP" else 2.5
        if net_rr < (min_rr - 1e-4):
            return False, f"Net R:R ratio {net_rr:.2f} < minimum required {min_rr:.1f} for {mode} (after spread {current_spread_price})"

        return True, "OK"


risk_engine = RiskEngine()

