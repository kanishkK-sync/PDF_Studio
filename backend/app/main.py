"""FastAPI application entry point."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from app.api.routes import compress, health, jobs, jpg_to_pdf, pdf_to_jpg
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.services.compress import rebuild_concurrency_gate
from app.services.jpg_to_pdf import rebuild_concurrency_gate as rebuild_jpg_to_pdf_gate
from app.services.pdf_to_jpg import rebuild_concurrency_gate as rebuild_pdf_to_jpg_gate
from app.utils.storage import purge_all, sweep_expired

logger = logging.getLogger(__name__)

SWEEP_INTERVAL_SECONDS = 5 * 60


def _empty_storage() -> None:
    """Start with a clean slate: nothing from a previous run survives."""
    try:
        removed = purge_all()
    except Exception:  # keep the server up; /api/health must still answer
        logger.exception("Could not empty storage at startup")
        return
    if removed:
        logger.info("Removed %s leftover job(s) at startup", removed)


async def _sweep_forever() -> None:
    """Delete expired jobs every few minutes, surviving any error."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            removed = await run_in_threadpool(sweep_expired)
        except Exception:
            logger.exception("Sweeping expired jobs failed")
        else:
            if removed:
                logger.info("Swept %s expired job(s)", removed)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Empty storage on start, run the sweeper, and stop it cleanly on shutdown."""
    await run_in_threadpool(_empty_storage)
    rebuild_concurrency_gate()
    rebuild_pdf_to_jpg_gate()
    rebuild_jpg_to_pdf_gate()
    sweeper = asyncio.create_task(_sweep_forever())
    try:
        yield
    finally:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

register_error_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(compress.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(pdf_to_jpg.router, prefix="/api")
app.include_router(jpg_to_pdf.router, prefix="/api")