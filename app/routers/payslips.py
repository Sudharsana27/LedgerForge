from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, get_authenticated_principal
from ..database import get_db
from ..payroll_service import PayrollNotFoundError
from ..payslip_service import (
    PayslipNotFoundError,
    PayslipUnavailableError,
    build_payslip_result,
    render_payslip_pdf,
)


router = APIRouter(prefix="/payslips", tags=["payslips"])


@router.get(
    "/{employee_id}/{run_id}",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}},
        401: {"description": "Authentication required"},
        403: {"description": "Payslip access denied"},
        404: {"description": "Payroll run or employee item not found"},
        503: {"description": "Payroll inputs or source data unavailable"},
    },
)
def get_payslip(
    employee_id: str = Path(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
    run_id: str = Path(
        min_length=1,
        max_length=30,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> Response:
    if principal.role != "HR" and principal.employee_id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Payslip access denied",
        )

    try:
        payslip = build_payslip_result(
            db,
            employee_id=employee_id,
            run_id=run_id,
        )
        pdf = render_payslip_pdf(payslip)
    except (PayslipNotFoundError, PayrollNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PayslipUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    filename = f"payslip-{employee_id}-{run_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
