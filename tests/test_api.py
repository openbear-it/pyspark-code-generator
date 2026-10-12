import asyncio
import json
import sqlite3

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.api as api
import app.database as database
import app.llm as llm
from app.main import app
from app.schemas import ChatContext, ChatDetail


def test_health_and_chat_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        specification = client.get("/openapi.json")
        assert specification.status_code == 200
        assert "/api/chats/{chat_id}/messages" in specification.json()["paths"]
        assert "/api/chats/{chat_id}/context/files" in specification.json()["paths"]
        assert "/api/chats/{chat_id}/suggestions" in specification.json()["paths"]
        assert "text/plain" in specification.json()["paths"]["/api/chats/{chat_id}/messages"]["post"]["responses"]["200"]["content"]
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "pyspark_generator_http_requests_total" in metrics.text
        created = client.post("/api/chats", json={"title": "ETL review"})
        assert created.status_code == 201
        assert created.json()["title"] == "ETL review"
        chat_id = created.json()["id"]
        context = {
            "relevant_code": "df = spark.read.csv(path)",
            "selected_code": "df = spark.read.csv(path)",
            "files": [],
            "programming_language": "PySpark",
            "requirements": "Filter invalid records",
            "libraries": "PySpark, Delta Lake",
        }
        assert client.put(f"/api/chats/{chat_id}/context", json=context).json() == context
        loaded = client.get(f"/api/chats/{chat_id}")
        assert loaded.status_code == 200
        assert loaded.json()["messages"] == []
        assert loaded.json()["context"] == context


def test_browser_sessions_isolate_chat_access(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    context = {
        "relevant_code": "",
        "selected_code": "",
        "files": [],
        "programming_language": "Python",
        "requirements": "",
        "libraries": "PySpark",
    }
    with TestClient(app) as first_browser, TestClient(app) as second_browser:
        first_list = first_browser.get("/api/chats")
        second_list = second_browser.get("/api/chats")
        first_cookie = first_browser.cookies.get("pyspark_browser_session")
        second_cookie = second_browser.cookies.get("pyspark_browser_session")

        assert first_cookie and second_cookie and first_cookie != second_cookie
        assert "httponly" in first_list.headers["set-cookie"].lower()
        assert "samesite=lax" in first_list.headers["set-cookie"].lower()
        assert first_list.json() == second_list.json() == []

        created = first_browser.post("/api/chats", json={})
        chat_id = created.json()["id"]
        assert [chat["id"] for chat in first_browser.get("/api/chats").json()] == [chat_id]
        assert second_browser.get("/api/chats").json() == []
        assert first_browser.get(f"/api/chats/{chat_id}").status_code == 200

        assert second_browser.get(f"/api/chats/{chat_id}").status_code == 404
        assert second_browser.get(f"/api/chats/{chat_id}/context").status_code == 404
        assert second_browser.put(f"/api/chats/{chat_id}/context", json=context).status_code == 404
        assert second_browser.post(
            f"/api/chats/{chat_id}/context/files",
            files={"files": ("data.csv", b"id\n1\n", "text/csv")},
        ).status_code == 404
        assert second_browser.post(
            f"/api/chats/{chat_id}/suggestions", json={"code": "df", "cursor": 2}
        ).status_code == 404
        assert second_browser.post(
            f"/api/chats/{chat_id}/messages", data={"prompt": "hello"}
        ).status_code == 404


def test_legacy_chats_are_hidden_but_retained(tmp_path, monkeypatch):
    database_path = tmp_path / "chats.db"
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO chats VALUES (?, ?, ?, ?)",
            ("legacy-chat", "Old shared chat", "2025-01-01", "2025-01-01"),
        )

    with TestClient(app) as client:
        assert client.get("/api/chats").json() == []
        assert client.get("/api/chats/legacy-chat").status_code == 404

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT id, owner_id FROM chats").fetchone() == ("legacy-chat", None)


def test_context_files_are_persisted(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    with TestClient(app) as client:
        chat_id = client.post("/api/chats", json={}).json()["id"]
        response = client.post(
            f"/api/chats/{chat_id}/context/files",
            files=[
                ("files", ("customers.csv", b"id,name,active\n1,Ada,true\n2,,false\n", "text/csv")),
                ("files", ("orders.json", b'[{"id": 1, "amount": 12.5}]', "application/json")),
            ],
        )

        assert response.status_code == 200
        assert [file["name"] for file in response.json()["files"]] == ["customers.csv", "orders.json"]
        assert "Columns (3)" in response.json()["files"][0]["analysis"]
        assert [file["name"] for file in client.get(f"/api/chats/{chat_id}").json()["context"]["files"]] == [
            "customers.csv",
            "orders.json",
        ]


def test_code_suggestion_uses_chat_context(tmp_path, monkeypatch):
    async def fake_suggestion(context, code, cursor):
        assert code == "result = df"
        assert cursor == len(code)
        return ".select('id')"

    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    monkeypatch.setattr(api, "request_code_suggestion", fake_suggestion)
    with TestClient(app) as client:
        chat_id = client.post("/api/chats", json={}).json()["id"]
        response = client.post(
            f"/api/chats/{chat_id}/suggestions",
            json={"code": "result = df", "cursor": 11},
        )

        assert response.status_code == 200
        assert response.json() == {"code": ".select('id')"}


def test_chat_response_is_streamed_and_persisted(tmp_path, monkeypatch):
    llm_user_content = []

    async def fake_stream_completion(chat, operation):
        llm_user_content.append(chat.messages[-1].content)
        yield "Ciao "
        yield "**mondo**"

    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    monkeypatch.setattr(api, "stream_completion", fake_stream_completion)
    with TestClient(app) as client:
        chat_id = client.post("/api/chats", json={}).json()["id"]
        response = client.post(
            f"/api/chats/{chat_id}/messages",
            data={"prompt": "Rispondi in italiano", "operation": "generate"},
            files=[("files", ("customers.csv", b"id,name\n1,Ada\n", "text/csv"))],
        )

        assert response.status_code == 200
        assert response.text == "Ciao **mondo**"
        assert '"name": "Ada"' in llm_user_content[0]
        messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
        assert [message["content"] for message in messages] == ["Rispondi in italiano", "Ciao **mondo**"]
        assert messages[0]["attachments"] == ["customers.csv"]


@pytest.mark.parametrize("finish_reason", [None, "stop", "length"])
def test_llm_stream_requires_completion_signal(monkeypatch, finish_reason):
    original_async_client = httpx.AsyncClient
    content = "Risposta parziale, già con accenti: è"

    async def handler(request):
        event = {"choices": [{"delta": {"content": content}}]}
        body = f"data: {json.dumps(event)}\n\n"
        if finish_reason:
            final_event = {"choices": [{"delta": {}, "finish_reason": finish_reason}]}
            body += f"data: {json.dumps(final_event)}\n\n"
        return httpx.Response(200, content=body.encode())

    monkeypatch.setattr(llm.config, "LLM_BASE_URL", "https://llm.example")
    monkeypatch.setattr(llm.config, "LLM_API_KEY", "test-key")
    monkeypatch.setattr(llm.config, "LLM_MODEL", "test-model")
    monkeypatch.setattr(
        llm.httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    chat = ChatDetail(
        id="chat",
        title="Test",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        messages=[],
        context=ChatContext(),
    )

    async def collect_stream():
        return [chunk async for chunk in llm.stream_completion(chat, "generate")]

    if finish_reason in {None, "length"}:
        with pytest.raises(HTTPException) as error:
            asyncio.run(collect_stream())
        assert error.value.status_code == 502
    else:
        assert asyncio.run(collect_stream()) == [content]