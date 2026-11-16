"""Report Export & Telegram Sharing Routes."""

from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from backend.app.telegram_reports.report_exporter import report_exporter

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])


class ShareTelegramSchema(BaseModel):
    recipient_ids: Optional[List[int]] = None
    format: str = "PDF"  # PDF, EXCEL, CSV
    account_type: Optional[str] = None


@router.get("/export")
def export_report(
    format: str = Query("PDF", description="PDF, EXCEL, or CSV"),
    account_type: Optional[str] = None,
):
    """Download trade performance tear-sheet in PDF, Excel, or CSV format."""
    fmt = format.upper()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    if fmt == "PDF":
        data = report_exporter.generate_pdf_report(account_type)
        media_type = "application/pdf"
        filename = f"Performance_Report_{timestamp}.pdf"
    elif fmt in ("EXCEL", "XLSX"):
        data = report_exporter.generate_excel_report(account_type)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"Performance_Report_{timestamp}.xlsx"
    elif fmt == "CSV":
        data = report_exporter.generate_csv_report(account_type)
        media_type = "text/csv"
        filename = f"Performance_Report_{timestamp}.csv"
    else:
        raise HTTPException(status_code=400, detail="Invalid format. Supported: PDF, EXCEL, CSV")

    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return Response(content=data, media_type=media_type, headers=headers)


@router.post("/share-telegram")
async def share_report_telegram(payload: ShareTelegramSchema):
    """Upload and deliver performance tear-sheet to authorized Telegram recipients."""
    res = await report_exporter.share_report_to_telegram(
        recipient_ids=payload.recipient_ids,
        format_type=payload.format,
        account_type=payload.account_type,
    )
    return res

