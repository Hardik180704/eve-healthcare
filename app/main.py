from fastapi import FastAPI

from app.api.routes import auth, diagnostics, health
from app.core.config import settings
from app.core.exceptions import APIError
from app.core.logging import setup_logging

setup_logging()

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


@app.exception_handler(APIError)
async def api_error_handler(request, exc: APIError):
    """Translate domain exceptions into consistent JSON error responses."""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Last-resort handler: log the error, never leak internals to the client."""
    import logging

    from fastapi.responses import JSONResponse

    logging.getLogger("eve.unhandled").exception(
        "unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
