from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterator
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .attendance_service import count_working_days
from .models import Employee, Holiday, LeaveBalance, LeaveRequest, LeaveType


BALANCE_FIELDS = {
    "CL": ("cl_balance", "cl_used"),
    "SL": ("sl_balance", "sl_used"),
    "EL": ("el_balance", "el_used_fy"),
}
ACTIVE_STATUSES = ("Pending", "Approved")
PENDING_STATUS = "Pending"
APPROVED_STATUS = "Approved"
REJECTED_STATUS = "Rejected"


class LeaveError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _financial_year_start(day: date) -> date:
    year = day.year if day.month >= 4 else day.year - 1
    return date(year, 4, 1)


def _financial_year_label(start: date) -> str:
    return f"FY{start.year}-{(start.year + 1) % 100:02d}"


def _financial_year_segments(
    start_date: date, end_date: date
) -> list[tuple[date, date, str]]:
    if start_date > end_date:
        raise LeaveError(422, "start_date must be on or before end_date")

    segments = []
    current = start_date
    while current <= end_date:
        fy_start = _financial_year_start(current)
        next_fy_start = date(fy_start.year + 1, 4, 1)
        segment_end = min(end_date, next_fy_start - timedelta(days=1))
        segments.append(
            (current, segment_end, _financial_year_label(fy_start))
        )
        current = segment_end + timedelta(days=1)
    return segments


def _eligible_days(
    db: Session, start_date: date, end_date: date
) -> int:
    holidays = set(
        db.scalars(
            select(Holiday.holiday_date).where(
                Holiday.holiday_date >= start_date,
                Holiday.holiday_date <= end_date,
            )
        ).all()
    )
    return count_working_days(start_date, end_date, holidays)


def _days_by_financial_year(
    db: Session, start_date: date, end_date: date
) -> list[tuple[str, int]]:
    return [
        (financial_year, _eligible_days(db, segment_start, segment_end))
        for segment_start, segment_end, financial_year
        in _financial_year_segments(start_date, end_date)
    ]


def _active_requests(
    db: Session,
    *,
    employee_id: str,
    leave_type_code: str,
    start_date: date,
    end_date: date,
    exclude_request_id: str | None = None,
) -> list[LeaveRequest]:
    statement = select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.leave_type_code == leave_type_code,
        LeaveRequest.status.in_(ACTIVE_STATUSES),
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date,
    )
    if exclude_request_id is not None:
        statement = statement.where(
            LeaveRequest.leave_request_id != exclude_request_id
        )
    return db.scalars(statement).all()


def _pending_days_in_year(
    db: Session,
    *,
    employee_id: str,
    leave_type_code: str,
    financial_year: str,
    exclude_request_id: str | None = None,
) -> int:
    year = int(financial_year[2:6])
    start = date(year, 4, 1)
    end = date(year + 1, 3, 31)
    total = 0
    for request in _active_requests(
        db,
        employee_id=employee_id,
        leave_type_code=leave_type_code,
        start_date=start,
        end_date=end,
        exclude_request_id=exclude_request_id,
    ):
        if request.status != PENDING_STATUS:
            continue
        total += _eligible_days(
            db, max(start, request.start_date), min(end, request.end_date)
        )
    return total


def _quota_usage_for_entitlement(
    db: Session,
    *,
    employee_id: str,
    leave_type_code: str,
    entitlement_reference: str,
    exclude_request_id: str | None = None,
) -> int:
    statement = select(LeaveRequest).where(
        LeaveRequest.employee_id == employee_id,
        LeaveRequest.leave_type_code == leave_type_code,
        LeaveRequest.entitlement_reference == entitlement_reference,
        LeaveRequest.status.in_(ACTIVE_STATUSES),
    )
    if exclude_request_id is not None:
        statement = statement.where(
            LeaveRequest.leave_request_id != exclude_request_id
        )
    return sum(
        _entitlement_days(
            db,
            leave_type_code,
            request.start_date,
            request.end_date,
        )
        for request in db.scalars(statement).all()
    )


def _entitlement_days(
    db: Session,
    leave_type_code: str,
    start_date: date,
    end_date: date,
) -> int:
    if leave_type_code == "ML":
        return (end_date - start_date).days + 1
    return _eligible_days(db, start_date, end_date)


def _lock_employee_leave_scope(db: Session, employee_id: str) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(
            select(Employee.employee_id)
            .where(Employee.employee_id == employee_id)
            .with_for_update()
        )


@contextmanager
def _leave_operation(db: Session) -> Iterator[None]:
    if db.in_transaction():
        raise LeaveError(
            409,
            "Leave operations require a session with no active transaction",
        )

    dialect = db.get_bind().dialect.name
    if dialect not in {"sqlite", "postgresql"}:
        raise RuntimeError(
            f"Leave reservation locking is unsupported for {dialect}"
        )

    transaction = db.begin()
    try:
        if dialect == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield
        transaction.commit()
    except BaseException:
        if transaction.is_active:
            transaction.rollback()
        raise


def _refresh_pending_days(
    db: Session,
    *,
    employee_id: str,
    financial_year: str,
) -> None:
    balance = db.get(LeaveBalance, (employee_id, financial_year))
    if balance is None:
        return

    year = int(financial_year[2:6])
    start = date(year, 4, 1)
    end = date(year + 1, 3, 31)
    requests = db.scalars(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == PENDING_STATUS,
            LeaveRequest.start_date <= end,
            LeaveRequest.end_date >= start,
        )
    ).all()
    balance.pending_days = Decimal(
        sum(
            _eligible_days(
                db,
                max(start, request.start_date),
                min(end, request.end_date),
            )
            for request in requests
        )
    )


def list_leave_balances(db: Session, employee_id: str) -> list[LeaveBalance]:
    if db.get(Employee, employee_id) is None:
        raise LeaveError(404, "Employee not found")
    return db.scalars(
        select(LeaveBalance)
        .where(LeaveBalance.employee_id == employee_id)
        .order_by(LeaveBalance.financial_year)
    ).all()


def _apply_for_leave_in_transaction(
    db: Session,
    *,
    employee_id: str,
    leave_type_code: str,
    start_date: date,
    end_date: date,
    reason: str,
    entitlement_reference: str | None = None,
) -> LeaveRequest:
    _lock_employee_leave_scope(db, employee_id)
    if db.get(Employee, employee_id) is None:
        raise LeaveError(404, "Employee not found")
    leave_type = db.get(LeaveType, leave_type_code)
    if leave_type is None:
        raise LeaveError(404, "Leave type not found")
    if start_date > end_date:
        raise LeaveError(422, "start_date must be on or before end_date")
    if leave_type_code in {"ML", "BL"}:
        if not entitlement_reference or not entitlement_reference.strip():
            raise LeaveError(
                422,
                "entitlement_reference is required for ML and BL requests",
            )
        entitlement_reference = entitlement_reference.strip()
        unlinked_history = db.scalars(
            select(LeaveRequest.leave_request_id).where(
                LeaveRequest.employee_id == employee_id,
                LeaveRequest.leave_type_code == leave_type_code,
                LeaveRequest.entitlement_reference.is_(None),
                LeaveRequest.status.in_(ACTIVE_STATUSES),
            )
        ).first()
        if unlinked_history is not None:
            raise LeaveError(
                409,
                f"Existing {leave_type_code} requests must be assigned "
                "entitlement references before new requests can be submitted",
            )
    elif entitlement_reference is not None:
        raise LeaveError(
            422,
            "entitlement_reference is only valid for ML and BL requests",
        )

    overlapping = db.scalars(
        select(LeaveRequest.leave_request_id).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status.in_(ACTIVE_STATUSES),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
        )
    ).first()
    if overlapping is not None:
        raise LeaveError(409, "Leave dates overlap an active request")

    year_days = _days_by_financial_year(db, start_date, end_date)
    total_days = sum(days for _, days in year_days)
    if total_days == 0:
        raise LeaveError(422, "The requested range contains no eligible leave days")

    if leave_type_code in BALANCE_FIELDS:
        balance_name, _ = BALANCE_FIELDS[leave_type_code]
        for financial_year, requested_days in year_days:
            if requested_days == 0:
                continue
            balance = db.get(
                LeaveBalance, (employee_id, financial_year)
            )
            if balance is None:
                raise LeaveError(
                    409,
                    f"No leave balance exists for {financial_year}",
                )
            available = Decimal(str(getattr(balance, balance_name)))
            pending = Decimal(
                _pending_days_in_year(
                    db,
                    employee_id=employee_id,
                    leave_type_code=leave_type_code,
                    financial_year=financial_year,
                )
            )
            if available - pending < requested_days:
                raise LeaveError(
                    409,
                    f"Insufficient {leave_type_code} balance for "
                    f"{financial_year}",
                )
    elif leave_type_code in {"ML", "BL"}:
        already_used = _quota_usage_for_entitlement(
            db,
            employee_id=employee_id,
            leave_type_code=leave_type_code,
            entitlement_reference=entitlement_reference,
        )
        requested_quota_days = _entitlement_days(
            db, leave_type_code, start_date, end_date
        )
        if already_used + requested_quota_days > leave_type.annual_quota_days:
            raise LeaveError(
                409,
                f"{leave_type_code} entitlement quota exceeded",
            )

    request = LeaveRequest(
        leave_request_id=f"LR-{uuid4().hex[:16].upper()}",
        employee_id=employee_id,
        leave_type_code=leave_type_code,
        entitlement_reference=entitlement_reference,
        start_date=start_date,
        end_date=end_date,
        days=Decimal(total_days),
        reason=reason,
        status=PENDING_STATUS,
        applied_on=date.today(),
        approver_id=None,
        decided_on=None,
    )
    db.add(request)
    try:
        db.flush()
        for financial_year, _ in year_days:
            _refresh_pending_days(
                db,
                employee_id=employee_id,
                financial_year=financial_year,
            )
    except IntegrityError as exc:
        raise LeaveError(409, "Leave request could not be saved") from exc
    return request


def apply_for_leave(
    db: Session,
    *,
    employee_id: str,
    leave_type_code: str,
    start_date: date,
    end_date: date,
    reason: str,
    entitlement_reference: str | None = None,
) -> LeaveRequest:
    with _leave_operation(db):
        return _apply_for_leave_in_transaction(
            db,
            employee_id=employee_id,
            leave_type_code=leave_type_code,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            entitlement_reference=entitlement_reference,
        )


def _approve_leave_in_transaction(
    db: Session,
    request_id: str,
    approver_id: str | None = None,
) -> LeaveRequest:
    request = db.get(LeaveRequest, request_id)
    if request is None:
        raise LeaveError(404, "Leave request not found")
    _lock_employee_leave_scope(db, request.employee_id)
    db.refresh(request)
    if request.status != PENDING_STATUS:
        raise LeaveError(409, "Only Pending leave requests can be approved")
    if approver_id is not None and db.get(Employee, approver_id) is None:
        raise LeaveError(422, "Approver employee does not exist")

    year_days = _days_by_financial_year(
        db, request.start_date, request.end_date
    )
    total_days = sum(days for _, days in year_days)
    if total_days == 0:
        raise LeaveError(
            409,
            "The requested range no longer contains eligible leave days",
        )
    leave_type_code = request.leave_type_code

    try:
        if leave_type_code in BALANCE_FIELDS:
            balance_name, used_name = BALANCE_FIELDS[leave_type_code]
            balance_column = getattr(LeaveBalance, balance_name)
            used_column = getattr(LeaveBalance, used_name)

            for financial_year, requested_days in year_days:
                if requested_days == 0:
                    continue
                balance = db.get(
                    LeaveBalance,
                    (request.employee_id, financial_year),
                    with_for_update=True,
                )
                if balance is None:
                    raise LeaveError(
                        409,
                        f"No leave balance exists for {financial_year}",
                    )
                pending_other = _pending_days_in_year(
                    db,
                    employee_id=request.employee_id,
                    leave_type_code=leave_type_code,
                    financial_year=financial_year,
                    exclude_request_id=request_id,
                )
                result = db.execute(
                    update(LeaveBalance)
                    .where(
                        LeaveBalance.employee_id == request.employee_id,
                        LeaveBalance.financial_year == financial_year,
                        balance_column - pending_other >= requested_days,
                    )
                    .values(
                        {
                            balance_name: balance_column - requested_days,
                            used_name: used_column + requested_days,
                        }
                    )
                )
                if result.rowcount != 1:
                    raise LeaveError(
                        409,
                        f"Insufficient {leave_type_code} balance for "
                        f"{financial_year}",
                    )
        elif leave_type_code in {"ML", "BL"}:
            if not request.entitlement_reference:
                raise LeaveError(
                    409,
                    "ML/BL requests without an entitlement reference "
                    "cannot be approved",
                )
            leave_type = db.get(LeaveType, leave_type_code)
            if leave_type is None:
                raise LeaveError(404, "Leave type not found")
            other_usage = _quota_usage_for_entitlement(
                db,
                employee_id=request.employee_id,
                leave_type_code=leave_type_code,
                entitlement_reference=request.entitlement_reference,
                exclude_request_id=request_id,
            )
            requested_quota_days = _entitlement_days(
                db,
                leave_type_code,
                request.start_date,
                request.end_date,
            )
            if (
                other_usage + requested_quota_days
                > leave_type.annual_quota_days
            ):
                raise LeaveError(
                    409,
                    f"{leave_type_code} entitlement quota exceeded",
                )

        result = db.execute(
            update(LeaveRequest)
            .where(
                LeaveRequest.leave_request_id == request_id,
                LeaveRequest.status == PENDING_STATUS,
            )
            .values(
                status=APPROVED_STATUS,
                approver_id=approver_id,
                decided_on=date.today(),
                days=Decimal(total_days),
            )
        )
        if result.rowcount != 1:
            raise LeaveError(409, "Leave request is no longer Pending")
        db.flush()
        for financial_year, _ in year_days:
            _refresh_pending_days(
                db,
                employee_id=request.employee_id,
                financial_year=financial_year,
            )
    except Exception:
        raise

    return request


def approve_leave(
    db: Session,
    request_id: str,
    approver_id: str | None = None,
) -> LeaveRequest:
    with _leave_operation(db):
        return _approve_leave_in_transaction(
            db,
            request_id,
            approver_id=approver_id,
        )


def _reject_leave_in_transaction(
    db: Session,
    request_id: str,
    approver_id: str | None = None,
) -> LeaveRequest:
    request = db.get(LeaveRequest, request_id)
    if request is None:
        raise LeaveError(404, "Leave request not found")
    _lock_employee_leave_scope(db, request.employee_id)
    db.refresh(request)
    if request.status != PENDING_STATUS:
        raise LeaveError(409, "Only Pending leave requests can be rejected")
    if approver_id is not None and db.get(Employee, approver_id) is None:
        raise LeaveError(422, "Approver employee does not exist")

    result = db.execute(
        update(LeaveRequest)
        .where(
            LeaveRequest.leave_request_id == request_id,
            LeaveRequest.status == PENDING_STATUS,
        )
        .values(
            status=REJECTED_STATUS,
            approver_id=approver_id,
            decided_on=date.today(),
        )
    )
    if result.rowcount != 1:
        raise LeaveError(409, "Leave request is no longer Pending")
    for financial_year, _ in _days_by_financial_year(
        db, request.start_date, request.end_date
    ):
        _refresh_pending_days(
            db,
            employee_id=request.employee_id,
            financial_year=financial_year,
        )
    return request


def reject_leave(
    db: Session,
    request_id: str,
    approver_id: str | None = None,
) -> LeaveRequest:
    with _leave_operation(db):
        return _reject_leave_in_transaction(
            db,
            request_id,
            approver_id=approver_id,
        )


def get_leave_request(db: Session, request_id: str) -> LeaveRequest:
    request = db.get(LeaveRequest, request_id)
    if request is None:
        raise LeaveError(404, "Leave request not found")
    return request


def list_leave_requests(
    db: Session,
    *,
    employee_id: str | None = None,
    status: str | None = None,
) -> list[LeaveRequest]:
    statement = select(LeaveRequest)
    if employee_id is not None:
        statement = statement.where(
            LeaveRequest.employee_id == employee_id
        )
    if status is not None:
        statement = statement.where(LeaveRequest.status == status)
    return db.scalars(
        statement.order_by(
            LeaveRequest.applied_on.desc(),
            LeaveRequest.leave_request_id,
        )
    ).all()


def list_leave_types(db: Session) -> list[LeaveType]:
    return db.scalars(
        select(LeaveType).order_by(LeaveType.leave_type_code)
    ).all()
