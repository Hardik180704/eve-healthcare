import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.enums import PaymentStatus
from app.models.payment import Payment, PaymentWebhookEvent
from tests.conftest import auth_headers, login, register, seed_centre_and_test


def make_user(client, email: str):
    assert register(client, email=email).status_code == 201
    return auth_headers(login(client, email=email).json()["access_token"])


def make_booking(client, headers, price="500.00") -> dict:
    centre_id, test_id = seed_centre_and_test(client, headers, price=price)
    appointment = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    response = client.post(
        "/bookings",
        json={"centre_id": centre_id, "test_id": test_id, "appointment_time": appointment},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_pending_payment(client, headers, price="500.00") -> dict:
    booking = make_booking(client, headers, price=price)
    response = client.post("/payments/", json={"booking_id": booking["id"]}, headers=headers)
    assert response.status_code == 201, response.text
    payment = response.json()
    # Deterministic simulation: odd payment ids succeed, even ids fail.
    payment["expected_outcome"] = "SUCCESS" if payment["id"] % 2 == 1 else "FAILED"
    return payment


def deliver_webhook(client, payment, outcome=None, event_id=None, amount=None, **overrides):
    payload = {
        "event_id": event_id or str(uuid4()),
        "payment_id": payment["id"],
        "status": outcome or payment["expected_outcome"],
        "amount": amount if amount is not None else payment.get("amount", "500.00"),
        **overrides,
    }
    return client.post("/payments/webhook", json=payload), payload


class TestPaymentCreation:
    def test_create_payment_pending(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        assert payment["status"] == "PENDING"
        assert str(payment["amount"]) in ("500.00", "500.0", "500")

    def test_create_payment_requires_auth(self, client):
        response = client.post("/payments/", json={"booking_id": str(uuid4())})
        assert response.status_code == 401

    def test_payment_for_nonexistent_booking(self, client):
        headers = make_user(client, "alice@example.com")
        response = client.post("/payments/", json={"booking_id": str(uuid4())}, headers=headers)
        assert response.status_code == 404

    def test_payment_for_another_users_booking(self, client):
        alice = make_user(client, "alice@example.com")
        bob = make_user(client, "bob@example.com")
        booking = make_booking(client, alice)
        response = client.post("/payments/", json={"booking_id": booking["id"]}, headers=bob)
        assert response.status_code == 404

    def test_duplicate_payment_rejected(self, client):
        headers = make_user(client, "alice@example.com")
        booking = make_booking(client, headers)
        first = client.post("/payments/", json={"booking_id": booking["id"]}, headers=headers)
        assert first.status_code == 201
        second = client.post("/payments/", json={"booking_id": booking["id"]}, headers=headers)
        assert second.status_code == 409

    def test_payment_for_cancelled_booking_rejected(self, client):
        headers = make_user(client, "alice@example.com")
        booking = make_booking(client, headers)
        assert client.post(f"/bookings/{booking['id']}/cancel", headers=headers).status_code == 200
        response = client.post("/payments/", json={"booking_id": booking["id"]}, headers=headers)
        assert response.status_code == 409

    def test_cannot_cancel_booking_with_pending_payment(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        response = client.post(f"/bookings/{payment['booking_id']}/cancel", headers=headers)
        assert response.status_code == 409

    def test_concurrent_payments_only_one_wins(self, client):
        """Two simultaneous payment attempts for one booking: exactly one 201."""
        headers = make_user(client, "alice@example.com")
        booking = make_booking(client, headers)
        results: list = []

        def attempt():
            local_client = type(client)(client.app)
            results.append(
                local_client.post("/payments/", json={"booking_id": booking["id"]}, headers=headers)
            )

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        statuses = sorted(r.status_code for r in results)
        assert statuses == [201, 409], [r.text for r in results]


class TestPaymentWebhook:
    def test_successful_payment_confirms_booking(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)

        response, _ = deliver_webhook(client, payment, outcome="SUCCESS")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["payment_status"] == "SUCCESS"
        assert data["booking_status"] == "CONFIRMED"
        assert data["duplicate"] is False

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "CONFIRMED"

    def test_failed_payment_fails_booking(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)

        response, _ = deliver_webhook(client, payment, outcome="FAILED")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["payment_status"] == "FAILED"
        assert data["booking_status"] == "FAILED"

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "FAILED"
        # a failed booking is terminal: cancellation is rejected
        cancel = client.post(f"/bookings/{payment['booking_id']}/cancel", headers=headers)
        assert cancel.status_code == 409

    def test_webhook_for_unknown_payment(self, client):
        response, _ = deliver_webhook(client, {"id": 999999, "expected_outcome": "SUCCESS"})
        assert response.status_code == 404

    def test_webhook_amount_mismatch_rejected(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers, price="500.00")

        response, payload = deliver_webhook(client, payment, amount="999.00")
        assert response.status_code == 409
        # state unchanged
        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "PENDING"
        # but the event is recorded for audit
        with SessionLocal() as db:
            events = db.scalars(
                select(PaymentWebhookEvent).where(
                    PaymentWebhookEvent.event_id == payload["event_id"]
                )
            ).all()
            assert len(events) == 1

    def test_webhook_malformed_payloads(self, client):
        for bad in [
            {"payment_id": 1, "status": "SUCCESS", "amount": "500.00"},  # missing event_id
            {"event_id": "e1", "payment_id": 1, "amount": "500.00"},  # missing status
            {"event_id": "e1", "status": "SUCCESS", "amount": "500.00"},  # missing payment_id
            {"event_id": "e1", "payment_id": "abc", "status": "SUCCESS", "amount": "1.00"},
            {"event_id": "e1", "payment_id": 1, "status": "MAYBE", "amount": "1.00"},
            {"event_id": "   ", "payment_id": 1, "status": "SUCCESS", "amount": "1.00"},
            {"event_id": "e1", "payment_id": 1, "status": "SUCCESS", "amount": "-5"},
        ]:
            response = client.post("/payments/webhook", json=bad)
            assert response.status_code == 422, f"{bad} -> {response.status_code}"


class TestWebhookIdempotency:
    def test_same_webhook_delivered_repeatedly(self, client):
        """The same event delivered three times changes state exactly once."""
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)

        responses = []
        for _ in range(3):
            response, payload = deliver_webhook(client, payment, event_id="evt-fixed-1")
            responses.append(response)

        assert all(r.status_code == 200 for r in responses)
        first, second, third = (r.json() for r in responses)
        assert first["duplicate"] is False
        assert second["duplicate"] is True
        assert third["duplicate"] is True
        assert first["payment_status"] == "SUCCESS"
        assert second["payment_status"] == "SUCCESS"
        assert third["payment_status"] == "SUCCESS"

        with SessionLocal() as db:
            events = db.scalars(
                select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == "evt-fixed-1")
            ).all()
            assert len(events) == 1
            payments = db.scalars(select(Payment)).all()
            assert len(payments) == 1

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "CONFIRMED"

    def test_repeated_failed_webhook_keeps_state(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)

        for i in range(3):
            response, _ = deliver_webhook(client, payment, outcome="FAILED", event_id=f"evt-f{i}")
            if i == 0:
                assert response.json()["payment_status"] == "FAILED"
            else:
                assert response.json()["payment_status"] == "FAILED"
                assert response.json()["message"] != ""

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "FAILED"

    def test_conflicting_webhook_rejected_and_state_preserved(self, client):
        """FAILED event for an already-SUCCESS payment must not corrupt state."""
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)

        success, _ = deliver_webhook(client, payment, outcome="SUCCESS", event_id="evt-s1")
        assert success.status_code == 200

        conflict, payload = deliver_webhook(client, payment, outcome="FAILED", event_id="evt-f1")
        assert conflict.status_code == 409

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "CONFIRMED"

        # retrying the conflicting event is still a conflict (event already recorded)
        retry, _ = deliver_webhook(client, payment, outcome="FAILED", event_id="evt-f1")
        assert retry.status_code == 409

    def test_conflicting_webhook_on_failed_payment(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        failed, _ = deliver_webhook(client, payment, outcome="FAILED", event_id="evt-f1")
        assert failed.status_code == 200

        conflict, _ = deliver_webhook(client, payment, outcome="SUCCESS", event_id="evt-s1")
        assert conflict.status_code == 409
        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "FAILED"

    def test_benign_duplicate_outcome_new_event_id(self, client):
        """Same outcome under a new event id: 200, no state change, event recorded."""
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        assert deliver_webhook(client, payment, event_id="evt-1")[0].status_code == 200

        response, payload = deliver_webhook(client, payment, event_id="evt-2")
        assert response.status_code == 200
        assert response.json()["duplicate"] is False

        with SessionLocal() as db:
            count = len(
                db.scalars(
                    select(PaymentWebhookEvent).where(
                        PaymentWebhookEvent.payment_id == payment["id"]
                    )
                ).all()
            )
            assert count == 2

    def test_concurrent_duplicate_webhooks(self, client):
        """The same event delivered concurrently: processed exactly once."""
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        responses: list = []

        def deliver():
            local_client = type(client)(client.app)
            r, _ = deliver_webhook(local_client, payment, event_id="evt-concurrent")
            responses.append(r.status_code)

        threads = [threading.Thread(target=deliver) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert responses.count(200) == 3
        with SessionLocal() as db:
            events = db.scalars(
                select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == "evt-concurrent")
            ).all()
            assert len(events) == 1

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        assert booking["status"] == "CONFIRMED"

    def test_concurrent_conflicting_webhooks(self, client):
        """SUCCESS and FAILED delivered concurrently: exactly one transition wins."""
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        results: list = []

        def deliver(outcome):
            local_client = type(client)(client.app)
            r, _ = deliver_webhook(local_client, payment, outcome=outcome)
            results.append((outcome, r.status_code))

        threads = [
            threading.Thread(target=deliver, args=("SUCCESS",)),
            threading.Thread(target=deliver, args=("FAILED",)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        booking = client.get(f"/bookings/{payment['booking_id']}", headers=headers).json()
        # both requests are handled, but exactly one transition wins
        assert sorted(code for _, code in results) == [200, 409], results
        assert booking["status"] in ("CONFIRMED", "FAILED")

        # booking status and payment status must agree
        with SessionLocal() as db:
            row = db.get(Payment, payment["id"])
            assert (row.status.value == "SUCCESS" and booking["status"] == "CONFIRMED") or (
                row.status.value == "FAILED" and booking["status"] == "FAILED"
            )


class TestEndToEnd:
    def test_full_booking_payment_flow(self, client):
        headers = make_user(client, "alice@example.com")
        booking = make_booking(client, headers, price="750.00")

        payment = client.post(
            "/payments/", json={"booking_id": booking["id"]}, headers=headers
        ).json()
        assert payment["status"] == "PENDING"
        assert str(payment["amount"]) in ("750.00", "750.0", "750")

        outcome = "SUCCESS" if payment["id"] % 2 == 1 else "FAILED"
        response, _ = deliver_webhook(client, payment, outcome=outcome)
        assert response.status_code == 200

        final = client.get(f"/bookings/{booking['id']}", headers=headers).json()
        assert final["status"] == ("CONFIRMED" if outcome == "SUCCESS" else "FAILED")

    def test_duplicate_webhook_does_not_duplicate_payment(self, client):
        headers = make_user(client, "alice@example.com")
        payment = make_pending_payment(client, headers)
        for _ in range(5):
            deliver_webhook(client, payment, event_id="evt-once")

        with SessionLocal() as db:
            payments = db.scalars(
                select(Payment).where(Payment.booking_id == payment["booking_id"])
            ).all()
            assert len(payments) == 1
            assert payments[0].status == PaymentStatus.SUCCESS
