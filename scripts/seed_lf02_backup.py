
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, update

from app.config import settings
from app.database import Base, engine
from app import models


DATA_DIR = Path(settings.data_dir).resolve()

TABLES = [
    ("departments", models.Department),
    ("roles", models.Role),
    ("employees", models.Employee),
    ("employee_assignments", models.EmployeeAssignment),
]

DATE_COLUMNS = {
    "departments": [],
    "roles": [],
    "employees": [
        "date_of_birth",
        "hire_date",
        "exit_date",
        "resignation_date",
        "created_at",
    ],
    "employee_assignments": ["effective_from", "effective_to"],
}


def read_csv(table_name):
    path = DATA_DIR / f"{table_name}.csv"

    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")

    df = pd.read_csv(path)

    for column in DATE_COLUMNS[table_name]:
        df[column] = pd.to_datetime(
            df[column], errors="coerce"
        ).dt.date

    records = df.to_dict(orient="records")

    # Convert pandas NaN/NaT values to Python None.
    clean_records = []

    for record in records:
        clean = {}

        for key, value in record.items():
            if pd.isna(value):
                clean[key] = None
            elif hasattr(value, "item"):
                clean[key] = value.item()
            else:
                clean[key] = value

        clean_records.append(clean)

    return clean_records


def main():
    Base.metadata.create_all(engine)

    # Read every CSV before changing the database.
    datasets = {
        name: read_csv(name)
        for name, _ in TABLES
    }

    # Clear only these four tables, child tables first.
    with engine.begin() as connection:
        for name, model in reversed(TABLES):
            connection.execute(delete(model.__table__))

    # Insert parent tables before child tables.
    for name, model in TABLES:
        records = datasets[name]
        table = model.__table__

        if name == "employees":
            # Insert employees first, then restore manager links.
            records_to_insert = [
                {**record, "manager_id": None}
                for record in records
            ]
        else:
            records_to_insert = records

        with engine.begin() as connection:
            if records_to_insert:
                connection.execute(
                    insert(table), records_to_insert
                )

        print(f"Seeded {len(records)} rows into {name}")

        if name == "employees":
            manager_links = [
                (record["employee_id"], record["manager_id"])
                for record in records
                if record["manager_id"] is not None
            ]

            with engine.begin() as connection:
                for employee_id, manager_id in manager_links:
                    connection.execute(
                        update(table)
                        .where(table.c.employee_id == employee_id)
                        .values(manager_id=manager_id)
                    )

    print("\nFour-table seed completed successfully.")


if __name__ == "__main__":
    main()
