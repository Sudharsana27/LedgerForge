"""Read-only outstanding receivables aggregation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Client, Invoice


OPEN_STATUSES = {"SENT", "PARTIALLY_PAID", "OVERDUE"}


class ReceivablesError(ValueError):
    """Raised when a receivables query uses an invalid filter."""


@dataclass(frozen=True)
class ReceivableInvoice:
    invoice_id: str
    invoice_number: str
    invoice_date: date
    due_date: date
    status: str
    balance_due: Decimal


@dataclass(frozen=True)
class ClientReceivable:
    client_id: str
    client_name: str
    open_invoice_count: int
    total_outstanding: Decimal
    invoices: tuple[ReceivableInvoice, ...]


@dataclass(frozen=True)
class ReceivablesReport:
    total_outstanding: Decimal
    clients: tuple[ClientReceivable, ...]


def build_receivables_report(
    db: Session,
    *,
    client_id: str | None = None,
    status: str | None = None,
) -> ReceivablesReport:
    """Aggregate open invoice balances without adding opening journal lines."""
    if status is not None and status not in OPEN_STATUSES:
        raise ReceivablesError(
            "Receivables status must be SENT, PARTIALLY_PAID, or OVERDUE."
        )
    if client_id is not None and db.get(Client, client_id) is None:
        raise ReceivablesError(f"Client {client_id} does not exist.")

    statement = (
        select(Client, Invoice)
        .join(Invoice, Invoice.client_id == Client.client_id)
        .where(
            Invoice.status.in_(OPEN_STATUSES),
            Invoice.balance_due > Decimal("0.00"),
            or_(
                Invoice.ledger_entry_id.is_not(None),
                Invoice.carried_in_from_prior_period == "Y",
            ),
        )
        .order_by(
            Client.client_id,
            Invoice.invoice_date,
            Invoice.invoice_number,
        )
    )
    if client_id is not None:
        statement = statement.where(Invoice.client_id == client_id)
    if status is not None:
        statement = statement.where(Invoice.status == status)

    rows = db.execute(statement).all()
    grouped: dict[str, tuple[Client, list[Invoice]]] = {}
    for client, invoice in rows:
        grouped.setdefault(client.client_id, (client, []))[1].append(invoice)

    clients: list[ClientReceivable] = []
    report_total = Decimal("0.00")
    for client, invoices in grouped.values():
        invoice_details = tuple(
            ReceivableInvoice(
                invoice_id=invoice.invoice_id,
                invoice_number=invoice.invoice_number,
                invoice_date=invoice.invoice_date,
                due_date=invoice.due_date,
                status=invoice.status,
                balance_due=invoice.balance_due,
            )
            for invoice in invoices
        )
        total = sum(
            (invoice.balance_due for invoice in invoices),
            Decimal("0.00"),
        )
        report_total += total
        clients.append(
            ClientReceivable(
                client_id=client.client_id,
                client_name=client.client_name,
                open_invoice_count=len(invoice_details),
                total_outstanding=total,
                invoices=invoice_details,
            )
        )

    return ReceivablesReport(
        total_outstanding=report_total,
        clients=tuple(clients),
    )
