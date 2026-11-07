from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.auth import ALGORITHM
from app.config import settings
from app.database import Base, get_db
from app.models import Department, Employee, Role, User
from app.routers import auth, employees, expenses, payslips, reports, tax


@pytest.fixture
def security_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", "test-secret-key-" + "x" * 40)
    engine = create_engine(f"sqlite:///{tmp_path / 'auth-test.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Finance",
                cost_center="CC01",
            )
        )
        db.flush()
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Finance Associate",
                level=1,
                grade="G1",
                band_min_annual=1,
                band_mid_annual=2,
                band_max_annual=3,
                overtime_eligible="N",
                band_year=2025,
            )
        )
        db.flush()
        employee_data = (
            ("EMP-ADMIN", "admin@example.test"),
            ("EMP-HR", "hr@example.test"),
            ("EMP-ONE", "one@example.test"),
            ("EMP-TWO", "two@example.test"),
            ("EMP-INACTIVE", "inactive@example.test"),
        )
        for employee_id, email in employee_data:
            employee = Employee(
                employee_id=employee_id,
                first_name=employee_id,
                last_name="Test",
                full_name=f"{employee_id} Test",
                work_email=email,
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
                notice_period_days=0,
            )
            db.add(employee)
        db.flush()
        from app.auth import hash_password

        for user_id, employee_id, email, role, active in (
            ("U-ADMIN", "EMP-ADMIN", "admin@example.test", "ADMIN", "Y"),
            ("U-HR", "EMP-HR", "hr@example.test", "HR", "Y"),
            ("U-ONE", "EMP-ONE", "one@example.test", "EMPLOYEE", "Y"),
            ("U-TWO", "EMP-TWO", "two@example.test", "EMPLOYEE", "Y"),
            (
                "U-INACTIVE",
                "EMP-INACTIVE",
                "inactive@example.test",
                "EMPLOYEE",
                "N",
            ),
        ):
            db.add(
                User(
                    user_id=user_id,
                    employee_id=employee_id,
                    username=email,
                    role=role,
                    is_active=active,
                    mfa_enabled="N",
                    last_login_at=None,
                    created_at="2025-01-01",
                    password_policy_note=None,
                    password_hash=hash_password("correct-horse-battery"),
                )
            )
        db.commit()

    def override_db():
        with session_factory() as db:
            yield db

    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(employees.router)
    app.include_router(payslips.router)
    app.include_router(reports.router)
    app.include_router(expenses.vendors_router)
    app.include_router(tax.router)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _token(client, username):
    response = client.post(
        "/auth/login",
        json={
            "username": username,
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def test_login_issues_thirty_minute_token_without_exposing_hash(security_client):
    client, _ = security_client
    response = client.post(
        "/auth/login",
        json={
            "username": "admin@example.test",
            "password": "correct-horse-battery",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["token_type"] == "bearer"
    assert result["expires_in"] == 1800
    claims = jwt.decode(
        result["access_token"],
        settings.secret_key,
        algorithms=[ALGORITHM],
    )
    assert claims["exp"] - claims["iat"] == 1800
    assert "password_hash" not in result
    assert "correct-horse-battery" not in result.values()


def test_login_rejects_bad_password_and_missing_secret_safely(
    security_client,
    monkeypatch,
):
    client, _ = security_client
    invalid = client.post(
        "/auth/login",
        json={"username": "admin@example.test", "password": "wrong"},
    )
    assert invalid.status_code == 401
    monkeypatch.setattr(settings, "secret_key", None)
    unavailable = client.post(
        "/auth/login",
        json={
            "username": "admin@example.test",
            "password": "correct-horse-battery",
        },
    )
    assert unavailable.status_code == 503
    monkeypatch.setattr(settings, "secret_key", "too-short")
    invalid_secret = client.post(
        "/auth/login",
        json={
            "username": "admin@example.test",
            "password": "correct-horse-battery",
        },
    )
    assert invalid_secret.status_code == 503


def test_bearer_validation_role_checks_and_employee_isolation(security_client):
    client, _ = security_client
    base = "/reports/trial-balance?start_date=2025-04-01&end_date=2025-04-30"
    assert client.get(base).status_code == 401
    assert client.get(base, headers={"Authorization": "Bearer invalid"}).status_code == 401

    expired = jwt.encode(
        {"sub": "U-HR", "exp": 1},
        settings.secret_key,
        algorithm=ALGORITHM,
    )
    assert (
        client.get(base, headers={"Authorization": f"Bearer {expired}"}).status_code
        == 401
    )

    employee_token = _token(client, "one@example.test")
    employee_headers = {"Authorization": f"Bearer {employee_token}"}
    assert client.get(base, headers=employee_headers).status_code == 403
    assert client.get("/employees", headers=employee_headers).status_code == 403
    assert (
        client.get(
            "/employees/EMP-TWO",
            headers=employee_headers,
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/employees/EMP-ONE",
            headers=employee_headers,
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/payslips/EMP-TWO/PR-2025-04",
            headers=employee_headers,
        ).status_code
        == 403
    )
    assert client.get("/vendors", headers=employee_headers).status_code == 403
    assert (
        client.post(
            "/tax/slabs/TS-1/versions",
            headers=employee_headers,
            json={
                "rate_percent": "11",
                "effective_from": "2027-01-01",
            },
        ).status_code
        == 403
    )
    admin_token = _token(client, "admin@example.test")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    authorized_but_missing = client.post(
        "/tax/slabs/TS-1/versions",
        headers=admin_headers,
        json={"rate_percent": "11", "effective_from": "2027-01-01"},
    )
    assert authorized_but_missing.status_code == 404

    hr_token = _token(client, "hr@example.test")
    hr_headers = {"Authorization": f"Bearer {hr_token}"}
    assert client.get(base, headers=hr_headers).status_code == 200
    assert client.get("/vendors", headers=hr_headers).status_code == 200
    assert (
        client.post(
            "/tax/slabs/TS-1/versions",
            headers=hr_headers,
            json={
                "rate_percent": "11",
                "effective_from": "2027-01-01",
            },
        ).status_code
        == 403
    )


def test_deactivated_user_token_is_immediately_revoked(security_client):
    client, session_factory = security_client
    token = _token(client, "one@example.test")
    with session_factory() as db:
        user = db.get(User, "U-ONE")
        user.is_active = "N"
        db.commit()
    response = client.get(
        "/employees/EMP-ONE",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
