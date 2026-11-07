# Task 7 Source Data Investigation

## Scope and method

Read-only investigation of the CSVs in `C:\GrowMar\03_Data\csv` and the
current payroll calculation rules in `app/payroll_service.py` and
`app/payroll_batch.py`. No code, source CSV, or database was changed. The
payroll item rows were used only as comparison values; none of their amounts
were calculation inputs.

The independent comparison used employee dates, salary revisions, salary
structures, salary component definitions, and attendance. It selected the
latest salary revision effective by the employee's last employed day in the
payroll period, then required fixed-earning structure rows to cover the
employee's employed dates. Fixed components were prorated by payable days
over calendar days and rounded per component to cents with `ROUND_HALF_UP`.
Attendance LOP was independently summed from `ABSENT_LOP`,
`UNPAID_LEAVE`, and `HALF_DAY_UNPAID`; overtime hours were summed from the
attendance records and capped at the supplied 50-hour monthly cap.

## Source file sizes and coverage

| CSV | Rows | Independent use / limitation |
|---|---:|---|
| `employees.csv` | 745 | Hire/exit dates and PF/ESI applicability flags. |
| `payroll_items.csv` | 7,340 | Comparison reference only; not used as a calculation input. |
| `payroll_runs.csv` | 18 | Periods and run-level totals for reconciliation. |
| `salary_structures.csv` | 12,295 | Effective-dated component amounts, employee and revision keys. |
| `salary_revisions.csv` | 2,459 | Effective revision selection and revision IDs. |
| `salary_components.csv` | 14 | Component type/fixed classification and descriptive rules. |
| `performance_reviews.csv` | 1,740 | Review dates and ratings; does not record award decisions or amounts. |
| `statutory_rates.csv` | 11 | Rates and thresholds, but all are labeled sample/training values. |
| `tax_parameters.csv` | 3 | Includes sample standard deduction and rebate threshold; no employee declarations or regime elections. |
| `tax_slabs.csv` | 14 | FY2025-26 and FY2026-27 slabs, explicitly marked sample training data. |
| `attendance.csv` | 150,155 | Dated status, LOP-related statuses, and overtime hours. |

The supplied list contains no employee-period bonus/commission award ledger,
sales results, loan/advance ledger, tax declaration/investment records, or
approved statutory/tax policy. A separate attendance-derived period result
can validate recorded statuses and hours, but not facts absent from attendance.

## 1. Fixed-salary reconstruction

The effective-dated revision/structure relationship is sufficient to
independently reconstruct the five fixed components for each payroll item.
Across all **7,340 of 7,340** rows:

- The selected effective BASIC, HRA, CONV, MED, and SPECIAL amounts prorate
  to the reference component amounts with **zero component mismatches**.
- Their monthly sum matches `monthly_fixed_gross` with **zero mismatches**.
- Per-component prorated/rounded earnings sum to `earned_fixed_pay` with
  **zero mismatches**.

This is a fixed-salary calculation comparison. The same source policy
definitions in `salary_components.csv` describe the components (for example
fixed conveyance/medical amounts and SPECIAL as a balancing figure); those
descriptions are not independent approval records for payroll totals.

### Nine April 2025 employees without structure effective on April 1

The 386 rows in `PR-2025-04` include these nine employees whose structure
does not start until after April 1:

| Employee ID | Name | Hire date | Effective revision |
|---|---|---|---|
| EMP-0595 | Zoya Malhotra | 2025-04-02 | SR-02266 |
| EMP-0596 | Brinda Kamath | 2025-04-03 | SR-02268 |
| EMP-0597 | Ekta Murthy | 2025-04-03 | SR-02270 |
| EMP-0598 | Anjali Das | 2025-04-03 | SR-02272 |
| EMP-0599 | Karthik Thomas | 2025-04-08 | SR-02274 |
| EMP-0600 | Trisha Siddiqui | 2025-04-11 | SR-02276 |
| EMP-0601 | Suresh Ramachandran | 2025-04-14 | SR-02278 |
| EMP-0602 | Fathima Malhotra | 2025-04-15 | SR-02280 |
| EMP-0603 | Bhuvana Joseph | 2025-04-17 | SR-02281 |

Important distinction: these nine have **no salary structure effective on the
first day of the payroll month**, but they do have a structure effective from
their hire date and covering their employed days in April. Therefore they are
not missing an effective structure for the days they were employed, and their
fixed pay reconstructs from that hire-date structure.

Using a stricter definition requiring one structure to cover every date from
April 1 through April 30 finds 15 rows, not nine: the nine new hires above plus
six employees whose exit dates fall during April. Those six have effective
structures through their respective exit dates. The full-month criterion is
not appropriate for prorated new hires or leavers.

## 2. Attendance, LOP, and overtime

Across the 7,340 employee/run rows:

- Attendance-derived LOP matches `payroll_items.csv` `lop_days` on **7,340 /
  7,340** rows.
- Attendance overtime summed and capped at the supplied 50 hours matches
  `overtime_hours_paid` on **7,340 / 7,340** rows.
- There are **zero duplicate employee/date attendance records** in the
  payroll periods checked.
- Attendance independently contains **150,155** rows, including 82,052
  PRESENT, 59,087 WFH, 7,135 PAID_LEAVE, 1,180 ABSENT_LOP, 572
  HALF_DAY_UNPAID, and 129 UNPAID_LEAVE records.

These are checks of source-record aggregation and the supplied cap, not
confirmation that the sample cap or overtime eligibility policy is approved.
`overtime_hours_paid` is validated here as hours; the supplied multiplier,
divisor, and ROUND_HALF_UP pay formula produce two one-paisa differences:

| Payroll item | Employee / run | Computed OT pay | Reference OT pay | Difference |
|---|---|---:|---:|---:|
| PI-002908 | EMP-0307 / PR-2025-11 | 4,898.63 | 4,898.62 | +0.01 |
| PI-006310 | EMP-0535 / PR-2026-07 | 6,361.13 | 6,361.12 | +0.01 |

Both are exact half-cent cases; ROUND_HALF_EVEN would match these two
references, but no authoritative rounding policy was supplied. No rounding
rule was inferred or changed.

The supplied file list does not include an independent role/assignment source
with each role's `overtime_eligible` flag. Attendance therefore supports
validation of recorded hours, LOP, and the capped-hour comparison, but cannot
by itself prove that each employee was eligible to receive overtime.

## 3. Variable pay and deductions

### Variable pay

There are **1,152** nonzero variable-pay rows totaling **59,696,588.35**:

| Source label | Rows | Amount |
|---|---:|---:|
| Performance Bonus | 518 | 27,011,627.22 |
| Festival Bonus | 355 | 2,452,500.00 |
| Sales Incentive | 234 | 29,783,461.13 |
| Spot Award | 45 | 449,000.00 |

`performance_reviews.csv` contains employee, year, appraisal date, rating,
and rating label. It has no bonus approval, award amount, commission sales,
or mapping from a rating to an award. Although 1,055 of the nonzero variable
pay rows have a performance review in the same calendar year, that association
does not independently establish eligibility or amount. Thus no variable-pay
amount can be calculated or verified independently from the supplied
non-reference data.

### Deductions independently checkable as arithmetic vs policy

All **7,340** payroll item rows satisfy the arithmetic identities:

- `gross_pay = earned_fixed_pay + overtime_pay + variable_pay`
- `total_deductions = pf_employee + esi_employee + professional_tax + tds + other_deductions`
- `net_pay = gross_pay - total_deductions`

These identities verify internal arithmetic only; several right-hand-side
values originate in the comparison reference and are not independently
supported.

The sample statutory rates permit a conditional formula comparison, not
approval of the policy:

- **PF:** applying the supplied employee flag, 12% rate, 15,000 basic ceiling,
  and reconstructed prorated basic matches employee PF on all 7,340 rows
  (zero formula mismatches). Employer PF also has zero formula mismatches.
  The reference has 6,884 nonzero employee PF rows totaling 11,888,910.15.
  Since both rate and ceiling are explicitly sample/training values, this
  does not certify statutory correctness.
- **Professional tax:** applying the supplied 200-per-month rule at gross
  pay >= 25,000 matches all 7,340 rows (zero formula mismatches). The
  reference has 7,032 nonzero rows totaling 1,406,400. The rate and threshold
  are sample/training values.
- **ESI:** the source contains 104 nonzero employee ESI rows totaling
  16,274.31 and 104 nonzero employer ESI rows totaling 70,522.00. There are
  **44** payroll rows with nonzero ESI while the employee's `esi_applicable`
  flag is `N`; this conflicts with flag-based application and yields 44
  mismatches against the current flag-aware formula for both employee and
  employer ESI. A further **36** rows have flag `N`, fixed gross within the
  supplied 21,000 threshold, but zero ESI. That second group is consistent
  with honoring the flag but conflicts with applying the threshold alone.
  This source conflict and the sample rates prevent an authoritative ESI
  validation.
- **TDS/income tax:** 2,726 rows contain nonzero TDS totaling 84,411,569.12.
  Employee tax declarations, investment proofs, selected regime, other
  income, and authoritative year-specific rules are absent. All 14 supplied
  tax slab rows say they are sample training data; the parameter file also
  labels its standard deduction and rebate threshold as sample. TDS cannot
  be independently calculated or certified.
- **Other deductions/loans:** 127 rows contain other deductions totaling
  885,500. No loan, advance, repayment schedule, or deduction authorization
  source is among the supplied files. These amounts cannot be independently
  verified.

## 4. Payroll item and run-total comparisons

`payroll_runs.csv` has 18 monthly runs from April 2025 through September
2026. All **7,340** item rows are accounted for by those runs; aggregate
`employees_paid` equals 7,340. For each of the 18 runs, independently summing
the reference items produced exact equality with the run's:

- `total_gross`
- `total_deductions`
- `total_net`
- `total_employer_contributions`
- `total_employer_cost`

There are **zero run-level mismatches** for those fields. This demonstrates
that payroll item totals reconcile to the corresponding payroll run totals;
it does not independently validate the employee-item amounts that make up
those totals.

Across all payroll items, the reference totals are gross pay 849,626,960.27,
deductions 98,608,653.58, and net pay 751,018,306.69. Independent fixed
salary/attendance calculations support the fixed and LOP/hour inputs, but
there is no independent basis for all gross and deduction amounts because
variable pay, TDS, other deductions, and approved statutory policy are
missing.

## 5. Conclusion and limitations

**Fixed salary, LOP, and overtime hours can be independently reconstructed
and match all 7,340 rows under the stated component-rounding and supplied
overtime-cap assumptions.** The nine April 2025 new hires lack a structure
on April 1 but have valid structures from hire date. Payroll item arithmetic
and all run aggregates reconcile exactly.

**A complete independent payroll calculation or 7,340-row validation is not
possible from these files.** Variable-pay award evidence, tax declarations
and approved TDS policy, loan/advance deductions, and approved statutory
policies are missing. The conditional PF/PT/ESI checks do not replace those
approvals, and ESI has the documented source-data conflict. No overall
payroll match percentage is claimed.

## 6. Follow-up: ESI eligibility and overtime rounding

### The 44 ESI deductions with `esi_applicable = N`

The 44 rows are spread across **four employees**: EMP-0131 Aanya George,
EMP-0137 Fathima More, EMP-0481 Abhishek Philip, and EMP-0633 Vijay Selvam.
The first three have 12 such payroll rows each, from April 2025 through March
2026; EMP-0633 has 8, from August 2025 through March 2026. Each employee's
single `employees.csv` row has `esi_applicable = N`. The payroll-item schema
has no ESI eligibility flag, and the supplied employee data has no
effective-dated flag history.

For all 44:

- The independently reconstructed `monthly_fixed_gross` is at or below the
  supplied sample ESI wage limit of 21,000.
- The recorded employee ESI is exactly
  `ROUND_HALF_UP(gross_pay * 0.75 / 100, 0.01)`.
- The recorded employer ESI is exactly
  `ROUND_HALF_UP(gross_pay * 3.25 / 100, 0.01)`.
- Together the 44 rows carry employee ESI of **7,505.97** and employer ESI
  of **32,525.83**.

The gross pay in these comparisons is the payroll reference value; because
independent variable-pay amounts are absent, this rate-formula match does not
independently validate that gross-pay input or the statutory rates.

| Payroll item | Run | Employee | Fixed gross | Reference gross | Employee ESI | Employer ESI |
|---|---|---|---:|---:|---:|---:|
| PI-000068 | PR-2025-04 | EMP-0131 Aanya George | 19,383 | 31,527.20 | 236.45 | 1,024.63 |
| PI-000072 | PR-2025-04 | EMP-0137 Fathima More | 20,924 | 28,259.47 | 211.95 | 918.43 |
| PI-000277 | PR-2025-04 | EMP-0481 Abhishek Philip | 20,612 | 24,873.13 | 186.55 | 808.38 |
| PI-000454 | PR-2025-05 | EMP-0131 Aanya George | 19,383 | 20,714.68 | 155.36 | 673.23 |
| PI-000458 | PR-2025-05 | EMP-0137 Fathima More | 20,924 | 22,835.33 | 171.26 | 742.15 |
| PI-000659 | PR-2025-05 | EMP-0481 Abhishek Philip | 20,612 | 21,999.35 | 165.00 | 714.98 |
| PI-000838 | PR-2025-06 | EMP-0131 Aanya George | 19,383 | 21,433.13 | 160.75 | 696.58 |
| PI-000842 | PR-2025-06 | EMP-0137 Fathima More | 20,924 | 22,084.21 | 165.63 | 717.74 |
| PI-001042 | PR-2025-06 | EMP-0481 Abhishek Philip | 20,612 | 21,801.15 | 163.51 | 708.54 |
| PI-001230 | PR-2025-07 | EMP-0131 Aanya George | 19,383 | 21,992.25 | 164.94 | 714.75 |
| PI-001234 | PR-2025-07 | EMP-0137 Fathima More | 20,924 | 23,841.29 | 178.81 | 774.84 |
| PI-001429 | PR-2025-07 | EMP-0481 Abhishek Philip | 20,612 | 22,792.12 | 170.94 | 740.74 |
| PI-001624 | PR-2025-08 | EMP-0131 Aanya George | 19,383 | 20,874.00 | 156.56 | 678.41 |
| PI-001628 | PR-2025-08 | EMP-0137 Fathima More | 20,924 | 22,332.35 | 167.49 | 725.80 |
| PI-001823 | PR-2025-08 | EMP-0481 Abhishek Philip | 20,612 | 22,197.54 | 166.48 | 721.42 |
| PI-001952 | PR-2025-08 | EMP-0633 Vijay Selvam | 20,271 | 11,896.00 | 89.22 | 386.62 |
| PI-002023 | PR-2025-09 | EMP-0131 Aanya George | 19,383 | 19,942.13 | 149.57 | 648.12 |
| PI-002027 | PR-2025-09 | EMP-0137 Fathima More | 20,924 | 24,243.67 | 181.83 | 787.92 |
| PI-002220 | PR-2025-09 | EMP-0481 Abhishek Philip | 20,612 | 23,882.17 | 179.12 | 776.17 |
| PI-002346 | PR-2025-09 | EMP-0633 Vijay Selvam | 20,271 | 21,635.39 | 162.27 | 703.15 |
| PI-002420 | PR-2025-10 | EMP-0131 Aanya George | 19,383 | 26,805.88 | 201.04 | 871.19 |
| PI-002424 | PR-2025-10 | EMP-0137 Fathima More | 20,924 | 27,533.54 | 206.50 | 894.84 |
| PI-002614 | PR-2025-10 | EMP-0481 Abhishek Philip | 20,612 | 27,820.89 | 208.66 | 904.18 |
| PI-002740 | PR-2025-10 | EMP-0633 Vijay Selvam | 20,271 | 22,415.05 | 168.11 | 728.49 |
| PI-002823 | PR-2025-11 | EMP-0131 Aanya George | 19,383 | 21,619.50 | 162.15 | 702.63 |
| PI-002827 | PR-2025-11 | EMP-0137 Fathima More | 20,924 | 23,740.69 | 178.06 | 771.57 |
| PI-003012 | PR-2025-11 | EMP-0481 Abhishek Philip | 20,612 | 23,089.40 | 173.17 | 750.41 |
| PI-003133 | PR-2025-11 | EMP-0633 Vijay Selvam | 20,271 | 21,245.57 | 159.34 | 690.48 |
| PI-003222 | PR-2025-12 | EMP-0131 Aanya George | 19,383 | 22,145.56 | 166.09 | 719.73 |
| PI-003226 | PR-2025-12 | EMP-0137 Fathima More | 20,924 | 23,841.29 | 178.81 | 774.84 |
| PI-003410 | PR-2025-12 | EMP-0481 Abhishek Philip | 20,612 | 24,278.56 | 182.09 | 789.05 |
| PI-003527 | PR-2025-12 | EMP-0633 Vijay Selvam | 20,271 | 22,609.96 | 169.57 | 734.82 |
| PI-003624 | PR-2026-01 | EMP-0131 Aanya George | 19,383 | 22,365.00 | 167.74 | 726.86 |
| PI-003628 | PR-2026-01 | EMP-0137 Fathima More | 20,924 | 22,835.33 | 171.26 | 742.15 |
| PI-003808 | PR-2026-01 | EMP-0481 Abhishek Philip | 20,612 | 23,485.79 | 176.14 | 763.29 |
| PI-003925 | PR-2026-01 | EMP-0633 Vijay Selvam | 20,271 | 22,317.59 | 167.38 | 725.32 |
| PI-004030 | PR-2026-02 | EMP-0131 Aanya George | 19,383 | 19,662.56 | 147.47 | 639.03 |
| PI-004034 | PR-2026-02 | EMP-0137 Fathima More | 20,924 | 21,383.87 | 160.38 | 694.98 |
| PI-004214 | PR-2026-02 | EMP-0481 Abhishek Philip | 20,612 | 21,206.58 | 159.05 | 689.21 |
| PI-004330 | PR-2026-02 | EMP-0633 Vijay Selvam | 20,271 | 22,317.59 | 167.38 | 725.32 |
| PI-004444 | PR-2026-03 | EMP-0131 Aanya George | 19,383 | 21,246.75 | 159.35 | 690.52 |
| PI-004448 | PR-2026-03 | EMP-0137 Fathima More | 20,924 | 22,432.94 | 168.25 | 729.07 |
| PI-004625 | PR-2026-03 | EMP-0481 Abhishek Philip | 20,612 | 21,602.96 | 162.02 | 702.10 |
| PI-004739 | PR-2026-03 | EMP-0633 Vijay Selvam | 20,271 | 21,635.39 | 162.27 | 703.15 |

This discrepancy is **not explained by the available employee eligibility
flags**. The payroll reference behaves as though both sample percentage
rates were applied to these rows, while the current payroll calculation
requires `esi_applicable == "Y"` before applying ESI. On the other hand, 36
additional rows have flag `N`, fixed gross within the sample threshold, and
zero ESI. Thus the reference does not consistently follow either the
current flag-aware rule or a threshold-only rule. With no dated eligibility
history, authoritative ESI policy, or row-level payroll eligibility input,
the evidence establishes a source-data/policy inconsistency but cannot prove
whether the employee flags are stale, the 44 reference deductions are
incorrect, or another eligibility decision was used. This is not a
calculation defect in the current service's explicit flag-gated formula; it
remains an unsupported policy/source inconsistency.

### Overtime rounding across all payroll items

The earlier two one-paisa differences are the only mismatches when the
independently reconstructed fixed gross and attendance hours are passed
through the supplied overtime formula and `ROUND_HALF_UP`:

- `ROUND_HALF_UP`: **7,338 / 7,340 match**, with **2 mismatches**, both
  +0.01 against the reference.
- `ROUND_HALF_EVEN`: **7,318 / 7,340 match**, with **22 mismatches**.
- There are 24 exact half-cent cases where the rounding modes differ:
  **22** reference values match `ROUND_HALF_UP`; **2** match
  `ROUND_HALF_EVEN`.
- For the other 7,316 rows the two modes produce the same rounded amount.

| Payroll item | Employee / run | Exact amount before rounding | HALF_UP | HALF_EVEN | Reference |
|---|---|---:|---:|---:|---:|
| PI-002908 | EMP-0307 / PR-2025-11 | 4,898.625 | 4,898.63 | 4,898.62 | 4,898.62 |
| PI-006310 | EMP-0535 / PR-2026-07 | 6,361.125 | 6,361.13 | 6,361.12 | 6,361.12 |

Accordingly, the supplied payroll data does **not** use one consistent
rounding behavior for every half-cent overtime result. Its dominant behavior
is `ROUND_HALF_UP` (matching 7,338 total rows); the two listed rows use the
`ROUND_HALF_EVEN` result or contain a one-paisa source discrepancy. The two
rows alone do not establish that HALF_EVEN is the intended universal rule.
The existing service uses `ROUND_HALF_UP`, which matches the other 7,338
rows under the supplied formula. An approved policy is still needed before
changing the implementation or treating either source outcome as authoritative.
