"""Authentication system — JWT-based with in-memory user store (migratable to DB)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from .config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


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
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}  # email -> UserRecord
        self._lock = Lock()

    def register(self, email: str, password: str) -> UserRecord:
        with self._lock:
            if email in self._users:
                raise ValueError("Un compte avec cet email existe deja")
            user = UserRecord(email=email, hashed_password=hash_password(password))
            self._users[email] = user
            return user

    def authenticate(self, email: str, password: str) -> UserRecord | None:
        with self._lock:
            user = self._users.get(email)
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def get_by_email(self, email: str) -> UserRecord | None:
        with self._lock:
            return self._users.get(email)

    def get_by_id(self, user_id: str) -> UserRecord | None:
        with self._lock:
            for user in self._users.values():
                if user.user_id == user_id:
                    return user
        return None


user_store = UserStore()

# ---------------------------------------------------------------------------
# Dependency: get_current_user
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> UserRecord:
    payload = verify_token(credentials.credentials)
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
    logger.info("User registered: %s", body.email)
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
    logger.info("User logged in: %s", body.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(current_user: Annotated[UserRecord, Depends(get_current_user)]) -> UserResponse:
    return UserResponse(user_id=current_user.user_id, email=current_user.email)
