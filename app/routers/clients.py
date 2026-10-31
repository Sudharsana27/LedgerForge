from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..auth import AuthenticatedPrincipal, get_authenticated_principal
from ..database import get_db
from ..models import ChartOfAccount, Client, Invoice
from ..schemas import ClientCreate, ClientOut, ClientUpdate


router = APIRouter(prefix="/clients", tags=["clients"])


def _require_client_manager(principal: AuthenticatedPrincipal) -> None:
    if principal.role not in {"HR", "ADMIN"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client management access denied",
        )


def _database_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="The client operation could not be completed.",
    )


def _validate_service_line(db: Session, account_code: str) -> None:
    if db.get(ChartOfAccount, account_code) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Primary service line does not exist",
        )


@router.post(
    "",
    response_model=ClientOut,
    status_code=status.HTTP_201_CREATED,
)
def create_client(
    payload: ClientCreate,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> Client:
    _require_client_manager(principal)
    if db.get(Client, payload.client_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client ID already exists",
        )
    _validate_service_line(db, payload.primary_service_line)
    client = Client(**payload.model_dump())
    try:
        db.add(client)
        db.commit()
        db.refresh(client)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client could not be created because it conflicts with an existing record.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _database_error() from exc
    return client


@router.get("", response_model=list[ClientOut])
def list_clients(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> list[Client]:
    _require_client_manager(principal)
    try:
        return list(
            db.scalars(
                select(Client)
                .order_by(Client.client_id)
                .offset(skip)
                .limit(limit)
            ).all()
        )
    except SQLAlchemyError as exc:
        raise _database_error() from exc


@router.get("/{client_id}", response_model=ClientOut)
def get_client(
    client_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> Client:
    _require_client_manager(principal)
    try:
        client = db.get(Client, client_id)
    except SQLAlchemyError as exc:
        raise _database_error() from exc
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found",
        )
    return client


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(
    client_id: str,
    payload: ClientUpdate,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> Client:
    _require_client_manager(principal)
    try:
        client = db.get(Client, client_id)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )
        changes = payload.model_dump(exclude_unset=True)
        if "primary_service_line" in changes:
            _validate_service_line(db, changes["primary_service_line"])
        for field_name, value in changes.items():
            setattr(client, field_name, value)
        db.commit()
        db.refresh(client)
        return client
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client could not be updated because it conflicts with an existing record.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _database_error() from exc


@router.delete(
    "/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_client(
    client_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
) -> Response:
    _require_client_manager(principal)
    try:
        client = db.get(Client, client_id)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )
        invoice_id = db.scalar(
            select(Invoice.invoice_id)
            .where(Invoice.client_id == client_id)
            .limit(1)
        )
        if invoice_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Client cannot be deleted while invoices reference it",
            )
        db.delete(client)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client cannot be deleted while records reference it",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _database_error() from exc
