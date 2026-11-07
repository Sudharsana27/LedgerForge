from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import require_roles
from ..database import get_db
from ..receivables_service import (
    ReceivablesError,
    build_receivables_report,
)
from ..schemas import (
    ReceivableInvoiceStatus,
    ReceivablesReportOut,
)


router = APIRouter(prefix="/receivables", tags=["receivables"])


@router.get(
    "",
    response_model=ReceivablesReportOut,
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
def get_receivables(
    client_id: str | None = Query(default=None, min_length=1, max_length=20),
    status_filter: ReceivableInvoiceStatus | None = Query(
        default=None, alias="status"
    ),
    db: Session = Depends(get_db),
):
    try:
        return build_receivables_report(
            db,
            client_id=client_id,
            status=status_filter,
        )
    except ReceivablesError as exc:
        code = 404 if "does not exist" in str(exc) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The receivables report could not be generated.",
        ) from exc
