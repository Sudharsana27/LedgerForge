import json
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
AUDIT_SUMMARY = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "phase3"
    / "payroll_component_audit_summary.json"
)


OUTPUT = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "phase3"
    / "Python_Sudharsana_Phase3_Report.pdf"
)


def build_report() -> None:
    with AUDIT_SUMMARY.open(encoding="utf-8") as source:
        audit = json.load(source)
    rounding_cases = ", ".join(
        f"{row['employee_id']}/{row['run_id']} "
        f"{row['calculated']} vs {row['reference']}"
        for row in audit["overtime_rounding_difference_rows"]
    )
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
        canvas.drawRightString(192 * mm, 9 * mm, f"Page {document.page}")
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
            "Git tag: phase-3 (retained) | 7 November 2026",
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
                    paragraph("Partial component audit", "TableSmall"),
                    paragraph(
                        f"{audit['fixed_component_reference_matches']}/"
                        f"{audit['fixed_component_rows_calculated']} fixed "
                        f"matches; {audit['overtime_pay_reference_matches']}/"
                        f"{audit['overtime_pay_calculated_rows']} overtime "
                        f"matches; {audit['unresolved_esi_conflict_rows']} "
                        "ESI conflicts; one attendance row unavailable. "
                        "Not a complete Check 2 pass.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("11 - Expenses", "TableSmall"),
                    paragraph(
                        "Completed and independently verified",
                        "TableSmall",
                    ),
                    paragraph(
                        "501 bills, 18 months; monthly and vendor-month "
                        "totals match; workflow tests pass.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("12 - Payroll", "TableSmall"),
                    paragraph(
                        "Partially completed",
                        "TableSmall",
                    ),
                    paragraph(
                        "Lifecycle, idempotency, posting and reversal tested; "
                        "complete Check 2 remains blocked; separate partial "
                        "component audit generated.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("13 - Security", "TableSmall"),
                    paragraph(
                        "Implemented but not independently verified",
                        "TableSmall",
                    ),
                    paragraph(
                        "64-byte local key; 30-minute login and route tested; "
                        "source users have no passwords.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("14 - Tax", "TableSmall"),
                    paragraph(
                        "Partially completed",
                        "TableSmall",
                    ),
                    paragraph(
                        "Audited effective versions; 54/54 monthly sums match "
                        "reference records; policy is sample data.",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("15 - Reports", "TableSmall"),
                    paragraph(
                        "Completed and independently verified",
                        "TableSmall",
                    ),
                    paragraph(
                        "5/5 official checks; trial balance 40 accounts, "
                        "0 mismatches; balance sheet balances.",
                        "TableSmall",
                    ),
                ],
            ],
            colWidths=[27 * mm, 48 * mm, 99 * mm],
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
            "only ADMIN may version tax configuration. Cross-employee "
            "payslip access is HR-only. A generated 64-byte secret is stored "
            "only in the ignored local .env. Login with that key returned "
            "200, a 1,800-second token, and 200 on a protected route. "
            "Automated tests cover missing/weak keys, 401/403, role isolation, "
            "and inactive-user revocation. Source users have no passwords.",
        ),
        paragraph("Payroll lifecycle", "Section"),
        paragraph(
            "Runs transition DRAFT -> PROCESSED -> APPROVED -> PAID. Processing "
            "recalculates saved items through the earlier payroll engine; "
            "approval links its balanced journal atomically and enforces "
            "separation of duties. Repeated approval, payment, and reversal "
            "do not duplicate postings. Reversal entries offset both payroll "
            "and recorded payment journals.",
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
            "records instead of rewriting previously saved payroll. Admin "
            "routes now version tax parameters and statutory rates with "
            "audit history. TDS uses configured slabs, deduction, rebate "
            "threshold, and cess; configuration changes and restoration are "
            "tested. PF, ESI, and TDS monthly report totals match the stored "
            "reference payroll items in 54/54 month/type checks. This checks "
            "report summation, not legal correctness: source rules are "
            "explicitly training samples.",
        ),
        paragraph("Source-data constraints", "Section"),
        paragraph(
            "The supplied data has 18 payroll runs and 7,340 items but no "
            "independent payroll_inputs.csv. The independent batch validator "
            "processed 7,340 eligible employee/run rows and skipped all "
            "7,340 for the same reason: missing independent variable-pay, "
            "TDS, and other-deduction inputs. The official Check 2 found "
            "0/7,340 result rows; no payroll match is claimed. A separate "
            "source-only partial audit reconstructs fixed components for "
            f"{audit['fixed_component_rows_calculated']}/"
            f"{audit['source_employee_run_rows']} employee/run rows and "
            f"attendance-dependent values for "
            f"{audit['lop_source_rows_calculated']} rows; "
            f"{audit['attendance_unavailable_rows']} row is unavailable "
            "because attendance is missing.",
        ),
        paragraph(
            "<b>PARTIAL RECONCILIATION — NOT A COMPLETE CHECK 2 PASS.</b> "
            f"Overtime pay matches {audit['overtime_pay_reference_matches']}/"
            f"{audit['overtime_pay_calculated_rows']} calculable rows; the "
            f"{len(audit['overtime_rounding_difference_rows'])} explicit "
            f"HALF_UP/reference one-paisa differences are {rounding_cases}. "
            f"PF employee/employer matches are "
            f"{audit['pf_employee_reference_matches']}/"
            f"{audit['pf_employee_calculated_rows']} and "
            f"{audit['pf_employer_reference_matches']}/"
            f"{audit['pf_employer_calculated_rows']}; these use sample rates. "
            f"{audit['unresolved_esi_conflict_rows']} ESI rows remain "
            "unresolved source-data conflicts. No variable pay, TDS, other "
            "deductions, complete gross, or net pay is claimed.",
        ),
        paragraph(
            "Tax and statutory rate rows are explicitly marked sample or "
            "training data. The existing source also documents conflicting "
            "ESI eligibility and two one-paisa overtime rounding differences. "
            "The calculation engine preserves its explicit input and rate "
            "rules; it does not alter historical values to force a match.",
        ),
        paragraph(
            "<b>Permissions:</b> Admin manages operations and tax versions; "
            "HR has organization-wide HR/finance/report access; employees "
            "access their own records; public access is limited to health "
            "and login. Admin tax changes are tested as 201; HR/employee "
            "changes as 403.",
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
                    paragraph("181 passed; 1 warning", "TableSmall"),
                ],
                [
                    paragraph("Independent payroll Check 2", "TableSmall"),
                    paragraph(
                        "0/7,340 found; 7,340 skipped for missing independent "
                        "inputs; not a pass",
                        "TableSmall",
                    ),
                ],
                [
                    paragraph("Monthly statutory report sums", "TableSmall"),
                    paragraph(
                        "PF, ESI, TDS: 54/54 matches to source-item totals; "
                        "not statutory policy validation",
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
                        "Backed up; upgraded a390f1b6d2e8 → d1e4a6b8c0f2; "
                        "source row counts preserved; integrity OK",
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
            "The original phase-3 tag is unchanged. The additive audit "
            "migration is d1e4a6b8c0f2; a fresh SQLite upgrade and the backed "
            "up local database both reached head. Existing payroll, journal, "
            "and tax source row counts were preserved; integrity_check=ok.",
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
            "Payroll inputs are incomplete, so the 7,340 Check 2 skips are "
            "reported rather than filled with reference values. Tax and "
            "statutory sources are sample-only; report matches are limited "
            "to stored totals. A verified backup preceded the audit migration. "
            "A weak local JWT key was rotated without printing or committing "
            "the replacement.",
        ),
        paragraph("Learning and Phase 4", "Section"),
        paragraph(
            "I learned to separate authorization from employee ownership, "
            "and to make journal operations atomic and idempotent.<br/>"
            "I learned that effective-dated settings need append-only audit "
            "history and must preserve saved payroll.<br/>"
            "Reconciliation must use independent inputs; reference outputs "
            "cannot stand in for missing calculation inputs.<br/>"
            "Phase 4: obtain approved payroll/tax sources, then harden "
            "deployment, monitoring, backups, and recovery.",
        ),
    ]

    document.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build_report()
