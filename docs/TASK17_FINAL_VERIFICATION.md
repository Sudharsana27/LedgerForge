# LedgerForge Task 17 — Final Local Verification

## Verified locally

- The demo employee requires an effective `SalaryRevision`,
  five fixed `SalaryStructure` earning rows, an effective
  `EmployeeAssignment`, November 2026 attendance, and statutory rates.
- [scripts/setup_demo_salary.py](../scripts/setup_demo_salary.py) is guarded
  and idempotent. Its default mode is restricted to the disposable
  `ledgerforge_demo_test` PostgreSQL database on `127.0.0.1:55432`; hosted
  mode requires an exact host/database match and typed confirmation.
- It refuses to run unless `DEMOEMP001` exists with the synthetic demo
  department/role and refuses to modify an employee that has payroll history.
- A focused regression test verified that running the setup twice adds salary
  data only on the first run.
- Payroll preview for `DEMOEMP001`, 2026-11-01 through 2026-11-30, verified:
  gross pay `29850.00`, professional tax `200.00`, net pay `29650.00`.
- A synthetic payroll run/item pair was verified in an isolated SQLite test.
- Payslip construction and PDF rendering returned a PDF beginning with
  `%PDF` and longer than 1 KB.
- Existing background-job tests verify HTTP 503 behavior when Redis is absent
  or no Celery worker responds.

## Not verified

- User reports that the Render demo login and synthetic salary data for
  `DEMOEMP001` exist. This session did not access the hosted database or
  independently verify those records.
- On 2026-11-21, a read-only `GET /api/v1/health` returned HTTP 200 with
  `status=ok` and `database=ok`. This verifies the live health endpoint and
  database connectivity at that time only; it does not verify login,
  payroll preview, or payslip behavior.
- A successful hosted November 2026 payroll preview after salary setup has
  not been reported or independently verified.
- No live hosted payslip was generated.
- No live Redis/Celery worker or hosted background payroll job was verified.
- The hosted database migration and deployed source commit were not read or
  independently verified during this health check. An earlier startup issue
  was reported; the successful health response shows the service is now
  responding, but does not identify the deployed commit or migration state.

## Hosted verification still required

The read-only health check succeeded, but it does not verify the API's
protected operations. The operator should:

1. Verify the currently deployed revision and migration version from the
   hosting dashboard or approved read-only inspection. Do not rerun or
   downgrade the hosted migration.
2. Verify Swagger and demo login.
3. Use the already-existing synthetic salary records to test payroll preview
   now that health responds; do not run the setup script again unless a
   separate read-only preflight identifies a specific missing row.
4. Run the read-only hosted demo preflight only if schema state still needs
   independent verification:

   ```powershell
   python -m scripts.provision_hosted_demo --expected-host YOUR-EXACT-HOST --preflight-only
   ```

5. Run the guarded hosted salary preflight, with `DATABASE_URL` already set
   only in the private process environment:

   ```powershell
   python -m scripts.setup_demo_salary `
     --hosted --expected-host YOUR-EXACT-HOST --preflight-only
   ```

   The preflight rejects missing `DEMOEMP001`, mismatched demo department/role
   references, and any existing payroll history. It performs no writes.
   Do not run the write mode when salary data is already confirmed present.
6. If hosted payslip verification is required, obtain explicit approval to
   create an isolated synthetic run/item; do not reuse or overwrite history.
   The route renders directly and does not depend on Redis/Celery.

The exact preview request body is:

   ```powershell
   $body = @{
     employee_id="DEMOEMP001"
     period_start="2026-11-01"
     period_end="2026-11-30"
     variable_pay="0"
     variable_pay_type=$null
     tds="0"
     other_deductions="0"
   } | ConvertTo-Json

   Invoke-RestMethod `
     -Uri "https://ledgerforge-bzmo.onrender.com/api/v1/payroll/calculate" `
     -Method Post -Headers @{ Authorization = "Bearer <access-token>" } `
     -ContentType "application/json" -Body $body
```

Do not create or approve a live payroll run for this preview. A bearer token
must be obtained through the existing approved login flow and must not be
written into documentation or command history.

The current free-only Render deployment remains unable to guarantee a
Redis/Celery worker. `/jobs/payroll/18-month` and status calls must continue
to return HTTP 503 until Redis and a responding worker are separately
configured and verified.
