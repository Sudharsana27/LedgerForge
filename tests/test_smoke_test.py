from argparse import Namespace

import httpx

from scripts.smoke_test import run_smoke_test


def test_smoke_test_checks_ui_login_payroll_and_payslip(tmp_path):
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path, request.headers.get("Authorization")))
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path in {"/docs", "/demo/"}:
            return httpx.Response(200, text="ok")
        if request.url.path == "/api/v1/auth/login":
            return httpx.Response(200, json={"access_token": "test-token"})
        if request.url.path == "/api/v1/payroll/calculate":
            return httpx.Response(200, json={"net_pay": "0.00"})
        if request.url.path == "/api/v1/payslips/EMP-DEMO/PR-DEMO":
            return httpx.Response(
                200,
                content=b"%PDF-demo",
                headers={"Content-Type": "application/pdf"},
            )
        return httpx.Response(404)

    args = Namespace(
        base_url="https://ledgerforge.example/",
        username="demo_admin",
        employee_id="EMP-DEMO",
        period_start="2026-01-01",
        period_end="2026-01-31",
        variable_pay="0",
        variable_pay_type=None,
        tds="0",
        other_deductions="0",
        run_id="PR-DEMO",
        payslip_output=tmp_path / "demo.pdf",
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        run_smoke_test(args, client, "temporary-password")

    assert (tmp_path / "demo.pdf").read_bytes() == b"%PDF-demo"
    assert [
        path
        for method, path, _authorization in seen
        if method == "GET"
    ] == [
        "/api/v1/health",
        "/docs",
        "/demo/",
        "/api/v1/payslips/EMP-DEMO/PR-DEMO",
    ]
    assert all(
        authorization == "Bearer test-token"
        for method, path, authorization in seen
        if path in {"/api/v1/payroll/calculate", "/api/v1/payslips/EMP-DEMO/PR-DEMO"}
    )
