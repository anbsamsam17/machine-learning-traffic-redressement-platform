"""Authentication system — JWT-based with in-memory user store (migratable to DB).

Security notes (audit 01):

- The JWT secret is validated fail-fast at boot (`config.Settings`, A4).
- `get_current_user` is the per-request dependency that resolves a Bearer
  token to a `UserRecord`.
- `get_owned_session` (A2) couples sessions to their owner: it loads the
  Session via `session_manager`, then returns 404 if the caller is not the
  owner. Routers receive this via `Depends(get_owned_session)` instead of
  calling `session_manager.get_session` directly — closes IDOR P1-2.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, EmailStr

from .config import get_settings
from .session import Session, session_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Password hashing (bcrypt directly, no passlib needed)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

_ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS = 24


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=_ALGORITHM)


def verify_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGORITHM])
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expire",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# In-memory user store (swap for DB later)
# ---------------------------------------------------------------------------

class UserRecord:
    __slots__ = ("user_id", "email", "hashed_password", "created_at")

    def __init__(self, email: str, hashed_password: str) -> None:
        self.user_id: str = uuid.uuid4().hex
        self.email: str = email
        self.hashed_password: str = hashed_password
        self.created_at: float = time.time()


class UserStore:
    """User store — uses Redis if REDIS_URL is set, else in-memory.

    Redis storage ensures users persist across API restarts and are shared
    across multiple uvicorn workers.
    """
    _REDIS_PREFIX = "user:"
    _REDIS_ID_PREFIX = "userid:"

    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}  # email -> UserRecord (fallback)
        self._lock = Lock()
        self._redis = None
        redis_url = get_settings().REDIS_URL
        if redis_url:
            try:
                import redis
                self._redis = redis.from_url(redis_url, decode_responses=False)
                self._redis.ping()
                logger.info("UserStore using Redis backend")
            except Exception as e:
                logger.warning("Redis unavailable for UserStore, falling back to memory: %s", e)
                self._redis = None

    def _serialize(self, user: UserRecord) -> bytes:
        import json as _json
        return _json.dumps({
            "user_id": user.user_id,
            "email": user.email,
            "hashed_password": user.hashed_password,
            "created_at": user.created_at,
        }).encode("utf-8")

    def _deserialize(self, raw: bytes) -> UserRecord:
        import json as _json
        d = _json.loads(raw.decode("utf-8"))
        user = UserRecord.__new__(UserRecord)
        user.user_id = d["user_id"]
        user.email = d["email"]
        user.hashed_password = d["hashed_password"]
        user.created_at = d["created_at"]
        return user

    def register(self, email: str, password: str) -> UserRecord:
        if self._redis is not None:
            key = f"{self._REDIS_PREFIX}{email}"
            if self._redis.exists(key):
                raise ValueError("Un compte avec cet email existe deja")
            user = UserRecord(email=email, hashed_password=hash_password(password))
            self._redis.set(key, self._serialize(user))
            self._redis.set(f"{self._REDIS_ID_PREFIX}{user.user_id}", email.encode("utf-8"))
            return user
        with self._lock:
            if email in self._users:
                raise ValueError("Un compte avec cet email existe deja")
            user = UserRecord(email=email, hashed_password=hash_password(password))
            self._users[email] = user
            return user

    def authenticate(self, email: str, password: str) -> UserRecord | None:
        user = self.get_by_email(email)
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def get_by_email(self, email: str) -> UserRecord | None:
        if self._redis is not None:
            raw = self._redis.get(f"{self._REDIS_PREFIX}{email}")
            if raw is None:
                return None
            return self._deserialize(raw)
        with self._lock:
            return self._users.get(email)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        if self._redis is not None:
            email_raw = self._redis.get(f"{self._REDIS_ID_PREFIX}{user_id}")
            if email_raw is None:
                return None
            email = email_raw.decode("utf-8") if isinstance(email_raw, bytes) else email_raw
            return self.get_by_email(email)
        with self._lock:
            for user in self._users.values():
                if user.user_id == user_id:
                    return user
        return None


user_store = UserStore()

# ---------------------------------------------------------------------------
# Dependency: get_current_user
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    mdl_access_token: Annotated[str | None, Cookie()] = None,
) -> UserRecord:
    """Resolve the current user from either the `Authorization: Bearer <jwt>`
    header (server-to-server, mobile apps) or the `mdl_access_token` cookie
    (browser pages — set by lib/auth.ts after login). Both vectors carry the
    same JWT; reading from the cookie too means React components can use
    plain `fetch()` without manually attaching the header on every call.
    """
    token = credentials.credentials if credentials else mdl_access_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = verify_token(token)
    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide: sub manquant",
        )
    user = user_store.get_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable",
        )
    return user


# ---------------------------------------------------------------------------
# Dependency: get_owned_session (A2 — closes IDOR P1-2)
# ---------------------------------------------------------------------------

def get_owned_session(
    session_id: str,
    current_user: Annotated[UserRecord, Depends(get_current_user)],
) -> Session:
    """Resolve a session and enforce that the caller owns it.

    Returns 404 (not 403) when the caller is not the owner — same response
    as a missing session so a third party cannot probe session-id existence.

    Routers replace `session_manager.get_session(sid)` by
    `session: Session = Depends(get_owned_session)` to inherit the check
    without per-handler boilerplate (E2 will plug it everywhere).
    """
    sess = session_manager.get_session(session_id)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvee ou expiree.",
        )
    if sess.owner_user_id and sess.owner_user_id != current_user.user_id:
        # Log the cross-tenant attempt for monitoring (truncated ids only).
        logger.warning(
            "IDOR refused: user=%s tried to access session owned by %s",
            current_user.user_id[:8], sess.owner_user_id[:8],
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvee ou expiree.",
        )
    return sess


def require_owned_session(session_id: str, user: "UserRecord") -> Session:
    """Imperative helper variant of ``get_owned_session``.

    Used by routers that resolve ``session_id`` from a body payload (instead
    of a path parameter) and therefore cannot rely on FastAPI's
    ``Depends(get_owned_session)`` plumbing. Same 404-on-mismatch semantics.
    """
    sess = session_manager.get_session(session_id)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvee ou expiree.",
        )
    if sess.owner_user_id and sess.owner_user_id != user.user_id:
        logger.warning(
            "IDOR refused: user=%s tried to access session owned by %s",
            user.user_id[:8], sess.owner_user_id[:8],
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session non trouvee ou expiree.",
        )
    return sess


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    user_id: str
    email: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# Rate limits are applied at the route level in main.py via the slowapi
# `limiter.limit(...)` decorator after the limiter exists. We expose hooks
# here for the future router-level decorators expected by A6.

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest) -> UserResponse:
    if len(body.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 8 caracteres",
        )
    try:
        user = user_store.register(body.email, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    logger.info("User registered: user_id=%s", user.user_id[:8])
    return UserResponse(user_id=user.user_id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    user = user_store.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
        )
    token = create_access_token({"sub": user.user_id, "email": user.email})
    logger.info("User logged in: user_id=%s", user.user_id[:8])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[UserRecord, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(user_id=current_user.user_id, email=current_user.email)


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    """Invalidate the auth cookie client-side.

    JWTs are stateless and cannot be revoked server-side without a
    blocklist, so this endpoint's job is to clear the `mdl_access_token`
    cookie (which the Next.js Edge middleware reads). The frontend is
    responsible for also clearing localStorage. Always returns
    `{"ok": true}` so the client can safely chain a redirect to /login.
    """
    # Expire the cookie immediately (matches the path used by lib/auth.ts)
    response.delete_cookie(
        key="mdl_access_token",
        path="/",
        samesite="lax",
    )
    logger.info("User logged out")
    return {"ok": True}
