
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .database import Base


class Department(Base):
    __tablename__ = "departments"

    department_id: Mapped[str] = mapped_column(
        String(10), primary_key=True
    )
    department_name: Mapped[str] = mapped_column(String(100))
    cost_center: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )


class Role(Base):
    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(
        String(10), primary_key=True
    )
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id"), nullable=False
    )
    role_title: Mapped[str] = mapped_column(String(150))
    level: Mapped[int] = mapped_column(Integer)
    grade: Mapped[str] = mapped_column(String(50))
    band_min_annual: Mapped[int] = mapped_column(Integer)
    band_mid_annual: Mapped[int] = mapped_column(Integer)
    band_max_annual: Mapped[int] = mapped_column(Integer)
    overtime_eligible: Mapped[str] = mapped_column(String(1))
    band_year: Mapped[int] = mapped_column(Integer)


class Employee(Base):
    __tablename__ = "employees"

    employee_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(200))
    work_email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False
    )
    gender: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    date_of_birth: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    hire_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    employment_status: Mapped[str] = mapped_column(String(30))
    employment_type: Mapped[str] = mapped_column(String(30))

    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.role_id"), nullable=False
    )
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=True
    )

    work_location: Mapped[str] = mapped_column(String(100))
    work_mode: Mapped[str] = mapped_column(String(30))
    highest_education: Mapped[str | None] = mapped_column(
        String(150), nullable=True
    )
    prior_experience_years: Mapped[float | None] = mapped_column(
        nullable=True
    )
    career_gap_months: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    commute_distance_km: Mapped[float | None] = mapped_column(
        nullable=True
    )
    pf_applicable: Mapped[str] = mapped_column(String(1))
    esi_applicable: Mapped[str] = mapped_column(String(1))
    notice_period_days: Mapped[int] = mapped_column(Integer)
    resignation_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    exit_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    exit_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True
    )
    created_at: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )


class EmployeeAssignment(Base):
    __tablename__ = "employee_assignments"

    assignment_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    effective_to: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id"), nullable=False
    )
    role_id: Mapped[str] = mapped_column(
        ForeignKey("roles.role_id"), nullable=False
    )
    job_level: Mapped[int] = mapped_column(Integer)
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=True
    )
    change_reason: Mapped[str] = mapped_column(String(100))


Index("ix_employees_department_id", Employee.department_id)
Index("ix_employees_manager_id", Employee.manager_id)


class SalaryComponent(Base):
    __tablename__ = "salary_components"

    component_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    component_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    component_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    taxable: Mapped[str] = mapped_column(
        String(1), nullable=False
    )
    calculation_rule: Mapped[str] = mapped_column(
        String(200), nullable=False
    )
    is_fixed: Mapped[str] = mapped_column(
        String(1), nullable=False
    )


class SalaryRevision(Base):
    __tablename__ = "salary_revisions"

    revision_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False, index=True
    )
    revision_reason: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    previous_annual_fixed: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    new_annual_fixed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    pct_change: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 3), nullable=True
    )
    role_id_after: Mapped[str] = mapped_column(
        ForeignKey("roles.role_id"), nullable=False
    )
    approved_by: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False
    )


class SalaryStructure(Base):
    __tablename__ = "salary_structures"

    structure_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=False
    )
    component_id: Mapped[str] = mapped_column(
        ForeignKey("salary_components.component_id"), nullable=False
    )
    component_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    component_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    monthly_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(
        Date, nullable=False
    )
    effective_to: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("salary_revisions.revision_id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_salary_structure_employee_dates",
            "employee_id", "effective_from", "effective_to",
        ),
    )


class Attendance(Base):
    __tablename__ = "attendance"

    attendance_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=False
    )
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False)
    weekday: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    leave_type_code: Mapped[str | None] = mapped_column(
        ForeignKey("leave_types.leave_type_code"), nullable=True
    )
    check_in: Mapped[str | None] = mapped_column(String(5), nullable=True)
    check_out: Mapped[str | None] = mapped_column(String(5), nullable=True)
    hours_worked: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2), nullable=True
    )
    overtime_hours: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 2), nullable=True
    )
    late_flag: Mapped[str | None] = mapped_column(String(1), nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    data_quality_flag: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id"), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_attendance_employee_date",
            "employee_id",
            "attendance_date",
        ),
    )


class LeaveType(Base):
    __tablename__ = "leave_types"

    leave_type_code: Mapped[str] = mapped_column(
        String(10), primary_key=True
    )
    leave_type_name: Mapped[str] = mapped_column(String(100), nullable=False)
    pay_type: Mapped[str] = mapped_column(String(20), nullable=False)
    annual_quota_days: Mapped[int] = mapped_column(Integer, nullable=False)
    prorated_for_joiners: Mapped[str] = mapped_column(
        String(1), nullable=False
    )
    carry_forward_allowed: Mapped[str] = mapped_column(
        String(1), nullable=False
    )
    max_carry_forward_days: Mapped[int] = mapped_column(
        Integer, nullable=False
    )
    policy_note: Mapped[str] = mapped_column(String(300), nullable=False)


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    leave_request_id: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=False
    )
    leave_type_code: Mapped[str] = mapped_column(
        ForeignKey("leave_types.leave_type_code"), nullable=False
    )
    entitlement_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    applied_on: Mapped[date] = mapped_column(Date, nullable=False)
    approver_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.employee_id"), nullable=True
    )
    decided_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "end_date >= start_date",
            name="ck_leave_request_date_range",
        ),
        Index(
            "ix_leave_requests_employee_dates",
            "employee_id",
            "start_date",
            "end_date",
        ),
        Index("ix_leave_requests_status", "status"),
    )


class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.employee_id"), primary_key=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    financial_year: Mapped[str] = mapped_column(
        String(20), primary_key=True
    )
    cl_entitlement: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    cl_used: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    cl_balance: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    sl_entitlement: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    sl_used: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    sl_balance: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    el_used_fy: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    el_balance: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )
    pending_days: Mapped[Decimal] = mapped_column(
        Numeric(7, 2), nullable=False
    )


class Holiday(Base):
    __tablename__ = "holidays"

    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    holiday_name: Mapped[str] = mapped_column(String(150), nullable=False)
    holiday_type: Mapped[str] = mapped_column(String(30), nullable=False)
    weekday: Mapped[str] = mapped_column(String(15), nullable=False)
    falls_on_weekend: Mapped[str] = mapped_column(String(1), nullable=False)
    calendar_note: Mapped[str] = mapped_column(String(300), nullable=False)


class ChartOfAccount(Base):
    __tablename__ = "chart_of_accounts"

    account_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    account_name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    normal_balance: Mapped[str] = mapped_column(String(10), nullable=False)
    parent_code: Mapped[str | None] = mapped_column(
        ForeignKey("chart_of_accounts.account_code", ondelete="RESTRICT"),
        nullable=True,
    )
    is_group: Mapped[str] = mapped_column(String(1), nullable=False)
    statement: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[str] = mapped_column(String(1), nullable=False)

    parent: Mapped["ChartOfAccount | None"] = relationship(
        back_populates="children",
        remote_side="ChartOfAccount.account_code",
    )
    children: Mapped[list["ChartOfAccount"]] = relationship(
        back_populates="parent"
    )

    __table_args__ = (
        CheckConstraint(
            "account_type IN "
            "('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')",
            name="ck_chart_of_accounts_type",
        ),
        CheckConstraint(
            "normal_balance IN ('DEBIT', 'CREDIT')",
            name="ck_chart_of_accounts_normal_balance",
        ),
        CheckConstraint(
            "is_group IN ('Y', 'N')",
            name="ck_chart_of_accounts_is_group",
        ),
        CheckConstraint(
            "is_active IN ('Y', 'N')",
            name="ck_chart_of_accounts_is_active",
        ),
        Index("ix_chart_of_accounts_parent_code", "parent_code"),
    )


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    entry_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    posting_period: Mapped[str] = mapped_column(String(20), nullable=False)
    financial_year: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_debit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    total_credit: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    reversal_of_source_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="entry",
        order_by="JournalLine.line_no",
    )

    __table_args__ = (
        CheckConstraint(
            "total_debit = total_credit",
            name="ck_journal_entries_balanced_totals",
        ),
        Index("ix_journal_entries_entry_date", "entry_date"),
    )


class JournalLine(Base):
    __tablename__ = "journal_lines"

    line_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    entry_id: Mapped[str] = mapped_column(
        ForeignKey("journal_entries.entry_id", ondelete="RESTRICT"),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    account_code: Mapped[str] = mapped_column(
        ForeignKey("chart_of_accounts.account_code", ondelete="RESTRICT"),
        nullable=False,
    )
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cost_center_department_id: Mapped[str | None] = mapped_column(
        ForeignKey("departments.department_id", ondelete="RESTRICT"),
        nullable=True,
    )
    line_description: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )

    entry: Mapped[JournalEntry] = relationship(back_populates="lines")
    account: Mapped[ChartOfAccount] = relationship()

    __table_args__ = (
        CheckConstraint("line_no > 0", name="ck_journal_lines_positive_number"),
        CheckConstraint(
            "debit >= 0 AND credit >= 0",
            name="ck_journal_lines_nonnegative_amounts",
        ),
        CheckConstraint(
            "(debit > 0 AND credit = 0) OR "
            "(credit > 0 AND debit = 0)",
            name="ck_journal_lines_one_sided_amount",
        ),
        UniqueConstraint(
            "entry_id", "line_no", name="uq_journal_lines_entry_line_no"
        ),
        Index("ix_journal_lines_entry_id", "entry_id"),
        Index("ix_journal_lines_account_code", "account_code"),
    )


class Client(Base):
    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    client_name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state_or_region: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    client_type: Mapped[str] = mapped_column(String(20), nullable=False)
    gst_registration: Mapped[str | None] = mapped_column(
        String(30), nullable=True
    )
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_behaviour: Mapped[str] = mapped_column(String(30), nullable=False)
    primary_service_line: Mapped[str] = mapped_column(
        ForeignKey(
            "chart_of_accounts.account_code",
            name="fk_clients_primary_service_line_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    onboarded_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[str] = mapped_column(String(1), nullable=False)

    primary_service_account: Mapped[ChartOfAccount] = relationship()
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="client"
    )

    __table_args__ = (
        CheckConstraint(
            "client_type IN ('DOMESTIC', 'EXPORT')",
            name="ck_clients_client_type",
        ),
        CheckConstraint(
            "payment_terms_days >= 0",
            name="ck_clients_nonnegative_payment_terms",
        ),
        CheckConstraint(
            "is_active IN ('Y', 'N')",
            name="ck_clients_is_active",
        ),
        Index("ix_clients_client_name", "client_name"),
        Index("ix_clients_is_active", "is_active"),
    )


class Invoice(Base):
    __tablename__ = "invoices"

    invoice_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    invoice_number: Mapped[str] = mapped_column(
        String(40), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        ForeignKey(
            "clients.client_id",
            name="fk_invoices_client_id_clients",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    service_line_account: Mapped[str] = mapped_column(
        ForeignKey(
            "chart_of_accounts.account_code",
            name="fk_invoices_service_line_account_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    gst_rate_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), nullable=False
    )
    gst_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    balance_due: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    last_payment_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    po_number: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    carried_in_from_prior_period: Mapped[str] = mapped_column(
        String(1), nullable=False
    )
    created_by: Mapped[str] = mapped_column(String(30), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ledger_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "journal_entries.entry_id",
            name="fk_invoices_ledger_entry_id_journal_entries",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    client: Mapped[Client] = relationship(back_populates="invoices")
    service_account: Mapped[ChartOfAccount] = relationship(
        foreign_keys=[service_line_account]
    )
    ledger_entry: Mapped[JournalEntry | None] = relationship(
        foreign_keys=[ledger_entry_id]
    )
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        order_by="InvoiceItem.line_no",
    )
    payments: Mapped[list["InvoicePayment"]] = relationship(
        back_populates="invoice",
        order_by="InvoicePayment.payment_date",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('DRAFT', 'SENT', 'PARTIALLY_PAID', 'PAID', 'OVERDUE', "
            "'CANCELLED')",
            name="ck_invoices_status",
        ),
        CheckConstraint(
            "subtotal >= 0 AND gst_amount >= 0 AND total_amount >= 0 "
            "AND amount_paid >= 0 AND balance_due >= 0",
            name="ck_invoices_nonnegative_amounts",
        ),
        CheckConstraint(
            "gst_rate_percent >= 0",
            name="ck_invoices_nonnegative_gst_rate",
        ),
        CheckConstraint(
            "total_amount = subtotal + gst_amount",
            name="ck_invoices_total_matches_components",
        ),
        CheckConstraint(
            "amount_paid <= total_amount AND balance_due <= total_amount",
            name="ck_invoices_paid_and_balance_within_total",
        ),
        CheckConstraint(
            "carried_in_from_prior_period IN ('Y', 'N')",
            name="ck_invoices_carried_in_flag",
        ),
        UniqueConstraint(
            "invoice_number", name="uq_invoices_invoice_number"
        ),
        UniqueConstraint(
            "ledger_entry_id", name="uq_invoices_ledger_entry_id"
        ),
        Index("ix_invoices_client_id", "client_id"),
        Index("ix_invoices_status_due_date", "status", "due_date"),
        Index("ix_invoices_invoice_date", "invoice_date"),
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    invoice_item_id: Mapped[str] = mapped_column(
        String(30), primary_key=True
    )
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey(
            "invoices.invoice_id",
            name="fk_invoice_items_invoice_id_invoices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(12, 3), nullable=False
    )
    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    revenue_account: Mapped[str] = mapped_column(
        ForeignKey(
            "chart_of_accounts.account_code",
            name="fk_invoice_items_revenue_account_chart_of_accounts",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    revenue_account_record: Mapped[ChartOfAccount] = relationship()

    __table_args__ = (
        CheckConstraint(
            "line_no > 0", name="ck_invoice_items_positive_line_number"
        ),
        CheckConstraint(
            "quantity > 0 AND unit_price >= 0 AND amount >= 0",
            name="ck_invoice_items_nonnegative_values",
        ),
        UniqueConstraint(
            "invoice_id",
            "line_no",
            name="uq_invoice_items_invoice_line_no",
        ),
        Index("ix_invoice_items_invoice_id", "invoice_id"),
        Index("ix_invoice_items_revenue_account", "revenue_account"),
    )


class InvoicePayment(Base):
    __tablename__ = "invoice_payments"

    payment_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        ForeignKey(
            "invoices.invoice_id",
            name="fk_invoice_payments_invoice_id_invoices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False
    )
    payment_mode: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_no: Mapped[str] = mapped_column(String(50), nullable=False)
    received_by: Mapped[str] = mapped_column(String(30), nullable=False)
    ledger_entry_id: Mapped[str] = mapped_column(
        ForeignKey(
            "journal_entries.entry_id",
            name="fk_invoice_payments_ledger_entry_id_journal_entries",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    invoice: Mapped[Invoice] = relationship(back_populates="payments")
    ledger_entry: Mapped[JournalEntry] = relationship(
        foreign_keys=[ledger_entry_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "ledger_entry_id", name="uq_invoice_payments_ledger_entry_id"
        ),
        UniqueConstraint(
            "invoice_id",
            "reference_no",
            name="uq_invoice_payments_invoice_reference",
        ),
        CheckConstraint(
            "amount > 0", name="ck_invoice_payments_positive_amount"
        ),
        Index(
            "ix_invoice_payments_invoice_date",
            "invoice_id",
            "payment_date",
        ),
    )


@event.listens_for(Session, "before_flush")
def _prevent_posted_journal_mutations(session, _flush_context, _instances):
    for instance in session.new:
        if isinstance(instance, JournalLine):
            entry = instance.entry
            if entry is None:
                entry = session.get(JournalEntry, instance.entry_id)
            if (
                entry is not None
                and inspect(entry).persistent
                and entry.status == "POSTED"
            ):
                raise ValueError(
                    "Lines cannot be added to posted journal entries; "
                    "create a reversal."
                )

    for instance in session.dirty:
        if isinstance(instance, JournalEntry):
            state = inspect(instance)
            status_history = state.attrs.status.history
            was_posted = (
                (
                    instance.status == "POSTED"
                    and not status_history.has_changes()
                )
                or "POSTED" in status_history.deleted
            )
            if state.persistent and was_posted and session.is_modified(
                instance, include_collections=True
            ):
                raise ValueError(
                    "Posted journal entries are immutable; create a reversal."
                )

        if isinstance(instance, JournalLine) and inspect(instance).persistent:
            entry = instance.entry
            if entry is None:
                entry = session.get(JournalEntry, instance.entry_id)
            if entry is not None and entry.status == "POSTED":
                raise ValueError(
                    "Lines of posted journal entries are immutable; "
                    "create a reversal."
                )

    for instance in session.deleted:
        if isinstance(instance, JournalEntry) and instance.status == "POSTED":
            raise ValueError(
                "Posted journal entries are immutable; create a reversal."
            )
        if isinstance(instance, JournalLine):
            entry = instance.entry
            if entry is None:
                entry = session.get(JournalEntry, instance.entry_id)
            if entry is not None and entry.status == "POSTED":
                raise ValueError(
                    "Lines of posted journal entries are immutable; "
                    "create a reversal."
                )


@event.listens_for(Session, "do_orm_execute")
def _prevent_bulk_posted_journal_mutations(execute_state):
    if not (execute_state.is_update or execute_state.is_delete):
        return
    table = getattr(execute_state.statement, "table", None)
    if table is not None and table.name in {
        "journal_entries",
        "journal_lines",
    }:
        raise ValueError(
            "Bulk journal updates and deletes are disabled; use a reversal."
        )
