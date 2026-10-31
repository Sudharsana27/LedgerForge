from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..database import get_db
from ..payroll_service import (
    PayrollError,
    PayrollNotFoundError,
    VARIABLE_PAY_TYPES,
    calculate_payroll,
)


router = APIRouter(prefix="/payroll", tags=["payroll"])


class PayrollCalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str = Field(min_length=1, max_length=20)
    period_start: date
    period_end: date
    variable_pay: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    variable_pay_type: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    tds: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    other_deductions: Decimal = Field(
        ge=0, max_digits=14, decimal_places=2
    )

    @model_validator(mode="after")
    def validate_period(self):
        if self.period_start > self.period_end:
            raise ValueError("period_start must be on or before period_end")
        if (
            self.period_start.year != self.period_end.year
            or self.period_start.month != self.period_end.month
        ):
            raise ValueError("Payroll periods must cover one calendar month")
        return self

    @model_validator(mode="after")
    def validate_variable_pay(self):
        if self.variable_pay > 0 and not self.variable_pay_type:
            raise ValueError(
                "variable_pay_type is required when variable_pay is positive"
            )
        if (
            self.variable_pay_type is not None
            and not self.variable_pay_type.strip()
        ):
            raise ValueError("variable_pay_type cannot be blank")
        if (
            self.variable_pay_type is not None
            and self.variable_pay_type not in VARIABLE_PAY_TYPES
        ):
            raise ValueError(
                "variable_pay_type must use a supplied source category"
            )
        if self.variable_pay_type and self.variable_pay <= 0:
            raise ValueError(
                "variable_pay_type is only valid when variable_pay is positive"
            )
        return self


class PayrollCalculationOut(BaseModel):
    employee_id: str
    period_start: date
    period_end: date
    department_id: str
    role_id: str
    calendar_days: int
    days_employed: int
    lop_days: Decimal
    payable_days: Decimal
    monthly_fixed_gross: Decimal
    basic: Decimal
    hra: Decimal
    conveyance: Decimal
    medical: Decimal
    special_allowance: Decimal
    earned_fixed_pay: Decimal
    overtime_hours_paid: Decimal
    overtime_pay: Decimal
    variable_pay: Decimal
    variable_pay_type: str | None
    gross_pay: Decimal
    pf_employee: Decimal
    esi_employee: Decimal
    professional_tax: Decimal
    tds: Decimal
    other_deductions: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    pf_employer: Decimal
    esi_employer: Decimal
    employer_cost: Decimal


@router.post("/calculate", response_model=PayrollCalculationOut)
def payroll_calculation(
    payload: PayrollCalculationInput,
    db: Session = Depends(get_db),
):
    try:
        return calculate_payroll(
            db,
            employee_id=payload.employee_id,
            period_start=payload.period_start,
            period_end=payload.period_end,
            variable_pay=payload.variable_pay,
            variable_pay_type=payload.variable_pay_type,
            tds=payload.tds,
            other_deductions=payload.other_deductions,
        )
    except PayrollNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PayrollError as exc:
        raise HTTPException(422, str(exc)) from exc
