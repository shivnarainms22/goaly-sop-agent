import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sop_agent.sop.state import SessionState


@dataclass
class Session:
    state: SessionState
    last_used: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """In-memory sessions: idle TTL, hard cap (oldest evicted), one lock per session."""

    def __init__(self, ttl: float, max_sessions: int, clock: Callable[[], float] = time.monotonic):
        self._ttl, self._max, self._clock = ttl, max_sessions, clock
        self._sessions: dict[str, Session] = {}  # insertion order == creation order
        self._guard = threading.Lock()

    def create(self, state: SessionState) -> tuple[str, Session]:
        with self._guard:
            while len(self._sessions) >= self._max:
                del self._sessions[next(iter(self._sessions))]
            sid, session = uuid.uuid4().hex, Session(state, self._clock())
            self._sessions[sid] = session
            return sid, session

    def get(self, sid: str) -> Session | None:
        with self._guard:
            session = self._sessions.get(sid)
            if session is None:
                return None
            if self._clock() - session.last_used > self._ttl:
                del self._sessions[sid]
                return None
            session.last_used = self._clock()
            return session
