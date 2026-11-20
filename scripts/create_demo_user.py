import argparse
from datetime import date
from getpass import getpass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import SessionLocal, engine
from app.models import Department, Employee, Role, User


DATABASE_HOST = "127.0.0.1"
DATABASE_PORT = 55432
DATABASE_NAME = "ledgerforge_demo_test"
DEMO_IDS = {
    "department": "DEMO01",
    "role": "DEMO01",
    "employee": "DEMOEMP001",
    "user": "DEMOUSER001",
}


def _validate_database_target(db: Session) -> None:
    url = engine.url
    if (
        url.drivername != "postgresql+psycopg2"
        or url.host != DATABASE_HOST
        or url.port != DATABASE_PORT
        or url.database != DATABASE_NAME
    ):
        raise RuntimeError(
            "Refusing to run: DATABASE_URL must target the approved "
            "disposable local PostgreSQL database."
        )

    actual_database = db.scalar(text("SELECT current_database()"))
    if actual_database != DATABASE_NAME:
        raise RuntimeError(
            "Refusing to run: the connected database does not match the "
            "approved disposable database."
        )


def _existing_demo_state(db: Session) -> str:
    models = (Department, Role, Employee, User)
    counts = {
        model: db.scalar(select(func.count()).select_from(model))
        for model in models
    }

    if all(count == 0 for count in counts.values()):
        return "empty"

    if not all(count == 1 for count in counts.values()):
        raise RuntimeError(
            "Refusing to modify a database with existing records in the "
            "demo account tables."
        )

    department = db.get(Department, DEMO_IDS["department"])
    role = db.get(Role, DEMO_IDS["role"])
    employee = db.get(Employee, DEMO_IDS["employee"])
    user = db.get(User, DEMO_IDS["user"])
    if (
        department is None
        or department.department_name != "Demonstration Department"
        or department.cost_center != "DEMO"
        or department.description != "Synthetic demonstration data"
        or role is None
        or role.department_id != DEMO_IDS["department"]
        or role.role_title != "Demo Administrator"
        or role.level != 1
        or role.grade != "DEMO"
        or role.band_min_annual != 0
        or role.band_mid_annual != 0
        or role.band_max_annual != 0
        or role.overtime_eligible != "N"
        or role.band_year != 2026
        or employee is None
        or employee.first_name != "Demo"
        or employee.last_name != "Administrator"
        or employee.full_name != "Demo Administrator"
        or employee.department_id != DEMO_IDS["department"]
        or employee.role_id != DEMO_IDS["role"]
        or employee.work_email != "demo-admin@example.invalid"
        or employee.hire_date != date(2026, 1, 1)
        or employee.employment_status != "ACTIVE"
        or employee.employment_type != "FULL_TIME"
        or employee.manager_id is not None
        or employee.work_location != "Demo"
        or employee.work_mode != "REMOTE"
        or employee.pf_applicable != "N"
        or employee.esi_applicable != "N"
        or employee.notice_period_days != 0
        or user is None
        or user.employee_id != DEMO_IDS["employee"]
        or user.username != "demo_admin"
        or user.role != "ADMIN"
        or not user.password_hash
    ):
        raise RuntimeError(
            "Refusing to modify existing records that do not exactly match "
            "the synthetic demo account."
        )

    return "already-created"


def _read_password() -> str:
    password = getpass("Temporary demo password (minimum 12 characters): ")
    if len(password.encode("utf-8")) < 12:
        raise ValueError("Password must contain at least 12 UTF-8 bytes.")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 72 UTF-8 bytes.")
    confirmation = getpass("Confirm temporary demo password: ")
    if password != confirmation:
        raise ValueError("The password entries do not match.")
    return password


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create one synthetic account in the disposable demo database."
    )
    parser.add_argument(
        "--confirm-demo",
        action="store_true",
        help="enable the explicit interactive confirmation prompt",
    )
    args = parser.parse_args()

    if not args.confirm_demo:
        raise SystemExit("Pass --confirm-demo to proceed.")

    with SessionLocal() as db:
        _validate_database_target(db)
        state = _existing_demo_state(db)
        if state == "already-created":
            print("Synthetic demo records already exist; no changes made.")
            return

    confirmation = input(
        "Type CREATE-DEMO to create synthetic records in the verified "
        "disposable database: "
    )
    if confirmation != "CREATE-DEMO":
        raise SystemExit("Cancelled; no changes made.")

    password = _read_password()
    password_hash = hash_password(password)
    del password

    with SessionLocal.begin() as db:
        _validate_database_target(db)
        if _existing_demo_state(db) != "empty":
            raise RuntimeError(
                "Demo records appeared before creation; no changes made."
            )

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
    print("Synthetic demonstration account created.")
    print("Username: demo_admin")


if __name__ == "__main__":
    main()
