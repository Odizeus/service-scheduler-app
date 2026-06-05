# Service Business Scheduler — Production Architecture

**Author:** Principal Software Architect
**Status:** Approved for build
**Version:** 1.0
**Stack baseline:** React (frontend) · FastAPI (backend) · MongoDB · Kubernetes ingress

---

## 0. Decisions Log (autonomous, production-ready defaults)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Multi-tenant SaaS** (one deployment, many businesses, each identified by a `business_slug`) | Matches "support different businesses" requirement; one codebase, isolated data |
| D2 | **JWT auth (email + bcrypt password)** for admins; short-lived access + refresh | No external dependency; fits FastAPI; rotate-friendly |
| D3 | **SendGrid** as email provider via an internal `EmailAdapter` interface | Reliable transactional email; swappable for Resend/SMTP |
| D4 | **Per-business IANA timezone** (e.g. `America/Chicago`) stored on Business doc | All slots stored UTC; converted at API boundary |
| D5 | **MongoDB** (already in env) with composite unique indexes for slot reservation | Atomic `findOneAndUpdate` prevents double-booking |
| D6 | **No payments in v1** | Out of scope; designed extension point only |
| D7 | **Single admin per business in v1**, schema supports multiple | Simpler ACL, future-proof |
| D8 | **2-hour default block, configurable** (60/90/120/180 min) | Stated default, allow flex |

---

## 1. Data Models (Domain Entities)

All documents extend `BaseDocument` (id ↔ `_id` via `PyObjectId`, ISO datetimes UTC).

### 1.1 `Business` (tenant)
| Field | Type | Notes |
|---|---|---|
| `id` | ObjectId | PK |
| `slug` | string, unique, lower-kebab | Public identifier (`/book/{slug}`) |
| `name` | string | "Acme Garage Doors" |
| `service_label` | string | Editable, e.g. "Garage Door Service" |
| `contact_phone` | string | E.164 |
| `contact_email` | string | |
| `address` | object `{street, city, state, zip, country}` | |
| `timezone` | string (IANA) | `America/Chicago` default |
| `service_types` | string[] | Editable list (e.g. `["Repair","Install","Maintenance"]`) |
| `availability` | object (see §1.2) | Working days/hours/block size |
| `branding` | object `{logo_url, primary_color}` | Optional |
| `email_templates` | object (see §1.3) | Per-event templates |
| `status` | enum `active\|suspended` | |
| `created_at`, `updated_at` | ISO datetime | |

### 1.2 Embedded `availability`
```
{
  "working_days": [1,2,3,4,5],            // ISO weekday: 1=Mon
  "day_start": "10:00",                    // local time HH:MM
  "day_end":   "20:00",
  "block_minutes": 120,
  "buffer_minutes": 0,                     // optional gap between slots
  "max_concurrent_bookings_per_slot": 1
}
```

### 1.3 Embedded `email_templates` (Jinja-style placeholders)
```
{
  "booking_confirmation_customer": { "subject": "...", "body_html": "..." },
  "booking_notification_admin":    { "subject": "...", "body_html": "..." },
  "booking_cancellation_customer": { "subject": "...", "body_html": "..." },
  "booking_reminder_customer":     { "subject": "...", "body_html": "..." }
}
```
Variables: `{{customer_name}}`, `{{service_type}}`, `{{date}}`, `{{time_block}}`, `{{business_name}}`, `{{business_phone}}`, `{{address}}`, `{{description}}`.

### 1.4 `AdminUser`
| Field | Type | Notes |
|---|---|---|
| `id`, `business_id` | ObjectId | Tenant scope |
| `email` | string, unique per business | |
| `password_hash` | bcrypt | |
| `role` | enum `owner\|staff` | v1: `owner` only |
| `last_login_at` | datetime | |
| `failed_attempts`, `locked_until` | int, datetime | Brute-force protection |

### 1.5 `Appointment` (a.k.a. Booking)
| Field | Type | Notes |
|---|---|---|
| `id`, `business_id` | ObjectId | |
| `customer` | object `{full_name, email, phone, address}` | |
| `service_type` | string (from `business.service_types`) | |
| `description` | string (≤2000 chars) | |
| `start_at_utc`, `end_at_utc` | datetime | Canonical slot times |
| `local_date` | string `YYYY-MM-DD` | Business-local; used for filters/uniqueness |
| `local_time_block` | string `HH:MM-HH:MM` | Display & uniqueness |
| `status` | enum `confirmed\|cancelled\|completed\|no_show` | |
| `cancellation` | object `{by:"admin"\|"customer", reason, at}` | |
| `created_at`, `updated_at` | datetime | |
| `confirmation_code` | string (8-char) | For customer-side lookup/cancel |

### 1.6 `AvailabilityOverride` (admin blocks/opens specific dates or slots)
| Field | Type | Notes |
|---|---|---|
| `id`, `business_id` | ObjectId | |
| `scope` | enum `day\|slot` | |
| `local_date` | string `YYYY-MM-DD` | |
| `local_time_block` | string `HH:MM-HH:MM` (null when `scope=day`) | |
| `action` | enum `block\|open` | `open` to whitelist a normally-closed day |
| `reason` | string | Admin-only note |

### 1.7 `AuditLog`
`{business_id, actor_id, actor_type, action, target_type, target_id, payload, at}` — every admin mutation (cancel, block, edit business, etc.).

### 1.8 `EmailOutbox`
`{business_id, to, template_key, payload, status, attempts, last_error, scheduled_for, sent_at}` — durable queue; worker pulls and sends via SendGrid; supports reminders.

---

## 2. Database Schema (MongoDB)

### Collections
`businesses`, `admin_users`, `appointments`, `availability_overrides`, `audit_logs`, `email_outbox`.

### Indexes
| Collection | Index | Purpose |
|---|---|---|
| `businesses` | `{slug: 1}` unique | Public lookup |
| `admin_users` | `{business_id:1, email:1}` unique | Login |
| `appointments` | `{business_id:1, local_date:1, local_time_block:1, status:1}` **unique partial** where `status="confirmed"` | **No double-booking** |
| `appointments` | `{business_id:1, start_at_utc:1}` | Range queries |
| `appointments` | `{business_id:1, customer.email:1}` | Filtering |
| `appointments` | `{confirmation_code:1}` unique | Customer self-service |
| `availability_overrides` | `{business_id:1, local_date:1, local_time_block:1}` | Fast lookup |
| `email_outbox` | `{status:1, scheduled_for:1}` | Worker scan |
| `audit_logs` | `{business_id:1, at:-1}` | Admin browsing |

### Concurrency model
- Slot reservation = `db.appointments.insert_one(...)` relying on the **unique partial index** above. Race losers receive duplicate-key error → mapped to HTTP 409.
- Admin block of a slot = `availability_overrides` insert + check no `confirmed` appointment exists in the same transaction (single-doc transactions; multi-doc only where needed).

---

## 3. API Routes

All under `/api`. Two subtrees: **public** (customer booking) and **admin** (JWT-protected).
Tenant resolution: every public route includes `:slug`; admin routes derive tenant from JWT.

### 3.1 Public (customer)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/public/business/{slug}` | Business profile, service types, branding |
| GET | `/api/public/business/{slug}/availability?month=YYYY-MM` | Computed slot grid for a month (only current + next month accepted) |
| POST | `/api/public/business/{slug}/appointments` | Create booking (atomic) |
| GET | `/api/public/appointments/{confirmation_code}` | Customer status lookup |
| POST | `/api/public/appointments/{confirmation_code}/cancel` | Optional customer cancel (toggle in business config) |

### 3.2 Admin auth
| Method | Path | |
|---|---|---|
| POST | `/api/admin/auth/login` | Returns access + refresh JWT |
| POST | `/api/admin/auth/refresh` | |
| POST | `/api/admin/auth/logout` | Revokes refresh token |
| POST | `/api/admin/auth/password` | Change password |

### 3.3 Admin resources
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/admin/business` | Read tenant config |
| PATCH | `/api/admin/business` | Edit name, service_label, contact, address, service_types |
| GET/PATCH | `/api/admin/business/availability` | Days/hours/block size |
| GET/PATCH | `/api/admin/business/email-templates` | Templates per event |
| GET | `/api/admin/appointments?from&to&status&service_type&q` | Filter/search |
| GET | `/api/admin/appointments/{id}` | Detail |
| POST | `/api/admin/appointments/{id}/cancel` | Admin cancel + reason |
| GET | `/api/admin/appointments/export.csv?from&to&status` | Streamed CSV |
| GET/POST/DELETE | `/api/admin/availability-overrides` | Block day or slot, list, remove |
| GET | `/api/admin/audit-logs` | Recent admin actions |

### 3.4 Response conventions
- JSON envelope: `{ "data": ..., "error": null }` or `{ "data": null, "error": { "code", "message", "details" } }`
- Error codes: `AUTH_INVALID`, `SLOT_TAKEN` (409), `SLOT_OUT_OF_WINDOW` (422), `BUSINESS_NOT_FOUND` (404), `VALIDATION` (422), `RATE_LIMITED` (429).

---

## 4. Booking Logic (Customer Flow)

### 4.1 Pre-validation (server-side, authoritative)
1. Resolve `business` by `slug`; assert `status=active`.
2. Parse requested date in business TZ; reject if:
   - Earlier than today (business TZ) OR
   - Later than **last day of next month** (business TZ).
3. Verify ISO weekday is in `availability.working_days`, unless an `availability_overrides{action:"open"}` matches.
4. Verify slot `HH:MM-HH:MM` aligns to the generated grid from `day_start`, `day_end`, `block_minutes`.
5. Verify no `availability_overrides{action:"block"}` matches the date or slot.
6. Verify `service_type` ∈ `business.service_types`.
7. Validate customer fields: name (2-100), email (RFC), phone (E.164 normalized), address (≤300), description (≤2000). Sanitize HTML.

### 4.2 Atomic reservation
- Compute `start_at_utc`, `end_at_utc`, `local_date`, `local_time_block`.
- `confirmation_code = base32(8)`.
- Insert appointment with `status="confirmed"`.
- If duplicate-key on `(business_id, local_date, local_time_block, status=confirmed)` → return **409 SLOT_TAKEN**.
- Enqueue `EmailOutbox` rows: `booking_confirmation_customer`, `booking_notification_admin`. Optional reminder at `start_at_utc - 24h`.
- Write `audit_logs`.

### 4.3 Idempotency
- Public POST accepts header `Idempotency-Key`. If a previous successful insert exists with the same key for the business in the last 24h, return that appointment instead of re-inserting.

### 4.4 Rate limiting
- Per-IP: 10 booking attempts / 10 min.
- Per-email: 5 bookings / day per business.
- Honeypot field + optional CAPTCHA toggle in business config.

---

## 5. Admin Logic

### 5.1 Auth lifecycle
- Login: bcrypt verify → issue access JWT (15 min) + refresh JWT (14 days, rotating, stored hash in DB).
- 5 failed attempts → 15 min lock (`locked_until`).
- All admin mutations require valid access JWT scoped to `business_id` (claim).

### 5.2 Capabilities
- View/filter appointments (date range, status, service type, free-text on name/email/phone).
- Cancel appointment → status `cancelled`, frees the slot (the unique partial index excludes `cancelled`), enqueue cancellation email.
- Block a **day**: insert `availability_overrides{scope:"day", action:"block"}`. If confirmed appointments exist on that day → require explicit `cascade=true` flag → cancel each (with reason).
- Block a **slot**: same as above, scoped to `slot`.
- Edit business fields & service_types.
- Edit email templates (live preview rendered server-side with sample variables; reject unknown placeholders).
- Export CSV: stream-generated, columns: `confirmation_code,status,local_date,local_time_block,service_type,full_name,email,phone,address,description,created_at`.

### 5.3 Concurrency safety
- All admin mutations write `AuditLog`.
- Email-template edits go through schema validator (subject ≤200, body ≤20KB, allow-listed Jinja vars only — prevents SSTI).

---

## 6. Availability Logic (Slot Computation)

### 6.1 Inputs
`business.availability`, `availability_overrides`, existing **confirmed** `appointments`, and the requested month.

### 6.2 Algorithm (per requested month)
1. Reject if month is outside `[current_month, next_month]` in business TZ.
2. Enumerate each date `d` in month.
3. `is_working = (weekday(d) ∈ working_days)` then apply `open` overrides → can re-open a non-working day; apply `block` day-overrides → close it entirely.
4. If working: generate slots `[day_start, day_start+block, …)` until `day_end`, stepping `block_minutes (+ buffer)`. Each slot < day_end.
5. For each slot, mark `available=false` if:
   - slot is in the past (business TZ), or
   - matching `availability_overrides{action:"block", scope:"slot"}` exists, or
   - a `confirmed` appointment with same `(local_date, local_time_block)` exists.
6. Convert each slot's `start/end` to UTC and to local display strings; return grid.

### 6.3 Caching
- Server-side memoize per `(business_id, month)` with TTL 30s; bust on any write to appointments/overrides/availability for that business.

---

## 7. Email Workflow

### 7.1 Triggers
| Event | To | Template |
|---|---|---|
| Booking created | Customer | `booking_confirmation_customer` |
| Booking created | Admin | `booking_notification_admin` |
| Booking cancelled | Customer | `booking_cancellation_customer` |
| 24h before appointment | Customer | `booking_reminder_customer` |

### 7.2 Pipeline
1. Domain event → write `EmailOutbox` row (`status=pending`, `scheduled_for=now` or future).
2. **Worker** (FastAPI background task + APScheduler) polls every 30s: `status=pending AND scheduled_for<=now`.
3. Render template via Jinja sandboxed env with whitelisted variables.
4. Send via `EmailAdapter` (SendGrid). On success → `status=sent`. On failure → exponential backoff (1m, 5m, 30m, 2h, 12h) up to 5 attempts → `status=failed` + alert in audit log.
5. SendGrid webhook (`/api/webhooks/sendgrid`) updates delivery/bounce status.

### 7.3 Deliverability
- DKIM/SPF/DMARC configured on sending domain.
- Per-business `from_email` requires domain verification before use; fallback to platform domain (`noreply@scheduler.app`) with business name as friendly From.

---

## 8. Component Hierarchy (Frontend, React)

### 8.1 Routing
- `/` — marketing splash (optional)
- `/book/:slug` — customer booking
- `/book/:slug/confirm/:code` — confirmation/lookup
- `/admin/login`
- `/admin` (protected)
  - `/admin/appointments`
  - `/admin/calendar`
  - `/admin/availability`
  - `/admin/business`
  - `/admin/email-templates`
  - `/admin/audit`

### 8.2 Component tree
```
<App>
├── <PublicShell>
│   ├── <BusinessHeader/>         // name, contact, branding
│   ├── <BookingWizard>
│   │   ├── <MonthPicker/>        // current + next only
│   │   ├── <AvailabilityCalendar/>      // shadcn Calendar
│   │   ├── <TimeBlockGrid/>      // 2h blocks
│   │   ├── <CustomerForm/>       // RHF + zod
│   │   └── <ReviewAndConfirm/>
│   └── <ConfirmationPage/>
└── <AdminShell> (JWT-gated)
    ├── <AdminNav/>
    ├── <AppointmentsTable/>      // filters, CSV export, cancel
    ├── <AppointmentDrawer/>      // detail + actions
    ├── <CalendarView/>           // month/week
    ├── <AvailabilityEditor/>     // days/hours/block size + overrides
    ├── <BusinessSettings/>       // name, services, contact, address
    ├── <ServiceTypesEditor/>
    ├── <EmailTemplatesEditor/>   // live preview, variable picker
    └── <AuditLogViewer/>
```

### 8.3 Shadcn primitives used
`calendar`, `dialog`, `dropdown-menu`, `popover`, `select`, `input`, `textarea`, `form`, `button`, `badge`, `table`, `tabs`, `sonner` (toast), `alert-dialog` (destructive confirms).

---

## 9. State Management

- **Server state:** TanStack Query (React Query) — caching, optimistic updates, retry, background refetch. Keys: `["availability", slug, month]`, `["appointments", filters]`, `["business"]`, `["templates"]`, `["overrides"]`.
- **Auth state:** small Zustand store (`access_token`, `expires_at`, `business_id`); refresh interceptor on the Axios client.
- **Form state:** React Hook Form + Zod resolvers (single source of truth for validation, shared schemas if served from backend OpenAPI).
- **UI state:** local component state (open dialogs, table sort).
- **Real-time refresh (optional v1.1):** polling every 30s on admin appointments; v2 → SSE channel `/api/admin/stream`.

---

## 10. Security Rules

### 10.1 Authentication
- bcrypt (cost 12) for passwords.
- JWT HS256 with rotating signing key (`JWT_SECRET` env). Access 15 min; refresh 14 days, stored hashed.
- Tenant claim (`business_id`) in JWT — every admin handler asserts `resource.business_id == claim.business_id` (tenant isolation).

### 10.2 Transport & headers
- HTTPS only (ingress).
- HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, strict `Content-Security-Policy` (no inline scripts).
- CORS: allow-list `REACT_APP_BACKEND_URL` origin + business custom domains.

### 10.3 Input & abuse
- Pydantic models on every request body; rejects unknown fields.
- HTML sanitization of `description` (bleach allow-list: text only).
- Rate limiting (slowapi): public booking endpoints, login endpoint, password endpoints.
- IP + email throttling on `/admin/auth/login`.
- Audit log every admin mutation.
- Webhook signatures (SendGrid) validated.

### 10.4 Data protection
- PII (name, email, phone, address) encrypted at rest via MongoDB-managed encryption (or field-level KMS if regulated).
- Backups encrypted; rotated daily, 30-day retention.
- Right-to-erasure endpoint: admin-triggered hard-delete + audit entry (keeps anonymized stats).

### 10.5 Authorization matrix
| Action | Public | Admin (owner) |
|---|---|---|
| Read own business profile | ✅ | ✅ |
| Read availability | ✅ | ✅ |
| Create appointment | ✅ | ✅ |
| Read all appointments | ❌ | ✅ |
| Cancel any appointment | ❌ | ✅ |
| Edit business / templates / overrides | ❌ | ✅ |

---

## 11. Deployment Strategy

### 11.1 Environments
- **dev** (local docker-compose: api, web, mongo, mailhog)
- **staging** (mirrors prod, seeded demo tenant)
- **prod** (Kubernetes)

### 11.2 Topology (prod)
```
            ┌─────────────────────┐
   Users →  │  Ingress (TLS)      │
            └─────────┬───────────┘
            ┌─────────┴───────────┐
            │  Web (React static) │  CDN-cached
            └─────────────────────┘
            ┌─────────────────────┐
            │  API (FastAPI)      │  HPA 2-10 pods
            ├─────────────────────┤
            │  Worker (emails,    │  1-3 pods
            │  reminders, retries)│
            └─────────┬───────────┘
                      │
            ┌─────────┴───────────┐
            │  MongoDB (replica   │  3-node RS, daily backup
            │  set)               │
            └─────────────────────┘
External: SendGrid (SMTP/API), Sentry (errors), Better Stack (logs+uptime)
```

### 11.3 Configuration
All from environment (Kubernetes Secrets):
`MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `JWT_REFRESH_SECRET`, `SENDGRID_API_KEY`, `EMAIL_FROM`, `SENTRY_DSN`, `RATE_LIMIT_REDIS_URL`.

### 11.4 CI/CD
- GitHub Actions: lint → unit → integration (ephemeral mongo) → build images → deploy to staging → smoke tests → manual promote to prod.
- Blue/green for API (two ReplicaSets, ingress flips), rolling for worker.
- Mongo migrations via versioned scripts (`migrations/NNN_*.py`) run as Kubernetes Jobs pre-deploy.

### 11.5 Observability
- **Logs:** structured JSON (request id, business_id, user_id) → Better Stack.
- **Metrics:** Prometheus exporters — booking rate, slot-contention 409s, email queue depth, p95 latency.
- **Tracing:** OpenTelemetry → Tempo/Jaeger.
- **Alerts:** email queue depth >100 for >10m; 5xx >2%; auth failures spike; DB replica lag.

### 11.6 Backups & DR
- Mongo: daily full + hourly oplog snapshots, 30-day retention, quarterly restore drill.
- Email outbox is the system-of-record for in-flight email; survives worker restarts.
- RPO 1h, RTO 4h.

---

## 12. QA & Risk Register

### 12.1 Functional risks
| # | Risk | Severity | Mitigation |
|---|------|----------|------------|
| R1 | **Double booking** under race | High | Unique partial index + duplicate-key handling + idempotency key |
| R2 | **TZ/DST bugs** (slots disappear on DST switch) | High | Store UTC; compute slots in business TZ via `zoneinfo`; unit tests covering DST transitions for at least 3 TZs |
| R3 | **Booking outside allowed window** (current+next month) | Med | Server authoritative validation; clamp client month picker |
| R4 | **Email template injection (SSTI/XSS)** | High | Sandboxed Jinja; allow-listed variables; HTML sanitization in customer description before rendering into templates |
| R5 | **Admin blocks day with existing bookings** | Med | Confirmation dialog + `cascade` flag + auto-cancel + notify customers |
| R6 | **Customer enters invalid phone/email** | Low | Server-side regex + libphonenumber normalization |
| R7 | **CSV export with PII downloaded by wrong user** | Med | Tenant scoping in token + audit log of exports |
| R8 | **Email deliverability** (bounces, spam) | Med | SPF/DKIM/DMARC, suppression list synced from SendGrid webhooks |
| R9 | **Brute force on admin login** | High | Rate limit + lockout + alerting |
| R10 | **Tenant data leak across businesses** | Critical | Every query filters by `business_id` from JWT claim; integration test asserts cross-tenant 404 |
| R11 | **Clock skew between server and DB** | Low | NTP on all nodes; reject appointments < now-1m |
| R12 | **Idempotency replay misuse** | Low | Idempotency keys scoped per business + 24h TTL |
| R13 | **Long descriptions / large payloads** | Low | Body size limit 64KB; description length capped |

### 12.2 Test plan
- **Unit:** availability generator (DST, working days, overrides), template renderer, validators.
- **Integration:** booking happy path, 409 on race (parallel inserts), tenant isolation, CSV correctness, email outbox state machine.
- **Contract:** OpenAPI schema diff in CI.
- **E2E (Playwright):** customer books → confirmation page → admin sees it → admin cancels → email enqueued.
- **Load:** 100 concurrent bookings on same slot — exactly one succeeds.
- **Security:** OWASP ZAP baseline scan in CI; auth-fuzz on JWT; SSTI tests on template editor.

### 12.3 Accessibility & UX
- WCAG 2.1 AA: keyboard navigation on calendar, ARIA labels on slot buttons, color contrast on busy/free states (no red/green only).
- Mobile-first responsive layout; calendar collapses to list view < 640px.

---

## 13. Extension Points (Post-v1 Roadmap)

- Payments / deposits (Stripe) — add `Payment` doc, lock slot on `pending_payment` state with TTL.
- SMS reminders (Twilio) — add `SmsAdapter`, parallel to email outbox.
- Multiple staff / resources — `Resource` doc + `appointment.resource_id` in uniqueness index.
- Recurring appointments — `series_id` + generator.
- Customer accounts — optional magic-link login for history.
- iCal feed per admin / customer.
- Public review/rating after completed appointment.

---

## 14. Glossary

- **Slot / Time Block:** Contiguous bookable interval (default 2h).
- **Override:** Admin-defined exception to default availability.
- **Tenant / Business:** A single service business with isolated data.
- **Confirmation Code:** Public, non-guessable identifier for an appointment.

---

**End of architecture document. Ready for implementation hand-off.**
