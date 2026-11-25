"""REST Routes for Gemini Supervisory Brain, Live Scheduler & Macro News."""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.core.symbol_utils import resolve_broker_symbol
from backend.app.db.session import get_db
from backend.app.db.models import (
    AppSettings,
    GeminiAnalysisReport,
    MacroNewsEvent,
    TradingPairBot,
    TradeLedger,
    LearnedPairRule,
    PairPatternMemory,
    SavedStrategy,
    StrategyScript,
)
from backend.app.ai_brain.scheduler import scheduler
from backend.app.ai_brain.news_guard import news_guard
from backend.app.ai_brain.forensic_learner import forensic_learner
from backend.app.ai_brain.cache_manager import cache_manager
from backend.app.ai_brain.gemini_supervisor import gemini_supervisor, INSTITUTIONAL_SUPERVISOR_SYSTEM_PROMPT
from backend.app.ai_brain.instruments import INSTRUMENT_UNIVERSE
from backend.app.mt5_bridge.connector import mt5_connector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["Gemini Supervisory Brain"])
brain_router = APIRouter(prefix="/ai-brain", tags=["Gemini Supervisory Brain (/ai-brain alias)"])


# Pydantic Schemas
class IntervalUpdateSchema(BaseModel):
    global_scan_interval_sec: Optional[int] = Field(None, ge=5, le=3600)
    pair_intervals: Optional[Dict[str, int]] = None


class NewsEventCreateSchema(BaseModel):
    event_time_utc: datetime
    currency: str = Field(..., max_length=8, description="USD, EUR, GBP, JPY")
    title: str = Field(..., description="Release title (e.g. US CPI YoY)")
    impact: str = Field("HIGH", description="HIGH, MEDIUM, LOW")
    forecast: Optional[str] = None
    previous: Optional[str] = None


@router.get("/reports")
def list_ai_reports(
    symbol: Optional[str] = None,
    account_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """List historical Gemini Supervisory analysis reports and market thesis."""
    query = db.query(GeminiAnalysisReport)
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        clean = resolved.rstrip("#")
        query = query.filter((GeminiAnalysisReport.symbol == resolved) | (GeminiAnalysisReport.symbol == clean) | (GeminiAnalysisReport.symbol == f"{clean}#"))
    if account_type:
        query = query.filter(GeminiAnalysisReport.account_type == account_type.upper())

    reports = query.order_by(GeminiAnalysisReport.scanned_at_utc.desc()).limit(limit).all()

    return [
        {
            "id": r.id,
            "account_type": r.account_type,
            "symbol": r.symbol,
            "market_regime": r.market_regime,
            "decision": r.decision,
            "recommended_mode": r.recommended_mode,
            "confidence": float(r.confidence),
            "entry_price": float(r.entry_price) if r.entry_price else None,
            "stop_loss": float(r.stop_loss) if r.stop_loss else None,
            "tp1": float(r.tp1) if r.tp1 else None,
            "tp2": float(r.tp2) if r.tp2 else None,
            "news_summary": r.news_summary,
            "thesis_text": r.thesis_text,
            "execution_status": r.execution_status,
            "readiness_pct": getattr(r, "readiness_pct", 0),
            "watch_bias": getattr(r, "watch_bias", "NONE"),
            "upcoming_setup": json.loads(r.upcoming_setup_json) if getattr(r, "upcoming_setup_json", None) else None,
            "scanned_at_utc": r.scanned_at_utc.isoformat(),
            "scanned_at_ist": to_ist_str(r.scanned_at_utc),
        }
        for r in reports
    ]


@router.get("/upcoming-setups")
@brain_router.get("/upcoming-setups")
@router.get("/radar")
@brain_router.get("/radar")
def get_upcoming_setups(db: Session = Depends(get_db)):
    """
    Return active upcoming setups across all pairs with live tick distance calculations.
    Splits into:
    1. actionable_setups: STAGE_PENDING / PLANNED trades ready for autonomous execution.
    2. watchlist_radar: Developing pre-trigger setups categorized into Scalp vs Swing.
    """
    st = db.query(AppSettings).filter_by(id=1).first()
    active_type = st.active_account_type if st else "DEMO"
    exec_mode = st.execution_mode if st else "AUTO"

    # 1. Actionable Setups (PLANNED in TradeLedger)
    planned_trades = (
        db.query(TradeLedger)
        .filter_by(account_type=active_type, status="PLANNED")
        .order_by(TradeLedger.opened_at_utc.desc())
        .all()
    )

    actionable = []
    for t in planned_trades:
        pair_bot = db.query(TradingPairBot).filter_by(symbol=t.symbol).first()
        digits = pair_bot.digits if pair_bot else 2
        max_spread_pts = pair_bot.max_spread_points if pair_bot else 35
        zone_pad = float(max_spread_pts) * (10 ** -digits) * 0.5

        cur_price = float(t.entry_price)
        dist_pts = 0
        in_zone = True

        if mt5_connector.is_connected:
            import MetaTrader5 as mt5
            from backend.app.core.instruments import resolve_marketwatch_symbol
            try:
                mw_sym = resolve_marketwatch_symbol(t.symbol)
                tick = mt5.symbol_info_tick(mw_sym) or mt5.symbol_info_tick(t.symbol)
                if tick:
                    cur_price = tick.ask if t.direction == "BUY" else tick.bid
                    if t.direction == "BUY":
                        dist_pts = int(round((cur_price - float(t.entry_price)) * (10 ** digits)))
                    else:
                        dist_pts = int(round((float(t.entry_price) - cur_price) * (10 ** digits)))
                    in_zone = abs(dist_pts) <= 10
            except Exception:
                pass

        entry_f = float(t.entry_price)
        sl_f = float(t.sl)
        tp1_f = float(t.tp1)
        tp2_f = float(t.tp2)
        sl_dist = abs(entry_f - sl_f)
        tp_dist = abs(tp2_f - entry_f)
        rr = round(tp_dist / max(0.0001, sl_dist), 2)

        actionable.append({
            "id": t.id,
            "trade_id": t.id,
            "symbol": t.symbol,
            "asset_class": getattr(pair_bot, "asset_class", "COMMODITIES") if pair_bot else "COMMODITIES",
            "direction": t.direction,
            "mode": t.mode,
            "setup_mode": t.mode,
            "trade_style": t.mode,
            "digits": digits,
            "lots": float(t.lots),
            "entry_price": entry_f,
            "planned_entry": entry_f,
            "trigger_price": entry_f,
            "trigger_zone_low": round(entry_f - zone_pad, digits),
            "trigger_zone_high": round(entry_f + zone_pad, digits),
            "sl": sl_f,
            "planned_sl": sl_f,
            "tp1": tp1_f,
            "planned_tp1": tp1_f,
            "tp2": tp2_f,
            "planned_tp2": tp2_f,
            "rr_ratio": rr,
            "projected_rr": rr,
            "current_price": cur_price,
            "distance_points": dist_pts,
            "distance_pips_or_pct": round(abs(cur_price - entry_f), digits),
            "in_trigger_zone": in_zone,
            "status": "READY_TO_EXECUTE" if in_zone else ("APPROACHING" if abs(dist_pts) <= 25 else "DEVELOPING"),
            "readiness_pct": 95 if in_zone else 80,
            "proximity_pct": 95 if in_zone else max(10, 90 - abs(dist_pts)),
            "thesis": t.ai_analysis_summary,
            "staged_at_ist": to_ist_str(t.opened_at_utc),
        })

    # 2. Watchlist Radar (Latest Gemini Analysis Reports with upcoming setups)
    pairs = db.query(TradingPairBot).filter_by(enabled=True).all()
    watchlist = []

    for p in pairs:
        latest_rep = (
            db.query(GeminiAnalysisReport)
            .filter_by(account_type=active_type, symbol=p.symbol)
            .order_by(GeminiAnalysisReport.scanned_at_utc.desc())
            .first()
        )
        if not latest_rep:
            continue

        upcoming_data = None
        if getattr(latest_rep, "upcoming_setup_json", None):
            try:
                upcoming_data = json.loads(latest_rep.upcoming_setup_json)
            except Exception:
                pass

        if not upcoming_data:
            entry_p = float(latest_rep.entry_price or 0.0)
            sl_p = float(latest_rep.stop_loss or 0.0)
            tp1_p = float(latest_rep.tp1 or 0.0)
            tp2_p = float(latest_rep.tp2 or 0.0)
            if entry_p > 0 and sl_p > 0:
                is_buy = entry_p > sl_p
                style = latest_rep.recommended_mode if latest_rep.recommended_mode in ("SCALP", "SWING") else "SCALP"
                upcoming_data = {
                    "watch_bias": "BULLISH_WATCH" if is_buy else "BEARISH_WATCH",
                    "setup_mode": style,
                    "trade_style": style,
                    "asset_class": p.asset_class,
                    "planning_tf": "M15" if style == "SCALP" else "H4",
                    "execution_tf": "M5" if style == "SCALP" else "H1",
                    "trigger_zone_low": round(entry_p - (float(p.max_spread_points) * (10 ** -p.digits)), p.digits),
                    "trigger_zone_high": round(entry_p + (float(p.max_spread_points) * (10 ** -p.digits)), p.digits),
                    "trigger_price": entry_p,
                    "planned_entry": entry_p,
                    "planned_sl": sl_p,
                    "planned_tp1": tp1_p,
                    "planned_tp2": tp2_p,
                    "rr_ratio": round(abs(tp2_p - entry_p) / max(0.0001, abs(entry_p - sl_p)), 2),
                    "projected_rr": round(abs(tp2_p - entry_p) / max(0.0001, abs(entry_p - sl_p)), 2),
                    "readiness_pct": 70,
                    "trigger_condition": f"Supervisory {latest_rep.decision} confirmation",
                    "invalidation_level": sl_p,
                    "invalidation_price": sl_p,
                    "expected_window": "Next 1-3 hours",
                    "expires_at": (now_utc() + timedelta(hours=2 if style == "SCALP" else 24)).isoformat(),
                }

        if upcoming_data and upcoming_data.get("planned_entry"):
            p_entry = float(upcoming_data["planned_entry"])
            bias = upcoming_data.get("watch_bias", "NONE")
            z_low = float(upcoming_data.get("trigger_zone_low") or (p_entry * 0.999))
            z_high = float(upcoming_data.get("trigger_zone_high") or (p_entry * 1.001))
            t_price = float(upcoming_data.get("trigger_price") or p_entry)
            style = upcoming_data.get("trade_style") or upcoming_data.get("setup_mode") or "SCALP"
            p_tf = upcoming_data.get("planning_tf") or ("M15" if style == "SCALP" else "H4")
            e_tf = upcoming_data.get("execution_tf") or ("M5" if style == "SCALP" else "H1")
            inv_p = float(upcoming_data.get("invalidation_price") or upcoming_data.get("invalidation_level") or (upcoming_data.get("planned_sl") or 0.0))
            exp_at = upcoming_data.get("expires_at") or (now_utc() + timedelta(hours=2 if style == "SCALP" else 24)).isoformat()

            cur_price = p_entry
            dist_pts = 0
            if mt5_connector.is_connected:
                import MetaTrader5 as mt5
                try:
                    tick = mt5.symbol_info_tick(p.symbol)
                    if tick:
                        cur_price = tick.ask if "BULL" in bias else tick.bid
                        if "BULL" in bias:
                            dist_pts = int(round((cur_price - p_entry) * (10 ** p.digits)))
                        else:
                            dist_pts = int(round((p_entry - cur_price) * (10 ** p.digits)))
                except Exception:
                    pass

            in_zone = z_low <= cur_price <= z_high
            status_tag = "TRIGGER_READY" if (in_zone or abs(dist_pts) <= 5) else ("APPROACHING" if abs(dist_pts) <= 25 else "DEVELOPING")

            # Calculate proximity percentage 0-100%
            sl_p = float(upcoming_data.get("planned_sl") or 0.0)
            spread_impact = round((float(p.max_spread_points) * (10 ** -p.digits) / max(0.0001, abs(p_entry - sl_p))) * 100, 1) if sl_p > 0 else 5.0

            proximity = int(max(0, min(100, 100 - (abs(dist_pts) * 2)))) if in_zone else max(10, min(95, 100 - abs(dist_pts)))

            watchlist.append({
                "symbol": p.symbol,
                "asset_class": p.asset_class,
                "trade_style": style.upper(),
                "setup_mode": style.upper(),
                "planning_tf": p_tf,
                "execution_tf": e_tf,
                "trigger_price": t_price,
                "distance_pips_or_pct": round(abs(cur_price - p_entry), p.digits),
                "invalidation_price": inv_p,
                "projected_rr": float(upcoming_data.get("projected_rr") or upcoming_data.get("rr_ratio") or 2.5),
                "expires_at": exp_at,
                "proximity_pct": proximity,
                "spread_impact_pct": spread_impact,
                "report_id": latest_rep.id,
                "market_regime": latest_rep.market_regime,
                "decision": latest_rep.decision,
                "confidence": float(latest_rep.confidence),
                "watch_bias": bias,
                "trigger_zone_low": z_low,
                "trigger_zone_high": z_high,
                "planned_entry": p_entry,
                "planned_sl": sl_p,
                "planned_tp1": float(upcoming_data.get("planned_tp1") or 0.0),
                "planned_tp2": float(upcoming_data.get("planned_tp2") or 0.0),
                "rr_ratio": float(upcoming_data.get("rr_ratio") or 2.5),
                "readiness_pct": int(upcoming_data.get("readiness_pct") or 65),
                "trigger_condition": upcoming_data.get("trigger_condition", ""),
                "invalidation_level": inv_p,
                "expected_window": upcoming_data.get("expected_window", ""),
                "current_price": cur_price,
                "distance_points": dist_pts,
                "in_trigger_zone": in_zone,
                "status": status_tag,
                "thesis": latest_rep.thesis_text,
                "scanned_at_ist": to_ist_str(latest_rep.scanned_at_utc),
            })

    scalp_setups = [item for item in watchlist if item.get("trade_style") == "SCALP"]
    swing_setups = [item for item in watchlist if item.get("trade_style") == "SWING"]

    return {
        "status": "SUCCESS",
        "account_type": active_type,
        "execution_mode": exec_mode,
        "actionable_setups": actionable,
        "watchlist_radar": watchlist,
        "scalp_setups": scalp_setups,
        "swing_setups": swing_setups,
        "total_actionable": len(actionable),
        "total_watchlist": len(watchlist),
        "total_scalp": len(scalp_setups),
        "total_swing": len(swing_setups),
    }


@router.post("/scan/{symbol}")
async def trigger_manual_scan(symbol: str, db: Session = Depends(get_db)):
    """Trigger an immediate supervisory scan for a specific pair, bypassing countdown timer."""
    resolved = resolve_broker_symbol(symbol, db)
    report = await scheduler.execute_pair_scan(resolved, db=db, bypass_circuit_breaker=True)
    if not report:
        raise HTTPException(
            status_code=404,
            detail=f"Pair '{resolved}' could not be scanned or was not found in database.",
        )

    return {
        "status": "SCANNED",
        "symbol": report.symbol,
        "market_regime": report.market_regime,
        "decision": report.decision,
        "recommended_mode": report.recommended_mode,
        "confidence": float(report.confidence),
        "execution_status": report.execution_status,
        "thesis_text": report.thesis_text,
        "scanned_at_ist": to_ist_str(report.scanned_at_utc),
    }


@router.post("/scan-all")
async def trigger_scan_all(db: Session = Depends(get_db)):
    """Trigger immediate supervisory analysis across all enabled trading pairs."""
    pairs = db.query(TradingPairBot).filter_by(enabled=True).all()
    results = []

    for p in pairs:
        rep = await scheduler.execute_pair_scan(p.symbol, db=db, bypass_circuit_breaker=True)
        if rep:
            results.append({
                "symbol": rep.symbol,
                "regime": rep.market_regime,
                "decision": rep.decision,
                "status": rep.execution_status,
            })

    return {
        "status": "COMPLETED",
        "scanned_count": len(results),
        "results": results,
    }


@router.post("/interval")
def update_intervals(payload: IntervalUpdateSchema):
    """Update global or per-pair scan intervals in MySQL and reset timers immediately."""
    scheduler.update_intervals(
        global_interval_sec=payload.global_scan_interval_sec,
        pair_intervals=payload.pair_intervals,
    )
    return {
        "status": "SUCCESS",
        "message": "Scan intervals updated and countdown timers reset.",
        "global_scan_interval_sec": payload.global_scan_interval_sec,
        "pair_intervals": payload.pair_intervals,
    }


class CopilotStageSchema(BaseModel):
    symbol: str
    mode: str = "SCALP"
    direction: str = "BUY"
    entry_price: float
    sl: float
    tp1: float
    tp2: float
    lots: Optional[float] = None
    ai_analysis_summary: Optional[str] = None


@router.post("/copilot/stage")
def stage_copilot_trade(payload: CopilotStageSchema, db: Session = Depends(get_db)):
    """Stage a planned trade setup into TradeLedger for 1-click execution."""
    st = db.query(AppSettings).filter_by(id=1).first()
    active_type = st.active_account_type if st else "DEMO"
    resolved = resolve_broker_symbol(payload.symbol, db)

    lots = payload.lots or 0.01
    trade = TradeLedger(
        account_type=active_type,
        position_id=0,
        symbol=resolved,
        magic_number=1001 if payload.mode.upper() == "SCALP" else 2001,
        mode=payload.mode.upper(),
        direction=payload.direction.upper(),
        lots=Decimal(str(lots)),
        initial_lots=Decimal(str(lots)),
        entry_price=Decimal(str(payload.entry_price)),
        sl=Decimal(str(payload.sl)),
        tp1=Decimal(str(payload.tp1)),
        tp2=Decimal(str(payload.tp2)),
        status="PLANNED",
        ai_analysis_summary=payload.ai_analysis_summary or "Staged from Gemini Supervisory Feed",
        opened_at_utc=now_utc(),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return {
        "status": "STAGED",
        "trade_id": trade.id,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "mode": trade.mode,
        "entry_price": float(trade.entry_price),
        "sl": float(trade.sl),
        "tp1": float(trade.tp1),
        "tp2": float(trade.tp2),
        "lots": float(trade.lots),
    }


@router.post("/copilot/{trade_id}/approve")
async def approve_copilot_trade(trade_id: int):
    """1-click user execution of a staged PLANNED Copilot trade setup."""
    try:
        ok, msg = await scheduler.approve_copilot_setup(trade_id)
        if not ok:
            raise HTTPException(status_code=400, detail={"error": "APPROVAL_FAILED", "message": msg})
        return {"status": "EXECUTED", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving copilot trade #{trade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail={"error": "EXECUTION_ERROR", "message": str(e)})


@router.post("/copilot/{trade_id}/reject")
async def reject_copilot_trade(trade_id: int):
    """1-click dismissal of a staged PLANNED Copilot trade setup."""
    try:
        ok, msg = await scheduler.reject_copilot_setup(trade_id)
        if not ok:
            raise HTTPException(status_code=400, detail={"error": "REJECTION_FAILED", "message": msg})
        return {"status": "DISMISSED", "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting copilot trade #{trade_id}: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail={"error": "REJECTION_ERROR", "message": str(e)})


@router.get("/news")
def get_macro_news_and_blackouts(symbol: Optional[str] = None, db: Session = Depends(get_db)):
    """View active Tier-1 macro economic calendar events and current blackout status."""
    events = news_guard.load_events_from_db(db=db)

    blackout_info = None
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        blackout_res = news_guard.check_blackout(resolved)
        blackout_info = blackout_res.to_dict()

    return {
        "total_events": len(events),
        "events": [
            {
                "id": ev["id"],
                "currency": ev["currency"],
                "title": ev["title"],
                "impact": ev["impact"],
                "forecast": ev.get("forecast"),
                "previous": ev.get("previous"),
                "event_time_utc": ev["event_time_utc"].isoformat(),
                "event_time_ist": to_ist_str(ev["event_time_utc"]),
            }
            for ev in events
        ],
        "blackout_check": blackout_info,
    }


@router.post("/news")
def create_macro_news_event(payload: NewsEventCreateSchema, db: Session = Depends(get_db)):
    """Add a Tier-1 macro news event to the economic calendar."""
    ev = news_guard.add_event(
        event_time_utc=payload.event_time_utc,
        currency=payload.currency,
        title=payload.title,
        impact=payload.impact,
        forecast=payload.forecast,
        previous=payload.previous,
        db=db,
    )
    return {
        "status": "CREATED",
        "event": {
            "id": ev["id"],
            "currency": ev["currency"],
            "title": ev["title"],
            "impact": ev["impact"],
            "event_time_utc": ev["event_time_utc"].isoformat(),
            "event_time_ist": to_ist_str(ev["event_time_utc"]),
        },
    }


class RuleStatusSchema(BaseModel):
    status: str = Field(..., description="LIVE, CANDIDATE, LOCKED, RETIRED, DEPRECATED")


def _serialize_rules(rules: List[LearnedPairRule]) -> List[dict]:
    res = []
    for r in rules:
        cond = json.loads(r.condition_json) if r.condition_json else {}
        act = json.loads(r.action_json) if r.action_json else {}
        origin_ids = json.loads(r.origin_loss_ids_json) if r.origin_loss_ids_json else []
        reason = act.get("reason") or cond.get("reason") or f"Blocks trade setups on {r.symbol} matching previous stop-loss fingerprint."
        category = "NEWS" if "NEWS" in r.rule_code else ("LIQU" if "LIQU" in r.rule_code else ("COUN" if "COUN" in r.rule_code else "REGI"))
        res.append({
            "id": r.id,
            "rule_code": r.rule_code,
            "symbol": r.symbol,
            "mode": r.mode,
            "status": r.status,
            "condition": cond,
            "action": act,
            "failure_reason": reason,
            "rule_description": reason,
            "category": category,
            "origin_loss_ids": origin_ids,
            "backtest_net_improvement_pct": float(r.backtest_net_improvement_pct or 0.0),
            "profit_factor_before": float(getattr(r, "profit_factor_before", 0.0) or 0.0),
            "profit_factor_after": float(getattr(r, "profit_factor_after", 0.0) or 0.0),
            "shadow_pf_before": float(getattr(r, "profit_factor_before", 0.0) or 0.0),
            "shadow_pf_after": float(getattr(r, "profit_factor_after", 0.0) or 0.0),
            "net_r_delta": float(getattr(r, "net_r_delta", 0.0) or 0.0),
            "net_r_saved": float(getattr(r, "net_r_delta", 0.0) or 0.0),
            "winners_preserved_pct": float(getattr(r, "winners_preserved_pct", 100.0) or 100.0),
            "winners_kept_pct": float(getattr(r, "winners_preserved_pct", 100.0) or 100.0),
            "avoided_losses_usd": float(getattr(r, "avoided_losses_usd", 0.0) or 0.0),
            "loss_avoided_usd": float(getattr(r, "avoided_losses_usd", 0.0) or 0.0),
            "trigger_count": int(getattr(r, "trigger_count", 0) or 0),
            "recent_profit_factor": float(getattr(r, "recent_profit_factor", 0.0) or 0.0),
            "shadow_scorecard": json.loads(r.shadow_scorecard_json) if getattr(r, "shadow_scorecard_json", None) else None,
            "created_at": r.created_at_utc.isoformat() if r.created_at_utc else "",
            "created_at_utc": r.created_at_utc.isoformat() if r.created_at_utc else "",
            "created_at_ist": to_ist_str(r.created_at_utc) if r.created_at_utc else "",
        })
    return res


@router.get("/rules")
def list_learned_rules(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
    as_dict: bool = False,
    db: Session = Depends(get_db),
):
    """List self-learned JSON filter rules produced by post-mortem forensics."""
    query = db.query(LearnedPairRule)
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        clean = resolved.rstrip("#")
        query = query.filter(
            (LearnedPairRule.symbol == resolved)
            | (LearnedPairRule.symbol == clean)
            | (LearnedPairRule.symbol == f"{clean}#")
        )
    if status:
        query = query.filter_by(status=status.upper())
    if mode:
        query = query.filter_by(mode=mode.upper())

    rules = query.order_by(LearnedPairRule.created_at_utc.desc()).all()
    res = _serialize_rules(rules)
    if as_dict:
        return {
            "rules": res,
            "live_count": sum(1 for r in res if r["status"] == "LIVE"),
            "locked_count": sum(1 for r in res if r["status"] == "LOCKED"),
            "candidate_count": sum(1 for r in res if r["status"] == "CANDIDATE"),
            "retired_count": sum(1 for r in res if r["status"] in ("RETIRED", "DEPRECATED")),
            "deprecated_count": sum(1 for r in res if r["status"] == "DEPRECATED"),
            "total_count": len(res),
        }
    return res


@brain_router.get("/rules")
def list_learned_rules_vault(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
    as_list: bool = False,
    db: Session = Depends(get_db),
):
    """Vault endpoint returning serialized rules + live aggregate status counters."""
    query = db.query(LearnedPairRule)
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        clean = resolved.rstrip("#")
        query = query.filter(
            (LearnedPairRule.symbol == resolved)
            | (LearnedPairRule.symbol == clean)
            | (LearnedPairRule.symbol == f"{clean}#")
        )
    if status:
        query = query.filter_by(status=status.upper())
    if mode:
        query = query.filter_by(mode=mode.upper())

    rules = query.order_by(LearnedPairRule.created_at_utc.desc()).all()
    res = _serialize_rules(rules)
    if as_list:
        return res
    return {
        "rules": res,
        "live_count": sum(1 for r in res if r["status"] == "LIVE"),
        "locked_count": sum(1 for r in res if r["status"] == "LOCKED"),
        "candidate_count": sum(1 for r in res if r["status"] == "CANDIDATE"),
        "retired_count": sum(1 for r in res if r["status"] in ("RETIRED", "DEPRECATED")),
        "deprecated_count": sum(1 for r in res if r["status"] == "DEPRECATED"),
        "total_count": len(res),
    }


@router.post("/rules/{rule_id}/status")
@brain_router.post("/rules/{rule_id}/status")
def update_rule_status(
    rule_id: int,
    payload: RuleStatusSchema,
    db: Session = Depends(get_db),
):
    """Update learned pair rule status (e.g. promote CANDIDATE to LIVE, or RETIRE)."""
    rule = db.query(LearnedPairRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"LearnedPairRule #{rule_id} not found")

    new_st = payload.status.upper()
    valid_states = {"LIVE", "CANDIDATE", "LOCKED", "RETIRED", "DEPRECATED"}
    if new_st not in valid_states:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{new_st}'. Must be one of {valid_states}",
        )

    rule.status = new_st
    db.commit()
    return {
        "status": "SUCCESS",
        "rule_id": rule.id,
        "rule_code": rule.rule_code,
        "new_status": rule.status,
    }


@router.delete("/rules/{rule_id}")
@brain_router.delete("/rules/{rule_id}")
def delete_learned_rule(rule_id: int, db: Session = Depends(get_db)):
    """Permanently delete/remove a self-learned rule from the vault."""
    rule = db.query(LearnedPairRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail=f"LearnedPairRule #{rule_id} not found")
    code = rule.rule_code
    db.delete(rule)
    db.commit()
    return {
        "status": "SUCCESS",
        "rule_id": rule_id,
        "rule_code": code,
        "message": f"Rule {code} permanently removed from vault.",
    }


@router.post("/circuit-breaker/reset")
@brain_router.post("/circuit-breaker/reset")
def reset_circuit_breaker(db: Session = Depends(get_db)):
    """Manually reset and clear the Daily Drawdown Circuit Breaker to resume autonomous trading."""
    prev_reason = scheduler.circuit_breaker_reason
    scheduler.circuit_breaker_tripped = False
    scheduler.circuit_breaker_until_utc = None
    scheduler.circuit_breaker_reason = None

    try:
        import asyncio
        from backend.app.ai_brain.telegram_notifier import telegram_notifier
        loop = asyncio.get_running_loop()
        loop.create_task(
            telegram_notifier.notify_system_guardrail(
                alert_type="CIRCUIT_BREAKER_RESET",
                title="Circuit Breaker Manually Cleared",
                details=f"Trader manually reset circuit breaker. Previous halt reason: {prev_reason or 'Daily Limit'}. Autonomous scanning and execution resumed.",
                action_taken="Scanning and Execution Unpaused",
                severity="INFO",
            )
        )
    except Exception as te:
        logger.debug(f"Circuit breaker reset notification note: {te}")

    return {
        "status": "SUCCESS",
        "message": "Circuit Breaker manually reset. Autonomous trade scanning and execution active.",
        "guardrail_status": scheduler.get_guardrail_status(db),
    }


@router.post("/forensics/{trade_id}")
def trigger_manual_forensics(trade_id: int, db: Session = Depends(get_db)):
    """Manually execute post-mortem diagnostics on a closed trade."""
    trade = db.query(TradeLedger).filter_by(id=trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail=f"Trade #{trade_id} not found in TradeLedger")

    rule = forensic_learner.run_sl_hit_postmortem(trade_id, db)
    return {
        "status": "COMPLETED",
        "trade_id": trade_id,
        "loss_postmortem_text": trade.loss_postmortem_text,
        "generated_rule": {
            "id": rule.id,
            "rule_code": rule.rule_code,
            "status": rule.status,
            "improvement_pct": float(rule.backtest_net_improvement_pct),
        } if rule else None,
    }


@router.get("/pattern-memory")
def get_pattern_memory(
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Fetch per-pair pattern win/loss memory scorecard (strictly isolating GOLD# vs BTCUSD#).
    """
    query = db.query(PairPatternMemory)
    if symbol:
        resolved = resolve_broker_symbol(symbol, db)
        clean = resolved.rstrip("#")
        query = query.filter(
            (PairPatternMemory.symbol == resolved)
            | (PairPatternMemory.symbol == clean)
            | (PairPatternMemory.symbol == f"{clean}#")
        )

    records = query.order_by(PairPatternMemory.symbol.asc(), PairPatternMemory.win_rate_pct.desc()).all()
    return [
        {
            "id": r.id,
            "symbol": r.symbol,
            "mode": r.mode,
            "pattern_signature": r.pattern_signature,
            "session_tag": r.session_tag,
            "wins": r.wins,
            "losses": r.losses,
            "total_trades": r.wins + r.losses,
            "win_rate_pct": float(r.win_rate_pct),
            "avg_r_multiple": float(r.avg_r_multiple),
            "net_pnl_usd": float(r.net_pnl_usd),
            "status": r.status,
            "last_ai_lesson": r.last_ai_lesson,
            "updated_at_ist": to_ist_str(r.updated_at),
        }
        for r in records
    ]


@router.get("/pending-limits")
async def get_pending_limits(db: Session = Depends(get_db)):
    """
    Return all active resting pending limit orders from MT5 broker terminal
    supplemented with TradeLedger records.
    """
    mt5_orders = []
    if mt5_connector.is_connected:
        try:
            mt5_orders = await mt5_connector.get_pending_orders()
        except Exception as e:
            logger.debug(f"Error fetching pending orders from MT5: {e}")

    # Also check TradeLedger for pending limits
    db_pending = db.query(TradeLedger).filter(TradeLedger.status == "PENDING").all()
    db_dict = {t.order_ticket: t for t in db_pending if t.order_ticket}

    combined = []
    seen_tickets = set()

    for ord_item in mt5_orders:
        t_id = ord_item.get("ticket")
        seen_tickets.add(t_id)
        db_rec = db_dict.get(t_id)
        combined.append({
            "ticket": t_id,
            "symbol": ord_item.get("symbol"),
            "order_type": ord_item.get("type_desc", "LIMIT"),
            "volume": ord_item.get("volume", 0.01),
            "price_open": ord_item.get("price_open", 0.0),
            "sl": ord_item.get("sl", 0.0),
            "tp": ord_item.get("tp", 0.0),
            "magic": ord_item.get("magic", 1001),
            "comment": ord_item.get("comment", ""),
            "state": "RESTING_ON_BROKER",
            "detected_patterns": json.loads(db_rec.detected_patterns_json) if db_rec and db_rec.detected_patterns_json else [],
        })

    for t in db_pending:
        if t.order_ticket not in seen_tickets:
            combined.append({
                "ticket": t.order_ticket or t.id,
                "symbol": t.symbol,
                "order_type": f"{t.direction}_LIMIT",
                "volume": float(t.lots),
                "price_open": float(t.entry_price),
                "sl": float(t.sl),
                "tp": float(t.tp2),
                "magic": t.magic_number,
                "comment": f"AUTO_{t.mode}",
                "state": "PENDING_EXECUTION",
                "detected_patterns": json.loads(t.detected_patterns_json) if t.detected_patterns_json else [],
            })

    return combined


# ============================================================================
# TASK 2: Daily Automated Cache Hygiene Engine Endpoints
# ============================================================================

class CacheConfigSchema(BaseModel):
    auto_daily_enabled: Optional[bool] = None
    daily_purge_hour_utc: Optional[int] = Field(None, ge=0, le=23)


@router.get("/cache/status")
def get_cache_status(db: Session = Depends(get_db)):
    """Return cache hygiene metrics, counts, last cleared, and next scheduled purge."""
    return cache_manager.get_status(db=db)


@router.post("/cache/clear")
def clear_cache_now(force_all: bool = False, db: Session = Depends(get_db)):
    """Trigger immediate manual cache purge for memory DFs, expired radar items, and payload buffers."""
    summary = cache_manager.purge_stale_entries(force_all=force_all, reason="USER_MANUAL_PURGE", db=db)
    status = cache_manager.get_status(db=db)
    return {
        "status": "SUCCESS",
        "message": f"Cache cleared: {summary['items_cleared']} items purged, ~{summary['estimated_bytes_freed']} bytes freed.",
        "summary": summary,
        "current_status": status,
    }


@router.patch("/cache/config")
def update_cache_config(payload: CacheConfigSchema, db: Session = Depends(get_db)):
    """Update auto-daily cache purge settings."""
    updated = cache_manager.configure(
        auto_daily_enabled=payload.auto_daily_enabled,
        daily_purge_hour_utc=payload.daily_purge_hour_utc,
        db=db,
    )
    return {"status": "SUCCESS", "config": updated}


# Endpoints attached to brain_router (/api/ai-brain/*)

@brain_router.get("/cache/status")
def get_cache_status_alias(db: Session = Depends(get_db)):
    return get_cache_status(db=db)

@brain_router.post("/cache/clear")
def clear_cache_now_alias(force_all: bool = False, db: Session = Depends(get_db)):
    return clear_cache_now(force_all=force_all, db=db)

@brain_router.patch("/cache/config")
def update_cache_config_alias(payload: CacheConfigSchema, db: Session = Depends(get_db)):
    return update_cache_config(payload=payload, db=db)


# ============================================================================
# TASK 4: Dynamic AI Scanning Interval & Timeframe Planning Controls
# ============================================================================

class ScannerConfigSchema(BaseModel):
    global_scan_interval_sec: Optional[int] = Field(None, ge=5, le=3600)
    scalp_planning_tf: Optional[str] = None
    scalp_execution_tf: Optional[str] = None
    swing_planning_tf: Optional[str] = None
    swing_execution_tf: Optional[str] = None
    pair_enabled_map: Optional[Dict[str, bool]] = None


@router.get("/scanner/config")
def get_scanner_config(db: Session = Depends(get_db)):
    """Get active dynamic scanning intervals, timeframe matrix, and active pairs."""
    st = db.query(AppSettings).filter_by(id=1).first()
    pairs = db.query(TradingPairBot).all()
    return {
        "global_scan_interval_sec": st.global_scan_interval_sec if st else 300,
        "scalp_planning_tf": getattr(st, "scalp_planning_tf", "M15"),
        "scalp_execution_tf": getattr(st, "scalp_execution_tf", "M5"),
        "swing_planning_tf": getattr(st, "swing_planning_tf", "H4"),
        "swing_execution_tf": getattr(st, "swing_execution_tf", "H1"),
        "pairs": [
            {
                "symbol": p.symbol,
                "asset_class": p.asset_class,
                "enabled": p.enabled,
                "scalp_enabled": p.scalp_enabled,
                "swing_enabled": p.swing_enabled,
                "scan_interval_sec": p.scan_interval_sec,
                "max_spread_points": p.max_spread_points,
            }
            for p in pairs
        ],
    }


@router.post("/scanner/config")
@router.patch("/scanner/config")
def update_scanner_config(payload: ScannerConfigSchema, db: Session = Depends(get_db)):
    """Hot-reload scanner intervals, timeframe matrix, and pair toggles without restart."""
    st = db.query(AppSettings).filter_by(id=1).first()
    if st:
        if payload.global_scan_interval_sec is not None:
            st.global_scan_interval_sec = payload.global_scan_interval_sec
        if payload.scalp_planning_tf is not None:
            st.scalp_planning_tf = payload.scalp_planning_tf
        if payload.scalp_execution_tf is not None:
            st.scalp_execution_tf = payload.scalp_execution_tf
        if payload.swing_planning_tf is not None:
            st.swing_planning_tf = payload.swing_planning_tf
        if payload.swing_execution_tf is not None:
            st.swing_execution_tf = payload.swing_execution_tf

    if payload.pair_enabled_map:
        for sym, is_en in payload.pair_enabled_map.items():
            pb = db.query(TradingPairBot).filter(
                (TradingPairBot.symbol == sym) | (TradingPairBot.symbol == f"{sym}#")
            ).first()
            if pb:
                pb.enabled = is_en

    db.commit()

    # Trigger hot-reload in scheduler
    try:
        scheduler._sync_pair_schedules(db)
    except Exception as e:
        logger.debug(f"Scheduler hot-reload note: {e}")

    return {"status": "SUCCESS", "message": "Scanner and timeframe configuration updated successfully."}


@router.get("/prompt-preview")
def get_prompt_preview(symbol: str = "GOLD#", db: Session = Depends(get_db)):
    """Render the exact institutional supervisor prompt for UI preview."""
    resolved = resolve_broker_symbol(symbol, db)
    rendered = gemini_supervisor.get_rendered_supervisor_prompt(resolved, db=db)
    return {
        "status": "SUCCESS",
        "symbol": resolved,
        "prompt_template": INSTITUTIONAL_SUPERVISOR_SYSTEM_PROMPT,
        "rendered_prompt": rendered,
    }


@router.post("/pairs/{symbol}/toggle")
def toggle_pair_enabled(symbol: str, db: Session = Depends(get_db)):
    """Toggle scanner enablement for a specific pair."""
    resolved = resolve_broker_symbol(symbol, db)
    pb = db.query(TradingPairBot).filter(
        (TradingPairBot.symbol == resolved) | (TradingPairBot.symbol == f"{resolved}#")
    ).first()
    if not pb:
        raise HTTPException(status_code=404, detail=f"Pair '{resolved}' not found.")
    pb.enabled = not pb.enabled
    db.commit()

    # Hot reload
    try:
        scheduler._sync_pair_schedules(db)
    except Exception:
        pass

    return {
        "status": "SUCCESS",
        "symbol": pb.symbol,
        "enabled": pb.enabled,
        "message": f"Pair {pb.symbol} scanner is now {'ENABLED' if pb.enabled else 'DISABLED'}.",
    }


@router.post("/reconcile-mt5")
@brain_router.post("/reconcile-mt5")
def trigger_mt5_reconciliation(db: Session = Depends(get_db)):
    """Manually trigger reconciliation of open trades in MySQL against live MT5 positions."""
    from backend.app.mt5_bridge.deal_reconciler import reconcile_open_trades_with_mt5
    res = reconcile_open_trades_with_mt5(db)
    return res


@router.get("/risk-guardrails")
@brain_router.get("/risk-guardrails")
@router.get("/guardrails")
@brain_router.get("/guardrails")
@router.get("/status")
@brain_router.get("/status")
def get_risk_guardrails(db: Session = Depends(get_db)):
    """Fetch live risk guardrail metrics, portfolio limits, circuit breaker, and cooldown timers."""
    return scheduler.get_guardrail_status(db)


# ============================================================================
# Telegram Notification Center & Template Testing
# ============================================================================

class TelegramConfigUpdateSchema(BaseModel):
    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    bot_username: Optional[str] = None
    admin_chat_id: Optional[str] = None
    thread_id: Optional[str] = None
    notify_pre_trigger: Optional[bool] = None
    notify_executions: Optional[bool] = None
    notify_be_and_partials: Optional[bool] = None
    notify_closures: Optional[bool] = None
    notify_system_alerts: Optional[bool] = None
    silent_pre_trigger: Optional[bool] = None


class TelegramTestSchema(BaseModel):
    template_type: str = Field(default="EXECUTION", description="SETUP, EXECUTION, LIMIT, BE, TP1, CLOSE, GUARDRAIL")
    symbol: Optional[str] = Field(default="GOLD#", description="Instrument symbol")
    chat_id: Optional[str] = None


@router.get("/telegram/config")
@brain_router.get("/telegram/config")
def get_telegram_config(db: Session = Depends(get_db)):
    """Fetch current Telegram alert configuration and category toggle flags."""
    from backend.app.core.crypto_vault import crypto_vault
    from backend.app.core.config import settings

    st = db.query(AppSettings).filter_by(id=1).first()
    if not st:
        raise HTTPException(status_code=404, detail="AppSettings not found")

    token = ""
    if st.telegram_bot_token_enc:
        try:
            token = crypto_vault.decrypt_secret(st.telegram_bot_token_enc) or ""
        except Exception:
            token = ""
    if not token and settings.TELEGRAM_BOT_TOKEN:
        token = settings.TELEGRAM_BOT_TOKEN

    masked_token = ""
    if token:
        if len(token) > 10:
            masked_token = f"{token[:6]}******{token[-4:]}"
        else:
            masked_token = "******"

    admin_chat = st.telegram_admin_chat_id or settings.TELEGRAM_CHAT_ID or ""

    return {
        "enabled": bool(st.telegram_enabled),
        "bot_token_masked": masked_token,
        "bot_username": st.telegram_bot_username or "",
        "admin_chat_id": admin_chat,
        "thread_id": st.telegram_thread_id or "",
        "notify_pre_trigger": bool(st.telegram_notify_pre_trigger),
        "notify_executions": bool(st.telegram_notify_executions),
        "notify_be_and_partials": bool(st.telegram_notify_be_and_partials),
        "notify_closures": bool(st.telegram_notify_closures),
        "notify_system_alerts": bool(st.telegram_notify_system_alerts),
        "silent_pre_trigger": bool(st.telegram_silent_pre_trigger),
        "is_configured": bool(token and admin_chat),
    }


@router.patch("/telegram/config")
@brain_router.patch("/telegram/config")
def update_telegram_config(payload: TelegramConfigUpdateSchema, db: Session = Depends(get_db)):
    """Update Telegram bot credentials and alert category subscription toggles."""
    from backend.app.core.crypto_vault import crypto_vault

    st = db.query(AppSettings).filter_by(id=1).first()
    if not st:
        raise HTTPException(status_code=404, detail="AppSettings not found")

    if payload.enabled is not None:
        st.telegram_enabled = payload.enabled
    if payload.bot_token is not None:
        clean_token = payload.bot_token.strip()
        if clean_token and not clean_token.startswith("***"):
            st.telegram_bot_token_enc = crypto_vault.encrypt_secret(clean_token)
    if payload.bot_username is not None:
        st.telegram_bot_username = payload.bot_username.strip()
    if payload.admin_chat_id is not None:
        clean_chat = payload.admin_chat_id.strip()
        if clean_chat:
            st.telegram_admin_chat_id = clean_chat
    if payload.thread_id is not None:
        st.telegram_thread_id = payload.thread_id.strip() or None
    if payload.notify_pre_trigger is not None:
        st.telegram_notify_pre_trigger = payload.notify_pre_trigger
    if payload.notify_executions is not None:
        st.telegram_notify_executions = payload.notify_executions
    if payload.notify_be_and_partials is not None:
        st.telegram_notify_be_and_partials = payload.notify_be_and_partials
    if payload.notify_closures is not None:
        st.telegram_notify_closures = payload.notify_closures
    if payload.notify_system_alerts is not None:
        st.telegram_notify_system_alerts = payload.notify_system_alerts
    if payload.silent_pre_trigger is not None:
        st.telegram_silent_pre_trigger = payload.silent_pre_trigger

    db.commit()
    db.refresh(st)
    return get_telegram_config(db)


@router.post("/telegram/test")
@brain_router.post("/telegram/test")
async def send_telegram_test_preview(payload: TelegramTestSchema, db: Session = Depends(get_db)):
    """Send live preview of an institutional HTML Telegram alert template."""
    import random
    import time
    from backend.app.ai_brain.telegram_notifier import telegram_notifier

    t_type = payload.template_type.upper()
    sym = payload.symbol or "GOLD#"

    cfg = telegram_notifier.get_config()
    target_chat = payload.chat_id or cfg.get("chat_id")
    if not cfg["bot_token"]:
        raise HTTPException(
            status_code=400,
            detail="Telegram Bot Token is not configured. Please save a valid bot token first.",
        )
    if not target_chat:
        raise HTTPException(
            status_code=400,
            detail="Telegram Chat ID is not configured. Please save a chat ID or register as admin.",
        )

    # Dynamic test ticket and price offsets to avoid collisions
    dynamic_ticket = int(time.time() * 10) % 90000000 + 10000000
    jitter = round(random.uniform(-3.0, 3.0), 2)

    common_kwargs = {
        "bypass_dedup": True,
        "bypass_category_check": True,
        "force_send": True,
        "override_chat_id": target_chat,
    }

    ok = False
    try:
        if t_type == "SETUP":
            ok = await telegram_notifier.notify_pre_trigger_setup(
                symbol=sym,
                trade_style="SCALP",
                direction="BUY",
                trigger_zone_price=2645.50 + jitter,
                invalidation_price=2638.00 + jitter,
                trigger_condition="Asian Low Sweep & M5 Bullish FVG Inversion Close",
                readiness_pct=85,
                time_to_trigger_est="15-30m",
                confluence_factors=[
                    "HTF H4 Bullish Order Flow",
                    "Session Low Liquidity Swept",
                    "M5 Imbalance Mitigation in Progress",
                    "Spread Healthy (11 pts)",
                ],
                thesis="Institutional liquidity grab below 2640. Expecting explosive expansion toward London High.",
                silent=False,
                **common_kwargs,
            )
        elif t_type == "EXECUTION":
            ok = await telegram_notifier.notify_trade_executed(
                ticket=dynamic_ticket,
                symbol=sym,
                mode="SCALP",
                direction="BUY",
                lots=0.15,
                entry_price=2648.20 + jitter,
                sl=2642.50 + jitter,
                tp1=2656.75 + jitter,
                tp2=2668.50 + jitter,
                cash_risk=85.50,
                risk_pct=0.50,
                spread_points=12,
                is_limit_order=False,
                confidence=0.88,
                gate_summary={
                    "G1_htf_alignment": True,
                    "G2_liquidity_sweep": True,
                    "G3_fvg_confluence": True,
                    "G4_risk_volatility": True,
                    "G5_spread_session": True,
                },
                ai_summary="Displacement candle confirmed off H1 demand block. Risk strictly capped at 0.50%.",
                **common_kwargs,
            )
        elif t_type == "LIMIT":
            ok = await telegram_notifier.notify_limit_filled_or_expired(
                ticket=dynamic_ticket,
                symbol=sym,
                direction="BUY",
                action="FILLED",
                fill_price=2645.50 + jitter,
                lots=0.15,
                sl=2640.00 + jitter,
                tp1=2653.75 + jitter,
                tp2=2665.00 + jitter,
                **common_kwargs,
            )
        elif t_type == "BE":
            ok = await telegram_notifier.notify_breakeven_locked(
                ticket=dynamic_ticket,
                symbol=sym,
                direction="BUY",
                entry_price=2648.20 + jitter,
                new_sl=2648.50 + jitter,
                current_r=1.05,
                next_target=2656.75 + jitter,
                **common_kwargs,
            )
        elif t_type == "TP1":
            ok = await telegram_notifier.notify_partial_tp1(
                ticket=dynamic_ticket,
                symbol=sym,
                direction="BUY",
                volume_closed=0.09,
                remaining_volume=0.06,
                realized_pnl=76.95,
                trailed_sl=2648.50 + jitter,
                tp2=2668.50 + jitter,
                current_r=1.50,
                **common_kwargs,
            )
        elif t_type == "CLOSE":
            ok = await telegram_notifier.notify_trade_closed(
                ticket=dynamic_ticket,
                symbol=sym,
                mode="SCALP",
                direction="BUY",
                entry_price=2648.20 + jitter,
                exit_price=2668.50 + jitter,
                gross_pnl=304.50,
                commission=0.00,
                swap=-2.15,
                net_pnl=302.35,
                r_multiple=3.54,
                exit_reason="TP2_HIT",
                hold_duration_str="1h 14m",
                prior_partial_pnl=76.95,
                today_scorecard={"wins": 4, "losses": 1, "net_pnl": 412.80, "open_positions": 2},
                **common_kwargs,
            )
        elif t_type == "GUARDRAIL":
            ok = await telegram_notifier.notify_system_guardrail(
                alert_type="CIRCUIT_BREAKER",
                title="Daily Drawdown -3.00% Circuit Breaker Active",
                details="Account daily drawdown touched -$312.40 (-3.12%). All autonomous scanning paused until 00:05 UTC next session.",
                action_taken="Autonomous Order Entry HALTED",
                severity="CRITICAL",
                **common_kwargs,
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown template_type: {t_type}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending test Telegram preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Telegram test failed: {str(e)}")

    if not ok:
        last_err = telegram_notifier.get_last_error()
        err_msg = f"Failed to deliver Telegram message: {last_err}" if last_err else "Failed to deliver Telegram message. Check bot token, chat ID permissions, or network connectivity."
        raise HTTPException(status_code=500, detail=err_msg)

    return {
        "status": "SUCCESS",
        "template_type": t_type,
        "symbol": sym,
        "message": f"Successfully delivered institutional {t_type} alert preview to Telegram.",
    }


# =========================================================================
# SAVED STRATEGIES & TESTED PNL VAULT (Empirical Scorecard Store)
# =========================================================================

class SavedStrategyCreateSchema(BaseModel):
    name: str = Field(..., max_length=128)
    strategy_code: str
    mode: str = Field("SCALP", max_length=16)  # SCALP, SWING, BOTH
    planning_tf: str = Field("M15", max_length=16)
    execution_tf: str = Field("M5", max_length=16)
    symbols: Optional[List[str]] = None
    rules_summary: Optional[str] = None
    prompt_template: Optional[str] = None
    tested_net_pnl: float = 0.0
    profit_factor: float = 1.0
    win_rate_pct: float = 50.0
    total_r: float = 0.0
    max_drawdown_pct: float = 0.0
    sample_trades_count: int = 0
    test_source: str = "BACKTEST_XM"
    is_active_live: bool = False


class SavedStrategyApplySchema(BaseModel):
    symbols: Optional[List[str]] = None
    mode: Optional[str] = None


def _serialize_saved_strategy(s: SavedStrategy) -> Dict[str, Any]:
    symbols_list = []
    if s.symbols_json:
        try:
            symbols_list = json.loads(s.symbols_json)
        except Exception:
            symbols_list = [s.symbols_json]
    return {
        "id": s.id,
        "name": s.name,
        "strategy_code": s.strategy_code,
        "mode": s.mode,
        "planning_tf": s.planning_tf,
        "execution_tf": s.execution_tf,
        "symbols": symbols_list,
        "rules_summary": s.rules_summary or "",
        "prompt_template": s.prompt_template or "",
        "tested_net_pnl": float(s.tested_net_pnl),
        "profit_factor": float(s.profit_factor),
        "win_rate_pct": float(s.win_rate_pct),
        "total_r": float(s.total_r),
        "max_drawdown_pct": float(s.max_drawdown_pct),
        "sample_trades_count": s.sample_trades_count,
        "test_source": s.test_source,
        "tested_at_ist": to_ist_str(s.tested_at_utc),
        "is_active_live": bool(s.is_active_live),
        "created_at_ist": to_ist_str(s.created_at_utc),
    }


@brain_router.get("/saved-strategies")
@router.get("/saved-strategies")
def list_saved_strategies(db: Session = Depends(get_db)):
    """List all saved empirical strategies in the Tested PnL Vault."""
    strategies = db.query(SavedStrategy).order_by(SavedStrategy.tested_net_pnl.desc()).all()
    return [_serialize_saved_strategy(s) for s in strategies]


@brain_router.post("/saved-strategies")
@router.post("/saved-strategies")
def create_saved_strategy(payload: SavedStrategyCreateSchema, db: Session = Depends(get_db)):
    """Save/bookmark strategy with verified empirical backtest metrics into vault."""
    from backend.app.strategy_lab.sandbox import validate_strategy_ast

    is_valid, err_msg, _ = validate_strategy_ast(payload.strategy_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"AST Security validation failed: {err_msg}")

    symbols_json = json.dumps(payload.symbols or ["EURUSD#", "GOLD#", "OILCash#", "BTCUSD#", "ETHUSD#"])

    record = SavedStrategy(
        name=payload.name,
        strategy_code=payload.strategy_code,
        mode=payload.mode.upper(),
        planning_tf=payload.planning_tf,
        execution_tf=payload.execution_tf,
        symbols_json=symbols_json,
        rules_summary=payload.rules_summary,
        prompt_template=payload.prompt_template,
        tested_net_pnl=Decimal(str(payload.tested_net_pnl)),
        profit_factor=Decimal(str(payload.profit_factor)),
        win_rate_pct=Decimal(str(payload.win_rate_pct)),
        total_r=Decimal(str(payload.total_r)),
        max_drawdown_pct=Decimal(str(payload.max_drawdown_pct)),
        sample_trades_count=payload.sample_trades_count,
        test_source=payload.test_source,
        is_active_live=payload.is_active_live,
        created_at_utc=now_utc(),
        tested_at_utc=now_utc(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "status": "SUCCESS",
        "message": f"Strategy '{record.name}' saved to Tested PnL Vault.",
        "strategy": _serialize_saved_strategy(record),
    }


@brain_router.post("/saved-strategies/{strategy_id}/apply")
@router.post("/saved-strategies/{strategy_id}/apply")
def apply_saved_strategy(
    strategy_id: int,
    payload: Optional[SavedStrategyApplySchema] = None,
    db: Session = Depends(get_db),
):
    """
    Deploy saved strategy to live scanner for its configured or requested symbols.
    Links strategy to TradingPairBot in MySQL and activates multi-timeframe scanning.
    """
    saved = db.query(SavedStrategy).filter_by(id=strategy_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail=f"SavedStrategy #{strategy_id} not found in vault")

    # 1. Sync or create corresponding StrategyScript
    script = db.query(StrategyScript).filter_by(name=saved.name).first()
    if not script:
        script = StrategyScript(
            name=saved.name,
            description=saved.rules_summary or f"Empirical strategy imported from Vault #{saved.id}",
            target_mode=saved.mode,
            python_code=saved.strategy_code,
            default_params_json="{}",
            is_builtin=False,
            created_at_utc=now_utc(),
        )
        db.add(script)
        db.commit()
        db.refresh(script)
    else:
        script.python_code = saved.strategy_code
        script.target_mode = saved.mode
        db.commit()

    # 2. Determine target symbols
    target_symbols = []
    if payload and payload.symbols:
        target_symbols = payload.symbols
    elif saved.symbols_json:
        try:
            target_symbols = json.loads(saved.symbols_json)
        except Exception:
            target_symbols = [saved.symbols_json]

    if not target_symbols:
        target_symbols = ["EURUSD#", "GOLD#", "OILCash#", "BTCUSD#", "ETHUSD#"]

    mode_to_apply = (payload.mode if payload and payload.mode else saved.mode).upper()

    applied_pairs = []
    for sym in target_symbols:
        clean = sym.rstrip("#")
        pair = (
            db.query(TradingPairBot)
            .filter((TradingPairBot.symbol == sym) | (TradingPairBot.symbol == clean) | (TradingPairBot.symbol == f"{clean}#"))
            .first()
        )
        if pair:
            if mode_to_apply in ("SCALP", "BOTH"):
                pair.scalp_strategy_id = script.id
                pair.scalp_enabled = True
            if mode_to_apply in ("SWING", "BOTH"):
                pair.swing_strategy_id = script.id
                pair.swing_enabled = True
            applied_pairs.append(pair.symbol)

    # 3. Update AppSettings scanner timeframes
    app_settings = db.query(AppSettings).filter_by(id=1).first()
    if app_settings:
        if mode_to_apply in ("SCALP", "BOTH"):
            app_settings.scalp_planning_tf = saved.planning_tf
            app_settings.scalp_execution_tf = saved.execution_tf
        if mode_to_apply in ("SWING", "BOTH"):
            app_settings.swing_planning_tf = saved.planning_tf
            app_settings.swing_execution_tf = saved.execution_tf

    # 4. Set is_active_live
    saved.is_active_live = True
    db.commit()

    # 5. Purge stale scanner cache
    try:
        cache_manager.clear_all()
    except Exception as e:
        logger.debug(f"Cache purge on strategy apply: {e}")

    return {
        "status": "SUCCESS",
        "message": f"Strategy '{saved.name}' deployed to live scanner across {len(applied_pairs)} symbols.",
        "strategy_id": saved.id,
        "script_id": script.id,
        "mode": mode_to_apply,
        "planning_tf": saved.planning_tf,
        "execution_tf": saved.execution_tf,
        "applied_pairs": applied_pairs,
    }


@brain_router.delete("/saved-strategies/{strategy_id}")
@router.delete("/saved-strategies/{strategy_id}")
def delete_saved_strategy(strategy_id: int, db: Session = Depends(get_db)):
    """Delete a strategy from the Tested PnL Vault."""
    saved = db.query(SavedStrategy).filter_by(id=strategy_id).first()
    if not saved:
        raise HTTPException(status_code=404, detail=f"SavedStrategy #{strategy_id} not found")

    db.delete(saved)
    db.commit()
    return {"status": "SUCCESS", "message": f"Strategy #{strategy_id} removed from vault."}





