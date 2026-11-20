import os
import subprocess
import sys


def main() -> None:
    required = ("DATABASE_URL", "SECRET_KEY")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing required deployment environment variables: "
            + ", ".join(missing)
        )
    if len(os.environ["SECRET_KEY"].encode("utf-8")) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 UTF-8 bytes.")

    port = os.environ.get("PORT", "8000")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise RuntimeError("PORT must be an integer between 1 and 65535.")

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
    )
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
        ],
    )


if __name__ == "__main__":
    main()
