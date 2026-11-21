from datetime import date, datetime, timezone
import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.database import Base, get_db
from app.main import app
from app.models import Department, Employee, Role


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(employee_id="E001", role="HR", user_id="U-HR")
    )
    return engine, session, TestClient(app)


def _department_employee(db):
    department = Department(
        department_id="D01",
        department_name="Engineering",
        cost_center="CC01",
        description=None,
    )
    role = Role(
        role_id="R01",
        department_id="D01",
        role_title="Developer",
        level=1,
        grade="G1",
        band_min_annual=300000,
        band_mid_annual=400000,
        band_max_annual=500000,
        overtime_eligible="N",
        band_year=2026,
    )
    employee = Employee(
        employee_id="E001",
        first_name="Asha",
        last_name="Ravi",
        full_name="Asha Ravi",
        work_email="asha@example.com",
        hire_date=date(2025, 1, 1),
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
        created_at=date(2025, 1, 1),
        updated_at=datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc),
    )
    db.add_all([department, role, employee])
    db.commit()


def test_employee_csv_export_headers_and_incremental_filter():
    engine, session, client = _client()
    with session() as db:
        _department_employee(db)

    response = client.get(
        "/exports/employees",
        params={"changed_since": "2026-11-19"},
    )
    assert response.status_code == 200
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("employee_id,first_name,last_name")
    assert "E001" in lines[1]

    engine.dispose()
    app.dependency_overrides.clear()


def test_employee_excel_export_contains_headers():
    engine, session, client = _client()
    def override_db():
        db = session()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_db
    with session() as db:
        _department_employee(db)

    response = client.get(
        "/exports/employees",
        params={"format": "xlsx"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )
    workbook = load_workbook(io.BytesIO(response.content))
    sheet = workbook.active
    assert sheet.cell(row=1, column=1).value == "employee_id"
    assert sheet.cell(row=2, column=1).value == "E001"

    engine.dispose()
    app.dependency_overrides.clear()
