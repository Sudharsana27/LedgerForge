import argparse
import json
from pathlib import Path

from app.config import settings
from app.database import SessionLocal
from app.payroll_batch import run_batch_validation


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate independently sourced payroll rows and compare "
            "successful results with payroll_items.csv."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(settings.data_dir),
        help="Directory containing payroll_runs.csv and payroll_items.csv.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="New or empty directory for validation outputs.",
    )
    parser.add_argument(
        "--payroll-inputs",
        type=Path,
        help=(
            "Optional independent payroll_inputs.csv. If omitted, this file "
            "is read from --data-dir when present."
        ),
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        summary = run_batch_validation(
            db,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            payroll_inputs_path=args.payroll_inputs,
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
