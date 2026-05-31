from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import PUBLIC_DIR
from app.core.database import close_pool
from app.routes import analysis, auth, documents, knowledge, learn, spa, users, words
from app.startup import startup


@asynccontextmanager
async def lifespan(application: FastAPI):
    startup()
    yield
    close_pool()


def create_app() -> FastAPI:
    application = FastAPI(title="Language Puzzle MVP", lifespan=lifespan)
    application.mount("/assets", StaticFiles(directory=PUBLIC_DIR), name="assets")

    for module in (auth, documents, analysis, knowledge, words, learn, users):
        application.include_router(module.router)
    application.include_router(spa.router)  # catch-all, must come last

    return application


app = create_app()
