import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.db.database import init_db

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Content Gap Analyzer MVP",
    description="Analyze search intent vs page content and generate recommendations.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(router)
