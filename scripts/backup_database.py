import argparse
import sqlite3
import os
import shutil
import subprocess
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path

from app.database import engine


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the configured database.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--restore", action="store_true", help="Restore a PostgreSQL dump to --restore-database.")
    parser.add_argument("--restore-database", help="Disposable PostgreSQL database URL for restore verification.")
    parser.add_argument("--dump", type=Path, help="PostgreSQL dump file to restore.")
    args = parser.parse_args()

    if engine.dialect.name == "postgresql":
        for executable in ("pg_dump", "pg_restore", "psql"):
            if shutil.which(executable) is None:
                raise RuntimeError(f"PostgreSQL tool is unavailable: {executable}")
        url = urlparse(str(engine.url).replace("postgresql+psycopg2://", "postgresql://"))
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if args.restore:
            if not args.restore_database or not args.dump:
                raise RuntimeError("--restore-database and --dump are required for restore.")
            restore_url = urlparse(args.restore_database)
            env = os.environ.copy()
            if restore_url.password:
                env["PGPASSWORD"] = restore_url.password
            subprocess.run(
                [
                    "pg_restore", "--clean", "--if-exists",
                    "--host", restore_url.hostname or "localhost",
                    "--port", str(restore_url.port or 5432),
                    "--username", restore_url.username or "",
                    "--dbname", restore_url.path.lstrip("/"),
                    str(args.dump),
                ],
                env=env,
                check=True,
            )
            print("PostgreSQL restore completed.")
            return
        backup_path = args.output_dir / f"ledgerforge-{stamp}.dump"
        env = os.environ.copy()
        if url.password:
            env["PGPASSWORD"] = url.password
        subprocess.run(
            [
                "pg_dump",
                "--format=custom",
                "--file", str(backup_path),
                "--host", url.hostname or "localhost",
                "--port", str(url.port or 5432),
                "--username", url.username or "",
                "--dbname", url.path.lstrip("/"),
            ],
            env=env,
            check=True,
        )
        print(backup_path)
        return

    if engine.dialect.name != "sqlite":
        raise RuntimeError("Unsupported database engine.")
    database_path = Path(engine.url.database).resolve()
    if not database_path.is_file():
        raise FileNotFoundError(database_path)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = args.output_dir / f"ledgerforge-{stamp}.db"
    with sqlite3.connect(database_path) as source:
        with sqlite3.connect(backup_path) as destination:
            source.backup(destination)
    print(backup_path)


if __name__ == "__main__":
    main()
