import argparse
import getpass
import os
import sys
from pathlib import Path

import httpx


def run_smoke_test(
    args: argparse.Namespace,
    client: httpx.Client,
    password: str,
) -> None:
    base_url = args.base_url.rstrip("/")
    health = client.get(f"{base_url}/api/v1/health")
    health.raise_for_status()
    if health.json().get("status") != "ok":
        raise RuntimeError("Health check did not report ok")
    docs = client.get(f"{base_url}/docs")
    docs.raise_for_status()
    demo_ui = client.get(f"{base_url}/demo/")
    demo_ui.raise_for_status()
    login = client.post(
        f"{base_url}/api/v1/auth/login",
        json={"username": args.username, "password": password},
    )
    login.raise_for_status()
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    payroll = client.post(
        f"{base_url}/api/v1/payroll/calculate",
        headers=headers,
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
    if "net_pay" not in payroll.json():
        raise RuntimeError("Payroll response did not contain the expected result.")

    if args.run_id:
        payslip = client.get(
            f"{base_url}/api/v1/payslips/{args.employee_id}/{args.run_id}",
            headers=headers,
        )
        payslip.raise_for_status()
        if payslip.headers.get("content-type", "").split(";")[0] != "application/pdf":
            raise RuntimeError("Payslip response was not a PDF.")
        if args.payslip_output is not None:
            args.payslip_output.write_bytes(payslip.content)


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
    parser.add_argument(
        "--run-id",
        help="optional existing payroll run for an authorized payslip check",
    )
    parser.add_argument(
        "--payslip-output",
        type=Path,
        help="optional local path to save the returned payslip PDF",
    )
    args = parser.parse_args()
    if args.payslip_output is not None and not args.run_id:
        parser.error("--payslip-output requires --run-id")
    password = os.environ.get(args.password_env) or getpass.getpass(
        "LedgerForge password: "
    )

    with httpx.Client(timeout=20.0) as client:
        run_smoke_test(args, client, password)

    print("health=PASS")
    print("docs=PASS")
    print("demo_ui=PASS")
    print("login=PASS")
    print("payroll=PASS")
    if args.run_id:
        print("payslip=PASS")
        if args.payslip_output is not None:
            print(f"payslip_saved={args.payslip_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
