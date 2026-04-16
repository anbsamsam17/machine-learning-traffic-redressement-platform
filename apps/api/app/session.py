"""Session manager with Redis backend (optional) and in-memory fallback."""

from __future__ import annotations

import io
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import pandas as pd

from .config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session data class (used by both backends)
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """One user session."""

    session_id: str
    mode: str  # "TV" | "PL" | "TV+PL"
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_accessed = time.time()

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.last_accessed) > ttl


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class SessionBackend:
    """Abstract base for session storage."""

    def create_session(self, mode: str) -> Session:
        raise NotImplementedError

    def get_session(self, session_id: str) -> Session | None:
        raise NotImplementedError

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        raise NotImplementedError

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def delete_session(self, session_id: str) -> None:
        raise NotImplementedError

    def cleanup_expired(self) -> int:
        raise NotImplementedError

    @property
    def active_count(self) -> int:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# In-memory backend
# ---------------------------------------------------------------------------

class MemoryBackend(SessionBackend):
    """Thread-safe, in-memory session store with TTL-based cleanup."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = Lock()

    def create_session(self, mode: str = "TV") -> Session:
        sid = uuid.uuid4().hex
        session = Session(session_id=sid, mode=mode)
        with self._lock:
            self._sessions[sid] = session
        logger.info("Session created: %s (mode=%s)", sid, mode)
        return session

    def get_session(self, session_id: str) -> Session | None:
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
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found or expired")
        session.data[key] = value

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found or expired")
        return session.data.get(key, default)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_expired(self) -> int:
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


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------

class RedisBackend(SessionBackend):
    """Redis-backed session store. DataFrames are serialised as Parquet bytes."""

    _PREFIX = "mdl:session:"
    _DATA_PREFIX = "mdl:sdata:"

    def __init__(self, redis_url: str) -> None:
        import redis as redis_lib

        self._r = redis_lib.Redis.from_url(redis_url, decode_responses=False)
        self._ttl = get_settings().SESSION_TTL_SECONDS
        logger.info("Redis session backend connected: %s", redis_url)

    # -- helpers ---------------------------------------------------------------

    def _session_key(self, sid: str) -> str:
        return f"{self._PREFIX}{sid}"

    def _data_key(self, sid: str, key: str) -> str:
        return f"{self._DATA_PREFIX}{sid}:{key}"

    @staticmethod
    def _serialize_value(value: Any) -> bytes:
        if isinstance(value, pd.DataFrame):
            buf = io.BytesIO()
            value.to_parquet(buf, engine="pyarrow")
            return b"__DF__" + buf.getvalue()
        return b"__JSON__" + json.dumps(value, default=str).encode("utf-8")

    @staticmethod
    def _deserialize_value(raw: bytes) -> Any:
        if raw.startswith(b"__DF__"):
            return pd.read_parquet(io.BytesIO(raw[6:]))
        if raw.startswith(b"__JSON__"):
            return json.loads(raw[8:].decode("utf-8"))
        return json.loads(raw.decode("utf-8"))

    # -- public API ------------------------------------------------------------

    def create_session(self, mode: str = "TV") -> Session:
        sid = uuid.uuid4().hex
        now = time.time()
        session = Session(session_id=sid, mode=mode, created_at=now, last_accessed=now)
        meta = json.dumps({"mode": mode, "created_at": now, "last_accessed": now})
        self._r.setex(self._session_key(sid), self._ttl, meta.encode("utf-8"))
        logger.info("Session created (redis): %s (mode=%s)", sid, mode)
        return session

    def get_session(self, session_id: str) -> Session | None:
        key = self._session_key(session_id)
        raw = self._r.get(key)
        if raw is None:
            return None
        meta = json.loads(raw.decode("utf-8"))
        session = Session(
            session_id=session_id,
            mode=meta["mode"],
            created_at=meta["created_at"],
            last_accessed=time.time(),
        )
        # Refresh TTL on access
        meta["last_accessed"] = session.last_accessed
        self._r.setex(key, self._ttl, json.dumps(meta).encode("utf-8"))
        return session

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        if self.get_session(session_id) is None:
            raise KeyError(f"Session {session_id} not found or expired")
        data_key = self._data_key(session_id, key)
        self._r.setex(data_key, self._ttl, self._serialize_value(value))

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        if self.get_session(session_id) is None:
            raise KeyError(f"Session {session_id} not found or expired")
        raw = self._r.get(self._data_key(session_id, key))
        if raw is None:
            return default
        return self._deserialize_value(raw)

    def delete_session(self, session_id: str) -> None:
        self._r.delete(self._session_key(session_id))
        # Clean up associated data keys
        pattern = f"{self._DATA_PREFIX}{session_id}:*"
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                self._r.delete(*keys)
            if cursor == 0:
                break

    def cleanup_expired(self) -> int:
        # Redis handles TTL natively; nothing to do
        return 0

    @property
    def active_count(self) -> int:
        pattern = f"{self._PREFIX}*"
        count = 0
        cursor = 0
        while True:
            cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=100)
            count += len(keys)
            if cursor == 0:
                break
        return count


# ---------------------------------------------------------------------------
# Session manager facade
# ---------------------------------------------------------------------------

class SessionManager:
    """Unified facade — delegates to Redis or memory backend."""

    def __init__(self) -> None:
        settings = get_settings()
        if settings.REDIS_URL:
            try:
                self._backend: SessionBackend = RedisBackend(settings.REDIS_URL)
                logger.info("Using Redis session backend")
            except Exception:
                logger.warning("Redis unavailable, falling back to memory backend", exc_info=True)
                self._backend = MemoryBackend()
        else:
            self._backend = MemoryBackend()
            logger.info("Using in-memory session backend")

    def create_session(self, mode: str = "TV") -> Session:
        return self._backend.create_session(mode)

    def get_session(self, session_id: str) -> Session | None:
        return self._backend.get_session(session_id)

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        self._backend.store_data(session_id, key, value)

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        return self._backend.get_data(session_id, key, default)

    def delete_session(self, session_id: str) -> None:
        self._backend.delete_session(session_id)

    def cleanup_expired(self) -> int:
        return self._backend.cleanup_expired()

    @property
    def active_count(self) -> int:
        return self._backend.active_count


# Module-level singleton
session_manager = SessionManager()
