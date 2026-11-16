"""Forex & Crypto Macro News Blackout Guard.

Maintains a high-impact economic calendar (Tier-1 releases: US CPI, Core PCE,
NFP, FOMC, Powell speeches, ECB/BoE/BoJ rate decisions) and enforces a strict
entry blackout 15 minutes before to 15 minutes after releases for affected currencies.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.session import SessionLocal
from backend.app.db.models import MacroNewsEvent

logger = logging.getLogger(__name__)

# Default Tier-1 High Impact Release Titles
TIER1_TITLES = {
    "FOMC Interest Rate Decision",
    "Fed Chair Powell Press Conference",
    "US CPI (Consumer Price Index) YoY",
    "US Core PCE Price Index MoM",
    "US Non-Farm Payrolls (NFP)",
    "ECB Interest Rate Decision",
    "BoE Official Bank Rate",
    "BoJ Policy Rate",
}


@dataclass
class NewsBlackoutResult:
    """Detailed status of economic news blackout for a specific symbol."""
    is_blackout: bool
    symbol: str
    affected_currencies: List[str]
    event_title: Optional[str] = None
    currency: Optional[str] = None
    impact: Optional[str] = None
    event_time_utc: Optional[str] = None
    event_time_ist: Optional[str] = None
    minutes_to_release: Optional[float] = None
    minutes_blackout_remaining: Optional[float] = None
    blackout_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MacroNewsGuard:
    """Evaluates macro economic news events and enforces entry blackouts."""

    def __init__(self, blackout_window_min: int = 15):
        self.blackout_window_min = blackout_window_min
        self._calendar_cache: List[Dict[str, Any]] = []
        self._last_loaded_utc: Optional[datetime] = None

    @staticmethod
    def parse_affected_currencies(symbol: str) -> List[str]:
        """
        Extract fiat currencies whose Tier-1 macro releases impact this MT5 symbol.
        GOLD# -> ["USD"]
        EURUSD# -> ["EUR", "USD"]
        GBPUSD# -> ["GBP", "USD"]
        USDJPY# -> ["USD", "JPY"]
        BTCUSD#, ETHUSD#, SOLUSD# -> ["USD"] (US interest rate / CPI shocks impact crypto liquidity)
        """
        clean = symbol.upper().replace("#", "").replace("M", "").strip()

        if "GOLD" in clean or "XAU" in clean:
            return ["USD"]
        if "BTC" in clean or "ETH" in clean or "SOL" in clean:
            return ["USD"]

        # Standard 6-character FX majors
        if len(clean) >= 6:
            base = clean[:3]
            quote = clean[3:6]
            currencies = []
            for c in (base, quote):
                if c in ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD"):
                    currencies.append(c)
            return currencies if currencies else ["USD"]

        return ["USD"]

    def load_events_from_db(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        """Load upcoming and recent macro events from MySQL database."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        try:
            # Query events from past 24 hours to next 7 days
            now = now_utc()
            past_window = now - timedelta(hours=24)
            future_window = now + timedelta(days=7)

            events = (
                db.query(MacroNewsEvent)
                .filter(
                    MacroNewsEvent.event_time_utc >= past_window,
                    MacroNewsEvent.event_time_utc <= future_window,
                )
                .order_by(MacroNewsEvent.event_time_utc.asc())
                .all()
            )

            results = []
            for ev in events:
                results.append({
                    "id": ev.id,
                    "event_time_utc": ev.event_time_utc if ev.event_time_utc.tzinfo else ev.event_time_utc.replace(tzinfo=timezone.utc),
                    "currency": ev.currency.upper(),
                    "title": ev.title,
                    "impact": ev.impact.upper(),
                    "forecast": ev.forecast,
                    "previous": ev.previous,
                    "actual": ev.actual,
                })

            self._calendar_cache = results
            self._last_loaded_utc = now
            return results
        finally:
            if close_db:
                db.close()

    def add_event(
        self,
        event_time_utc: datetime,
        currency: str,
        title: str,
        impact: str = "HIGH",
        forecast: Optional[str] = None,
        previous: Optional[str] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """Add a single high-impact macro event to MySQL and in-memory cache."""
        close_db = False
        if db is None:
            db = SessionLocal()
            close_db = True

        if event_time_utc.tzinfo is None:
            event_time_utc = event_time_utc.replace(tzinfo=timezone.utc)

        try:
            db_event = MacroNewsEvent(
                event_time_utc=event_time_utc,
                currency=currency.upper(),
                title=title,
                impact=impact.upper(),
                forecast=forecast,
                previous=previous,
                created_at_utc=now_utc(),
            )
            db.add(db_event)
            db.commit()
            db.refresh(db_event)

            ev_dict = {
                "id": db_event.id,
                "event_time_utc": event_time_utc,
                "currency": currency.upper(),
                "title": title,
                "impact": impact.upper(),
                "forecast": forecast,
                "previous": previous,
                "actual": None,
            }
            self._calendar_cache.append(ev_dict)
            return ev_dict
        finally:
            if close_db:
                db.close()

    def check_blackout(
        self,
        symbol: str,
        current_time_utc: Optional[datetime] = None,
        custom_events: Optional[List[Dict[str, Any]]] = None,
    ) -> NewsBlackoutResult:
        """
        Check if the symbol is within the +/- 15 minute blackout window of a Tier-1 release.
        """
        ref_time = current_time_utc or now_utc()
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        affected_currencies = self.parse_affected_currencies(symbol)
        events = custom_events if custom_events is not None else self._calendar_cache

        # If cache is empty and no custom events provided, attempt quick DB reload
        if not events and custom_events is None:
            events = self.load_events_from_db()

        window_sec = self.blackout_window_min * 60

        for ev in events:
            ev_curr = str(ev.get("currency", "")).upper()
            if ev_curr not in affected_currencies:
                continue

            ev_impact = str(ev.get("impact", "")).upper()
            if ev_impact not in ("HIGH", "TIER1"):
                continue

            ev_time = ev.get("event_time_utc")
            if isinstance(ev_time, str):
                ev_time = datetime.fromisoformat(ev_time.replace("Z", "+00:00"))
            if ev_time.tzinfo is None:
                ev_time = ev_time.replace(tzinfo=timezone.utc)

            time_diff_sec = (ev_time - ref_time).total_seconds()
            # In blackout window if: -window_sec <= (ev_time - ref_time) <= window_sec
            # That is, within 15 min before release to 15 min after release.
            if -window_sec <= time_diff_sec <= window_sec:
                min_to_release = round(time_diff_sec / 60.0, 1)
                # Blackout ends window_sec after release time
                end_blackout_time = ev_time + timedelta(seconds=window_sec)
                min_remaining = max(0.0, round((end_blackout_time - ref_time).total_seconds() / 60.0, 1))

                reason = (
                    f"NEWS_BLACKOUT: {ev.get('title')} ({ev_curr}) scheduled at "
                    f"{to_ist_str(ev_time)}. {abs(min_to_release):.1f}m "
                    f"{'until release' if min_to_release >= 0 else 'since release'}. "
                    f"Blackout lifts in {min_remaining:.1f}m."
                )

                return NewsBlackoutResult(
                    is_blackout=True,
                    symbol=symbol,
                    affected_currencies=affected_currencies,
                    event_title=ev.get("title"),
                    currency=ev_curr,
                    impact=ev_impact,
                    event_time_utc=ev_time.isoformat(),
                    event_time_ist=to_ist_str(ev_time),
                    minutes_to_release=min_to_release,
                    minutes_blackout_remaining=min_remaining,
                    blackout_reason=reason,
                )

        return NewsBlackoutResult(
            is_blackout=False,
            symbol=symbol,
            affected_currencies=affected_currencies,
            blackout_reason="No high-impact releases within +/- 15m window.",
        )


news_guard = MacroNewsGuard(blackout_window_min=15)


def seed_default_macro_news(session: Session) -> None:
    """Seed default upcoming Tier-1 macro calendar releases if table is empty."""
    if session.query(MacroNewsEvent).count() == 0:
        base = now_utc()
        events = [
            (base + timedelta(hours=2), "USD", "US Core CPI YoY", "HIGH", "3.1%", "3.2%"),
            (base + timedelta(hours=14), "USD", "FOMC Interest Rate Decision", "HIGH", "5.25%", "5.25%"),
            (base + timedelta(days=1, hours=4), "EUR", "ECB Interest Rate Decision", "HIGH", "3.75%", "3.75%"),
            (base + timedelta(days=2, hours=6), "USD", "US Non-Farm Payrolls (NFP)", "HIGH", "180K", "175K"),
            (base + timedelta(days=3, hours=1), "JPY", "BoJ Policy Rate", "HIGH", "0.25%", "0.25%"),
        ]
        for t, curr, title, imp, fc, prev in events:
            session.add(
                MacroNewsEvent(
                    event_time_utc=t,
                    currency=curr,
                    title=title,
                    impact=imp,
                    forecast=fc,
                    previous=prev,
                    created_at_utc=base,
                )
            )
        session.commit()
        logger.info("Seeded default Tier-1 macro news calendar events.")

