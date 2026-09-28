from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import BookingStatus


class BookingCreate(BaseModel):
    centre_id: int = Field(gt=0)
    test_id: int = Field(gt=0)
    appointment_time: datetime

    @field_validator("appointment_time")
    @classmethod
    def must_be_in_the_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            # Interpret naive datetimes as UTC.
            v = v.replace(tzinfo=UTC)
        if v <= datetime.now(UTC):
            raise ValueError("appointment_time must be in the future")
        return v


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    centre_id: int
    test_id: int
    appointment_time: datetime
    amount: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime
