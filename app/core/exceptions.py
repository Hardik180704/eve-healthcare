"""Domain exceptions raised by services and translated to HTTP responses."""


class APIError(Exception):
    status_code = 500
    default_detail = "Internal server error"

    def __init__(self, detail: str | None = None):
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class NotFoundError(APIError):
    status_code = 404
    default_detail = "Resource not found"


class ConflictError(APIError):
    status_code = 409
    default_detail = "Resource conflict"


class ValidationError(APIError):
    status_code = 422
    default_detail = "Validation error"


class AuthenticationError(APIError):
    status_code = 401
    default_detail = "Not authenticated"
