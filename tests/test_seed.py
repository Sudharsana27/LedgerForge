from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import JournalEntry
from scripts import seed


def test_seed_orders_salary_revisions_before_structures_on_orm_schema(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "csv"
    data_dir.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'typed-seed.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    rows = {
        "departments": [
            {
                "department_id": "D01",
                "department_name": "Engineering",
                "cost_center": "CC01",
                "description": None,
            }
        ],
        "roles": [
            {
                "role_id": "R01",
                "department_id": "D01",
                "role_title": "Developer",
                "level": 1,
                "grade": "G1",
                "band_min_annual": 300000,
                "band_mid_annual": 500000,
                "band_max_annual": 700000,
                "overtime_eligible": "Y",
                "band_year": 2026,
            }
        ],
        "employees": [
            {
                "employee_id": "EMP-SEED",
                "first_name": "Seed",
                "last_name": "Employee",
                "full_name": "Seed Employee",
                "work_email": "seed@example.com",
                "gender": None,
                "date_of_birth": None,
                "hire_date": "2024-01-01",
                "exit_date": None,
                "employment_status": "ACTIVE",
                "employment_type": "FULL_TIME",
                "department_id": "D01",
                "role_id": "R01",
                "manager_id": None,
                "work_location": "Chennai",
                "work_mode": "OFFICE",
                "highest_education": None,
                "prior_experience_years": None,
                "career_gap_months": None,
                "commute_distance_km": None,
                "pf_applicable": "Y",
                "esi_applicable": "N",
                "notice_period_days": 30,
                "resignation_date": None,
                "exit_type": None,
                "exit_reason": None,
                "created_at": None,
            }
        ],
        "salary_components": [
            {
                "component_id": "BASIC",
                "component_name": "Basic",
                "component_type": "Earning",
                "taxable": "Y",
                "calculation_rule": "Fixed",
                "is_fixed": "Y",
            }
        ],
        "salary_revisions": [
            {
                "revision_id": "SR-SEED",
                "employee_id": "EMP-SEED",
                "effective_from": "2026-01-01",
                "revision_reason": "Annual review",
                "previous_annual_fixed": 500000,
                "new_annual_fixed": 550000,
                "pct_change": 10,
                "role_id_after": "R01",
                "approved_by": None,
                "created_at": "2026-01-01T10:00:00",
            }
        ],
        "salary_structures": [
            {
                "structure_id": "SS-SEED",
                "employee_id": "EMP-SEED",
                "component_id": "BASIC",
                "component_name": "Basic",
                "component_type": "Earning",
                "monthly_amount": 45833.33,
                "effective_from": "2026-01-01",
                "effective_to": "2025-12-31",
                "revision_id": "SR-SEED",
            }
        ],
        "chart_of_accounts": [
            {
                "account_code": "1000",
                "account_name": "Assets",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
                "parent_code": None,
                "is_group": "Y",
                "statement": "BALANCE_SHEET",
                "is_active": "Y",
            },
            {
                "account_code": "1001",
                "account_name": "Cash",
                "account_type": "ASSET",
                "normal_balance": "DEBIT",
                "parent_code": "1000.0",
                "is_group": "N",
                "statement": "BALANCE_SHEET",
                "is_active": "Y",
            },
            {
                "account_code": "2000",
                "account_name": "Liabilities",
                "account_type": "LIABILITY",
                "normal_balance": "CREDIT",
                "parent_code": None,
                "is_group": "Y",
                "statement": "BALANCE_SHEET",
                "is_active": "Y",
            },
            {
                "account_code": "2001",
                "account_name": "Payable",
                "account_type": "LIABILITY",
                "normal_balance": "CREDIT",
                "parent_code": "2000.0",
                "is_group": "N",
                "statement": "BALANCE_SHEET",
                "is_active": "Y",
            },
        ],
        "journal_entries": [
            {
                "entry_id": "JE-SEED",
                "entry_date": "2025-04-01",
                "posting_period": "2025-04",
                "financial_year": "2025-26",
                "description": "Seed journal",
                "source_type": "MANUAL",
                "source_id": "MJ-SEED",
                "status": "POSTED",
                "total_debit": "1.10",
                "total_credit": "1.10",
                "reversal_of_source_id": None,
                "created_by": "tester",
                "created_at": "2025-04-01 09:00:00",
            }
        ],
        "journal_lines": [
            {
                "line_id": "JL-SEED-1",
                "entry_id": "JE-SEED",
                "line_no": 1,
                "account_code": "1001",
                "debit": "1.10",
                "credit": "0.00",
                "cost_center_department_id": "D01",
                "line_description": "Cash debit",
            },
            {
                "line_id": "JL-SEED-2",
                "entry_id": "JE-SEED",
                "line_no": 2,
                "account_code": "2001",
                "debit": "0.00",
                "credit": "1.10",
                "cost_center_department_id": None,
                "line_description": "Payable credit",
            },
        ],
    }

    dictionary_rows = []
    integer_columns = {
        "level",
        "band_min_annual",
        "band_mid_annual",
        "band_max_annual",
        "band_year",
        "career_gap_months",
        "notice_period_days",
        "line_no",
    }
    decimal_columns = {
        "prior_experience_years",
        "commute_distance_km",
        "previous_annual_fixed",
        "new_annual_fixed",
        "pct_change",
        "monthly_amount",
        "total_debit",
        "total_credit",
        "debit",
        "credit",
    }
    for table_name, records in rows.items():
        frame = pd.DataFrame(records)
        frame.to_csv(data_dir / f"{table_name}.csv", index=False)
        for column in frame.columns:
            dtype = "string"
            if column.endswith("_date") or column in {
                "hire_date",
                "effective_from",
                "effective_to",
            }:
                dtype = "date"
            elif column == "created_at" and table_name in {
                "salary_revisions",
                "journal_entries",
            }:
                dtype = "timestamp"
            elif column in integer_columns:
                dtype = "integer"
            elif column in decimal_columns:
                dtype = "decimal"
            dictionary_rows.append(
                {
                    "sheet": table_name,
                    "column": column,
                    "data_type": dtype,
                }
            )

    dictionary_path = data_dir / "data_dictionary.csv"
    pd.DataFrame(dictionary_rows).to_csv(dictionary_path, index=False)
    monkeypatch.setattr(seed, "DATA_DIR", data_dir)
    monkeypatch.setattr(seed, "DICTIONARY_FILE", dictionary_path)
    monkeypatch.setattr(seed, "engine", engine)

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE local_only_records "
                    "(record_id TEXT PRIMARY KEY, value TEXT NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO local_only_records VALUES "
                    "('LOCAL-1', 'preserve')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO departments VALUES "
                    "('D-LOCAL', 'Local', 'CC-LOCAL', NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO departments VALUES "
                    "('D01', 'Old department', 'CC01', NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO roles VALUES "
                    "('R01', 'D01', 'Old role', 1, 'G1', 1, 2, 3, 'Y', 2026)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO employees "
                    "(employee_id, first_name, last_name, full_name, "
                    "work_email, hire_date, employment_status, "
                    "employment_type, department_id, role_id, work_location, "
                    "work_mode, pf_applicable, esi_applicable, "
                    "notice_period_days) VALUES "
                    "('EMP-SEED', 'Old', 'Employee', 'Old Employee', "
                    "'seed@example.com', '2024-01-01', 'ACTIVE', "
                    "'FULL_TIME', 'D01', 'R01', 'Chennai', 'OFFICE', "
                    "'Y', 'N', 30)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO salary_components VALUES "
                    "('BASIC', 'Old Basic', 'Earning', 'Y', 'Fixed', 'Y')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO salary_revisions "
                    "(revision_id, employee_id, effective_from, "
                    "revision_reason, new_annual_fixed, role_id_after, "
                    "created_at) VALUES "
                    "('SR-SEED', 'EMP-SEED', '2026-01-01', 'Old', 1, "
                    "'R01', '2026-01-01 10:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO salary_structures "
                    "(structure_id, employee_id, component_id, "
                    "component_name, component_type, monthly_amount, "
                    "effective_from, revision_id) VALUES "
                    "('SS-SEED', 'EMP-SEED', 'BASIC', 'Old Basic', "
                    "'Earning', 1, '2026-01-01', 'SR-SEED')"
                )
            )

        seed.main()
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "PRAGMA foreign_keys"
            ).scalar_one() == 1
            assert connection.exec_driver_sql(
                "PRAGMA foreign_key_check"
            ).all() == []
            assert connection.execute(
                text("SELECT revision_id FROM salary_revisions")
            ).scalar_one() == "SR-SEED"
            assert connection.execute(
                text("SELECT revision_id FROM salary_structures")
            ).scalar_one() == "SR-SEED"
            assert connection.execute(
                text(
                    "SELECT value FROM local_only_records "
                    "WHERE record_id = 'LOCAL-1'"
                )
            ).scalar_one() == "preserve"
            assert connection.execute(
                text(
                    "SELECT parent_code FROM chart_of_accounts "
                    "WHERE account_code = '1001'"
                )
            ).scalar_one() == "1000"
            with Session(bind=connection) as db:
                seeded_entry = db.get(JournalEntry, "JE-SEED")
            assert seeded_entry.total_debit == Decimal("1.10")
            assert seeded_entry.total_credit == Decimal("1.10")
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM journal_lines "
                    "WHERE entry_id = 'JE-SEED'"
                )
            ).scalar_one() == 2
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM departments "
                    "WHERE department_id = 'D-LOCAL'"
                )
            ).scalar_one() == 0
    finally:
        engine.dispose()
