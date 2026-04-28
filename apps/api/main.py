import logging
import time
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apps.api.config import settings
from apps.api.routes import audit_router, enrich_router, generate_router, pipeline_router, github_router
from packages.services.supabase_service import supabase_service

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

TTL_INTERVAL_SECONDS = 3600  # Run cleanup every 1 hour


async def _ttl_cleanup_loop():
    """Background loop that runs job TTL cleanup on a fixed interval."""
    await asyncio.sleep(10)  # Initial delay — let the app finish starting
    while True:
        try:
            summary = await supabase_service.cleanup_stale_jobs()
            total = summary["stuck_failed"] + summary["expired_deleted"]
            if total > 0:
                logger.info(f"TTL cleanup: {summary['stuck_failed']} stuck failed, {summary['expired_deleted']} expired deleted")
            else:
                logger.debug("TTL cleanup: nothing to clean")
        except Exception as e:
            logger.error(f"TTL cleanup loop error: {e}")
        await asyncio.sleep(TTL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages background tasks that run for the lifetime of the app."""
    task = asyncio.create_task(_ttl_cleanup_loop())
    logger.info("TTL cleanup background task started (interval: 1h)")
    yield
    task.cancel()
    logger.info("TTL cleanup background task stopped")


app = FastAPI(
    title="ForgeTest API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        f"{request.method} {request.url.path} {response.status_code} {duration_ms:.2f}ms"
    )
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)}
    )


app.include_router(audit_router, prefix="/api/v1")
app.include_router(enrich_router, prefix="/api/v1")
app.include_router(generate_router, prefix="/api/v1")
app.include_router(pipeline_router, prefix="/api/v1")
app.include_router(github_router, prefix="/api/v1")


@app.get("/")
def root():
    return {"message": "ForgeTest API", "version": "1.0.0"}


@app.get("/health")
def health_check():
    return JSONResponse(content={"status": "healthy"}, status_code=200)