from fastapi import FastAPI
from .database import Base, engine
from .routers import (
    attendance,
    auth,
    clients,
    departments,
    employees,
    expenses,
    invoices,
    leave,
    payroll,
    payslips,
    reports,
    receivables,
    salary,
    tax,
)

Base.metadata.create_all(engine)

app = FastAPI(
    title="LedgerForge API",
    version="0.1.0",
    description="Payroll, accounting and employee data engine for Zenith Nova Technologies",
)

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "ledgerforge"}

app.include_router(departments.router)
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(salary.router)
app.include_router(attendance.router)
app.include_router(leave.router)
app.include_router(payroll.router)
app.include_router(payslips.router)
app.include_router(clients.router)
app.include_router(invoices.router)
app.include_router(receivables.router)
app.include_router(reports.router)
app.include_router(expenses.vendors_router)
app.include_router(expenses.router)
app.include_router(tax.router)