import argparse
import getpass
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test a live LedgerForge API.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--password-env",
        default="LEDGERFORGE_SMOKE_PASSWORD",
        help="environment variable containing the password (prompt if unset)",
    )
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--variable-pay", required=True)
    parser.add_argument("--variable-pay-type")
    parser.add_argument("--tds", required=True)
    parser.add_argument("--other-deductions", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    password = os.environ.get(args.password_env) or getpass.getpass(
        "LedgerForge password: "
    )

    with httpx.Client(timeout=20.0) as client:
        health = client.get(f"{base_url}/api/v1/health")
        health.raise_for_status()
        if health.json().get("status") != "ok":
            raise RuntimeError("Health check did not report ok")
        docs = client.get(f"{base_url}/docs")
        docs.raise_for_status()
        login = client.post(
            f"{base_url}/api/v1/auth/login",
            json={"username": args.username, "password": password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        payroll = client.post(
            f"{base_url}/api/v1/payroll/calculate",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "employee_id": args.employee_id,
                "period_start": args.period_start,
                "period_end": args.period_end,
                "variable_pay": args.variable_pay,
                "variable_pay_type": args.variable_pay_type,
                "tds": args.tds,
                "other_deductions": args.other_deductions,
            },
        )
        payroll.raise_for_status()
    print("health=PASS")
    print("docs=PASS")
    print("login=PASS")
    print(f"payroll=PASS net_pay={payroll.json()['net_pay']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
