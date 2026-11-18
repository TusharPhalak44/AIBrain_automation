"""Gemini API Token & Cost Accounting Engine."""

from datetime import datetime, timezone
from decimal import Decimal
import logging
from typing import Any, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.db.models import GeminiModelRateCard, GeminiUsageLedger, AppSettings
from backend.app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Default fallback rates per 1,000,000 tokens in USD
DEFAULT_RATES: Dict[str, Tuple[Decimal, Decimal, Decimal, bool]] = {
    # model_id: (input_rate, output_rate, cached_rate, is_free_tier_eligible)
    "gemini-3.8-flash": (Decimal("0.75"), Decimal("3.75"), Decimal("0.075"), True),
    "gemini-3.6-flash": (Decimal("0.50"), Decimal("3.00"), Decimal("0.05"), True),
    "gemini-3-flash-preview": (Decimal("0.50"), Decimal("3.00"), Decimal("0.05"), True),
    "gemini-3.5-flash-lite": (Decimal("0.30"), Decimal("2.50"), Decimal("0.03"), True),
    "gemini-3.1-pro-preview": (Decimal("2.00"), Decimal("12.00"), Decimal("0.20"), False),
    "gemini-4-argon": (Decimal("2.00"), Decimal("10.00"), Decimal("0.10"), False),
}


def get_model_rate_card(model_id: str, db: Optional[Session] = None) -> Tuple[Decimal, Decimal, Decimal, bool]:
    """Retrieve rate card for model_id from database or hardcoded defaults."""
    clean_id = model_id.replace("models/", "").strip()
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        rc = db.query(GeminiModelRateCard).filter_by(model_id=clean_id).first()
        if rc:
            return (
                Decimal(str(rc.input_per_1m_usd)),
                Decimal(str(rc.output_per_1m_usd)),
                Decimal(str(rc.cached_per_1m_usd)),
                bool(rc.is_free_tier_eligible),
            )
    except Exception as e:
        logger.debug(f"Could not load rate card from DB: {e}")
    finally:
        if close_db:
            db.close()

    # Fallback to default rates or standard flash rates
    if clean_id in DEFAULT_RATES:
        return DEFAULT_RATES[clean_id]
    for key, val in DEFAULT_RATES.items():
        if key in clean_id or clean_id in key:
            return val
    # Generic baseline
    return (Decimal("0.75"), Decimal("3.75"), Decimal("0.075"), True)


def calculate_cost(
    prompt_tokens: int,
    output_tokens: int,
    thinking_tokens: int,
    cached_tokens: int,
    input_rate: Decimal,
    output_rate: Decimal,
    cached_rate: Decimal,
) -> Decimal:
    """Exact USD cost calculation according to Google Gemini pricing formulas."""
    uncached_prompt = max(0, prompt_tokens - cached_tokens)
    input_cost = (Decimal(str(uncached_prompt)) / Decimal("1000000.0")) * input_rate
    cached_cost = (Decimal(str(cached_tokens)) / Decimal("1000000.0")) * cached_rate
    output_cost = (Decimal(str(output_tokens + thinking_tokens)) / Decimal("1000000.0")) * output_rate
    total = input_cost + cached_cost + output_cost
    return total.quantize(Decimal("0.000001"))


def record_gemini_usage(
    db: Optional[Session],
    model_id: str,
    call_purpose: str,  # LIVE_SCAN, MANUAL_SCAN, SL_FORENSICS, RULE_VALIDATION, KEY_TEST
    response: Any,
    latency_ms: int = 0,
    symbol: str = "GLOBAL",
    account_type: str = "DEMO",
    report_id: Optional[int] = None,
    http_status: int = 200,
    force_free_tier: Optional[bool] = None,
) -> Optional[GeminiUsageLedger]:
    """Capture token usage metadata from Gemini API response and persist in GeminiUsageLedger."""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        clean_model = model_id.replace("models/", "").strip()
        in_r, out_r, c_r, free_elig = get_model_rate_card(clean_model, db=db)

        # Extract tokens from usage_metadata (official google-genai response object)
        prompt_tokens = 0
        output_tokens = 0
        thinking_tokens = 0
        cached_tokens = 0
        total_tokens = 0

        if hasattr(response, "usage_metadata") and response.usage_metadata is not None:
            um = response.usage_metadata
            prompt_tokens = int(getattr(um, "prompt_token_count", 0) or 0)
            output_tokens = int(getattr(um, "candidates_token_count", 0) or 0)
            thinking_tokens = int(getattr(um, "thoughts_token_count", 0) or 0)
            cached_tokens = int(getattr(um, "cached_content_token_count", 0) or 0)
            total_tokens = int(getattr(um, "total_token_count", 0) or (prompt_tokens + output_tokens + thinking_tokens))
        elif isinstance(response, dict):
            # Dict fallback if mock or dict response
            prompt_tokens = int(response.get("prompt_token_count", response.get("prompt_tokens", 0)))
            output_tokens = int(response.get("candidates_token_count", response.get("output_tokens", 0)))
            thinking_tokens = int(response.get("thoughts_token_count", response.get("thinking_tokens", 0)))
            cached_tokens = int(response.get("cached_content_token_count", response.get("cached_tokens", 0)))
            total_tokens = int(response.get("total_token_count", response.get("total_tokens", prompt_tokens + output_tokens + thinking_tokens)))

        # Determine billing tier
        is_free_tier = False
        if force_free_tier is not None:
            is_free_tier = force_free_tier
        else:
            st = db.query(AppSettings).filter_by(id=1).first()
            if st and st.gemini_use_free_tier and free_elig:
                is_free_tier = True

        billing_tier = "FREE" if is_free_tier else "PAID"

        # Compute calculated cost
        actual_cost = calculate_cost(
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cached_tokens=cached_tokens,
            input_rate=in_r,
            output_rate=out_r,
            cached_rate=c_r,
        )

        cost_to_record = Decimal("0.000000") if is_free_tier else actual_cost

        utc_now = now_utc()
        ist_str = to_ist_str(utc_now)
        # Format IST date as YYYY-MM-DD
        ist_date = ist_str.split(" ")[0] if " " in ist_str else utc_now.strftime("%Y-%m-%d")

        ledger_entry = GeminiUsageLedger(
            created_at_utc=utc_now,
            ist_date=ist_date,
            account_type=account_type.upper(),
            symbol=symbol,
            model_id=clean_model,
            call_purpose=call_purpose,
            billing_tier=billing_tier,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost_to_record,
            latency_ms=latency_ms,
            http_status=http_status,
            report_id=report_id,
        )
        db.add(ledger_entry)
        db.commit()
        db.refresh(ledger_entry)
        logger.info(
            f"Logged Gemini usage #{ledger_entry.id} ({clean_model} for {call_purpose}): "
            f"{total_tokens} tokens, ${cost_to_record} ({billing_tier})"
        )
        return ledger_entry
    except Exception as e:
        logger.error(f"Failed to record Gemini usage in ledger: {e}", exc_info=True)
        return None
    finally:
        if close_db:
            db.close()

