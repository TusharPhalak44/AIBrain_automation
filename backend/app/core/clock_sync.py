"""IST & Broker Server Clock Engine.

Provides timezone-aware UTC timestamps, Indian Standard Time (IST) formatting,
and dynamic broker server UTC offset calculation for XM MT5 (GMT+2 / GMT+3).
"""

from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
from backend.app.core.config import settings

IST_ZONE = ZoneInfo(settings.DISPLAY_TIMEZONE)  # Asia/Kolkata


def now_utc() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    """Return current datetime converted to IST."""
    return now_utc().astimezone(IST_ZONE)


def to_ist(utc_dt: Optional[datetime]) -> Optional[datetime]:
    """Convert any datetime (assumed UTC if naive) to IST."""
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(IST_ZONE)


def to_ist_str(utc_dt: Optional[datetime], fmt: str = "%d %b %Y, %I:%M:%S %p IST") -> str:
    """Format a UTC datetime into clean human-readable IST string."""
    if utc_dt is None:
        return "-"
    ist_dt = to_ist(utc_dt)
    return ist_dt.strftime(fmt)


def compute_broker_offset_sec(tick_time_epoch: Optional[int] = None, system_utc_epoch: Optional[int] = None) -> int:
    """
    Compute dynamic broker server UTC offset from live tick timestamp vs system UTC.
    XM MT5 typically runs on Cyprus/Eastern European time:
    - Winter: GMT+2 (7200 sec)
    - Summer: GMT+3 (10800 sec)
    """
    if tick_time_epoch is None:
        try:
            import MetaTrader5 as mt5
            if mt5.terminal_info():
                for s in ["EURUSD#", "EURUSD", "GOLD#", "GOLD", "OILCash#", "OILCash", "BTCUSD#"]:
                    t = mt5.symbol_info_tick(s)
                    if t and t.time:
                        tick_time_epoch = t.time
                        break
        except Exception:
            pass

    if tick_time_epoch is None:
        return settings.BROKER_TZ_OFFSET_SEC

    if system_utc_epoch is None:
        system_utc_epoch = int(now_utc().timestamp())

    raw_diff = tick_time_epoch - system_utc_epoch
    # Snap to nearest 1800-second boundary within [-43200, +43200]
    snapped = round(raw_diff / 1800.0) * 1800
    return int(snapped)


def broker_epoch_to_utc(broker_epoch: int, offset_sec: Optional[int] = None) -> datetime:
    """
    Convert broker local server epoch timestamp to timezone-aware UTC datetime.
    Ensures MT5 deal/position timestamps do not get inflated by broker offset (+2h / +3h).
    """
    sec = offset_sec if offset_sec is not None else compute_broker_offset_sec()
    utc_epoch = broker_epoch - sec
    cur_epoch = int(now_utc().timestamp())
    if utc_epoch > cur_epoch + 60:
        utc_epoch = cur_epoch
    return datetime.fromtimestamp(utc_epoch, tz=timezone.utc)


def get_broker_time(utc_dt: Optional[datetime] = None, offset_sec: Optional[int] = None) -> datetime:
    """Calculate broker server datetime from UTC and offset."""
    dt = utc_dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    sec = offset_sec if offset_sec is not None else settings.BROKER_TZ_OFFSET_SEC
    return dt + timedelta(seconds=sec)


def get_broker_midnight_utc(reference_utc: Optional[datetime] = None, offset_sec: Optional[int] = None) -> datetime:
    """
    Get the UTC datetime corresponding to today's 00:00:00 broker server time.
    Used to anchor daily baseline equity and daily drawdown calculations.
    """
    dt = reference_utc or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    sec = offset_sec if offset_sec is not None else settings.BROKER_TZ_OFFSET_SEC

    # Convert to broker naive local perspective
    broker_dt = dt + timedelta(seconds=sec)
    broker_midnight = broker_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convert back to UTC
    return broker_midnight - timedelta(seconds=sec)


def is_rollover_period(broker_dt: Optional[datetime] = None, offset_sec: Optional[int] = None) -> bool:
    """
    Check if current broker time is in the rollover danger window (23:50 to 01:10).
    During rollover, broker spreads widen drastically, swaps are assessed, and new entries are blocked.
    """
    b_dt = broker_dt or get_broker_time(offset_sec=offset_sec)
    time_minutes = b_dt.hour * 60 + b_dt.minute
    # 23:50 is 1430 minutes; 01:10 is 70 minutes
    return time_minutes >= 1430 or time_minutes < 70

