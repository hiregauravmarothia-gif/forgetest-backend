import logging
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from apps.api.config import settings
from apps.api.routes import audit_router, enrich_router, generate_router, pipeline_router, github_router

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ForgeTest API",
    version="1.0.0",
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