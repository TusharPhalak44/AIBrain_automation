"""Daily Automated Cache Hygiene Engine.

Responsible for scheduled and on-demand clearing of:
1. In-memory OHLCV / technical indicator DataFrame caches.
2. Expired or invalidated setups in the Upcoming Trades & Pre-Trigger Setups Radar older than TTL:
   - Scalp pre-triggers (> 2 hours)
   - Swing pre-triggers (> 24 hours)
3. Temporary AI prompt/response payload caches and stale MT5 tick buffers.

CRITICAL INVARIANT:
Never delete or alter `learned_pair_rules`, historical closed trades, or open position state in MySQL.
"""

from datetime import datetime, timezone, timedelta
import logging
import sys
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.session import SessionLocal
from backend.app.db.models import AppSettings

logger = logging.getLogger(__name__)


class CacheManager:
    """Manages in-memory data structures, pre-trigger radar TTL expiry, and daily automated cache purges."""

    _instance: Optional["CacheManager"] = None

    def __new__(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
            cls._instance._init_caches()
        return cls._instance

    def _init_caches(self) -> None:
        # In-memory OHLCV and indicator cache: key -> {"df": DataFrame, "cached_at": datetime}
        self._df_cache: Dict[str, Any] = {}
        # In-memory pre-trigger radar cache: key -> {"setup": dict, "created_at": datetime, "style": str}
        self._radar_cache: Dict[str, Any] = {}
        # In-memory tick buffers: key -> {"ticks": list, "last_updated": datetime}
        self._tick_buffers: Dict[str, Any] = {}
        # Temporary prompt/response payload buffer: key -> {"payload": any, "created_at": datetime}
        self._payload_cache: Dict[str, Any] = {}
        # In-memory fast quote cache: key -> {"quote": dict, "time": datetime}
        self._quote_cache: Dict[str, Any] = {}

        self.last_cleared_at_utc: Optional[datetime] = None
        self.last_purge_summary: Dict[str, Any] = {
            "items_cleared": 0,
            "estimated_bytes_freed": 0,
            "cleared_at_utc": None,
            "reason": "Initialized",
        }

    # --- Cache storage helper methods ---

    def store_df(self, key: str, df: Any) -> None:
        """Cache an OHLCV or indicator DataFrame."""
        self._df_cache[key] = {"df": df, "cached_at": now_utc()}

    def get_df(self, key: str, max_age_seconds: int = 30) -> Optional[Any]:
        """Retrieve cached DataFrame if not older than max_age_seconds."""
        entry = self._df_cache.get(key)
        if entry:
            age = (now_utc() - entry["cached_at"]).total_seconds()
            if age <= max_age_seconds:
                return entry["df"]
            else:
                self._df_cache.pop(key, None)
        return None

    def store_radar_setup(self, key: str, setup: Dict[str, Any], style: str = "SCALP") -> None:
        """Cache a pre-trigger radar setup with creation timestamp and trade style."""
        self._radar_cache[key] = {
            "setup": setup,
            "created_at": now_utc(),
            "style": style.upper(),
        }

    def get_radar_setups(self) -> List[Dict[str, Any]]:
        """Return all active, non-expired radar setups."""
        self._expire_radar_entries()
        return [entry["setup"] for entry in self._radar_cache.values()]

    def store_tick(self, symbol: str, tick: Any) -> None:
        """Store tick in circular buffer (max 100 per symbol)."""
        if symbol not in self._tick_buffers:
            self._tick_buffers[symbol] = {"ticks": [], "last_updated": now_utc()}
        buf = self._tick_buffers[symbol]["ticks"]
        buf.append(tick)
        if len(buf) > 100:
            buf.pop(0)
        self._tick_buffers[symbol]["last_updated"] = now_utc()

    def store_payload(self, key: str, payload: Any) -> None:
        """Store temporary AI prompt or response payload."""
        self._payload_cache[key] = {"payload": payload, "created_at": now_utc()}

    # --- Purge and Hygiene routines ---

    def _expire_radar_entries(self, scalp_ttl_hours: float = 2.0, swing_ttl_hours: float = 24.0) -> int:
        """Internal helper to expire pre-trigger setups exceeding TTL."""
        now = now_utc()
        expired_keys = []
        for key, entry in self._radar_cache.items():
            age_hours = (now - entry["created_at"]).total_seconds() / 3600.0
            limit = scalp_ttl_hours if entry.get("style") == "SCALP" else swing_ttl_hours
            if age_hours > limit:
                expired_keys.append(key)
        for k in expired_keys:
            self._radar_cache.pop(k, None)
        return len(expired_keys)

    def purge_stale_entries(
        self,
        scalp_ttl_hours: float = 2.0,
        swing_ttl_hours: float = 24.0,
        force_all: bool = False,
        reason: str = "SCHEDULED_DAILY_PURGE",
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """
        Execute safe cache purge.
        Clears in-memory DFs, expired pre-trigger radar setups, prompt payload caches, and tick buffers.
        Never touches learned_pair_rules, trade_ledger, or open positions in MySQL.
        """
        now = now_utc()
        items_cleared = 0
        bytes_freed = 0

        # Estimate size before purge
        try:
            bytes_freed += sys.getsizeof(self._df_cache)
            bytes_freed += sys.getsizeof(self._payload_cache)
            bytes_freed += sys.getsizeof(self._tick_buffers)
            bytes_freed += sys.getsizeof(self._quote_cache)
        except Exception:
            pass

        # 1. Clear DataFrames
        df_count = len(self._df_cache)
        self._df_cache.clear()
        items_cleared += df_count

        # 2. Expire Radar Setups
        if force_all:
            radar_count = len(self._radar_cache)
            self._radar_cache.clear()
            items_cleared += radar_count
        else:
            radar_expired = self._expire_radar_entries(scalp_ttl_hours, swing_ttl_hours)
            items_cleared += radar_expired

        # 3. Clear temporary AI payloads & tick buffers
        payload_count = len(self._payload_cache)
        self._payload_cache.clear()
        items_cleared += payload_count

        tick_count = sum(len(v.get("ticks", [])) for v in self._tick_buffers.values())
        self._tick_buffers.clear()
        self._quote_cache.clear()
        items_cleared += tick_count

        # Update last cleared timestamp
        self.last_cleared_at_utc = now
        summary = {
            "items_cleared": items_cleared,
            "estimated_bytes_freed": bytes_freed,
            "cleared_at_utc": now.isoformat(),
            "cleared_at_ist": to_ist_str(now),
            "reason": reason,
        }
        self.last_purge_summary = summary

        # Persist timestamp to MySQL AppSettings
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True
        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st:
                st.cache_last_cleared_at_utc = now
                db.commit()
        except Exception as e:
            logger.debug(f"Could not persist cache_last_cleared_at_utc: {e}")
        finally:
            if close_db:
                db.close()

        logger.info(
            f"Daily Cache Purge completed: {items_cleared} items cleared, "
            f"~{bytes_freed} bytes freed ({reason})."
        )
        return summary

    def get_status(self, db: Optional[Session] = None) -> Dict[str, Any]:
        """Return live cache hygiene status, counts, and scheduled purge timing."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        auto_daily = True
        purge_hour = 0
        purge_minute = 5
        last_cleared = self.last_cleared_at_utc

        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st:
                auto_daily = getattr(st, "cache_auto_daily_enabled", True)
                purge_hour = getattr(st, "cache_daily_purge_hour_utc", 0)
                purge_minute = getattr(st, "cache_daily_purge_minute_utc", 5)
                if getattr(st, "cache_last_cleared_at_utc", None):
                    last_cleared = st.cache_last_cleared_at_utc
        except Exception as e:
            logger.debug(f"Could not read AppSettings for cache: {e}")
        finally:
            if close_db:
                db.close()

        # Compute next scheduled purge time
        now = now_utc()
        next_purge = now.replace(hour=purge_hour, minute=purge_minute, second=0, microsecond=0)
        if next_purge <= now:
            next_purge += timedelta(days=1)

        seconds_until_purge = max(0, int((next_purge - now).total_seconds()))

        # Determine health badge
        is_purge_due = False
        if last_cleared:
            if last_cleared.tzinfo is None:
                last_cleared = last_cleared.replace(tzinfo=timezone.utc)
            hours_since_clear = (now - last_cleared).total_seconds() / 3600.0
            if hours_since_clear > 26:
                is_purge_due = True
        else:
            is_purge_due = False

        cached_count = (
            len(self._df_cache)
            + len(self._radar_cache)
            + len(self._payload_cache)
            + len(self._tick_buffers)
            + len(self._quote_cache)
        )

        estimated_size = (
            sys.getsizeof(self._df_cache)
            + sys.getsizeof(self._radar_cache)
            + sys.getsizeof(self._payload_cache)
            + sys.getsizeof(self._tick_buffers)
            + sys.getsizeof(self._quote_cache)
        )

        return {
            "health_badge": "Purge Due" if is_purge_due else "Healthy",
            "is_purge_due": is_purge_due,
            "auto_daily_enabled": auto_daily,
            "daily_purge_hour_utc": purge_hour,
            "daily_purge_minute_utc": purge_minute,
            "last_cleared_at_utc": last_cleared.isoformat() if last_cleared else None,
            "last_cleared_at_ist": to_ist_str(last_cleared) if last_cleared else "Never",
            "next_scheduled_at_utc": next_purge.isoformat(),
            "next_scheduled_at_ist": to_ist_str(next_purge),
            "seconds_until_next_purge": seconds_until_purge,
            "cached_entries_count": cached_count,
            "estimated_size_kb": round(estimated_size / 1024.0, 2),
            "last_purge_summary": self.last_purge_summary,
        }

    def configure(
        self,
        auto_daily_enabled: Optional[bool] = None,
        daily_purge_hour_utc: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Update cache purge configuration in AppSettings."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st:
                if auto_daily_enabled is not None:
                    st.cache_auto_daily_enabled = auto_daily_enabled
                if daily_purge_hour_utc is not None:
                    st.cache_daily_purge_hour_utc = max(0, min(23, daily_purge_hour_utc))
                db.commit()
                db.refresh(st)
            return self.get_status(db=db)
        finally:
            if close_db:
                db.close()


# Singleton instance
cache_manager = CacheManager()
