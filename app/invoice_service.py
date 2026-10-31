"""Transactional invoice and payment business operations."""

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .ledger_service import (
    JournalEntryInput,
    JournalLineInput,
    create_journal_entry_in_transaction,
    reverse_journal_entry_in_transaction,
)
from .models import (
    ChartOfAccount,
    Client,
    Invoice,
    InvoiceItem,
    InvoicePayment,
    JournalEntry,
)


CENT = Decimal("0.01")
GST_RATE_SCALE = Decimal("0.0001")
QUANTITY_SCALE = Decimal("0.001")
REVENUE_ACCOUNTS = {"4001", "4002", "4003", "4004"}


class InvoiceServiceError(ValueError):
    """Raised when an invoice operation violates a business rule."""


@dataclass(frozen=True)
class InvoiceItemDraft:
    description: str
    quantity: Decimal
    unit_price: Decimal
    revenue_account: str


@dataclass(frozen=True)
class DraftInvoiceInput:
    invoice_id: str
    invoice_number: str
    client_id: str
    invoice_date: date
    due_date: date
    gst_rate_percent: Decimal
    items: Sequence[InvoiceItemDraft]
    created_by: str
    created_at: datetime
    po_number: str | None = None


@dataclass(frozen=True)
class InvoicePaymentInput:
    payment_date: date
    amount: Decimal
    payment_mode: str
    reference_no: str
    received_by: str


def _require_transaction_owner(db: Session, operation: str) -> None:
    if db.in_transaction():
        raise InvoiceServiceError(
            f"{operation} requires a Session with no active transaction."
        )


def _require_decimal(
    value: Decimal, field: str, scale: Decimal
) -> Decimal:
    if not isinstance(value, Decimal):
        raise InvoiceServiceError(f"{field} must be a Decimal value.")
    if not value.is_finite():
        raise InvoiceServiceError(f"{field} must be finite.")
    if value.as_tuple().exponent < scale.as_tuple().exponent:
        raise InvoiceServiceError(
            f"{field} cannot have more than "
            f"{abs(scale.as_tuple().exponent)} decimal places."
        )
    return value


def _line_amount(quantity: Decimal, unit_price: Decimal) -> Decimal:
    quantity = _require_decimal(quantity, "Quantity", QUANTITY_SCALE)
    unit_price = _require_decimal(unit_price, "Unit price", CENT)
    if quantity <= 0:
        raise InvoiceServiceError("Quantity must be greater than zero.")
    if unit_price < 0:
        raise InvoiceServiceError("Unit price cannot be negative.")
    with localcontext() as context:
        context.prec = 50
        return (quantity * unit_price).quantize(
            CENT, rounding=ROUND_HALF_UP
        )


def _gst_amount(subtotal: Decimal, rate: Decimal) -> Decimal:
    rate = _require_decimal(rate, "GST rate", GST_RATE_SCALE)
    if rate < 0:
        raise InvoiceServiceError("GST rate cannot be negative.")
    with localcontext() as context:
        context.prec = 50
        return (subtotal * rate / Decimal("100")).quantize(
            CENT, rounding=ROUND_HALF_UP
        )


def _validate_account_types(
    db: Session,
    expected_types: dict[str, str],
) -> None:
    accounts = {
        account.account_code: account
        for account in db.scalars(
            select(ChartOfAccount).where(
                ChartOfAccount.account_code.in_(expected_types)
            )
        )
    }
    for account_code, expected_type in expected_types.items():
        account = accounts.get(account_code)
        if account is not None and account.account_type != expected_type:
            raise InvoiceServiceError(
                f"Account {account_code} must be an {expected_type.lower()} "
                f"account, not {account.account_type.lower()}."
            )


def _financial_year(day: date) -> str:
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def _journal_input(
    *,
    entry_id: str,
    entry_date: date,
    description: str,
    source_type: str,
    source_id: str,
    created_by: str,
) -> JournalEntryInput:
    return JournalEntryInput(
        entry_id=entry_id,
        entry_date=entry_date,
        posting_period=entry_date.strftime("%Y-%m"),
        financial_year=_financial_year(entry_date),
        description=description,
        source_type=source_type,
        source_id=source_id,
        created_by=created_by,
        created_at=datetime.combine(entry_date, time.min),
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:16].upper()}"


def _load_invoice_for_update(db: Session, invoice_id: str) -> Invoice:
    invoice = db.scalar(
        select(Invoice)
        .options(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.ledger_entry),
        )
        .where(Invoice.invoice_id == invoice_id)
        .with_for_update()
    )
    if invoice is None:
        raise InvoiceServiceError(f"Invoice {invoice_id} does not exist.")
    return invoice


def get_invoice(db: Session, invoice_id: str) -> Invoice | None:
    return db.scalar(
        select(Invoice)
        .options(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.ledger_entry),
        )
        .where(Invoice.invoice_id == invoice_id)
    )


def list_invoices(
    db: Session,
    *,
    client_id: str | None = None,
    status: str | None = None,
) -> list[Invoice]:
    statement = (
        select(Invoice)
        .options(
            selectinload(Invoice.items),
            selectinload(Invoice.payments),
            selectinload(Invoice.ledger_entry),
        )
        .order_by(Invoice.invoice_date.desc(), Invoice.invoice_id)
    )
    if client_id is not None:
        statement = statement.where(Invoice.client_id == client_id)
    if status is not None:
        statement = statement.where(Invoice.status == status)
    return list(db.scalars(statement))


def _status_for_balance(invoice: Invoice, business_date: date) -> str:
    if invoice.balance_due == Decimal("0.00"):
        return "PAID"
    if invoice.due_date < business_date:
        return "OVERDUE"
    if invoice.amount_paid > Decimal("0.00"):
        return "PARTIALLY_PAID"
    return "SENT"


def create_draft_invoice(
    db: Session,
    draft: DraftInvoiceInput,
) -> Invoice:
    """Create an unposted invoice draft, calculating item and GST amounts."""
    _require_transaction_owner(db, "create_draft_invoice")
    if not draft.items:
        raise InvoiceServiceError("An invoice must contain at least one item.")
    if not isinstance(draft.invoice_date, date) or not isinstance(
        draft.due_date, date
    ):
        raise InvoiceServiceError("Invoice and due dates are required.")

    calculated_items: list[tuple[InvoiceItemDraft, Decimal]] = []
    subtotal = Decimal("0.00")
    for item in draft.items:
        if item.revenue_account not in REVENUE_ACCOUNTS:
            raise InvoiceServiceError(
                "Invoice items must use a supported revenue account "
                "(4001–4004)."
            )
        amount = _line_amount(item.quantity, item.unit_price)
        calculated_items.append((item, amount))
        subtotal += amount

    gst_amount = _gst_amount(subtotal, draft.gst_rate_percent)
    total_amount = subtotal + gst_amount
    if total_amount <= Decimal("0.00"):
        raise InvoiceServiceError("Invoice total must be greater than zero.")

    try:
        with db.begin():
            client = db.get(Client, draft.client_id)
            if client is None:
                raise InvoiceServiceError(
                    f"Client {draft.client_id} does not exist."
                )
            invoice = Invoice(
                invoice_id=draft.invoice_id,
                invoice_number=draft.invoice_number,
                client_id=draft.client_id,
                invoice_date=draft.invoice_date,
                due_date=draft.due_date,
                service_line_account=client.primary_service_line,
                currency="INR",
                subtotal=subtotal,
                gst_rate_percent=draft.gst_rate_percent,
                gst_amount=gst_amount,
                total_amount=total_amount,
                amount_paid=Decimal("0.00"),
                balance_due=total_amount,
                status="DRAFT",
                last_payment_date=None,
                po_number=draft.po_number,
                carried_in_from_prior_period="N",
                created_by=draft.created_by,
                created_at=draft.created_at,
                ledger_entry_id=None,
            )
            invoice.items.extend(
                InvoiceItem(
                    invoice_item_id=_new_id("II"),
                    line_no=line_no,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=amount,
                    revenue_account=item.revenue_account,
                )
                for line_no, (item, amount) in enumerate(
                    calculated_items, start=1
                )
            )
            db.add(invoice)
            db.flush()
            return invoice
    except IntegrityError as exc:
        raise InvoiceServiceError(
            f"Draft invoice could not be saved because a database "
            f"constraint was violated: {exc.orig}"
        ) from exc


def send_invoice(
    db: Session,
    invoice_id: str,
    *,
    business_date: date,
    created_by: str,
) -> JournalEntry:
    """Post a draft invoice once and transition it to SENT or OVERDUE."""
    _require_transaction_owner(db, "send_invoice")
    try:
        with db.begin():
            invoice = _load_invoice_for_update(db, invoice_id)
            if invoice.status in {
                "SENT",
                "PARTIALLY_PAID",
                "PAID",
                "OVERDUE",
            } and invoice.ledger_entry_id:
                entry = invoice.ledger_entry
                if entry is None or entry.status != "POSTED":
                    raise InvoiceServiceError(
                        "Invoice references a missing or unposted journal entry."
                    )
                return entry
            if invoice.status == "CANCELLED":
                raise InvoiceServiceError(
                    "A cancelled invoice cannot be sent."
                )
            if invoice.carried_in_from_prior_period == "Y":
                raise InvoiceServiceError(
                    "Carried-in historical invoices cannot be sent or posted again."
                )
            if invoice.status != "DRAFT":
                raise InvoiceServiceError(
                    f"Only draft invoices can be sent; current status is "
                    f"{invoice.status}."
                )
            if invoice.ledger_entry_id is not None:
                raise InvoiceServiceError(
                    "A draft invoice already has a ledger reference."
                )
            if not invoice.items:
                raise InvoiceServiceError(
                    "An invoice must contain at least one item."
                )

            revenue_totals: dict[str, Decimal] = {}
            for item in invoice.items:
                if item.revenue_account not in REVENUE_ACCOUNTS:
                    raise InvoiceServiceError(
                        "Invoice items must use a supported revenue account "
                        "(4001–4004)."
                    )
                revenue_totals[item.revenue_account] = (
                    revenue_totals.get(item.revenue_account, Decimal("0.00"))
                    + item.amount
                )
            if sum(revenue_totals.values(), Decimal("0.00")) != invoice.subtotal:
                raise InvoiceServiceError(
                    "Invoice item amounts do not equal the invoice subtotal."
                )
            account_types = {
                "1100": "ASSET",
                **{
                    account_code: "INCOME"
                    for account_code in revenue_totals
                },
            }
            if invoice.gst_amount > Decimal("0.00"):
                account_types["2200"] = "LIABILITY"
            _validate_account_types(db, account_types)

            entry_id = _new_id("JE-INV")
            lines: list[JournalLineInput] = [
                JournalLineInput(
                    line_id=_new_id("JL-INV"),
                    line_no=1,
                    account_code="1100",
                    debit=invoice.total_amount,
                    credit=Decimal("0.00"),
                    line_description=f"Accounts receivable {invoice.invoice_number}",
                )
            ]
            line_no = 2
            for account_code, amount in sorted(revenue_totals.items()):
                if amount <= Decimal("0.00"):
                    continue
                lines.append(
                    JournalLineInput(
                        line_id=_new_id("JL-INV"),
                        line_no=line_no,
                        account_code=account_code,
                        debit=Decimal("0.00"),
                        credit=amount,
                        line_description=(
                            f"Revenue {invoice.invoice_number}"
                        ),
                    )
                )
                line_no += 1
            if invoice.gst_amount > Decimal("0.00"):
                lines.append(
                    JournalLineInput(
                        line_id=_new_id("JL-INV"),
                        line_no=line_no,
                        account_code="2200",
                        debit=Decimal("0.00"),
                        credit=invoice.gst_amount,
                        line_description=f"GST {invoice.invoice_number}",
                    )
                )

            entry = create_journal_entry_in_transaction(
                db,
                _journal_input(
                    entry_id=entry_id,
                    entry_date=business_date,
                    description=f"Invoice {invoice.invoice_number}",
                    source_type="INVOICE",
                    source_id=invoice.invoice_id,
                    created_by=created_by,
                ),
                lines,
            )
            invoice.ledger_entry = entry
            invoice.ledger_entry_id = entry.entry_id
            invoice.status = _status_for_balance(invoice, business_date)
            db.flush()
            return entry
    except IntegrityError as exc:
        raise InvoiceServiceError(
            f"Invoice could not be posted because a database constraint "
            f"was violated: {exc.orig}"
        ) from exc


def record_payment(
    db: Session,
    invoice_id: str,
    payment: InvoicePaymentInput,
) -> InvoicePayment:
    """Record a payment and post the matching bank/receivable journal entry."""
    _require_transaction_owner(db, "record_payment")
    amount = _require_decimal(payment.amount, "Payment amount", CENT)
    if amount <= Decimal("0.00"):
        raise InvoiceServiceError("Payment amount must be greater than zero.")
    if not isinstance(payment.payment_date, date):
        raise InvoiceServiceError("Payment date is required.")

    try:
        with db.begin():
            invoice = _load_invoice_for_update(db, invoice_id)
            duplicate_reference = db.scalar(
                select(InvoicePayment.payment_id)
                .where(
                    InvoicePayment.invoice_id == invoice_id,
                    InvoicePayment.reference_no == payment.reference_no,
                )
                .limit(1)
            )
            if duplicate_reference is not None:
                raise InvoiceServiceError(
                    "Payment reference already exists for this invoice."
                )
            if invoice.status in {"DRAFT", "CANCELLED"}:
                raise InvoiceServiceError(
                    f"Payments are not allowed for {invoice.status.lower()} "
                    "invoices."
                )
            if invoice.status not in {
                "SENT",
                "PARTIALLY_PAID",
                "OVERDUE",
            }:
                raise InvoiceServiceError(
                    f"Payments are not allowed for invoices with status "
                    f"{invoice.status}."
                )
            if (
                invoice.ledger_entry_id is None
                and invoice.carried_in_from_prior_period != "Y"
            ):
                raise InvoiceServiceError(
                    "Invoice has no posted ledger entry."
                )
            if invoice.ledger_entry_id is not None and (
                invoice.ledger_entry is None
                or invoice.ledger_entry.status != "POSTED"
            ):
                raise InvoiceServiceError(
                    "Invoice references a missing or unposted journal entry."
                )
            if invoice.balance_due <= Decimal("0.00"):
                raise InvoiceServiceError(
                    "Invoice has no outstanding balance."
                )
            if amount > invoice.balance_due:
                raise InvoiceServiceError(
                    "Payment amount exceeds the outstanding balance."
                )

            new_amount_paid = invoice.amount_paid + amount
            new_balance_due = invoice.total_amount - new_amount_paid
            if new_balance_due < Decimal("0.00"):
                raise InvoiceServiceError(
                    "Payment amount exceeds the outstanding balance."
                )

            payment_id = _new_id("PAY")
            entry_id = _new_id("JE-PAY")
            _validate_account_types(
                db,
                {"1001": "ASSET", "1100": "ASSET"},
            )
            entry = create_journal_entry_in_transaction(
                db,
                _journal_input(
                    entry_id=entry_id,
                    entry_date=payment.payment_date,
                    description=(
                        f"Payment {payment.reference_no} for "
                        f"{invoice.invoice_number}"
                    ),
                    source_type="INVOICE_PAYMENT",
                    source_id=payment_id,
                    created_by=payment.received_by,
                ),
                [
                    JournalLineInput(
                        line_id=_new_id("JL-PAY"),
                        line_no=1,
                        account_code="1001",
                        debit=amount,
                        credit=Decimal("0.00"),
                        line_description=(
                            f"Bank receipt {payment.reference_no}"
                        ),
                    ),
                    JournalLineInput(
                        line_id=_new_id("JL-PAY"),
                        line_no=2,
                        account_code="1100",
                        debit=Decimal("0.00"),
                        credit=amount,
                        line_description=(
                            f"Receivable settlement {invoice.invoice_number}"
                        ),
                    ),
                ],
            )
            recorded_payment = InvoicePayment(
                payment_id=payment_id,
                invoice_id=invoice.invoice_id,
                payment_date=payment.payment_date,
                amount=amount,
                payment_mode=payment.payment_mode,
                reference_no=payment.reference_no,
                received_by=payment.received_by,
                ledger_entry_id=entry.entry_id,
            )
            db.add(recorded_payment)
            invoice.amount_paid = new_amount_paid
            invoice.balance_due = new_balance_due
            invoice.last_payment_date = payment.payment_date
            invoice.status = _status_for_balance(
                invoice, payment.payment_date
            )
            db.flush()
            return recorded_payment
    except IntegrityError as exc:
        raise InvoiceServiceError(
            f"Payment could not be recorded because a database constraint "
            f"was violated: {exc.orig}"
        ) from exc


def cancel_invoice(
    db: Session,
    invoice_id: str,
    *,
    business_date: date,
    created_by: str,
) -> JournalEntry | None:
    """Cancel a draft or reverse an unpaid posted invoice atomically."""
    _require_transaction_owner(db, "cancel_invoice")
    try:
        with db.begin():
            invoice = _load_invoice_for_update(db, invoice_id)
            if invoice.status == "CANCELLED":
                reversal = db.scalar(
                    select(JournalEntry).where(
                        JournalEntry.source_type == "INVOICE_REVERSAL",
                        JournalEntry.source_id == invoice.invoice_id,
                    )
                )
                return reversal or invoice.ledger_entry
            if invoice.status == "DRAFT":
                invoice.status = "CANCELLED"
                invoice.balance_due = Decimal("0.00")
                db.flush()
                return None
            if invoice.status in {"PARTIALLY_PAID", "PAID"} or (
                invoice.amount_paid > Decimal("0.00")
            ):
                raise InvoiceServiceError(
                    "Partially paid or paid invoices cannot be cancelled."
                )
            if invoice.status not in {"SENT", "OVERDUE"}:
                raise InvoiceServiceError(
                    "Only an unpaid SENT or OVERDUE invoice can be cancelled."
                )
            if (
                invoice.amount_paid != Decimal("0.00")
                or invoice.balance_due != invoice.total_amount
                or invoice.payments
            ):
                raise InvoiceServiceError(
                    "Partially paid or paid invoices cannot be cancelled."
                )
            if invoice.ledger_entry_id is None or invoice.ledger_entry is None:
                raise InvoiceServiceError(
                    "Invoice has no individual posted journal entry to reverse."
                )
            if invoice.ledger_entry.status != "POSTED":
                raise InvoiceServiceError(
                    "Only a posted invoice journal entry can be reversed."
                )

            original_entry = invoice.ledger_entry
            original_lines = list(original_entry.lines)
            reversal_entry = reverse_journal_entry_in_transaction(
                db,
                original_entry.entry_id,
                _journal_input(
                    entry_id=_new_id("JE-REV"),
                    entry_date=business_date,
                    description=f"Reversal of invoice {invoice.invoice_number}",
                    source_type="INVOICE_REVERSAL",
                    source_id=invoice.invoice_id,
                    created_by=created_by,
                ),
                [_new_id("JL-REV") for _ in original_lines],
            )
            invoice.status = "CANCELLED"
            invoice.balance_due = Decimal("0.00")
            db.flush()
            return reversal_entry
    except IntegrityError as exc:
        raise InvoiceServiceError(
            f"Invoice could not be cancelled because a database constraint "
            f"was violated: {exc.orig}"
        ) from exc


def refresh_invoice_status(
    db: Session,
    invoice_id: str,
    *,
    business_date: date,
) -> Invoice:
    """Recompute an invoice's open status using the supplied business date."""
    _require_transaction_owner(db, "refresh_invoice_status")
    if not isinstance(business_date, date):
        raise InvoiceServiceError("Business date is required.")
    try:
        with db.begin():
            invoice = _load_invoice_for_update(db, invoice_id)
            if invoice.status not in {"DRAFT", "CANCELLED"}:
                invoice.status = _status_for_balance(invoice, business_date)
                db.flush()
            return invoice
    except IntegrityError as exc:
        raise InvoiceServiceError(
            f"Invoice status could not be updated because a database "
            f"constraint was violated: {exc.orig}"
        ) from exc
