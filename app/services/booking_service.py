import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.booking import Booking
from app.models.diagnostic import CentreTest, DiagnosticCentre, DiagnosticTest
from app.models.enums import BookingStatus, PaymentStatus
from app.models.payment import Payment
from app.models.user import User
from app.schemas.booking import BookingCreate

logger = logging.getLogger("eve.bookings")


def get_booking_owned_or_404(db: Session, user: User, booking_id: UUID) -> Booking:
    """Fetch a booking owned by the user.

    A booking that does not exist and one owned by somebody else return the
    same 404, so booking IDs cannot be enumerated.
    """
    booking = db.get(Booking, booking_id)
    if booking is None or booking.user_id != user.id:
        raise NotFoundError("Booking not found")
    return booking


def create_booking(db: Session, user: User, payload: BookingCreate) -> Booking:
    centre = db.get(DiagnosticCentre, payload.centre_id)
    if centre is None:
        raise NotFoundError("Diagnostic centre not found")

    test = db.get(DiagnosticTest, payload.test_id)
    if test is None:
        raise NotFoundError("Diagnostic test not found")

    # The price always comes from the centre/test association, never from the client.
    centre_test = db.execute(
        select(CentreTest).where(CentreTest.centre_id == centre.id, CentreTest.test_id == test.id)
    ).scalar_one_or_none()
    if centre_test is None:
        raise NotFoundError(f"Test '{test.name}' is not offered at centre '{centre.name}'")

    booking = Booking(
        user_id=user.id,
        centre_id=centre.id,
        test_id=test.id,
        appointment_time=payload.appointment_time,
        amount=centre_test.price,
        status=BookingStatus.PENDING,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    logger.info(
        "booking created: id=%s user_id=%s centre=%s test=%s amount=%s",
        booking.id,
        user.id,
        centre.id,
        test.id,
        booking.amount,
    )
    return booking


def list_bookings(db: Session, user: User) -> list[Booking]:
    return db.scalars(
        select(Booking).where(Booking.user_id == user.id).order_by(Booking.created_at.desc())
    ).all()


def cancel_booking(db: Session, user: User, booking_id: UUID) -> Booking:
    booking = get_booking_owned_or_404(db, user, booking_id)
    if booking.status != BookingStatus.PENDING:
        raise ConflictError(f"Booking cannot be cancelled from status '{booking.status.value}'")
    pending_payment = db.execute(
        select(Payment).where(
            Payment.booking_id == booking.id, Payment.status == PaymentStatus.PENDING
        )
    ).scalar_one_or_none()
    if pending_payment is not None:
        raise ConflictError("Cannot cancel a booking while its payment is in progress")

    booking.status = BookingStatus.CANCELLED
    db.commit()
    db.refresh(booking)
    logger.info("booking cancelled: id=%s user_id=%s", booking.id, user.id)
    return booking
