from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, get_authenticated_principal
from ..database import get_db
from ..invoice_service import (
    DraftInvoiceInput,
    InvoiceItemDraft,
    InvoicePaymentInput,
    InvoiceServiceError,
    cancel_invoice,
    create_draft_invoice,
    get_invoice,
    list_invoices,
    record_payment,
    refresh_invoice_status,
    send_invoice,
)
from ..schemas import (
    InvoiceActionOut,
    InvoiceCreate,
    InvoiceOut,
    InvoicePaymentCreate,
    InvoicePaymentOut,
    InvoiceRefreshStatus,
    InvoiceSendInput,
    InvoiceStatus,
)


router = APIRouter(prefix="/invoices", tags=["invoices"])


def _service_error(exc: InvoiceServiceError) -> HTTPException:
    detail = str(exc)
    if "does not exist" in detail:
        code = status.HTTP_404_NOT_FOUND
    elif "already exists" in detail:
        code = status.HTTP_409_CONFLICT
        detail = "Invoice data conflicts with an existing record."
    elif "database constraint was violated" in detail:
        code = status.HTTP_409_CONFLICT
        detail = "Invoice data conflicts with an existing record."
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(status_code=code, detail=detail)


def _database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The invoice operation could not be completed.",
    )


@router.post(
    "",
    response_model=InvoiceOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invoice_draft(
    payload: InvoiceCreate,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    invoice_id = f"INV-{uuid4().hex[:16].upper()}"
    draft = DraftInvoiceInput(
        invoice_id=invoice_id,
        invoice_number=payload.invoice_number,
        client_id=payload.client_id,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date,
        gst_rate_percent=payload.gst_rate_percent,
        items=[
            InvoiceItemDraft(**item.model_dump())
            for item in payload.items
        ],
        created_by=principal.employee_id,
        created_at=datetime.now(),
        po_number=payload.po_number,
    )
    try:
        create_draft_invoice(db, draft)
        invoice = get_invoice(db, invoice_id)
    except InvoiceServiceError as exc:
        raise _service_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if invoice is None:
        raise _database_error()
    return invoice


@router.get(
    "",
    response_model=list[InvoiceOut],
    dependencies=[Depends(get_authenticated_principal)],
)
def get_invoices(
    client_id: str | None = Query(default=None, min_length=1, max_length=20),
    status_filter: InvoiceStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
):
    try:
        return list_invoices(
            db,
            client_id=client_id,
            status=status_filter,
        )
    except SQLAlchemyError as exc:
        raise _database_error() from exc


@router.get(
    "/{invoice_id}",
    response_model=InvoiceOut,
    dependencies=[Depends(get_authenticated_principal)],
)
def get_invoice_by_id(
    invoice_id: str,
    db: Session = Depends(get_db),
):
    try:
        invoice = get_invoice(db, invoice_id)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@router.post("/{invoice_id}/send", response_model=InvoiceActionOut)
def send_invoice_draft(
    invoice_id: str,
    payload: InvoiceSendInput,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    try:
        entry = send_invoice(
            db,
            invoice_id,
            business_date=payload.business_date,
            created_by=principal.employee_id,
        )
        invoice = get_invoice(db, invoice_id)
    except InvoiceServiceError as exc:
        raise _service_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if invoice is None:
        raise _database_error()
    return InvoiceActionOut(invoice=invoice, journal_entry_id=entry.entry_id)


@router.post(
    "/{invoice_id}/payments",
    response_model=InvoicePaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_invoice_payment(
    invoice_id: str,
    payload: InvoicePaymentCreate,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    payment = InvoicePaymentInput(
        payment_date=payload.payment_date,
        amount=payload.amount,
        payment_mode=payload.payment_mode,
        reference_no=payload.reference_no,
        received_by=principal.employee_id,
    )
    try:
        return record_payment(db, invoice_id, payment)
    except InvoiceServiceError as exc:
        raise _service_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc


@router.post("/{invoice_id}/cancel", response_model=InvoiceActionOut)
def cancel_invoice_record(
    invoice_id: str,
    payload: InvoiceRefreshStatus,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    try:
        entry = cancel_invoice(
            db,
            invoice_id,
            business_date=payload.business_date,
            created_by=principal.employee_id,
        )
        invoice = get_invoice(db, invoice_id)
    except InvoiceServiceError as exc:
        raise _service_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if invoice is None:
        raise _database_error()
    return InvoiceActionOut(
        invoice=invoice,
        journal_entry_id=entry.entry_id if entry is not None else None,
    )


@router.post(
    "/{invoice_id}/refresh-status",
    response_model=InvoiceOut,
    dependencies=[Depends(get_authenticated_principal)],
)
def refresh_invoice_status_record(
    invoice_id: str,
    payload: InvoiceRefreshStatus,
    db: Session = Depends(get_db),
):
    try:
        refresh_invoice_status(
            db,
            invoice_id,
            business_date=payload.business_date,
        )
        invoice = get_invoice(db, invoice_id)
    except InvoiceServiceError as exc:
        raise _service_error(exc) from exc
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if invoice is None:
        raise _database_error()
    return invoice
