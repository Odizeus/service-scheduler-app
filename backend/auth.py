"""Auth helpers: bcrypt + JWT."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.applications import FastAPI


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


def _server_module():
    """Find the loaded backend server module regardless of import name."""
    for module_name in ("server", "backend.server", "__main__"):
        module = sys.modules.get(module_name)
        if module and all(hasattr(module, attr) for attr in ("db", "require_current_admin", "write_audit_log")):
            return module
    for module in list(sys.modules.values()):
        if module and all(hasattr(module, attr) for attr in ("db", "require_current_admin", "write_audit_log")):
            return module
    return None


def _install_cancelled_appointment_delete_route(app: FastAPI) -> None:
    """Install admin-only permanent elimination for cancelled appointments."""
    if getattr(app, "_cancelled_appointment_delete_route_installed", False):
        return

    server = _server_module()
    if not server:
        return

    async def admin_delete_cancelled_appointment(
        appt_id: str,
        claims: dict = Depends(server.require_current_admin),
    ):
        doc = await server.db.appointments.find_one(
            {"_id": appt_id, "business_id": claims["business_id"]}
        )
        if not doc:
            raise HTTPException(404, "Appointment not found")
        if doc.get("status") != "cancelled":
            raise HTTPException(409, "Only cancelled appointments can be eliminated")

        customer = doc.get("customer", {}) or {}
        audit_details = {
            "confirmation_code": doc.get("confirmation_code", ""),
            "status": doc.get("status", ""),
            "local_date": doc.get("local_date", ""),
            "local_time_block": doc.get("local_time_block", ""),
            "service_type": doc.get("service_type", ""),
            "customer_name": customer.get("full_name", ""),
            "customer_email": customer.get("email", ""),
            "cancelled_by": doc.get("cancelled_by", ""),
            "cancelled_at": doc.get("cancelled_at", ""),
        }

        res = await server.db.appointments.delete_one(
            {"_id": appt_id, "business_id": claims["business_id"], "status": "cancelled"}
        )
        if res.deleted_count == 0:
            raise HTTPException(404, "Appointment not found")

        await server.write_audit_log(
            business_id=claims["business_id"],
            action="appointment.eliminated",
            admin_id=claims["sub"],
            target_type="appointment",
            target_id=appt_id,
            details=audit_details,
        )
        return {"deleted": True, "id": appt_id}

    app.add_api_route(
        "/api/admin/appointments/{appt_id}",
        admin_delete_cancelled_appointment,
        methods=["DELETE"],
        name="admin_delete_cancelled_appointment",
    )
    app._cancelled_appointment_delete_route_installed = True


_original_include_router = FastAPI.include_router


def _include_router_with_cancelled_delete(self, router, *args, **kwargs):
    result = _original_include_router(self, router, *args, **kwargs)
    if getattr(router, "prefix", None) == "/api":
        _install_cancelled_appointment_delete_route(self)
    return result


if not getattr(FastAPI, "_scheduler_cancelled_delete_patch_installed", False):
    FastAPI.include_router = _include_router_with_cancelled_delete
    FastAPI._scheduler_cancelled_delete_patch_installed = True
