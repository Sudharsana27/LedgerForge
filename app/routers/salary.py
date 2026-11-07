
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_roles,
)
from ..database import get_db
from ..salary_service import (
    get_revision_history,
    get_structure,
    revise_salary,
)

router = APIRouter(prefix="/salary", tags=["salary"])


class SalaryComponentInput(BaseModel):
    component_id: str
    monthly_amount: Decimal = Field(ge=0)


class SalaryRevisionInput(BaseModel):
    employee_id: str
    effective_from: date
    revision_reason: str = Field(min_length=1, max_length=100)
    new_annual_fixed: Decimal = Field(gt=0)
    role_id_after: str
    approved_by: str | None = None
    components: list[SalaryComponentInput] = Field(min_length=1)


def revision_output(row):
    pct = (
        float(row.pct_change)
        if row.pct_change is not None
        else None
    )
    return {
        "revision_id": row.revision_id,
        "employee_id": row.employee_id,
        "effective_from": row.effective_from,
        "revision_reason": row.revision_reason,
        "previous_annual_fixed": (
            float(row.previous_annual_fixed)
            if row.previous_annual_fixed is not None
            else None
        ),
        "new_annual_fixed": float(row.new_annual_fixed),
        "pct_change": pct,
        "raise_above_20_percent": pct is not None and pct > 20,
        "role_id_after": row.role_id_after,
        "approved_by": row.approved_by,
    }


@router.get("/employees/{employee_id}/structure")
def employee_structure(
    employee_id: str,
    on_date: date,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    if (
        principal.role not in {"ADMIN", "HR"}
        and principal.employee_id != employee_id
    ):
        raise HTTPException(403, "Salary data access denied")
    try:
        rows = get_structure(db, employee_id, on_date)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "employee_id": employee_id,
        "on_date": on_date,
        "components": [
            {
                "structure_id": row.structure_id,
                "component_id": row.component_id,
                "component_name": row.component_name,
                "component_type": row.component_type,
                "monthly_amount": float(row.monthly_amount),
                "effective_from": row.effective_from,
                "effective_to": row.effective_to,
                "revision_id": row.revision_id,
            }
            for row in rows
        ],
    }


@router.get("/employees/{employee_id}/revisions")
def employee_revisions(
    employee_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    if (
        principal.role not in {"ADMIN", "HR"}
        and principal.employee_id != employee_id
    ):
        raise HTTPException(403, "Salary data access denied")
    try:
        rows = get_revision_history(db, employee_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [revision_output(row) for row in rows]


@router.post("/revisions", status_code=201)
def create_salary_revision(
    payload: SalaryRevisionInput,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    try:
        revision = revise_salary(
            db,
            employee_id=payload.employee_id,
            effective_from=payload.effective_from,
            revision_reason=payload.revision_reason,
            new_annual_fixed=payload.new_annual_fixed,
            role_id_after=payload.role_id_after,
            approved_by=payload.approved_by,
            components=[
                item.model_dump() for item in payload.components
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return revision_output(revision)
