import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Department


@pytest.fixture
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
    )
    Base.metadata.create_all(test_engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with testing_session() as db:
        for number in range(1, 12):
            db.add(
                Department(
                    department_id=f"D{number:02}",
                    department_name=f"Department {number}",
                    cost_center=f"CC{number:02}",
                    description=None,
                )
            )
        db.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_departments_and_unknown_id(client):
    response = client.get("/departments")
    assert response.status_code == 200
    assert len(response.json()) == 11
    assert client.get("/departments/D99").status_code == 404
