from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, require_roles
from ..database import get_db
from ..models import StatutoryRate, TaxParameter, TaxSlab
from ..tax_schemas import (
    StatutoryRateOut,
    StatutoryRateUpdate,
    TaxParameterOut,
    TaxParameterUpdate,
    TaxSlabOut,
    TaxSlabUpdate,
)
from ..tax_service import (
    TaxConfigurationError,
    build_statutory_report,
    calculate_annual_tds,
    update_statutory_rate,
    update_tax_parameter,
    update_tax_slab,
)


router = APIRouter(tags=["tax and statutory reports"])


def _tax_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TaxConfigurationError):
        detail = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "does not exist" in detail
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return HTTPException(status_code=code, detail=detail)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The tax operation could not be completed.",
    )


@router.get(
    "/tax/slabs",
    response_model=list[TaxSlabOut],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def list_tax_slabs(
    regime: str | None = Query(default=None, min_length=1, max_length=20),
    financial_year: str | None = Query(
        default=None, min_length=1, max_length=20
    ),
    db: Session = Depends(get_db),
) -> list[TaxSlab]:
    query = select(TaxSlab).order_by(
        TaxSlab.regime,
        TaxSlab.financial_year,
        TaxSlab.income_from,
        TaxSlab.effective_from,
    )
    if regime is not None:
        query = query.where(TaxSlab.regime == regime)
    if financial_year is not None:
        query = query.where(TaxSlab.financial_year == financial_year)
    try:
        return list(db.scalars(query).all())
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.post(
    "/tax/slabs/{slab_id}/versions",
    response_model=TaxSlabOut,
    status_code=status.HTTP_201_CREATED,
)
def create_tax_slab_version(
    slab_id: str,
    payload: TaxSlabUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN")
    ),
    db: Session = Depends(get_db),
) -> TaxSlab:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user identity is unavailable.",
        )
    try:
        return update_tax_slab(
            db,
            slab_id=slab_id,
            rate_percent=payload.rate_percent,
            effective_from=payload.effective_from,
            changed_by=principal.user_id,
            changed_at=datetime.now(),
        )
    except TaxConfigurationError as exc:
        raise _tax_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.get(
    "/tax/parameters",
    response_model=list[TaxParameterOut],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def list_tax_parameters(db: Session = Depends(get_db)) -> list[TaxParameter]:
    try:
        return list(
            db.scalars(
                select(TaxParameter).order_by(
                    TaxParameter.parameter,
                    TaxParameter.effective_from,
                )
            ).all()
        )
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.post(
    "/tax/parameters/{parameter}/versions",
    response_model=TaxParameterOut,
    status_code=status.HTTP_201_CREATED,
)
def create_tax_parameter_version(
    parameter: str,
    payload: TaxParameterUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN")
    ),
    db: Session = Depends(get_db),
) -> TaxParameter:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user identity is unavailable.",
        )
    try:
        return update_tax_parameter(
            db,
            parameter=parameter,
            value=payload.value,
            effective_from=payload.effective_from,
            changed_by=principal.user_id,
        )
    except TaxConfigurationError as exc:
        raise _tax_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.get(
    "/tax/statutory-rates",
    response_model=list[StatutoryRateOut],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def list_statutory_rates(db: Session = Depends(get_db)) -> list[StatutoryRate]:
    try:
        return list(
            db.scalars(
                select(StatutoryRate).order_by(
                    StatutoryRate.parameter,
                    StatutoryRate.effective_from,
                    StatutoryRate.id,
                )
            ).all()
        )
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.post(
    "/tax/statutory-rates/{parameter}/versions",
    response_model=StatutoryRateOut,
    status_code=status.HTTP_201_CREATED,
)
def create_statutory_rate_version(
    parameter: str,
    payload: StatutoryRateUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN")
    ),
    db: Session = Depends(get_db),
) -> StatutoryRate:
    if principal.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user identity is unavailable.",
        )
    try:
        return update_statutory_rate(
            db,
            parameter=parameter,
            value=payload.value,
            effective_from=payload.effective_from,
            source_note=payload.source_note,
            changed_by=principal.user_id,
        )
    except TaxConfigurationError as exc:
        raise _tax_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.get(
    "/tax/calculate",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def calculate_tds(
    annual_gross_income: Decimal = Query(ge=0, max_digits=18, decimal_places=2),
    financial_year: str = Query(min_length=1, max_length=20),
    regime: str = Query(min_length=1, max_length=20),
    on_date: date = Query(),
    db: Session = Depends(get_db),
):
    try:
        return calculate_annual_tds(
            db,
            annual_gross_income=annual_gross_income,
            financial_year=financial_year,
            regime=regime,
            on_date=on_date,
        )
    except TaxConfigurationError as exc:
        raise _tax_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc


@router.get(
    "/statutory/{report_type}",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def statutory_report(
    report_type: str,
    start_date: date,
    end_date: date,
    db: Session = Depends(get_db),
):
    try:
        return build_statutory_report(
            db,
            report_type=report_type.lower(),
            start_date=start_date,
            end_date=end_date,
        )
    except TaxConfigurationError as exc:
        raise _tax_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _tax_error(exc) from exc
