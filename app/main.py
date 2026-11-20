from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
from .routers import exports as exports_router
from .routers import jobs as jobs_router

Base.metadata.create_all(engine)

app = FastAPI(
    title="LedgerForge API",
    version="1.0.0",
    description="Payroll, accounting and employee data engine for Zenith Nova Technologies",
)

@app.get("/health", tags=["system"])
@app.get("/api/v1/health", tags=["system"])
def health():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "service": "ledgerforge",
                "database": "unavailable",
            },
        )
    return {
        "status": "ok",
        "service": "ledgerforge",
        "database": "ok",
        "api_version": "v1",
    }


@app.get("/", include_in_schema=False)
def demo_ui_redirect():
    return RedirectResponse("/demo/")


ROUTERS = (
    departments.router,
    auth.router,
    employees.router,
    salary.router,
    attendance.router,
    leave.router,
    payroll.router,
    payslips.router,
    clients.router,
    invoices.router,
    receivables.router,
    reports.router,
    expenses.vendors_router,
    expenses.router,
    tax.router,
    exports_router.router,
    jobs_router.router,
)

# Existing integrations remain compatible while all canonical routes live under /api/v1.
for router in ROUTERS:
    app.include_router(router)
    app.include_router(router, prefix="/api/v1")

app.mount(
    "/demo",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="demo-ui",
)