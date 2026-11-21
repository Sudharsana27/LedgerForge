import argparse
import os
from datetime import date
from getpass import getpass

from sqlalchemy import MetaData, Table, func, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import normalize_database_url
from app.database import SessionLocal, engine
from app.models import Department, Employee, Role, User


DATABASE_NAME = "ledgerforge_wirm"
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
            f"host and the {DATABASE_NAME} database."
        )


def validate_private_database_url(expected_host: str) -> None:
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url:
        raise RuntimeError(
            "Refusing to run: set DATABASE_URL in the private process "
            "environment; values loaded only from .env are not accepted."
        )
    private_url = make_url(normalize_database_url(raw_url))
    validate_target(private_url, expected_host)
    if private_url != engine.url:
        raise RuntimeError(
            "Refusing to run: DATABASE_URL does not match the application's "
            "configured database target."
        )


def database_inventory(db: Session) -> dict[str, int]:
    inspector = inspect(db.get_bind())
    metadata = MetaData()
    inventory = {}
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
            inventory[f"{schema}.{table_name}"] = db.scalar(
                select(func.count()).select_from(table)
            )
    return inventory


def ensure_schema_ready(inventory: dict[str, int]) -> None:
    required_tables = {
        f"public.{model.__table__.name}"
        for model in (Department, Role, Employee, User)
    }
    missing = required_tables - inventory.keys()
    if missing:
        raise RuntimeError(
            "Refusing to provision: required public schema tables are missing: "
            + ", ".join(sorted(missing))
        )


def ensure_database_empty(inventory: dict[str, int]) -> None:
    populated = [
        table_name
        for table_name, count in inventory.items()
        if not table_name.endswith(".alembic_version") and count
    ]
    if populated:
        raise RuntimeError(
            "Refusing to provision a non-empty database. Populated tables: "
            + ", ".join(sorted(populated))
        )


def read_only_inventory(expected_host: str) -> dict[str, int]:
    validate_private_database_url(expected_host)
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            with Session(bind=connection) as db:
                if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
                    raise RuntimeError(
                        "Connected database name does not match target."
                    )
                return database_inventory(db)


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
            "Provision one synthetic demo account in an empty "
            f"{DATABASE_NAME} PostgreSQL database."
        )
    )
    parser.add_argument("--expected-host", required=True)
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="inspect schema and row counts without modifying the database",
    )
    args = parser.parse_args()

    inventory = read_only_inventory(args.expected_host)
    print(f"database={DATABASE_NAME}")
    if inventory:
        for table_name, count in sorted(inventory.items()):
            print(f"{table_name} rows={count}")
    else:
        print("No user tables found.")

    if args.preflight_only:
        return

    ensure_schema_ready(inventory)
    ensure_database_empty(inventory)

    password = read_password()
    password_hash = hash_password(password)
    del password

    with SessionLocal.begin() as db:
        validate_private_database_url(args.expected_host)
        if db.scalar(text("SELECT current_database()")) != DATABASE_NAME:
            raise RuntimeError("Connected database name changed; refusing.")
        lock_database_tables(db)
        inventory = database_inventory(db)
        ensure_schema_ready(inventory)
        ensure_database_empty(inventory)
        confirmation = input(
            f"Type INSERT-SYNTHETIC-DEMO {DATABASE_NAME}@"
            f"{args.expected_host} to authorize these four synthetic records: "
        )
        if confirmation != (
            f"INSERT-SYNTHETIC-DEMO {DATABASE_NAME}@{args.expected_host}"
        ):
            raise SystemExit("Cancelled; no changes made.")
        create_records(db, password_hash)
        if any(
            db.scalar(select(func.count()).select_from(model)) != 1
            for model in (Department, Role, Employee, User)
        ):
            raise RuntimeError(
                "Synthetic record count verification failed; rolling back."
            )

    print("Synthetic demo account created.")
    print("Username: demo_admin")


if __name__ == "__main__":
    main()
