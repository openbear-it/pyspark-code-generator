import logging
from typing import Annotated, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.config import MAX_FILE_SIZE
from app.database import create_chat, get_chat, list_chats, save_message, update_chat_context
from app.llm import request_code_suggestion, stream_completion
from app.schemas import Chat, ChatContext, ChatCreate, ChatDetail, CodeSuggestion, CodeSuggestionRequest, Message, Operation
from app.source_analysis import analyze_source

router = APIRouter(prefix="/api", tags=["chats"])
logger = logging.getLogger(__name__)
STREAM_ERROR_PREFIX = "\x1ePYSPARK_STREAM_ERROR:"


def get_browser_session_id(request: Request) -> str:
    return request.state.browser_session_id


BrowserSessionId = Annotated[str, Depends(get_browser_session_id)]


@router.get("/chats", response_model=list[Chat], summary="List chat sessions")
async def read_chats(browser_session_id: BrowserSessionId) -> list[Chat]:
    return list_chats(browser_session_id)


@router.post("/chats", response_model=Chat, status_code=201, summary="Create a chat session")
async def add_chat(payload: ChatCreate, browser_session_id: BrowserSessionId) -> Chat:
    return create_chat(payload.title, browser_session_id)


@router.get("/chats/{chat_id}", response_model=ChatDetail, summary="Retrieve a chat session")
async def read_chat(chat_id: str, browser_session_id: BrowserSessionId) -> ChatDetail:
    return get_chat(chat_id, browser_session_id)


@router.get("/chats/{chat_id}/context", response_model=ChatContext, summary="Retrieve persistent chat context")
async def read_chat_context(chat_id: str, browser_session_id: BrowserSessionId) -> ChatContext:
    return get_chat(chat_id, browser_session_id).context


@router.put("/chats/{chat_id}/context", response_model=ChatContext, summary="Replace persistent chat context")
async def replace_chat_context(chat_id: str, context: ChatContext, browser_session_id: BrowserSessionId) -> ChatContext:
    return update_chat_context(chat_id, browser_session_id, context)


@router.post(
    "/chats/{chat_id}/context/files",
    response_model=ChatContext,
    summary="Analyze and add files to the persistent LLM context",
    description="Uploads UTF-8 CSV, TSV, JSON, JSON Lines, or text sources up to 2 MB each. Structured files are profiled locally and their schema is included in future LLM requests.",
)
async def add_context_files(
    chat_id: str,
    files: Annotated[list[UploadFile], File(description="One or more UTF-8 text files to persist as context")],
    browser_session_id: BrowserSessionId,
) -> ChatContext:
    chat = get_chat(chat_id, browser_session_id)
    context_files = {file.name: file for file in chat.context.files}
    for upload in files:
        content = await upload.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the 2 MB limit")
        try:
            source = analyze_source(upload.filename or "uploaded-file", content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        context_files[source.name] = source
    return update_chat_context(
        chat_id, browser_session_id, chat.context.model_copy(update={"files": list(context_files.values())})
    )


@router.post(
    "/chats/{chat_id}/suggestions",
    response_model=CodeSuggestion,
    summary="Get an inline LLM code suggestion",
    description="Returns a short code-only completion for the cursor position. The editor calls this endpoint after a pause in typing.",
)
async def suggest_code(
    chat_id: str, payload: CodeSuggestionRequest, browser_session_id: BrowserSessionId
) -> CodeSuggestion:
    context = get_chat(chat_id, browser_session_id).context
    return CodeSuggestion(code=await request_code_suggestion(context, payload.code, payload.cursor))


@router.post(
    "/chats/{chat_id}/messages",
    summary="Stream a response for a prompt and optional text files",
    description="Accepts multipart form data. UTF-8 CSV, TSV, JSON, JSON Lines, and text files up to 2 MB are structurally analyzed before being sent to the LLM.",
    responses={
        200: {
            "description": "Plain-text response streamed as LLM tokens are received.",
            "content": {"text/plain": {"schema": {"type": "string"}}},
        }
    },
)
async def add_message(
    chat_id: str,
    browser_session_id: BrowserSessionId,
    prompt: Annotated[str, Form(min_length=1)],
    operation: Annotated[Operation, Form()] = "generate",
    files: Annotated[Optional[list[UploadFile]], File()] = None,
) -> Message:
    get_chat(chat_id, browser_session_id)
    attachment_names: list[str] = []
    file_context: list[str] = []
    for upload in files or []:
        content = await upload.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the 2 MB limit")
        try:
            source = analyze_source(upload.filename or "uploaded-file", content)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        attachment_names.append(source.name)
        file_context.append(f"\n\n--- File: {source.name} ---\n{source.analysis}\n{source.content}")

    save_message(chat_id, browser_session_id, "user", prompt, attachment_names)
    chat = get_chat(chat_id, browser_session_id)
    if file_context:
        llm_message = chat.messages[-1].model_copy(update={"content": prompt + "".join(file_context)})
        chat = chat.model_copy(update={"messages": [*chat.messages[:-1], llm_message]})

    async def generate_response():
        chunks: list[str] = []
        try:
            async for chunk in stream_completion(chat, operation):
                chunks.append(chunk)
                yield chunk
        except HTTPException as error:
            logger.warning("LLM stream failed: %s", error.detail)
            yield f"{STREAM_ERROR_PREFIX}{quote(str(error.detail), safe='')}\n"
            return
        except Exception as error:
            logger.exception("Unexpected LLM stream failure")
            detail = f"Unexpected stream failure ({type(error).__name__})"
            yield f"{STREAM_ERROR_PREFIX}{quote(detail, safe='')}\n"
            return
        save_message(chat_id, browser_session_id, "assistant", "".join(chunks), [])

    return StreamingResponse(generate_response(), media_type="text/plain")