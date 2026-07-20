"""Exportación del journal de operaciones a PDF."""
import datetime
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


def build_pdf(path, trades, stats, title="BacktestICT — Journal de Operaciones"):
    """Genera un PDF con el resumen de estadísticas y la tabla de operaciones."""
    doc = SimpleDocTemplate(
        path, pagesize=landscape(A4),
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, spaceAfter=4*mm)
    subtitle_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9,
                                     textColor=colors.grey, spaceAfter=6*mm)

    stat_header_style = ParagraphStyle("StatH", parent=styles["Normal"], fontSize=8,
                                        textColor=colors.grey, alignment=TA_CENTER)
    stat_value_style = ParagraphStyle("StatV", parent=styles["Normal"], fontSize=16,
                                       alignment=TA_CENTER, spaceAfter=3*mm)

    elements = []

    # ── header ──
    elements.append(Paragraph(title, title_style))
    elements.append(Paragraph(
        f"Exportado el {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')} — {stats.get('total', 0)} operaciones",
        subtitle_style
    ))
    elements.append(Spacer(1, 3*mm))

    # ── stats cards ──
    def stat_table(fields):
        data = [[Paragraph(label, stat_header_style) for label, _ in fields]]
        data.append([Paragraph(value, stat_value_style) for _, value in fields])
        table = Table(data, colWidths=[doc.width / len(fields)] * len(fields))
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e222d")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#d1d4dc")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#2a2e39")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#3a3e49")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, 1), 8),
            ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ]))
        return table

    stat_fields = [
        ("Total", str(stats.get("total", 0))),
        ("Ganadas", str(stats.get("wins", 0))),
        ("Perdidas", str(stats.get("losses", 0))),
        ("Winrate", f"{stats.get('winrate', 0):.1f}%"),
        ("Suma R", f"{stats.get('sum_r', 0):.2f}R"),
        ("Expectancy", f"{stats.get('expectancy', 0):.2f}R"),
    ]
    elements.append(stat_table(stat_fields))
    elements.append(Spacer(1, 3*mm))

    # Estadísticas avanzadas (profit factor, Sharpe por-trade, rachas, mejor/peor
    # R) — ver core/stats.py. Solo se agregan si vienen en `stats` (compatibilidad
    # con quien llame a build_pdf sin pasarlas).
    if "profit_factor" in stats:
        pf = stats.get("profit_factor", 0)
        adv_fields = [
            ("Profit Factor", "∞" if pf == float("inf") else f"{pf:.2f}"),
            ("Sharpe", f"{stats.get('sharpe', 0):.2f}"),
            ("Racha Ganadora", str(stats.get("max_win_streak", 0))),
            ("Racha Perdedora", str(stats.get("max_loss_streak", 0))),
            ("Mejor R", f"{stats.get('best_r', 0):.2f}R"),
            ("Peor R", f"{stats.get('worst_r', 0):.2f}R"),
        ]
        elements.append(stat_table(adv_fields))
    elements.append(Spacer(1, 6*mm))

    # ── trades table ──
    if trades:
        headers = ["Fecha Entrada", "Símbolo", "Dir", "Entrada", "SL", "TP", "Salida", "Resultado", "R", "P&L"]
        header_style = ParagraphStyle("Th", parent=styles["Normal"], fontSize=7,
                                       textColor=colors.white, alignment=TA_CENTER)
        cell_style = ParagraphStyle("Td", parent=styles["Normal"], fontSize=7,
                                     alignment=TA_CENTER, spaceAfter=0, leading=9)

        col_widths = [30*mm, 18*mm, 10*mm, 18*mm, 18*mm, 18*mm, 18*mm, 16*mm, 12*mm, 18*mm]

        rows = [[Paragraph(h, header_style) for h in headers]]
        for t in trades:
            result = t.get("result", "")
            r_val = t.get("r", 0)
            pnl = t.get("pnl", 0)
            row = [
                Paragraph(str(t.get("entry_time", "")), cell_style),
                Paragraph(str(t.get("symbol", "")), cell_style),
                Paragraph("Buy" if t.get("dir") == "buy" else "Sell", cell_style),
                Paragraph(str(t.get("entry", "")), cell_style),
                Paragraph(str(t.get("sl", "")), cell_style),
                Paragraph(str(t.get("tp", "")), cell_style),
                Paragraph(str(t.get("exit", "")), cell_style),
                Paragraph(result, cell_style),
                Paragraph(f"{r_val:.2f}R", cell_style),
                Paragraph(f"{pnl:+.2f}", cell_style),
            ]
            rows.append(row)

        trade_table = Table(rows, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e222d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#3a3e49")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ]
        for i, t in enumerate(trades):
            row_idx = i + 1
            result = t.get("result", "")
            if result == "Ganada":
                style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#1a2e2a")))
                style_cmds.append(("TEXTCOLOR", (7, row_idx), (7, row_idx), colors.HexColor("#26a69a")))
            elif result == "Perdida":
                style_cmds.append(("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#2e1a1a")))
                style_cmds.append(("TEXTCOLOR", (7, row_idx), (7, row_idx), colors.HexColor("#ef5350")))

        trade_table.setStyle(TableStyle(style_cmds))
        elements.append(trade_table)

    doc.build(elements)
