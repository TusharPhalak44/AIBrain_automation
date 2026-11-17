"""REST Routes for Gemini Supervisory Brain, Live Scheduler & Macro News."""

from datetime import datetime, timezone
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
)
from backend.app.ai_brain.scheduler import scheduler
from backend.app.ai_brain.news_guard import news_guard
from backend.app.ai_brain.forensic_learner import forensic_learner
from backend.app.mt5_bridge.connector import mt5_connector

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["Gemini Supervisory Brain"])


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
async def get_upcoming_setups(db: Session = Depends(get_db)):
    """
    Return active upcoming setups across all pairs with live tick distance calculations.
    Splits into:
    1. actionable_setups: STAGE_PENDING / PLANNED Copilot trades ready for 1-click execution.
    2. watchlist_radar: Developing pre-trigger setups with live distance points ticking towards entry.
    """
    st = db.query(AppSettings).filter_by(id=1).first()
    active_type = st.active_account_type if st else "DEMO"
    exec_mode = st.execution_mode if st else "COPILOT"

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

        cur_price = float(t.entry_price)
        dist_pts = 0
        in_zone = True

        if mt5_connector.is_connected:
            import MetaTrader5 as mt5
            try:
                tick = mt5.symbol_info_tick(t.symbol)
                if tick:
                    cur_price = tick.ask if t.direction == "BUY" else tick.bid
                    if t.direction == "BUY":
                        dist_pts = int(round((cur_price - float(t.entry_price)) * (10 ** digits)))
                    else:
                        dist_pts = int(round((float(t.entry_price) - cur_price) * (10 ** digits)))
                    in_zone = abs(dist_pts) <= 10
            except Exception:
                pass

        sl_dist = abs(float(t.entry_price) - float(t.sl))
        tp_dist = abs(float(t.tp2) - float(t.entry_price))
        rr = round(tp_dist / max(0.0001, sl_dist), 2)

        actionable.append({
            "id": t.id,
            "trade_id": t.id,
            "symbol": t.symbol,
            "direction": t.direction,
            "mode": t.mode,
            "lots": float(t.lots),
            "entry_price": float(t.entry_price),
            "sl": float(t.sl),
            "tp1": float(t.tp1),
            "tp2": float(t.tp2),
            "rr_ratio": rr,
            "current_price": cur_price,
            "distance_points": dist_pts,
            "in_trigger_zone": in_zone,
            "status": "READY_TO_EXECUTE" if in_zone else ("APPROACHING" if abs(dist_pts) <= 25 else "DEVELOPING"),
            "readiness_pct": 95 if in_zone else 80,
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
                upcoming_data = {
                    "watch_bias": "BULLISH_WATCH" if is_buy else "BEARISH_WATCH",
                    "setup_mode": latest_rep.recommended_mode if latest_rep.recommended_mode != "NONE" else "SCALP",
                    "trigger_zone_low": round(entry_p - (float(p.max_spread_points) * 0.01), p.digits),
                    "trigger_zone_high": round(entry_p + (float(p.max_spread_points) * 0.01), p.digits),
                    "planned_entry": entry_p,
                    "planned_sl": sl_p,
                    "planned_tp1": tp1_p,
                    "planned_tp2": tp2_p,
                    "rr_ratio": round(abs(tp2_p - entry_p) / max(0.0001, abs(entry_p - sl_p)), 2),
                    "readiness_pct": 70,
                    "trigger_condition": f"Supervisory {latest_rep.decision} confirmation",
                    "invalidation_level": sl_p,
                    "expected_window": "Next 1-3 hours",
                }

        if upcoming_data and upcoming_data.get("planned_entry"):
            p_entry = float(upcoming_data["planned_entry"])
            bias = upcoming_data.get("watch_bias", "NONE")
            z_low = float(upcoming_data.get("trigger_zone_low") or (p_entry * 0.999))
            z_high = float(upcoming_data.get("trigger_zone_high") or (p_entry * 1.001))

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

            watchlist.append({
                "symbol": p.symbol,
                "asset_class": p.asset_class,
                "report_id": latest_rep.id,
                "market_regime": latest_rep.market_regime,
                "decision": latest_rep.decision,
                "confidence": float(latest_rep.confidence),
                "watch_bias": bias,
                "setup_mode": upcoming_data.get("setup_mode", "SCALP"),
                "trigger_zone_low": z_low,
                "trigger_zone_high": z_high,
                "planned_entry": p_entry,
                "planned_sl": float(upcoming_data.get("planned_sl") or 0.0),
                "planned_tp1": float(upcoming_data.get("planned_tp1") or 0.0),
                "planned_tp2": float(upcoming_data.get("planned_tp2") or 0.0),
                "rr_ratio": float(upcoming_data.get("rr_ratio") or 2.5),
                "readiness_pct": int(upcoming_data.get("readiness_pct") or 65),
                "trigger_condition": upcoming_data.get("trigger_condition", ""),
                "invalidation_level": float(upcoming_data.get("invalidation_level") or 0.0),
                "expected_window": upcoming_data.get("expected_window", ""),
                "current_price": cur_price,
                "distance_points": dist_pts,
                "in_trigger_zone": in_zone,
                "status": status_tag,
                "thesis": latest_rep.thesis_text,
                "scanned_at_ist": to_ist_str(latest_rep.scanned_at_utc),
            })

    return {
        "status": "SUCCESS",
        "account_type": active_type,
        "execution_mode": exec_mode,
        "actionable_setups": actionable,
        "watchlist_radar": watchlist,
        "total_actionable": len(actionable),
        "total_watchlist": len(watchlist),
    }


@router.post("/scan/{symbol}")
async def trigger_manual_scan(symbol: str, db: Session = Depends(get_db)):
    """Trigger an immediate supervisory scan for a specific pair, bypassing countdown timer."""
    resolved = resolve_broker_symbol(symbol, db)
    report = await scheduler.execute_pair_scan(resolved)
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
        rep = await scheduler.execute_pair_scan(p.symbol)
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


@router.get("/rules")
def list_learned_rules(
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    mode: Optional[str] = None,
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
    res = []
    for r in rules:
        cond = json.loads(r.condition_json) if r.condition_json else {}
        act = json.loads(r.action_json) if r.action_json else {}
        origin_ids = json.loads(r.origin_loss_ids_json) if r.origin_loss_ids_json else []
        res.append({
            "id": r.id,
            "rule_code": r.rule_code,
            "symbol": r.symbol,
            "mode": r.mode,
            "status": r.status,
            "condition": cond,
            "action": act,
            "origin_loss_ids": origin_ids,
            "backtest_net_improvement_pct": float(r.backtest_net_improvement_pct),
            "created_at_utc": r.created_at_utc.isoformat(),
            "created_at_ist": to_ist_str(r.created_at_utc),
        })
    return res


@router.post("/rules/{rule_id}/status")
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


