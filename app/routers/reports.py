from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..financial_reports import (
    FinancialReportError,
    balance_sheet,
    profit_and_loss,
    trial_balance,
)


router = APIRouter(prefix="/reports", tags=["financial reports"])


def _report_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FinancialReportError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The financial report could not be generated.",
    )


@router.get(
    "/trial-balance",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def get_trial_balance(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
):
    try:
        return trial_balance(db, start_date=start_date, end_date=end_date)
    except FinancialReportError as exc:
        raise _report_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _report_error(exc) from exc


@router.get(
    "/profit-and-loss",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def get_profit_and_loss(
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
):
    try:
        return profit_and_loss(db, start_date=start_date, end_date=end_date)
    except FinancialReportError as exc:
        raise _report_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _report_error(exc) from exc


@router.get(
    "/balance-sheet",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def get_balance_sheet(
    as_of_date: date = Query(),
    db: Session = Depends(get_db),
):
    try:
        return balance_sheet(db, as_of_date=as_of_date)
    except FinancialReportError as exc:
        raise _report_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _report_error(exc) from exc
