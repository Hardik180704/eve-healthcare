from fastapi import FastAPI

from app.api.routes import health
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    description=(
        "Backend API for booking diagnostic tests at diagnostic centres, with a simulated "
        "payment gateway and an idempotent payment webhook."
    ),
    version="1.0.0",
)

app.include_router(health.router)
