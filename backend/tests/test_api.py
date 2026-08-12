from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_stream_finishes() -> None:
    with client.stream("POST", "/api/chat/stream", json={"content": "你好"}) as response:
        body = "".join(response.iter_text())
    assert response.status_code == 200
    assert "event: message.delta" in body
    assert "event: completed" in body


def test_chat_rejects_agent() -> None:
    response = client.post(
        "/api/chat/stream",
        json={"content": "画一张图", "mode": "chat", "agent_type": "image"},
    )
    assert response.status_code == 422

