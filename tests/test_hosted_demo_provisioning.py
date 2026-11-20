import pytest
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.database import Base
from app.models import Department, Employee, Role, User
from scripts.provision_hosted_demo import (
    DATABASE_NAME,
    create_records,
    ensure_database_empty,
    validate_target,
)


@pytest.mark.parametrize(
    "url",
    [
        URL.create(
            "postgresql+psycopg2",
            host="127.0.0.1",
            port=55432,
            database=DATABASE_NAME,
        ),
        URL.create(
            "postgresql+psycopg2",
            host="another-host.example",
            port=5432,
            database=DATABASE_NAME,
        ),
        URL.create(
            "postgresql+psycopg2",
            host="approved-host.example",
            port=5432,
            database="ledgerforge",
        ),
        URL.create(
            "sqlite",
            database=DATABASE_NAME,
        ),
    ],
)
def test_hosted_demo_target_guard_rejects_mismatches(url):
    with pytest.raises(RuntimeError, match="Refusing to run"):
        validate_target(url, "approved-host.example")


def test_hosted_demo_provisioning_requires_all_tables_empty_and_hashes_password():
    database_engine = create_engine("sqlite://")
    Base.metadata.create_all(database_engine)
    try:
        with Session(database_engine) as db:
            ensure_database_empty(db)
            password_hash = hash_password("temporary-test-password")
            create_records(db, password_hash)
            db.commit()
            ensure_database_empty_raises(db)
            assert db.query(Department).count() == 1
            assert db.query(Role).count() == 1
            assert db.query(Employee).count() == 1
            assert db.query(User).count() == 1
            user = db.query(User).one()
            assert user.password_hash != "temporary-test-password"
            assert verify_password("temporary-test-password", user.password_hash)
            assert db.get(Employee, "DEMOEMP001").role_id == "DEMO01"
            assert db.get(User, "DEMOUSER001").employee_id == "DEMOEMP001"
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


def ensure_database_empty_raises(db):
    with pytest.raises(RuntimeError, match="non-empty database"):
        ensure_database_empty(db)
