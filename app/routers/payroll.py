import calendar
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, require_roles
from ..database import get_db
from ..payroll_service import (
    PayrollError,
    PayrollNotFoundError,
    VARIABLE_PAY_TYPES,
    calculate_payroll,
)
from ..payroll_workflow_service import (
    PayrollWorkflowError,
    PayrollRunItemInput,
    approve_payroll_run,
    create_payroll_run,
    pay_payroll_run,
    process_payroll_run,
    reverse_payroll_run,
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


class PayrollRunItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str = Field(min_length=1, max_length=20)
    variable_pay: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    variable_pay_type: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    tds: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    other_deductions: Decimal = Field(
        ge=0, max_digits=14, decimal_places=2
    )

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
        if self.variable_pay_type and self.variable_pay <= 0:
            raise ValueError(
                "variable_pay_type is only valid when variable_pay is positive"
            )
        if self.variable_pay_type and self.variable_pay_type not in VARIABLE_PAY_TYPES:
            raise ValueError(
                "variable_pay_type must use a supplied source category"
            )
        return self


class PayrollRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period_start: date
    period_end: date
    pay_date: date
    idempotency_key: str | None = Field(
        default=None, min_length=1, max_length=100
    )
    items: list[PayrollRunItemCreate] = Field(min_length=1, max_length=5000)

    @model_validator(mode="after")
    def validate_period(self):
        if (
            self.period_start.day != 1
            or self.period_start.year != self.period_end.year
            or self.period_start.month != self.period_end.month
            or self.period_end.day
            != calendar.monthrange(
                self.period_end.year, self.period_end.month
            )[1]
        ):
            raise ValueError(
                "Payroll runs must cover one full calendar month"
            )
        if self.pay_date < self.period_end:
            raise ValueError(
                "pay_date must be on or after the payroll period end"
            )
        employee_ids = [item.employee_id for item in self.items]
        if len(set(employee_ids)) != len(employee_ids):
            raise ValueError("A payroll run cannot contain duplicate employees")
        return self


@router.post("/calculate", response_model=PayrollCalculationOut)
def payroll_calculation(
    payload: PayrollCalculationInput,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
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


def _workflow_error(exc: PayrollWorkflowError) -> HTTPException:
    if "does not exist" in str(exc):
        return HTTPException(404, str(exc))
    return HTTPException(422, str(exc))


def _actor_id(principal: AuthenticatedPrincipal) -> str:
    if principal.user_id is None:
        raise HTTPException(401, "Authenticated user ID is unavailable")
    return principal.user_id


@router.post("/runs", status_code=201)
def create_run(
    payload: PayrollRunCreate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        run = create_payroll_run(
            db,
            period_start=payload.period_start,
            period_end=payload.period_end,
            pay_date=payload.pay_date,
            items=[
                PayrollRunItemInput(**item.model_dump())
                for item in payload.items
            ],
            run_by=_actor_id(principal),
            idempotency_key=payload.idempotency_key,
        )
        return {
            "run_id": run.run_id,
            "status": run.status,
            "employees_paid": run.employees_paid,
            "total_gross": run.total_gross,
            "total_deductions": run.total_deductions,
            "total_net": run.total_net,
            "total_employer_cost": run.total_employer_cost,
        }
    except PayrollWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.post("/runs/{run_id}/process")
def process_run(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        run = process_payroll_run(
            db, run_id, processed_by=_actor_id(principal)
        )
        return {"run_id": run.run_id, "status": run.status}
    except PayrollWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.post("/runs/{run_id}/approve")
def approve_run(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        run, entry = approve_payroll_run(
            db, run_id, approved_by=_actor_id(principal)
        )
        return {
            "run_id": run.run_id,
            "status": run.status,
            "journal_entry_id": entry.entry_id,
        }
    except PayrollWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.post("/runs/{run_id}/pay")
def pay_run(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        run, entry = pay_payroll_run(
            db, run_id, paid_by=_actor_id(principal)
        )
        return {
            "run_id": run.run_id,
            "status": run.status,
            "payment_journal_entry_id": entry.entry_id,
        }
    except PayrollWorkflowError as exc:
        raise _workflow_error(exc) from exc


@router.post("/runs/{run_id}/reverse")
def reverse_run(
    run_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        run, entry = reverse_payroll_run(
            db, run_id, reversed_by=_actor_id(principal)
        )
        return {
            "run_id": run.run_id,
            "status": run.status,
            "reversal_journal_entry_id": entry.entry_id,
        }
    except PayrollWorkflowError as exc:
        raise _workflow_error(exc) from exc
