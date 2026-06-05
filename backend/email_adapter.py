"""Email adapter using Resend.

If RESEND_API_KEY is empty, falls back to MOCKED mode (stores in outbox only).
When the key is set, emails are actually delivered AND mirrored in outbox for audit.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Dict

import resend

logger = logging.getLogger(__name__)

_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
_SENDER = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev").strip()

if _API_KEY:
    resend.api_key = _API_KEY
    logger.info("Resend adapter live (sender=%s)", _SENDER)
else:
    logger.warning("RESEND_API_KEY not set - email delivery is MOCKED")


def render(template: str, variables: Dict[str, str]) -> str:
    """Tiny {{var}} renderer (no logic, safe)."""
    def repl(m: re.Match) -> str:
        return str(variables.get(m.group(1).strip(), ""))
    return re.sub(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", repl, template)


async def _send_via_resend(*, to: str, subject: str, body_html: str) -> str | None:
    """Returns Resend message id on success, raises on failure."""
    params = {"from": _SENDER, "to": [to], "subject": subject, "html": body_html}
    res = await asyncio.to_thread(resend.Emails.send, params)
    return res.get("id") if isinstance(res, dict) else None


async def enqueue_email(
    db, *, business_id: str, to: str, subject: str, body_html: str, template_key: str
) -> None:
    """Persist + (optionally) deliver."""
    doc = {
        "_id": str(uuid.uuid4()),
        "business_id": business_id,
        "to": to,
        "subject": subject,
        "body_html": body_html,
        "template_key": template_key,
        "status": "queued",
        "provider_message_id": None,
        "attempts": 0,
        "last_error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": None,
    }
    if _API_KEY:
        try:
            msg_id = await _send_via_resend(to=to, subject=subject, body_html=body_html)
            doc["status"] = "sent"
            doc["provider_message_id"] = msg_id
            doc["sent_at"] = datetime.now(timezone.utc).isoformat()
            doc["attempts"] = 1
            logger.info("[resend] sent to=%s id=%s", to, msg_id)
        except Exception as e:
            doc["status"] = "failed"
            doc["last_error"] = str(e)[:500]
            doc["attempts"] = 1
            logger.error("[resend] FAILED to=%s err=%s", to, e)
    else:
        logger.info("[email-outbox MOCK] to=%s subject=%s template=%s", to, subject, template_key)

    await db.email_outbox.insert_one(doc)
