import csv
import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TypedDict

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.orm import Session

from .models import Employee
from .payroll_service import (
    PayrollError,
    PayrollNotFoundError,
    calculate_payroll,
)


RESULT_COLUMNS = (
    "employee_id",
    "run_id",
    "gross_pay",
    "total_deductions",
    "net_pay",
)
EXCEPTION_COLUMNS = ("employee_id", "run_id", "reason")
COMPARISON_COLUMNS = (
    "employee_id",
    "run_id",
    "source_reference",
    "status",
    "gross_pay_delta",
    "total_deductions_delta",
    "net_pay_delta",
    "reason",
)
INPUT_COLUMNS = (
    "employee_id",
    "run_id",
    "variable_pay",
    "variable_pay_type",
    "tds",
    "other_deductions",
    "source_reference",
)
REFERENCE_COLUMNS = (
    "employee_id",
    "run_id",
    "gross_pay",
    "total_deductions",
    "net_pay",
)
CENT = Decimal("0.01")
COMPARISON_TOLERANCE = CENT


class PayrollInputs(TypedDict):
    variable_pay: Decimal
    variable_pay_type: str | None
    tds: Decimal
    other_deductions: Decimal


def _read_csv(
    path: Path,
    required_columns: tuple[str, ...],
) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise ValueError(f"{path.name} has no header row")
            missing = set(required_columns) - set(reader.fieldnames)
            if missing:
                raise ValueError(
                    f"{path.name} is missing required column(s): "
                    + ", ".join(sorted(missing))
                )
            return list(reader)
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc


def _unique_by_key(
    rows: list[dict[str, str]],
    *,
    key_columns: tuple[str, str],
    file_name: str,
) -> dict[tuple[str, str], dict[str, str]]:
    keyed: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (
            (row.get(key_columns[0]) or "").strip(),
            (row.get(key_columns[1]) or "").strip(),
        )
        if not all(key):
            raise ValueError(
                f"{file_name} contains a row with an empty "
                f"{key_columns[0]} or {key_columns[1]}"
            )
        if key in keyed:
            raise ValueError(
                f"{file_name} contains duplicate record for "
                f"{key_columns[0]}={key[0]}, {key_columns[1]}={key[1]}"
            )
        keyed[key] = row
    return keyed


def _money(value: str | None, *, field: str) -> Decimal:
    try:
        amount = Decimal((value or "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal amount") from exc
    if not amount.is_finite():
        raise ValueError(f"{field} must be a finite decimal amount")
    return amount


def _input_values(
    row: Mapping[str, str],
) -> tuple[PayrollInputs | None, str | None]:
    missing = [
        field
        for field in (
            "variable_pay",
            "tds",
            "other_deductions",
            "source_reference",
        )
        if not (row.get(field) or "").strip()
    ]
    if missing:
        return None, (
            "Independent payroll input is missing: "
            + ", ".join(missing)
        )

    try:
        values: PayrollInputs = {
            "variable_pay": _money(row["variable_pay"], field="variable_pay"),
            "variable_pay_type": (row.get("variable_pay_type") or "").strip()
            or None,
            "tds": _money(row["tds"], field="tds"),
            "other_deductions": _money(
                row["other_deductions"], field="other_deductions"
            ),
        }
    except ValueError as exc:
        return None, str(exc)
    return values, None


def _unsupported_rate_reason(db: Session, period_end: date) -> str | None:
    bind = db.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("statutory_rates"):
        return None

    table = Table("statutory_rates", MetaData(), autoload_with=bind)
    rows = db.execute(
        select(
            table.c.parameter,
            table.c.effective_from,
            table.c.note,
        ).where(table.c.effective_from <= period_end)
    ).all()
    latest: dict[str, tuple[date, str]] = {}
    for parameter, effective_from, note in rows:
        previous = latest.get(parameter)
        if previous is None or effective_from > previous[0]:
            latest[parameter] = (effective_from, str(note or ""))

    unsupported = sorted(
        parameter
        for parameter, (_effective_from, note) in latest.items()
        if "sample" in note.lower() or "training" in note.lower()
    )
    if unsupported:
        return (
            "Unsupported statutory policy: source marks rate(s) as "
            "sample/training: "
            + ", ".join(unsupported)
        )
    return None


def _format_money(value: Decimal) -> str:
    return format(value.quantize(CENT), ".2f")


def _write_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def run_batch_validation(
    db: Session,
    *,
    data_dir: Path,
    output_dir: Path,
    payroll_inputs_path: Path | None = None,
) -> dict[str, object]:
    """Calculate only rows with explicit independent payroll inputs."""
    data_dir = Path(data_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = {
        "results": output_dir / "payroll_results.csv",
        "exceptions": output_dir / "payroll_exceptions.csv",
        "comparisons": output_dir / "payroll_comparison.csv",
        "summary": output_dir / "payroll_summary.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing:
        raise FileExistsError(
            "Refusing to overwrite existing output file(s): "
            + ", ".join(existing)
        )

    run_rows = _read_csv(
        data_dir / "payroll_runs.csv",
        ("run_id", "period_start", "period_end"),
    )
    runs: dict[str, tuple[date, date]] = {}
    for row in run_rows:
        run_id = row["run_id"].strip()
        if not run_id or run_id in runs:
            raise ValueError(
                "payroll_runs.csv contains an empty or duplicate run_id"
            )
        try:
            runs[run_id] = (
                date.fromisoformat(row["period_start"]),
                date.fromisoformat(row["period_end"]),
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid period dates for payroll run {run_id}"
            ) from exc

    reference_rows = _read_csv(
        data_dir / "payroll_items.csv",
        REFERENCE_COLUMNS,
    )
    references = _unique_by_key(
        reference_rows,
        key_columns=("employee_id", "run_id"),
        file_name="payroll_items.csv",
    )

    inputs_path = payroll_inputs_path or data_dir / "payroll_inputs.csv"
    if payroll_inputs_path is not None and not inputs_path.is_file():
        raise ValueError(
            f"Independent payroll input file not found: {inputs_path}"
        )
    if inputs_path.exists():
        input_rows = _read_csv(inputs_path, INPUT_COLUMNS)
        independent_inputs = _unique_by_key(
            input_rows,
            key_columns=("employee_id", "run_id"),
            file_name=inputs_path.name,
        )
    else:
        independent_inputs = {}

    employees = db.scalars(
        select(Employee).order_by(Employee.employee_id)
    ).all()
    result_rows: list[dict[str, object]] = []
    exception_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []
    processed = 0
    comparison_counts = {
        "matched": 0,
        "mismatched": 0,
        "reference_missing": 0,
        "reference_invalid": 0,
    }

    for run_id, (period_start, period_end) in runs.items():
        for employee in employees:
            if employee.hire_date > period_end or (
                employee.exit_date is not None
                and employee.exit_date < period_start
            ):
                continue
            processed += 1
            key = (employee.employee_id, run_id)
            input_row = independent_inputs.get(key)
            if input_row is None:
                exception_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "reason": (
                            "Missing independent payroll input record "
                            "(variable_pay, TDS, and other_deductions "
                            "cannot be inferred)"
                        ),
                    }
                )
                continue

            input_values, input_error = _input_values(input_row)
            if input_error:
                exception_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "reason": input_error,
                    }
                )
                continue

            unsupported_policy = _unsupported_rate_reason(db, period_end)
            if unsupported_policy:
                exception_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "reason": unsupported_policy,
                    }
                )
                continue

            try:
                calculation = calculate_payroll(
                    db,
                    employee_id=employee.employee_id,
                    period_start=period_start,
                    period_end=period_end,
                    **input_values,
                )
            except (PayrollError, PayrollNotFoundError) as exc:
                exception_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "reason": str(exc),
                    }
                )
                continue

            result = {
                "employee_id": employee.employee_id,
                "run_id": run_id,
                "gross_pay": _format_money(calculation["gross_pay"]),
                "total_deductions": _format_money(
                    calculation["total_deductions"]
                ),
                "net_pay": _format_money(calculation["net_pay"]),
            }
            result_rows.append(result)

            reference = references.get(key)
            if reference is None:
                comparison_counts["reference_missing"] += 1
                comparison_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "source_reference": input_row["source_reference"],
                        "status": "REFERENCE_MISSING",
                        "gross_pay_delta": "",
                        "total_deductions_delta": "",
                        "net_pay_delta": "",
                        "reason": "No matching payroll_items.csv row",
                    }
                )
                continue

            try:
                deltas = {
                    field: Decimal(str(result[field]))
                    - _money(reference[field], field=field)
                    for field in (
                        "gross_pay",
                        "total_deductions",
                        "net_pay",
                    )
                }
            except ValueError as exc:
                comparison_counts["reference_invalid"] += 1
                comparison_rows.append(
                    {
                        "employee_id": employee.employee_id,
                        "run_id": run_id,
                        "source_reference": input_row["source_reference"],
                        "status": "REFERENCE_INVALID",
                        "gross_pay_delta": "",
                        "total_deductions_delta": "",
                        "net_pay_delta": "",
                        "reason": str(exc),
                    }
                )
                continue

            matched = all(
                abs(delta) <= COMPARISON_TOLERANCE
                for delta in deltas.values()
            )
            status = "MATCH" if matched else "MISMATCH"
            comparison_counts[
                "matched" if matched else "mismatched"
            ] += 1
            comparison_rows.append(
                {
                    "employee_id": employee.employee_id,
                    "run_id": run_id,
                    "source_reference": input_row["source_reference"],
                    "status": status,
                    "gross_pay_delta": _format_money(deltas["gross_pay"]),
                    "total_deductions_delta": _format_money(
                        deltas["total_deductions"]
                    ),
                    "net_pay_delta": _format_money(deltas["net_pay"]),
                    "reason": "",
                }
            )

    _write_csv(output_paths["results"], RESULT_COLUMNS, result_rows)
    _write_csv(output_paths["exceptions"], EXCEPTION_COLUMNS, exception_rows)
    _write_csv(
        output_paths["comparisons"],
        COMPARISON_COLUMNS,
        comparison_rows,
    )
    summary: dict[str, object] = {
        "runs": len(runs),
        "processed": processed,
        "successful": len(result_rows),
        "skipped": len(exception_rows),
        "errors": 0,
        "comparison": comparison_counts,
        "outputs": {name: str(path) for name, path in output_paths.items()},
    }
    with output_paths["summary"].open(
        "x", encoding="utf-8", newline="\n"
    ) as output:
        json.dump(summary, output, indent=2)
        output.write("\n")
    return summary
