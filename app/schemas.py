from typing import Literal, Optional

from pydantic import BaseModel

Operation = Literal["generate", "analyze", "improve", "comment"]


class ChatCreate(BaseModel):
    title: Optional[str] = None


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


class ChatContext(BaseModel):
    relevant_code: str = ""
    selected_code: str = ""
    programming_language: str = "Python"
    requirements: str = ""
    libraries: str = "PySpark"


class ChatDetail(Chat):
    messages: list[Message]
    context: ChatContext