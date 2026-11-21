from pathlib import Path
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .database import Base, engine
from .config import settings
from redis import Redis
from redis.exceptions import RedisError
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


@app.middleware("http")
async def structured_request_logging(request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid4())
    started = time.perf_counter()
    response = await call_next(request)
    record = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    logging.getLogger("ledgerforge.structured").info(
        json.dumps(record, separators=(",", ":"))
    )
    response.headers["X-Request-ID"] = request_id
    return response

@app.get("/health", tags=["system"])
@app.get("/api/v1/health", tags=["system"])
def health():
    cache_status = "disabled"
    if settings.redis_url:
        try:
            Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
            cache_status = "ok"
        except (RedisError, TimeoutError):
            cache_status = "unavailable"
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
                "cache": cache_status,
            },
        )
    return {
        "status": "ok",
        "service": "ledgerforge",
        "database": "ok",
        "cache": cache_status,
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