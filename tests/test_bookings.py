from datetime import UTC, datetime, timedelta
from uuid import uuid4

from tests.conftest import auth_headers, login, register, seed_centre_and_test


def make_user(client, email: str):
    """Register + login a fresh user. Returns auth headers."""
    assert register(client, email=email).status_code == 201
    return auth_headers(login(client, email=email).json()["access_token"])


def future_time(days: int = 2) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def create_booking(client, headers, centre_id, test_id, **overrides):
    payload = {
        "centre_id": centre_id,
        "test_id": test_id,
        "appointment_time": future_time(),
        **overrides,
    }
    return client.post("/bookings", json=payload, headers=headers)


class TestBookingCreation:
    def test_create_booking_success(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers, price="500.00")

        response = create_booking(client, headers, centre_id, test_id)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "PENDING"
        assert str(data["amount"]) in ("500.00", "500.0", "500")
        assert data["centre_id"] == centre_id
        assert data["test_id"] == test_id

    def test_price_determined_server_side(self, client):
        """A client-supplied amount must be ignored; the server snapshots the price."""
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers, price="750.00")

        response = create_booking(client, headers, centre_id, test_id, amount="1.00")
        assert response.status_code == 201
        assert str(response.json()["amount"]) in ("750.00", "750.0", "750")

    def test_create_booking_requires_auth(self, client):
        response = client.post(
            "/bookings",
            json={"centre_id": 1, "test_id": 1, "appointment_time": future_time()},
        )
        assert response.status_code == 401

    def test_invalid_centre(self, client):
        headers = make_user(client, "alice@example.com")
        _, test_id = seed_centre_and_test(client, headers)
        response = create_booking(client, headers, 9999, test_id)
        assert response.status_code == 404

    def test_invalid_test(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, _ = seed_centre_and_test(client, headers)
        response = create_booking(client, headers, centre_id, 9999)
        assert response.status_code == 404

    def test_test_not_offered_at_centre(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, _ = seed_centre_and_test(client, headers)
        # a second test that exists but is not associated with the centre
        other = client.post(
            "/diagnostics/tests",
            json={"code": "LFT", "name": "Liver Function Test"},
            headers=headers,
        )
        response = create_booking(client, headers, centre_id, other.json()["id"])
        assert response.status_code == 404
        assert "not offered" in response.json()["detail"]

    def test_past_appointment_rejected(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        response = create_booking(client, headers, centre_id, test_id, appointment_time=past)
        assert response.status_code == 422

    def test_naive_appointment_treated_as_utc(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        naive_future = (datetime.now(UTC) + timedelta(days=3)).replace(tzinfo=None).isoformat()
        response = create_booking(
            client, headers, centre_id, test_id, appointment_time=naive_future
        )
        assert response.status_code == 201


class TestBookingRetrieval:
    def test_get_own_booking(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        booking_id = create_booking(client, headers, centre_id, test_id).json()["id"]

        response = client.get(f"/bookings/{booking_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == booking_id

    def test_get_nonexistent_booking(self, client):
        headers = make_user(client, "alice@example.com")
        response = client.get(f"/bookings/{uuid4()}", headers=headers)
        assert response.status_code == 404

    def test_get_malformed_booking_id(self, client):
        headers = make_user(client, "alice@example.com")
        response = client.get("/bookings/not-a-uuid", headers=headers)
        assert response.status_code == 422

    def test_list_only_own_bookings(self, client):
        alice = make_user(client, "alice@example.com")
        bob = make_user(client, "bob@example.com")
        centre_id, test_id = seed_centre_and_test(client, alice)
        create_booking(client, alice, centre_id, test_id)
        create_booking(client, bob, centre_id, test_id)

        alice_list = client.get("/bookings", headers=alice).json()
        bob_list = client.get("/bookings", headers=bob).json()
        assert len(alice_list) == 1
        assert len(bob_list) == 1
        assert alice_list[0]["user_id"] != bob_list[0]["user_id"]


class TestBookingAuthorization:
    """The core authorization requirement: users must never access each other's bookings."""

    def test_bob_cannot_read_alices_booking(self, client):
        alice = make_user(client, "alice@example.com")
        bob = make_user(client, "bob@example.com")
        centre_id, test_id = seed_centre_and_test(client, alice)
        booking_id = create_booking(client, alice, centre_id, test_id).json()["id"]

        response = client.get(f"/bookings/{booking_id}", headers=bob)
        assert response.status_code == 404

    def test_bob_cannot_cancel_alices_booking(self, client):
        alice = make_user(client, "alice@example.com")
        bob = make_user(client, "bob@example.com")
        centre_id, test_id = seed_centre_and_test(client, alice)
        booking_id = create_booking(client, alice, centre_id, test_id).json()["id"]

        response = client.post(f"/bookings/{booking_id}/cancel", headers=bob)
        assert response.status_code == 404
        # and the booking is untouched
        still = client.get(f"/bookings/{booking_id}", headers=alice)
        assert still.json()["status"] == "PENDING"

    def test_bob_cannot_pay_for_alices_booking(self, client):
        alice = make_user(client, "alice@example.com")
        bob = make_user(client, "bob@example.com")
        centre_id, test_id = seed_centre_and_test(client, alice)
        booking_id = create_booking(client, alice, centre_id, test_id).json()["id"]

        response = client.post("/payments/", json={"booking_id": booking_id}, headers=bob)
        assert response.status_code == 404

    def test_unauthenticated_access_denied(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        booking_id = create_booking(client, headers, centre_id, test_id).json()["id"]

        assert client.get(f"/bookings/{booking_id}").status_code == 401
        assert client.get("/bookings").status_code == 401
        assert client.post(f"/bookings/{booking_id}/cancel").status_code == 401


class TestCancellation:
    def test_cancel_pending_booking(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        booking_id = create_booking(client, headers, centre_id, test_id).json()["id"]

        response = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
        assert response.status_code == 200
        assert response.json()["status"] == "CANCELLED"

    def test_cancel_twice_rejected(self, client):
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        booking_id = create_booking(client, headers, centre_id, test_id).json()["id"]

        assert client.post(f"/bookings/{booking_id}/cancel", headers=headers).status_code == 200
        second = client.post(f"/bookings/{booking_id}/cancel", headers=headers)
        assert second.status_code == 409

    def test_cancel_nonexistent_booking(self, client):
        headers = make_user(client, "alice@example.com")
        response = client.post(f"/bookings/{uuid4()}/cancel", headers=headers)
        assert response.status_code == 404


class TestNoStatusControl:
    def test_no_arbitrary_status_updates(self, client):
        """There is no client-facing endpoint that sets booking status directly."""
        headers = make_user(client, "alice@example.com")
        centre_id, test_id = seed_centre_and_test(client, headers)
        booking_id = create_booking(client, headers, centre_id, test_id).json()["id"]

        patch = client.patch(
            f"/bookings/{booking_id}", json={"status": "CONFIRMED"}, headers=headers
        )
        assert patch.status_code == 405  # method not allowed: route does not exist
        put = client.put(f"/bookings/{booking_id}", json={"status": "CONFIRMED"}, headers=headers)
        assert put.status_code == 405
