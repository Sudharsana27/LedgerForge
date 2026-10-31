from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.database import Base, get_db
from app.routers import clients, invoices, receivables
from app.models import ChartOfAccount, Client


@pytest.fixture
def api_client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'invoice-api.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add_all(
            [
                ChartOfAccount(
                    account_code=code,
                    account_name=f"Account {code}",
                    account_type=account_type,
                    normal_balance=normal_balance,
                    parent_code=None,
                    is_group="N",
                    statement=statement,
                    is_active="Y",
                )
                for code, account_type, normal_balance, statement in (
                    ("1001", "ASSET", "DEBIT", "BALANCE_SHEET"),
                    ("1100", "ASSET", "DEBIT", "BALANCE_SHEET"),
                    ("2200", "LIABILITY", "CREDIT", "BALANCE_SHEET"),
                    ("4001", "INCOME", "CREDIT", "PROFIT_AND_LOSS"),
                    ("4002", "INCOME", "CREDIT", "PROFIT_AND_LOSS"),
                    ("4003", "INCOME", "CREDIT", "PROFIT_AND_LOSS"),
                    ("4004", "INCOME", "CREDIT", "PROFIT_AND_LOSS"),
                )
            ]
        )
        db.add(
            Client(
                client_id="CL-API",
                client_name="API Client",
                industry="Technology",
                city="Chennai",
                state_or_region="Tamil Nadu",
                country="IN",
                client_type="DOMESTIC",
                gst_registration=None,
                payment_terms_days=30,
                payment_behaviour="normal",
                primary_service_line="4001",
                contact_email="api@example.com",
                onboarded_on=date(2020, 1, 1),
                is_active="Y",
            )
        )
        db.commit()

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(clients.router)
    app.include_router(invoices.router)
    app.include_router(receivables.router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_authenticated_principal] = lambda: (
        AuthenticatedPrincipal(employee_id="EMP-API", role="HR")
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        engine.dispose()


def _invoice_payload(**values):
    payload = {
        "invoice_number": "INV/2025-26/API-1",
        "client_id": "CL-API",
        "invoice_date": "2025-04-01",
        "due_date": "2025-05-01",
        "gst_rate_percent": "18.0000",
        "items": [
            {
                "description": "Consulting",
                "quantity": "1.000",
                "unit_price": "100.00",
                "revenue_account": "4001",
            }
        ],
    }
    payload.update(values)
    return payload


def _client_payload(**values):
    payload = {
        "client_id": "CL-NEW",
        "client_name": "New Client",
        "industry": "Technology",
        "city": "Chennai",
        "state_or_region": "Tamil Nadu",
        "country": "IN",
        "client_type": "DOMESTIC",
        "gst_registration": None,
        "payment_terms_days": 30,
        "payment_behaviour": "normal",
        "primary_service_line": "4001",
        "contact_email": "client@example.com",
        "onboarded_on": "2025-01-15",
        "is_active": "Y",
    }
    payload.update(values)
    return payload


def test_client_api_create_get_list_paginate_update_and_delete(api_client):
    created = api_client.post("/clients", json=_client_payload())
    assert created.status_code == 201
    assert created.json()["client_id"] == "CL-NEW"
    assert created.json()["contact_email"] == "client@example.com"

    fetched = api_client.get("/clients/CL-NEW")
    assert fetched.status_code == 200
    assert fetched.json()["client_name"] == "New Client"

    second = api_client.post(
        "/clients",
        json=_client_payload(
            client_id="CL-Z",
            client_name="Second Client",
        ),
    )
    assert second.status_code == 201
    all_clients = api_client.get("/clients")
    page = api_client.get("/clients?skip=1&limit=1")
    assert all_clients.status_code == 200
    assert page.status_code == 200
    assert page.json() == all_clients.json()[1:2]
    assert api_client.get("/clients?skip=-1").status_code == 422
    assert api_client.get("/clients?limit=501").status_code == 422

    updated = api_client.patch(
        "/clients/CL-NEW",
        json={"client_name": "Updated Client", "payment_terms_days": 45},
    )
    assert updated.status_code == 200
    assert updated.json()["client_name"] == "Updated Client"
    assert updated.json()["payment_terms_days"] == 45

    deleted = api_client.delete("/clients/CL-NEW")
    assert deleted.status_code == 204
    assert api_client.get("/clients/CL-NEW").status_code == 404


def test_client_api_rejects_invalid_input_and_duplicate_records(api_client):
    assert api_client.post(
        "/clients",
        json=_client_payload(contact_email="not-an-email"),
    ).status_code == 422
    assert api_client.post(
        "/clients",
        json=_client_payload(client_name="   "),
    ).status_code == 422
    assert api_client.post(
        "/clients",
        json=_client_payload(payment_terms_days=-1),
    ).status_code == 422
    assert api_client.post(
        "/clients",
        json=_client_payload(primary_service_line="9999"),
    ).status_code == 422
    assert api_client.post(
        "/clients",
        json=_client_payload(unexpected="field"),
    ).status_code == 422

    assert api_client.post("/clients", json=_client_payload()).status_code == 201
    duplicate = api_client.post("/clients", json=_client_payload())
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Client ID already exists"

    assert api_client.patch("/clients/CL-NEW", json={}).status_code == 422
    assert api_client.patch(
        "/clients/CL-NEW",
        json={"client_name": None},
    ).status_code == 422
    assert api_client.get("/clients/UNKNOWN").status_code == 404
    assert api_client.patch(
        "/clients/UNKNOWN",
        json={"client_name": "Unknown"},
    ).status_code == 404
    assert api_client.delete("/clients/UNKNOWN").status_code == 404


def test_client_api_requires_hr_or_admin_authorization(api_client):
    api_client.app.dependency_overrides[get_authenticated_principal] = (
        lambda: AuthenticatedPrincipal(employee_id="EMP-API", role="EMPLOYEE")
    )
    assert api_client.get("/clients").status_code == 403
    assert api_client.get("/clients/CL-API").status_code == 403
    assert api_client.post("/clients", json=_client_payload()).status_code == 403

    api_client.app.dependency_overrides[get_authenticated_principal] = (
        lambda: AuthenticatedPrincipal(employee_id="EMP-API", role="ADMIN")
    )
    assert api_client.get("/clients/CL-API").status_code == 200

    api_client.app.dependency_overrides.pop(get_authenticated_principal)
    response = api_client.get("/clients")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_client_api_rejects_delete_when_invoices_reference_client(api_client):
    created = api_client.post("/invoices", json=_invoice_payload())
    assert created.status_code == 201

    response = api_client.delete("/clients/CL-API")
    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Client cannot be deleted while invoices reference it"
    )
    assert api_client.get("/clients/CL-API").status_code == 200


def test_invoice_api_create_get_filter_send_and_payment(api_client):
    created = api_client.post("/invoices", json=_invoice_payload())
    assert created.status_code == 201
    invoice = created.json()
    invoice_id = invoice["invoice_id"]
    assert invoice_id.startswith("INV-")
    assert invoice["invoice_number"] == "INV/2025-26/API-1"
    assert invoice["status"] == "DRAFT"
    assert invoice["ledger_entry_id"] is None
    assert invoice["created_by"] == "EMP-API"
    assert invoice["total_amount"] == "118.00"

    fetched = api_client.get(f"/invoices/{invoice_id}")
    assert fetched.status_code == 200
    assert fetched.json()["items"][0]["revenue_account"] == "4001"
    assert api_client.get("/invoices?client_id=CL-API&status=DRAFT").json()
    assert api_client.get("/invoices?status=INVALID").status_code == 422

    sent = api_client.post(
        f"/invoices/{invoice_id}/send",
        json={"business_date": "2025-04-10"},
    )
    assert sent.status_code == 200
    assert sent.json()["invoice"]["status"] == "SENT"
    entry_id = sent.json()["journal_entry_id"]

    repeated = api_client.post(
        f"/invoices/{invoice_id}/send",
        json={"business_date": "2025-04-11"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["journal_entry_id"] == entry_id

    payment = api_client.post(
        f"/invoices/{invoice_id}/payments",
        json={
            "payment_date": "2025-04-20",
            "amount": "25.00",
            "payment_mode": "NEFT",
            "reference_no": "UTR-API-1",
        },
    )
    assert payment.status_code == 201
    assert payment.json()["amount"] == "25.00"
    updated = api_client.get(f"/invoices/{invoice_id}").json()
    assert updated["amount_paid"] == "25.00"
    assert updated["balance_due"] == "93.00"
    assert updated["status"] == "PARTIALLY_PAID"
    receivables_report = api_client.get("/receivables")
    assert receivables_report.status_code == 200
    assert receivables_report.json()["total_outstanding"] == "93.00"
    assert receivables_report.json()["clients"][0]["invoices"][0][
        "invoice_number"
    ] == "INV/2025-26/API-1"


def test_invoice_api_validation_missing_records_and_rejected_operations(
    api_client,
):
    assert api_client.post(
        "/invoices", json=_invoice_payload(due_date="2025-03-01")
    ).status_code == 422
    assert api_client.post(
        "/invoices", json=_invoice_payload(client_id="NO-CLIENT")
    ).status_code == 404
    assert api_client.get("/invoices/UNKNOWN").status_code == 404
    assert api_client.post(
        "/invoices/UNKNOWN/send",
        json={"business_date": "2025-04-10"},
    ).status_code == 404

    created = api_client.post("/invoices", json=_invoice_payload())
    invoice_id = created.json()["invoice_id"]
    draft_payment = api_client.post(
        f"/invoices/{invoice_id}/payments",
        json={
            "payment_date": "2025-04-10",
            "amount": "1.00",
            "payment_mode": "NEFT",
            "reference_no": "UTR-DRAFT",
        },
    )
    assert draft_payment.status_code == 422

    sent = api_client.post(
        f"/invoices/{invoice_id}/send",
        json={"business_date": "2025-04-10"},
    )
    assert sent.status_code == 200
    rejected = api_client.post(
        f"/invoices/{invoice_id}/payments",
        json={
            "payment_date": "2025-04-10",
            "amount": "118.01",
            "payment_mode": "NEFT",
            "reference_no": "UTR-OVERPAY",
        },
    )
    assert rejected.status_code == 422


def test_invoice_api_duplicate_number_returns_sanitized_conflict(api_client):
    first = api_client.post("/invoices", json=_invoice_payload())
    assert first.status_code == 201

    duplicate = api_client.post("/invoices", json=_invoice_payload())
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == (
        "Invoice data conflicts with an existing record."
    )


def test_invoice_api_rejects_duplicate_payment_reference(api_client):
    created = api_client.post("/invoices", json=_invoice_payload())
    invoice_id = created.json()["invoice_id"]
    api_client.post(
        f"/invoices/{invoice_id}/send",
        json={"business_date": "2025-04-10"},
    )
    payload = {
        "payment_date": "2025-04-20",
        "amount": "25.00",
        "payment_mode": "NEFT",
        "reference_no": "UTR-DUPLICATE",
    }
    first = api_client.post(
        f"/invoices/{invoice_id}/payments",
        json=payload,
    )
    duplicate = api_client.post(
        f"/invoices/{invoice_id}/payments",
        json=payload,
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == (
        "Invoice data conflicts with an existing record."
    )


def test_invoice_api_cancel_and_refresh_status(api_client):
    draft = api_client.post(
        "/invoices",
        json=_invoice_payload(invoice_number="INV/2025-26/CANCEL"),
    ).json()
    cancelled = api_client.post(
        f"/invoices/{draft['invoice_id']}/cancel",
        json={"business_date": "2025-04-10"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["invoice"]["status"] == "CANCELLED"
    assert cancelled.json()["journal_entry_id"] is None

    payload = _invoice_payload(
        invoice_number="INV/2025-26/OVERDUE",
        due_date="2025-04-10",
    )
    invoice_id = api_client.post("/invoices", json=payload).json()["invoice_id"]
    sent = api_client.post(
        f"/invoices/{invoice_id}/send",
        json={"business_date": "2025-04-10"},
    )
    assert sent.json()["invoice"]["status"] == "SENT"

    refreshed = api_client.post(
        f"/invoices/{invoice_id}/refresh-status",
        json={"business_date": "2025-04-11"},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "OVERDUE"

    reversed_invoice = api_client.post(
        f"/invoices/{invoice_id}/cancel",
        json={"business_date": "2025-04-12"},
    )
    assert reversed_invoice.status_code == 200
    assert reversed_invoice.json()["invoice"]["status"] == "CANCELLED"
    assert reversed_invoice.json()["journal_entry_id"]


def test_invoice_and_receivables_routes_fail_closed_without_principal():
    app = FastAPI()
    app.include_router(invoices.router)
    app.include_router(receivables.router)
    with TestClient(app) as client:
        assert client.get("/invoices").status_code == 401
        assert client.get("/receivables").status_code == 401


def test_api_serializes_decimal_money_without_float_conversion(api_client):
    created = api_client.post(
        "/invoices",
        json=_invoice_payload(
            invoice_number="INV/2025-26/DECIMAL",
            items=[
                {
                    "description": "Fractional",
                    "quantity": "1.250",
                    "unit_price": "10.02",
                    "revenue_account": "4001",
                }
            ],
        ),
    )

    assert created.status_code == 201
    assert created.json()["subtotal"] == "12.53"
    assert created.json()["gst_amount"] == "2.26"
    assert created.json()["total_amount"] == "14.79"
