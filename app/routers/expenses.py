from datetime import date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, require_roles
from ..database import get_db
from ..expense_schemas import (
    ExpenseBillCreate,
    ExpenseBillOut,
    ExpensePaymentCreate,
    VendorCreate,
    VendorOut,
)
from ..expense_service import (
    ExpenseServiceError,
    approve_expense_bill,
    build_spend_report,
    get_expense_bill,
    pay_expense_bill,
    submit_expense_bill,
)
from ..models import ChartOfAccount, ExpenseBill, Vendor


router = APIRouter(
    prefix="/expenses",
    tags=["expenses"],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
vendors_router = APIRouter(
    prefix="/vendors",
    tags=["vendors"],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)


def _service_error(exc: ExpenseServiceError) -> HTTPException:
    detail = str(exc)
    if "does not exist" in detail:
        code = status.HTTP_404_NOT_FOUND
    elif "already exists" in detail or "conflicts" in detail:
        code = status.HTTP_409_CONFLICT
        detail = "Expense bill conflicts with an existing record."
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=detail)


@vendors_router.post(
    "",
    response_model=VendorOut,
    status_code=status.HTTP_201_CREATED,
)
def create_vendor(
    payload: VendorCreate,
    db: Session = Depends(get_db),
) -> Vendor:
    existing = db.get(Vendor, payload.vendor_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vendor ID already exists",
        )
    account = db.get(ChartOfAccount, payload.primary_expense_account)
    if (
        account is None
        or account.account_type != "EXPENSE"
        or account.is_group != "N"
        or account.is_active != "Y"
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Primary expense account must be an active expense posting account.",
        )
    vendor = Vendor(**payload.model_dump())
    try:
        db.add(vendor)
        db.commit()
        db.refresh(vendor)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vendor conflicts with an existing record.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The vendor could not be created.",
        ) from exc
    return vendor


@vendors_router.get("", response_model=list[VendorOut])
def list_vendors(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[Vendor]:
    try:
        return list(
            db.scalars(
                select(Vendor)
                .order_by(Vendor.vendor_id)
                .offset(skip)
                .limit(limit)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Vendors could not be listed.",
        ) from exc


@vendors_router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(
    vendor_id: str,
    db: Session = Depends(get_db),
) -> Vendor:
    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vendor not found",
        )
    return vendor


@router.post(
    "",
    response_model=ExpenseBillOut,
    status_code=status.HTTP_201_CREATED,
)
def submit_bill(
    payload: ExpenseBillCreate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
) -> ExpenseBill:
    try:
        return submit_expense_bill(
            db,
            expense_id=f"EXP-{uuid4().hex[:16].upper()}",
            submitted_by=principal.employee_id,
            submitted_at=datetime.now(),
            **payload.model_dump(),
        )
    except ExpenseServiceError as exc:
        raise _service_error(exc) from exc


@router.get("", response_model=list[ExpenseBillOut])
def list_bills(
    status_filter: str | None = Query(default=None, alias="status"),
    vendor_id: str | None = Query(default=None, min_length=1, max_length=20),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ExpenseBill]:
    query = select(ExpenseBill)
    if status_filter is not None:
        query = query.where(ExpenseBill.status == status_filter)
    if vendor_id is not None:
        query = query.where(ExpenseBill.vendor_id == vendor_id)
    try:
        return list(
            db.scalars(
                query.order_by(ExpenseBill.expense_date, ExpenseBill.expense_id)
                .offset(skip)
                .limit(limit)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Expense bills could not be listed.",
        ) from exc


@router.get("/{expense_id}", response_model=ExpenseBillOut)
def get_bill(
    expense_id: str,
    db: Session = Depends(get_db),
) -> ExpenseBill:
    bill = get_expense_bill(db, expense_id)
    if bill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense bill not found",
        )
    return bill


@router.post("/{expense_id}/approve", response_model=ExpenseBillOut)
def approve_bill(
    expense_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
) -> ExpenseBill:
    try:
        return approve_expense_bill(
            db,
            expense_id,
            approved_by=principal.employee_id,
            approved_at=datetime.now(),
        )
    except ExpenseServiceError as exc:
        raise _service_error(exc) from exc


@router.post("/{expense_id}/payments", response_model=ExpenseBillOut)
def pay_bill(
    expense_id: str,
    payload: ExpensePaymentCreate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
) -> ExpenseBill:
    try:
        return pay_expense_bill(
            db,
            expense_id,
            payment_date=payload.payment_date,
            payment_mode=payload.payment_mode,
            cash_account=payload.cash_account,
            paid_by=principal.employee_id,
            paid_at=datetime.now(),
        )
    except ExpenseServiceError as exc:
        raise _service_error(exc) from exc


@router.get("/reports/spend")
def spend_report(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
):
    try:
        return build_spend_report(
            db,
            start_date=start_date,
            end_date=end_date,
        )
    except ExpenseServiceError as exc:
        raise _service_error(exc) from exc
