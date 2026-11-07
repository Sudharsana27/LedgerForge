# LF-06 Attendance Hand-Check

## Source and method

The source is `../03_Data/csv/attendance.csv`; the month checked is April
2025. I filtered the CSV independently by `employee_id` and the
`2025-04-` attendance-date prefix, then counted one row per employee/date.
The source has no duplicate employee/date pairs for this month.

The calculations are:

- `days_present`: rows whose source status is `PRESENT`.
- `work_from_home_days`: rows whose source status is `WFH`.
- `absent_days`: `ABSENT_LOP` counts as 1 day and `HALF_DAY_UNPAID` as 0.5;
  leave statuses are not treated as absences.
- `late_days`: rows with `late_flag == "Y"`.
- `overtime_hours`: sum of the explicitly supplied `overtime_hours`, treating
  null as 0.
- `missing_checkout_count`: rows with
  `data_quality_flag == "MISSING_CHECKOUT"`.

The API values below were obtained from
`GET /attendance/{employee_id}/monthly-summary?month=2025-04` after loading
the selected source rows into an isolated SQLite test database.

## Comparison

Difference is application value minus independently counted CSV value.

| Employee | Metric | CSV expected | Application | Difference | Result |
|---|---|---:|---:|---:|---|
| EMP-0002 | Days present | 2 | 2 | 0 | PASS |
| EMP-0002 | Work-from-home days | 18 | 18 | 0 | PASS |
| EMP-0002 | Absent days | 0 | 0 | 0 | PASS |
| EMP-0002 | Late days | 1 | 1 | 0 | PASS |
| EMP-0002 | Overtime hours | 0 | 0 | 0 | PASS |
| EMP-0002 | Missing-checkout count | 0 | 0 | 0 | PASS |
| EMP-0004 | Days present | 12 | 12 | 0 | PASS |
| EMP-0004 | Work-from-home days | 5 | 5 | 0 | PASS |
| EMP-0004 | Absent days | 0 | 0 | 0 | PASS |
| EMP-0004 | Late days | 0 | 0 | 0 | PASS |
| EMP-0004 | Overtime hours | 0 | 0 | 0 | PASS |
| EMP-0004 | Missing-checkout count | 0 | 0 | 0 | PASS |
| EMP-0006 | Days present | 18 | 18 | 0 | PASS |
| EMP-0006 | Work-from-home days | 1 | 1 | 0 | PASS |
| EMP-0006 | Absent days | 0 | 0 | 0 | PASS |
| EMP-0006 | Late days | 1 | 1 | 0 | PASS |
| EMP-0006 | Overtime hours | 0 | 0 | 0 | PASS |
| EMP-0006 | Missing-checkout count | 0 | 0 | 0 | PASS |

Each employee has 20 recorded rows in the month. April 2025 has 22 Monday–
Friday dates; the supplied global calendar marks April 14 and April 18 as
holidays, leaving 20 working days.

## Reproduce the CSV-side calculation

Run from the project root with Pandas installed and the supplied data
directory available:

```python
from pathlib import Path
import pandas as pd

rows = pd.read_csv(
    Path("../03_Data/csv/attendance.csv"),
    usecols=[
        "employee_id", "attendance_date", "status", "late_flag",
        "overtime_hours", "data_quality_flag",
    ],
)
rows = rows[
    rows["employee_id"].isin(["EMP-0002", "EMP-0004", "EMP-0006"])
    & rows["attendance_date"].str.startswith("2025-04-")
]
for employee_id, group in rows.groupby("employee_id"):
    print(
        employee_id,
        {
            "days_present": int((group["status"] == "PRESENT").sum()),
            "work_from_home_days": int((group["status"] == "WFH").sum()),
            "absent_days": int((group["status"] == "ABSENT_LOP").sum())
            + 0.5 * int((group["status"] == "HALF_DAY_UNPAID").sum()),
            "late_days": int((group["late_flag"] == "Y").sum()),
            "overtime_hours": float(group["overtime_hours"].fillna(0).sum()),
            "missing_checkout_count": int(
                (group["data_quality_flag"] == "MISSING_CHECKOUT").sum()
            ),
        },
    )
```

The same employee/month values are regression-tested in
`tests/test_attendance_leave.py`.
