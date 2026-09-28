from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.schemas.payment import PaymentCreate, PaymentOut, WebhookEventIn, WebhookResult
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentOut,
    status_code=201,
    summary="Initiate payment for a booking",
    description=(
        "Creates a payment (status PENDING) for one of the authenticated user's "
        "PENDING bookings. Exactly one payment attempt is allowed per booking. "
        "\n\nThe simulated gateway decides the outcome deterministically from the "
        "payment id: odd ids are approved (SUCCESS), even ids are declined (FAILED). "
        "The gateway then delivers the outcome to `POST /payments/webhook`, which "
        "completes the payment and confirms or fails the booking."
    ),
)
def create_payment(
    payload: PaymentCreate,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return payment_service.create_payment(db, user, payload)


@router.post(
    "/webhook",
    summary="Payment gateway webhook",
    description=(
        "Receives payment outcome events from the gateway. Idempotent by event_id: "
        "repeated deliveries of the same event are processed at most once, enforced "
        "by a database-level unique constraint and transactional processing. "
        "Events that conflict with the current payment state are rejected with 409 "
        "and recorded for audit."
    ),
    response_model=WebhookResult,
)
def payment_webhook(payload: WebhookEventIn, db: Session = Depends(get_db)):
    result = payment_service.process_webhook(db, payload)
    return JSONResponse(status_code=200, content=result.model_dump(mode="json"))
