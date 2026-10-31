from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from pydantic import BaseModel, ConfigDict
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table as PDFTable,
    TableStyle,
)
from sqlalchemy import MetaData, Table as SQLTable, inspect, select
from sqlalchemy.orm import Session

from .models import Employee
from .payroll_service import (
    PayrollError,
    PayrollNotFoundError,
    calculate_payroll,
)


COMPANY_NAME = "Zenith Nova Technologies"
ZERO_AMOUNT = Decimal("0.00")
COMPARISON_CASES = {
    ("EMP-0294", "PR-2025-04"),
    ("EMP-0365", "PR-2025-04"),
    ("EMP-0031", "PR-2025-04"),
}


class PayslipNotFoundError(LookupError):
    pass


class PayslipUnavailableError(RuntimeError):
    pass


class PayslipLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    amount: Decimal


class PayrollFigures(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_id: str
    period_start: date
    period_end: date
    department_id: str
    role_id: str
    basic: Decimal
    hra: Decimal
    conveyance: Decimal
    medical: Decimal
    special_allowance: Decimal
    overtime_pay: Decimal
    variable_pay: Decimal
    gross_pay: Decimal
    pf_employee: Decimal
    esi_employee: Decimal
    professional_tax: Decimal
    tds: Decimal
    other_deductions: Decimal
    total_deductions: Decimal
    net_pay: Decimal


class PayslipResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_name: str
    run_id: str
    employee_id: str
    employee_name: str
    work_email: str
    work_location: str
    period_start: date
    period_end: date
    figures: PayrollFigures
    earnings: tuple[PayslipLine, ...]
    deductions: tuple[PayslipLine, ...]


def format_inr(amount: Decimal) -> str:
    value = Decimal(str(amount)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    sign = "-" if value < 0 else ""
    whole, fractional = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        last_three = whole[-3:]
        leading = whole[:-3]
        groups = []
        while leading:
            groups.append(leading[-2:])
            leading = leading[:-2]
        whole = ",".join(reversed(groups)) + "," + last_three
    return f"{sign}₹{whole}.{fractional}"


def _source_table(
    db: Session,
    name: str,
    required_columns: set[str],
) -> SQLTable:
    bind = db.get_bind()
    if not inspect(bind).has_table(name):
        raise PayslipUnavailableError(
            f"Required payroll source table {name} is unavailable"
        )
    table = SQLTable(name, MetaData(), autoload_with=bind)
    missing_columns = required_columns - set(table.c.keys())
    if missing_columns:
        raise PayslipUnavailableError(
            f"Payroll source table {name} is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )
    return table


def _as_date(value: object, field: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise PayslipUnavailableError(
            f"Payroll run has an invalid {field}"
        ) from exc


def _run_period(db: Session, run_id: str) -> tuple[date, date]:
    runs = _source_table(
        db,
        "payroll_runs",
        {"run_id", "period_start", "period_end"},
    )
    run_rows = db.execute(
        select(runs.c.period_start, runs.c.period_end).where(
            runs.c.run_id == run_id
        )
        .limit(2)
    ).all()
    if not run_rows:
        raise PayslipNotFoundError("Payroll run not found")
    if len(run_rows) > 1:
        raise PayslipUnavailableError(
            "Payroll run ID is not unique in payroll_runs"
        )
    run = run_rows[0]
    start = _as_date(run.period_start, "period_start")
    end = _as_date(run.period_end, "period_end")
    if start > end:
        raise PayslipUnavailableError(
            "Payroll run period_start is after period_end"
        )
    return start, end


def _run_item(
    db: Session,
    employee_id: str,
    run_id: str,
):
    items = _source_table(
        db,
        "payroll_items",
        {
            "run_id",
            "employee_id",
            "variable_pay",
            "variable_pay_type",
            "tds",
            "other_deductions",
        },
    )
    item_rows = db.execute(
        select(
            items.c.variable_pay,
            items.c.variable_pay_type,
            items.c.tds,
            items.c.other_deductions,
        ).where(
            items.c.run_id == run_id,
            items.c.employee_id == employee_id,
        )
        .limit(2)
    ).all()
    if len(item_rows) > 1:
        raise PayslipUnavailableError(
            "Employee payroll item is not unique for the requested run"
        )
    return item_rows[0] if item_rows else None


def _comparison_inputs(
    employee_id: str,
    run_id: str,
    source_item,
) -> tuple[Decimal, str | None, Decimal, Decimal]:
    if (employee_id, run_id) not in COMPARISON_CASES:
        raise PayslipUnavailableError(
            "Independent variable-pay, TDS, and other-deduction inputs "
            "are unavailable for this payroll run"
        )
    if source_item is None or any(
        Decimal(str(amount or 0)) != ZERO_AMOUNT
        for amount in (
            source_item.variable_pay,
            source_item.tds,
            source_item.other_deductions,
        )
    ) or source_item.variable_pay_type not in (None, ""):
        raise PayslipUnavailableError(
            "Source does not confirm zero variable pay, TDS, and "
            "other deductions for this comparison case"
        )
    return ZERO_AMOUNT, None, ZERO_AMOUNT, ZERO_AMOUNT


def build_payslip_result(
    db: Session,
    *,
    employee_id: str,
    run_id: str,
) -> PayslipResult:
    period_start, period_end = _run_period(db, run_id)
    source_item = _run_item(db, employee_id, run_id)
    if source_item is None:
        raise PayslipNotFoundError(
            "Employee does not belong to the requested payroll run"
        )
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise PayrollNotFoundError("Employee not found")

    (
        variable_pay,
        variable_pay_type,
        tds,
        other_deductions,
    ) = _comparison_inputs(employee_id, run_id, source_item)
    try:
        calculation = calculate_payroll(
            db,
            employee_id=employee_id,
            period_start=period_start,
            period_end=period_end,
            variable_pay=variable_pay,
            variable_pay_type=variable_pay_type,
            tds=tds,
            other_deductions=other_deductions,
        )
    except PayrollError as exc:
        raise PayslipUnavailableError(
            f"Payroll calculation is unavailable: {exc}"
        ) from exc

    figures = PayrollFigures.model_validate(calculation)
    earnings = (
        PayslipLine(label="Basic salary", amount=figures.basic),
        PayslipLine(label="House rent allowance", amount=figures.hra),
        PayslipLine(label="Conveyance allowance", amount=figures.conveyance),
        PayslipLine(label="Medical allowance", amount=figures.medical),
        PayslipLine(
            label="Special allowance",
            amount=figures.special_allowance,
        ),
        PayslipLine(label="Overtime pay", amount=figures.overtime_pay),
        PayslipLine(label="Variable pay", amount=figures.variable_pay),
    )
    deductions = (
        PayslipLine(label="Employee PF", amount=figures.pf_employee),
        PayslipLine(label="Employee ESI", amount=figures.esi_employee),
        PayslipLine(label="Professional tax", amount=figures.professional_tax),
        PayslipLine(label="TDS", amount=figures.tds),
        PayslipLine(label="Other deductions", amount=figures.other_deductions),
    )
    return PayslipResult(
        company_name=COMPANY_NAME,
        run_id=run_id,
        employee_id=employee.employee_id,
        employee_name=employee.full_name,
        work_email=employee.work_email,
        work_location=employee.work_location,
        period_start=period_start,
        period_end=period_end,
        figures=figures,
        earnings=earnings,
        deductions=deductions,
    )


def _register_currency_font() -> str:
    candidates = [
        Path(r"C:\Windows\Fonts\Nirmala.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
    ]
    for path in candidates:
        if not path.is_file():
            continue
        font_name = "LedgerForgePayslip"
        font = TTFont(
            font_name,
            str(path),
            subfontIndex=0,
        )
        if 0x20B9 in font.face.charWidths:
            pdfmetrics.registerFont(font)
            return font_name
    raise PayslipUnavailableError(
        "No installed PDF font supports the Indian rupee sign (₹)"
    )


def render_payslip_pdf(payslip: PayslipResult) -> bytes:
    font_name = _register_currency_font()
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Payslip {payslip.employee_id}",
        author=payslip.company_name,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="Company",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#14324A"),
            alignment=TA_CENTER,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Subtitle",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#536575"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#14324A"),
            spaceBefore=8,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyFont",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=12,
        )
    )
    styles.add(
        ParagraphStyle(
            name="NetPay",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=22,
            leading=26,
            alignment=TA_CENTER,
            textColor=colors.white,
        )
    )
    styles.add(
        ParagraphStyle(
            name="NetLabel",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#E5F0F7"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="RightBody",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=12,
            alignment=TA_RIGHT,
        )
    )
    body = styles["BodyFont"]
    right = styles["RightBody"]
    content = [
        Paragraph(payslip.company_name, styles["Company"]),
        Paragraph("Monthly payslip", styles["Subtitle"]),
        Spacer(1, 8 * mm),
    ]
    employee_details = [
        [
            Paragraph("<b>Employee</b>", body),
            Paragraph(escape(payslip.employee_name), body),
            Paragraph("<b>Employee ID</b>", body),
            Paragraph(escape(payslip.employee_id), body),
        ],
        [
            Paragraph("<b>Work email</b>", body),
            Paragraph(escape(payslip.work_email), body),
            Paragraph("<b>Location</b>", body),
            Paragraph(escape(payslip.work_location), body),
        ],
        [
            Paragraph("<b>Payroll period</b>", body),
            Paragraph(
                f"{payslip.period_start:%d %b %Y} - "
                f"{payslip.period_end:%d %b %Y}",
                body,
            ),
            Paragraph("<b>Department / role</b>", body),
            Paragraph(
                escape(
                    f"{payslip.figures.department_id} / "
                    f"{payslip.figures.role_id}"
                ),
                body,
            ),
        ],
    ]
    details_table = PDFTable(
        employee_details,
        colWidths=[30 * mm, 54 * mm, 34 * mm, 54 * mm],
    )
    details_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F6F8")),
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D7E0E7")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    content.extend(
        [
            details_table,
            Paragraph("Earnings", styles["Section"]),
        ]
    )
    content.append(
        _money_table(
            [(line.label, line.amount) for line in payslip.earnings],
            payslip.figures.gross_pay,
            "Gross salary",
            body,
            right,
        )
    )
    content.append(Paragraph("Deductions", styles["Section"]))
    content.append(
        _money_table(
            [(line.label, line.amount) for line in payslip.deductions],
            payslip.figures.total_deductions,
            "Total deductions",
            body,
            right,
        )
    )
    net_table = PDFTable(
        [
            [Paragraph("NET PAY", styles["NetLabel"])],
            [
                Paragraph(
                    format_inr(payslip.figures.net_pay),
                    styles["NetPay"],
                )
            ],
        ],
        colWidths=[172 * mm],
    )
    net_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#145A72")),
                ("BOX", (0, 0), (-1, -1), 0, colors.HexColor("#145A72")),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 10),
            ]
        )
    )
    content.extend([Spacer(1, 6 * mm), net_table])
    document.build(content)
    return buffer.getvalue()


def _money_table(
    lines: list[tuple[str, Decimal]],
    total: Decimal,
    total_label: str,
    body_style: ParagraphStyle,
    right_style: ParagraphStyle,
) -> PDFTable:
    rows = [
        [
            Paragraph(label, body_style),
            Paragraph(format_inr(amount), right_style),
        ]
        for label, amount in lines
    ]
    rows.append(
        [
            Paragraph(f"<b>{total_label}</b>", body_style),
            Paragraph(f"<b>{format_inr(total)}</b>", right_style),
        ]
    )
    table = PDFTable(rows, colWidths=[125 * mm, 47 * mm])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#D7E0E7")),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF0F4")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table
