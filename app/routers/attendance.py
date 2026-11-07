from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, get_authenticated_principal
from ..attendance_service import attendance_records, monthly_summary
from ..database import get_db
from ..schemas import AttendanceMonthlySummary, AttendanceOut

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.get(
    "/{employee_id}/monthly-summary",
    response_model=AttendanceMonthlySummary,
)
def employee_monthly_summary(
    employee_id: str,
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    if principal.role not in {"ADMIN", "HR"} and principal.employee_id != employee_id:
        raise HTTPException(403, "Attendance access denied")
    try:
        return monthly_summary(db, employee_id, month)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{employee_id}", response_model=list[AttendanceOut])
def employee_attendance(
    employee_id: str,
    start_date: date,
    end_date: date,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    if principal.role not in {"ADMIN", "HR"} and principal.employee_id != employee_id:
        raise HTTPException(403, "Attendance access denied")
    try:
        return attendance_records(
            db, employee_id, start_date, end_date
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
