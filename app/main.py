import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import auth, bookings, diagnostics, health, payments
from app.core.config import settings
from app.core.exceptions import APIError
from app.core.logging import setup_logging

setup_logging()

logger = logging.getLogger("eve.http")

app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend API for booking diagnostic tests at diagnostic centres, with a simulated "
        "payment gateway and an idempotent payment webhook."
    ),
    version="1.0.0",
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(diagnostics.router)
app.include_router(bookings.router)
app.include_router(payments.router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One INFO line per request: method, path, status. No bodies, no headers."""
    response = await call_next(request)
    logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.exception_handler(APIError)
async def api_error_handler(request: Request, exc: APIError):
    """Translate domain exceptions into consistent JSON error responses."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler: log the error, never leak internals to the client."""
    logging.getLogger("eve.unhandled").exception(
        "unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
