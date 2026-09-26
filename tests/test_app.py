import os
import re
import sqlite3

import httpx
from groq import APIConnectionError, APITimeoutError, PermissionDeniedError, RateLimitError

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage
import pytest

import app as backend


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "DATABASE_PATH", tmp_path / "therapist.db")
    with TestClient(backend.app) as test_client:
        yield test_client


def test_pages_are_rendered_and_moods_are_saved(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "Chat with ChatWell" in home.text
    assert "Mood tracker" in home.text
    assert 'id="chat-form"' in home.text
    assert 'action="/add_mood"' in home.text
    assert re.search(r'href="http://testserver/static/compiled-tailwind\.css\?v=\d+"', home.text)
    assert re.search(r'src="http://testserver/static/script\.js\?v=\d+"', home.text)
    assert "bg-zinc-950" in home.text
    assert "moveStars" not in home.text

    response = client.post(
        "/add_mood", data={"mood": "<b>Calm</b>", "note": "A good day"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/#moods"

    updated = client.get("/")
    assert "&lt;b&gt;Calm&lt;/b&gt;" in updated.text
    assert "A good day" in updated.text
    assert 'id="chat-form"' in updated.text

    chat_page = client.get("/chat", follow_redirects=False)
    assert chat_page.status_code == 303
    assert chat_page.headers["location"] == "/#chat"
    assert client.get("/static/script.js").status_code == 200
    stylesheet = client.get("/static/compiled-tailwind.css")
    assert stylesheet.status_code == 200
    assert ".bg-zinc-800" in stylesheet.text
    assert ".text-zinc-100" in stylesheet.text
    assert "@keyframes" not in stylesheet.text
    assert client.get("/static/style.css").status_code == 404
    assert client.get("/.env").status_code == 404


def test_chat_uses_pipeline_and_persists_reply(client, monkeypatch):
    class FakeChain:
        def invoke(self, payload):
            assert "I feel anxious" in payload["input"]
            assert "Client is 25 years old" in payload["input"]
            assert payload["history"] == []
            return "**Try box breathing.**"

    monkeypatch.setattr(backend, "get_rag_chain", lambda: FakeChain())
    response = client.post(
        "/chat",
        json={
            "symptoms": "I feel anxious",
            "age": "25",
            "sex": "Other",
            "duration": "2 days",
            "session_id": "test-session",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"response": "Try box breathing."}

    with sqlite3.connect(backend.DATABASE_PATH) as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE session_id = ? ORDER BY id",
            ("test-session",),
        ).fetchall()
    assert rows == [("User", "I feel anxious"), ("Therapist", "Try box breathing.")]


def test_chat_omits_empty_optional_context(client, monkeypatch):
    class FakeChain:
        def invoke(self, payload):
            assert payload == {"input": "A synthetic check-in", "history": []}
            return "Take a short pause."

    monkeypatch.setattr(backend, "get_rag_chain", lambda: FakeChain())
    response = client.post("/chat", json={"symptoms": "A synthetic check-in"})
    assert response.status_code == 200
    assert response.json() == {"response": "Take a short pause."}


def test_chat_follow_up_receives_only_its_session_history(client, monkeypatch):
    inputs = []

    class FakeChain:
        def invoke(self, payload):
            inputs.append(payload)
            return "A different option is available."

    monkeypatch.setattr(backend, "get_rag_chain", lambda: FakeChain())
    first = client.post(
        "/chat", json={"symptoms": "I tried a tiny task.", "session_id": "first-session"}
    )
    second = client.post(
        "/chat", json={"symptoms": "It did not help.", "session_id": "first-session"}
    )
    separate = client.post(
        "/chat", json={"symptoms": "A separate check-in.", "session_id": "second-session"}
    )
    assert all(response.status_code == 200 for response in (first, second, separate))
    assert inputs[0]["history"] == []
    history = inputs[1]["history"]
    assert [type(message) for message in history] == [HumanMessage, AIMessage]
    assert [message.text for message in history] == [
        "I tried a tiny task.",
        "A different option is available.",
    ]
    assert inputs[1]["input"] == "It did not help."
    assert inputs[2]["history"] == []


def test_history_is_bounded_and_missing_session_ids_are_unique(client):
    with sqlite3.connect(backend.DATABASE_PATH) as conn:
        conn.executemany(
            "INSERT INTO chat_history (session_id, role, content) VALUES (?, ?, ?)",
            [("bounded-session", "User", f"message-{index}") for index in range(12)],
        )
        conn.commit()
    history = backend.recent_chat_history("bounded-session")
    assert [message.text for message in history] == [
        f"message-{index}" for index in range(4, 12)
    ]
    assert backend.ChatInput(symptoms="one").session_id != backend.ChatInput(symptoms="two").session_id


def test_chat_marks_model_reply_that_hits_output_limit(client, monkeypatch):
    class LimitedOutputChain:
        def invoke(self, _):
            return AIMessage(
                content="Try one small action, such as washing a cup—it",
                response_metadata={"finish_reason": "length"},
            )

    monkeypatch.setattr(backend, "get_rag_chain", lambda: LimitedOutputChain())
    response = client.post("/chat", json={"symptoms": "Synthetic check-in"})
    assert response.status_code == 200
    assert response.json() == {
        "response": "Try one small action, such as washing a cup—it",
        "truncated": True,
    }


def test_chat_rejects_empty_or_oversized_input(client):
    assert client.post("/chat", json={"symptoms": ""}).status_code == 422
    assert client.post("/chat", json={"symptoms": "a" * 4001}).status_code == 422


def test_crisis_message_does_not_call_model(client, monkeypatch):
    def unexpected_chain():
        raise AssertionError("The model should not be called")

    monkeypatch.setattr(backend, "get_rag_chain", unexpected_chain)
    response = client.post("/chat", json={"symptoms": "I want to hurt myself"})
    assert response.status_code == 200
    assert "Safety Alert" in response.json()["response"]


def test_chat_failure_returns_json_error(client, monkeypatch):
    class FailedChain:
        def invoke(self, _):
            raise RuntimeError("Model unavailable")

    monkeypatch.setattr(backend, "get_rag_chain", lambda: FailedChain())
    response = client.post("/chat", json={"symptoms": "Hello"})
    assert response.status_code == 502
    assert response.json() == {
        "error": "I am having trouble accessing Groq or the local knowledge index."
    }


def test_groq_client_uses_hosted_model_and_expected_settings(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GROQ_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    backend.get_groq_llm.cache_clear()
    try:
        client = backend.get_groq_llm()
        assert client.model_name == "openai/gpt-oss-120b"
        assert client.temperature == 0.6
        assert client.max_tokens == 1024
        assert client.reasoning_effort == "low"
        assert client.reasoning_format is None
        assert client.model_kwargs == {"include_reasoning": False}
        assert client.request_timeout == 90
        assert client.max_retries == 0
        assert client.groq_api_key is not None
        assert client.groq_api_key.get_secret_value() == "test-key"
    finally:
        backend.get_groq_llm.cache_clear()


def test_groq_client_loads_key_from_project_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GROQ_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    original_key = os.environ.pop("GROQ_API_KEY", None)
    backend.get_groq_llm.cache_clear()
    try:
        client = backend.get_groq_llm()
        assert client.groq_api_key is not None
        assert client.groq_api_key.get_secret_value() == "file-key"
    finally:
        backend.get_groq_llm.cache_clear()
        os.environ.pop("GROQ_API_KEY", None)
        if original_key is not None:
            os.environ["GROQ_API_KEY"] = original_key


def test_qwen_model_can_still_be_selected(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    backend.get_groq_llm.cache_clear()
    try:
        client = backend.get_groq_llm()
        assert client.model_name == "qwen/qwen3.8-27b"
        assert client.reasoning_effort == "none"
        assert client.max_tokens == 512
        assert client.reasoning_format == "hidden"
        assert client.model_kwargs == {}
    finally:
        backend.get_groq_llm.cache_clear()


def test_chat_without_groq_key_returns_setup_error(client, monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "BASE_DIR", tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    backend.get_groq_llm.cache_clear()
    backend.get_rag_chain.cache_clear()
    try:
        response = client.post("/chat", json={"symptoms": "Hello"})
        assert response.status_code == 503
        assert response.json() == {
            "error": "Set GROQ_API_KEY in .env or the server environment to enable chat."
        }
    finally:
        backend.get_groq_llm.cache_clear()
        backend.get_rag_chain.cache_clear()


def test_chat_reports_groq_rate_limit(client, monkeypatch):
    class LimitedChain:
        def invoke(self, _):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(429, request=request)
            raise RateLimitError("Rate limit reached", response=response, body=None)

    monkeypatch.setattr(backend, "get_rag_chain", lambda: LimitedChain())
    response = client.post("/chat", json={"symptoms": "Hello"})
    assert response.status_code == 429
    assert response.json() == {
        "error": "Groq's rate limit was reached. Please try again later."
    }


def test_chat_rate_limit_names_quota_and_retry_time(client, monkeypatch):
    class LimitedChain:
        def invoke(self, _):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(429, headers={"retry-after": "42"}, request=request)
            body = {"error": {"message": "Rate limit reached on output tokens per minute (OTPM)"}}
            raise RateLimitError("Rate limit reached", response=response, body=body)

    monkeypatch.setattr(backend, "get_rag_chain", lambda: LimitedChain())
    response = client.post("/chat", json={"symptoms": "Synthetic check-in"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"
    assert response.json() == {
        "error": "Groq's output tokens per minute limit was reached. Try again in about 42 seconds."
    }


def test_chat_reports_blocked_groq_model(client, monkeypatch):
    class BlockedChain:
        def invoke(self, _):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            response = httpx.Response(403, request=request)
            raise PermissionDeniedError("Model blocked", response=response, body=None)

    monkeypatch.setattr(backend, "get_rag_chain", lambda: BlockedChain())
    response = client.post("/chat", json={"symptoms": "Hello"})
    assert response.status_code == 403
    assert "Groq blocked this model" in response.json()["error"]


def test_chat_timeout_can_be_retried_without_saving_failed_message(client, monkeypatch):
    class TimedOutChain:
        def invoke(self, _):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            raise APITimeoutError(request=request)

    monkeypatch.setattr(backend, "get_rag_chain", lambda: TimedOutChain())
    response = client.post("/chat", json={"symptoms": "Synthetic check-in"})
    assert response.status_code == 504
    assert response.json() == {
        "error": "Groq took too long to respond. Your message is ready to retry."
    }
    with sqlite3.connect(backend.DATABASE_PATH) as conn:
        assert conn.execute("SELECT count(*) FROM chat_history").fetchone()[0] == 0


def test_chat_connection_failure_is_reported_separately(client, monkeypatch):
    class DisconnectedChain:
        def invoke(self, _):
            request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
            raise APIConnectionError(request=request)

    monkeypatch.setattr(backend, "get_rag_chain", lambda: DisconnectedChain())
    response = client.post("/chat", json={"symptoms": "Synthetic check-in"})
    assert response.status_code == 503
    assert response.json() == {
        "error": "Could not connect to Groq. Please retry your message."
    }
