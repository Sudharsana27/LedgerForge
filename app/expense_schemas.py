from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VendorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_id: str = Field(min_length=1, max_length=20)
    vendor_name: str = Field(min_length=1, max_length=200)
    primary_expense_account: str = Field(min_length=1, max_length=20)
    payment_terms_days: int = Field(ge=0)
    city: str = Field(min_length=1, max_length=100)
    gst_registration: str | None = Field(default=None, max_length=30)
    is_active: str = Field(default="Y", pattern=r"^[YN]$")


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vendor_id: str
    vendor_name: str
    primary_expense_account: str
    payment_terms_days: int
    city: str
    gst_registration: str | None
    is_active: str


class ExpenseBillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_id: str = Field(min_length=1, max_length=20)
    category_account: str | None = Field(default=None, max_length=20)
    bill_reference: str = Field(min_length=1, max_length=80)
    expense_date: date
    due_date: date
    description: str = Field(min_length=1, max_length=500)
    department_id: str = Field(min_length=1, max_length=10)
    amount_excl_gst: Decimal = Field(
        ge=0, max_digits=18, decimal_places=2
    )
    gst_rate_percent: Decimal = Field(
        ge=0, max_digits=7, decimal_places=4
    )

    @model_validator(mode="after")
    def validate_due_date(self):
        if self.due_date < self.expense_date:
            raise ValueError("due_date must be on or after expense_date")
        return self


class ExpenseBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    expense_id: str
    expense_date: date
    category_account: str
    vendor_id: str
    bill_reference: str
    description: str
    department_id: str
    amount_excl_gst: Decimal
    gst_rate_percent: Decimal
    gst_amount: Decimal
    total_amount: Decimal
    due_date: date
    paid_date: date | None
    status: str
    payment_mode: str | None
    submitted_by: str
    approved_by: str | None
    ledger_entry_id: str | None
    payment_ledger_entry_id: str | None
    submitted_at: datetime | None
    approved_at: datetime | None
    paid_at: datetime | None


class ExpensePaymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_date: date
    payment_mode: str = Field(min_length=1, max_length=30)
    cash_account: str = Field(default="1001", min_length=1, max_length=20)
