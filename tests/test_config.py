import pytest

from app.config import normalize_database_url
from scripts.start_api import main as start_api


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "postgres://user:password@db.example:5432/ledger",
            "postgresql+psycopg2://user:password@db.example:5432/ledger",
        ),
        (
            "postgresql://user:password@db.example:5432/ledger",
            "postgresql+psycopg2://user:password@db.example:5432/ledger",
        ),
        (
            "postgresql+psycopg://user:password@db.example:5432/ledger",
            "postgresql+psycopg://user:password@db.example:5432/ledger",
        ),
        ("sqlite:///./ledgerforge.db", "sqlite:///./ledgerforge.db"),
    ],
)
def test_normalize_database_url(source, expected):
    assert normalize_database_url(source) == expected


def test_startup_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "s" * 40)

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        start_api()


def test_startup_rejects_short_secret_before_migrating(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "short")

    with pytest.raises(RuntimeError, match="at least 32"):
        start_api()


def test_startup_rejects_invalid_port_before_migrating(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("SECRET_KEY", "s" * 40)
    monkeypatch.setenv("PORT", "70000")

    with pytest.raises(RuntimeError, match="PORT must be"):
        start_api()
