
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.database import Base, get_db
from app.main import app
from app.models import Department, Employee, Role


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(
            employee_id="E001",
            role="HR",
            user_id="U-HR",
        )
    )

    with TestingSessionLocal() as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Engineering",
                cost_center="CC01",
                description="Test department",
            )
        )
        db.add(
            Role(
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
        )
        db.commit()

        db.add(
            Employee(
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
            )
        )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()


def valid_employee():
    return {
        "employee_id": "E002",
        "first_name": "Bala",
        "last_name": "Kumar",
        "work_email": "bala@example.com",
        "hire_date": "2026-01-10",
        "employment_status": "ACTIVE",
        "employment_type": "FULL_TIME",
        "department_id": "D01",
        "role_id": "R01",
        "manager_id": "E001",
        "work_location": "Chennai",
        "work_mode": "HYBRID",
        "pf_applicable": "Y",
        "esi_applicable": "N",
        "notice_period_days": 30,
    }


def test_list_employees_and_pagination(client):
    response = client.get("/employees?skip=0&limit=1")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert "date_of_birth" not in response.json()[0]


def test_search_employees(client):
    response = client.get("/employees?q=asha")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["employee_id"] == "E001"


def test_filter_by_department(client):
    response = client.get("/employees?department_id=D01")
    assert response.status_code == 200
    assert all(e["department_id"] == "D01" for e in response.json())


def test_get_employee_and_unknown_id(client):
    assert client.get("/employees/E001").status_code == 200
    assert client.get("/employees/UNKNOWN").status_code == 404


def test_invalid_input_returns_422(client):
    data = valid_employee()
    data["work_email"] = "not-an-email"
    response = client.post("/employees", json=data)
    assert response.status_code == 422


def test_create_employee(client):
    response = client.post("/employees", json=valid_employee())
    assert response.status_code == 201
    assert response.json()["employee_id"] == "E002"
    assert response.json()["full_name"] == "Bala Kumar"


def test_patch_employee(client):
    response = client.patch(
        "/employees/E001",
        json={"first_name": "AshaPriya"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "AshaPriya Ravi"


def test_soft_delete_and_team(client):
    # Create a direct report for E001.
    create_response = client.post("/employees", json=valid_employee())
    assert create_response.status_code == 201

    # Team endpoint returns the direct report.
    team_response = client.get("/employees/E001/team")
    assert team_response.status_code == 200
    assert any(e["employee_id"] == "E002" for e in team_response.json())

    # Deleting is a soft delete: the row remains retrievable.
    delete_response = client.delete("/employees/E002")
    assert delete_response.status_code == 200
    assert delete_response.json()["exit_date"] is not None
    assert client.get("/employees/E002").status_code == 200
