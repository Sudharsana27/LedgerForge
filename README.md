# LedgerForge — Employee, Payroll & Accounting API

LedgerForge is a Python-based backend project developed as part of the Aura Workforce Python Developers training track. It evolves from a FastAPI starter application into an employee management, salary, attendance, payroll, and accounting platform.

The project focuses on REST API development, relational database modelling, data seeding, effective-dated salary structures, salary revision history, and automated testing.

## Project Information

| Item | Details |
|---|---|
| Project | LedgerForge |
| Track | Aura Workforce — Python Developers |
| Language | Python |
| Framework | FastAPI |
| ORM | SQLAlchemy |
| Validation | Pydantic |
| Database | SQLite starter configuration |
| Migrations | Alembic |
| Testing | Pytest |
| Repository | [05_Starter_Project](https://github.com/Sudharsana27/05_Starter_Project) |
| Phase tag | `phase-1` |
| Current task branch | `lf-05-salary-structures` |

**Training project:** All company and business data used in LedgerForge is fictional and intended for educational purposes only.

## Features

### Application foundation
- FastAPI application with interactive Swagger documentation.
- Health-check endpoint at `GET /health`.
- Environment-based configuration.
- SQLAlchemy database integration.
- Alembic migration support.
- Git-based development workflow.

### Data management
- Department, employee, role, and employee-assignment models.
- CSV data seeding support.
- Relational database constraints and relationships.
- Employee and department API functionality.

### Employee and team management
- Employee creation, retrieval, and update functionality.
- Employee search, department filtering, and pagination.
- Manager–team relationships using employee identifiers.
- Team-member retrieval.
- Soft-delete support using an employee exit date.

### Salary structure and revision
- SQLAlchemy models for salary components, salary structures, and salary revisions.
- Effective-date-based salary structure retrieval.
- Salary revision functionality that closes previous records and creates new records.
- Revision history with reasons for changes.
- Automated tests for salary API functionality.

### Attendance and leave (LF-06)
- Attendance date-range retrieval and per-employee monthly summaries.
- Leave type and balance listings.
- Leave requests with overlap checks, approval and rejection transitions.
- Balance validation at application and atomic balance deduction at approval.
- Weekends and supplied holiday dates excluded from leave-day counts.

### Payroll calculation (LF-07)
- Source-supported monthly payroll calculations with explicit inputs for
  deductions that the supplied source files do not define.

## LF-07 Payroll Calculation

`POST /payroll/calculate` calculates a single complete calendar-month payroll
result. It uses the employee's effective fixed salary structure, recorded
attendance loss-of-pay statuses, eligible overtime, and the effective rows in
the seeded `statutory_rates` table. The JSON response includes calculation
fields but is not a full `payroll_items.csv` export. The endpoint is stateless:
it does not persist payroll runs or payroll items, so a repeat request
recalculates rather than creating duplicate database records.

Example request (the monetary inputs below are required even when their value
is zero):

```json
{
  "employee_id": "EMP-0002",
  "period_start": "2025-04-01",
  "period_end": "2025-04-30",
  "variable_pay": "0",
  "variable_pay_type": null,
  "tds": "0",
  "other_deductions": "0"
}
```

`variable_pay`, `tds`, and `other_deductions` are explicit request inputs:
the source CSV set has no independent bonus/incentive or loan-repayment
records, and the supplied data does not define the TDS annualization,
withholding, or marginal-relief procedure. Positive variable pay also requires
`variable_pay_type`. No value is silently assumed for these fields, and the
engine does not calculate income tax.

The supported formulas follow the source data:

- Fixed salary components are read from the effective salary structure and
  prorated by `payable_days / calendar_days`. Employment days are inclusive of
  hire and exit dates. `ABSENT_LOP` and `UNPAID_LEAVE` count as one LOP day;
  `HALF_DAY_UNPAID` counts as one half day; paid leave, present, and WFH do not
  reduce pay. Missing attendance is an error; unrecorded dates are not
  inferred to be absences. Duplicate employee/date rows and unknown
  attendance statuses fail explicitly. Approved leave is consumed through
  attendance statuses (`PAID_LEAVE` or `UNPAID_LEAVE`); the engine does not
  independently reinterpret leave requests. In the supplied data, approved
  leave overlaps 7,037 paid-leave attendance rows and 129 unpaid-leave rows,
  but pending, rejected, and cancelled requests also overlap some
  `PAID_LEAVE` attendance. Those conflicts require source-data review.
- Attendance overtime is summed, capped by the effective
  `OT_MONTHLY_CAP_HOURS`, and paid only for an overtime-eligible salary role
  using monthly fixed gross / `WORKING_HOURS_PER_MONTH` times
  `OT_MULTIPLIER`.
- Employee and employer PF use the effective employee/employer rates and
  `PF_WAGE_CEILING`, subject to the employee's PF flag. ESI uses gross pay and
  is gated by the employee ESI flag and full-month fixed-gross wage limit.
  Professional tax applies at the effective gross threshold and monthly rate.
- The engine uses `Decimal` throughout. Currency components and percentage or
  overtime amounts are rounded to two decimal places with `ROUND_HALF_UP`;
  fixed-component calculations are rounded per component before summation.
  Independent reconstruction from employee hire/exit dates, effective salary
  revisions and structures, and attendance matches the five fixed component
  amounts, monthly fixed gross, earned fixed pay, LOP days, and capped
  overtime hours on all 7,340 payroll rows. These are source-data
  reconciliations, not approval of payroll policy or validation of all
  payroll-item totals.

The supplied statutory rates and tax slabs are explicitly marked as sample
training data, not confirmed production policy. The calculation uses the
effective statutory rows available in the database; no tax slab calculation
is performed. In the payroll reference, 44 rows contain employee and employer
ESI although the corresponding employee flag is `N`. They belong to four
employees: EMP-0131, EMP-0137, and EMP-0481 have 12 such rows each, and
EMP-0633 has 8. All 44 amounts match the supplied 0.75% employee and 3.25%
employer rates applied to reference gross, and all have fixed gross within
the sample 21,000 limit. However, 36 additional `N`-flag rows within that
limit have no ESI. The employee table has no effective-dated eligibility
history, and payroll items contain no eligibility decision. The reference
therefore conflicts with the current flag-gated formula and does not
consistently follow a threshold-only interpretation. This is an unresolved
source-data/policy inconsistency; available data cannot establish whether
flags are stale, deductions are wrong, or another eligibility decision was
used. The engine honors the explicit employee flag and does not alter values
to force a match.

The supplied overtime formula matches 7,338 of 7,340 reference overtime-pay
amounts using `ROUND_HALF_UP`. Two are one paisa lower in the reference:
`PI-002908` (`EMP-0307`, `PR-2025-11`) computes 4,898.625, and `PI-006310`
(`EMP-0535`, `PR-2026-07`) computes 6,361.125. There are 24 exact half-cent
cases where `ROUND_HALF_UP` and `ROUND_HALF_EVEN` differ; 22 reference amounts
match HALF_UP and these two match HALF_EVEN. The data therefore has a dominant
HALF_UP pattern but does not establish one authoritative tie-breaking policy.
The implementation retains HALF_UP pending a business decision.

Three reference rows also have a role mismatch between the effective
assignment and salary revision; the payroll role and overtime eligibility use
the dated employee assignment, which matches the reference role. A salary
revision starting partway through a month, conflicting effective salary rows,
missing attendance, or unavailable statutory inputs produces an explicit
error rather than a guessed result. Reference item `PI-003864` for
`EMP-0566` (`PR-2026-01`) has one employed day but no attendance record for
that day. The calculation therefore fails with a missing-attendance error;
the engine does not infer a status or salary adjustment.

The project checkout does not contain `verify_ledgerforge.py` or the LF-07
playbook. The source `payroll_items.csv` contains 7,340 rows across 18 monthly
periods from April 2025 through September 2026. The official verifier accepts
a result CSV with `employee_id`, `run_id`, `gross_pay`, `total_deductions`,
and `net_pay`, and is run with
`python verify_ledgerforge.py payroll <results.csv> --data <csv-directory>`.
Independent variable-pay and loan inputs and an approved TDS policy remain
unavailable. The source `payroll_items.csv` schema contains
these fields, which any future reconciliation export must account for:
`payroll_item_id`, `run_id`, `employee_id`, `period_start`, `period_end`,
`department_id`, `role_id`, `calendar_days`, `days_employed`, `lop_days`,
`payable_days`, `monthly_fixed_gross`, `basic`, `hra`, `conveyance`,
`medical`, `special_allowance`, `earned_fixed_pay`, `overtime_hours_paid`,
`overtime_pay`, `variable_pay`, `variable_pay_type`, `gross_pay`,
`pf_employee`, `esi_employee`, `professional_tax`, `tds`,
`other_deductions`, `total_deductions`, `net_pay`, `pf_employer`,
`esi_employer`, `employer_cost`, and `calculation_note`. The current API
does not provide this complete export. Official payroll reconciliation remains
blocked; no overall match percentage is claimed. The 1,152 nonzero
variable-pay reference rows total 59,696,588.35;
performance reviews do not contain award decisions, amounts, or commission
sales, so variable pay remains unsupported. TDS has 2,726 nonzero rows
totaling 84,411,569.12 but no employee declarations, regime elections, or
approved tax rules. Other deductions have 127 nonzero rows totaling 885,500
and no loan/advance ledger or repayment authorizations. These amounts can be
checked for arithmetic consistency with the payroll item totals, but not
independently derived or validated from the supplied source records.

### Source reconciliation versus payroll policy validation

The independent investigation in
[`artifacts/phase2/task7/source-data-investigation.md`](./artifacts/phase2/task7/source-data-investigation.md)
compares source-derived fixed salary, attendance LOP, and capped overtime
hours against the payroll reference. All 7,340 rows match those source-derived
components/hours, and summing the payroll items agrees exactly with all 18
`payroll_runs.csv` aggregates. These checks show consistency between the
available source records and reference totals; they do not prove that the
reference's variable pay, TDS, other deductions, or sample statutory rules
are correct or approved. A complete independent calculation or full 7,340-row
payroll validation is not claimed.

### Independent batch validation

Run the batch validator against a database already loaded with the employee,
salary, assignment, attendance, and statutory source tables:

```powershell
python -m scripts.validate_payroll `
  --data-dir C:\GrowMar\03_Data\csv `
  --output-dir C:\path\to\new-payroll-validation
```

The output directory must not already contain any of the generated output
files. The validator reads `payroll_runs.csv` to determine periods and
employees from the independently loaded employee data. `payroll_items.csv` is
read only as the comparison reference. Successful calculations are written to
`payroll_results.csv` with the official verifier's required five columns;
`payroll_comparison.csv` records the reference deltas, and
`payroll_exceptions.csv` records each skipped employee/run and reason.
`payroll_summary.json` reports processed, successful, skipped, error, and
comparison counts.

Because the supplied data has no independent employee-period bonus, TDS, or
loan-recovery records, a successful calculation requires a separate
`payroll_inputs.csv` containing `employee_id`, `run_id`, `variable_pay`,
`variable_pay_type`, `tds`, `other_deductions`, and a non-empty
`source_reference`. Monetary fields must be explicitly supplied, including
explicit zeroes; missing amounts are not treated as zero. The file may be
placed in the data directory or supplied with `--payroll-inputs`. The batch
validator also skips periods whose effective statutory-rate notes identify
the rates as sample/training data. No approved independent input or approved
statutory rates are currently supplied, so a run without those sources will
produce no successful rows. This workflow does not claim complete validation
of the 7,340 payroll reference rows.

## LF-08 Payslips

`GET /payslips/{employee_id}/{run_id}` produces a PDF from a typed payslip
result. The service reads the period from the matching `payroll_runs` row,
checks that the employee has a `payroll_items` membership row for that run,
then calculates the earnings and deductions through LF-07
`calculate_payroll`. It does not use reference gross, deduction, or net
amounts as calculation inputs. The PDF is generated with the project-owned
ReportLab template and includes employee details, the period, earnings,
deductions, gross salary, total deductions, and a visually emphasized net
pay. Monetary output uses Indian digit grouping and two decimal places (for
example, `₹1,23,456.00`). The host must have a rupee-glyph-capable TrueType
font installed; the current Windows environment uses Nirmala UI.

The current source data has no independent variable-pay, TDS, or other
deduction input service. To avoid silently assuming zero, payslip calculation
is currently enabled only for the three LF-08 comparison cases below, and
only while their `payroll_items` source rows confirm all three inputs are
zero. The amounts supplied to the engine are explicit zero inputs; reference
gross, deductions, and net are used only after calculation for comparison.
Other employee/run requests receive `503` until authoritative calculation
inputs are integrated.

| Source payroll item | Run / employee | Calculated gross | Calculated deductions | Calculated net | Source comparison |
|---|---|---:|---:|---:|---|
| `PI-000151` | `PR-2025-04` / `EMP-0294` | ₹19,949.10 | ₹1,063.30 | ₹18,885.80 | Matches source totals |
| `PI-000193` | `PR-2025-04` / `EMP-0365` | ₹37,313.33 | ₹1,991.04 | ₹35,322.29 | Matches source totals |
| `PI-000014` | `PR-2025-04` / `EMP-0031` | ₹29,841.91 | ₹1,560.44 | ₹28,281.47 | Matches source totals |

These are three selected comparisons, not evidence that all payroll periods
are reconciled. LF-07 limitations still apply: the source has conflicting ESI
records, two one-paisa overtime rounding differences, one missing attendance
record (`PI-003864`), no independent variable-pay/TDS/loan inputs for general
calculation, and sample statutory rates. Official reconciliation remains
blocked because the verifier and complete payroll calculation inputs are
unavailable.

Payslip access fails closed. The route requires an
`AuthenticatedPrincipal` from `get_authenticated_principal`; that dependency
currently returns `401` because the project has no implemented authentication
provider or trusted principal source. When an authentication provider is
integrated, authorization permits the employee whose ID owns the payslip or a
principal whose verified role is exactly `HR`. `ADMIN` is not treated as HR.
Tests inject trusted principals only to exercise the policy; this is not a
production login mechanism. Consequently, no user can fetch a payslip through
the current production configuration until authentication is integrated.

PDF generation and parsing are tested with ReportLab and pypdf. Install the
declared dependencies from `requirements.txt`; run the focused payslip tests
with:

```powershell
python -m pytest tests/test_payslips.py -q
```

Before LF-08, the LF-07 focused payroll tests completed with **31 passed**
and the full suite with **72 passed**. After LF-08, the payslip tests
completed with **11 passed** and the full suite with **83 passed**. Test runs
reported one upstream Starlette/httpx deprecation warning.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Application logic |
| FastAPI | REST API development |
| SQLAlchemy | Database models and queries |
| Pydantic | Request validation and response schemas |
| SQLite | Local development database |
| Alembic | Database schema migrations |
| Pytest | Automated testing |
| Git and GitHub | Version control and collaboration |

## Prerequisites

Install the following before running the project:

- Python 3.12 recommended.
- Git.
- Visual Studio Code or another Python IDE.
- PowerShell, Command Prompt, or another terminal.

Docker Desktop is required only for workflows that use the project's Docker configuration.

## Getting Started

### 1. Clone the repository

```powershell
git clone https://github.com/Sudharsana27/05_Starter_Project.git
cd 05_Starter_Project
```

### 2. Create a virtual environment

```powershell
python -m venv .venv
```

### 3. Activate the virtual environment

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
```

### 4. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 5. Configure environment variables

Create a local `.env` file using the example configuration provided in the repository.

```powershell
Copy-Item .env.example .env
```

Review the database URL and other settings in `.env`. Keep secrets and environment-specific values out of Git.

### 6. Prepare the database

Use the project's Alembic migration workflow when setting up a fresh database:

```powershell
python -m alembic upgrade head
```

Follow the project's seeding instructions for the relevant dataset. The example seeder and the full CSV data seeder serve different purposes.

### 7. Start the API

```powershell
uvicorn app.main:app --reload
```

Open these addresses in your browser:

- API base URL: http://127.0.0.1:8000
- Interactive Swagger documentation: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

Keep the terminal running while testing the API. Press `Ctrl+C` to stop the server.

### 8. Run automated tests

```powershell
$testDb = "ledgerforge-tests-$([guid]::NewGuid().ToString('N')).db"
$env:DATABASE_URL = "sqlite:///./$testDb"
python -m pytest -q
Remove-Item -LiteralPath $testDb
```

To run the salary, department, and employee test suites specifically:

```powershell
$testDb = "ledgerforge-tests-$([guid]::NewGuid().ToString('N')).db"
$env:DATABASE_URL = "sqlite:///./$testDb"
python -m pytest tests/test_salary.py tests/test_departments.py tests/test_employees.py -q
Remove-Item -LiteralPath $testDb
```

The salary, department, and employee test suites returned **16 passed** in the recorded test run. Run the tests again after subsequent changes to confirm the current result.

For a safe full-suite run, use a unique SQLite file so the tests cannot touch
the development database:

```powershell
$testDb = "ledgerforge-tests-$([guid]::NewGuid().ToString('N')).db"
$env:DATABASE_URL = "sqlite:///./$testDb"
python -m pytest -q
Remove-Item -LiteralPath $testDb
```

The LF-06/full suite verification completed with **26 passed**. Pytest reported
one upstream Starlette/httpx deprecation warning.

## LF-06 Attendance and Leave

The API uses the supplied `attendance.csv`, `leave_types.csv`,
`leave_requests.csv`, `leave_balances.csv`, and `holidays.csv` columns. The
data dictionary is metadata and is not loaded as a business table.

### Routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/attendance/{employee_id}?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` | Attendance records for an inclusive date range |
| GET | `/attendance/{employee_id}/monthly-summary?month=YYYY-MM` | Monthly attendance summary |
| GET | `/leave/types` | Leave type policy data |
| GET | `/leave/balances/{employee_id}` | Leave balance snapshots |
| GET | `/leave/requests?employee_id=...&status=...` | Filter leave requests |
| POST | `/payroll/calculate` | Calculate one complete monthly payroll result; variable pay, TDS, and loan deductions are explicit inputs |
| POST | `/leave/requests` | Submit a leave request |
| GET | `/leave/requests/{request_id}` | Retrieve a request |
| POST | `/leave/requests/{request_id}/approve` | Approve a pending request |
| POST | `/leave/requests/{request_id}/reject` | Reject a pending request |

Example monthly summary:

```text
GET /attendance/EMP-0002/monthly-summary?month=2025-04
```

Example leave application:

```json
{
  "employee_id": "EMP-0002",
  "leave_type_code": "CL",
  "start_date": "2026-08-04",
  "end_date": "2026-08-05",
  "reason": "Personal leave"
}
```

The request is created with the source status `Pending`. Approval and rejection
accept an optional approver body such as `{"approver_id": "EMP-0004"}`. An
approver ID, if supplied, must identify an employee. The current API has no
authentication, so it does not infer an approver from a logged-in user.

### Attendance summary rules

- `calendar_days` is the number of dates in the month. `working_days` counts
  Monday through Friday, excluding dates in the supplied holiday table.
- `recorded_days` counts unique employee/date records. Duplicate records for
  the same employee and date fail explicitly instead of being double-counted.
- `days_present` counts source status `PRESENT`; `work_from_home_days` counts
  `WFH`; `attended_days` is their sum.
- `absent_days` counts `ABSENT_LOP` as one day and `HALF_DAY_UNPAID` as half a
  day. Paid and unpaid leave statuses are not inferred to be absence.
- `late_days` counts rows whose `late_flag` is `Y`. Overtime is the sum of the
  supplied `overtime_hours`; null values contribute zero and are not derived
  from check-in/check-out times.
- A `MISSING_CHECKOUT` data-quality flag increments
  `missing_checkout_count`. The record is not reclassified as absent, and the
  API does not invent a checkout time or overtime amount. The source contains
  198 such records; all have no checkout and explicitly report zero overtime.
- A month with no attendance records returns zero attendance metrics. It does
  not treat unrecorded calendar days as absences.

### Leave-day and balance rules

- Leave dates are inclusive. Saturday, Sunday, and supplied holiday dates are
  excluded; one date is excluded only once even if it is both a weekend and a
  holiday. A request containing no eligible weekday is rejected.
- The source has one holiday table and no employee-to-calendar or location
  mapping. All listed dates, including entries marked `Regional` or
  `Optional`, are therefore treated as organization-wide holidays. This is a
  documented dataset limitation, not a location-aware calendar.
- The balance data uses labels such as `FY2026-27`; the implementation treats
  an Indian financial year as April 1 through March 31. Leave requests crossing
  financial years are split for balance/quota validation and deductions.
- `CL`, `SL`, and `EL` use the matching `cl_balance`, `sl_balance`, and
  `el_balance` fields; approval decreases that balance and increases its
  corresponding used field. `ML` and `BL` have no per-employee balance
  columns. Their source policy notes describe 182 days per maternity
  entitlement and up to 3 days per bereavement event, so each new request must
  provide an `entitlement_reference`. Approved and pending requests with the
  same employee, leave type, and reference are counted across all financial
  years; ML quota measures calendar days to reflect the source's 26-week
  duration, while BL quota measures eligible leave days using the weekend and
  holiday exclusions above. The request's `days` value still reports eligible
  weekdays for both types, so ML's quota duration and returned `days` use
  different measures. Rejected requests release their quota. `LOP` is unpaid
  and has no balance deduction.
- The source leave-request CSV has no entitlement reference. Imported
  historical ML/BL rows therefore retain a null reference and cannot be
  reliably assigned to an entitlement or event. New requests for that employee
  and leave type are blocked until active imported rows are reconciled and
  assigned references, avoiding an uncounted prior entitlement. The source
  does not define how a new ML entitlement is identified per pregnancy/event,
  how split BL requests should identify one event, or how references should
  be verified; the API currently requires a caller-supplied reference. Confirm
  these policy details with HR, including whether BL's “days” means working
  or calendar days.
- Applying a request does not deduct the available balance. Pending requests
  of the same type reserve available days during validation. Approval rechecks
  availability and atomically updates the balance and request; rejected
  requests do not deduct a balance. The source `pending_days` field is refreshed
  from active Pending requests for each affected financial year; type-specific
  availability is calculated from the request rows because that summary field
  is not split by leave type.
- Only full-day requests are supported. The source request schema has no
  half-day field; supporting half-days would require an explicit duration
  field and corresponding half-day overlap, quota, and balance calculations.
- Leave applications and approvals serialize per employee before checking
  reservations. SQLite acquires a write reservation with `BEGIN IMMEDIATE`;
  PostgreSQL locks the employee row with `SELECT FOR UPDATE`. Both database
  families are supported for this locking path; other dialects fail explicitly
  rather than silently accepting a non-serialized reservation.
- Leave service operations own their transaction and require a SQLAlchemy
  session with no active transaction at entry. They commit on success and roll
  back on any error, releasing the SQLite write lock. If a caller already has
  a transaction, the service rejects the operation without rolling back or
  changing that caller's work. The FastAPI database dependency supplies a
  fresh session per request.

### Migration, seeding, and verification

Apply migrations before loading the CSVs:

```powershell
python -m alembic upgrade head
python -m scripts.seed
```

LF-06's migration creates typed tables on a fresh database. If a database
already contains the CSV seeder's generic LF-06 tables, it validates keys and
references, then rebuilds only those five tables to add primary keys, foreign
keys, indexes, and typed columns while preserving the records. The existing
organization migration adopts tables that are already present, addressing the
starter database's earlier migration-version mismatch. Its downgrade is
explicitly disabled because it cannot distinguish tables it
created from pre-existing tables; LF-06 and its follow-on migrations also
disable downgrades that could lose or invalidate data. Alembic downgrade
through these revisions is unsupported. The entitlement-reference revision
adds a nullable column so existing CSV rows remain loadable; historical ML/BL
rows without references require HR reconciliation.

The source `salary_structures.csv` contains five historical rows whose
`effective_to` precedes `effective_from`. The migration removes the ORM-level
date-range check so the full refresh can retain those source rows verbatim;
salary revisions created through the API continue to write valid effective
periods. The salary API will not return these empty historical periods as
effective on any date.

The full seeder remains a transactional full refresh: it deletes rows from its
known CSV tables and reloads them from the configured data directory. It does
not merge local-only rows, and rollback occurs if a delete or insert fails.
Foreign-key-dependent rows are inserted after their parents; salary revisions
are loaded before salary structures, which reference those revisions. Back up
the database before intentionally running the refresh. Attendance is read in
the existing 5,000-row chunks. Tables not represented by CSV files are not
deleted.

Verification against a disposable migrated SQLite database:

- Full test suite: **26 passed**, one Starlette/httpx deprecation warning.
- Full seeder: all 28 CSV table counts matched; attendance loaded **150,155**
  rows in **71.04 seconds** (attendance chunk processing time).
- SQLite integrity check: `ok`; foreign-key check: zero violations.
- Three independent April 2025 employee hand-counts: all metrics matched;
  details and reproduction method are in
  [docs/LF-06-attendance-hand-check.md](./docs/LF-06-attendance-hand-check.md).

The tests and full seeder were run against temporary databases. The existing
`ledgerforge.db` was not reset or overwritten.

## API Documentation

The application exposes interactive API documentation through Swagger at `/docs`.

The API includes functionality for:

| Area | Functionality |
|---|---|
| System | Health check |
| Departments | Department listing and lookup |
| Employees | Employee creation, retrieval, updates, search, and filtering |
| Teams | Retrieval of an employee's direct reports |
| Salary | Salary structure retrieval and salary revision operations |
| Attendance | Date-range records and monthly attendance summaries |
| Leave | Leave types/balances, requests, approval, and rejection |
| Payroll | Stateless monthly payroll calculation with explicit variable-pay, TDS, and loan-deduction inputs |

Consult `/docs` for the exact route paths, HTTP methods, request schemas, and response formats available in the current checkout.

## Salary Structure and Revision Design

Salary information is modelled using three main entities:

- **Salary components:** Represent individual elements of compensation.
- **Salary structures:** Represent the applicable salary components over an effective period.
- **Salary revisions:** Record changes to an employee's salary, including the revision date and reason.

The salary service supports retrieving the structure applicable to an employee on a specified date and revising salary records by closing the previous effective period and creating the new records.

Effective-date boundaries are important: the implementation and its tests should ensure that a date returns the correct structure and that salary revision history preserves previous changes.

## Project Structure

```text
05_Starter_Project/
├── app/
│   ├── config.py
│   ├── database.py
│   ├── attendance_service.py
│   ├── leave_service.py
│   ├── payroll_service.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── salary_service.py
│   └── routers/
│       ├── attendance.py
│       ├── departments.py
│       ├── employees.py
│       ├── leave.py
│       ├── payroll.py
│       └── salary.py
├── scripts/
├── tests/
│   ├── test_attendance_leave.py
│   ├── test_departments.py
│   ├── test_employees.py
│   ├── test_payroll.py
│   └── test_salary.py
├── alembic/
├── docs/
│   └── LF-06-attendance-hand-check.md
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Some directories may contain additional files as development continues.

## Development Guidelines

- Use a separate Git branch for each task.
- Use SQLAlchemy models for database entities and Pydantic schemas for request validation.
- Write automated tests for API endpoints and business rules.
- Use `Decimal` rather than floating-point arithmetic for monetary calculations.
- Use database migrations to manage schema changes.
- Validate effective-date ranges to avoid overlaps and incorrect salary history.
- Never commit `.env`, virtual environments, database files, or secrets.
- Commit and push completed work regularly.

## Git Workflow

Create a branch for a new task:

```powershell
git switch -c lf-06-next-task
```

Run tests and review changes:

```powershell
python -m pytest -q
git status
git diff
```

Stage only the files intended for the commit:

```powershell
git add README.md
git diff --cached --check
git diff --cached
```

Commit and push:

```powershell
git commit -m "docs: update LedgerForge README"
git push
```

For a new branch without an upstream, use:

```powershell
git push -u origin lf-06-next-task
```

## LF-09 Double-Entry Ledger Core

The ledger uses `chart_of_accounts`, `journal_entries`, and `journal_lines`.
Chart accounts retain their parent/child hierarchy. Journal line amounts and
entry totals use fixed-precision `NUMERIC(18, 2)` columns and Python `Decimal`
values; a line must contain a positive debit or credit, but not both.

`app.ledger_service.create_journal_entry(db, entry, lines)` validates the
account references and exact debit/credit totals, then writes the posted
entry and all its lines in one database transaction. A failed operation rolls
back the whole journal. The helper owns that transaction, so pass it a
SQLAlchemy session with no active transaction. Posted entries and their lines
cannot be changed, appended, or deleted through ORM unit-of-work or bulk ORM
operations; use
`reverse_journal_entry(...)` to create a new posted entry with opposite lines.
`account_balance(db, account, as_of_date)` returns the normal-side balance
through the supplied date. Group accounts include their descendants.

`app.payroll_ledger_service.post_payroll_run(db, run_id, created_by=...)`
posts an approved or paid payroll run atomically. It checks each employee's
gross, deductions, and net pay, then reconciles the run totals against the
payroll items before posting. Fixed earnings, overtime, variable pay, and
employer PF/ESI are debited to accounts 5001–5005 by department; net salary,
employee/employer PF and ESI, TDS, professional tax, and advance recovery are
credited to their corresponding payable/advance accounts. The journal entry
uses `source_type=PAYROLL_RUN` and the run ID as `source_id`. Existing linked
or source-matched posted entries are returned instead of duplicated. The
service uses the ledger's transaction-aware entry helper, so journal posting
and updating `payroll_runs.journal_entry_id` commit or roll back together.
Imported source runs already have linked journal entries; calling the service
for those runs will not create a second posting.

The task specifies a ledger service and data export, not HTTP routes; no
posting or balance API endpoint is exposed by this milestone.

The existing CSV seeder is a full refresh of all CSV-backed tables. It now
preserves ledger decimals and resolves the source chart CSV's `parent_code`
values ending in `.0` only when removing that suffix matches an existing
`account_code`. Do not run `python -m scripts.seed` against a development
database: use a disposable database because the seeder deletes and reloads all
CSV-backed tables.

To export the three ledger tables from a database already loaded with the
source records, choose a new or empty destination directory:

```powershell
python -m scripts.export_ledger --output-dir .\ledger_export
```

The exporter writes source-compatible `chart_of_accounts.csv`,
`journal_entries.csv`, and `journal_lines.csv`, with money rendered to two
decimal places. It refuses to overwrite any of those files.

## LF-10 Invoices, Payments, and Receivables

Authenticated client routes under `/clients` provide HR/admin-only creation,
retrieval, paginated listing, partial updates, and deletion when no invoices
reference the client. Invoice routes under `/invoices` support draft creation,
retrieval, listing by client/status, sending, payment recording, cancellation,
and overdue refresh using an explicit business date. The `/receivables` report
includes eligible open balances, including carried-in invoices without a
ledger-entry link. The service uses `Decimal` balances and excludes drafts,
paid invoices, and cancelled invoices.

Payment references are unique per invoice. The `e7c2d10f4b39` migration checks
for existing duplicate `(invoice_id, reference_no)` pairs before adding the
unique index; such duplicates must be reconciled before upgrading.

The official `verify_ledgerforge.py checks --data ...` check was run against
the preserved Task 10 validation export and passed 5/5 checks. This verifies
that export's ledger, payroll, receivables, employee, and termination-date
data; it is not a substitute for application API tests or a fresh database
import.

## Training Roadmap

| Milestones | Scope |
|---|---|
| LF-01 | Project bootstrap and repository setup |
| LF-02 | Employee, department, role, and assignment data model |
| LF-03 | One-command CSV data seeder |
| LF-04 | Employee and team APIs |
| LF-05 | Salary structures and revision history |
| LF-06–LF-08 | Attendance, leave, payroll, and payslips |
| LF-09–LF-12 | Accounting ledger, invoices, expenses, and payroll posting |
| LF-13–LF-16 | Authentication, tax reports, financial reports, and release candidate |
| LF-17–LF-20 | Deployment, reliability, exports, final audit, and submission |

## Current Development Status

The project has progressed beyond its original starter application. The branch
recorded for the preceding milestone is `lf-05-salary-structures`, which
contains the salary structure and revision API work.

The recorded verification run for the salary, department, and employee test
suites completed with 16 passing tests. LF-06 attendance and leave, LF-07
payroll calculation, LF-08 payslip generation, LF-09 double-entry ledger, and
LF-10 invoices, payments, and receivables are implemented in this checkout.
Expenses, broader reporting, and deployment remain later milestones.

## Learning Outcomes

This project provides practical experience with:

- Building REST APIs using FastAPI.
- Modelling relational data with SQLAlchemy.
- Validating input with Pydantic.
- Managing database schema changes with Alembic.
- Loading CSV data into a database.
- Writing automated tests using Pytest.
- Maintaining a task-based Git workflow.

---

**LedgerForge · Aura Workforce · Python Developers Training Track**
