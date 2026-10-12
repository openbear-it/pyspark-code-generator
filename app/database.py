import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.config import DATABASE_PATH
from app.schemas import Chat, ChatContext, ChatDetail, Message


def current_time() -> str:
    return datetime.now(UTC).isoformat()


def connection() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE_PATH)
    database.row_factory = sqlite3.Row
    return database


def initialize_database() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with connection() as database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                attachments TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            );
            CREATE TABLE IF NOT EXISTS chat_contexts (
                chat_id TEXT PRIMARY KEY,
                relevant_code TEXT NOT NULL DEFAULT '',
                selected_code TEXT NOT NULL DEFAULT '',
                programming_language TEXT NOT NULL DEFAULT 'Python',
                requirements TEXT NOT NULL DEFAULT '',
                libraries TEXT NOT NULL DEFAULT 'PySpark',
                FOREIGN KEY (chat_id) REFERENCES chats(id)
            );
            """
        )
        context_columns = {row["name"] for row in database.execute("PRAGMA table_info(chat_contexts)")}
        if "selected_code" not in context_columns:
            database.execute("ALTER TABLE chat_contexts ADD COLUMN selected_code TEXT NOT NULL DEFAULT ''")


def is_database_available() -> bool:
    try:
        with connection() as database:
            database.execute("SELECT 1")
    except sqlite3.Error:
        return False
    return True


def list_chats() -> list[Chat]:
    with connection() as database:
        rows = database.execute("SELECT * FROM chats ORDER BY updated_at DESC").fetchall()
    return [Chat(**dict(row)) for row in rows]


def create_chat(title: str | None) -> Chat:
    timestamp = current_time()
    chat = Chat(id=str(uuid4()), title=title or "New PySpark chat", created_at=timestamp, updated_at=timestamp)
    with connection() as database:
        database.execute("INSERT INTO chats VALUES (?, ?, ?, ?)", tuple(chat.model_dump().values()))
        database.execute("INSERT INTO chat_contexts (chat_id) VALUES (?)", (chat.id,))
    return chat


def get_chat(chat_id: str) -> ChatDetail:
    with connection() as database:
        chat = database.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
        if chat is None:
            raise HTTPException(status_code=404, detail="Chat not found")
        rows = database.execute(
            "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at", (chat_id,)
        ).fetchall()
        context = database.execute(
            "SELECT relevant_code, selected_code, programming_language, requirements, libraries "
            "FROM chat_contexts WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    messages = [
        Message(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            attachments=json.loads(row["attachments"]),
            created_at=row["created_at"],
        )
        for row in rows
    ]
    return ChatDetail(
        **dict(chat),
        messages=messages,
        context=ChatContext(**dict(context)) if context else ChatContext(),
    )


def update_chat_context(chat_id: str, context: ChatContext) -> ChatContext:
    get_chat(chat_id)
    with connection() as database:
        database.execute(
            """
            INSERT INTO chat_contexts (chat_id, relevant_code, selected_code, programming_language, requirements, libraries)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                relevant_code = excluded.relevant_code,
                selected_code = excluded.selected_code,
                programming_language = excluded.programming_language,
                requirements = excluded.requirements,
                libraries = excluded.libraries
            """,
            (chat_id, *context.model_dump().values()),
        )
    return context


def save_message(chat_id: str, role: str, content: str, attachments: list[str]) -> Message:
    message = Message(
        id=str(uuid4()),
        role=role,
        content=content,
        attachments=attachments,
        created_at=current_time(),
    )
    with connection() as database:
        database.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            (message.id, chat_id, role, content, json.dumps(attachments), message.created_at),
        )
        database.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (current_time(), chat_id))
    return message