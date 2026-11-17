"""Gemini Usage & Cost Accounting Analytics Routes."""

import csv
from datetime import datetime, timedelta
from decimal import Decimal
import io
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.clock_sync import now_utc, to_ist_str
from backend.app.db.models import AppSettings, GeminiModelRateCard, GeminiUsageLedger
from backend.app.db.session import get_db
from backend.app.ai_brain.usage_tracker import get_model_rate_card, calculate_cost

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["AI Usage & Billing"])


class RateCardUpdateItem(BaseModel):
    model_id: str
    input_per_1m_usd: float
    output_per_1m_usd: float
    cached_per_1m_usd: float
    is_free_tier_eligible: bool = True


class UpdateRatesPayload(BaseModel):
    rates: Optional[List[RateCardUpdateItem]] = None
    gemini_use_free_tier: Optional[bool] = None


@router.get("/summary")
def get_usage_summary(
    granularity: str = Query("DAILY", description="DAILY, WEEKLY, or MONTHLY"),
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    symbol: Optional[str] = Query(None, description="Filter by symbol e.g. GOLD#"),
    model_id: Optional[str] = Query(None, description="Filter by model e.g. gemini-3.8-flash"),
    call_purpose: Optional[str] = Query(None, description="LIVE_SCAN, MANUAL_SCAN, SL_FORENSICS, etc."),
    account_type: Optional[str] = Query(None, description="DEMO or LIVE"),
    usd_to_inr_rate: float = Query(86.50, description="USD to INR exchange rate"),
    db: Session = Depends(get_db),
):
    """Compile comprehensive Gemini API token usage, costs, breakdowns, and time-series."""
    query = db.query(GeminiUsageLedger)

    if account_type:
        query = query.filter(GeminiUsageLedger.account_type == account_type.upper())
    if symbol:
        clean_sym = symbol.rstrip("#")
        query = query.filter(
            (GeminiUsageLedger.symbol == symbol)
            | (GeminiUsageLedger.symbol == clean_sym)
            | (GeminiUsageLedger.symbol == f"{clean_sym}#")
        )
    if model_id:
        clean_m = model_id.replace("models/", "").strip()
        query = query.filter(GeminiUsageLedger.model_id.contains(clean_m))
    if call_purpose:
        query = query.filter(GeminiUsageLedger.call_purpose == call_purpose.upper())
    if start_date:
        query = query.filter(GeminiUsageLedger.ist_date >= start_date)
    if end_date:
        query = query.filter(GeminiUsageLedger.ist_date <= end_date)

    entries = query.order_by(GeminiUsageLedger.created_at_utc.desc()).all()

    # Pre-fetch rate cards for shadow pricing
    rate_cards = {rc.model_id: rc for rc in db.query(GeminiModelRateCard).all()}

    total_calls = len(entries)
    total_tokens = sum(e.total_tokens for e in entries)
    total_prompt = sum(e.prompt_tokens for e in entries)
    total_output = sum(e.output_tokens for e in entries)
    total_thinking = sum(e.thinking_tokens for e in entries)
    total_cached = sum(e.cached_tokens for e in entries)
    total_cost_usd = sum(float(e.estimated_cost_usd) for e in entries)
    total_cost_inr = total_cost_usd * usd_to_inr_rate

    # Shadow Paid Value & Cached Savings
    shadow_paid_usd = 0.0
    cached_savings_usd = 0.0
    for e in entries:
        rc = rate_cards.get(e.model_id)
        in_r = Decimal(str(rc.input_per_1m_usd)) if rc else Decimal("0.75")
        out_r = Decimal(str(rc.output_per_1m_usd)) if rc else Decimal("3.75")
        c_r = Decimal(str(rc.cached_per_1m_usd)) if rc else Decimal("0.075")

        full_cost = calculate_cost(
            prompt_tokens=e.prompt_tokens,
            output_tokens=e.output_tokens,
            thinking_tokens=e.thinking_tokens,
            cached_tokens=e.cached_tokens,
            input_rate=in_r,
            output_rate=out_r,
            cached_rate=c_r,
        )
        shadow_paid_usd += float(full_cost)

        # Savings = difference between paying full input rate on cached tokens vs cached rate
        if e.cached_tokens > 0:
            diff = in_r - c_r
            if diff > 0:
                saving = (Decimal(str(e.cached_tokens)) / Decimal("1000000.0")) * diff
                cached_savings_usd += float(saving)

    avg_cost = (total_cost_usd / total_calls) if total_calls > 0 else 0.0
    avg_latency = (sum(e.latency_ms for e in entries) / total_calls) if total_calls > 0 else 0.0

    # Today / Week / Month figures (IST based)
    now_ist_str = to_ist_str(now_utc()).split(" ")[0]
    today_cost = sum(float(e.estimated_cost_usd) for e in entries if e.ist_date == now_ist_str)

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    week_cost = sum(float(e.estimated_cost_usd) for e in entries if e.ist_date >= week_ago)
    month_cost = sum(float(e.estimated_cost_usd) for e in entries if e.ist_date >= month_ago)
    run_rate_30d = (month_cost / 30.0 * 30.0) if month_cost > 0 else (today_cost * 30.0)

    # Time series aggregation
    buckets: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        b_key = e.ist_date
        if granularity.upper() == "MONTHLY":
            b_key = e.ist_date[:7]  # YYYY-MM
        elif granularity.upper() == "WEEKLY":
            try:
                dt = datetime.strptime(e.ist_date, "%Y-%m-%d")
                b_key = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
            except Exception:
                b_key = e.ist_date

        if b_key not in buckets:
            buckets[b_key] = {
                "date_bucket": b_key,
                "calls": 0,
                "tokens": 0,
                "prompt_tokens": 0,
                "output_tokens": 0,
                "cached_tokens": 0,
                "cost_usd": 0.0,
                "cost_inr": 0.0,
            }

        buckets[b_key]["calls"] += 1
        buckets[b_key]["tokens"] += e.total_tokens
        buckets[b_key]["prompt_tokens"] += e.prompt_tokens
        buckets[b_key]["output_tokens"] += e.output_tokens
        buckets[b_key]["cached_tokens"] += e.cached_tokens
        c = float(e.estimated_cost_usd)
        buckets[b_key]["cost_usd"] += c
        buckets[b_key]["cost_inr"] += c * usd_to_inr_rate

    # Sort time series chronologically
    time_series = sorted(buckets.values(), key=lambda x: x["date_bucket"])
    for b in time_series:
        b["cost_usd"] = round(b["cost_usd"], 4)
        b["cost_inr"] = round(b["cost_inr"], 2)

    # By Symbol Breakdown
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        sym = e.symbol or "GLOBAL"
        if sym not in by_symbol:
            by_symbol[sym] = {"symbol": sym, "calls": 0, "tokens": 0, "cost_usd": 0.0, "cost_inr": 0.0}
        by_symbol[sym]["calls"] += 1
        by_symbol[sym]["tokens"] += e.total_tokens
        c = float(e.estimated_cost_usd)
        by_symbol[sym]["cost_usd"] += c
        by_symbol[sym]["cost_inr"] += c * usd_to_inr_rate
    for s in by_symbol.values():
        s["cost_usd"] = round(s["cost_usd"], 4)
        s["cost_inr"] = round(s["cost_inr"], 2)

    # By Model Breakdown
    by_model: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        m = e.model_id
        if m not in by_model:
            by_model[m] = {"model_id": m, "calls": 0, "tokens": 0, "cost_usd": 0.0, "cost_inr": 0.0}
        by_model[m]["calls"] += 1
        by_model[m]["tokens"] += e.total_tokens
        c = float(e.estimated_cost_usd)
        by_model[m]["cost_usd"] += c
        by_model[m]["cost_inr"] += c * usd_to_inr_rate
    for m in by_model.values():
        m["cost_usd"] = round(m["cost_usd"], 4)
        m["cost_inr"] = round(m["cost_inr"], 2)

    # By Purpose Breakdown
    by_purpose: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        p = e.call_purpose
        if p not in by_purpose:
            by_purpose[p] = {"purpose": p, "calls": 0, "tokens": 0, "cost_usd": 0.0, "cost_inr": 0.0}
        by_purpose[p]["calls"] += 1
        by_purpose[p]["tokens"] += e.total_tokens
        c = float(e.estimated_cost_usd)
        by_purpose[p]["cost_usd"] += c
        by_purpose[p]["cost_inr"] += c * usd_to_inr_rate
    for p in by_purpose.values():
        p["cost_usd"] = round(p["cost_usd"], 4)
        p["cost_inr"] = round(p["cost_inr"], 2)

    # Recent 50 calls for tabular ledger
    recent_calls = []
    for e in entries[:50]:
        recent_calls.append({
            "id": e.id,
            "created_at_ist": to_ist_str(e.created_at_utc),
            "ist_date": e.ist_date,
            "account_type": e.account_type,
            "symbol": e.symbol,
            "model_id": e.model_id,
            "call_purpose": e.call_purpose,
            "billing_tier": e.billing_tier,
            "prompt_tokens": e.prompt_tokens,
            "output_tokens": e.output_tokens,
            "thinking_tokens": e.thinking_tokens,
            "cached_tokens": e.cached_tokens,
            "total_tokens": e.total_tokens,
            "estimated_cost_usd": round(float(e.estimated_cost_usd), 6),
            "estimated_cost_inr": round(float(e.estimated_cost_usd) * usd_to_inr_rate, 4),
            "latency_ms": e.latency_ms,
            "http_status": e.http_status,
            "report_id": e.report_id,
        })

    st = db.query(AppSettings).filter_by(id=1).first()
    free_tier_active = bool(st.gemini_use_free_tier) if st else False

    return {
        "status": "SUCCESS",
        "currency": "USD",
        "usd_to_inr_rate": usd_to_inr_rate,
        "free_tier_active": free_tier_active,
        "totals": {
            "total_calls": total_calls,
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_output_tokens": total_output,
            "total_thinking_tokens": total_thinking,
            "total_cached_tokens": total_cached,
            "total_cost_usd": round(total_cost_usd, 4),
            "total_cost_inr": round(total_cost_inr, 2),
            "shadow_paid_usd": round(shadow_paid_usd, 4),
            "shadow_paid_inr": round(shadow_paid_usd * usd_to_inr_rate, 2),
            "cached_savings_usd": round(cached_savings_usd, 4),
            "cached_savings_inr": round(cached_savings_usd * usd_to_inr_rate, 2),
            "avg_cost_per_call_usd": round(avg_cost, 6),
            "avg_latency_ms": round(avg_latency, 1),
            "today_cost_usd": round(today_cost, 4),
            "week_cost_usd": round(week_cost, 4),
            "month_cost_usd": round(month_cost, 4),
            "run_rate_30d_usd": round(run_rate_30d, 2),
        },
        "time_series": time_series,
        "by_symbol": list(by_symbol.values()),
        "by_model": list(by_model.values()),
        "by_purpose": list(by_purpose.values()),
        "recent_calls": recent_calls,
    }


@router.get("/export")
def export_usage_csv(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    model_id: Optional[str] = Query(None),
    call_purpose: Optional[str] = Query(None),
    account_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Export filtered usage records as downloadable CSV spreadsheet."""
    query = db.query(GeminiUsageLedger)
    if account_type:
        query = query.filter(GeminiUsageLedger.account_type == account_type.upper())
    if symbol:
        clean_sym = symbol.rstrip("#")
        query = query.filter(
            (GeminiUsageLedger.symbol == symbol)
            | (GeminiUsageLedger.symbol == clean_sym)
            | (GeminiUsageLedger.symbol == f"{clean_sym}#")
        )
    if model_id:
        clean_m = model_id.replace("models/", "").strip()
        query = query.filter(GeminiUsageLedger.model_id.contains(clean_m))
    if call_purpose:
        query = query.filter(GeminiUsageLedger.call_purpose == call_purpose.upper())
    if start_date:
        query = query.filter(GeminiUsageLedger.ist_date >= start_date)
    if end_date:
        query = query.filter(GeminiUsageLedger.ist_date <= end_date)

    entries = query.order_by(GeminiUsageLedger.created_at_utc.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID",
        "Timestamp (IST)",
        "Date (IST)",
        "Account Type",
        "Symbol",
        "Model ID",
        "Call Purpose",
        "Billing Tier",
        "Prompt Tokens",
        "Output Tokens",
        "Thinking Tokens",
        "Cached Tokens",
        "Total Tokens",
        "Cost (USD)",
        "Latency (ms)",
        "HTTP Status",
        "Report ID",
    ])

    for e in entries:
        writer.writerow([
            e.id,
            to_ist_str(e.created_at_utc),
            e.ist_date,
            e.account_type,
            e.symbol,
            e.model_id,
            e.call_purpose,
            e.billing_tier,
            e.prompt_tokens,
            e.output_tokens,
            e.thinking_tokens,
            e.cached_tokens,
            e.total_tokens,
            f"{float(e.estimated_cost_usd):.6f}",
            e.latency_ms,
            e.http_status,
            e.report_id or "",
        ])

    csv_data = output.getvalue()
    filename = f"gemini_usage_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/rates")
def get_rate_cards(db: Session = Depends(get_db)):
    """Fetch current model pricing rate cards and free tier setting."""
    cards = db.query(GeminiModelRateCard).all()
    st = db.query(AppSettings).filter_by(id=1).first()

    return {
        "status": "SUCCESS",
        "gemini_use_free_tier": bool(st.gemini_use_free_tier) if st else False,
        "rates": [
            {
                "model_id": c.model_id,
                "input_per_1m_usd": float(c.input_per_1m_usd),
                "output_per_1m_usd": float(c.output_per_1m_usd),
                "cached_per_1m_usd": float(c.cached_per_1m_usd),
                "is_free_tier_eligible": c.is_free_tier_eligible,
                "updated_at_utc": c.updated_at_utc.isoformat() if c.updated_at_utc else None,
            }
            for c in cards
        ],
    }


@router.put("/rates")
def update_rate_cards(payload: UpdateRatesPayload, db: Session = Depends(get_db)):
    """Update model rate card prices and free tier toggle."""
    st = db.query(AppSettings).filter_by(id=1).first()
    if payload.gemini_use_free_tier is not None and st:
        st.gemini_use_free_tier = payload.gemini_use_free_tier
        st.updated_at_utc = now_utc()

    if payload.rates:
        for item in payload.rates:
            mid = item.model_id.replace("models/", "").strip()
            rc = db.query(GeminiModelRateCard).filter_by(model_id=mid).first()
            if not rc:
                rc = GeminiModelRateCard(model_id=mid)
                db.add(rc)
            rc.input_per_1m_usd = Decimal(str(item.input_per_1m_usd))
            rc.output_per_1m_usd = Decimal(str(item.output_per_1m_usd))
            rc.cached_per_1m_usd = Decimal(str(item.cached_per_1m_usd))
            rc.is_free_tier_eligible = item.is_free_tier_eligible
            rc.updated_at_utc = now_utc()

    db.commit()
    return {"status": "SUCCESS", "message": "Model rate cards updated successfully"}
