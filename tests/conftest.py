"""Test configuration.

The DATABASE_URL environment variable is set to a dedicated test database
BEFORE any application module is imported, so the app and Alembic both use it.
Migrations are applied to the test database on every test session, which also
keeps the migrations themselves continuously verified.
"""

import os

TEST_DB_NAME = "eve_healthcare_test"
TEST_DB_URL = "postgresql+psycopg://eve:eve_password@localhost:5432/eve_healthcare_test"
ADMIN_DB_URL = "postgresql+psycopg://eve:eve_password@localhost:5432/postgres"

os.environ["DATABASE_URL"] = TEST_DB_URL

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.database import Base, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402

TRUNCATE_SQL = text(
    "TRUNCATE TABLE payment_webhook_events, payments, bookings, centre_tests, "
    "diagnostic_tests, diagnostic_centres, users RESTART IDENTITY CASCADE"
)


@pytest.fixture(scope="session", autouse=True)
def test_database():
    """Drop, recreate and migrate a clean test database for the session."""
    admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin_engine.dispose()

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    yield


@pytest.fixture(autouse=True)
def clean_tables(test_database):
    """Empty every table after each test so tests are fully isolated."""
    yield
    with engine.begin() as conn:
        conn.execute(TRUNCATE_SQL)


@pytest.fixture
def client():
    def override_get_db():
        from app.core.database import SessionLocal

        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- shared helpers -----------------------------------------------------------


def register(client: TestClient, email: str = "alice@example.com", password: str = "secret123"):
    return client.post(
        "/auth/signup",
        json={"full_name": "Alice Example", "email": email, "password": password},
    )


def login(client: TestClient, email: str = "alice@example.com", password: str = "secret123"):
    return client.post("/auth/login", json={"email": email, "password": password})


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def alice(client):
    """A registered, logged-in user. Returns (auth_headers, user_id)."""
    response = register(client)
    assert response.status_code == 201, response.text
    user = response.json()
    token = login(client).json()["access_token"]
    return auth_headers(token), user["id"]


def seed_centre_and_test(client: TestClient, headers: dict[str, str], price="500.00"):
    """Create one centre, one test, and associate them. Returns (centre_id, test_id)."""
    centre = client.post(
        "/diagnostics/centres",
        json={"name": "Test Centre", "address": "1 Main St", "city": "Pune"},
        headers=headers,
    )
    assert centre.status_code == 201, centre.text
    test = client.post(
        "/diagnostics/tests",
        json={"code": "CBC", "name": "Complete Blood Count", "description": None},
        headers=headers,
    )
    assert test.status_code == 201, test.text
    link = client.post(
        f"/diagnostics/centres/{centre.json()['id']}/tests",
        json={"test_id": test.json()["id"], "price": price},
        headers=headers,
    )
    assert link.status_code == 201, link.text
    return centre.json()["id"], test.json()["id"]


# keep Base imported for Alembic autogenerate parity checks in future revisions
_ = Base
