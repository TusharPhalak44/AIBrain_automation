"""Trade & Fee-Adjusted PnL Report Exporter (CSV, XLSX, and PDF Tear-Sheets)."""

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from backend.app.core.clock_sync import to_ist_str, now_utc
from backend.app.db.session import SessionLocal
from backend.app.db.models import TradeLedger, TelegramRecipient
from backend.app.ai_brain.instruments import INSTRUMENT_UNIVERSE

logger = logging.getLogger(__name__)


def _format_price_for_export(val: Any, symbol: str) -> str:
    if val is None or str(val).strip() in ("", "0", "0.0", "None"):
        return ""
    try:
        spec = INSTRUMENT_UNIVERSE.get(symbol) or INSTRUMENT_UNIVERSE.get(f"{symbol}#") or INSTRUMENT_UNIVERSE.get(symbol.rstrip("#"))
        digits = spec.digits if spec else 2
        return f"{float(val):.{digits}f}"
    except Exception:
        return str(val)


class ReportExporter:
    """Exports performance tear-sheets and shares them directly via Telegram."""

    @staticmethod
    def _fetch_trades(account_type: Optional[str] = None, session: Optional[Any] = None) -> List[TradeLedger]:
        """Fetch trades from TradeLedger."""
        if session is not None:
            query = session.query(TradeLedger)
            if account_type:
                query = query.filter(TradeLedger.account_type == account_type.upper())
            return query.order_by(TradeLedger.opened_at_utc.desc()).all()

        with SessionLocal() as db:
            query = db.query(TradeLedger)
            if account_type:
                query = query.filter(TradeLedger.account_type == account_type.upper())
            return query.order_by(TradeLedger.opened_at_utc.desc()).all()

    def generate_csv_report(self, account_type: Optional[str] = None, session: Optional[Any] = None) -> bytes:
        """Generate CSV performance report with IST timestamps."""
        trades = self._fetch_trades(account_type, session=session)
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            "Trade ID",
            "Account Type",
            "Position ID",
            "Symbol",
            "Mode",
            "Direction",
            "Status",
            "Lots",
            "Entry Price",
            "Exit Price",
            "SL",
            "TP1",
            "Gross PnL ($)",
            "Commission ($)",
            "Swap ($)",
            "Net PnL ($)",
            "R-Multiple",
            "Exit Reason",
            "Opened At (IST)",
            "Closed At (IST)",
        ])

        for t in trades:
            sym = t.symbol or ""
            writer.writerow([
                t.id,
                t.account_type,
                t.position_id,
                sym,
                t.mode,
                t.direction,
                t.status,
                float(t.lots),
                _format_price_for_export(t.entry_price, sym),
                _format_price_for_export(t.exit_price, sym),
                _format_price_for_export(t.sl, sym),
                _format_price_for_export(t.tp1, sym),
                float(t.gross_pnl),
                float(t.commission),
                float(t.swap),
                float(t.net_pnl),
                float(t.r_multiple) if t.r_multiple else "",
                t.exit_reason or "",
                to_ist_str(t.opened_at_utc),
                to_ist_str(t.closed_at_utc) if t.closed_at_utc else "",
            ])

        return output.getvalue().encode("utf-8")

    def generate_excel_report(self, account_type: Optional[str] = None, session: Optional[Any] = None) -> bytes:
        """Generate styled Excel (.xlsx) workbook with summary metrics."""
        trades = self._fetch_trades(account_type, session=session)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Trade Ledger"

        # Headers
        headers = [
            "ID", "Account", "Position ID", "Symbol", "Mode", "Direction",
            "Status", "Lots", "Entry", "Exit", "SL", "TP1",
            "Gross PnL", "Commission", "Swap", "Net PnL", "R:R",
            "Exit Reason", "Opened (IST)", "Closed (IST)"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")

        for t in trades:
            ws.append([
                t.id,
                t.account_type,
                t.position_id,
                t.symbol,
                t.mode,
                t.direction,
                t.status,
                float(t.lots),
                float(t.entry_price),
                float(t.exit_price) if t.exit_price else "-",
                float(t.sl),
                float(t.tp1),
                float(t.gross_pnl),
                float(t.commission),
                float(t.swap),
                float(t.net_pnl),
                float(t.r_multiple) if t.r_multiple else "-",
                t.exit_reason or "-",
                to_ist_str(t.opened_at_utc),
                to_ist_str(t.closed_at_utc) if t.closed_at_utc else "-",
            ])

        # Auto-adjust column width
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = max(max_len + 3, 11)

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def generate_pdf_report(self, account_type: Optional[str] = None, session: Optional[Any] = None) -> bytes:
        """Generate high-density institutional PDF performance tear-sheet."""
        trades = self._fetch_trades(account_type, session=session)
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()

        elements = []

        # Title
        title_style = ParagraphStyle(
            name="TitleStyle",
            parent=styles["Heading1"],
            fontSize=18,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=6,
        )
        elements.append(Paragraph("XM Global MT5 Performance Tear-Sheet", title_style))

        # Subtitle
        sub_style = ParagraphStyle(
            name="SubStyle",
            parent=styles["Normal"],
            fontSize=10,
            textColor=colors.HexColor("#64748b"),
            spaceAfter=14,
        )
        elements.append(Paragraph(f"Generated at: {to_ist_str(now_utc())} | Scope: {account_type or 'ALL ACCOUNTS'}", sub_style))

        # Metrics aggregation
        total_trades = len(trades)
        closed_trades = [t for t in trades if t.status == "CLOSED"]
        gross_pnl = sum(float(t.gross_pnl) for t in closed_trades)
        commission = sum(float(t.commission) for t in closed_trades)
        swap = sum(float(t.swap) for t in closed_trades)
        net_pnl = sum(float(t.net_pnl) for t in closed_trades)
        wins = [t for t in closed_trades if float(t.net_pnl) > 0]
        win_rate = (len(wins) / len(closed_trades) * 100.0) if closed_trades else 0.0

        summary_data = [
            ["Metric", "Value", "Metric", "Value"],
            ["Total Trades", str(total_trades), "Win Rate %", f"{win_rate:.1f}%"],
            ["Gross PnL", f"${gross_pnl:.2f}", "Total Commission", f"${commission:.2f}"],
            ["Total Swap", f"${swap:.2f}", "Net Realized PnL", f"${net_pnl:.2f}"],
        ]
        t_summary = Table(summary_data, colWidths=[130, 140, 130, 140])
        t_summary.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1e293b")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ]))
        elements.append(t_summary)
        elements.append(Spacer(1, 14))

        # Recent Trades Table
        elements.append(Paragraph("Recent Executions", styles["Heading3"]))
        trade_rows = [["ID", "Symbol", "Mode", "Dir", "Lots", "Entry", "Exit", "Net PnL", "Exit Reason"]]
        for t in trades[:15]:
            pnl_val = float(t.net_pnl)
            trade_rows.append([
                str(t.id),
                t.symbol,
                t.mode,
                t.direction,
                f"{float(t.lots):.2f}",
                _format_price_for_export(t.entry_price, t.symbol),
                _format_price_for_export(t.exit_price, t.symbol) if t.exit_price else "-",
                f"${pnl_val:.2f}",
                t.exit_reason or "-",
            ])

        t_trades = Table(trade_rows, colWidths=[30, 75, 55, 45, 45, 65, 65, 75, 85])
        t_trades.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("ALIGN", (4, 1), (7, -1), "RIGHT"),
        ]))
        elements.append(t_trades)

        doc.build(elements)
        return buffer.getvalue()

    async def share_report_to_telegram(
        self,
        recipient_ids: Optional[List[int]] = None,
        format_type: str = "PDF",
        account_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate report and upload to selected Telegram recipients."""
        from backend.app.telegram_reports.telegram_bot import telegram_service

        fmt = format_type.upper()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")

        if fmt == "PDF":
            data = self.generate_pdf_report(account_type)
            filename = f"Performance_Report_{timestamp}.pdf"
        elif fmt in ("EXCEL", "XLSX"):
            data = self.generate_excel_report(account_type)
            filename = f"Performance_Report_{timestamp}.xlsx"
        else:
            data = self.generate_csv_report(account_type)
            filename = f"Performance_Report_{timestamp}.csv"

        with SessionLocal() as db:
            query = db.query(TelegramRecipient).filter(
                TelegramRecipient.is_active.is_(True),
                TelegramRecipient.chat_id.isnot(None),
            )
            if recipient_ids:
                query = query.filter(TelegramRecipient.id.in_(recipient_ids))
            recipients = query.all()

        sent_count = 0
        for r in recipients:
            if r.chat_id:
                ok = await telegram_service.send_document(
                    r.chat_id,
                    data,
                    filename,
                    caption=f"📈 <b>Performance Report ({fmt})</b>\n{to_ist_str(now_utc())}",
                )
                if ok:
                    sent_count += 1

        return {
            "format": fmt,
            "filename": filename,
            "recipients_contacted": sent_count,
            "total_target_recipients": len(recipients),
        }


report_exporter = ReportExporter()
