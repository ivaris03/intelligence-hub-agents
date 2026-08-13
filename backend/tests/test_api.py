from fastapi.testclient import TestClient

from app.auth.security import get_current_user
from app.core.config import Settings, get_settings
from app.db.base import User
from app.main import app

app.dependency_overrides[get_settings] = lambda: Settings(
    dashscope_api_key=None,
    tavily_api_key=None,
    langsmith_tracing=False,
    langsmith_api_key=None,
)
client = TestClient(app)
app.dependency_overrides[get_current_user] = lambda: User(
    phone="13900000001",
    password_hash="unused",
    display_name="测试用户",
    role="admin",
    is_active=True,
)


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
