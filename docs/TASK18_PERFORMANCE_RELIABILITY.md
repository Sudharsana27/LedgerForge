# LedgerForge Task 18 — Performance, Reliability and Backup

## Verification evidence

- Baseline: 223 tests passed before Task 18/19 changes; targeted Phase 4 set:
  27 tests passed.
- Benchmark database: disposable PostgreSQL 16 container on local port 55433.
  Database name: `ledgerforge_phase4`; no existing Docker volume or hosted
  database was changed.
- Workload: 18 distinct monthly payroll periods, 18 PAID runs in the benchmark
  database, approved minimal synthetic data.
- Job runtime: 0.088912 seconds.
- Throughput: 202.45 periods/second and 202.45 runs/second.
- Job completion status: 18 runs considered, 18 completed as SKIPPED because
  they were already PAID. No DRAFT rows were recalculated.
- Limitation: the benchmark database had no source-backed DRAFT payroll
  calculations or 18-run salary/attendance fixtures, so processing 18 DRAFT
  runs was not possible without manufacturing payroll history.

### Final 18-DRAFT verification

- Isolated PostgreSQL 16 database:
  `ledgerforge_phase4_benchmark`, local port 55434.
- Synthetic salary, attendance, assignment, statutory-rate, payroll-run, and
  payroll-item data was created only in that disposable database.
- Runtime: 0.640194 seconds for processing 18 DRAFT runs.
- Throughput: 28.12 periods/second.
- Completion: 18 completed, 0 failed, with all 18 runs verified as `PROCESSED`.
- Payroll period selection: 0.171 ms execution, 18 rows.
- Payroll-item employee/range scan: 0.056 ms execution, 18 rows.
- Effective salary structure scan: 0.125 ms execution, 5 rows.
- Docker backup/restore: custom-format dump restored to
  `ledgerforge_18draft_restore`; restored counts were 18 `PROCESSED` runs and
  18 payroll items.

## PostgreSQL EXPLAIN ANALYZE

| Rank | Query | Planning | Execution | Result |
|---|---|---:|---:|---|
| 1 | Payroll-item employee/period range | 0.591 ms | 0.533 ms | index scan, 0 rows |
| 2 | Payroll-run period order/limit | 238 ms planning buffers; 0.816 ms planning time | 0.121 ms | 18 rows |
| 3 | Journal date-range export | 0.831 ms planning time | 0.034 ms | 0 rows |

Ranking is by observed execution time from isolated local data. A small
fixture limits the value of re-timing a before/after comparison. Existing
indexes cover payroll-item employee/period and journal entry date. The Phase
4 migration adds payroll-run creation and period-run indexes plus
employee-created/updated indexes for incremental exports.

## Reliability

- Pagination: employee and other list endpoints retain bounded `skip`/`limit`
  parameters.
- Caching: Redis-aware health reporting is implemented. Redis remains optional;
  `/health` reports `cache: ok`, `disabled`, or `unavailable`.
- Structured logging: HTTP middleware emits JSON request logs with request ID,
  method, path, status, and duration.
- Health: `/health` and `/api/v1/health` perform `SELECT 1` and return 503
  database-unavailable responses on database failure.

## Backup and restore

- PostgreSQL backup completed with `pg_dump --format=custom` inside the
  isolated Docker PostgreSQL container.
- Restore completed into separate database `ledgerforge_restore_phase4` with
  `pg_restore --clean --if-exists`.
- Verified restored counts: 18 payroll runs, 1 employee, 1 department,
  1 role.
- Infrastructure limitation: the host Python environment has no `pg_dump`,
  `pg_restore`, or `psql` executables. The backup script reports this explicitly;
  container tools were used for the verified local backup/restore.

## Remaining Task 18 actions

- The measured workload was synthetic and small; performance at realistic
  employee/run volume and any numeric acceptance threshold remain unverified.
- No before/after query-plan benchmark was captured to quantify index benefit.
- Redis-aware health is present, but no read-through/application response
  caching behavior was found or verified.
