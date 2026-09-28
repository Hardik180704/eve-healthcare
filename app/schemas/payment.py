from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PaymentStatus


class PaymentCreate(BaseModel):
    booking_id: UUID


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    booking_id: UUID
    amount: Decimal
    status: PaymentStatus
    created_at: datetime


class WebhookEventIn(BaseModel):
    """Schema for gateway webhook deliveries.

    event_id must be globally unique per logical gateway event; repeated
    deliveries of the same logical event must reuse the same event_id.
    """

    event_id: str = Field(min_length=1, max_length=255)
    payment_id: int = Field(gt=0)
    status: PaymentStatus
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)

    @field_validator("event_id")
    @classmethod
    def event_id_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("event_id must not be blank")
        return v.strip()


class WebhookEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    payment_id: int
    status: str
    received_at: datetime


class WebhookResult(BaseModel):
    event_id: str
    payment_id: int
    payment_status: PaymentStatus
    booking_status: str
    duplicate: bool
    message: str
