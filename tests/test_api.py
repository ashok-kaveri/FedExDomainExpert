from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with patch("api.server.build_chain") as mock_build, \
         patch("api.server.ask") as mock_ask:
        mock_build.return_value = MagicMock()
        mock_ask.return_value = {
            "answer": "Label generation creates a FedEx label via the REST API.",
            "sources": ["https://pluginhive.com/label-gen"],
        }
        from api.server import app
        yield TestClient(app)


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ask_returns_answer_and_sources(client):
    resp = client.post("/ask", json={"question": "How does label generation work?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Label generation creates a FedEx label via the REST API."
    assert "https://pluginhive.com/label-gen" in data["sources"]
    assert data["session_id"] == "default"


def test_ask_with_custom_session_id(client):
    resp = client.post("/ask", json={
        "question": "How does label generation work?",
        "session_id": "team-member-123",
    })
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "team-member-123"


def test_clear_session(client):
    resp = client.delete("/sessions/team-member-123")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "team-member-123"}
