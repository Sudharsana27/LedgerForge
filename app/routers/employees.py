
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_roles,
)
from ..database import get_db
from ..models import Department, Employee, Role
from ..schemas import EmployeeCreate, EmployeeOut, EmployeeUpdate

router = APIRouter(prefix="/employees", tags=["employees"])


def validate_references(
    db: Session,
    department_id: str,
    role_id: str,
    manager_id: str | None,
    employee_id: str | None = None,
) -> None:
    """Check that referenced department, role, and manager exist."""

    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(422, "Department does not exist")

    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(422, "Role does not exist")

    if role.department_id != department_id:
        raise HTTPException(
            422, "The selected role does not belong to this department"
        )

    if manager_id is not None:
        if manager_id == employee_id:
            raise HTTPException(422, "An employee cannot manage themselves")

        if not db.get(Employee, manager_id):
            raise HTTPException(422, "Manager does not exist")


def _require_manager(principal: AuthenticatedPrincipal) -> None:
    if principal.role not in {"ADMIN", "HR"}:
        raise HTTPException(403, "Employee management access denied")


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    q: str | None = None,
    department_id: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    query = db.query(Employee)

    if q:
        search = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Employee.first_name.ilike(search),
                Employee.last_name.ilike(search),
                Employee.full_name.ilike(search),
                Employee.work_email.ilike(search),
            )
        )

    if department_id:
        query = query.filter(Employee.department_id == department_id)

    return (
        query.order_by(Employee.employee_id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(
    employee_id: str,
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    if (
        principal.role not in {"ADMIN", "HR"}
        and principal.employee_id != employee_id
    ):
        raise HTTPException(403, "Employee data access denied")
    employee = db.get(Employee, employee_id)

    if not employee:
        raise HTTPException(404, "Employee not found")

    return employee


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(
    employee_data: EmployeeCreate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    data = employee_data.model_dump()
    employee_id = data["employee_id"]

    if db.get(Employee, employee_id):
        raise HTTPException(409, "Employee ID already exists")

    validate_references(
        db,
        department_id=data["department_id"],
        role_id=data["role_id"],
        manager_id=data.get("manager_id"),
        employee_id=employee_id,
    )

    data["full_name"] = (
        f'{data["first_name"].strip()} {data["last_name"].strip()}'
    )

    employee = Employee(**data)
    db.add(employee)

    try:
        db.commit()
        db.refresh(employee)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Employee could not be created; check for duplicate email or invalid references"
        )

    return employee


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: str,
    employee_data: EmployeeUpdate,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)

    if not employee:
        raise HTTPException(404, "Employee not found")

    changes = employee_data.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(422, "Provide at least one field to update")

    department_id = changes.get("department_id", employee.department_id)
    role_id = changes.get("role_id", employee.role_id)
    manager_id = changes.get("manager_id", employee.manager_id)

    validate_references(
        db,
        department_id=department_id,
        role_id=role_id,
        manager_id=manager_id,
        employee_id=employee_id,
    )

    if "first_name" in changes or "last_name" in changes:
        first_name = changes.get("first_name", employee.first_name)
        last_name = changes.get("last_name", employee.last_name)
        changes["full_name"] = f"{first_name.strip()} {last_name.strip()}"

    for field, value in changes.items():
        setattr(employee, field, value)

    try:
        db.commit()
        db.refresh(employee)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Employee could not be updated; check for duplicate email or invalid references"
        )

    return employee


@router.delete("/{employee_id}", response_model=EmployeeOut)
def soft_delete_employee(
    employee_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)

    if not employee:
        raise HTTPException(404, "Employee not found")

    if employee.exit_date is None:
        employee.exit_date = date.today()
        db.commit()
        db.refresh(employee)

    return employee


@router.get("/{employee_id}/team", response_model=list[EmployeeOut])
def get_employee_team(
    employee_id: str,
    principal: AuthenticatedPrincipal = Depends(
        require_roles("ADMIN", "HR")
    ),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)

    if not employee:
        raise HTTPException(404, "Employee not found")

    return (
        db.query(Employee)
        .filter(Employee.manager_id == employee_id)
        .order_by(Employee.employee_id)
        .all()
    )
