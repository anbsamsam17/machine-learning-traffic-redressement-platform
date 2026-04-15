"""In-memory session manager with TTL expiry."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """One user session (in-memory)."""

    session_id: str
    mode: str  # "TV" | "PL" | "TV+PL"
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_accessed = time.time()

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.last_accessed) > ttl


class SessionManager:
    """Thread-safe, in-memory session store with TTL-based cleanup."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    # -- public API ------------------------------------------------------------

    def create_session(self, mode: str = "TV") -> Session:
        """Create a new session and return it."""
        sid = uuid.uuid4().hex
        session = Session(session_id=sid, mode=mode)
        with self._lock:
            self._sessions[sid] = session
        logger.info("Session created: %s (mode=%s)", sid, mode)
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Retrieve a session by ID; returns None if missing or expired."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            ttl = get_settings().SESSION_TTL_SECONDS
            if session.is_expired(ttl):
                del self._sessions[session_id]
                logger.info("Session expired and removed: %s", session_id)
                return None
            session.touch()
            return session

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        """Store arbitrary data in an existing session."""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found or expired")
        session.data[key] = value

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        """Retrieve data from a session."""
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found or expired")
        return session.data.get(key, default)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns the number purged."""
        ttl = get_settings().SESSION_TTL_SECONDS
        to_remove: list[str] = []
        with self._lock:
            for sid, session in self._sessions.items():
                if session.is_expired(ttl):
                    to_remove.append(sid)
            for sid in to_remove:
                del self._sessions[sid]
        if to_remove:
            logger.info("Cleaned up %d expired sessions", len(to_remove))
        return len(to_remove)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)


# Module-level singleton
session_manager = SessionManager()
