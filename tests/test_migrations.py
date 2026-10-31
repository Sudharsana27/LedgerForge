import importlib.util
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Department, Employee, Role


REVISION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "081f56311621_create_initial_organization_schema.py"
)
ENTITLEMENT_REVISION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "d24e7a91c630_add_leave_entitlement_reference.py"
)
SALARY_CONSTRAINT_REVISION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "c3f4a8d1027b_allow_legacy_salary_ranges.py"
)


def _load_revision():
    spec = importlib.util.spec_from_file_location(
        "initial_organization_revision",
        REVISION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_entitlement_revision():
    spec = importlib.util.spec_from_file_location(
        "leave_entitlement_revision",
        ENTITLEMENT_REVISION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_salary_constraint_revision():
    spec = importlib.util.spec_from_file_location(
        "salary_constraint_revision",
        SALARY_CONSTRAINT_REVISION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_revision(connection, revision, operation):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(revision, operation)()


def test_adopted_organization_rows_survive_upgrade_and_blocked_downgrade(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'adopted.db'}")
    organization_tables = [
        Base.metadata.tables[name]
        for name in (
            "departments",
            "roles",
            "employees",
            "employee_assignments",
        )
    ]
    Base.metadata.create_all(engine, tables=organization_tables)
    with Session(engine) as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Preserved",
                cost_center="CC01",
                description=None,
            )
        )
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Preserved role",
                level=1,
                grade="G1",
                band_min_annual=1,
                band_mid_annual=2,
                band_max_annual=3,
                overtime_eligible="N",
                band_year=2026,
            )
        )
        db.add(
            Employee(
                employee_id="EMP-PRESERVED",
                first_name="Existing",
                last_name="Employee",
                full_name="Existing Employee",
                work_email="existing@example.com",
                hire_date=date(2020, 1, 1),
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="D01",
                role_id="R01",
                manager_id=None,
                work_location="Chennai",
                work_mode="OFFICE",
                pf_applicable="Y",
                esi_applicable="N",
                notice_period_days=30,
            )
        )
        db.commit()

    revision = _load_revision()
    with engine.begin() as connection:
        _run_revision(connection, revision, "upgrade")
        with pytest.raises(RuntimeError, match="cannot safely determine ownership"):
            _run_revision(connection, revision, "downgrade")

    with Session(engine) as db:
        assert db.scalar(
            select(Department.department_name).where(
                Department.department_id == "D01"
            )
        ) == "Preserved"
        assert db.scalar(
            select(Employee.employee_id).where(
                Employee.employee_id == "EMP-PRESERVED"
            )
        ) == "EMP-PRESERVED"
    engine.dispose()


def test_fresh_organization_schema_downgrade_is_explicitly_blocked(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    revision = _load_revision()
    with engine.begin() as connection:
        _run_revision(connection, revision, "upgrade")
        with pytest.raises(RuntimeError, match="cannot safely determine ownership"):
            _run_revision(connection, revision, "downgrade")
    assert "departments" in Base.metadata.tables
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='departments'"
        ).scalar_one() == "departments"
    engine.dispose()


def test_adopted_legacy_organization_tables_are_not_recreated_or_dropped(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-adopted.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE departments "
                "(department_id TEXT, department_name TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE roles "
                "(role_id TEXT, department_id TEXT, role_title TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE employees "
                "(employee_id TEXT, department_id TEXT, manager_id TEXT)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE employee_assignments "
                "(assignment_id TEXT, employee_id TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO departments VALUES ('D-LEGACY', 'Keep me')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO employees VALUES ('E-LEGACY', 'D-LEGACY', NULL)"
            )
        )

    revision = _load_revision()
    with engine.begin() as connection:
        _run_revision(connection, revision, "upgrade")
        with pytest.raises(RuntimeError, match="cannot safely determine ownership"):
            _run_revision(connection, revision, "downgrade")
        assert connection.execute(
            text(
                "SELECT department_name FROM departments "
                "WHERE department_id = 'D-LEGACY'"
            )
        ).scalar_one() == "Keep me"
        assert connection.execute(
            text(
                "SELECT employee_id FROM employees "
                "WHERE employee_id = 'E-LEGACY'"
            )
        ).scalar_one() == "E-LEGACY"
    engine.dispose()


def test_entitlement_migration_adds_nullable_column_without_losing_rows(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'old-leave-schema.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE leave_requests "
                "(leave_request_id TEXT PRIMARY KEY, reason TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO leave_requests VALUES ('LR-OLD', 'Existing row')"
            )
        )
        _run_revision(
            connection,
            _load_entitlement_revision(),
            "upgrade",
        )
        assert connection.execute(
            text(
                "SELECT reason, entitlement_reference FROM leave_requests "
                "WHERE leave_request_id = 'LR-OLD'"
            )
        ).one() == ("Existing row", None)
    engine.dispose()


def test_salary_migration_removes_legacy_range_check_without_losing_rows(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'salary-range.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE salary_structures ("
                "structure_id TEXT PRIMARY KEY, "
                "effective_from DATE NOT NULL, "
                "effective_to DATE, "
                "CONSTRAINT ck_salary_structure_date_range "
                "CHECK (effective_to IS NULL OR "
                "effective_to >= effective_from))"
            )
        )
        connection.execute(
            text(
                "INSERT INTO salary_structures VALUES "
                "('SS-LEGACY', '2021-03-01', '2021-03-31')"
            )
        )
        _run_revision(
            connection,
            _load_salary_constraint_revision(),
            "upgrade",
        )
        assert connection.execute(
            text(
                "SELECT effective_from, effective_to "
                "FROM salary_structures WHERE structure_id = 'SS-LEGACY'"
            )
        ).one() == ("2021-03-01", "2021-03-31")
        connection.execute(
            text(
                "UPDATE salary_structures SET effective_from = '2021-04-01' "
                "WHERE structure_id = 'SS-LEGACY'"
            )
        )
        assert "ck_salary_structure_date_range" not in {
            constraint["name"]
            for constraint in inspect(connection).get_check_constraints(
                "salary_structures"
            )
        }
    engine.dispose()
