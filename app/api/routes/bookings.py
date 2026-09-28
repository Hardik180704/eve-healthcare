from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.booking import BookingCreate, BookingOut
from app.services import booking_service

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post(
    "",
    response_model=BookingOut,
    status_code=201,
    summary="Book a diagnostic test at a centre",
    description=(
        "Creates a booking for the authenticated user. The price is determined "
        "server-side from the centre/test association and snapshotted onto the "
        "booking; the initial status is PENDING."
    ),
)
def create_booking(
    payload: BookingCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return booking_service.create_booking(db, user, payload)


@router.get(
    "",
    response_model=list[BookingOut],
    summary="List the authenticated user's bookings",
)
def list_bookings(
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return booking_service.list_bookings(db, user)


@router.get(
    "/{booking_id}",
    response_model=BookingOut,
    summary="Get one of the authenticated user's bookings",
    description="Returns 404 both for unknown IDs and for bookings owned by other users.",
)
def get_booking(
    booking_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return booking_service.get_booking_owned_or_404(db, user, booking_id)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Cancel a pending booking",
    description=(
        "Only PENDING bookings can be cancelled. Bookings with a payment in "
        "progress cannot be cancelled."
    ),
)
def cancel_booking(
    booking_id: UUID,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return booking_service.cancel_booking(db, user, booking_id)
