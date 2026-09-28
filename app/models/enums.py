import enum


class BookingStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PaymentStatus(enum.StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


# Allowed state transitions. Terminal states map to an empty set.
BOOKING_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING: {
        BookingStatus.CONFIRMED,
        BookingStatus.FAILED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: set(),
    BookingStatus.FAILED: set(),
    BookingStatus.CANCELLED: set(),
}

PAYMENT_TRANSITIONS: dict[PaymentStatus, set[PaymentStatus]] = {
    PaymentStatus.PENDING: {PaymentStatus.SUCCESS, PaymentStatus.FAILED},
    PaymentStatus.SUCCESS: set(),
    PaymentStatus.FAILED: set(),
}
