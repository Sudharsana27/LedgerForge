from __future__ import annotations

import csv
import io
from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from openpyxl import Workbook

from ..auth import require_roles
from ..database import get_db
from ..models import Employee, JournalEntry, PayrollItem, PayrollRun


router = APIRouter(prefix="/exports", tags=["exports"])


def _csv_response(filename: str, fieldnames: tuple[str, ...], rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    stream.seek(0)
    return StreamingResponse(
        iter([stream.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _serialize(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value)


def _excel_response(filename: str, fieldnames: tuple[str, ...], rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Export"
    sheet.append(list(fieldnames))
    for row in rows:
        sheet.append([row[field] for field in fieldnames])
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return StreamingResponse(
        iter([stream.read()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _export_response(
    format: Literal["csv", "xlsx"],
    basename: str,
    fieldnames: tuple[str, ...],
    rows,
):
    if format == "xlsx":
        return _excel_response(f"{basename}.xlsx", fieldnames, rows)
    return _csv_response(f"{basename}.csv", fieldnames, rows)


@router.get(
    "/employees",
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
    openapi_extra={
        "examples": {
            "csvEmployeeExport": {
                "summary": "Incremental employee CSV",
                "value": {"changed_since": "2026-11-01", "format": "csv"},
            }
        }
    },
)
def export_employees(
    changed_since: date | None = Query(
        default=None,
        description=(
            "Include employees created or updated on or after this date."
        ),
    ),
    format: Literal["csv", "xlsx"] = Query(default="csv"),
    db: Session = Depends(get_db),
):
    query = select(Employee)
    if changed_since:
        query = query.where(
            (Employee.created_at >= changed_since)
            | (Employee.updated_at >= datetime.combine(changed_since, time.min))
        )
    records = db.scalars(query.order_by(Employee.employee_id)).all()
    fields = (
        "employee_id", "first_name", "last_name", "work_email",
        "department_id", "role_id", "hire_date", "exit_date",
    )
    rows = [{field: _serialize(getattr(record, field)) for field in fields} for record in records]
    return _export_response(format, "employees", fields, rows)


@router.get("/payroll", dependencies=[Depends(require_roles("ADMIN", "HR"))])
def export_payroll(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    changed_since: date | None = Query(
        default=None,
        description="Include payroll items whose run was created on or after this date.",
    ),
    format: Literal["csv", "xlsx"] = Query(default="csv"),
    db: Session = Depends(get_db),
):
    query = select(PayrollItem)
    if changed_since:
        query = query.join(PayrollRun).where(
            PayrollRun.created_at >= datetime.combine(changed_since, time.min)
        )
    if start_date:
        query = query.where(PayrollItem.period_start >= start_date)
    if end_date:
        query = query.where(PayrollItem.period_end <= end_date)
    records = db.scalars(query.order_by(PayrollItem.payroll_item_id)).all()
    fields = (
        "payroll_item_id", "run_id", "employee_id", "period_start", "period_end",
        "gross_pay", "total_deductions", "net_pay",
    )
    rows = [{field: _serialize(getattr(record, field)) for field in fields} for record in records]
    return _export_response(format, "payroll", fields, rows)


@router.get("/ledger", dependencies=[Depends(require_roles("ADMIN", "HR"))])
def export_ledger(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    changed_since: date | None = Query(
        default=None,
        description="Include journal entries created on or after this date.",
    ),
    format: Literal["csv", "xlsx"] = Query(default="csv"),
    db: Session = Depends(get_db),
):
    query = select(JournalEntry)
    if changed_since:
        query = query.where(
            JournalEntry.created_at >= datetime.combine(changed_since, time.min)
        )
    if start_date:
        query = query.where(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.where(JournalEntry.entry_date <= end_date)
    entries = db.scalars(query.order_by(JournalEntry.entry_id)).all()
    fields = (
        "entry_id", "entry_date", "posting_period", "financial_year",
        "description", "source_type", "source_id", "status",
        "total_debit", "total_credit",
    )
    rows = [{field: _serialize(getattr(record, field)) for field in fields} for record in entries]
    return _export_response(format, "ledger", fields, rows)
