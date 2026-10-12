from contextlib import asynccontextmanager
from pathlib import Path
import re
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api import router as chat_router
from app.database import initialize_database, is_database_available
from app.metrics import collect_request_metrics

ROOT_DIR = Path(__file__).resolve().parent
SESSION_COOKIE_NAME = "pyspark_browser_session"
SESSION_COOKIE_MAX_AGE = 31_536_000


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


@app.middleware("http")
async def browser_session(request: Request, call_next):
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    new_session = not session_id or re.fullmatch(r"[A-Za-z0-9_-]{43}", session_id) is None
    if new_session:
        session_id = secrets.token_urlsafe(32)
    request.state.browser_session_id = session_id
    response = await call_next(request)
    if new_session:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            max_age=SESSION_COOKIE_MAX_AGE,
            path="/",
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
        )
    return response


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