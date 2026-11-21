# LedgerForge Task 20 — Release Checklist

Task 20 may begin only after Task 17 hosted approval, or the hosted items
must remain explicitly documented as manual blockers.

## Pre-release

- [ ] Confirm Task 17 hosted salary preflight result.
- [ ] Confirm or document November 2026 hosted payroll preview result.
- [ ] Confirm or document hosted payslip availability.
- [ ] Review all local changes and untracked files.
- [ ] Re-run `python -m pytest --cov=app --cov-report=term-missing -q`.
- [ ] Run `git diff --check`.
- [ ] Verify no credential or private connection string is tracked.
- [ ] Verify no Task 17 demo password or hosted database value changed.

## Commit and push

- [ ] Obtain explicit commit approval.
- [ ] Stage only reviewed LedgerForge source, test, migration, and documentation files.
- [ ] Create a release commit with the required Copilot co-author trailer.
- [ ] Obtain explicit push approval.
- [ ] Push the `lf-05-salary-structures` branch.

## Deployment

- [ ] Obtain explicit Render deployment approval.
- [ ] Preserve the existing free web service and database configuration.
- [ ] Confirm migrations apply successfully.
- [ ] Do not configure Redis/Celery or paid services.
- [ ] Do not execute live payroll jobs or create payment records.

## Post-deployment verification

- [ ] Verify `/api/v1/health` and `/health`.
- [ ] Verify `/openapi.json` and `/docs`.
- [ ] Verify `/demo/` and login.
- [ ] Verify employee/payroll/ledger CSV and XLSX exports.
- [ ] Verify background job endpoints return HTTP 503 without a worker.
- [ ] Verify hosted payroll preview only if salary setup was approved.
- [ ] Verify hosted payslip only if an approved synthetic run exists.
- [ ] Record the deployed commit, test result, and remaining infrastructure
  limitations.
