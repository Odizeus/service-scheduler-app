"""Service Business Scheduler - FastAPI backend.

Multi-tenant capable; auto-seeds one demo business on startup.
"""
from __future__ import annotations

import csv
import io
import logging
import os
import secrets
import string
import uuid

import certifi
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError
from starlette.middleware.cors import CORSMiddleware

from auth import (
    hash_password,
    issue_access_token,
    require_admin,
    verify_password,
)
from availability import (
    date_in_allowed_window,
    generate_day_slots,
    is_month_allowed,
    iso_weekday,
    now_in_tz,
    to_utc,
)
from email_adapter import enqueue_email, render
from models import (
    AdminUser,
    Availability,
    Business,
    CancelAppointmentRequest,
    ChangePasswordRequest,
    CreateAdminRequest,
    CreateAppointmentRequest,
    CreateOverrideRequest,
    LoginRequest,
    PortalCancelRequest,
    PortalRescheduleRequest,
    UpdateAvailabilityRequest,
    UpdateBusinessRequest,
    UpdateStatusRequest,
    UpdateTemplatesRequest,
)

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("scheduler")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
client = AsyncIOMotorClient(
    MONGO_URL,
    tls=True,
    tlsCAFile=certifi.where(),
    serverSelectionTimeoutMS=10000,
)
db = client[DB_NAME]

app = FastAPI(title="Service Business Scheduler")
api = APIRouter(prefix="/api")

APP_ENV = os.environ.get("APP_ENV", "development").lower()
_raw_cors = os.environ.get("CORS_ORIGINS", "").strip()
if APP_ENV == "production" and (not _raw_cors or "*" in _raw_cors):
    raise RuntimeError("CORS_ORIGINS must be set to explicit frontend origins in production.")

DEFAULT_DEV_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
CORS_ORIGINS = [
    origin.strip()
    for origin in (_raw_cors or DEFAULT_DEV_ORIGINS).split(",")
    if origin.strip() and origin.strip() != "*"
]

# CORS must be registered before routes are mounted
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

RATE_LIMIT_BUCKETS: Dict[Tuple[str, str], List[float]] = {}
RATE_LIMIT_RULES = [
    ("/api/admin/auth/login", 10, 60),
    ("/api/public/business/", 120, 60),
    ("/api/portal/", 120, 60),
]


@app.middleware("http")
async def security_and_rate_limit_middleware(request: Request, call_next):
    now_ts = datetime.now(timezone.utc).timestamp()
    client_ip = request.client.host if request.client else "unknown"
    path = request.url.path

    for prefix, max_requests, window_seconds in RATE_LIMIT_RULES:
        if path.startswith(prefix):
            key = (client_ip, prefix)
            recent = [
                ts for ts in RATE_LIMIT_BUCKETS.get(key, [])
                if now_ts - ts < window_seconds
            ]
            if len(recent) >= max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again shortly."},
                )
            recent.append(now_ts)
            RATE_LIMIT_BUCKETS[key] = recent
            break

    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ---------- helpers ----------
def confirmation_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def new_access_token() -> str:
    # ~32 chars, URL-safe; opaque, unguessable
    return secrets.token_urlsafe(24)


def portal_url_for(token: str) -> str:
    base = os.environ.get("FRONTEND_BASE_URL", "").rstrip("/")
    return f"{base}/portal/{token}" if base else f"/portal/{token}"


def strip_id(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return doc
    if "_id" in doc:
        doc["id"] = doc.pop("_id")
    return doc


async def require_current_admin(claims: dict = Depends(require_admin)) -> dict:
    """Validate JWT claims against the current admin document.

    token_version lets us invalidate all old JWTs immediately after logout,
    password change, or emergency account reset.
    """
    user = await db.admin_users.find_one(
        {"_id": claims.get("sub"), "business_id": claims.get("business_id")}
    )
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Admin user not found")
    expected_version = int(user.get("token_version", 0) or 0)
    token_version = int(claims.get("token_version", 0) or 0)
    if token_version != expected_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    claims["role"] = user.get("role", "staff")
    return claims


async def write_audit_log(
    *,
    business_id: str,
    action: str,
    admin_id: str = "",
    target_type: str = "",
    target_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    await db.audit_logs.insert_one({
        "_id": str(uuid.uuid4()),
        "business_id": business_id,
        "action": action,
        "admin_id": admin_id,
        "target_type": target_type,
        "target_id": target_id,
        "details": details or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


async def add_appointment_history(
    *,
    appointment_id: str,
    business_id: str,
    action: str,
    actor: str,
    actor_id: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> None:
    entry = {
        "id": str(uuid.uuid4()),
        "action": action,
        "actor": actor,
        "actor_id": actor_id,
        "details": details or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.appointments.update_one(
        {"_id": appointment_id, "business_id": business_id},
        {
            "$push": {"history": entry},
            "$set": {"updated_at": entry["created_at"]},
        },
    )
    await write_audit_log(
        business_id=business_id,
        action=f"appointment.{action}",
        admin_id=actor_id if actor == "admin" else "",
        target_type="appointment",
        target_id=appointment_id,
        details=entry,
    )



def business_to_public(b: Dict[str, Any]) -> Dict[str, Any]:
    """Public-safe business view (no internal fields)."""
    return {
        "id": b["id"],
        "slug": b["slug"],
        "name": b["name"],
        "service_label": b.get("service_label", "Service"),
        "contact_phone": b.get("contact_phone", ""),
        "contact_email": b.get("contact_email", ""),
        "website": b.get("website", ""),
        "logo_url": b.get("logo_url", ""),
        "address": b.get("address", {}),
        "timezone": b.get("timezone", "America/New_York"),
        "service_types": b.get("service_types", []),
        "service_area": b.get("service_area", {"cities": [], "zip_codes": [], "counties": [], "out_of_area_policy": "block"}),
        "availability": b.get("availability", {}),
    }


def check_service_area(biz: Dict[str, Any], customer) -> str:
    """Returns 'in_area' if customer city/zip/county matches any configured rule,
    'out_of_area' if none match. If no rules are configured, returns 'in_area'."""
    sa = biz.get("service_area") or {}
    cities = [c.strip().lower() for c in (sa.get("cities") or []) if c and c.strip()]
    zips = [z.strip() for z in (sa.get("zip_codes") or []) if z and z.strip()]
    counties = [c.strip().lower() for c in (sa.get("counties") or []) if c and c.strip()]
    if not (cities or zips or counties):
        return "in_area"
    cust_city = (getattr(customer, "city", None) or "").strip().lower()
    cust_zip = (getattr(customer, "zip", None) or "").strip()
    cust_county = (getattr(customer, "county", None) or "").strip().lower()
    if cust_city and cust_city in cities:
        return "in_area"
    if cust_zip and cust_zip in zips:
        return "in_area"
    if cust_county and cust_county in counties:
        return "in_area"
    return "out_of_area"


def biz_email_vars(biz: Dict[str, Any]) -> Dict[str, str]:
    """Variables sourced from Business settings, shared across all emails."""
    addr = biz.get("address", {}) or {}
    parts = [addr.get("street", ""), addr.get("city", ""), addr.get("state", ""), addr.get("zip", "")]
    formatted = ", ".join([p for p in parts if p])
    return {
        "business_name": biz.get("name", ""),
        "business_phone": biz.get("contact_phone", ""),
        "business_email": biz.get("contact_email", ""),
        "business_website": biz.get("website", ""),
        "business_logo_url": biz.get("logo_url", ""),
        "business_address": formatted,
    }


async def get_business(slug: str) -> Dict[str, Any]:
    doc = await db.businesses.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Business not found")
    return strip_id(doc)


async def get_business_by_id(bid: str) -> Dict[str, Any]:
    doc = await db.businesses.find_one({"_id": bid})
    if not doc:
        raise HTTPException(404, "Business not found")
    return strip_id(doc)


# ---------- startup: indexes + seed ----------
@app.on_event("startup")
async def startup_event():
    await db.businesses.create_index([("slug", ASCENDING)], unique=True)
    await db.admin_users.create_index(
        [("business_id", ASCENDING), ("email", ASCENDING)], unique=True
    )
    # Unique partial index → atomic slot reservation for both confirmed AND pending (out-of-area awaiting approval)
    try:
        await db.appointments.drop_index("uniq_active_slot")
    except Exception:
        pass
    await db.appointments.create_index(
        [
            ("business_id", ASCENDING),
            ("local_date", ASCENDING),
            ("local_time_block", ASCENDING),
        ],
        unique=True,
        partialFilterExpression={"status": {"$in": ["confirmed", "pending"]}},
        name="uniq_active_slot",
    )
    await db.appointments.create_index([("confirmation_code", ASCENDING)], unique=True)
    await db.appointments.create_index(
        [("access_token", ASCENDING)],
        unique=True,
        partialFilterExpression={"access_token": {"$type": "string"}},
        name="uniq_access_token",
    )
    await db.appointments.create_index(
        [("business_id", ASCENDING), ("start_at_utc", ASCENDING)]
    )
    await db.availability_overrides.create_index(
        [("business_id", ASCENDING), ("local_date", ASCENDING), ("local_time_block", ASCENDING)]
    )
    await db.audit_logs.create_index([("business_id", ASCENDING), ("created_at", ASCENDING)])
    await db.audit_logs.create_index([("target_type", ASCENDING), ("target_id", ASCENDING)])
    log.info("Indexes ensured")
    await seed_demo()


async def seed_demo():
    slug = os.environ.get("SEED_BUSINESS_SLUG", "demo-services")
    if await db.businesses.find_one({"slug": slug}):
        return
    business_id = str(uuid.uuid4())
    biz = Business(
        id=business_id,
        slug=slug,
        name=os.environ.get("SEED_BUSINESS_NAME", "Demo Service Co."),
        service_label="Service",
        timezone=os.environ.get("SEED_BUSINESS_TIMEZONE", "America/New_York"),
        contact_phone="+1 (555) 010-2030",
        contact_email="hello@example.com",
        service_types=[
            "Garage Door Repair",
            "Cleaning",
            "Painting",
            "Handyman",
            "HVAC",
            "Lawn Care",
        ],
    )
    doc = biz.model_dump()
    doc["_id"] = doc.pop("id")
    doc["created_at"] = doc["created_at"].isoformat()
    doc["updated_at"] = doc["updated_at"].isoformat()
    await db.businesses.insert_one(doc)

    admin = AdminUser(
        id=str(uuid.uuid4()),
        business_id=business_id,
        email=os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com"),
        password_hash=hash_password(os.environ.get("SEED_ADMIN_PASSWORD", "Admin@12345")),
    )
    a = admin.model_dump()
    a["_id"] = a.pop("id")
    a["created_at"] = a["created_at"].isoformat()
    await db.admin_users.insert_one(a)
    log.info("Seeded demo business slug=%s admin=%s", slug, admin.email)


@app.on_event("shutdown")
async def shutdown():
    client.close()


# ============================================================
# PUBLIC API
# ============================================================
@api.get("/")
async def root():
    return {"service": "scheduler", "status": "ok"}


@api.get("/public/business/{slug}")
async def public_business(slug: str):
    biz = await get_business(slug)
    return business_to_public(biz)


@api.get("/public/business/{slug}/availability")
async def public_availability(slug: str, month: str = Query(..., description="YYYY-MM")):
    biz = await get_business(slug)
    try:
        year, mo = month.split("-")
        year, mo = int(year), int(mo)
    except Exception:
        raise HTTPException(422, "month must be YYYY-MM")

    tz = biz["timezone"]
    if not is_month_allowed(year, mo, tz):
        raise HTTPException(422, "month outside allowed window (current or next month only)")

    avail = biz["availability"]
    working = set(avail.get("working_days", [1, 2, 3, 4, 5]))
    slots_template = generate_day_slots(
        avail["day_start"],
        avail["day_end"],
        int(avail["block_minutes"]),
        int(avail.get("buffer_minutes", 0)),
    )

    # Pull overrides + booked appointments for month
    import calendar as _cal

    last_day = _cal.monthrange(year, mo)[1]
    month_dates = [date(year, mo, d) for d in range(1, last_day + 1)]
    date_strs = [d.isoformat() for d in month_dates]

    overrides_cur = db.availability_overrides.find(
        {"business_id": biz["id"], "local_date": {"$in": date_strs}}
    )
    overrides = [strip_id(o) async for o in overrides_cur]
    overrides_by_date: Dict[str, List[Dict[str, Any]]] = {}
    for o in overrides:
        overrides_by_date.setdefault(o["local_date"], []).append(o)

    booked_cur = db.appointments.find(
        {
            "business_id": biz["id"],
            "status": {"$in": ["confirmed", "pending"]},
            "local_date": {"$in": date_strs},
        },
        {"local_date": 1, "local_time_block": 1, "_id": 0},
    )
    booked = {(b["local_date"], b["local_time_block"]) async for b in booked_cur}

    nowtz = now_in_tz(tz)
    today = nowtz.date()

    days_out: List[Dict[str, Any]] = []
    for d in month_dates:
        ds = d.isoformat()
        wd = iso_weekday(d)
        day_overrides = overrides_by_date.get(ds, [])
        day_block = any(o["scope"] == "day" and o["action"] == "block" for o in day_overrides)
        day_open = any(o["scope"] == "day" and o["action"] == "open" for o in day_overrides)
        is_working = (wd in working or day_open) and not day_block

        if d < today:
            is_working = False

        slot_blocks = {
            o["local_time_block"]
            for o in day_overrides
            if o["scope"] == "slot" and o["action"] == "block"
        }

        day_slots = []
        if is_working:
            for s, e in slots_template:
                tb = f"{s}-{e}"
                # Past slot today
                start_utc = to_utc(tz, d, s)
                is_past = start_utc <= nowtz.astimezone(start_utc.tzinfo)
                available = (
                    not is_past
                    and tb not in slot_blocks
                    and (ds, tb) not in booked
                )
                day_slots.append(
                    {
                        "time_block": tb,
                        "start": s,
                        "end": e,
                        "available": available,
                    }
                )
        days_out.append(
            {
                "date": ds,
                "weekday": wd,
                "is_working_day": is_working,
                "slots": day_slots,
            }
        )

    return {"month": f"{year:04d}-{mo:02d}", "timezone": tz, "days": days_out}


@api.post("/public/business/{slug}/appointments")
async def create_appointment(slug: str, body: CreateAppointmentRequest):
    biz = await get_business(slug)
    tz = biz["timezone"]

    # Date parse
    try:
        d = datetime.strptime(body.local_date, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(422, "local_date must be YYYY-MM-DD")

    if not date_in_allowed_window(d, tz):
        raise HTTPException(422, "Date outside allowed window (today through end of next month)")

    # Slot validation
    avail = biz["availability"]
    if "-" not in body.local_time_block:
        raise HTTPException(422, "Invalid time block")
    s, e = body.local_time_block.split("-")
    valid_slots = {
        f"{a}-{b}"
        for a, b in generate_day_slots(
            avail["day_start"],
            avail["day_end"],
            int(avail["block_minutes"]),
            int(avail.get("buffer_minutes", 0)),
        )
    }
    if body.local_time_block not in valid_slots:
        raise HTTPException(422, "Time block does not match business schedule")

    # Working-day check (+ overrides)
    wd = iso_weekday(d)
    working = set(avail.get("working_days", [1, 2, 3, 4, 5]))
    ov_cur = db.availability_overrides.find({"business_id": biz["id"], "local_date": body.local_date})
    overrides = [o async for o in ov_cur]
    day_block = any(o["scope"] == "day" and o["action"] == "block" for o in overrides)
    day_open = any(o["scope"] == "day" and o["action"] == "open" for o in overrides)
    slot_blocked = any(
        o["scope"] == "slot" and o["action"] == "block" and o.get("local_time_block") == body.local_time_block
        for o in overrides
    )
    if day_block or slot_blocked or not (wd in working or day_open):
        raise HTTPException(409, "This time is not available")

    # Service type check
    if body.service_type not in biz.get("service_types", []):
        raise HTTPException(422, "Unknown service_type")

    # Build appointment
    start_utc = to_utc(tz, d, s)
    end_utc = to_utc(tz, d, e)
    code = confirmation_code()
    token = new_access_token()
    appt_id = str(uuid.uuid4())

    # Service-area gate
    needs_approval = False
    status_for_appt = "confirmed"
    if check_service_area(biz, body.customer) == "out_of_area":
        policy = (biz.get("service_area") or {}).get("out_of_area_policy", "block")
        if policy == "block":
            raise HTTPException(422, "Sorry, your address is outside our service area.")
        # manual_approval
        status_for_appt = "pending"
        needs_approval = True

    doc = {
        "_id": appt_id,
        "business_id": biz["id"],
        "confirmation_code": code,
        "access_token": token,
        "customer": body.customer.model_dump(),
        "service_type": body.service_type,
        "description": body.description,
        "start_at_utc": start_utc.isoformat(),
        "end_at_utc": end_utc.isoformat(),
        "local_date": body.local_date,
        "local_time_block": body.local_time_block,
        "status": status_for_appt,
        "needs_approval": needs_approval,
        "cancellation_reason": None,
        "cancelled_by": None,
        "cancelled_at": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await db.appointments.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Slot just got booked. Please choose another time.")

    await add_appointment_history(
        appointment_id=appt_id,
        business_id=biz["id"],
        action="created",
        actor="customer",
        details={
            "status": status_for_appt,
            "local_date": body.local_date,
            "local_time_block": body.local_time_block,
            "needs_approval": needs_approval,
        },
    )

    # Send emails (MOCKED outbox)
    vars_ = {
        "customer_name": body.customer.full_name,
        "customer_email": body.customer.email,
        "customer_phone": body.customer.phone,
        "customer_address": body.customer.address,
        "service_type": body.service_type,
        "date": body.local_date,
        "time_block": body.local_time_block,
        "address": body.customer.address,
        "description": body.description or "",
        "confirmation_code": code,
        "portal_url": portal_url_for(token),
        "cancellation_note": "",
        **biz_email_vars(biz),
    }
    templates = biz.get("email_templates", {})
    tpl_c = templates.get("booking_confirmation_customer", {})
    if tpl_c:
        subject_override = (
            f"Booking request received - pending approval ({biz['name']})"
            if needs_approval else render(tpl_c.get("subject", ""), vars_)
        )
        await enqueue_email(
            db,
            business_id=biz["id"],
            to=body.customer.email,
            subject=subject_override,
            body_html=render(tpl_c.get("body_html", ""), vars_),
            template_key="booking_confirmation_customer",
        )
    tpl_a = templates.get("booking_notification_admin", {})
    if tpl_a and biz.get("contact_email"):
        admin_subject = render(tpl_a.get("subject", ""), vars_)
        if needs_approval:
            admin_subject = "[NEEDS APPROVAL - OUT OF AREA] " + admin_subject
        await enqueue_email(
            db,
            business_id=biz["id"],
            to=biz["contact_email"],
            subject=admin_subject,
            body_html=render(tpl_a.get("body_html", ""), vars_),
            template_key="booking_notification_admin",
        )

    return {
        "id": appt_id,
        "confirmation_code": code,
        "access_token": token,
        "portal_url": portal_url_for(token),
        "local_date": body.local_date,
        "local_time_block": body.local_time_block,
        "service_type": body.service_type,
        "status": status_for_appt,
        "needs_approval": needs_approval,
    }


@api.get("/public/appointments/{code}")
async def get_appointment_by_code(code: str):
    doc = await db.appointments.find_one({"confirmation_code": code})
    if not doc:
        raise HTTPException(404, "Not found")
    doc = strip_id(doc)
    biz = await get_business_by_id(doc["business_id"])
    return {
        "confirmation_code": doc["confirmation_code"],
        "status": doc["status"],
        "service_type": doc["service_type"],
        "local_date": doc["local_date"],
        "local_time_block": doc["local_time_block"],
        "customer": {"full_name": doc["customer"]["full_name"]},
        "business": {
            "name": biz["name"],
            "contact_phone": biz.get("contact_phone", ""),
            "contact_email": biz.get("contact_email", ""),
            "website": biz.get("website", ""),
            "logo_url": biz.get("logo_url", ""),
        },
    }


# ============================================================
# CUSTOMER SELF-SERVICE PORTAL
# ============================================================
async def _load_portal_appointment(token: str) -> Dict[str, Any]:
    """Resolve token -> appointment. Raises 404 (invalid) or 410 (expired)."""
    if not token or len(token) < 16:
        raise HTTPException(404, "Invalid or unknown link")
    doc = await db.appointments.find_one({"access_token": token})
    if not doc:
        raise HTTPException(404, "Invalid or unknown link")
    # Expiry rule: token expires once the appointment start time has passed.
    start = doc.get("start_at_utc")
    if isinstance(start, str):
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        except Exception:
            start_dt = None
    else:
        start_dt = start
    if start_dt and start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if start_dt and start_dt <= datetime.now(timezone.utc):
        raise HTTPException(410, "This appointment has already started or passed; the link has expired")
    return strip_id(doc)


def _portal_view(appt: Dict[str, Any], biz: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": appt["id"],
        "confirmation_code": appt["confirmation_code"],
        "status": appt["status"],
        "service_type": appt["service_type"],
        "description": appt.get("description", ""),
        "local_date": appt["local_date"],
        "local_time_block": appt["local_time_block"],
        "customer": appt["customer"],
        "business": {
            "slug": biz["slug"],
            "name": biz["name"],
            "contact_phone": biz.get("contact_phone", ""),
            "contact_email": biz.get("contact_email", ""),
            "website": biz.get("website", ""),
            "timezone": biz.get("timezone", "America/New_York"),
            "service_types": biz.get("service_types", []),
        },
    }


@api.get("/portal/{token}")
async def portal_get(token: str):
    appt = await _load_portal_appointment(token)
    biz = await get_business_by_id(appt["business_id"])
    return _portal_view(appt, biz)


@api.get("/portal/{token}/availability")
async def portal_availability(token: str, month: str = Query(..., description="YYYY-MM")):
    appt = await _load_portal_appointment(token)
    biz = await get_business_by_id(appt["business_id"])
    # Reuse the public availability endpoint internally
    return await public_availability(biz["slug"], month)


@api.post("/portal/{token}/reschedule")
async def portal_reschedule(token: str, body: PortalRescheduleRequest):
    appt = await _load_portal_appointment(token)
    if appt["status"] == "cancelled":
        raise HTTPException(409, "Cannot reschedule a cancelled appointment")
    biz = await get_business_by_id(appt["business_id"])
    tz = biz["timezone"]

    try:
        d = datetime.strptime(body.local_date, "%Y-%m-%d").date()
    except Exception:
        raise HTTPException(422, "local_date must be YYYY-MM-DD")
    if not date_in_allowed_window(d, tz):
        raise HTTPException(422, "Date outside allowed window")
    if "-" not in body.local_time_block:
        raise HTTPException(422, "Invalid time block")
    s, e = body.local_time_block.split("-")

    avail = biz["availability"]
    valid_slots = {
        f"{a}-{b}"
        for a, b in generate_day_slots(
            avail["day_start"], avail["day_end"],
            int(avail["block_minutes"]), int(avail.get("buffer_minutes", 0)),
        )
    }
    if body.local_time_block not in valid_slots:
        raise HTTPException(422, "Time block does not match business schedule")

    wd = iso_weekday(d)
    working = set(avail.get("working_days", [1, 2, 3, 4, 5]))
    ov_cur = db.availability_overrides.find(
        {"business_id": biz["id"], "local_date": body.local_date}
    )
    overrides = [o async for o in ov_cur]
    day_block = any(o["scope"] == "day" and o["action"] == "block" for o in overrides)
    day_open = any(o["scope"] == "day" and o["action"] == "open" for o in overrides)
    slot_blocked = any(
        o["scope"] == "slot" and o["action"] == "block"
        and o.get("local_time_block") == body.local_time_block
        for o in overrides
    )
    if day_block or slot_blocked or not (wd in working or day_open):
        raise HTTPException(409, "This time is not available")

    # No-op if same slot
    if appt["local_date"] == body.local_date and appt["local_time_block"] == body.local_time_block:
        return _portal_view(appt, biz)

    start_utc = to_utc(tz, d, s)
    end_utc = to_utc(tz, d, e)

    # Atomic in-place update; unique partial index will reject duplicate confirmed/pending slot
    try:
        res = await db.appointments.update_one(
            {"_id": appt["id"], "status": {"$in": ["confirmed", "pending"]}},
            {
                "$set": {
                    "local_date": body.local_date,
                    "local_time_block": body.local_time_block,
                    "start_at_utc": start_utc.isoformat(),
                    "end_at_utc": end_utc.isoformat(),
                }
            },
        )
    except DuplicateKeyError:
        raise HTTPException(409, "This time was just booked. Please choose another.")
    if res.matched_count == 0:
        # Appt may have been cancelled by admin between the load and the update
        raise HTTPException(409, "Appointment is no longer reschedulable")

    await add_appointment_history(
        appointment_id=appt["id"],
        business_id=biz["id"],
        action="rescheduled",
        actor="customer",
        details={
            "from": {
                "local_date": appt["local_date"],
                "local_time_block": appt["local_time_block"],
            },
            "to": {
                "local_date": body.local_date,
                "local_time_block": body.local_time_block,
            },
        },
    )
    updated = strip_id(await db.appointments.find_one({"_id": appt["id"]}))
    return _portal_view(updated, biz)


@api.post("/portal/{token}/cancel")
async def portal_cancel(token: str, body: PortalCancelRequest):
    appt = await _load_portal_appointment(token)
    if appt["status"] == "cancelled":
        biz = await get_business_by_id(appt["business_id"])
        return _portal_view(appt, biz)
    await db.appointments.update_one(
        {"_id": appt["id"]},
        {
            "$set": {
                "status": "cancelled",
                "cancellation_reason": body.reason,
                "cancelled_by": "customer",
                "cancelled_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    biz = await get_business_by_id(appt["business_id"])
    tpl = biz.get("email_templates", {}).get("booking_cancellation_customer", {})
    if tpl:
        vars_ = {
            "customer_name": appt["customer"]["full_name"],
            "date": appt["local_date"],
            "time_block": appt["local_time_block"],
            "cancellation_note": f" Reason: {body.reason}" if body.reason else "",
            **biz_email_vars(biz),
        }
        await enqueue_email(
            db,
            business_id=biz["id"],
            to=appt["customer"]["email"],
            subject=render(tpl.get("subject", ""), vars_),
            body_html=render(tpl.get("body_html", ""), vars_),
            template_key="booking_cancellation_customer",
        )
    # Also notify admin
    tpl_a = biz.get("email_templates", {}).get("booking_notification_admin", {})
    if tpl_a and biz.get("contact_email"):
        vars_a = {
            "customer_name": appt["customer"]["full_name"],
            "customer_email": appt["customer"]["email"],
            "customer_phone": appt["customer"]["phone"],
            "customer_address": appt["customer"].get("address", ""),
            "service_type": appt["service_type"],
            "date": appt["local_date"],
            "time_block": appt["local_time_block"],
            "description": "[CUSTOMER CANCELLED] " + (body.reason or ""),
            **biz_email_vars(biz),
        }
        await enqueue_email(
            db,
            business_id=biz["id"],
            to=biz["contact_email"],
            subject=f"[Cancelled by customer] {appt['service_type']} on {appt['local_date']}",
            body_html=render(tpl_a.get("body_html", ""), vars_a),
            template_key="booking_notification_admin",
        )
    await add_appointment_history(
        appointment_id=appt["id"],
        business_id=biz["id"],
        action="cancelled",
        actor="customer",
        details={"reason": body.reason},
    )
    updated = strip_id(await db.appointments.find_one({"_id": appt["id"]}))
    return _portal_view(updated, biz)


# ============================================================
# ADMIN AUTH
# ============================================================
@api.post("/admin/auth/login")
async def admin_login(body: LoginRequest):
    user = await db.admin_users.find_one({"email": body.email})
    if not user:
        raise HTTPException(401, "Invalid credentials")
    if user.get("locked_until"):
        locked = user["locked_until"]
        if isinstance(locked, str):
            locked_dt = datetime.fromisoformat(locked)
        else:
            locked_dt = locked
        if locked_dt > datetime.now(timezone.utc):
            raise HTTPException(429, "Account temporarily locked")
    MAX_FAILED = 5
    LOCKOUT_MINUTES = 15
    if not verify_password(body.password, user["password_hash"]):
        new_attempts = user.get("failed_attempts", 0) + 1
        update: Dict[str, Any] = {"failed_attempts": new_attempts}
        if new_attempts >= MAX_FAILED:
            from datetime import timedelta
            update["locked_until"] = (
                datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
            ).isoformat()
        await db.admin_users.update_one({"_id": user["_id"]}, {"$set": update})
        raise HTTPException(401, "Invalid credentials")

    token_version = int(user.get("token_version", 0) or 0)
    await db.admin_users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "failed_attempts": 0,
                "locked_until": None,
                "token_version": token_version,
                "last_login_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    token = issue_access_token(
        user_id=user["_id"],
        business_id=user["business_id"],
        email=user["email"],
        token_version=token_version,
    )
    biz = await get_business_by_id(user["business_id"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"id": user["_id"], "email": user["email"]},
        "business": {"id": biz["id"], "slug": biz["slug"], "name": biz["name"]},
    }


@api.post("/admin/auth/logout")
async def admin_logout(claims: dict = Depends(require_current_admin)):
    await db.admin_users.update_one(
        {"_id": claims["sub"], "business_id": claims["business_id"]},
        {"$inc": {"token_version": 1}},
    )
    await write_audit_log(
        business_id=claims["business_id"],
        action="admin.logout",
        admin_id=claims["sub"],
        target_type="admin_user",
        target_id=claims["sub"],
    )
    return {"ok": True}


@api.get("/admin/me")
async def admin_me(claims: dict = Depends(require_current_admin)):
    biz = await get_business_by_id(claims["business_id"])
    return {
        "user": {"id": claims["sub"], "email": claims["email"]},
        "business": {"id": biz["id"], "slug": biz["slug"], "name": biz["name"]},
    }


# ============================================================
# ADMIN: BUSINESS
# ============================================================
@api.get("/admin/business")
async def admin_get_business(claims: dict = Depends(require_current_admin)):
    return await get_business_by_id(claims["business_id"])


@api.patch("/admin/business")
async def admin_update_business(body: UpdateBusinessRequest, claims: dict = Depends(require_current_admin)):
    patch: Dict[str, Any] = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            patch[k] = v
    if "timezone" in patch:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(patch["timezone"])
        except Exception:
            raise HTTPException(422, "Invalid IANA timezone")
    if "website" in patch and patch["website"] and not patch["website"].startswith(("http://", "https://")):
        patch["website"] = "https://" + patch["website"]
    if not patch:
        return await get_business_by_id(claims["business_id"])
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.businesses.update_one({"_id": claims["business_id"]}, {"$set": patch})
    await write_audit_log(
        business_id=claims["business_id"],
        action="business.updated",
        admin_id=claims["sub"],
        target_type="business",
        target_id=claims["business_id"],
        details={"fields": sorted(patch.keys())},
    )
    return await get_business_by_id(claims["business_id"])


@api.patch("/admin/business/availability")
async def admin_update_availability(
    body: UpdateAvailabilityRequest, claims: dict = Depends(require_current_admin)
):
    biz = await get_business_by_id(claims["business_id"])
    current = biz.get("availability", Availability().model_dump())
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            current[k] = v
    # validate
    if current["block_minutes"] not in (60, 90, 120, 180, 240):
        raise HTTPException(422, "block_minutes must be 60/90/120/180/240")
    if not (set(current.get("working_days", [])) <= set(range(1, 8))):
        raise HTTPException(422, "working_days must be 1..7")
    await db.businesses.update_one(
        {"_id": claims["business_id"]},
        {"$set": {"availability": current, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await write_audit_log(
        business_id=claims["business_id"],
        action="availability.updated",
        admin_id=claims["sub"],
        target_type="business",
        target_id=claims["business_id"],
        details={"availability": current},
    )
    return current


@api.get("/admin/business/email-templates")
async def admin_get_templates(claims: dict = Depends(require_current_admin)):
    biz = await get_business_by_id(claims["business_id"])
    return biz.get("email_templates", {})


@api.patch("/admin/business/email-templates")
async def admin_update_templates(
    body: UpdateTemplatesRequest, claims: dict = Depends(require_current_admin)
):
    biz = await get_business_by_id(claims["business_id"])
    current = biz.get("email_templates", {})
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            current[k] = v
    await db.businesses.update_one(
        {"_id": claims["business_id"]},
        {"$set": {"email_templates": current, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    await write_audit_log(
        business_id=claims["business_id"],
        action="email_templates.updated",
        admin_id=claims["sub"],
        target_type="business",
        target_id=claims["business_id"],
        details={"fields": sorted(data.keys())},
    )
    return current


# ============================================================
# ADMIN: APPOINTMENTS
# ============================================================
@api.get("/admin/appointments")
async def admin_list_appointments(
    claims: dict = Depends(require_current_admin),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    service_type: Optional[str] = None,
    q: Optional[str] = None,
):
    query: Dict[str, Any] = {"business_id": claims["business_id"]}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        query["local_date"] = rng
    if status_filter:
        query["status"] = status_filter
    if service_type:
        query["service_type"] = service_type
    if q:
        query["$or"] = [
            {"customer.full_name": {"$regex": q, "$options": "i"}},
            {"customer.email": {"$regex": q, "$options": "i"}},
            {"customer.phone": {"$regex": q, "$options": "i"}},
            {"confirmation_code": {"$regex": q, "$options": "i"}},
        ]
    cur = db.appointments.find(query).sort([("local_date", 1), ("local_time_block", 1)])
    items = [strip_id(d) async for d in cur]
    return {"items": items, "count": len(items)}


@api.get("/admin/appointments/export.csv")
async def admin_export_csv(
    claims: dict = Depends(require_current_admin),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
    status_filter: Optional[str] = Query(default=None, alias="status"),
):
    query: Dict[str, Any] = {"business_id": claims["business_id"]}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        query["local_date"] = rng
    if status_filter:
        query["status"] = status_filter

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "confirmation_code",
            "status",
            "local_date",
            "local_time_block",
            "service_type",
            "full_name",
            "email",
            "phone",
            "address",
            "description",
            "created_at",
        ]
    )
    async for d in db.appointments.find(query).sort([("local_date", 1)]):
        c = d.get("customer", {})
        writer.writerow(
            [
                d.get("confirmation_code", ""),
                d.get("status", ""),
                d.get("local_date", ""),
                d.get("local_time_block", ""),
                d.get("service_type", ""),
                c.get("full_name", ""),
                c.get("email", ""),
                c.get("phone", ""),
                c.get("address", ""),
                (d.get("description", "") or "").replace("\n", " "),
                d.get("created_at", ""),
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="appointments.csv"'},
    )


@api.get("/admin/appointments/{appt_id}")
async def admin_get_appointment(appt_id: str, claims: dict = Depends(require_current_admin)):
    doc = await db.appointments.find_one({"_id": appt_id, "business_id": claims["business_id"]})
    if not doc:
        raise HTTPException(404, "Not found")
    return strip_id(doc)


@api.post("/admin/appointments/{appt_id}/cancel")
async def admin_cancel_appointment(
    appt_id: str, body: CancelAppointmentRequest, claims: dict = Depends(require_current_admin)
):
    doc = await db.appointments.find_one({"_id": appt_id, "business_id": claims["business_id"]})
    if not doc:
        raise HTTPException(404, "Not found")
    if doc["status"] == "cancelled":
        return strip_id(doc)
    await db.appointments.update_one(
        {"_id": appt_id},
        {
            "$set": {
                "status": "cancelled",
                "cancellation_reason": body.reason,
                "cancelled_by": "admin",
                "cancelled_at": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
    # Optionally keep the slot blocked (record an availability override)
    if body.keep_slot_blocked:
        await db.availability_overrides.insert_one({
            "_id": str(uuid.uuid4()),
            "business_id": claims["business_id"],
            "scope": "slot",
            "local_date": doc["local_date"],
            "local_time_block": doc["local_time_block"],
            "action": "block",
            "reason": f"Held after cancellation: {body.reason}" if body.reason else "Held after cancellation",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    # Notify customer
    biz = await get_business_by_id(claims["business_id"])
    tpl = biz.get("email_templates", {}).get("booking_cancellation_customer", {})
    if tpl:
        vars_ = {
            "customer_name": doc["customer"]["full_name"],
            "date": doc["local_date"],
            "time_block": doc["local_time_block"],
            "cancellation_note": f" Reason: {body.reason}" if body.reason else "",
            **biz_email_vars(biz),
        }
        await enqueue_email(
            db,
            business_id=biz["id"],
            to=doc["customer"]["email"],
            subject=render(tpl.get("subject", ""), vars_),
            body_html=render(tpl.get("body_html", ""), vars_),
            template_key="booking_cancellation_customer",
        )
    await add_appointment_history(
        appointment_id=appt_id,
        business_id=claims["business_id"],
        action="cancelled",
        actor="admin",
        actor_id=claims["sub"],
        details={"reason": body.reason, "keep_slot_blocked": body.keep_slot_blocked},
    )
    updated = await db.appointments.find_one({"_id": appt_id})
    return strip_id(updated)


@api.post("/admin/appointments/{appt_id}/status")
async def admin_update_status(
    appt_id: str, body: UpdateStatusRequest, claims: dict = Depends(require_current_admin)
):
    doc = await db.appointments.find_one({"_id": appt_id, "business_id": claims["business_id"]})
    if not doc:
        raise HTTPException(404, "Not found")
    if body.status == "cancelled":
        raise HTTPException(400, "Use the /cancel endpoint to cancel an appointment")
    # If moving FROM cancelled to confirmed, ensure the slot is free (unique partial index will block duplicates)
    update: Dict[str, Any] = {"status": body.status}
    if body.status != "cancelled" and doc.get("cancelled_at"):
        update["cancellation_reason"] = None
        update["cancelled_by"] = None
        update["cancelled_at"] = None
    try:
        await db.appointments.update_one({"_id": appt_id}, {"$set": update})
    except DuplicateKeyError:
        raise HTTPException(409, "Slot is already booked by another active appointment")
    await add_appointment_history(
        appointment_id=appt_id,
        business_id=claims["business_id"],
        action="status_changed",
        actor="admin",
        actor_id=claims["sub"],
        details={"from": doc.get("status"), "to": body.status},
    )
    updated = await db.appointments.find_one({"_id": appt_id})
    return strip_id(updated)




# ============================================================
# ADMIN: USERS (multi-user)
# ============================================================
@api.get("/admin/users")
async def admin_list_users(claims: dict = Depends(require_current_admin)):
    cur = db.admin_users.find(
        {"business_id": claims["business_id"]},
        {"password_hash": 0, "failed_attempts": 0, "locked_until": 0, "token_version": 0},
    )
    items = []
    async for u in cur:
        u["id"] = u.pop("_id")
        items.append(u)
    return {"items": items}


@api.post("/admin/users")
async def admin_create_user(body: CreateAdminRequest, claims: dict = Depends(require_current_admin)):
    existing = await db.admin_users.find_one(
        {"business_id": claims["business_id"], "email": body.email}
    )
    if existing:
        raise HTTPException(409, "User with this email already exists")
    uid = str(uuid.uuid4())
    doc = {
        "_id": uid,
        "business_id": claims["business_id"],
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": body.role,
        "failed_attempts": 0,
        "locked_until": None,
        "token_version": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.admin_users.insert_one(doc)
    await write_audit_log(
        business_id=claims["business_id"],
        action="admin_user.created",
        admin_id=claims["sub"],
        target_type="admin_user",
        target_id=uid,
        details={"email": body.email, "role": body.role},
    )
    return {"id": uid, "email": body.email, "role": body.role}


@api.delete("/admin/users/{uid}")
async def admin_delete_user(uid: str, claims: dict = Depends(require_current_admin)):
    if uid == claims["sub"]:
        raise HTTPException(400, "You cannot delete your own account")
    # Prevent deleting the last user
    count = await db.admin_users.count_documents({"business_id": claims["business_id"]})
    if count <= 1:
        raise HTTPException(400, "Cannot delete the last admin user")
    res = await db.admin_users.delete_one(
        {"_id": uid, "business_id": claims["business_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "Not found")
    await write_audit_log(
        business_id=claims["business_id"],
        action="admin_user.deleted",
        admin_id=claims["sub"],
        target_type="admin_user",
        target_id=uid,
    )
    return {"deleted": True}


@api.post("/admin/users/me/password")
async def admin_change_own_password(
    body: ChangePasswordRequest, claims: dict = Depends(require_current_admin)
):
    await db.admin_users.update_one(
        {"_id": claims["sub"]},
        {
            "$set": {"password_hash": hash_password(body.new_password)},
            "$inc": {"token_version": 1},
        },
    )
    await write_audit_log(
        business_id=claims["business_id"],
        action="admin.password_changed",
        admin_id=claims["sub"],
        target_type="admin_user",
        target_id=claims["sub"],
    )
    return {"updated": True, "reauth_required": True}


# ============================================================
# ADMIN: AVAILABILITY OVERRIDES
# ============================================================
@api.get("/admin/availability-overrides")
async def admin_list_overrides(
    claims: dict = Depends(require_current_admin),
    from_date: Optional[str] = Query(default=None, alias="from"),
    to_date: Optional[str] = Query(default=None, alias="to"),
):
    query: Dict[str, Any] = {"business_id": claims["business_id"]}
    if from_date or to_date:
        rng: Dict[str, Any] = {}
        if from_date:
            rng["$gte"] = from_date
        if to_date:
            rng["$lte"] = to_date
        query["local_date"] = rng
    cur = db.availability_overrides.find(query).sort([("local_date", 1)])
    return {"items": [strip_id(d) async for d in cur]}


@api.post("/admin/availability-overrides")
async def admin_create_override(
    body: CreateOverrideRequest, claims: dict = Depends(require_current_admin)
):
    if body.scope == "slot" and not body.local_time_block:
        raise HTTPException(422, "local_time_block required when scope=slot")
    oid = str(uuid.uuid4())
    doc = {
        "_id": oid,
        "business_id": claims["business_id"],
        "scope": body.scope,
        "local_date": body.local_date,
        "local_time_block": body.local_time_block,
        "action": body.action,
        "reason": body.reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.availability_overrides.insert_one(doc)
    await write_audit_log(
        business_id=claims["business_id"],
        action="availability_override.created",
        admin_id=claims["sub"],
        target_type="availability_override",
        target_id=oid,
        details={
            "scope": body.scope,
            "local_date": body.local_date,
            "local_time_block": body.local_time_block,
            "action": body.action,
        },
    )
    return strip_id(doc)


@api.delete("/admin/availability-overrides/{oid}")
async def admin_delete_override(oid: str, claims: dict = Depends(require_current_admin)):
    res = await db.availability_overrides.delete_one(
        {"_id": oid, "business_id": claims["business_id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(404, "Not found")
    await write_audit_log(
        business_id=claims["business_id"],
        action="availability_override.deleted",
        admin_id=claims["sub"],
        target_type="availability_override",
        target_id=oid,
    )
    return {"deleted": True}


# ---------- mount ----------
app.include_router(api)
