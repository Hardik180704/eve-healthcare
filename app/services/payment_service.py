import json
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.booking import Booking
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment, PaymentWebhookEvent
from app.models.user import User
from app.schemas.payment import PaymentCreate, WebhookEventIn, WebhookResult

logger = logging.getLogger("eve.payments")


def create_payment(db: Session, user: User, payload: PaymentCreate) -> Payment:
    """Initiate a payment for a booking owned by the authenticated user.

    The booking row is locked (SELECT ... FOR UPDATE) and its status is
    re-validated inside the transaction, so two concurrent payment attempts
    for the same booking cannot both succeed.
    """
    booking = db.execute(
        select(Booking).where(Booking.id == payload.booking_id).with_for_update()
    ).scalar_one_or_none()
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Booking not found")
    if booking.status != BookingStatus.PENDING:
        raise ConflictError(
            f"Payment is allowed only for PENDING bookings; booking is '{booking.status.value}'"
        )

    existing = db.execute(
        select(Payment).where(Payment.booking_id == booking.id)
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("A payment already exists for this booking")

    # Snapshot the booking amount; the client never sets amounts.
    payment = Payment(booking_id=booking.id, amount=booking.amount, status=PaymentStatus.PENDING)
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Unique constraint on payments.booking_id: a concurrent request for
        # the same booking won the race.
        db.rollback()
        raise ConflictError("A payment already exists for this booking") from None
    db.refresh(payment)
    logger.info(
        "payment initiated: id=%s booking_id=%s amount=%s", payment.id, booking.id, payment.amount
    )
    return payment


def _webhook_result(
    event_id: str, payment: Payment, booking: Booking, duplicate: bool, message: str
) -> WebhookResult:
    return WebhookResult(
        event_id=event_id,
        payment_id=payment.id,
        payment_status=payment.status,
        booking_status=booking.status.value,
        duplicate=duplicate,
        message=message,
    )


def process_webhook(db: Session, payload: WebhookEventIn) -> WebhookResult:
    """Apply a gateway webhook event exactly once, transactionally.

    Concurrency safety:
    - The payment row is locked with SELECT ... FOR UPDATE, so two concurrent
      events for the same payment are serialized.
    - The event row is inserted inside the same transaction; the UNIQUE
      constraint on payment_webhook_events.event_id makes duplicate deliveries
      fail the insert, which is translated into an idempotent no-op.
    """
    payment = db.execute(
        select(Payment).where(Payment.id == payload.payment_id).with_for_update()
    ).scalar_one_or_none()
    if payment is None:
        raise NotFoundError("Payment not found")

    event = PaymentWebhookEvent(
        event_id=payload.event_id,
        payment_id=payment.id,
        status=payload.status.value,
        payload=json.loads(payload.model_dump_json()),
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Duplicate delivery: the event was already recorded under this
        # event_id. Replay the same verdict the first delivery produced so the
        # response for an event_id is deterministic.
        fresh_payment = db.execute(
            select(Payment).where(Payment.id == payload.payment_id).with_for_update()
        ).scalar_one()
        recorded = db.execute(
            select(PaymentWebhookEvent).where(PaymentWebhookEvent.event_id == payload.event_id)
        ).scalar_one()
        fresh_booking = db.get(Booking, fresh_payment.booking_id)
        if recorded.status != fresh_payment.status.value:
            raise ConflictError(
                f"Event status '{recorded.status}' conflicts with payment state "
                f"'{fresh_payment.status.value}'"
            ) from None
        logger.info(
            "duplicate webhook ignored: event_id=%s payment_id=%s",
            payload.event_id,
            payload.payment_id,
        )
        return _webhook_result(
            payload.event_id, fresh_payment, fresh_booking, True, "Duplicate event ignored"
        )

    booking = db.execute(
        select(Booking).where(Booking.id == payment.booking_id).with_for_update()
    ).scalar_one()

    if payload.amount.quantize(Decimal("0.01")) != payment.amount.quantize(Decimal("0.01")):
        db.commit()  # keep the event for audit; no state change
        logger.warning(
            "webhook amount mismatch: event_id=%s payment_id=%s", payload.event_id, payment.id
        )
        raise ConflictError("Webhook amount does not match the payment amount")

    if payment.status == PaymentStatus.PENDING:
        if booking.status != BookingStatus.PENDING:
            db.commit()  # keep the event for audit; no state change
            raise ConflictError(
                f"Booking is '{booking.status.value}'; payment outcome cannot be applied"
            )
        payment.status = payload.status
        booking.status = (
            BookingStatus.CONFIRMED
            if payload.status == PaymentStatus.SUCCESS
            else BookingStatus.FAILED
        )
        db.commit()
        logger.info(
            "webhook applied: event_id=%s payment_id=%s payment=%s booking=%s",
            payload.event_id,
            payment.id,
            payment.status.value,
            booking.status.value,
        )
        return _webhook_result(
            payload.event_id, payment, booking, False, "Event processed; booking updated"
        )

    if payment.status == payload.status:
        # Same outcome reported again under a new event id: benign, no change.
        db.commit()
        return _webhook_result(
            payload.event_id, payment, booking, False, "Payment already in this state; no change"
        )

    # Conflicting outcome (e.g. FAILED event for an already-SUCCESS payment).
    db.commit()  # keep the event for audit; no state change
    logger.warning(
        "conflicting webhook: event_id=%s payment_id=%s current=%s got=%s",
        payload.event_id,
        payment.id,
        payment.status.value,
        payload.status.value,
    )
    raise ConflictError(
        f"Event status '{payload.status.value}' conflicts with payment state "
        f"'{payment.status.value}'"
    )
