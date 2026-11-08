import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sop_agent.api.sessions import SessionStore
from sop_agent.config import Settings
from sop_agent.data.repository import Repository
from sop_agent.llm.client import AnthropicLLM, LLMAuthError, LLMClient
from sop_agent.sop.engine import SOPEngine
from sop_agent.sop.state import SessionState

INDEX = Path(__file__).resolve().parent.parent / "web" / "index.html"
log = logging.getLogger("sop_agent")


class NewSession(BaseModel):
    consent_scenario: Literal["default", "timeout"] = "default"


class Message(BaseModel):
    text: str


def create_app(
    settings: Settings | None = None, llm_factory: Callable[[str], LLMClient] | None = None
) -> FastAPI:
    settings = settings or Settings()
    repo = Repository.load(settings.fixtures_dir)
    llm_factory = llm_factory or (lambda key: AnthropicLLM(key, settings))
    app = FastAPI(title="SOP claims agent")
    app.state.sessions = store = SessionStore(settings.session_ttl_seconds, settings.max_sessions)

    @app.get("/")
    def index():
        return FileResponse(INDEX, media_type="text/html")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {
            "responder_mode": settings.responder_mode,
            "server_key_configured": bool(settings.anthropic_api_key),
        }

    @app.post("/api/sessions")
    def create_session(body: NewSession):
        sid, session = store.create(SessionState.new(consent_scenario=body.consent_scenario))
        return {"session_id": sid, "state": session.state.snapshot()}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        return _session(sid).state.snapshot()

    @app.post("/api/sessions/{sid}/messages")
    def post_message(sid: str, body: Message, x_anthropic_key: str | None = Header(default=None)):
        text = body.text.strip()
        if not text or len(text) > settings.max_message_chars:
            raise HTTPException(422, f"Message must be 1-{settings.max_message_chars} characters")
        session = _session(sid)
        key = x_anthropic_key or settings.anthropic_api_key
        if not key:
            raise HTTPException(401, "Provide an Anthropic API key")
        with session.lock:
            try:
                result = SOPEngine(repo, llm_factory(key), settings).handle_turn(session.state, text)
            except LLMAuthError as e:
                raise HTTPException(401, "Anthropic rejected the API key") from e
            except Exception as e:  # noqa: BLE001 - boundary: log the type only (no PII/key), return generic 500
                log.error("turn failed: %s", type(e).__name__)
                raise HTTPException(500, "Internal error while handling the message") from e
            return {
                "reply": result.reply,
                "state": session.state.snapshot(),
                "trace": result.trace.model_dump(mode="json"),
            }

    def _session(sid: str):
        session = store.get(sid)
        if session is None:
            raise HTTPException(404, "Unknown or expired session")
        return session

    return app


app = create_app()
