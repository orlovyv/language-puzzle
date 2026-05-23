from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import PUBLIC_DIR
from app.routes.api import router as api_router
from app.routes.api import startup


def create_app() -> FastAPI:
    application = FastAPI(title="Language Puzzle MVP")
    application.mount("/assets", StaticFiles(directory=PUBLIC_DIR), name="assets")
    application.include_router(api_router)
    @application.on_event("startup")
    async def on_startup():
        startup()
    return application


app = create_app()
