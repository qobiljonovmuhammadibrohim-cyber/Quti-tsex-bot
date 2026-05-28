"""
pdf_reports.py — PDF hisobotlar generatsiyasi
ReportLab orqali professional PDF lar yaratish.
"""
import logging
from io import BytesIO
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend

from sqlalchemy import select, func, case as sa_case
import sqlalchemy.sql.functions as sf
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    User, UserRole, WorkEntry, WorkStatus, WorkType,
    Penalty, Advance, WarehouseProduct,
)

logger = logging.getLogger(__name__)


# ═══ STYLE ════════════════════════════════════════════════════════════════════

COLOR_PRIMARY    = colors.HexColor("#6366f1")
COLOR_SECONDARY  = colors.HexColor("#8b5cf6")
COLOR_SUCCESS    = colors.HexColor("#10b981")
COLOR_WARNING    = colors.HexColor("#f59e0b")
COLOR_DANGER     = colors.HexColor("#ef4444")
COLOR_DARK       = colors.HexColor("#1e293b")
COLOR_LIGHT      = colors.HexColor("#f8fafc")
COLOR_MUTED      = colors.HexColor("#64748b")


def _fmt(n):
    try: return f"{int(float(n)):,}".replace(",", " ")
    except: return str(n)


def _build_styles():
    """Style dictionary."""
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "Title", parent=styles["Heading1"],
        fontSize=22, textColor=COLOR_DARK,
        alignment=TA_CENTER, spaceAfter=10, leading=28,
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=11, textColor=COLOR_MUTED,
        alignment=TA_CENTER, spaceAfter=14,
    )
    section_style = ParagraphStyle(
        "Section", parent=styles["Heading2"],
        fontSize=14, textColor=COLOR_PRIMARY,
        spaceBefore=14, spaceAfter=8,
    )
    normal_style = ParagraphStyle(
        "Normal2", parent=styles["Normal"],
        fontSize=10, textColor=COLOR_DARK,
    )
    small_style = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=8, textColor=COLOR_MUTED,
        alignment=TA_CENTER,
    )

    return {
        "title":    title_style,
        "subtitle": subtitle_style,
        "section":  section_style,
        "normal":   normal_style,
        "small":    small_style,
    }


def _make_kpi_table(items: List[tuple]) -> Table:
    """KPI kartochkalar jadvali. items: [(label, value, color), ...]"""
    n_cols = len(items)
    data = [[Paragraph(f"<b>{label}</b>", ParagraphStyle("L", fontSize=9, textColor=COLOR_MUTED, alignment=TA_CENTER))
             for label, _, _ in items]]
    data.append([Paragraph(f"<b>{value}</b>", ParagraphStyle("V", fontSize=16, textColor=clr, alignment=TA_CENTER))
                 for _, value, clr in items])

    t = Table(data, colWidths=[(17*cm)/n_cols] * n_cols)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_LIGHT),
        ("BOX",        (0, 0), (-1, -1), 0.5, COLOR_PRIMARY),
        ("INNERGRID",  (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _make_data_table(headers: List[str], rows: List[list], col_widths: List[float] = None) -> Table:
    """Standart ma'lumotlar jadvali."""
    table_data = [[Paragraph(f"<b>{h}</b>", ParagraphStyle("H", fontSize=10, textColor=colors.white))
                   for h in headers]]
    for row in rows:
        cells = []
        for cell in row:
            if isinstance(cell, (int, float)):
                cells.append(Paragraph(_fmt(cell), ParagraphStyle("C", fontSize=9, alignment=TA_RIGHT)))
            else:
                cells.append(Paragraph(str(cell), ParagraphStyle("C", fontSize=9)))
        table_data.append(cells)

    if col_widths is None:
        col_widths = [17*cm / len(headers)] * len(headers)

    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TEXTCOLOR",      (0, 0), (-1, 0), colors.white),
        ("ALIGN",          (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING",  (0, 0), (-1, 0), 8),
        ("TOPPADDING",     (0, 0), (-1, 0), 8),
        ("BACKGROUND",     (0, 1), (-1, -1), COLOR_LIGHT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COLOR_LIGHT]),
        ("GRID",           (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 1), (-1, -1), 4),
    ]))
    return t


def _make_bar_chart(labels: List[str], values: List[float], title: str = "") -> Drawing:
    """Bar chart yaratish."""
    drawing = Drawing(17*cm, 6*cm)
    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 30
    chart.height = 5*cm - 20
    chart.width  = 17*cm - 60
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.fontSize = 7
    chart.categoryAxis.labels.angle = 30
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = COLOR_PRIMARY
    chart.bars.strokeColor = None
    drawing.add(chart)
    return drawing


def _make_pie_chart(labels: List[str], values: List[float]) -> Drawing:
    """Pie chart."""
    drawing = Drawing(15*cm, 7*cm)
    pie = Pie()
    pie.x = 50
    pie.y = 20
    pie.width  = 5*cm
    pie.height = 5*cm
    pie.data = values
    pie.labels = labels
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    pie_colors = [
        COLOR_PRIMARY, COLOR_SECONDARY, COLOR_SUCCESS,
        COLOR_WARNING, COLOR_DANGER, colors.HexColor("#06b6d4"),
        colors.HexColor("#84cc16"), colors.HexColor("#f97316"),
    ]
    for i, c in enumerate(pie_colors):
        if i < len(values):
            pie.slices[i].fillColor = c
    drawing.add(pie)

    legend = Legend()
    legend.x = 9*cm
    legend.y = 6*cm
    legend.deltay = 12
    legend.colorNamePairs = [(pie_colors[i % len(pie_colors)], labels[i]) for i in range(len(labels))]
    legend.fontSize = 8
    drawing.add(legend)

    return drawing


def _page_footer(canvas, doc):
    """Har sahifa pastida footer."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(COLOR_MUTED)
    page_num = canvas.getPageNumber()
    canvas.drawCentredString(A4[0] / 2, 1*cm, f"— {page_num} — | Quti Tsexi | {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    canvas.restoreState()


# ═══ HISOBOTLAR ════════════════════════════════════════════════════════════════

async def generate_daily_report_pdf(db: AsyncSession, report_date: date) -> bytes:
    """Kunlik hisobot PDF."""
    s = _build_styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    # Ma'lumotlar
    r_kpi = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
            func.count(func.distinct(WorkEntry.worker_id)),
        ).where(WorkEntry.work_date == report_date)
    )
    kpi = r_kpi.one()
    total, total_inc = int(kpi[0] or 0), float(kpi[1] or 0)
    ok, rej, workers_n = int(kpi[2] or 0), int(kpi[3] or 0), int(kpi[4] or 0)

    # Ishchilar
    r_workers = await db.execute(
        select(
            User.full_name,
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(
            WorkEntry.work_date == report_date,
            WorkEntry.status == WorkStatus.approved,
        )
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
    )
    workers_data = r_workers.all()

    # Ish turlari
    r_types = await db.execute(
        select(
            WorkEntry.work_type,
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        )
        .where(
            WorkEntry.work_date == report_date,
            WorkEntry.status == WorkStatus.approved,
        )
        .group_by(WorkEntry.work_type)
        .order_by(func.count(WorkEntry.id).desc())
    )
    types_data = r_types.all()

    # Hujjat tarkibi
    story = []

    # Title
    story.append(Paragraph("KUNLIK HISOBOT", s["title"]))
    story.append(Paragraph(report_date.strftime("%d.%m.%Y — %A"), s["subtitle"]))
    story.append(Spacer(1, 10))

    # KPI
    kpi_items = [
        ("Daromad",    _fmt(total_inc) + " so\'m", COLOR_SUCCESS),
        ("Ishlar",     str(total),                  COLOR_PRIMARY),
        ("Qabul",      str(ok),                     COLOR_SUCCESS),
        ("Rad",        str(rej),                    COLOR_DANGER),
        ("Ishchilar",  str(workers_n),              COLOR_SECONDARY),
    ]
    story.append(_make_kpi_table(kpi_items))
    story.append(Spacer(1, 14))

    # Ishchilar bo'limi
    if workers_data:
        story.append(Paragraph("Ishchilar bo\'yicha", s["section"]))
        rows = [[i+1, w[0], w[1], _fmt(w[2]) + " so\'m"] for i, w in enumerate(workers_data)]
        story.append(_make_data_table(
            ["#", "Ishchi", "Ish soni", "Daromad"],
            rows,
            [1*cm, 8*cm, 3*cm, 5*cm],
        ))
        story.append(Spacer(1, 14))

    # Ish turlari
    if types_data:
        story.append(Paragraph("Ish turlari bo\'yicha", s["section"]))
        rows = [[(t[0].value if t[0] else "?").replace("_", " ").title(), t[1], _fmt(t[2]) + " so\'m"]
                for t in types_data]
        story.append(_make_data_table(
            ["Ish turi", "Soni", "Daromad"],
            rows,
            [8*cm, 4*cm, 5*cm],
        ))

        # Bar chart
        story.append(Spacer(1, 10))
        story.append(Paragraph("Diagramma", s["section"]))
        chart_labels = [(t[0].value if t[0] else "?")[:12] for t in types_data[:10]]
        chart_values = [int(t[1]) for t in types_data[:10]]
        story.append(_make_bar_chart(chart_labels, chart_values, "Ish turlari soni"))

    # Build
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


async def generate_monthly_report_pdf(db: AsyncSession, year: int, month: int) -> bytes:
    """Oylik hisobot PDF."""
    s = _build_styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date   = date(year, month, last_day)

    # Umumiy KPI
    r_kpi = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
        ).where(
            WorkEntry.work_date >= start_date,
            WorkEntry.work_date <= end_date,
        )
    )
    kpi = r_kpi.one()
    total = int(kpi[0] or 0)
    inc   = float(kpi[1] or 0)
    ok    = int(kpi[2] or 0)
    rej   = int(kpi[3] or 0)

    # Jami jarima
    r_pen = await db.execute(
        select(func.coalesce(func.sum(Penalty.summa), 0))
        .where(
            func.extract('month', Penalty.created_at) == month,
            func.extract('year', Penalty.created_at) == year,
        )
    )
    total_penalty = float(r_pen.scalar() or 0)

    # Jami avans
    r_adv = await db.execute(
        select(func.coalesce(func.sum(Advance.summa), 0))
        .where(Advance.oy == month, Advance.yil == year)
    )
    total_advance = float(r_adv.scalar() or 0)

    # Ishchilar
    r_workers = await db.execute(
        select(
            User.full_name,
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        )
        .join(WorkEntry, WorkEntry.worker_id == User.id)
        .where(
            WorkEntry.work_date >= start_date,
            WorkEntry.work_date <= end_date,
            WorkEntry.status == WorkStatus.approved,
        )
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
    )
    workers_data = r_workers.all()

    # Kunlar bo'yicha trend (top 20)
    r_daily = await db.execute(
        select(
            WorkEntry.work_date,
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        )
        .where(
            WorkEntry.work_date >= start_date,
            WorkEntry.work_date <= end_date,
            WorkEntry.status == WorkStatus.approved,
        )
        .group_by(WorkEntry.work_date)
        .order_by(WorkEntry.work_date)
    )
    daily_data = r_daily.all()

    story = []
    month_name = ["", "Yanvar","Fevral","Mart","Aprel","May","Iyun",
                  "Iyul","Avgust","Sentabr","Oktabr","Noyabr","Dekabr"][month]

    story.append(Paragraph("OYLIK HISOBOT", s["title"]))
    story.append(Paragraph(f"{month_name} {year}", s["subtitle"]))
    story.append(Spacer(1, 10))

    # KPI
    kpi_items = [
        ("Daromad",  _fmt(inc) + " so\'m",            COLOR_SUCCESS),
        ("Ishlar",   str(total),                       COLOR_PRIMARY),
        ("Qabul",    str(ok),                          COLOR_SUCCESS),
        ("Rad",      str(rej),                         COLOR_DANGER),
        ("Jarima",   "-" + _fmt(total_penalty),         COLOR_DANGER),
        ("Avans",    "-" + _fmt(total_advance),         COLOR_WARNING),
    ]
    story.append(_make_kpi_table(kpi_items))
    story.append(Spacer(1, 14))

    # Ishchilar
    if workers_data:
        story.append(Paragraph("TOP ishchilar", s["section"]))
        rows = []
        for i, w in enumerate(workers_data[:30]):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else str(i+1)))
            rows.append([medal, w[0], w[1], _fmt(w[2]) + " so\'m"])
        story.append(_make_data_table(
            ["#", "Ishchi", "Ish soni", "Daromad"],
            rows,
            [1*cm, 8*cm, 3*cm, 5*cm],
        ))
        story.append(Spacer(1, 14))

    # Daily trend chart
    if daily_data and len(daily_data) > 1:
        story.append(Paragraph("Kunlik daromad trendi", s["section"]))
        chart_labels = [d[0].strftime("%d") for d in daily_data]
        chart_values = [float(d[1]) for d in daily_data]
        story.append(_make_bar_chart(chart_labels, chart_values))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


async def generate_worker_report_pdf(db: AsyncSession, worker_id: int, year: int, month: int) -> bytes:
    """Ishchi shaxsiy hisobot PDF."""
    s = _build_styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date   = date(year, month, last_day)

    worker = await db.get(User, worker_id)
    if not worker:
        raise ValueError(f"Worker {worker_id} not found")

    # Statistika
    r_kpi = await db.execute(
        select(
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.approved, 1), else_=0)),
            sf.sum(sa_case((WorkEntry.status == WorkStatus.rejected, 1), else_=0)),
        ).where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.work_date >= start_date,
            WorkEntry.work_date <= end_date,
        )
    )
    kpi = r_kpi.one()
    total = int(kpi[0] or 0)
    inc   = float(kpi[1] or 0)
    ok    = int(kpi[2] or 0)
    rej   = int(kpi[3] or 0)

    # Jarima
    r_pen = await db.execute(
        select(Penalty).where(
            Penalty.worker_id == worker_id,
            func.extract('month', Penalty.created_at) == month,
            func.extract('year', Penalty.created_at) == year,
        )
    )
    penalties = r_pen.scalars().all()
    total_pen = sum(float(p.summa) for p in penalties)

    # Avans
    r_adv = await db.execute(
        select(Advance).where(
            Advance.worker_id == worker_id,
            Advance.oy == month, Advance.yil == year,
        )
    )
    advances = r_adv.scalars().all()
    total_adv = sum(float(a.summa) for a in advances)

    sof_maosh = inc - total_pen - total_adv

    # Ish turlari
    r_types = await db.execute(
        select(
            WorkEntry.work_type,
            func.count(WorkEntry.id),
            func.coalesce(func.sum(WorkEntry.jami_summa), 0),
        )
        .where(
            WorkEntry.worker_id == worker_id,
            WorkEntry.work_date >= start_date,
            WorkEntry.work_date <= end_date,
            WorkEntry.status == WorkStatus.approved,
        )
        .group_by(WorkEntry.work_type)
        .order_by(func.coalesce(func.sum(WorkEntry.jami_summa), 0).desc())
    )
    types_data = r_types.all()

    story = []
    month_name = ["", "Yanvar","Fevral","Mart","Aprel","May","Iyun",
                  "Iyul","Avgust","Sentabr","Oktabr","Noyabr","Dekabr"][month]

    story.append(Paragraph(f"ISHCHI HISOBOTI", s["title"]))
    story.append(Paragraph(f"{worker.full_name} — {month_name} {year}", s["subtitle"]))
    story.append(Spacer(1, 10))

    # KPI cards
    kpi_items = [
        ("Sof maosh",  _fmt(sof_maosh) + " so\'m", COLOR_SUCCESS),
        ("Daromad",    _fmt(inc) + " so\'m",       COLOR_PRIMARY),
        ("Ishlar",     str(total),                  COLOR_SECONDARY),
    ]
    story.append(_make_kpi_table(kpi_items))
    story.append(Spacer(1, 10))

    kpi_items2 = [
        ("Qabul qilingan", str(ok),                       COLOR_SUCCESS),
        ("Rad etilgan",    str(rej),                      COLOR_DANGER),
        ("Jarima",         "-" + _fmt(total_pen),         COLOR_DANGER),
        ("Avans",          "-" + _fmt(total_adv),         COLOR_WARNING),
    ]
    story.append(_make_kpi_table(kpi_items2))
    story.append(Spacer(1, 14))

    # Ish turlari
    if types_data:
        story.append(Paragraph("Ish turlari bo\'yicha", s["section"]))
        rows = [[(t[0].value if t[0] else "?").replace("_", " ").title(),
                 t[1], _fmt(t[2]) + " so\'m"] for t in types_data]
        story.append(_make_data_table(
            ["Ish turi", "Soni", "Daromad"],
            rows,
            [8*cm, 4*cm, 5*cm],
        ))
        story.append(Spacer(1, 14))

    # Jarimalar tafsiloti
    if penalties:
        story.append(Paragraph("Jarimalar tafsiloti", s["section"]))
        rows = [[(p.created_at.strftime('%d.%m.%Y') if p.created_at else "—"),
                 p.sabab[:50], _fmt(p.summa)] for p in penalties]
        story.append(_make_data_table(
            ["Sana", "Sabab", "Miqdor"],
            rows,
            [3*cm, 9*cm, 5*cm],
        ))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes


async def generate_warehouse_report_pdf(db: AsyncSession) -> bytes:
    """Ombor hisoboti PDF."""
    s = _build_styles()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    r = await db.execute(
        select(WarehouseProduct)
        .where(WarehouseProduct.is_active == True)
        .order_by(WarehouseProduct.category, WarehouseProduct.miqdor.asc())
    )
    products = r.scalars().all()

    # Kategoriyalar bo'yicha guruhlash
    cats = {}
    for p in products:
        cn = p.category.value if p.category else "?"
        cats.setdefault(cn, []).append(p)

    # Kam qolganlar
    low_stock = [p for p in products if p.miqdor <= (p.min_threshold or 0)]

    story = []
    story.append(Paragraph("OMBOR HISOBOTI", s["title"]))
    story.append(Paragraph(datetime.now().strftime("%d.%m.%Y %H:%M"), s["subtitle"]))
    story.append(Spacer(1, 10))

    # KPI
    kpi_items = [
        ("Jami mahsulot",    str(len(products)),                 COLOR_PRIMARY),
        ("Kategoriyalar",    str(len(cats)),                     COLOR_SECONDARY),
        ("Kam qolgan",       str(len(low_stock)),                COLOR_DANGER),
    ]
    story.append(_make_kpi_table(kpi_items))
    story.append(Spacer(1, 14))

    # Kam qolganlar (priority)
    if low_stock:
        story.append(Paragraph("Kam qolgan mahsulotlar", s["section"]))
        rows = []
        for p in low_stock[:20]:
            name = p.name
            if p.razmer: name += f" | {p.razmer}"
            if p.rang:   name += f" | {p.rang}"
            rows.append([name, f"{p.miqdor:.0f} {p.birlik or 'dona'}",
                         f"{p.min_threshold or 0:.0f}"])
        story.append(_make_data_table(
            ["Mahsulot", "Qoldi", "Min"],
            rows,
            [10*cm, 4*cm, 3*cm],
        ))
        story.append(Spacer(1, 14))

    # Har kategoriya
    for cat_name, items in cats.items():
        story.append(Paragraph(cat_name.replace("_", " ").title(), s["section"]))
        rows = []
        for p in items[:50]:
            name = p.name
            if p.razmer: name += f" | {p.razmer}"
            rows.append([name, f"{p.miqdor:.0f} {p.birlik or 'dona'}",
                         p.rang or "—"])
        story.append(_make_data_table(
            ["Mahsulot", "Qoldi", "Rang"],
            rows,
            [10*cm, 4*cm, 3*cm],
        ))
        story.append(Spacer(1, 10))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes
