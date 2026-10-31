import calendar
import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Attendance, Employee, Holiday


MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month_bounds(month: str) -> tuple[date, date]:
    if not MONTH_PATTERN.fullmatch(month):
        raise ValueError("Month must use the YYYY-MM format")

    year, month_number = (int(value) for value in month.split("-"))
    last_day = calendar.monthrange(year, month_number)[1]
    return date(year, month_number, 1), date(year, month_number, last_day)


def monthly_summary(db: Session, employee_id: str, month: str) -> dict:
    """Summarize source attendance statuses without inferring missing days."""
    first_day, last_day = _month_bounds(month)

    if db.get(Employee, employee_id) is None:
        raise LookupError("Employee not found")

    rows = db.scalars(
        select(Attendance)
        .where(
            Attendance.employee_id == employee_id,
            Attendance.attendance_date >= first_day,
            Attendance.attendance_date <= last_day,
        )
        .order_by(Attendance.attendance_date, Attendance.attendance_id)
    ).all()

    statuses_by_day: dict[date, Attendance] = {}
    for row in rows:
        if row.attendance_date in statuses_by_day:
            raise ValueError(
                f"Multiple attendance records found for "
                f"{employee_id} on {row.attendance_date}"
            )
        statuses_by_day[row.attendance_date] = row

    holiday_dates = set(
        db.scalars(
            select(Holiday.holiday_date).where(
                Holiday.holiday_date >= first_day,
                Holiday.holiday_date <= last_day,
            )
        ).all()
    )
    working_days = sum(
        1
        for day_number in range(1, last_day.day + 1)
        if date(first_day.year, first_day.month, day_number).weekday() < 5
        and date(first_day.year, first_day.month, day_number)
        not in holiday_dates
    )

    present_days = sum(row.status == "PRESENT" for row in statuses_by_day.values())
    work_from_home_days = sum(
        row.status == "WFH" for row in statuses_by_day.values()
    )
    absent_days = sum(
        (
            Decimal("1")
            if row.status == "ABSENT_LOP"
            else Decimal("0.5")
            if row.status == "HALF_DAY_UNPAID"
            else Decimal("0")
        )
        for row in statuses_by_day.values()
    )

    return {
        "employee_id": employee_id,
        "month": month,
        "calendar_days": last_day.day,
        "working_days": working_days,
        "recorded_days": len(statuses_by_day),
        "days_present": present_days,
        "work_from_home_days": work_from_home_days,
        "attended_days": present_days + work_from_home_days,
        "absent_days": absent_days,
        "late_days": sum(
            row.late_flag == "Y" for row in statuses_by_day.values()
        ),
        "overtime_hours": sum(
            (
                Decimal(str(row.overtime_hours))
                if row.overtime_hours is not None
                else Decimal("0")
            )
            for row in statuses_by_day.values()
        ),
        "missing_checkout_count": sum(
            row.data_quality_flag == "MISSING_CHECKOUT"
            for row in statuses_by_day.values()
        ),
    }


def attendance_records(
    db: Session,
    employee_id: str,
    start_date: date,
    end_date: date,
) -> list[Attendance]:
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if db.get(Employee, employee_id) is None:
        raise LookupError("Employee not found")

    return db.scalars(
        select(Attendance)
        .where(
            Attendance.employee_id == employee_id,
            Attendance.attendance_date >= start_date,
            Attendance.attendance_date <= end_date,
        )
        .order_by(Attendance.attendance_date, Attendance.attendance_id)
    ).all()


def count_working_days(
    start_date: date,
    end_date: date,
    holidays: set[date] | frozenset[date],
) -> int:
    """Count inclusive weekdays excluding each holiday date at most once."""
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    total = 0
    current = start_date
    while current <= end_date:
        if current.weekday() < 5 and current not in holidays:
            total += 1
        current += timedelta(days=1)
    return total
