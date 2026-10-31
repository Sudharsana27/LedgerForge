from datetime import date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database import Base, get_db
from app.main import app
from app.models import (
    Attendance,
    Department,
    Employee,
    Holiday,
    LeaveBalance,
    LeaveRequest,
    LeaveType,
    Role,
)
from app.leave_service import LeaveError, apply_for_leave


SOURCE_HAND_COUNTS = {
    "EMP-0002": {
        "days_present": 2,
        "work_from_home_days": 18,
        "absent_days": 0.0,
        "late_days": 1,
        "overtime_hours": 0.0,
        "missing_checkout_count": 0,
    },
    "EMP-0004": {
        "days_present": 12,
        "work_from_home_days": 5,
        "absent_days": 0.0,
        "late_days": 0,
        "overtime_hours": 0.0,
        "missing_checkout_count": 0,
    },
    "EMP-0006": {
        "days_present": 18,
        "work_from_home_days": 1,
        "absent_days": 0.0,
        "late_days": 1,
        "overtime_hours": 0.0,
        "missing_checkout_count": 0,
    },
}


@pytest.fixture
def test_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(engine)

    with testing_session() as db:
        departments_file = Path(settings.data_dir).resolve() / "departments.csv"
        department_rows = pd.read_csv(departments_file)
        department_ids = set()
        for record in department_rows.to_dict(orient="records"):
            record["description"] = (
                None
                if pd.isna(record.get("description"))
                else record.get("description")
            )
            department_ids.add(record["department_id"])
            db.add(Department(**record))
        if "D01" not in department_ids:
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
                band_mid_annual=500000,
                band_max_annual=700000,
                overtime_eligible="Y",
                band_year=2026,
            )
        )
        for employee_id in SOURCE_HAND_COUNTS:
            db.add(
                Employee(
                    employee_id=employee_id,
                    first_name="Test",
                    last_name=employee_id,
                    full_name=f"Test {employee_id}",
                    work_email=f"{employee_id.lower()}@example.com",
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
                )
            )

        leave_types = [
            ("CL", "Casual Leave", "Paid", 12),
            ("SL", "Sick Leave", "Paid", 12),
            ("EL", "Earned Leave", "Paid", 15),
            ("ML", "Maternity Leave", "Paid", 182),
            ("BL", "Bereavement Leave", "Paid", 3),
            ("LOP", "Loss of Pay", "Unpaid", 0),
        ]
        for code, name, pay_type, quota in leave_types:
            db.add(
                LeaveType(
                    leave_type_code=code,
                    leave_type_name=name,
                    pay_type=pay_type,
                    annual_quota_days=quota,
                    prorated_for_joiners="N",
                    carry_forward_allowed="N",
                    max_carry_forward_days=0,
                    policy_note="Test policy",
                )
            )
        for employee_id in SOURCE_HAND_COUNTS:
            db.add(
                LeaveBalance(
                    employee_id=employee_id,
                    as_of_date=date(2026, 9, 30),
                    financial_year="FY2026-27",
                    cl_entitlement=Decimal("10"),
                    cl_used=Decimal("0"),
                    cl_balance=Decimal("10"),
                    sl_entitlement=Decimal("10"),
                    sl_used=Decimal("0"),
                    sl_balance=Decimal("10"),
                    el_used_fy=Decimal("0"),
                    el_balance=Decimal("20"),
                    pending_days=Decimal("0"),
                )
            )
            db.add(
                LeaveBalance(
                    employee_id=employee_id,
                    as_of_date=date(2026, 3, 31),
                    financial_year="FY2025-26",
                    cl_entitlement=Decimal("10"),
                    cl_used=Decimal("0"),
                    cl_balance=Decimal("10"),
                    sl_entitlement=Decimal("10"),
                    sl_used=Decimal("0"),
                    sl_balance=Decimal("10"),
                    el_used_fy=Decimal("0"),
                    el_balance=Decimal("20"),
                    pending_days=Decimal("0"),
                )
            )

        holidays_file = Path(settings.data_dir).resolve() / "holidays.csv"
        holiday_rows = pd.read_csv(holidays_file)
        for record in holiday_rows.to_dict(orient="records"):
            record["holiday_date"] = date.fromisoformat(
                record["holiday_date"]
            )
            db.add(Holiday(**record))
        db.add(
            Holiday(
                holiday_date=date(2026, 8, 3),
                holiday_name="Test regional holiday",
                holiday_type="Regional",
                weekday="Monday",
                falls_on_weekend="N",
                calendar_note="Test calendar",
            )
        )
        db.commit()

        source_file = Path(settings.data_dir).resolve() / "attendance.csv"
        source_rows = pd.read_csv(
            source_file,
            usecols=[
                "attendance_id",
                "employee_id",
                "attendance_date",
                "weekday",
                "status",
                "leave_type_code",
                "check_in",
                "check_out",
                "hours_worked",
                "overtime_hours",
                "late_flag",
                "source",
                "data_quality_flag",
                "department_id",
            ],
        )
        source_rows = source_rows[
            source_rows.employee_id.isin(SOURCE_HAND_COUNTS)
            & source_rows.attendance_date.str.startswith("2025-04-")
        ]
        for record in source_rows.to_dict(orient="records"):
            record["attendance_date"] = date.fromisoformat(
                record["attendance_date"]
            )
            for field in ("hours_worked", "overtime_hours"):
                value = record[field]
                record[field] = (
                    None if pd.isna(value) else Decimal(str(value))
                )
            for field, value in record.items():
                if pd.isna(value):
                    record[field] = None
            db.add(Attendance(**record))

        db.add(
            Attendance(
                attendance_id="ATT-MISSING-CHECKOUT",
                employee_id="EMP-0002",
                attendance_date=date(2025, 5, 5),
                weekday="Mon",
                status="PRESENT",
                leave_type_code=None,
                check_in="09:00",
                check_out=None,
                hours_worked=None,
                overtime_hours=None,
                late_flag="N",
                source="Test record",
                data_quality_flag="MISSING_CHECKOUT",
                department_id="D01",
            )
        )
        db.add(
            Attendance(
                attendance_id="ATT-HALF-UNPAID",
                employee_id="EMP-0002",
                attendance_date=date(2025, 5, 6),
                weekday="Tue",
                status="HALF_DAY_UNPAID",
                leave_type_code=None,
                check_in=None,
                check_out=None,
                hours_worked=None,
                overtime_hours=Decimal("0"),
                late_flag="N",
                source="Test record",
                data_quality_flag=None,
                department_id="D01",
            )
        )
        db.add(
            Attendance(
                attendance_id="ATT-OVERTIME",
                employee_id="EMP-0002",
                attendance_date=date(2025, 5, 7),
                weekday="Wed",
                status="PRESENT",
                leave_type_code=None,
                check_in="09:00",
                check_out="19:30",
                hours_worked=Decimal("10.5"),
                overtime_hours=Decimal("2.5"),
                late_flag="N",
                source="Test record",
                data_quality_flag=None,
                department_id="D01",
            )
        )
        db.commit()

    yield testing_session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(test_database):
    def override_get_db():
        db = test_database()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("employee_id", "expected"),
    SOURCE_HAND_COUNTS.items(),
)
def test_monthly_summaries_match_independent_csv_counts(
    client, employee_id, expected
):
    response = client.get(
        f"/attendance/{employee_id}/monthly-summary",
        params={"month": "2025-04"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["employee_id"] == employee_id
    assert result["month"] == "2025-04"
    assert result["recorded_days"] == 20
    assert result["working_days"] == 20
    for metric, value in expected.items():
        assert result[metric] == value


def test_attendance_missing_checkout_and_empty_month(client):
    missing = client.get(
        "/attendance/EMP-0002/monthly-summary",
        params={"month": "2025-05"},
    )
    assert missing.status_code == 200
    assert missing.json()["days_present"] == 2
    assert missing.json()["missing_checkout_count"] == 1
    assert missing.json()["absent_days"] == 0.5
    assert missing.json()["overtime_hours"] == 2.5

    empty = client.get(
        "/attendance/EMP-0002/monthly-summary",
        params={"month": "2025-06"},
    )
    assert empty.status_code == 200
    assert empty.json()["recorded_days"] == 0
    assert empty.json()["days_present"] == 0
    assert empty.json()["working_days"] == 21


def test_attendance_validates_employee_month_and_date_range(client):
    assert client.get(
        "/attendance/UNKNOWN/monthly-summary",
        params={"month": "2025-04"},
    ).status_code == 404
    assert client.get(
        "/attendance/EMP-0002/monthly-summary",
        params={"month": "2025-13"},
    ).status_code == 422
    assert client.get(
        "/attendance/EMP-0002",
        params={"start_date": "2025-05-10", "end_date": "2025-05-01"},
    ).status_code == 422


def test_attendance_date_range_returns_matching_rows(client):
    response = client.get(
        "/attendance/EMP-0002",
        params={"start_date": "2025-04-01", "end_date": "2025-04-30"},
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 20
    assert all(row["employee_id"] == "EMP-0002" for row in rows)
    assert all("2025-04-01" <= row["attendance_date"] <= "2025-04-30" for row in rows)


def test_attendance_duplicate_dates_fail_explicitly(client, test_database):
    with test_database() as db:
        original = db.query(Attendance).filter_by(
            employee_id="EMP-0002",
            attendance_date=date(2025, 4, 1),
        ).one()
        db.add(
            Attendance(
                attendance_id="ATT-DUPLICATE-DATE",
                employee_id=original.employee_id,
                attendance_date=original.attendance_date,
                weekday=original.weekday,
                status=original.status,
                leave_type_code=original.leave_type_code,
                check_in=original.check_in,
                check_out=original.check_out,
                hours_worked=original.hours_worked,
                overtime_hours=original.overtime_hours,
                late_flag=original.late_flag,
                source="Test duplicate",
                data_quality_flag=original.data_quality_flag,
                department_id=original.department_id,
            )
        )
        db.commit()

    response = client.get(
        "/attendance/EMP-0002/monthly-summary",
        params={"month": "2025-04"},
    )
    assert response.status_code == 422
    assert "Multiple attendance records" in response.json()["detail"]


def test_leave_apply_approve_and_prevent_double_deduction(client, test_database):
    applied = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-01",
            "end_date": "2026-08-07",
            "reason": "Family event",
        },
    )
    assert applied.status_code == 201
    request = applied.json()
    assert request["status"] == "Pending"
    assert request["days"] == 4

    with test_database() as db:
        balance = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert balance.cl_balance == Decimal("10")
        assert balance.cl_used == Decimal("0")
        assert balance.pending_days == Decimal("4")

    approved = client.post(
        f"/leave/requests/{request['leave_request_id']}/approve",
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "Approved"
    assert approved.json()["days"] == 4

    with test_database() as db:
        balance = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert balance.cl_balance == Decimal("6")
        assert balance.cl_used == Decimal("4")
        assert balance.pending_days == Decimal("0")

    repeated = client.post(
        f"/leave/requests/{request['leave_request_id']}/approve",
        json={},
    )
    assert repeated.status_code == 409
    with test_database() as db:
        balance = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert balance.cl_balance == Decimal("6")
        assert balance.cl_used == Decimal("4")
        assert balance.pending_days == Decimal("0")


def test_leave_reject_insufficient_balance_and_overlapping_request(
    client, test_database
):
    first = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-04",
            "end_date": "2026-08-05",
            "reason": "Personal",
        },
    )
    assert first.status_code == 201
    assert first.json()["days"] == 2
    assert client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "SL",
            "start_date": "2026-08-05",
            "end_date": "2026-08-06",
            "reason": "Overlap attempt",
        },
    ).status_code == 409

    rejected = client.post(
        f"/leave/requests/{first.json()['leave_request_id']}/reject",
        json={},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "Rejected"
    with test_database() as db:
        balance = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert balance.cl_balance == Decimal("10")
        assert balance.cl_used == Decimal("0")
        assert balance.pending_days == Decimal("0")
    assert client.post(
        f"/leave/requests/{first.json()['leave_request_id']}/reject",
        json={},
    ).status_code == 409
    released = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-04",
            "end_date": "2026-08-05",
            "reason": "Reapply after rejection",
        },
    )
    assert released.status_code == 201

    insufficient = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-09-01",
            "end_date": "2026-09-30",
            "reason": "Long leave",
        },
    )
    assert insufficient.status_code == 409
    assert "Insufficient" in insufficient.json()["detail"]


def test_pending_requests_reserve_available_balance(client, test_database):
    first = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-04",
            "end_date": "2026-08-11",
            "reason": "First request",
        },
    )
    assert first.status_code == 201
    assert first.json()["days"] == 6
    with test_database() as db:
        balance = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert balance.pending_days == Decimal("6")
    second = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-12",
            "end_date": "2026-08-19",
            "reason": "Second request",
        },
    )
    assert second.status_code == 409
    assert "Insufficient" in second.json()["detail"]


def test_leave_request_spans_month_and_financial_year(client, test_database):
    applied = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-03-30",
            "end_date": "2026-04-02",
            "reason": "Financial year transition",
        },
    )
    assert applied.status_code == 201
    assert applied.json()["days"] == 4
    with test_database() as db:
        previous = db.get(LeaveBalance, ("EMP-0002", "FY2025-26"))
        current = db.get(LeaveBalance, ("EMP-0002", "FY2026-27"))
        assert previous.pending_days == Decimal("2")
        assert current.pending_days == Decimal("2")


def test_ml_entitlement_accumulates_across_financial_years(client):
    request_payload = {
        "employee_id": "EMP-0002",
        "leave_type_code": "ML",
        "entitlement_reference": "MAT-2026-001",
        "reason": "Maternity leave",
    }
    first = client.post(
        "/leave/requests",
        json={
            **request_payload,
            "start_date": "2026-03-02",
            "end_date": "2026-07-01",
        },
    )
    assert first.status_code == 201
    assert first.json()["days"] == 83

    second = client.post(
        "/leave/requests",
        json={
            **request_payload,
            "start_date": "2027-03-01",
            "end_date": "2027-04-30",
        },
    )
    assert second.status_code == 409
    assert "entitlement quota exceeded" in second.json()["detail"]


def test_ml_entitlement_requires_reconciliation_of_unlinked_history(
    client, test_database
):
    with test_database() as db:
        db.add(
            LeaveRequest(
                leave_request_id="LR-ML-LEGACY",
                employee_id="EMP-0002",
                leave_type_code="ML",
                entitlement_reference=None,
                start_date=date(2025, 5, 1),
                end_date=date(2025, 5, 2),
                days=Decimal("2"),
                reason="Imported historical request",
                status="Approved",
                applied_on=date(2025, 4, 1),
                approver_id=None,
                decided_on=date(2025, 4, 2),
            )
        )
        db.commit()

    response = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "ML",
            "entitlement_reference": "MAT-2026-001",
            "start_date": "2026-03-02",
            "end_date": "2026-03-02",
            "reason": "Maternity leave",
        },
    )
    assert response.status_code == 409
    assert "must be assigned entitlement references" in response.json()["detail"]


def test_bl_event_limit_spans_financial_years_and_allows_distinct_event(client):
    first = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "BL",
            "entitlement_reference": "EVENT-2027-01",
            "start_date": "2027-03-29",
            "end_date": "2027-03-30",
            "reason": "Bereavement",
        },
    )
    assert first.status_code == 201

    same_event = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "BL",
            "entitlement_reference": "EVENT-2027-01",
            "start_date": "2027-04-01",
            "end_date": "2027-04-01",
            "reason": "Continuation of same event",
        },
    )
    assert same_event.status_code == 201
    approved = client.post(
        f"/leave/requests/{first.json()['leave_request_id']}/approve",
        json={},
    )
    assert approved.status_code == 200
    assert client.post(
        f"/leave/requests/{first.json()['leave_request_id']}/approve",
        json={},
    ).status_code == 409

    over_quota = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "BL",
            "entitlement_reference": "EVENT-2027-01",
            "start_date": "2027-04-02",
            "end_date": "2027-04-02",
            "reason": "Same event exceeds entitlement",
        },
    )
    assert over_quota.status_code == 409

    other_event = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "BL",
            "entitlement_reference": "EVENT-2027-02",
            "start_date": "2027-04-05",
            "end_date": "2027-04-06",
            "reason": "Separate bereavement event",
        },
    )
    assert other_event.status_code == 201


def test_leave_applications_serialize_reservations_in_sqlite(tmp_path):
    database_path = tmp_path / "concurrent-leave.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    with testing_session() as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Engineering",
                cost_center="CC01",
                description=None,
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
                band_mid_annual=500000,
                band_max_annual=700000,
                overtime_eligible="Y",
                band_year=2026,
            )
        )
        db.flush()
        db.add(
            Employee(
                employee_id="EMP-LOCK",
                first_name="Concurrent",
                last_name="Request",
                full_name="Concurrent Request",
                work_email="concurrent@example.com",
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
            )
        )
        db.add(
            LeaveType(
                leave_type_code="CL",
                leave_type_name="Casual Leave",
                pay_type="Paid",
                annual_quota_days=12,
                prorated_for_joiners="N",
                carry_forward_allowed="N",
                max_carry_forward_days=0,
                policy_note="Short-notice personal leave",
            )
        )
        db.add(
            LeaveBalance(
                employee_id="EMP-LOCK",
                as_of_date=date(2026, 9, 30),
                financial_year="FY2026-27",
                cl_entitlement=Decimal("8"),
                cl_used=Decimal("0"),
                cl_balance=Decimal("8"),
                sl_entitlement=Decimal("8"),
                sl_used=Decimal("0"),
                sl_balance=Decimal("8"),
                el_used_fy=Decimal("0"),
                el_balance=Decimal("0"),
                pending_days=Decimal("0"),
            )
        )
        db.commit()

    barrier = Barrier(2)

    def submit(start_date):
        with testing_session() as db:
            barrier.wait(timeout=10)
            try:
                apply_for_leave(
                    db,
                    employee_id="EMP-LOCK",
                    leave_type_code="CL",
                    start_date=start_date,
                    end_date=start_date.replace(day=start_date.day + 4),
                    reason="Concurrent reservation",
                )
                return "created"
            except LeaveError as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    submit,
                    [date(2026, 8, 3), date(2026, 8, 10)],
                )
            )
        assert results.count("created") == 1
        assert results.count(409) == 1
        with testing_session() as db:
            assert db.query(LeaveBalance).filter_by(
                employee_id="EMP-LOCK",
                financial_year="FY2026-27",
            ).one().pending_days == Decimal("5")
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def _file_leave_sessions(database_path, cl_balance):
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    with testing_session() as db:
        db.add(
            Department(
                department_id="D01",
                department_name="Engineering",
                cost_center="CC01",
                description=None,
            )
        )
        db.flush()
        db.add(
            Role(
                role_id="R01",
                department_id="D01",
                role_title="Developer",
                level=1,
                grade="G1",
                band_min_annual=300000,
                band_mid_annual=500000,
                band_max_annual=700000,
                overtime_eligible="Y",
                band_year=2026,
            )
        )
        db.flush()
        db.add(
            Employee(
                employee_id="EMP-LOCK",
                first_name="Concurrent",
                last_name="Request",
                full_name="Concurrent Request",
                work_email="concurrent@example.com",
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
            )
        )
        db.add(
            LeaveType(
                leave_type_code="CL",
                leave_type_name="Casual Leave",
                pay_type="Paid",
                annual_quota_days=12,
                prorated_for_joiners="N",
                carry_forward_allowed="N",
                max_carry_forward_days=0,
                policy_note="Short-notice personal leave",
            )
        )
        db.add(
            LeaveBalance(
                employee_id="EMP-LOCK",
                as_of_date=date(2026, 9, 30),
                financial_year="FY2026-27",
                cl_entitlement=Decimal(str(cl_balance)),
                cl_used=Decimal("0"),
                cl_balance=Decimal(str(cl_balance)),
                sl_entitlement=Decimal("8"),
                sl_used=Decimal("0"),
                sl_balance=Decimal("8"),
                el_used_fy=Decimal("0"),
                el_balance=Decimal("0"),
                pending_days=Decimal("0"),
            )
        )
        db.commit()
    return engine, testing_session


def test_leave_validation_failure_releases_sqlite_write_lock(tmp_path):
    engine, testing_session = _file_leave_sessions(
        tmp_path / "validation-lock.db",
        cl_balance=0,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE transaction_probe "
                "(probe_id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
        )

    first = testing_session()
    second = testing_session()
    try:
        with pytest.raises(LeaveError, match="Insufficient CL balance"):
            apply_for_leave(
                first,
                employee_id="EMP-LOCK",
                leave_type_code="CL",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 8, 3),
                reason="Insufficient balance",
            )

        assert not first.in_transaction()
        with second.begin():
            second.execute(
                text("INSERT INTO transaction_probe (value) VALUES ('ok')")
            )
        assert not second.in_transaction()
    finally:
        first.close()
        second.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_leave_operation_rejects_active_transaction_without_rolling_it_back(
    tmp_path,
):
    engine, testing_session = _file_leave_sessions(
        tmp_path / "active-caller-transaction.db",
        cl_balance=8,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE caller_work "
                "(work_id INTEGER PRIMARY KEY, value TEXT NOT NULL)"
            )
        )

    caller_session = testing_session()
    observer_session = testing_session()
    try:
        caller_session.execute(
            text("INSERT INTO caller_work (value) VALUES ('keep')")
        )
        with pytest.raises(
            LeaveError,
            match="session with no active transaction",
        ):
            apply_for_leave(
                caller_session,
                employee_id="EMP-LOCK",
                leave_type_code="CL",
                start_date=date(2026, 8, 3),
                end_date=date(2026, 8, 3),
                reason="Caller has pending work",
            )

        assert caller_session.in_transaction()
        assert caller_session.execute(
            text("SELECT value FROM caller_work")
        ).scalar_one() == "keep"
        caller_session.commit()
        assert observer_session.execute(
            text("SELECT value FROM caller_work")
        ).scalar_one() == "keep"
        assert (
            observer_session.query(LeaveRequest)
            .filter_by(employee_id="EMP-LOCK")
            .count()
            == 0
        )
    finally:
        caller_session.close()
        observer_session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_leave_validation_and_listing(client):
    assert client.get("/leave/types").status_code == 200
    balances = client.get("/leave/balances/EMP-0002")
    assert balances.status_code == 200
    assert balances.json()[0]["cl_balance"] == 10
    assert client.get("/leave/balances/UNKNOWN").status_code == 404
    assert client.get("/leave/requests/UNKNOWN").status_code == 404

    assert client.post(
        "/leave/requests",
        json={
            "employee_id": "UNKNOWN",
            "leave_type_code": "CL",
            "start_date": "2026-08-04",
            "end_date": "2026-08-05",
            "reason": "Unknown employee",
        },
    ).status_code == 404
    assert client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "UNKNOWN",
            "start_date": "2026-08-04",
            "end_date": "2026-08-05",
            "reason": "Unknown leave type",
        },
    ).status_code == 404
    assert client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-05",
            "end_date": "2026-08-04",
            "reason": "Reversed dates",
        },
    ).status_code == 422
    assert client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "reason": "Weekend only",
        },
    ).status_code == 422

    created = client.post(
        "/leave/requests",
        json={
            "employee_id": "EMP-0002",
            "leave_type_code": "CL",
            "start_date": "2026-08-04",
            "end_date": "2026-08-04",
            "reason": "Personal",
        },
    )
    assert created.status_code == 201
    listed = client.get(
        "/leave/requests",
        params={"employee_id": "EMP-0002", "status": "Pending"},
    )
    assert listed.status_code == 200
    assert [item["leave_request_id"] for item in listed.json()] == [
        created.json()["leave_request_id"]
    ]


def test_openapi_contains_lf06_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/attendance/{employee_id}/monthly-summary" in paths
    assert "/attendance/{employee_id}" in paths
    assert "/leave/types" in paths
    assert "/leave/balances/{employee_id}" in paths
    assert "/leave/requests/{request_id}/approve" in paths
    assert "/leave/requests/{request_id}/reject" in paths
