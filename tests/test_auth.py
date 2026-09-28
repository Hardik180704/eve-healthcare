from datetime import UTC, datetime, timedelta

from app.core import security
from tests.conftest import auth_headers, login, register


class TestSignup:
    def test_signup_success(self, client):
        response = register(client)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "alice@example.com"
        assert data["full_name"] == "Alice Example"
        assert "id" in data
        # the password hash must never appear in any response
        assert "password" not in data
        assert "password_hash" not in data

    def test_duplicate_signup_rejected(self, client):
        assert register(client).status_code == 201
        response = register(client, email="alice@example.com")
        assert response.status_code == 409

    def test_duplicate_signup_case_insensitive(self, client):
        assert register(client).status_code == 201
        response = register(client, email="ALICE@example.com")
        assert response.status_code == 409

    def test_signup_invalid_email(self, client):
        response = client.post(
            "/auth/signup",
            json={"full_name": "X", "email": "not-an-email", "password": "secret123"},
        )
        assert response.status_code == 422

    def test_signup_short_password(self, client):
        response = register(client, password="short")
        assert response.status_code == 422

    def test_signup_missing_fields(self, client):
        response = client.post("/auth/signup", json={"email": "x@example.com"})
        assert response.status_code == 422


class TestLogin:
    def test_login_success(self, client):
        assert register(client).status_code == 201
        response = login(client)
        assert response.status_code == 200
        data = response.json()
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_wrong_password(self, client):
        assert register(client).status_code == 201
        response = login(client, password="wrongpassword")
        assert response.status_code == 401

    def test_login_unknown_email(self, client):
        response = login(client, email="nobody@example.com")
        assert response.status_code == 401

    def test_login_email_case_insensitive(self, client):
        assert register(client).status_code == 201
        response = login(client, email="ALICE@example.com")
        assert response.status_code == 200


class TestMe:
    def test_me_with_valid_token(self, client):
        assert register(client).status_code == 201
        token = login(client).json()["access_token"]
        response = client.get("/auth/me", headers=auth_headers(token))
        assert response.status_code == 200
        assert response.json()["email"] == "alice@example.com"

    def test_me_without_token(self, client):
        assert client.get("/auth/me").status_code == 401

    def test_me_with_garbage_token(self, client):
        assert client.get("/auth/me", headers=auth_headers("garbage.token.here")).status_code == 401

    def test_me_with_expired_token(self, client, monkeypatch):
        assert register(client).status_code == 201
        monkeypatch.setattr(security.settings, "access_token_expire_minutes", -1)
        expired = security.create_access_token("00000000-0000-0000-0000-000000000000")
        response = client.get("/auth/me", headers=auth_headers(expired))
        assert response.status_code == 401

    def test_me_with_token_for_deleted_user(self, client):
        assert register(client).status_code == 201
        token = login(client).json()["access_token"]
        # remove the user directly from the database
        from sqlalchemy import delete

        from app.core.database import SessionLocal
        from app.models.user import User

        with SessionLocal() as db:
            db.execute(delete(User).where(User.email == "alice@example.com"))
            db.commit()
        response = client.get("/auth/me", headers=auth_headers(token))
        assert response.status_code == 401


class TestJWTFormat:
    def test_token_contains_subject_and_expiry(self, client):
        assert register(client).status_code == 201
        token = login(client).json()["access_token"]
        payload = security.jwt.decode(
            token,
            security.settings.jwt_secret_key,
            algorithms=[security.settings.jwt_algorithm],
        )
        assert "sub" in payload
        assert "exp" in payload
        assert payload["exp"] > datetime.now(UTC).timestamp()

    def test_token_valid_for_configured_lifetime(self, client):
        assert register(client).status_code == 201
        before = datetime.now(UTC)
        token = login(client).json()["access_token"]
        payload = security.jwt.decode(
            token,
            security.settings.jwt_secret_key,
            algorithms=[security.settings.jwt_algorithm],
        )
        expected = before + timedelta(minutes=security.settings.access_token_expire_minutes)
        assert abs(payload["exp"] - expected.timestamp()) < 5
