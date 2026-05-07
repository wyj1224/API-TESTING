from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.runs import router as runs_router
from app.api.schemas import router as schemas_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    app.include_router(schemas_router)
    app.include_router(runs_router)
    return app


app = create_app()
