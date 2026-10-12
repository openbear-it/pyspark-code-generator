from fastapi.testclient import TestClient

import app.api as api
import app.database as database
from app.main import app


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