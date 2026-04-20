import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, ChatSession, Message
import main

# StaticPool forces all connections to share one in-memory DB
test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = sessionmaker(bind=test_engine)


@pytest.fixture(autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    original = main.SessionLocal
    main.SessionLocal = TestSessionLocal
    yield
    main.SessionLocal = original
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def session():
    db = TestSessionLocal()
    yield db
    db.close()


def mock_hf(chunks):
    mock = MagicMock()
    mock.chat.completions.create.return_value = iter(chunks)
    return mock


def make_stream_chunk(token):
    chunk = MagicMock()
    chunk.choices[0].delta.content = token
    return chunk


# ── Session endpoints ──────────────────────────────────────────────────────────

def test_create_session(client):
    res = client.post("/sessions")
    assert res.status_code == 200
    data = res.json()
    assert "id" in data
    assert data["title"] == "New Chat"


def test_get_sessions_empty(client):
    res = client.get("/sessions")
    assert res.status_code == 200
    assert res.json() == []


def test_get_sessions_returns_created(client):
    client.post("/sessions")
    client.post("/sessions")
    res = client.get("/sessions")
    assert len(res.json()) == 2


def test_delete_session(client):
    session_id = client.post("/sessions").json()["id"]
    res = client.delete(f"/sessions/{session_id}")
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert client.get("/sessions").json() == []


def test_delete_nonexistent_session(client):
    res = client.delete("/sessions/nonexistent-id")
    assert res.status_code == 404


def test_delete_session_also_deletes_messages(client, session):
    session_id = client.post("/sessions").json()["id"]
    msg = Message(id="msg-1", session_id=session_id, role="user", content="hello")
    session.add(msg)
    session.commit()

    client.delete(f"/sessions/{session_id}")
    remaining = session.query(Message).filter(Message.session_id == session_id).all()
    assert remaining == []


# ── Messages endpoint ──────────────────────────────────────────────────────────

def test_get_messages_empty(client):
    session_id = client.post("/sessions").json()["id"]
    res = client.get(f"/sessions/{session_id}/messages")
    assert res.status_code == 200
    assert res.json() == []


def test_get_messages_order(client, session):
    session_id = client.post("/sessions").json()["id"]
    session.add(Message(id="m1", session_id=session_id, role="user", content="first"))
    session.add(Message(id="m2", session_id=session_id, role="assistant", content="second"))
    session.commit()

    messages = client.get(f"/sessions/{session_id}/messages").json()
    assert messages[0]["content"] == "first"
    assert messages[1]["content"] == "second"


# ── Generate endpoint ──────────────────────────────────────────────────────────

def test_generate_streams_response(client):
    session_id = client.post("/sessions").json()["id"]

    chunks = [make_stream_chunk("Hello"), make_stream_chunk(" world")]
    with patch("main.hf_client", mock_hf(chunks)):
        res = client.post("/generate", json={"prompt": "Hi", "session_id": session_id})

    assert res.status_code == 200
    assert "Hello" in res.text
    assert " world" in res.text
    assert "[DONE]" in res.text


def test_generate_saves_messages_to_db(client, session):
    session_id = client.post("/sessions").json()["id"]

    chunks = [make_stream_chunk("Hi there")]
    with patch("main.hf_client", mock_hf(chunks)):
        client.post("/generate", json={"prompt": "Hello", "session_id": session_id})

    messages = session.query(Message).filter(Message.session_id == session_id).all()
    assert any(m.role == "user" and m.content == "Hello" for m in messages)
    assert any(m.role == "assistant" and m.content == "Hi there" for m in messages)


def test_generate_sends_history_to_llm(client, session):
    session_id = client.post("/sessions").json()["id"]
    session.add(Message(id="m1", session_id=session_id, role="user", content="What is 2+2?"))
    session.add(Message(id="m2", session_id=session_id, role="assistant", content="4"))
    session.commit()

    chunks = [make_stream_chunk("Sure")]
    mock = mock_hf(chunks)
    with patch("main.hf_client", mock):
        client.post("/generate", json={"prompt": "Are you sure?", "session_id": session_id})

    messages_sent = mock.chat.completions.create.call_args[1]["messages"]
    assert messages_sent[0]["role"] == "system"
    assert messages_sent[1] == {"role": "user", "content": "What is 2+2?"}
    assert messages_sent[2] == {"role": "assistant", "content": "4"}
    assert messages_sent[3] == {"role": "user", "content": "Are you sure?"}


def test_generate_invalid_session(client):
    res = client.post("/generate", json={"prompt": "Hi", "session_id": "invalid-id"})
    assert res.status_code == 404


def test_generate_updates_session_title(client, session):
    session_id = client.post("/sessions").json()["id"]

    chunks = [make_stream_chunk("response")]
    with patch("main.hf_client", mock_hf(chunks)):
        client.post("/generate", json={"prompt": "Tell me about Python", "session_id": session_id})

    updated = session.query(ChatSession).filter(ChatSession.id == session_id).first()
    assert updated.title == "Tell me about Python"
