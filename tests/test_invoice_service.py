from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select, func
from sqlalchemy.orm import sessionmaker

from app import invoice_service
from app.database import Base
from app.invoice_service import (
    DraftInvoiceInput,
    InvoiceItemDraft,
    InvoicePaymentInput,
    InvoiceServiceError,
    cancel_invoice,
    create_draft_invoice,
    record_payment,
    refresh_invoice_status,
    send_invoice,
)
from app.ledger_service import LedgerError
from app.models import (
    ChartOfAccount,
    Client,
    Invoice,
    InvoicePayment,
    JournalEntry,
    JournalLine,
)


@pytest.fixture
def invoice_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'invoice-service.db'}")

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
                account_name="Bank",
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
    db.add(
        Client(
            client_id="CL-TEST",
            client_name="Test Client",
            industry="Technology",
            city="Chennai",
            state_or_region="Tamil Nadu",
            country="IN",
            client_type="DOMESTIC",
            gst_registration=None,
            payment_terms_days=30,
            payment_behaviour="normal",
            primary_service_line="4001",
            contact_email="client@example.com",
            onboarded_on=date(2020, 1, 1),
            is_active="Y",
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _draft(
    *,
    invoice_id="INV-SERVICE",
    invoice_number="INV/2025-26/SERVICE",
    due_date=date(2025, 5, 1),
    gst_rate=Decimal("18.0000"),
    items=None,
):
    if items is None:
        items = [
            InvoiceItemDraft(
                description="Consulting",
                quantity=Decimal("1.000"),
                unit_price=Decimal("100.00"),
                revenue_account="4001",
            )
        ]
    return DraftInvoiceInput(
        invoice_id=invoice_id,
        invoice_number=invoice_number,
        client_id="CL-TEST",
        invoice_date=date(2025, 4, 1),
        due_date=due_date,
        gst_rate_percent=gst_rate,
        items=items,
        created_by="tester",
        created_at=datetime(2025, 4, 1, 9),
    )


def _payment(amount, *, payment_date=date(2025, 4, 20), reference="UTR-TEST"):
    return InvoicePaymentInput(
        payment_date=payment_date,
        amount=amount,
        payment_mode="NEFT",
        reference_no=reference,
        received_by="tester",
    )


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def _create_and_send(db, **draft_args):
    draft = create_draft_invoice(db, _draft(**draft_args))
    db.commit()
    entry = send_invoice(
        db,
        draft.invoice_id,
        business_date=date(2025, 4, 10),
        created_by="tester",
    )
    return draft.invoice_id, entry


def test_creating_draft_creates_no_journal_entry(invoice_db):
    invoice = create_draft_invoice(invoice_db, _draft())

    assert invoice.status == "DRAFT"
    assert invoice.subtotal == Decimal("100.00")
    assert invoice.gst_amount == Decimal("18.00")
    assert invoice.total_amount == Decimal("118.00")
    assert invoice.balance_due == Decimal("118.00")
    assert invoice.ledger_entry_id is None
    assert len(invoice.items) == 1
    assert _count(invoice_db, JournalEntry) == 0


def test_draft_calculation_rounds_each_line_and_gst_half_up(invoice_db):
    invoice = create_draft_invoice(
        invoice_db,
        _draft(
            items=[
                InvoiceItemDraft(
                    description="Fractional line",
                    quantity=Decimal("1.250"),
                    unit_price=Decimal("10.02"),
                    revenue_account="4001",
                ),
                InvoiceItemDraft(
                    description="Second service",
                    quantity=Decimal("2.000"),
                    unit_price=Decimal("5.00"),
                    revenue_account="4002",
                ),
            ]
        ),
    )

    assert [item.amount for item in invoice.items] == [
        Decimal("12.53"),
        Decimal("10.00"),
    ]
    assert invoice.subtotal == Decimal("22.53")
    assert invoice.gst_amount == Decimal("4.06")
    assert invoice.total_amount == Decimal("26.59")


def test_send_posts_balanced_entry_and_credits_item_revenue_and_gst(invoice_db):
    invoice_id, entry = _create_and_send(
        invoice_db,
        items=[
            InvoiceItemDraft(
                description="Software",
                quantity=Decimal("1.000"),
                unit_price=Decimal("100.00"),
                revenue_account="4001",
            ),
            InvoiceItemDraft(
                description="Support",
                quantity=Decimal("2.000"),
                unit_price=Decimal("25.00"),
                revenue_account="4002",
            ),
        ],
    )
    lines = invoice_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == entry.entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    line_amounts = {
        line.account_code: (line.debit, line.credit) for line in lines
    }

    assert entry.status == "POSTED"
    assert entry.total_debit == entry.total_credit == Decimal("177.00")
    assert line_amounts == {
        "1100": (Decimal("177.00"), Decimal("0.00")),
        "4001": (Decimal("0.00"), Decimal("100.00")),
        "4002": (Decimal("0.00"), Decimal("50.00")),
        "2200": (Decimal("0.00"), Decimal("27.00")),
    }
    invoice_db.commit()
    stored = invoice_db.get(Invoice, invoice_id)
    assert stored.status == "SENT"
    assert stored.ledger_entry_id == entry.entry_id


def test_zero_gst_invoice_does_not_post_a_zero_gst_line(invoice_db):
    invoice_id, entry = _create_and_send(
        invoice_db,
        invoice_id="INV-ZERO-GST",
        invoice_number="INV/2025-26/ZERO-GST",
        gst_rate=Decimal("0.0000"),
    )
    lines = invoice_db.scalars(
        select(JournalLine).where(JournalLine.entry_id == entry.entry_id)
    ).all()

    assert entry.total_debit == entry.total_credit == Decimal("100.00")
    assert {line.account_code for line in lines} == {"1100", "4001"}
    invoice_db.commit()
    assert invoice_db.get(Invoice, invoice_id).gst_amount == Decimal("0.00")


def test_repeated_send_returns_existing_posting(invoice_db):
    invoice_id, first_entry = _create_and_send(invoice_db)
    second_entry = send_invoice(
        invoice_db,
        invoice_id,
        business_date=date(2025, 4, 11),
        created_by="tester",
    )

    assert second_entry.entry_id == first_entry.entry_id
    assert _count(invoice_db, JournalEntry) == 1


def test_payment_reduces_balance_and_multiple_payments_are_supported(invoice_db):
    invoice_id, _ = _create_and_send(invoice_db)
    first = record_payment(
        invoice_db, invoice_id, _payment(Decimal("25.00"), reference="UTR-1")
    )
    payment_entry_id = first.ledger_entry_id
    invoice_db.commit()
    invoice = invoice_db.get(Invoice, invoice_id)
    assert invoice.amount_paid == Decimal("25.00")
    assert invoice.balance_due == Decimal("93.00")
    assert invoice.status == "PARTIALLY_PAID"
    assert first.amount == Decimal("25.00")
    payment_lines = invoice_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == payment_entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    assert [
        (line.account_code, line.debit, line.credit)
        for line in payment_lines
    ] == [
        ("1001", Decimal("25.00"), Decimal("0.00")),
        ("1100", Decimal("0.00"), Decimal("25.00")),
    ]
    invoice_db.commit()

    second = record_payment(
        invoice_db, invoice_id, _payment(Decimal("50.00"), reference="UTR-2")
    )
    invoice_db.commit()
    invoice = invoice_db.get(Invoice, invoice_id)
    assert invoice.amount_paid == Decimal("75.00")
    assert invoice.balance_due == Decimal("43.00")
    assert invoice.status == "PARTIALLY_PAID"
    assert second.amount == Decimal("50.00")
    assert _count(invoice_db, InvoicePayment) == 2


@pytest.mark.parametrize("amount", [Decimal("0.00"), Decimal("-1.00")])
def test_zero_and_negative_payments_are_rejected(invoice_db, amount):
    invoice_id, _ = _create_and_send(invoice_db)

    with pytest.raises(InvoiceServiceError, match="greater than zero"):
        record_payment(invoice_db, invoice_id, _payment(amount))

    assert _count(invoice_db, InvoicePayment) == 0
    assert _count(invoice_db, JournalEntry) == 1


def test_overpayment_is_rejected(invoice_db):
    invoice_id, _ = _create_and_send(invoice_db)

    with pytest.raises(InvoiceServiceError, match="exceeds the outstanding"):
        record_payment(invoice_db, invoice_id, _payment(Decimal("118.01")))

    assert _count(invoice_db, InvoicePayment) == 0
    assert _count(invoice_db, JournalEntry) == 1


def test_duplicate_payment_reference_is_rejected_without_second_posting(
    invoice_db,
):
    invoice_id, _ = _create_and_send(invoice_db)
    record_payment(
        invoice_db,
        invoice_id,
        _payment(Decimal("25.00"), reference="UTR-DUPLICATE"),
    )
    invoice_db.commit()

    with pytest.raises(InvoiceServiceError, match="reference already exists"):
        record_payment(
            invoice_db,
            invoice_id,
            _payment(Decimal("25.00"), reference="UTR-DUPLICATE"),
        )

    assert _count(invoice_db, InvoicePayment) == 1
    assert _count(invoice_db, JournalEntry) == 2
    assert invoice_db.get(Invoice, invoice_id).balance_due == Decimal("93.00")


@pytest.mark.parametrize("status", ["DRAFT", "CANCELLED"])
def test_payments_against_draft_or_cancelled_invoice_are_rejected(
    invoice_db, status
):
    invoice = create_draft_invoice(
        invoice_db,
        _draft(
            invoice_id=f"INV-{status}",
            invoice_number=f"INV/2025-26/{status}",
        ),
    )
    if status == "CANCELLED":
        invoice.status = "CANCELLED"
        invoice.balance_due = Decimal("0.00")
        invoice_db.commit()

    with pytest.raises(InvoiceServiceError, match="Payments are not allowed"):
        record_payment(
            invoice_db, invoice.invoice_id, _payment(Decimal("1.00"))
        )

    assert _count(invoice_db, InvoicePayment) == 0
    assert _count(invoice_db, JournalEntry) == 0


def test_full_payment_changes_status_to_paid(invoice_db):
    invoice_id, _ = _create_and_send(invoice_db)
    record_payment(
        invoice_db, invoice_id, _payment(Decimal("118.00"))
    )
    invoice_db.commit()

    invoice = invoice_db.get(Invoice, invoice_id)
    assert invoice.amount_paid == Decimal("118.00")
    assert invoice.balance_due == Decimal("0.00")
    assert invoice.status == "PAID"
    assert _count(invoice_db, JournalEntry) == 2


def test_overdue_refresh_uses_explicit_date_without_extra_posting(invoice_db):
    invoice_id, original_entry = _create_and_send(
        invoice_db, due_date=date(2025, 4, 10)
    )
    invoice_db.commit()
    refreshed = refresh_invoice_status(
        invoice_db,
        invoice_id,
        business_date=date(2025, 4, 11),
    )

    assert refreshed.status == "OVERDUE"
    assert refreshed.ledger_entry_id == original_entry.entry_id
    assert _count(invoice_db, JournalEntry) == 1


def test_draft_cancellation_creates_no_journal_entry(invoice_db):
    invoice = create_draft_invoice(invoice_db, _draft())
    invoice_db.commit()

    result = cancel_invoice(
        invoice_db,
        invoice.invoice_id,
        business_date=date(2025, 4, 12),
        created_by="tester",
    )

    assert result is None
    stored = invoice_db.get(Invoice, invoice.invoice_id)
    assert stored.status == "CANCELLED"
    assert stored.balance_due == Decimal("0.00")
    assert _count(invoice_db, JournalEntry) == 0


def test_unpaid_posted_cancellation_creates_exact_reversal(invoice_db):
    invoice_id, original_entry = _create_and_send(invoice_db)
    original_lines = invoice_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == original_entry.entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    original_values = [
        (line.account_code, line.debit, line.credit, line.line_no)
        for line in original_lines
    ]
    invoice_db.commit()

    reversal = cancel_invoice(
        invoice_db,
        invoice_id,
        business_date=date(2025, 4, 12),
        created_by="tester",
    )
    reversal_lines = invoice_db.scalars(
        select(JournalLine)
        .where(JournalLine.entry_id == reversal.entry_id)
        .order_by(JournalLine.line_no)
    ).all()

    assert reversal.status == "POSTED"
    assert reversal.reversal_of_source_id == invoice_id
    assert [
        (line.account_code, line.credit, line.debit, line.line_no)
        for line in reversal_lines
    ] == original_values
    original = invoice_db.get(JournalEntry, original_entry.entry_id)
    assert original.status == "POSTED"
    assert [
        (line.account_code, line.debit, line.credit, line.line_no)
        for line in original.lines
    ] == original_values
    invoice_db.commit()
    stored = invoice_db.get(Invoice, invoice_id)
    assert stored.status == "CANCELLED"
    assert stored.balance_due == Decimal("0.00")
    assert stored.ledger_entry_id == original_entry.entry_id
    assert _count(invoice_db, JournalEntry) == 2
    invoice_db.commit()

    repeated_reversal = cancel_invoice(
        invoice_db,
        invoice_id,
        business_date=date(2025, 4, 13),
        created_by="tester",
    )
    assert repeated_reversal.entry_id == reversal.entry_id
    assert _count(invoice_db, JournalEntry) == 2


@pytest.mark.parametrize("payment_amount", [Decimal("1.00"), Decimal("118.00")])
def test_partially_paid_or_paid_invoice_cancellation_is_rejected(
    invoice_db, payment_amount
):
    invoice_id, _ = _create_and_send(invoice_db)
    record_payment(invoice_db, invoice_id, _payment(payment_amount))
    invoice_db.commit()

    with pytest.raises(InvoiceServiceError, match="cannot be cancelled"):
        cancel_invoice(
            invoice_db,
            invoice_id,
            business_date=date(2025, 4, 12),
            created_by="tester",
        )

    assert _count(invoice_db, JournalEntry) == 2
    assert invoice_db.get(Invoice, invoice_id).status in {
        "PARTIALLY_PAID",
        "PAID",
    }


def test_ledger_failure_rolls_back_invoice_and_payment_changes(
    invoice_db, monkeypatch
):
    invoice_id, _ = _create_and_send(invoice_db)
    invoice_db.commit()
    original_amount_paid = invoice_db.get(Invoice, invoice_id).amount_paid
    original_journal_count = _count(invoice_db, JournalEntry)
    invoice_db.commit()
    real_post = invoice_service.create_journal_entry_in_transaction

    def post_then_fail(*args, **kwargs):
        real_post(*args, **kwargs)
        raise LedgerError("simulated failure after journal flush")

    monkeypatch.setattr(
        invoice_service, "create_journal_entry_in_transaction", post_then_fail
    )
    with pytest.raises(LedgerError, match="simulated failure"):
        record_payment(
            invoice_db, invoice_id, _payment(Decimal("10.00"))
        )

    invoice_db.rollback()
    assert _count(invoice_db, JournalEntry) == original_journal_count
    assert _count(invoice_db, InvoicePayment) == 0
    invoice = invoice_db.get(Invoice, invoice_id)
    assert invoice.amount_paid == original_amount_paid
    assert invoice.balance_due == Decimal("118.00")


def test_payment_persistence_failure_rolls_back_journal_posting(
    invoice_db,
):
    invoice_id, _ = _create_and_send(invoice_db)
    invoice_db.commit()
    original_journal_count = _count(invoice_db, JournalEntry)
    invoice_db.commit()

    def fail_payment_insert(_mapper, _connection, _target):
        raise RuntimeError("simulated payment persistence failure")

    event.listen(InvoicePayment, "before_insert", fail_payment_insert)
    try:
        with pytest.raises(
            RuntimeError, match="simulated payment persistence failure"
        ):
            record_payment(
                invoice_db, invoice_id, _payment(Decimal("10.00"))
            )
    finally:
        event.remove(InvoicePayment, "before_insert", fail_payment_insert)

    invoice_db.rollback()
    assert _count(invoice_db, JournalEntry) == original_journal_count
    assert _count(invoice_db, InvoicePayment) == 0
    invoice = invoice_db.get(Invoice, invoice_id)
    assert invoice.amount_paid == Decimal("0.00")
    assert invoice.balance_due == Decimal("118.00")


def test_invoice_update_failure_rolls_back_invoice_journal_posting(
    invoice_db,
):
    invoice = create_draft_invoice(invoice_db, _draft())
    invoice_db.commit()

    def fail_invoice_update(_mapper, _connection, _target):
        raise RuntimeError("simulated invoice persistence failure")

    event.listen(Invoice, "before_update", fail_invoice_update)
    try:
        with pytest.raises(
            RuntimeError, match="simulated invoice persistence failure"
        ):
            send_invoice(
                invoice_db,
                invoice.invoice_id,
                business_date=date(2025, 4, 10),
                created_by="tester",
            )
    finally:
        event.remove(Invoice, "before_update", fail_invoice_update)

    invoice_db.rollback()
    assert _count(invoice_db, JournalEntry) == 0
    stored = invoice_db.get(Invoice, invoice.invoice_id)
    assert stored.status == "DRAFT"
    assert stored.ledger_entry_id is None


def test_invoice_ledger_posting_failure_rolls_back_new_entry(
    invoice_db, monkeypatch
):
    invoice = create_draft_invoice(invoice_db, _draft())
    invoice_db.commit()
    real_post = invoice_service.create_journal_entry_in_transaction

    def post_then_fail(*args, **kwargs):
        real_post(*args, **kwargs)
        raise LedgerError("simulated failure after invoice journal flush")

    monkeypatch.setattr(
        invoice_service, "create_journal_entry_in_transaction", post_then_fail
    )
    with pytest.raises(LedgerError, match="simulated failure"):
        send_invoice(
            invoice_db,
            invoice.invoice_id,
            business_date=date(2025, 4, 10),
            created_by="tester",
        )

    assert _count(invoice_db, JournalEntry) == 0
    invoice_db.commit()
    stored = invoice_db.get(Invoice, invoice.invoice_id)
    assert stored.status == "DRAFT"
    assert stored.ledger_entry_id is None


def test_carried_in_invoice_is_not_reposted_but_can_receive_payment(
    invoice_db,
):
    carried = Invoice(
        invoice_id="INV-CARRIED",
        invoice_number="INV/2024-25/CARRIED",
        client_id="CL-TEST",
        invoice_date=date(2025, 2, 1),
        due_date=date(2025, 3, 1),
        service_line_account="4001",
        currency="INR",
        subtotal=Decimal("100.00"),
        gst_rate_percent=Decimal("0.0000"),
        gst_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("100.00"),
        status="OVERDUE",
        last_payment_date=None,
        po_number=None,
        carried_in_from_prior_period="Y",
        created_by="source",
        created_at=datetime(2025, 2, 1),
        ledger_entry_id=None,
    )
    invoice_db.add(carried)
    invoice_db.commit()
    carried_invoice_id = carried.invoice_id

    with pytest.raises(InvoiceServiceError, match="cannot be sent"):
        send_invoice(
            invoice_db,
            carried_invoice_id,
            business_date=date(2025, 4, 1),
            created_by="tester",
        )
    assert not invoice_db.in_transaction()

    payment = record_payment(
        invoice_db,
        carried_invoice_id,
        _payment(
            Decimal("10.00"),
            payment_date=date(2025, 4, 1),
            reference="UTR-CARRIED",
        ),
    )
    assert payment.amount == Decimal("10.00")
    invoice_db.commit()
    assert invoice_db.get(Invoice, carried_invoice_id).balance_due == (
        Decimal("90.00")
    )
    assert _count(invoice_db, JournalEntry) == 1


def test_service_rejects_non_decimal_money(invoice_db):
    invoice_id, _ = _create_and_send(invoice_db)

    with pytest.raises(InvoiceServiceError, match="must be a Decimal"):
        record_payment(
            invoice_db,
            invoice_id,
            _payment(10.0),
        )
