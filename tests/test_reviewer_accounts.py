from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Department, Employee, Role, User
from scripts.provision_reviewer_accounts import (
    account_status,
    provision_missing_accounts,
)


def _reviewer_database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(
        Department(
            department_id="DEMO01",
            department_name="Demonstration Department",
            cost_center="DEMO",
            description="Synthetic demonstration data",
        )
    )
    db.flush()
    db.add(
        Role(
            role_id="DEMO01",
            department_id="DEMO01",
            role_title="Demo Administrator",
            level=1,
            grade="DEMO",
            band_min_annual=0,
            band_mid_annual=0,
            band_max_annual=0,
            overtime_eligible="N",
            band_year=2026,
        )
    )
    db.flush()
    db.add(
        Employee(
            employee_id="DEMOEMP001",
            first_name="Demo",
            last_name="Administrator",
            full_name="Demo Administrator",
            work_email="demo-admin@example.invalid",
            hire_date=date(2026, 1, 1),
            employment_status="ACTIVE",
            employment_type="FULL_TIME",
            department_id="DEMO01",
            role_id="DEMO01",
            manager_id=None,
            work_location="Demo",
            work_mode="REMOTE",
            pf_applicable="N",
            esi_applicable="N",
            notice_period_days=0,
        )
    )
    db.flush()
    db.add(
        User(
            user_id="DEMOUSER001",
            employee_id="DEMOEMP001",
            username="demo_admin",
            role="ADMIN",
            is_active="Y",
            mfa_enabled="N",
            password_hash="existing-hash",
        )
    )
    db.flush()
    return engine, db


def test_reviewer_accounts_are_synthetic_role_scoped_and_idempotent():
    engine, db = _reviewer_database()
    assert dict(account_status(db)) == {
        "demo_admin": "present; unchanged",
        "demo_hr": "missing",
        "demo_employee": "missing",
    }

    created = provision_missing_accounts(
        db,
        {"demo_hr": "hr-hash", "demo_employee": "employee-hash"},
    )
    assert created == ["demo_hr", "demo_employee"]
    assert provision_missing_accounts(db, {}) == []

    hr = db.query(User).filter_by(username="demo_hr").one()
    employee_user = db.query(User).filter_by(username="demo_employee").one()
    assert (hr.role, hr.employee_id) == ("HR", "DEMOHR001")
    assert (employee_user.role, employee_user.employee_id) == (
        "EMPLOYEE",
        "DEMOEMP002",
    )
    assert db.get(Employee, "DEMOEMP001").full_name == "Demo Administrator"
    assert db.get(User, "DEMOUSER001").password_hash == "existing-hash"
    assert dict(account_status(db))["demo_employee"] == "ready; unchanged"

    db.close()
    engine.dispose()
