"""Admin route installer for permanently eliminating cancelled appointments.

This keeps the delete-route implementation out of auth helpers while preserving
existing behavior. The route is intentionally strict: only authenticated admins
can delete appointments that already have status='cancelled'.
"""
from __future__ import annotations

import sys
from typing import Any

from fastapi import Depends, FastAPI, HTTPException


def _server_module() -> Any | None:
    """Find the loaded backend server module regardless of import name."""
    for module_name in ("server", "backend.server", "__main__"):
        module = sys.modules.get(module_name)
        if module and all(hasattr(module, attr) for attr in ("db", "require_current_admin", "write_audit_log")):
            return module
    for module in list(sys.modules.values()):
        if module and all(hasattr(module, attr) for attr in ("db", "require_current_admin", "write_audit_log")):
            return module
    return None


def install_cancelled_appointment_delete_route(app: FastAPI) -> None:
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
