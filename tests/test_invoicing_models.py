import importlib.util
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import (
    CheckConstraint,
    Numeric,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import (
    ChartOfAccount,
    Client,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    JournalEntry,
)
from scripts import seed


REVISION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b710c4a2d9e1_add_clients_and_invoices.py"
)
PAYMENT_REFERENCE_REVISION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "e7c2d10f4b39_prevent_duplicate_invoice_payments.py"
)


@pytest.fixture
def invoicing_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'invoicing-models.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                ChartOfAccount(
                    account_code="4001",
                    account_name="Service revenue",
                    account_type="INCOME",
                    normal_balance="CREDIT",
                    parent_code=None,
                    is_group="N",
                    statement="PROFIT_AND_LOSS",
                    is_active="Y",
                ),
                JournalEntry(
                    entry_id="JE-INVOICE",
                    entry_date=date(2025, 4, 1),
                    posting_period="2025-04",
                    financial_year="2025-26",
                    description="Invoice posting reference",
                    source_type="INVOICE",
                    source_id="INV-MODEL",
                    status="POSTED",
                    total_debit=Decimal("0.00"),
                    total_credit=Decimal("0.00"),
                    created_by="tester",
                    created_at=datetime(2025, 4, 1, 9),
                ),
                JournalEntry(
                    entry_id="JE-PAYMENT",
                    entry_date=date(2025, 4, 2),
                    posting_period="2025-04",
                    financial_year="2025-26",
                    description="Payment posting reference",
                    source_type="INVOICE_PAYMENT",
                    source_id="PAY-MODEL",
                    status="POSTED",
                    total_debit=Decimal("0.00"),
                    total_credit=Decimal("0.00"),
                    created_by="tester",
                    created_at=datetime(2025, 4, 2, 9),
                ),
            ]
        )
        db.add(
            Client(
                client_id="CL-MODEL",
                client_name="Model Client",
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
        yield db
    engine.dispose()


def _invoice(
    *,
    invoice_id="INV-MODEL",
    invoice_number="INV/2025-26/MODEL",
    client_id="CL-MODEL",
    service_line_account="4001",
    status="SENT",
    ledger_entry_id=None,
    subtotal=Decimal("12.34"),
    gst_amount=Decimal("2.22"),
    total_amount=Decimal("14.56"),
    amount_paid=Decimal("0.00"),
    balance_due=Decimal("14.56"),
):
    return Invoice(
        invoice_id=invoice_id,
        invoice_number=invoice_number,
        client_id=client_id,
        invoice_date=date(2025, 4, 1),
        due_date=date(2025, 5, 1),
        service_line_account=service_line_account,
        currency="INR",
        subtotal=subtotal,
        gst_rate_percent=Decimal("18.0000"),
        gst_amount=gst_amount,
        total_amount=total_amount,
        amount_paid=amount_paid,
        balance_due=balance_due,
        status=status,
        last_payment_date=None,
        po_number=None,
        carried_in_from_prior_period="N",
        created_by="tester",
        created_at=datetime(2025, 4, 1, 9),
        ledger_entry_id=ledger_entry_id,
    )


def test_invoice_models_preserve_decimal_precision_and_relationships(
    invoicing_db,
):
    invoice = _invoice(ledger_entry_id="JE-INVOICE")
    invoice.items.append(
        InvoiceItem(
            invoice_item_id="II-MODEL",
            line_no=1,
            description="Consulting",
            quantity=Decimal("1.250"),
            unit_price=Decimal("9.87"),
            amount=Decimal("12.34"),
            revenue_account="4001",
        )
    )
    invoice.payments.append(
        InvoicePayment(
            payment_id="PAY-MODEL",
            payment_date=date(2025, 4, 2),
            amount=Decimal("2.34"),
            payment_mode="NEFT",
            reference_no="UTR-MODEL",
            received_by="U-TEST",
            ledger_entry_id="JE-PAYMENT",
        )
    )
    invoicing_db.add(invoice)
    invoicing_db.commit()
    invoicing_db.expire_all()

    stored = invoicing_db.scalar(
        select(Invoice).where(Invoice.invoice_id == "INV-MODEL")
    )
    assert stored.client.client_name == "Model Client"
    assert stored.ledger_entry.entry_id == "JE-INVOICE"
    assert stored.items[0].invoice.invoice_id == "INV-MODEL"
    assert stored.items[0].revenue_account_record.account_code == "4001"
    assert stored.payments[0].invoice.invoice_id == "INV-MODEL"
    assert stored.payments[0].ledger_entry.entry_id == "JE-PAYMENT"
    assert stored.subtotal == Decimal("12.34")
    assert stored.gst_rate_percent == Decimal("18.0000")
    assert stored.gst_amount == Decimal("2.22")
    assert stored.items[0].quantity == Decimal("1.250")
    assert stored.items[0].unit_price == Decimal("9.87")
    assert stored.payments[0].amount == Decimal("2.34")


def test_cancelled_invoice_with_zero_balance_is_valid(invoicing_db):
    cancelled = _invoice(
        invoice_id="INV-CANCELLED",
        invoice_number="INV/2025-26/CANCELLED",
        status="CANCELLED",
        subtotal=Decimal("100.00"),
        gst_amount=Decimal("18.00"),
        total_amount=Decimal("118.00"),
        amount_paid=Decimal("0.00"),
        balance_due=Decimal("0.00"),
    )
    invoicing_db.add(cancelled)
    invoicing_db.commit()

    stored = invoicing_db.get(Invoice, "INV-CANCELLED")
    assert stored.status == "CANCELLED"
    assert stored.total_amount == Decimal("118.00")
    assert stored.balance_due == Decimal("0.00")


def test_invoice_rejects_negative_financial_amounts(invoicing_db):
    invoicing_db.add(
        _invoice(
            invoice_id="INV-NEGATIVE",
            invoice_number="INV/2025-26/NEGATIVE",
            subtotal=Decimal("-1.00"),
            gst_amount=Decimal("0.00"),
            total_amount=Decimal("-1.00"),
            balance_due=Decimal("0.00"),
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


def test_invoice_number_and_invoice_line_number_are_unique(invoicing_db):
    invoicing_db.add(_invoice())
    invoicing_db.commit()

    invoicing_db.add(
        _invoice(
            invoice_id="INV-DUP-NUM",
            invoice_number="INV/2025-26/MODEL",
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()

    invoice = invoicing_db.get(Invoice, "INV-MODEL")
    invoice.items.extend(
        [
            InvoiceItem(
                invoice_item_id="II-ONE",
                line_no=1,
                description="First",
                quantity=Decimal("1"),
                unit_price=Decimal("1.00"),
                amount=Decimal("1.00"),
                revenue_account="4001",
            ),
            InvoiceItem(
                invoice_item_id="II-TWO",
                line_no=1,
                description="Duplicate line",
                quantity=Decimal("1"),
                unit_price=Decimal("1.00"),
                amount=Decimal("1.00"),
                revenue_account="4001",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


@pytest.mark.parametrize(
    "invoice",
    [
        _invoice(invoice_id="INV-BAD-CLIENT", client_id="NO-CLIENT"),
        _invoice(
            invoice_id="INV-BAD-LEDGER",
            invoice_number="INV/2025-26/BAD-LEDGER",
            ledger_entry_id="NO-ENTRY",
        ),
        _invoice(
            invoice_id="INV-BAD-ACCOUNT",
            invoice_number="INV/2025-26/BAD-ACCOUNT",
            service_line_account="NO-ACCOUNT",
        ),
    ],
)
def test_invoice_foreign_keys_are_enforced(invoicing_db, invoice):
    invoicing_db.add(invoice)
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


@pytest.mark.parametrize(
    ("invoice_id", "revenue_account"),
    [
        ("NO-INVOICE", "4001"),
        ("INV-MODEL", "NO-ACCOUNT"),
    ],
)
def test_invoice_item_foreign_keys_are_enforced(
    invoicing_db, invoice_id, revenue_account
):
    if invoice_id == "INV-MODEL":
        invoicing_db.add(_invoice())
        invoicing_db.flush()
    invoicing_db.add(
        InvoiceItem(
            invoice_item_id="II-BAD-REFERENCE",
            invoice_id=invoice_id,
            line_no=1,
            description="Invalid reference",
            quantity=Decimal("1.000"),
            unit_price=Decimal("1.00"),
            amount=Decimal("1.00"),
            revenue_account=revenue_account,
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


@pytest.mark.parametrize(
    ("invoice_id", "ledger_entry_id"),
    [
        ("NO-INVOICE", "JE-PAYMENT"),
        ("INV-MODEL", "NO-ENTRY"),
    ],
)
def test_invoice_payment_foreign_keys_are_enforced(
    invoicing_db, invoice_id, ledger_entry_id
):
    if invoice_id == "INV-MODEL":
        invoicing_db.add(_invoice())
        invoicing_db.flush()
    invoicing_db.add(
        InvoicePayment(
            payment_id="PAY-BAD-REFERENCE",
            invoice_id=invoice_id,
            payment_date=date(2025, 4, 2),
            amount=Decimal("1.00"),
            payment_mode="NEFT",
            reference_no="UTR-BAD",
            received_by="U-TEST",
            ledger_entry_id=ledger_entry_id,
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


@pytest.mark.parametrize(
    "item",
    [
        InvoiceItem(
            invoice_item_id="II-ZERO-QTY",
            invoice_id="INV-MODEL",
            line_no=1,
            description="Invalid quantity",
            quantity=Decimal("0.000"),
            unit_price=Decimal("1.00"),
            amount=Decimal("0.00"),
            revenue_account="4001",
        ),
        InvoiceItem(
            invoice_item_id="II-NEGATIVE",
            invoice_id="INV-MODEL",
            line_no=1,
            description="Invalid amount",
            quantity=Decimal("1.000"),
            unit_price=Decimal("-1.00"),
            amount=Decimal("-1.00"),
            revenue_account="4001",
        ),
    ],
)
def test_invoice_item_nonnegative_constraints(invoicing_db, item):
    invoicing_db.add(_invoice())
    invoicing_db.flush()
    invoicing_db.add(item)
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


def test_payment_requires_positive_amount_and_unique_ledger_reference(
    invoicing_db,
):
    invoicing_db.add(_invoice())
    invoicing_db.flush()
    invoicing_db.add(
        InvoicePayment(
            payment_id="PAY-ZERO",
            invoice_id="INV-MODEL",
            payment_date=date(2025, 4, 2),
            amount=Decimal("0.00"),
            payment_mode="NEFT",
            reference_no="UTR-ZERO",
            received_by="U-TEST",
            ledger_entry_id="JE-PAYMENT",
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()

    invoice = _invoice()
    invoicing_db.add(invoice)
    invoicing_db.flush()
    invoicing_db.add(
        InvoicePayment(
            payment_id="PAY-ONE",
            invoice_id=invoice.invoice_id,
            payment_date=date(2025, 4, 2),
            amount=Decimal("1.00"),
            payment_mode="NEFT",
            reference_no="UTR-ONE",
            received_by="U-TEST",
            ledger_entry_id="JE-PAYMENT",
        )
    )
    invoicing_db.commit()
    invoicing_db.add(
        InvoicePayment(
            payment_id="PAY-TWO",
            invoice_id=invoice.invoice_id,
            payment_date=date(2025, 4, 2),
            amount=Decimal("1.00"),
            payment_mode="NEFT",
            reference_no="UTR-TWO",
            received_by="U-TEST",
            ledger_entry_id="JE-PAYMENT",
        )
    )
    with pytest.raises(IntegrityError):
        invoicing_db.flush()
    invoicing_db.rollback()


def test_invoice_models_use_numeric_columns_and_status_constraint():
    for model, columns in (
        (
            Invoice,
            (
                "subtotal",
                "gst_rate_percent",
                "gst_amount",
                "total_amount",
                "amount_paid",
                "balance_due",
            ),
        ),
        (
            InvoiceItem,
            ("quantity", "unit_price", "amount"),
        ),
        (InvoicePayment, ("amount",)),
    ):
        for column_name in columns:
            assert isinstance(model.__table__.c[column_name].type, Numeric)
    status_check = next(
        constraint
        for constraint in Invoice.__table__.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_invoices_status"
    )
    for status in (
        "DRAFT",
        "SENT",
        "PARTIALLY_PAID",
        "PAID",
        "OVERDUE",
        "CANCELLED",
    ):
        assert status in str(status_check.sqltext)

    assert {
        constraint.name
        for constraint in Invoice.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    } == {
        "uq_invoices_invoice_number",
        "uq_invoices_ledger_entry_id",
    }
    assert {
        foreign_key.name
        for foreign_key in Invoice.__table__.foreign_key_constraints
    } == {
        "fk_invoices_client_id_clients",
        "fk_invoices_ledger_entry_id_journal_entries",
        "fk_invoices_service_line_account_chart_of_accounts",
    }


def test_seeder_registers_invoice_tables_with_dependency_order_and_decimals():
    positions = {table: seed.PRIORITY.index(table) for table in seed.PRIORITY}
    assert positions["chart_of_accounts"] < positions["clients"]
    assert positions["journal_entries"] < positions["invoices"]
    assert positions["journal_lines"] < positions["invoices"]
    assert positions["clients"] < positions["invoices"]
    assert positions["invoices"] < positions["invoice_items"]
    assert positions["invoices"] < positions["invoice_payments"]
    assert seed.normalize_value("12659866.00", "decimal", "invoices") == (
        Decimal("12659866.00")
    )
    assert seed.normalize_value("270492.58", "decimal", "invoice_payments") == (
        Decimal("270492.58")
    )
    assert seed.csv_dtypes("invoice_items")["unit_price"] is str
    assert seed.csv_dtypes("invoice_items")["revenue_account"] is str
    assert seed.csv_dtypes("invoices")["ledger_entry_id"] is str


def test_seeder_requires_invoice_migration_tables_before_generic_creation(
    tmp_path, monkeypatch
):
    engine = create_engine(f"sqlite:///{tmp_path / 'unmigrated.db'}")
    monkeypatch.setattr(seed, "engine", engine)

    with pytest.raises(RuntimeError, match="Run Alembic migrations"):
        seed.create_missing_tables({})

    assert inspect(engine).get_table_names() == []
    engine.dispose()


def _load_revision():
    spec = importlib.util.spec_from_file_location(
        "client_invoice_revision",
        REVISION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_payment_reference_revision():
    spec = importlib.util.spec_from_file_location(
        "payment_reference_revision",
        PAYMENT_REFERENCE_REVISION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_payment_reference_migration_enforces_unique_invoice_reference(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'payment-reference.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE invoice_payments ("
                "payment_id VARCHAR(30) PRIMARY KEY, "
                "invoice_id VARCHAR(30) NOT NULL, "
                "reference_no VARCHAR(50) NOT NULL)"
            )
        )
        revision = _load_payment_reference_revision()
        assert revision.down_revision == "b710c4a2d9e1"
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()

        assert "uq_invoice_payments_invoice_reference" in {
            index["name"]
            for index in inspect(connection).get_indexes("invoice_payments")
        }
        connection.execute(
            text(
                "INSERT INTO invoice_payments "
                "(payment_id, invoice_id, reference_no) "
                "VALUES ('PAY-1', 'INV-1', 'REF-1')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO invoice_payments "
                    "(payment_id, invoice_id, reference_no) "
                    "VALUES ('PAY-2', 'INV-1', 'REF-1')"
                )
            )

        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
        assert "uq_invoice_payments_invoice_reference" not in {
            index["name"]
            for index in inspect(connection).get_indexes("invoice_payments")
        }
    engine.dispose()


def test_payment_reference_migration_refuses_existing_duplicates(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-duplicates.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE invoice_payments ("
                "payment_id VARCHAR(30) PRIMARY KEY, "
                "invoice_id VARCHAR(30) NOT NULL, "
                "reference_no VARCHAR(50) NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO invoice_payments VALUES "
                "('PAY-1', 'INV-1', 'REF-1'), "
                "('PAY-2', 'INV-1', 'REF-1')"
            )
        )
        revision = _load_payment_reference_revision()
        with pytest.raises(RuntimeError, match="duplicate data is reconciled"):
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
        assert "uq_invoice_payments_invoice_reference" not in {
            index["name"]
            for index in inspect(connection).get_indexes("invoice_payments")
        }
    engine.dispose()


def test_invoicing_migration_upgrade_and_downgrade_on_disposable_database(
    tmp_path,
):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE chart_of_accounts "
                "(account_code VARCHAR(20) PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE journal_entries "
                "(entry_id VARCHAR(30) PRIMARY KEY)"
            )
        )
        revision = _load_revision()
        assert revision.down_revision == "f09a6b27c431"
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()

        inspector = inspect(connection)
        assert {
            "clients",
            "invoices",
            "invoice_items",
            "invoice_payments",
        }.issubset(inspector.get_table_names())
        assert {
            "ix_clients_client_name",
            "ix_clients_is_active",
        }.issubset(
            {index["name"] for index in inspector.get_indexes("clients")}
        )
        assert {
            "invoice_number",
            "ledger_entry_id",
        }.issubset(
            {
                column
                for constraint in inspector.get_unique_constraints("invoices")
                for column in constraint["column_names"]
            }
        )
        item_foreign_keys = inspector.get_foreign_keys("invoice_items")
        assert any(
            foreign_key["referred_table"] == "invoices"
            for foreign_key in item_foreign_keys
        )

        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
        remaining = set(inspect(connection).get_table_names())
        assert not {
            "clients",
            "invoices",
            "invoice_items",
            "invoice_payments",
        }.intersection(remaining)
    engine.dispose()


def test_invoicing_migration_leaves_one_alembic_head():
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["e7c2d10f4b39"]
