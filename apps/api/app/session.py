"""Session manager with Redis backend (optional) and in-memory fallback.

Security notes (audit 01):

- P0-2 (RCE): the previous implementation pickled non-Parquet DataFrames into
  Redis as `__DFPKL__<bytes>` and used `pickle.loads` on read. Any attacker
  able to write a Redis key under `mdl:sdata:*` (compromised host, exposed
  port, mis-config) could trigger arbitrary code execution. We now refuse
  Pickle entirely:
    - on write, DataFrames are cast (geometry/dict → JSON string) before
      Parquet serialisation; if the cast still fails we raise instead of
      silently falling back to Pickle;
    - on read, any leftover `__DFPKL__` blob raises `ValueError`. Existing
      Pickle blobs become unreadable; they will be re-uploaded by the user
      on the next session (TTL is short, default 2h).

- P1-2 (IDOR): sessions now carry `owner_user_id` and `get_owned_session`
  (in auth.py) wraps `session_manager.get_session` to refuse cross-tenant
  access. Logs only emit truncated session ids (8 hex chars).
"""

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


def _sid_log(sid: str) -> str:
    """Return the first 8 hex chars of a session id for log lines (P1-2)."""
    if not sid:
        return "<empty>"
    return sid[:8]


# ---------------------------------------------------------------------------
# Session data class (used by both backends)
# ---------------------------------------------------------------------------

@dataclass
class Session:
    """One user session — bound to its owner for tenant isolation (A2)."""

    session_id: str
    mode: str  # "TV" | "PL" | "TV+PL"
    owner_user_id: str = ""  # empty only for legacy sessions; A2 enforces non-empty
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_accessed = time.time()

    def is_expired(self, ttl: int) -> bool:
        return (time.time() - self.last_accessed) > ttl


# ---------------------------------------------------------------------------
# Helpers — DataFrame normalisation for safe serialisation (A3)
# ---------------------------------------------------------------------------

def _df_to_parquet_safe(df: pd.DataFrame) -> bytes:
    """Serialise *df* to Parquet, casting non-Parquet-compatible cells to JSON str.

    Parquet rejects mixed-type cells and Python dicts (e.g. GeoJSON geometry).
    We force such columns to string JSON to avoid the historical Pickle fallback
    (audit P0-2). If a column still fails, we raise — never fall back to Pickle.
    """
    safe = df.copy()
    for col in safe.columns:
        series = safe[col]
        if series.dtype != "object":
            continue
        # Probe a few non-null entries; if any cell is a dict/list/set we cast
        # the whole column to JSON string.
        sample = series.dropna().head(20)
        if any(isinstance(v, (dict, list, set, tuple)) for v in sample):
            safe[col] = series.apply(
                lambda v: json.dumps(v, default=str) if isinstance(v, (dict, list, set, tuple)) else v
            )

    buf = io.BytesIO()
    safe.to_parquet(buf, engine="pyarrow")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Backend interface
# ---------------------------------------------------------------------------

class SessionBackend:
    """Abstract base for session storage."""

    def create_session(self, mode: str, owner_user_id: str = "") -> Session:
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

    def create_session(self, mode: str = "TV", owner_user_id: str = "") -> Session:
        sid = uuid.uuid4().hex
        session = Session(session_id=sid, mode=mode, owner_user_id=owner_user_id)
        with self._lock:
            self._sessions[sid] = session
        logger.info("Session created: sid=%s mode=%s owner=%s",
                    _sid_log(sid), mode, _sid_log(owner_user_id))
        return session

    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            ttl = get_settings().SESSION_TTL_SECONDS
            if session.is_expired(ttl):
                del self._sessions[session_id]
                logger.info("Session expired and removed: sid=%s", _sid_log(session_id))
                return None
            session.touch()
            return session

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {_sid_log(session_id)} not found or expired")
        session.data[key] = value

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {_sid_log(session_id)} not found or expired")
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

class _RedisDataProxy(dict):
    """Dict-like proxy that lazily loads values from Redis on access.

    Ensures ``session.data.get("raw_df")`` works transparently with the Redis
    backend, just like it does with MemoryBackend.
    """

    def __init__(self, backend: "RedisBackend", session_id: str) -> None:
        super().__init__()
        self._backend = backend
        self._sid = session_id
        self._cache: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        try:
            raw = self._backend._r.get(self._backend._data_key(self._sid, key))
            if raw is not None:
                val = self._backend._deserialize_value(raw)
                self._cache[key] = val
                return val
        except ValueError:
            # Pickle blob refused (A3); propagate so caller knows the cache
            # is corrupt instead of silently returning default.
            raise
        except Exception:
            logger.exception("Redis read failed for key=%s sid=%s",
                             key, _sid_log(self._sid))
        return default

    def __getitem__(self, key: str) -> Any:
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __contains__(self, key: object) -> bool:
        return self.get(str(key)) is not None

    # Write-through: persists to Redis so ``session.data["x"] = y`` behaves
    # the same as ``session_manager.store_data(sid, "x", y)``.
    def __setitem__(self, key: str, value: Any) -> None:
        try:
            data_key = self._backend._data_key(self._sid, key)
            self._backend._r.setex(
                data_key,
                self._backend._ttl,
                self._backend._serialize_value(value),
            )
            self._cache[key] = value
        except Exception:
            logger.exception("Redis write-through failed for key=%s sid=%s; cache only",
                             key, _sid_log(self._sid))
            self._cache[key] = value

    def pop(self, key: str, *args: Any) -> Any:
        try:
            self._backend._r.delete(self._backend._data_key(self._sid, key))
        except Exception:
            logger.exception("Redis delete failed for key=%s sid=%s",
                             key, _sid_log(self._sid))
        return self._cache.pop(key, *args)

    def update(self, *args: Any, **kwargs: Any) -> None:
        other: dict[str, Any] = {}
        if args:
            other.update(args[0])
        other.update(kwargs)
        for k, v in other.items():
            self[k] = v


class RedisBackend(SessionBackend):
    """Redis-backed session store. DataFrames serialised as Parquet only (A3)."""

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
            # A3: no Pickle fallback. _df_to_parquet_safe casts non-Parquet
            # columns; if it still fails we propagate the error.
            return b"__DF__" + _df_to_parquet_safe(value)
        return b"__JSON__" + json.dumps(value, default=str).encode("utf-8")

    @staticmethod
    def _deserialize_value(raw: bytes) -> Any:
        if raw.startswith(b"__DFPKL__"):
            # A3: legacy Pickle blobs are explicitly refused (RCE vector).
            logger.error("Refused legacy pickle blob from Redis (A3, P0-2)")
            raise ValueError("legacy pickle blob refused")
        if raw.startswith(b"__DF__"):
            return pd.read_parquet(io.BytesIO(raw[6:]))
        if raw.startswith(b"__JSON__"):
            return json.loads(raw[8:].decode("utf-8"))
        return json.loads(raw.decode("utf-8"))

    # -- public API ------------------------------------------------------------

    def create_session(self, mode: str = "TV", owner_user_id: str = "") -> Session:
        sid = uuid.uuid4().hex
        now = time.time()
        session = Session(
            session_id=sid,
            mode=mode,
            owner_user_id=owner_user_id,
            created_at=now,
            last_accessed=now,
        )
        meta = json.dumps({
            "mode": mode,
            "owner_user_id": owner_user_id,
            "created_at": now,
            "last_accessed": now,
        })
        self._r.setex(self._session_key(sid), self._ttl, meta.encode("utf-8"))
        logger.info("Session created (redis): sid=%s mode=%s owner=%s",
                    _sid_log(sid), mode, _sid_log(owner_user_id))
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
            owner_user_id=meta.get("owner_user_id", ""),
            created_at=meta["created_at"],
            last_accessed=time.time(),
        )
        # Refresh TTL on access
        meta["last_accessed"] = session.last_accessed
        self._r.setex(key, self._ttl, json.dumps(meta).encode("utf-8"))

        # Use a lazy-loading dict proxy so session.data.get("key") works
        # without loading all DataFrames upfront (they can be huge)
        session.data = _RedisDataProxy(self, session_id)
        return session

    def store_data(self, session_id: str, key: str, value: Any) -> None:
        if self.get_session(session_id) is None:
            raise KeyError(f"Session {_sid_log(session_id)} not found or expired")
        data_key = self._data_key(session_id, key)
        self._r.setex(data_key, self._ttl, self._serialize_value(value))

    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        if self.get_session(session_id) is None:
            raise KeyError(f"Session {_sid_log(session_id)} not found or expired")
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

    def create_session(self, mode: str = "TV", owner_user_id: str = "") -> Session:
        return self._backend.create_session(mode, owner_user_id=owner_user_id)

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
