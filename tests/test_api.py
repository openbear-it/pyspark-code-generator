from fastapi.testclient import TestClient

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
            "programming_language": "PySpark",
            "requirements": "Filter invalid records",
            "libraries": "PySpark, Delta Lake",
        }
        assert client.put(f"/api/chats/{chat_id}/context", json=context).json() == context
        loaded = client.get(f"/api/chats/{chat_id}")
        assert loaded.status_code == 200
        assert loaded.json()["messages"] == []
        assert loaded.json()["context"] == context