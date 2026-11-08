import threading

import pytest
from fastapi.testclient import TestClient

from sop_agent.api.app import create_app
from sop_agent.api.sessions import SessionStore
from sop_agent.config import Settings
from sop_agent.llm.client import LLMAuthError
from sop_agent.llm.fake import FakeLLM
from sop_agent.sop.state import SessionState

KEY = "sk-ant-test-secret"


def make_client(extractions=(), key=None, mode="template", **overrides):
    settings = Settings(SOP_TODAY="2026-11-07", responder_mode=mode, ANTHROPIC_API_KEY=key, **overrides)
    llm = FakeLLM(list(extractions))
    seen = []

    def factory(api_key):
        seen.append(api_key)
        return llm

    app = create_app(settings, factory)
    return TestClient(app), app, llm, seen


def new_session(client, **body):
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 200
    return r.json()["session_id"]


def test_healthz_and_config():
    client, *_ = make_client(key=None)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/config").json() == {"responder_mode": "template", "server_key_configured": False}
    client, *_ = make_client(key="server-key", mode="llm")
    assert client.get("/api/config").json() == {"responder_mode": "llm", "server_key_configured": True}


def test_create_session_returns_initial_state_and_scenario():
    client, *_ = make_client()
    body = client.post("/api/sessions", json={"consent_scenario": "timeout"}).json()
    assert body["state"]["phase"] == "VERIFY_ID"
    assert body["state"]["consent"]["scenario"] == "timeout"
    assert client.post("/api/sessions", json={}).json()["state"]["consent"]["scenario"] == "default"


def test_unknown_consent_scenario_is_422():
    client, *_ = make_client()
    assert client.post("/api/sessions", json={"consent_scenario": "nope"}).status_code == 422


def test_get_session_and_unknown_session_404():
    client, *_ = make_client()
    sid = new_session(client)
    assert client.get(f"/api/sessions/{sid}").json()["phase"] == "VERIFY_ID"
    assert client.get("/api/sessions/missing").status_code == 404
    assert (
        client.post(
            "/api/sessions/missing/messages", json={"text": "hi"}, headers={"X-Anthropic-Key": KEY}
        ).status_code
        == 404
    )


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_empty_or_oversized_message_is_422(text):
    client, *_ = make_client()
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": text}, headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 422


def test_missing_key_is_401():
    client, *_ = make_client(key=None)
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Provide an Anthropic API key"}


def test_rejected_key_is_401():
    client, app, llm, _ = make_client()
    llm.extract = lambda **_: (_ for _ in ()).throw(LLMAuthError("x"))
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 401
    assert r.json() == {"detail": "Anthropic rejected the API key"}


def test_unexpected_error_is_generic_500():
    client, app, llm, _ = make_client()
    llm.extract = lambda **_: (_ for _ in ()).throw(RuntimeError(f"boom {KEY}"))
    sid = new_session(client)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 500
    assert KEY not in r.text and "boom" not in r.text


def test_demo_turn_verifies_and_reaches_process_case(P9_DEMO_EXTRACTION):
    client, _, _, seen = make_client([P9_DEMO_EXTRACTION])
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "demo"}, headers={"X-Anthropic-Key": KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["phase"] == "PROCESS_CASE"
    assert body["state"]["identity"]["verified"] is True
    assert body["trace"]["phase_after"] == "PROCESS_CASE"
    assert body["reply"]
    assert seen == [KEY]
    assert KEY not in r.text
    assert client.get(f"/api/sessions/{sid}").json()["phase"] == "PROCESS_CASE"


def test_server_key_is_used_when_no_header(P9_DEMO_EXTRACTION):
    client, _, _, seen = make_client([P9_DEMO_EXTRACTION], key="server-key")
    sid = new_session(client)
    r = client.post(f"/api/sessions/{sid}/messages", json={"text": "demo"})
    assert r.status_code == 200
    assert seen == ["server-key"]
    assert "server-key" not in r.text


def test_concurrent_messages_to_one_session_are_serialised():
    client, app, *_ = make_client(key="k")
    sid = new_session(client)
    codes = []

    def post():
        codes.append(client.post(f"/api/sessions/{sid}/messages", json={"text": "hello"}).status_code)

    threads = [threading.Thread(target=post) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert codes == [200, 200]
    assert len(app.state.sessions.get(sid).state.transcript) == 4


def test_store_expires_and_evicts_oldest():
    now = [0.0]
    store = SessionStore(ttl=10, max_sessions=2, clock=lambda: now[0])
    a, _ = store.create(SessionState.new())
    b, _ = store.create(SessionState.new())
    c, _ = store.create(SessionState.new())
    assert store.get(a) is None and store.get(b) and store.get(c)
    now[0] = 11.0
    assert store.get(b) is None


def test_store_hands_out_one_lock_per_session():
    store = SessionStore(ttl=10, max_sessions=2)
    sid, session = store.create(SessionState.new())
    assert store.get(sid).lock is session.lock
