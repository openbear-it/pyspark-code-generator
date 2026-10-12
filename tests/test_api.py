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
            "programming_language": "PySpark",
            "requirements": "Filter invalid records",
            "libraries": "PySpark, Delta Lake",
        }
        assert client.put(f"/api/chats/{chat_id}/context", json=context).json() == context
        loaded = client.get(f"/api/chats/{chat_id}")
        assert loaded.status_code == 200
        assert loaded.json()["messages"] == []
        assert loaded.json()["context"] == context


def test_chat_response_is_streamed_and_persisted(tmp_path, monkeypatch):
    async def fake_stream_completion(chat, operation):
        yield "Ciao "
        yield "**mondo**"

    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "chats.db")
    monkeypatch.setattr(api, "stream_completion", fake_stream_completion)
    with TestClient(app) as client:
        chat_id = client.post("/api/chats", json={}).json()["id"]
        response = client.post(
            f"/api/chats/{chat_id}/messages",
            data={"prompt": "Rispondi in italiano", "operation": "generate"},
        )

        assert response.status_code == 200
        assert response.text == "Ciao **mondo**"
        assert [message["content"] for message in client.get(f"/api/chats/{chat_id}").json()["messages"]] == [
            "Rispondi in italiano",
            "Ciao **mondo**",
        ]