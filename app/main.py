from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api import router as chat_router
from app.database import initialize_database, is_database_available
from app.metrics import collect_request_metrics

ROOT_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="PySpark Code Generator API",
    summary="Generate, analyze, improve, and comment PySpark code with an OpenAI-compatible LLM.",
    description=(
        "Create a chat session, optionally set its persistent context, then submit prompts and UTF-8 text files. "
        "The service retains session history in SQLite."
    ),
    version="0.1.0",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "chats", "description": "Persistent chat sessions, context, and LLM requests."},
        {"name": "operations", "description": "Service health and readiness probes."},
    ],
    lifespan=lifespan,
)
app.middleware("http")(collect_request_metrics)
app.mount("/static", StaticFiles(directory=ROOT_DIR / "static"), name="static")
app.include_router(chat_router)


@app.get("/", include_in_schema=False)
async def interface() -> FileResponse:
    return FileResponse(ROOT_DIR / "static" / "index.html")


@app.get("/health", tags=["operations"], summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["operations"], summary="Readiness probe")
async def readiness() -> dict[str, str]:
    if not is_database_available():
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)