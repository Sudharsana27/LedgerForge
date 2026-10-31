
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    department_id: str
    department_name: str
    cost_center: str
    description: str | None = None


class EmployeeCreate(BaseModel):
    employee_id: str = Field(min_length=1, max_length=20)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    work_email: EmailStr
    hire_date: date
    employment_status: str = Field(min_length=1, max_length=30)
    employment_type: str = Field(min_length=1, max_length=30)
    department_id: str = Field(min_length=1, max_length=10)
    role_id: str = Field(min_length=1, max_length=10)
    manager_id: str | None = None
    work_location: str = Field(min_length=1, max_length=100)
    work_mode: str = Field(min_length=1, max_length=30)

    gender: str | None = None
    exit_date: date | None = None
    highest_education: str | None = None
    prior_experience_years: float | None = Field(default=None, ge=0)
    career_gap_months: int | None = Field(default=None, ge=0)
    commute_distance_km: float | None = Field(default=None, ge=0)
    pf_applicable: str = "Y"
    esi_applicable: str = "N"
    notice_period_days: int = Field(default=30, ge=0)


class EmployeeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    work_email: EmailStr | None = None
    employment_status: str | None = None
    employment_type: str | None = None
    department_id: str | None = None
    role_id: str | None = None
    manager_id: str | None = None
    work_location: str | None = None
    work_mode: str | None = None
    exit_date: date | None = None


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: str
    first_name: str
    last_name: str
    full_name: str
    work_email: str
    hire_date: date
    exit_date: date | None = None
    employment_status: str
    employment_type: str
    department_id: str
    role_id: str
    manager_id: str | None = None
    work_location: str
    work_mode: str


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attendance_id: str
    employee_id: str
    attendance_date: date
    weekday: str
    status: str
    leave_type_code: str | None = None
    check_in: str | None = None
    check_out: str | None = None
    hours_worked: float | None = None
    overtime_hours: float | None = None
    late_flag: str | None = None
    source: str
    data_quality_flag: str | None = None
    department_id: str


class AttendanceMonthlySummary(BaseModel):
    employee_id: str
    month: str
    calendar_days: int
    working_days: int
    recorded_days: int
    days_present: int
    work_from_home_days: int
    attended_days: int
    absent_days: float
    late_days: int
    overtime_hours: float
    missing_checkout_count: int


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    leave_type_code: str
    leave_type_name: str
    pay_type: str
    annual_quota_days: int
    prorated_for_joiners: str
    carry_forward_allowed: str
    max_carry_forward_days: int
    policy_note: str


class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: str
    as_of_date: date
    financial_year: str
    cl_entitlement: float
    cl_used: float
    cl_balance: float
    sl_entitlement: float
    sl_used: float
    sl_balance: float
    el_used_fy: float
    el_balance: float
    pending_days: float


class LeaveRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str = Field(min_length=1, max_length=20)
    leave_type_code: str = Field(min_length=1, max_length=10)
    entitlement_reference: str | None = Field(default=None, max_length=100)
    start_date: date
    end_date: date
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        if (
            self.leave_type_code in {"ML", "BL"}
            and not self.entitlement_reference
        ):
            raise ValueError(
                "entitlement_reference is required for ML and BL requests"
            )
        if (
            self.leave_type_code not in {"ML", "BL"}
            and self.entitlement_reference is not None
        ):
            raise ValueError(
                "entitlement_reference is only valid for ML and BL requests"
            )
        return self


class LeaveDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver_id: str | None = Field(default=None, max_length=20)


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    leave_request_id: str
    employee_id: str
    leave_type_code: str
    entitlement_reference: str | None = None
    start_date: date
    end_date: date
    days: float
    reason: str
    status: str
    applied_on: date
    approver_id: str | None = None
    decided_on: date | None = None


ClientType = Literal["DOMESTIC", "EXPORT"]
ClientActiveFlag = Literal["Y", "N"]


class ClientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1, max_length=20)
    client_name: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    state_or_region: str = Field(min_length=1, max_length=100)
    country: str = Field(min_length=2, max_length=3)
    client_type: ClientType
    gst_registration: str | None = Field(default=None, max_length=30)
    payment_terms_days: int = Field(ge=0)
    payment_behaviour: str = Field(min_length=1, max_length=30)
    primary_service_line: str = Field(min_length=1, max_length=20)
    contact_email: EmailStr
    onboarded_on: date
    is_active: ClientActiveFlag = "Y"

    @field_validator(
        "client_id",
        "client_name",
        "industry",
        "city",
        "state_or_region",
        "country",
        "payment_behaviour",
        "primary_service_line",
        "contact_email",
        mode="before",
    )
    @classmethod
    def strip_text_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ClientUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state_or_region: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    country: str | None = Field(default=None, min_length=2, max_length=3)
    client_type: ClientType | None = None
    gst_registration: str | None = Field(default=None, max_length=30)
    payment_terms_days: int | None = Field(default=None, ge=0)
    payment_behaviour: str | None = Field(
        default=None, min_length=1, max_length=30
    )
    primary_service_line: str | None = Field(
        default=None, min_length=1, max_length=20
    )
    contact_email: EmailStr | None = None
    onboarded_on: date | None = None
    is_active: ClientActiveFlag | None = None

    @field_validator(
        "client_name",
        "industry",
        "city",
        "state_or_region",
        "country",
        "payment_behaviour",
        "primary_service_line",
        "contact_email",
        mode="before",
    )
    @classmethod
    def strip_text_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_changes(self):
        if not self.model_fields_set:
            raise ValueError("At least one client field must be provided")
        if any(
            getattr(self, field_name) is None
            for field_name in self.model_fields_set
            if field_name != "gst_registration"
        ):
            raise ValueError("Client fields cannot be null")
        return self


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_id: str
    client_name: str
    industry: str
    city: str
    state_or_region: str
    country: str
    client_type: ClientType
    gst_registration: str | None = None
    payment_terms_days: int
    payment_behaviour: str
    primary_service_line: str
    contact_email: EmailStr
    onboarded_on: date
    is_active: ClientActiveFlag


InvoiceStatus = Literal[
    "DRAFT",
    "SENT",
    "PARTIALLY_PAID",
    "PAID",
    "OVERDUE",
    "CANCELLED",
]

ReceivableInvoiceStatus = Literal["SENT", "PARTIALLY_PAID", "OVERDUE"]


class InvoiceItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, max_length=500)
    quantity: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    revenue_account: str = Field(
        pattern=r"^400[1-4]$", min_length=4, max_length=4
    )


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoice_number: str = Field(min_length=1, max_length=40)
    client_id: str = Field(min_length=1, max_length=20)
    invoice_date: date
    due_date: date
    gst_rate_percent: Decimal = Field(
        ge=0, max_digits=7, decimal_places=4
    )
    items: list[InvoiceItemCreate] = Field(min_length=1)
    po_number: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_due_date(self):
        if self.due_date < self.invoice_date:
            raise ValueError("due_date must be on or after invoice_date")
        return self


class InvoicePaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_date: date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payment_mode: str = Field(min_length=1, max_length=30)
    reference_no: str = Field(min_length=1, max_length=50)


class InvoiceRefreshStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_date: date


class InvoiceSendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_date: date


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_item_id: str
    line_no: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    revenue_account: str


class InvoicePaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_id: str
    payment_date: date
    amount: Decimal
    payment_mode: str
    reference_no: str
    received_by: str
    ledger_entry_id: str


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_id: str
    invoice_number: str
    client_id: str
    invoice_date: date
    due_date: date
    service_line_account: str
    currency: str
    subtotal: Decimal
    gst_rate_percent: Decimal
    gst_amount: Decimal
    total_amount: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    status: InvoiceStatus
    last_payment_date: date | None = None
    po_number: str | None = None
    carried_in_from_prior_period: str
    created_by: str
    created_at: datetime
    ledger_entry_id: str | None = None
    items: list[InvoiceItemOut]
    payments: list[InvoicePaymentOut]


class InvoiceActionOut(BaseModel):
    invoice: InvoiceOut
    journal_entry_id: str | None = None


class ReceivableInvoiceOut(BaseModel):
    invoice_id: str
    invoice_number: str
    invoice_date: date
    due_date: date
    status: ReceivableInvoiceStatus
    balance_due: Decimal


class ClientReceivableOut(BaseModel):
    client_id: str
    client_name: str
    open_invoice_count: int
    total_outstanding: Decimal
    invoices: list[ReceivableInvoiceOut]


class ReceivablesReportOut(BaseModel):
    total_outstanding: Decimal
    clients: list[ClientReceivableOut]
