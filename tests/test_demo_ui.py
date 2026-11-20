from fastapi.testclient import TestClient

from app.main import app


def test_demo_ui_serves_responsive_authenticated_tools():
    with TestClient(app) as client:
        response = client.get("/demo/")
        root = client.get("/", follow_redirects=False)

    assert response.status_code == 200
    assert root.status_code == 307
    assert root.headers["location"] == "/demo/"
    assert "viewport" in response.text
    assert "/api/v1/auth/login" in response.text
    assert "/api/v1/payroll/calculate" in response.text
    assert "/api/v1/jobs/payroll/18-month" in response.text
    assert "/api/v1/jobs/${encodeURIComponent(id)}" in response.text
    assert "/api/v1/payslips/" in response.text
    assert "sessionStorage" in response.text
    assert "never falls back to synchronous execution" in response.text
    assert "clearPrivateResults" in response.text
