"""24-hour appointment reminder runner.

Production use:
    python reminders.py

Recommended schedule:
    Run hourly from a Render Scheduled Job.

Behavior:
    - Sends customer reminders for confirmed appointments starting in ~24 hours.
    - Sends one admin digest email per business for the same reminder window.
    - Marks appointments after successful enqueue/send attempt to prevent duplicates.
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from email_adapter import enqueue_email

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("scheduler.reminders")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
REMINDER_WINDOW_HOURS = int(os.environ.get("REMINDER_WINDOW_HOURS", "1"))


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _business_address(biz: Dict[str, Any]) -> str:
    addr = biz.get("address", {}) or {}
    parts = [addr.get("street", ""), addr.get("city", ""), addr.get("state", ""), addr.get("zip", "")]
    return ", ".join([p for p in parts if p])


def _customer_address(appt: Dict[str, Any]) -> str:
    customer = appt.get("customer", {}) or {}
    parts = [customer.get("address", ""), customer.get("city", ""), customer.get("zip", "")]
    return ", ".join([p for p in parts if p])


def _customer_html(appt: Dict[str, Any], biz: Dict[str, Any]) -> str:
    customer = appt.get("customer", {}) or {}
    return f"""
    <p>Hi {customer.get('full_name', 'there')},</p>
    <p>This is a reminder for your <b>{appt.get('service_type', 'service')}</b> appointment with <b>{biz.get('name', 'us')}</b>.</p>
    <ul>
      <li><b>Date:</b> {appt.get('local_date', '')}</li>
      <li><b>Time:</b> {appt.get('local_time_block', '')}</li>
      <li><b>Service address:</b> {_customer_address(appt)}</li>
      <li><b>Confirmation code:</b> {appt.get('confirmation_code', '')}</li>
    </ul>
    <p>Questions? Contact us at {biz.get('contact_phone', '')} or {biz.get('contact_email', '')}.</p>
    <p>{biz.get('name', '')}<br>{_business_address(biz)}</p>
    """


def _admin_digest_html(appts: Iterable[Dict[str, Any]], biz: Dict[str, Any]) -> str:
    rows = []
    for appt in sorted(appts, key=lambda a: (a.get("local_date", ""), a.get("local_time_block", ""))):
        customer = appt.get("customer", {}) or {}
        rows.append(
            "<li>"
            f"<b>{appt.get('local_time_block', '')}</b> — "
            f"{customer.get('full_name', 'Customer')} · {appt.get('service_type', '')}<br>"
            f"{customer.get('phone', '')} · {customer.get('email', '')}<br>"
            f"{_customer_address(appt)}"
            "</li>"
        )
    return f"""
    <p>Reminder: upcoming appointments for <b>{biz.get('name', '')}</b>.</p>
    <ul>{''.join(rows)}</ul>
    """


async def run_reminders() -> Dict[str, int]:
    client = AsyncIOMotorClient(
        MONGO_URL,
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=10000,
    )
    db = client[DB_NAME]
    try:
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(hours=24)
        window_end = window_start + timedelta(hours=REMINDER_WINDOW_HOURS)
        log.info("Reminder window UTC: %s to %s", window_start.isoformat(), window_end.isoformat())

        query = {
            "status": "confirmed",
            "reminder_24_sent": {"$ne": True},
        }
        candidates = []
        async for appt in db.appointments.find(query):
            start = _parse_dt(appt.get("start_at_utc"))
            if not start:
                continue
            if window_start <= start < window_end:
                candidates.append(appt)

        if not candidates:
            log.info("No reminder candidates found")
            return {"appointments_checked": 0, "customer_reminders": 0, "admin_digests": 0}

        business_ids = sorted({a["business_id"] for a in candidates})
        businesses = {
            b["_id"]: b
            async for b in db.businesses.find({"_id": {"$in": business_ids}})
        }

        customer_sent = 0
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for appt in candidates:
            biz = businesses.get(appt.get("business_id"))
            if not biz:
                log.warning("Skipping appointment %s: missing business", appt.get("_id"))
                continue

            customer = appt.get("customer", {}) or {}
            email = customer.get("email")
            if not email:
                log.warning("Skipping appointment %s: missing customer email", appt.get("_id"))
                continue

            subject = f"Reminder: {appt.get('service_type', 'Appointment')} on {appt.get('local_date', '')}"
            await enqueue_email(
                db,
                business_id=appt["business_id"],
                to=email,
                subject=subject,
                body_html=_customer_html(appt, biz),
                template_key="appointment_reminder_24_customer",
            )
            await db.appointments.update_one(
                {"_id": appt["_id"], "reminder_24_sent": {"$ne": True}},
                {"$set": {"reminder_24_sent": True, "reminder_24_sent_at": datetime.now(timezone.utc).isoformat()}},
            )
            grouped[appt["business_id"]].append(appt)
            customer_sent += 1

        admin_digests = 0
        for business_id, appts in grouped.items():
            biz = businesses.get(business_id)
            if not biz or not biz.get("contact_email"):
                continue
            subject = f"Reminder: {len(appts)} appointment{'s' if len(appts) != 1 else ''} coming up"
            await enqueue_email(
                db,
                business_id=business_id,
                to=biz["contact_email"],
                subject=subject,
                body_html=_admin_digest_html(appts, biz),
                template_key="appointment_reminder_24_admin_digest",
            )
            admin_digests += 1

        log.info("Reminder run complete: customer=%s admin_digests=%s", customer_sent, admin_digests)
        return {
            "appointments_checked": len(candidates),
            "customer_reminders": customer_sent,
            "admin_digests": admin_digests,
        }
    finally:
        client.close()


if __name__ == "__main__":
    result = asyncio.run(run_reminders())
    print(result)
