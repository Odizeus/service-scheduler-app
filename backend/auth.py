"""Auth helpers: bcrypt + JWT."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Header, HTTPException, status


JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = os.environ.get("JWT_ALGO", "HS256")
ACCESS_TTL = int(os.environ.get("ACCESS_TOKEN_TTL_MIN", "720"))

_ENV = os.environ.get("APP_ENV", "development").lower()
if _ENV == "production" and JWT_SECRET == "dev-secret-change-me":
    raise RuntimeError(
        "JWT_SECRET must be set to a strong random value in production. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
    )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def issue_access_token(*, user_id: str, business_id: str, email: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "business_id": business_id,
        "email": email,
        "token_version": int(token_version or 0),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ACCESS_TTL)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


async def require_admin(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency: parse 'Bearer <token>', return JWT claims."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = decode_token(token)
    if claims.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    return claims
