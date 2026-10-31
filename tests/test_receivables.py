from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.invoice_service import (
    DraftInvoiceInput,
    InvoiceItemDraft,
    InvoicePaymentInput,
    cancel_invoice,
    create_draft_invoice,
    record_payment,
    send_invoice,
)
from app.ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    account_balance,
    create_journal_entry,
)
from app.models import ChartOfAccount, Client, Invoice, JournalEntry
from app.receivables_service import (
    ReceivablesError,
    build_receivables_report,
)


@pytest.fixture
def receivables_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'receivables.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    db.add_all(
        [
            ChartOfAccount(
                account_code="1000",
                account_name="Cash",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code=None,
                is_group="Y",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="1001",
                account_name="Operating bank",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code="1000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="1100",
                account_name="Accounts receivable",
                account_type="ASSET",
                normal_balance="DEBIT",
                parent_code="1000",
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="2200",
                account_name="GST output payable",
                account_type="LIABILITY",
                normal_balance="CREDIT",
                parent_code=None,
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            ChartOfAccount(
                account_code="3001",
                account_name="Opening balance equity",
                account_type="EQUITY",
                normal_balance="CREDIT",
                parent_code=None,
                is_group="N",
                statement="BALANCE_SHEET",
                is_active="Y",
            ),
            *[
                ChartOfAccount(
                    account_code=code,
                    account_name=f"Revenue {code}",
                    account_type="INCOME",
                    normal_balance="CREDIT",
                    parent_code=None,
                    is_group="N",
                    statement="PROFIT_AND_LOSS",
                    is_active="Y",
                )
                for code in ("4001", "4002", "4003", "4004")
            ],
        ]
    )
    db.add_all(
        [
            Client(
                client_id=f"CL-{index}",
                client_name=f"Client {index}",
                industry="Technology",
                city="Chennai",
                state_or_region="Tamil Nadu",
                country="IN",
                client_type="DOMESTIC",
                gst_registration=None,
                payment_terms_days=30,
                payment_behaviour="normal",
                primary_service_line="4001",
                contact_email=f"client{index}@example.com",
                onboarded_on=date(2020, 1, 1),
                is_active="Y",
            )
            for index in range(1, 4)
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _entry(entry_id, entry_date, source_type, source_id):
    return JournalEntryInput(
        entry_id=entry_id,
        entry_date=entry_date,
        posting_period=entry_date.strftime("%Y-%m"),
        financial_year="2025-26",
        description=source_type,
        source_type=source_type,
        source_id=source_id,
        created_by="test",
        created_at=datetime.combine(entry_date, datetime.min.time()),
    )


def _make_invoice(
    db,
    *,
    invoice_id,
    client_id,
    amount,
    due_date,
    status="SENT",
    carried="N",
    gst_rate=Decimal("0.0000"),
):
    draft = DraftInvoiceInput(
        invoice_id=invoice_id,
        invoice_number=f"INV/{invoice_id}",
        client_id=client_id,
        invoice_date=date(2025, 4, 1),
        due_date=due_date,
        gst_rate_percent=gst_rate,
        items=[
            InvoiceItemDraft(
                description="Services",
                quantity=Decimal("1.000"),
                unit_price=amount,
                revenue_account="4001",
            )
        ],
        created_by="test",
        created_at=datetime(2025, 4, 1),
    )
    if carried == "Y":
        invoice = Invoice(
            invoice_id=invoice_id,
            invoice_number=f"INV/{invoice_id}",
            client_id=client_id,
            invoice_date=date(2025, 2, 1),
            due_date=due_date,
            service_line_account="4001",
            currency="INR",
            subtotal=amount,
            gst_rate_percent=gst_rate,
            gst_amount=Decimal("0.00"),
            total_amount=amount,
            amount_paid=Decimal("0.00"),
            balance_due=amount,
            status=status,
            last_payment_date=None,
            po_number=None,
            carried_in_from_prior_period="Y",
            created_by="source",
            created_at=datetime(2025, 2, 1),
            ledger_entry_id=None,
        )
        db.add(invoice)
        db.commit()
        return invoice_id

    invoice = create_draft_invoice(db, draft)
    db.commit()
    if status != "DRAFT":
        send_invoice(
            db,
            invoice_id,
            business_date=date(2025, 4, 10),
            created_by="test",
        )
        db.commit()
    return invoice_id


def _post_opening_carried_receivable(db, invoice_id, amount):
    create_journal_entry(
        db,
        _entry(
            "JE-OPENING-CARRIED",
            date(2025, 4, 1),
            "OPENING",
            "OB-TEST",
        ),
        [
            JournalLineInput(
                line_id="JL-OPENING-AR",
                line_no=1,
                account_code="1100",
                debit=amount,
                credit=Decimal("0.00"),
                line_description=f"Carried invoice {invoice_id}",
            ),
            JournalLineInput(
                line_id="JL-OPENING-EQUITY",
                line_no=2,
                account_code="3001",
                debit=Decimal("0.00"),
                credit=amount,
            ),
        ],
    )


def test_receivables_report_reconciles_and_excludes_non_open_invoices(
    receivables_db,
):
    db = receivables_db
    # Client 1: ₹118 invoice with two payments totaling ₹25 leaves ₹93 open.
    client_one_invoice = _make_invoice(
        db,
        invoice_id="INV-CLIENT-1",
        client_id="CL-1",
        amount=Decimal("100.00"),
        due_date=date(2025, 5, 1),
        gst_rate=Decimal("18.0000"),
    )
    record_payment(
        db,
        client_one_invoice,
        InvoicePaymentInput(
            payment_date=date(2025, 4, 15),
            amount=Decimal("10.00"),
            payment_mode="NEFT",
            reference_no="UTR-1",
            received_by="test",
        ),
    )
    db.commit()
    record_payment(
        db,
        client_one_invoice,
        InvoicePaymentInput(
            payment_date=date(2025, 4, 20),
            amount=Decimal("15.00"),
            payment_mode="NEFT",
            reference_no="UTR-2",
            received_by="test",
        ),
    )
    db.commit()

    # Client 2: the carried invoice is represented by the opening AR line.
    carried_id = _make_invoice(
        db,
        invoice_id="INV-00007",
        client_id="CL-2",
        amount=Decimal("200.00"),
        due_date=date(2025, 3, 31),
        status="OVERDUE",
        carried="Y",
    )
    _post_opening_carried_receivable(db, carried_id, Decimal("200.00"))

    # Client 3: an unpaid overdue invoice.
    _make_invoice(
        db,
        invoice_id="INV-CLIENT-3",
        client_id="CL-3",
        amount=Decimal("50.00"),
        due_date=date(2025, 4, 9),
        status="OVERDUE",
    )

    # Draft INV-00740 is intentionally unposted and excluded.
    draft_id = _make_invoice(
        db,
        invoice_id="INV-00740",
        client_id="CL-1",
        amount=Decimal("80.00"),
        due_date=date(2025, 10, 29),
        status="DRAFT",
    )
    assert db.get(Invoice, draft_id).balance_due == Decimal("80.00")

    # A fully paid invoice and a reversed cancellation must not be reported.
    paid_id = _make_invoice(
        db,
        invoice_id="INV-PAID",
        client_id="CL-2",
        amount=Decimal("30.00"),
        due_date=date(2025, 5, 1),
    )
    record_payment(
        db,
        paid_id,
        InvoicePaymentInput(
            payment_date=date(2025, 4, 20),
            amount=Decimal("30.00"),
            payment_mode="NEFT",
            reference_no="UTR-PAID",
            received_by="test",
        ),
    )
    db.commit()

    cancelled_id = _make_invoice(
        db,
        invoice_id="INV-CANCELLED",
        client_id="CL-3",
        amount=Decimal("40.00"),
        due_date=date(2025, 5, 1),
    )
    cancel_invoice(
        db,
        cancelled_id,
        business_date=date(2025, 4, 30),
        created_by="test",
    )
    db.commit()

    report = build_receivables_report(db)
    by_client = {client.client_id: client for client in report.clients}
    assert report.total_outstanding == Decimal("343.00")
    assert set(by_client) == {"CL-1", "CL-2", "CL-3"}
    assert {
        client_id: data.total_outstanding
        for client_id, data in by_client.items()
    } == {
        "CL-1": Decimal("93.00"),
        "CL-2": Decimal("200.00"),
        "CL-3": Decimal("50.00"),
    }
    assert by_client["CL-1"].open_invoice_count == 1
    assert by_client["CL-2"].invoices[0].invoice_id == carried_id
    assert by_client["CL-2"].invoices[0].status == "OVERDUE"
    assert by_client["CL-3"].invoices[0].invoice_number == (
        "INV/INV-CLIENT-3"
    )
    listed_ids = {
        invoice.invoice_id
        for client in report.clients
        for invoice in client.invoices
    }
    assert "INV-00740" not in listed_ids
    assert paid_id not in listed_ids
    assert cancelled_id not in listed_ids

    # The report sums invoice-level balances only. The carried item is
    # represented by opening AR once, not added a second time from the ledger.
    assert account_balance(db, "1100", date(2026, 1, 1)) == (
        report.total_outstanding
    )


def test_receivables_report_filters_client_and_open_status(receivables_db):
    db = receivables_db
    _make_invoice(
        db,
        invoice_id="INV-SENT",
        client_id="CL-1",
        amount=Decimal("10.00"),
        due_date=date(2025, 5, 1),
        status="SENT",
    )
    _make_invoice(
        db,
        invoice_id="INV-OVERDUE",
        client_id="CL-2",
        amount=Decimal("20.00"),
        due_date=date(2025, 4, 1),
        status="OVERDUE",
    )

    report = build_receivables_report(db, client_id="CL-1", status="SENT")
    assert report.total_outstanding == Decimal("10.00")
    assert [client.client_id for client in report.clients] == ["CL-1"]
    assert report.clients[0].invoices[0].status == "SENT"

    overdue = build_receivables_report(db, status="OVERDUE")
    assert overdue.total_outstanding == Decimal("20.00")
    with pytest.raises(ReceivablesError, match="Receivables status"):
        build_receivables_report(db, status="PAID")
    with pytest.raises(ReceivablesError, match="does not exist"):
        build_receivables_report(db, client_id="NO-CLIENT")
