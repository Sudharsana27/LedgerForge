from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "phase3"
    / "Python_Sudharsana_Phase3_Report.pdf"
)


def build_report() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#17324D"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#1F5A7A"),
            spaceBefore=5,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodySmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="TableSmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
        )
    )

    def paragraph(text: str, style: str = "BodySmall") -> Paragraph:
        return Paragraph(text, styles[style])

    def footer(canvas, document) -> None:
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D4DEE6"))
        canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#526777"))
        canvas.drawString(18 * mm, 9 * mm, "LedgerForge | Phase 3")
        canvas.drawRightString(
            192 * mm, 9 * mm, f"Page {document.page} of 3"
        )
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title="LedgerForge Phase 3 Submission Report",
        author="LedgerForge",
    )

    story = [
        paragraph("LedgerForge - Phase 3 Submission Report", "ReportTitle"),
        paragraph(
            "Sudharsana | Python Track | LedgerForge | Phase 3 - Connected System",
            "BodySmall",
        ),
        paragraph(
            'Repository: <link href="https://github.com/Sudharsana27/LedgerForge" '
            'color="blue">github.com/Sudharsana27/LedgerForge</link> | '
            "Git tag: phase-3 | 23 October 2026",
            "BodySmall",
        ),
        paragraph("Executive summary", "Section"),
        paragraph(
            "Phase 3 extends the existing FastAPI and SQLAlchemy ledger with "
            "authenticated access, auditable payroll and expense workflows, "
            "versioned tax configuration, and financial statements. Earlier "
            "employee, salary, attendance, leave, payroll-calculation, "
            "payslip, invoicing, and double-entry ledger behavior remains "
            "covered by regression tests.",
        ),
        paragraph("Five-task completion status", "Section"),
        Table(
            [
                [
                    paragraph("<b>Task</b>", "TableSmall"),
                    paragraph("<b>Status</b>", "TableSmall"),
                    paragraph("<b>Evidence / limitation</b>", "TableSmall"),
                ],
                [
                    paragraph("11 - Expenses", "TableSmall"),
                    paragraph(
                        "Complete",
                        "TableSmall",
                    ),
                    paragraph(
                        "501 source bills reconcile; approval, duplicate, "
                        "and payment tests pass.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("12 - Payroll", "TableSmall"),
                    paragraph(
                        "Partial",
                        "TableSmall",
                    ),
                    paragraph(
                        "Lifecycle / posting / reversal tests pass; "
                        "independent Check 2 is blocked by missing inputs.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("13 - Security", "TableSmall"),
                    paragraph(
                        "Implemented",
                        "TableSmall",
                    ),
                    paragraph(
                        "JWT, role isolation, expiry, inactive-user tests; "
                        "local secret must be strengthened.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("14 - Tax", "TableSmall"),
                    paragraph(
                        "Partial",
                        "TableSmall",
                    ),
                    paragraph(
                        "Versioning, audit, TDS and PF/ESI reports tested; "
                        "source rates are training samples.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("15 - Reports", "TableSmall"),
                    paragraph("Complete", "TableSmall"),
                    paragraph(
                        "Official trial balance: 40 accounts, 0 mismatches; "
                        "P&L matches and balance-sheet difference is 0.00.",
                        "TableSmall",
                    ),
                ],
            ],
            colWidths=[31 * mm, 23 * mm, 120 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F5")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C4D0D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        paragraph("Authentication and authorization", "Section"),
        paragraph(
            "API access uses 30-minute signed bearer tokens. Password hashes "
            "are verified with bcrypt, user activation is checked on every "
            "request, and employee-facing routes enforce record ownership. "
            "ADMIN and HR roles protect operational and financial surfaces; "
            "only ADMIN may version tax slabs. Cross-employee payslip access "
            "is HR-only. Login is disabled until a unique SECRET_KEY of at "
            "least 32 bytes is configured. The source user CSV has no "
            "credentials, so passwords are provisioned interactively with "
            "scripts/set_user_password.py and are never committed.",
        ),
        paragraph("Payroll lifecycle", "Section"),
        paragraph(
            "Payroll runs are created as DRAFT from explicit per-employee "
            "variable-pay, TDS, and other-deduction inputs. Idempotency keys "
            "are bound to saved request contents; processing replays each "
            "item through the calculation engine and checks run totals. "
            "Approval and its journal posting are atomic and require a "
            "different user from the run creator. Payment records net-pay "
            "disbursement; reversal creates balanced reversal entries for "
            "both the payroll posting and any recorded payment. Repeated "
            "posting, payment, and reversal operations are idempotent.",
        ),
        PageBreak(),
        paragraph("Financial, expense, and tax controls", "ReportTitle"),
        paragraph("Expense workflow", "Section"),
        paragraph(
            "Expense bills progress through SUBMITTED, APPROVED, and PAID. "
            "The workflow prevents self-approval, detects duplicate vendor / "
            "reference / date / amount combinations, validates posting "
            "accounts, and records balanced accrual and settlement journals. "
            "Spend reconciliation compares monthly and vendor-month totals "
            "against the supplied expenses.csv source.",
        ),
        paragraph("Financial reporting", "Section"),
        paragraph(
            "Trial balance, profit-and-loss, and balance-sheet reports include "
            "posted journal activity only. Contra-asset normal balances and "
            "unclosed current-period profit are represented so the balance "
            "sheet remains balanced. The trial-balance export is formatted "
            "for comparison by the official LedgerForge checker.",
        ),
        paragraph("Tax and statutory reporting", "Section"),
        paragraph(
            "Tax slab changes create new effective-dated versions and audit "
            "records instead of rewriting previously saved payroll. TDS "
            "estimates use configured slabs, rebate threshold, deduction, "
            "and cess. Statutory reports sum saved payroll items for the "
            "selected period. The API flags sample/training tax data; these "
            "figures are not approved production tax policy or tax advice.",
        ),
        paragraph("Source-data constraints", "Section"),
        paragraph(
            "The supplied data has 18 payroll runs and 7,340 items but no "
            "independent payroll_inputs.csv. The independent batch validator "
            "therefore processed 7,340 rows, skipped all 7,340 for missing "
            "variable-pay / TDS / other-deduction inputs, and calculated "
            "zero successful comparisons. Reusing the reference payroll "
            "totals as calculated output would not be an independent check "
            "and was deliberately avoided.",
        ),
        paragraph(
            "Tax and statutory rate rows are explicitly marked sample or "
            "training data. The existing source also documents conflicting "
            "ESI eligibility and two one-paisa overtime rounding differences. "
            "The calculation engine preserves its explicit input and rate "
            "rules; it does not alter historical values to force a match.",
        ),
        paragraph("Role-permission summary", "Section"),
        Table(
            [
                [
                    paragraph("<b>Role</b>", "TableSmall"),
                    paragraph("<b>Permitted scope</b>", "TableSmall"),
                ],
                [
                    paragraph("Admin", "TableSmall"),
                    paragraph(
                        "Employee/finance/payroll operations, reports, and "
                        "tax configuration; own payslip only.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("HR", "TableSmall"),
                    paragraph(
                        "Organization employee/payroll/finance records, "
                        "reports, and payslips.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("Employee", "TableSmall"),
                    paragraph(
                        "Own employee, salary, attendance, leave, and "
                        "payslip records only.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("Public", "TableSmall"),
                    paragraph("Health check and login only.", "TableSmall"),
                ],
            ],
            colWidths=[30 * mm, 144 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F5")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C4D0D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            ),
        ),
        PageBreak(),
        paragraph("Validation and release record", "ReportTitle"),
        paragraph("Automated and official checks", "Section"),
        Table(
            [
                [
                    paragraph("<b>Validation</b>", "TableSmall"),
                    paragraph("<b>Result</b>", "TableSmall"),
                ],
                [
                    paragraph("Pytest regression + Phase 3", "TableSmall"),
                    paragraph("177 passed; 1 warning", "TableSmall"),
                ],
                [
                    paragraph("Workflow and tax coverage", "TableSmall"),
                    paragraph(
                        "Payroll journal posting, payment and reversal; "
                        "historical payroll preservation; PF/ESI/TDS reports",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("Official source checks", "TableSmall"),
                    paragraph("5/5 passed", "TableSmall"),
                ],
                [
                    paragraph("Official trial balance", "TableSmall"),
                    paragraph("40 accounts; 0 mismatches", "TableSmall"),
                ],
                [
                    paragraph("Expense reconciliation", "TableSmall"),
                    paragraph(
                        "501 bills, 18 months; 0 monthly or "
                        "vendor-month mismatches",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("Migration", "TableSmall"),
                    paragraph(
                        "Seeded database backed up, adopted at e7c2d10f4b39, "
                        "upgraded to a390f1b6d2e8; SQLite integrity check OK",
                        "TableSmall",
                    ),
                ],
            ],
            colWidths=[54 * mm, 120 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F5")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C4D0D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            ),
        ),
        paragraph("Official vs. LedgerForge totals", "Section"),
        Table(
            [
                [
                    paragraph("<b>Measure</b>", "TableSmall"),
                    paragraph("<b>Official</b>", "TableSmall"),
                    paragraph("<b>LedgerForge</b>", "TableSmall"),
                ],
                [
                    paragraph("Revenue", "TableSmall"),
                    paragraph("1,260,930,052.00", "TableSmall"),
                    paragraph("1,260,930,052.00", "TableSmall"),
                ],
                [
                    paragraph("Expenses", "TableSmall"),
                    paragraph("1,036,246,464.42", "TableSmall"),
                    paragraph("1,036,246,464.42", "TableSmall"),
                ],
                [
                    paragraph("Profit", "TableSmall"),
                    paragraph("224,683,587.58", "TableSmall"),
                    paragraph("224,683,587.58", "TableSmall"),
                ],
            ],
            colWidths=[40 * mm, 67 * mm, 67 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0F5")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#C4D0D8")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            ),
        ),
        paragraph(
            "Official payroll summary: 18 runs; employer cost "
            "861,586,392.42. Balance sheet at 2026-09-30: assets "
            "463,762,958.65; liabilities 77,499,607.07; equity "
            "161,579,764.00; current profit 224,683,587.58; difference 0.00.",
        ),
        paragraph("Operational notes", "Section"),
        paragraph(
            "The additive Phase 3 migration is revision a390f1b6d2e8. Fresh "
            "databases use alembic upgrade head. The supplied seeded SQLite "
            "database had a stale legacy Alembic marker; its schema was "
            "verified and backed up before stamping the known baseline and "
            "applying the additive migration. Downgrade is intentionally "
            "blocked to protect financial history and credentials.",
        ),
        paragraph(
            "Before enabling login, configure a strong local SECRET_KEY and "
            "provision active users with the interactive password utility. "
            "Before treating tax or historical payroll as production-ready, "
            "obtain approved statutory policy and independent payroll input "
            "records. All supplied company data is fictional training data.",
        ),
        paragraph("Problems and resolutions", "Section"),
        paragraph(
            "The seeded database had a stale migration marker and older "
            "columns. A verified backup, schema preflight, safe baseline "
            "stamp, and additive migration preserved its data. Missing "
            "independent payroll inputs caused the 7,340 rows to be reported "
            "as skipped rather than filled with invented amounts. The "
            "configured JWT secret is 25 bytes; authentication correctly "
            "fails closed until it is rotated to at least 32 bytes.",
        ),
        paragraph("Learning and Phase 4", "Section"),
        paragraph(
            "Phase 3 applied least-privilege authorization and separated "
            "payroll/expense approval from posting. It reinforced the value "
            "of atomic, idempotent journal operations and effective-dated "
            "configuration. Reconciliation must use independent inputs, not "
            "reference results. Phase 4 should add approved payroll inputs "
            "and statutory policy, then harden deployment, monitoring, "
            "backups, and operational recovery.",
        ),
    ]

    document.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build_report()
