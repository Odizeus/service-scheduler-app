"""Pydantic models for the Service Business Scheduler."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Literal
from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ---------- Embedded objects ----------
class Address(BaseModel):
    street: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = "US"


class ServiceArea(BaseModel):
    cities: List[str] = []
    zip_codes: List[str] = []
    counties: List[str] = []
    out_of_area_policy: Literal["block", "manual_approval"] = "block"


class Availability(BaseModel):
    working_days: List[int] = [1, 2, 3, 4, 5]  # 1=Mon ... 7=Sun
    day_start: str = "10:00"
    day_end: str = "20:00"
    block_minutes: int = 120
    buffer_minutes: int = 0


class EmailTemplate(BaseModel):
    subject: str
    body_html: str


class EmailTemplates(BaseModel):
    booking_confirmation_customer: EmailTemplate = EmailTemplate(
        subject="Your booking is confirmed - {{business_name}}",
        body_html=(
            "<p>Hi {{customer_name}},</p>"
            "<p>Your <b>{{service_type}}</b> appointment with <b>{{business_name}}</b> "
            "is confirmed for <b>{{date}}</b> at <b>{{time_block}}</b>.</p>"
            "<p>Confirmation code: <b>{{confirmation_code}}</b></p>"
            "<p><a href=\"{{portal_url}}\">Manage your appointment</a> "
            "(reschedule or cancel anytime before it starts).</p>"
            "<p>{{business_name}}<br>"
            "{{business_address}}<br>"
            "{{business_phone}} · {{business_email}}<br>"
            "{{business_website}}</p>"
        ),
    )
    booking_notification_admin: EmailTemplate = EmailTemplate(
        subject="New booking - {{service_type}} on {{date}}",
        body_html=(
            "<p>New appointment booked at {{business_name}}.</p>"
            "<ul>"
            "<li>Customer: {{customer_name}} ({{customer_email}}, {{customer_phone}})</li>"
            "<li>Service: {{service_type}}</li>"
            "<li>When: {{date}} {{time_block}}</li>"
            "<li>Customer address: {{customer_address}}</li>"
            "<li>Notes: {{description}}</li>"
            "</ul>"
        ),
    )
    booking_cancellation_customer: EmailTemplate = EmailTemplate(
        subject="Your appointment was cancelled",
        body_html=(
            "<p>Hi {{customer_name}},</p>"
            "<p>Your appointment with {{business_name}} on {{date}} at {{time_block}} "
            "has been cancelled.{{cancellation_note}}</p>"
            "<p>Questions? Reach us at {{business_phone}} or {{business_email}}.</p>"
        ),
    )


# ---------- Documents ----------
class Business(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    slug: str
    name: str
    service_label: str = "Service"
    contact_phone: str = ""
    contact_email: str = ""
    website: str = ""
    logo_url: str = ""
    address: Address = Field(default_factory=Address)
    timezone: str = "America/New_York"
    service_types: List[str] = ["Repair", "Installation", "Maintenance"]
    service_area: ServiceArea = Field(default_factory=ServiceArea)
    availability: Availability = Field(default_factory=Availability)
    email_templates: EmailTemplates = Field(default_factory=EmailTemplates)
    status: Literal["active", "suspended"] = "active"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AdminUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    business_id: str
    email: EmailStr
    password_hash: str
    role: Literal["owner", "staff"] = "owner"
    failed_attempts: int = 0
    locked_until: Optional[datetime] = None
    token_version: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CustomerInfo(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=5, max_length=30)
    address: str = Field(min_length=2, max_length=300)
    city: Optional[str] = Field(default=None, max_length=100)
    zip: Optional[str] = Field(default=None, max_length=20)
    county: Optional[str] = Field(default=None, max_length=100)


class Appointment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    business_id: str
    confirmation_code: str
    access_token: Optional[str] = None
    customer: CustomerInfo
    service_type: str
    description: str = Field(max_length=2000)
    start_at_utc: datetime
    end_at_utc: datetime
    local_date: str  # YYYY-MM-DD in business TZ
    local_time_block: str  # HH:MM-HH:MM in business TZ
    status: Literal["pending", "confirmed", "cancelled", "completed", "no_show"] = "confirmed"
    needs_approval: bool = False
    cancellation_reason: Optional[str] = None
    cancelled_by: Optional[Literal["admin", "customer"]] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    history: List[dict] = Field(default_factory=list)


class AvailabilityOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    business_id: str
    scope: Literal["day", "slot"]
    local_date: str  # YYYY-MM-DD
    local_time_block: Optional[str] = None  # required when scope=="slot"
    action: Literal["block", "open"] = "block"
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------- Request payloads ----------
class CreateAppointmentRequest(BaseModel):
    customer: CustomerInfo
    service_type: str
    description: str = Field(default="", max_length=2000)
    local_date: str  # YYYY-MM-DD
    local_time_block: str  # HH:MM-HH:MM


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CreateAdminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Literal["owner", "staff"] = "staff"


class ChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class UpdateBusinessRequest(BaseModel):
    name: Optional[str] = None
    service_label: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    address: Optional[Address] = None
    service_types: Optional[List[str]] = None
    service_area: Optional[ServiceArea] = None
    timezone: Optional[str] = None


class UpdateAvailabilityRequest(BaseModel):
    working_days: Optional[List[int]] = None
    day_start: Optional[str] = None
    day_end: Optional[str] = None
    block_minutes: Optional[int] = None
    buffer_minutes: Optional[int] = None


class UpdateTemplatesRequest(BaseModel):
    booking_confirmation_customer: Optional[EmailTemplate] = None
    booking_notification_admin: Optional[EmailTemplate] = None
    booking_cancellation_customer: Optional[EmailTemplate] = None


class CreateOverrideRequest(BaseModel):
    scope: Literal["day", "slot"]
    local_date: str
    local_time_block: Optional[str] = None
    action: Literal["block", "open"] = "block"
    reason: str = ""


class CancelAppointmentRequest(BaseModel):
    reason: str = ""
    keep_slot_blocked: bool = False


class PortalCancelRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class PortalRescheduleRequest(BaseModel):
    local_date: str
    local_time_block: str


class UpdateStatusRequest(BaseModel):
    status: Literal["pending", "confirmed", "cancelled", "completed", "no_show"]
