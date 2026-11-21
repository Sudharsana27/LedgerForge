# LedgerForge final submission checklist

## Ready to submit

- [x] Consolidated four-phase report PDF (11 pages).
- [x] Phase 4 Tasks 16-20 report PDF (3 pages).
- [x] Local reviewer-account helper and focused role/idempotence test.
- [x] Read-only live health check: HTTP 200, `status=ok`, `database=ok`
      on 2026-11-21.
- [x] Prior full-suite evidence: 227 passed, 0 skipped, 84% app coverage.
- [x] Current focused regression run: 15 passed, one upstream deprecation
      warning.

## Still pending

- [ ] Check reviewer account existence through the guarded read-only hosted
      preflight. Existing `demo_admin` is user-reported; no reviewer login
      was tested in this run.
- [ ] If authorized and absent, provision only the missing synthetic HR and
      Employee accounts; never run the empty-database provisioning helper on
      the populated demo database.
- [ ] Verify hosted login, protected role behavior, and November 2026 payroll
      preview. No hosted payroll run or payslip was created.
- [ ] Confirm deployed revision and migration state. The live health result
      alone does not establish either.
- [ ] Obtain approval before commit, push, tag, or Render deployment.
- [ ] No verified Redis/Celery worker; 18-month jobs remain unavailable on
      the current free setup.
- [ ] No demo video exists in this deliverable; provide a real video URL only
      if one is recorded.

## Reviewer access: safe procedure

Keep the Render `DATABASE_URL` in the operator's private PowerShell
environment. Never paste it into a command, file, report, or chat. First run
the read-only reviewer preflight:

```powershell
python -m scripts.provision_reviewer_accounts `
  --hosted --expected-host YOUR-EXACT-POSTGRES-HOST --preflight-only
```

The helper checks the expected database, the existing synthetic `demo_admin`
anchor, and fixed IDs for the reviewer accounts. It reports only account
names and readiness states. If either account is missing, and only after
approval to insert synthetic records, rerun without `--preflight-only`:

```powershell
python -m scripts.provision_reviewer_accounts `
  --hosted --expected-host YOUR-EXACT-POSTGRES-HOST
```

Type the exact target confirmation when prompted. Enter distinct passwords
at the hidden prompts (12-72 UTF-8 bytes); the helper stores only bcrypt
hashes. It will not reset `demo_admin` or an existing reviewer password.
Each new account is linked to its own synthetic employee row under the
existing demo department and role.

Then open `https://ledgerforge-bzmo.onrender.com/docs` and use
`POST /api/v1/auth/login` with each username and its privately delivered
password. Do not save passwords or tokens in this checklist. Use the returned
bearer token only in Swagger's temporary Authorize control:

- Admin: `demo_admin`; test an authorized ADMIN endpoint.
- HR: `demo_hr`; test an HR-authorized employee listing.
- Employee: `demo_employee`; test own employee detail and confirm employee
  listing is denied (HTTP 403).

The employee account has no independently provisioned salary, attendance,
payroll, or payslip records. Do not claim those views work for it without
separate approved records and tests.

## Submission destinations

- Programme site: submit
  `docs/Sudharsana_S_LedgerForge_Consolidated_Report.pdf`.
- Google Form: submit
  `docs/Python_Sudharsana_S_Phase4_Report.pdf`.
- Use the GitHub repository and live demo URLs shown in the reports in their
  corresponding form fields.
- Paste a demo-video URL only after a real video has been recorded and
  uploaded. Do not invent or substitute the live app URL for a video.
- Confirm destination mapping against the programme's current submission
  instructions before upload.

## Exact Git commands (run only after approval)

The commands below stage reviewed deliverables only. They intentionally
exclude the database dump, `.env`, local databases, `app/job_service.py`,
`check_migration.py`, `check_salary_schema.py`, and
`scripts/seed_lf02_backup.py`. Migration `6f2b18d4a731` is already committed
on the branch.

```powershell
git add -- README.md app/main.py app/models.py app/payslip_service.py `
  app/routers/employees.py app/routers/exports.py requirements.txt `
  scripts/provision_hosted_demo.py scripts/backup_database.py `
  scripts/benchmark_18_draft_payroll.py scripts/setup_demo_salary.py `
  scripts/provision_reviewer_accounts.py `
  tests/test_hosted_demo_provisioning.py tests/test_demo_salary_setup.py `
  tests/test_phase4_exports.py tests/test_reviewer_accounts.py `
  docs/TASK17_FINAL_VERIFICATION.md docs/TASK18_PERFORMANCE_RELIABILITY.md `
  docs/TASK19_EXPORTS_API.md docs/TASK20_RELEASE_CHECKLIST.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/Sudharsana_S_LedgerForge_Consolidated_Report.pdf `
  docs/Python_Sudharsana_S_Phase4_Report.pdf
git diff --cached --check
git diff --cached --stat
git status --short
git commit -m "Prepare LedgerForge final submission" `
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin lf-05-salary-structures
git tag -a v1.0.0 -m "LedgerForge final submission"
git push origin v1.0.0
```

The branch is `lf-05-salary-structures`. The tag `v1.0.0` was not present
when this checklist was prepared. Commit, push, and tag commands have not
been run.
