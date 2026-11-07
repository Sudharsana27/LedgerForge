
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.database import Base, get_db
from app.main import app
from app.models import (
    Department,
    Employee,
    Role,
    SalaryComponent,
    SalaryRevision,
    SalaryStructure,
)


@pytest.fixture
def setup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(
        bind=engine, autoflush=False, autocommit=False
    )
    Base.metadata.create_all(engine)

    db = TestingSession()
    db.add(Department(
        department_id="D01",
        department_name="Engineering",
        cost_center="CC01",
        description="Test department",
    ))
    db.add(Role(
        role_id="R01",
        department_id="D01",
        role_title="Developer",
        level=1,
        grade="G1",
        band_min_annual=300000,
        band_mid_annual=500000,
        band_max_annual=700000,
        overtime_eligible="N",
        band_year=2026,
    ))

    for number in range(1, 4):
        db.add(Employee(
            employee_id=f"T{number}",
            first_name=f"Test{number}",
            last_name="Employee",
            full_name=f"Test{number} Employee",
            work_email=f"test{number}@example.com",
            hire_date=date(2024, 1, 1),
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
        ))

    for component_id, name in [
        ("BASIC", "Basic Salary"),
        ("HRA", "House Rent Allowance"),
    ]:
        db.add(SalaryComponent(
            component_id=component_id,
            component_name=name,
            component_type="EARNING",
            taxable="Y",
            calculation_rule="Fixed amount",
            is_fixed="Y",
        ))

    db.commit()
    db.close()

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(
            employee_id="T1",
            role="HR",
            user_id="U-HR",
        )
    )
    yield TestingSession
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(setup_db):
    return TestClient(app)


def add_revision(db, employee_id, effective_from, amount, revision_id):
    db.add(SalaryRevision(
        revision_id=revision_id,
        employee_id=employee_id,
        effective_from=effective_from,
        revision_reason="Joining",
        previous_annual_fixed=None,
        new_annual_fixed=Decimal(str(amount)),
        pct_change=None,
        role_id_after="R01",
        approved_by=None,
        created_at=__import__("datetime").datetime(2026, 1, 1),
    ))
    db.flush()
    for component_id, monthly_amount in [
        ("BASIC", amount / 2 / 12),
        ("HRA", amount / 2 / 12),
    ]:
        component = db.get(SalaryComponent, component_id)
        db.add(SalaryStructure(
            structure_id=f"{revision_id}-{component_id}",
            employee_id=employee_id,
            component_id=component_id,
            component_name=component.component_name,
            component_type=component.component_type,
            monthly_amount=Decimal(str(monthly_amount)),
            effective_from=effective_from,
            effective_to=None,
            revision_id=revision_id,
        ))
    db.commit()


def test_structure_at_effective_date_and_boundary(client, setup_db):
    db = setup_db()
    add_revision(db, "T1", date(2025, 1, 1), 600000, "SR-T1-1")
    add_revision(db, "T1", date(2026, 1, 1), 720000, "SR-T1-2")
    rows = db.query(SalaryStructure).filter_by(
        employee_id="T1", revision_id="SR-T1-1"
    ).all()
    for row in rows:
        row.effective_to = date(2025, 12, 31)
    db.commit()
    db.close()

    old = client.get(
        "/salary/employees/T1/structure",
        params={"on_date": "2025-12-31"},
    )
    new = client.get(
        "/salary/employees/T1/structure",
        params={"on_date": "2026-01-01"},
    )
    assert old.status_code == 200
    assert all(x["revision_id"] == "SR-T1-1" for x in old.json()["components"])
    assert new.status_code == 200
    assert all(x["revision_id"] == "SR-T1-2" for x in new.json()["components"])


def test_revision_history_has_reasons(client, setup_db):
    db = setup_db()
    add_revision(db, "T1", date(2025, 1, 1), 600000, "SR-T1-1")
    add_revision(db, "T1", date(2026, 1, 1), 720000, "SR-T1-2")
    db.query(SalaryRevision).filter_by(revision_id="SR-T1-2").update(
        {"revision_reason": "Annual Increment"}
    )
    db.commit()
    db.close()

    response = client.get("/salary/employees/T1/revisions")
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert response.json()[1]["revision_reason"] == "Annual Increment"


def test_three_employees_have_independent_structures(client, setup_db):
    db = setup_db()
    for number in range(1, 4):
        add_revision(
            db, f"T{number}", date(2025, 1, 1),
            600000 + number * 10000, f"SR-T{number}-1"
        )
    db.close()

    for number in range(1, 4):
        response = client.get(
            f"/salary/employees/T{number}/structure",
            params={"on_date": "2025-06-01"},
        )
        assert response.status_code == 200
        assert len(response.json()["components"]) == 2


def test_unknown_employee_returns_404(client):
    response = client.get(
        "/salary/employees/UNKNOWN/structure",
        params={"on_date": "2025-01-01"},
    )
    assert response.status_code == 404


def test_missing_date_returns_422(client):
    response = client.get("/salary/employees/T1/structure")
    assert response.status_code == 422


def test_invalid_revision_payload_returns_422(client):
    response = client.post("/salary/revisions", json={
        "employee_id": "T1",
        "effective_from": "2026-01-01",
        "revision_reason": "Annual Increment",
        "new_annual_fixed": -100,
        "role_id_after": "R01",
        "components": [],
    })
    assert response.status_code == 422
