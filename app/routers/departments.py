"""PATTERN TO COPY: a router = a group of related endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..auth import require_roles
from ..database import get_db
from ..models import Department
from ..schemas import DepartmentOut
router = APIRouter(
    prefix="/departments",
    tags=["departments"],
    dependencies=[Depends(require_roles("ADMIN", "HR"))],
)
@router.get("", response_model=list[DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    return db.query(Department).order_by(Department.department_id).all()
@router.get("/{department_id}", response_model=DepartmentOut)
def get_department(department_id: str, db: Session = Depends(get_db)):
    d = db.get(Department, department_id)
    if not d: raise HTTPException(404, "Department not found")
    return d
