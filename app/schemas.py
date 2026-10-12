from typing import Literal, Optional

from pydantic import BaseModel, Field

Operation = Literal["generate", "analyze", "improve", "comment"]


class ChatCreate(BaseModel):
    title: Optional[str] = None


class CodeSuggestionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2 * 1024 * 1024)
    cursor: int = Field(ge=0)


class CodeSuggestion(BaseModel):
    code: str


class Chat(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class Message(BaseModel):
    id: str
    role: str
    content: str
    attachments: list[str]
    created_at: str


class ContextFile(BaseModel):
    name: str
    content: str
    analysis: str = ""


class ChatContext(BaseModel):
    relevant_code: str = ""
    selected_code: str = ""
    files: list[ContextFile] = []
    programming_language: str = "Python"
    requirements: str = ""
    libraries: str = "PySpark"


class ChatDetail(Chat):
    messages: list[Message]
    context: ChatContext