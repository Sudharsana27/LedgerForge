import argparse
from datetime import date
from getpass import getpass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import MetaData, Table, func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import SessionLocal, engine
from app.models import Department, Employee, Role, User


DATABASE_NAME = "ledgerforge_demo"
DEMO_IDS = {
    "department": "DEMO01",
    "role": "DEMO01",
    "employee": "DEMOEMP001",
    "user": "DEMOUSER001",
}


def validate_target(url: URL, expected_host: str) -> None:
    if (
        url.drivername != "postgresql+psycopg2"
        or not expected_host
        or url.host != expected_host
        or url.database != DATABASE_NAME
        or url.host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError(
            "Refusing to run: use PostgreSQL with the explicitly confirmed "
            "host and the new ledgerforge_demo database."
        )


def ensure_database_empty(db: Session) -> None:
    inspector = inspect(db.get_bind())
    metadata = MetaData()
    populated = []
    schemas = [
        schema
        for schema in inspector.get_schema_names()
        if schema not in {"information_schema", "pg_catalog", "temp"}
    ]
    for schema in schemas:
        for table_name in inspector.get_table_names(schema=schema):
            if table_name == "alembic_version":
                continue
            table = Table(
                table_name,
                metadata,
                schema=schema,
                autoload_with=db.get_bind(),
            )
            count = db.scalar(select(func.count()).select_from(table))
            if count:
                populated.append(f"{schema}.{table_name}")
    if populated:
        raise RuntimeError(
            "Refusing to provision a non-empty database. Populated tables: "
            + ", ".join(sorted(populated))
        )


def lock_database_tables(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    inspector = inspect(db.get_bind())
    preparer = db.get_bind().dialect.identifier_preparer
    schemas = [
        schema
        for schema in inspector.get_schema_names()
        if schema not in {"information_schema", "pg_catalog", "temp"}
    ]
    tables = sorted(
        (schema, name)
        for schema in schemas
        for name in inspector.get_table_names(schema=schema)
    )
    if tables:
        quoted_names = ", ".join(
            f"{preparer.quote_schema(schema)}.{preparer.quote(name)}"
            for schema, name in tables
        )
        db.execute(
            text(
                f"LOCK TABLE {quoted_names} IN SHARE ROW EXCLUSIVE MODE"
            )
        )


def read_password() -> str:
    password = getpass("Demo password (minimum 12 characters): ")
    encoded = password.encode("utf-8")
    if not 12 <= len(encoded) <= 72:
        raise ValueError("Password must contain 12–72 UTF-8 bytes.")
    if getpass("Confirm demo password: ") != password:
        raise ValueError("Password entries do not match.")
    return password


def create_records(db: Session, password_hash: str) -> None:
    db.add(
        Department(
            department_id=DEMO_IDS["department"],
            department_name="Demonstration Department",
            cost_center="DEMO",
            description="Synthetic demonstration data",
        )
    )
    db.flush()
    db.add(
        Role(
            role_id=DEMO_IDS["role"],
            department_id=DEMO_IDS["department"],
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
            employee_id=DEMO_IDS["employee"],
            first_name="Demo",
            last_name="Administrator",
            full_name="Demo Administrator",
            work_email="demo-admin@example.invalid",
            hire_date=date(2026, 1, 1),
            employment_status="ACTIVE",
            employment_type="FULL_TIME",
            department_id=DEMO_IDS["department"],
            role_id=DEMO_IDS["role"],
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
            user_id=DEMO_IDS["user"],
            employee_id=DEMO_IDS["employee"],
            username="demo_admin",
            role="ADMIN",
            is_active="Y",
            mfa_enabled="N",
            password_hash=password_hash,
        )
    )
    db.flush()
    if (
        db.get(Role, DEMO_IDS["role"]).department_id
        != db.get(Department, DEMO_IDS["department"]).department_id
        or db.get(Employee, DEMO_IDS["employee"]).role_id
        != db.get(Role, DEMO_IDS["role"]).role_id
        or db.get(Employee, DEMO_IDS["employee"]).department_id
        != db.get(Department, DEMO_IDS["department"]).department_id
        or db.get(User, DEMO_IDS["user"]).employee_id
        != db.get(Employee, DEMO_IDS["employee"]).employee_id
    ):
        raise RuntimeError("Synthetic demo foreign-key verification failed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Provision one synthetic demo account in a new, empty hosted "
            "ledgerforge_demo PostgreSQL database."
        )
    )
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--confirm-demo", action="store_true")
    args = parser.parse_args()
    validate_target(engine.url, args.expected_host)
    if not args.confirm_demo:
        raise SystemExit("Pass --confirm-demo to enable the typed confirmation.")

    with SessionLocal() as db:
        if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
            raise RuntimeError("Connected database name does not match target.")
        ensure_database_empty(db)

    confirmation = input(
        f"Type CREATE-SYNTHETIC-DEMO {DATABASE_NAME}@{args.expected_host} "
        "to continue: "
    )
    if confirmation != f"CREATE-SYNTHETIC-DEMO {DATABASE_NAME}@{args.expected_host}":
        raise SystemExit("Cancelled; no changes made.")

    password = read_password()
    password_hash = hash_password(password)
    del password

    alembic_config = Config(
        str(Path(__file__).resolve().parents[1] / "alembic.ini")
    )
    command.upgrade(alembic_config, "head")

    with SessionLocal.begin() as db:
        validate_target(engine.url, args.expected_host)
        if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
            raise RuntimeError("Connected database name changed; refusing.")
        lock_database_tables(db)
        ensure_database_empty(db)
        create_records(db, password_hash)

    print("Synthetic demo account created.")
    print("Username: demo_admin")


if __name__ == "__main__":
    main()
