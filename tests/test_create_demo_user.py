from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import Base
from app.models import Department, Employee, Role, User
from scripts import create_demo_user


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


@pytest.mark.parametrize(
    "url",
    [
        URL.create(
            "postgresql+psycopg2",
            host="render.example",
            port=55432,
            database="ledgerforge_demo_test",
        ),
        URL.create(
            "postgresql+psycopg2",
            host="127.0.0.1",
            port=5432,
            database="ledgerforge_demo_test",
        ),
        URL.create(
            "postgresql+psycopg2",
            host="127.0.0.1",
            port=55432,
            database="ledgerforge",
        ),
        URL.create(
            "sqlite",
            database="ledgerforge_demo_test",
        ),
    ],
)
def test_database_target_guard_rejects_everything_except_disposable_target(
    monkeypatch, url
):
    monkeypatch.setattr(create_demo_user, "engine", SimpleNamespace(url=url))

    class NoQuerySession:
        def scalar(self, _statement):
            pytest.fail("Rejected database target must not be queried")

    with pytest.raises(RuntimeError, match="Refusing to run"):
        create_demo_user._validate_database_target(NoQuerySession())


def test_database_target_guard_checks_connected_database_name(monkeypatch):
    monkeypatch.setattr(
        create_demo_user,
        "engine",
        SimpleNamespace(
            url=URL.create(
                "postgresql+psycopg2",
                host="127.0.0.1",
                port=55432,
                database="ledgerforge_demo_test",
            )
        ),
    )

    with pytest.raises(RuntimeError, match="connected database"):
        create_demo_user._validate_database_target(
            SimpleNamespace(scalar=lambda _statement: "other_database")
        )


def test_demo_state_is_idempotent_and_does_not_replace_password():
    engine, db = _session()
    try:
        assert create_demo_user._existing_demo_state(db) == "empty"
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
        stored_hash = hash_password("temporary-test-password")
        db.add(
            User(
                user_id="DEMOUSER001",
                employee_id="DEMOEMP001",
                username="demo_admin",
                role="ADMIN",
                is_active="Y",
                mfa_enabled="N",
                password_hash=stored_hash,
            )
        )
        db.commit()

        assert create_demo_user._existing_demo_state(db) == "already-created"
        assert db.get(User, "DEMOUSER001").password_hash == stored_hash
        assert db.query(Department).count() == 1
        assert db.query(Role).count() == 1
        assert db.query(Employee).count() == 1
        assert db.query(User).count() == 1
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
