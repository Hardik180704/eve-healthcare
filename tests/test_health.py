from fastapi.testclient import TestClient


class TestHealth:
    def test_health_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "connected"}

    def test_openapi_docs_served(self, client):
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    def test_openapi_lists_all_routes(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for expected in (
            "/auth/signup",
            "/auth/login",
            "/auth/me",
            "/diagnostics/centres",
            "/diagnostics/centres/{centre_id}",
            "/diagnostics/centres/{centre_id}/tests",
            "/diagnostics/tests",
            "/bookings",
            "/bookings/{booking_id}",
            "/bookings/{booking_id}/cancel",
            "/payments",
            "/payments/webhook",
        ):
            assert expected in paths, f"{expected} missing from OpenAPI"

    def test_unknown_route_is_json_404(self, client):
        response = client.get("/nope")
        assert response.status_code == 404
        assert response.json()["detail"] == "Not Found"

    def test_unhandled_errors_do_not_leak_internals(self, client):
        from app.core.database import get_db
        from app.main import app

        def broken_db():
            raise RuntimeError("secret internal database detail xyz")

        app.dependency_overrides[get_db] = broken_db
        try:
            raising_disabled = TestClient(app, raise_server_exceptions=False)
            response = raising_disabled.get("/diagnostics/centres")
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert "xyz" not in response.text
