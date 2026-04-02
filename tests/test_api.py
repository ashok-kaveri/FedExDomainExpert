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
        # Clear sessions between tests
        import api.server as srv
        srv._sessions.clear()
        yield TestClient(app), mock_build, mock_ask


def test_health_returns_ok(client):
    test_client, _, _ = client
    resp = test_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ask_returns_answer_and_sources(client):
    test_client, mock_build, mock_ask = client
    resp = test_client.post("/ask", json={"question": "How does label generation work?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Label generation creates a FedEx label via the REST API."
    assert "https://pluginhive.com/label-gen" in data["sources"]
    assert data["session_id"] == "default"
    mock_ask.assert_called_once_with("How does label generation work?", mock_build.return_value)


def test_ask_with_custom_session_id(client):
    test_client, mock_build, _ = client
    resp = test_client.post("/ask", json={
        "question": "How does label generation work?",
        "session_id": "team-member-123",
    })
    assert resp.status_code == 200
    assert resp.json()["session_id"] == "team-member-123"
    mock_build.assert_called_once()  # verifies a new session was created


def test_clear_session(client):
    test_client, _, _ = client
    resp = test_client.delete("/sessions/team-member-123")
    assert resp.status_code == 200
    assert resp.json() == {"status": "cleared", "session_id": "team-member-123"}
