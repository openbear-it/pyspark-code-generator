from typing import Annotated, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import MAX_FILE_SIZE
from app.database import create_chat, get_chat, list_chats, save_message, update_chat_context
from app.llm import request_completion
from app.schemas import Chat, ChatContext, ChatCreate, ChatDetail, Message, Operation

router = APIRouter(prefix="/api", tags=["chats"])


@router.get("/chats", response_model=list[Chat], summary="List chat sessions")
async def read_chats() -> list[Chat]:
    return list_chats()


@router.post("/chats", response_model=Chat, status_code=201, summary="Create a chat session")
async def add_chat(payload: ChatCreate) -> Chat:
    return create_chat(payload.title)


@router.get("/chats/{chat_id}", response_model=ChatDetail, summary="Retrieve a chat session")
async def read_chat(chat_id: str) -> ChatDetail:
    return get_chat(chat_id)


@router.get("/chats/{chat_id}/context", response_model=ChatContext, summary="Retrieve persistent chat context")
async def read_chat_context(chat_id: str) -> ChatContext:
    return get_chat(chat_id).context


@router.put("/chats/{chat_id}/context", response_model=ChatContext, summary="Replace persistent chat context")
async def replace_chat_context(chat_id: str, context: ChatContext) -> ChatContext:
    return update_chat_context(chat_id, context)


@router.post(
    "/chats/{chat_id}/messages",
    response_model=Message,
    summary="Send a prompt and optional text files to the LLM",
    description="Accepts multipart form data. Each uploaded UTF-8 text file is limited to 2 MB.",
)
async def add_message(
    chat_id: str,
    prompt: Annotated[str, Form(min_length=1)],
    operation: Annotated[Operation, Form()] = "generate",
    files: Annotated[Optional[list[UploadFile]], File()] = None,
) -> Message:
    get_chat(chat_id)
    attachment_names: list[str] = []
    file_context: list[str] = []
    for upload in files or []:
        content = await upload.read(MAX_FILE_SIZE + 1)
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail=f"{upload.filename} exceeds the 2 MB limit")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=422, detail=f"{upload.filename} is not UTF-8 text") from error
        attachment_names.append(upload.filename or "uploaded-file")
        file_context.append(f"\n\n--- File: {upload.filename} ---\n{text}")

    save_message(chat_id, "user", prompt + "".join(file_context), attachment_names)
    answer = await request_completion(get_chat(chat_id), operation)
    return save_message(chat_id, "assistant", answer, [])