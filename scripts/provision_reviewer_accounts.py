import argparse
import os
from datetime import date
from getpass import getpass

from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import normalize_database_url
from app.database import SessionLocal, engine
from app.models import Department, Employee, Role, User


LOCAL_TARGET = ("127.0.0.1", 55432, "ledgerforge_demo_test")
HOSTED_DATABASE = "ledgerforge_wirm"
DEMO_EMPLOYEE_ID = "DEMOEMP001"
DEMO_USER_ID = "DEMOUSER001"
REVIEWERS = (
    {
        "employee_id": "DEMOHR001",
        "user_id": "DEMOUSERHR001",
        "username": "demo_hr",
        "role": "HR",
        "first_name": "Demo",
        "last_name": "Human Resources",
        "full_name": "Demo Human Resources",
        "work_email": "demo-hr@example.invalid",
    },
    {
        "employee_id": "DEMOEMP002",
        "user_id": "DEMOUSEREMP002",
        "username": "demo_employee",
        "role": "EMPLOYEE",
        "first_name": "Demo",
        "last_name": "Employee",
        "full_name": "Demo Employee",
        "work_email": "demo-employee@example.invalid",
    },
)


def _validate_target(*, hosted: bool, expected_host: str | None) -> None:
    url = engine.url
    if url.drivername != "postgresql+psycopg2":
        raise RuntimeError("Refusing to run: PostgreSQL is required.")

    if not hosted:
        if (url.host, url.port, url.database) != LOCAL_TARGET:
            raise RuntimeError(
                "Refusing to run: local mode is restricted to the approved "
                "disposable PostgreSQL target."
            )
        return

    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url or not expected_host:
        raise RuntimeError(
            "Refusing to run: hosted mode requires a private DATABASE_URL "
            "and --expected-host."
        )
    private_url = make_url(normalize_database_url(raw_url))
    if (
        private_url != url
        or private_url.host != expected_host
        or private_url.database != HOSTED_DATABASE
        or private_url.host in {"localhost", "127.0.0.1", "::1"}
    ):
        raise RuntimeError(
            "Refusing to run: database target does not match the explicitly "
            "expected hosted database."
        )


def _check_anchor_records(db: Session) -> None:
    department = db.get(Department, "DEMO01")
    role = db.get(Role, "DEMO01")
    employee = db.get(Employee, DEMO_EMPLOYEE_ID)
    admin = db.get(User, DEMO_USER_ID)
    if (
        department is None
        or department.department_name != "Demonstration Department"
        or role is None
        or role.department_id != department.department_id
        or role.role_title != "Demo Administrator"
        or employee is None
        or employee.department_id != department.department_id
        or employee.role_id != role.role_id
        or admin is None
        or admin.employee_id != employee.employee_id
        or admin.username != "demo_admin"
        or admin.role != "ADMIN"
        or admin.is_active != "Y"
        or not admin.password_hash
    ):
        raise RuntimeError(
            "Refusing to provision: expected synthetic demo anchors are "
            "missing or do not match."
        )


def account_status(db: Session) -> list[tuple[str, str]]:
    _check_anchor_records(db)
    result = [("demo_admin", "present; unchanged")]
    for spec in REVIEWERS:
        employee = db.get(Employee, spec["employee_id"])
        user = db.get(User, spec["user_id"])
        named_user = db.scalar(
            select(User).where(User.username == spec["username"])
        )
        if named_user is not None and named_user.user_id != spec["user_id"]:
            raise RuntimeError(
                "Refusing to provision: reviewer username is already in use."
            )
        if employee is not None and (
            employee.first_name != spec["first_name"]
            or employee.last_name != spec["last_name"]
            or employee.full_name != spec["full_name"]
            or employee.work_email != spec["work_email"]
            or employee.department_id != "DEMO01"
            or employee.role_id != "DEMO01"
        ):
            raise RuntimeError(
                "Refusing to modify an existing non-matching reviewer employee."
            )
        employee_user = db.scalar(
            select(User).where(User.employee_id == spec["employee_id"])
        )
        if employee_user is not None and employee_user.user_id != spec["user_id"]:
            raise RuntimeError(
                "Refusing to provision: reviewer employee is linked to "
                "another user."
            )
        if user is not None and (
            user.employee_id != spec["employee_id"]
            or user.username != spec["username"]
            or user.role != spec["role"]
            or user.is_active != "Y"
            or not user.password_hash
        ):
            raise RuntimeError(
                "Refusing to modify an existing non-matching reviewer account."
            )
        if user is not None and employee is None:
            raise RuntimeError(
                "Refusing to provision: reviewer user has no employee record."
            )
        result.append(
            (
                spec["username"],
                "ready; unchanged" if user is not None else "missing",
            )
        )
    return result


def provision_missing_accounts(
    db: Session,
    password_hashes: dict[str, str],
) -> list[str]:
    states = dict(account_status(db))
    created = []
    for spec in REVIEWERS:
        if states[spec["username"]] == "ready; unchanged":
            continue
        if spec["username"] not in password_hashes:
            raise ValueError("A password hash is required for each new account.")

        employee = db.get(Employee, spec["employee_id"])
        if employee is None:
            employee = Employee(
                employee_id=spec["employee_id"],
                first_name=spec["first_name"],
                last_name=spec["last_name"],
                full_name=spec["full_name"],
                work_email=spec["work_email"],
                hire_date=date(2026, 1, 1),
                employment_status="ACTIVE",
                employment_type="FULL_TIME",
                department_id="DEMO01",
                role_id="DEMO01",
                manager_id=DEMO_EMPLOYEE_ID,
                work_location="Demo",
                work_mode="REMOTE",
                pf_applicable="N",
                esi_applicable="N",
                notice_period_days=0,
            )
            db.add(employee)
            db.flush()
        db.add(
            User(
                user_id=spec["user_id"],
                employee_id=spec["employee_id"],
                username=spec["username"],
                role=spec["role"],
                is_active="Y",
                mfa_enabled="N",
                created_at="2026-11-21",
                password_hash=password_hashes[spec["username"]],
            )
        )
        created.append(spec["username"])
    db.flush()
    account_status(db)
    return created


def _read_passwords(missing_usernames: list[str]) -> dict[str, str]:
    hashes = {}
    for username in missing_usernames:
        password = getpass(f"Password for {username} (12–72 UTF-8 bytes): ")
        encoded = password.encode("utf-8")
        if not 12 <= len(encoded) <= 72:
            raise ValueError("Password must contain 12–72 UTF-8 bytes.")
        if getpass(f"Confirm password for {username}: ") != password:
            raise ValueError("Password entries do not match.")
        hashes[username] = hash_password(password)
        del password
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect or provision synthetic HR and Employee demo users."
    )
    parser.add_argument("--hosted", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    _validate_target(hosted=args.hosted, expected_host=args.expected_host)

    with SessionLocal() as db:
        expected_database = HOSTED_DATABASE if args.hosted else LOCAL_TARGET[2]
        if db.scalar(text("SELECT current_database()")) != expected_database:
            raise RuntimeError(
                "Connected database name does not match the approved target."
            )
        if args.hosted:
           db.rollback()
           db.execute(text("SET TRANSACTION READ ONLY"))
           statuses = account_status(db)
        else:
           statuses = account_status(db)
        print("Reviewer account preflight:")
        for username, state in statuses:
            print(f"{username}: {state}")

    if args.preflight_only:
        return

    missing = [
        username for username, state in statuses if state == "missing"
    ]
    if not missing:
        print("All reviewer accounts are ready; no changes made.")
        return
    if not args.hosted:
        confirmation = input(
            "Type CREATE-REVIEWERS to add only the missing synthetic "
            "accounts to the disposable local database: "
        )
    else:
        confirmation = input(
            f"Type CREATE-REVIEWERS {HOSTED_DATABASE}@{args.expected_host} "
            "to authorize synthetic hosted inserts: "
        )
    expected = (
        f"CREATE-REVIEWERS {HOSTED_DATABASE}@{args.expected_host}"
        if args.hosted
        else "CREATE-REVIEWERS"
    )
    if confirmation != expected:
        raise SystemExit("Cancelled; no changes made.")

    password_hashes = _read_passwords(missing)
    _validate_target(hosted=args.hosted, expected_host=args.expected_host)
    with SessionLocal.begin() as db:
        if args.hosted:
            db.execute(text("SELECT pg_advisory_xact_lock(8127, 2016)"))
            if db.scalar(text("SELECT current_database()")) != HOSTED_DATABASE:
                raise RuntimeError("Connected database changed; refusing.")
        created = provision_missing_accounts(db, password_hashes)
    print(f"Reviewer accounts created: {', '.join(created)}")
    print("Existing admin and ready reviewer accounts were not modified.")


if __name__ == "__main__":
    main()
