from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..leave_service import (
    LeaveError,
    apply_for_leave,
    approve_leave,
    get_leave_request,
    list_leave_balances,
    list_leave_requests,
    list_leave_types,
    reject_leave,
)
from ..models import Employee
from ..schemas import (
    LeaveBalanceOut,
    LeaveDecisionInput,
    LeaveRequestCreate,
    LeaveRequestOut,
    LeaveTypeOut,
)

router = APIRouter(prefix="/leave", tags=["leave"])


@router.get("/types", response_model=list[LeaveTypeOut])
def get_leave_types(db: Session = Depends(get_db)):
    return list_leave_types(db)


@router.get(
    "/balances/{employee_id}",
    response_model=list[LeaveBalanceOut],
)
def employee_leave_balances(
    employee_id: str,
    db: Session = Depends(get_db),
):
    try:
        return list_leave_balances(db, employee_id)
    except LeaveError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get("/requests", response_model=list[LeaveRequestOut])
def get_leave_requests(
    employee_id: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    if employee_id is not None and db.get(Employee, employee_id) is None:
        raise HTTPException(404, "Employee not found")
    return list_leave_requests(
        db, employee_id=employee_id, status=status
    )


@router.post(
    "/requests",
    response_model=LeaveRequestOut,
    status_code=201,
)
def create_leave_request(
    payload: LeaveRequestCreate,
    db: Session = Depends(get_db),
):
    try:
        return apply_for_leave(db, **payload.model_dump())
    except LeaveError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.get(
    "/requests/{request_id}",
    response_model=LeaveRequestOut,
)
def get_request(request_id: str, db: Session = Depends(get_db)):
    try:
        return get_leave_request(db, request_id)
    except LeaveError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post(
    "/requests/{request_id}/approve",
    response_model=LeaveRequestOut,
)
def approve_request(
    request_id: str,
    payload: LeaveDecisionInput | None = None,
    db: Session = Depends(get_db),
):
    try:
        return approve_leave(
            db,
            request_id,
            approver_id=payload.approver_id if payload else None,
        )
    except LeaveError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@router.post(
    "/requests/{request_id}/reject",
    response_model=LeaveRequestOut,
)
def reject_request(
    request_id: str,
    payload: LeaveDecisionInput | None = None,
    db: Session = Depends(get_db),
):
    try:
        return reject_leave(
            db,
            request_id,
            approver_id=payload.approver_id if payload else None,
        )
    except LeaveError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
