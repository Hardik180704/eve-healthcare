# EVE Healthcare — Diagnostics Booking API

A backend API for booking diagnostic tests at diagnostic centres, with user
authentication, server-side pricing, a simulated payment gateway, and an
**idempotent payment webhook**.

Built as an SDE hiring assignment. The focus is on correctness, clean
architecture, transactional integrity, and test coverage — not on feature count.

---

## Project overview

Users register and log in with JWT authentication, browse diagnostic centres
and their tests with centre-specific pricing, book a test slot, and pay for
the booking through a simulated gateway whose outcome is delivered
asynchronously via a webhook. The webhook consumer is safe against duplicate
and concurrent deliveries, and the whole payment lifecycle is protected by
database constraints and explicit state machines.

## Tech stack

| Layer     | Choice                                       |
| --------- | -------------------------------------------- |
| Language  | Python 3.12+ (developed on 3.14)             |
| Framework | FastAPI                                      |
| Database  | PostgreSQL 16                                |
| ORM       | SQLAlchemy 2.x (2.0-style, typed)            |
| Migrations| Alembic                                      |
| Config    | Pydantic v2 + pydantic-settings              |
| Auth      | JWT (PyJWT) + bcrypt password hashing        |
| Testing   | pytest + FastAPI TestClient (httpx)          |
| Linting   | Ruff                                         |
| Runtime   | Docker + Docker Compose                      |

## Architecture

A deliberately simple layered architecture:

```
app/
├── main.py              # FastAPI app factory: routers, middleware, error handlers
├── seed.py              # Idempotent seed script (python -m app.seed)
├── api/
│   ├── deps.py          # get_current_user (JWT → User) dependency
│   └── routes/          # Thin HTTP layer: auth, diagnostics, bookings, payments
├── core/
│   ├── config.py        # Pydantic settings from environment/.env
│   ├── database.py      # Engine, SessionLocal, Base, get_db dependency
│   ├── security.py      # bcrypt hashing + JWT encode/decode
│   ├── exceptions.py    # Domain exceptions (404/409/422/401) → JSON responses
│   └── logging.py       # Logging configuration
├── models/              # SQLAlchemy models + state machines (enums.py)
├── schemas/             # Pydantic request/response schemas
└── services/            # Business logic: booking_service, payment_service
```

- **Routes** parse/validate HTTP input and call services.
- **Services** own business rules, authorization checks, and transactions.
- **Models** own schema constraints (FKs, uniques, indexes) and the legal
  state transitions.
- Responses are never crafted from client input where money is involved:
  prices and amounts always come from database rows.

## Project structure

```
.
├── alembic/                  # Migration environment + versions
├── alembic.ini
├── app/                      # Application package (see above)
├── tests/                    # pytest suite (auth, diagnostics, bookings, payments)
├── .env.example              # Copy to .env
├── Dockerfile
├── docker-compose.yml        # PostgreSQL + API, migrations applied on boot
├── pyproject.toml            # Ruff + pytest configuration
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Setup instructions (local, without Docker)

Requires Python 3.12+ and a running PostgreSQL (any modern version).

```bash
git clone https://github.com/Hardik180704/eve-healthcare.git
cd eve-healthcare

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env          # then edit values if your DB differs
```

### Environment variables

| Variable                       | Purpose                                        | Example                                            |
| ------------------------------ | ---------------------------------------------- | -------------------------------------------------- |
| `DATABASE_URL`                 | SQLAlchemy URL (psycopg v3 driver)             | `postgresql+psycopg://eve:eve_password@localhost:5432/eve_healthcare` |
| `JWT_SECRET_KEY`               | Secret used to sign JWTs                       | long random string                                 |
| `JWT_ALGORITHM`                | JWT algorithm                                  | `HS256`                                            |
| `ACCESS_TOKEN_EXPIRE_MINUTES`  | Token lifetime                                 | `1440`                                             |
| `ENVIRONMENT` / `DEBUG`        | App flags                                      | `development` / `true`                             |
| `POSTGRES_*`                   | Used by docker-compose for the DB container    | `eve` / `eve_password` / `eve_healthcare` / `5432` |
| `PAYMENT_GATEWAY_URL`          | Reserved for a real gateway integration        | `http://localhost:9999`                            |

Generate a strong secret with:
`python -c "import secrets; print(secrets.token_hex(32))"`

### Database setup

```bash
createdb eve_healthcare        # or use docker compose up -d db (below)
```

### Migration commands

```bash
alembic upgrade head                       # apply all migrations
alembic revision --autogenerate -m "..."   # create a new migration
alembic downgrade -1                       # roll back the last migration
```

The test suite runs `alembic upgrade head` against a dedicated test database
(`eve_healthcare_test`) on every run, so migrations are continuously verified.

### Seed instructions

```bash
python -m app.seed
```

Creates two diagnostic centres, six tests, and centre-specific prices.
The script is idempotent — run it as many times as you like.

### Run the API

```bash
uvicorn app.main:app --reload
# http://localhost:8000  (Swagger UI at /docs)
```

## Docker instructions

```bash
docker compose up -d --build
```

This starts PostgreSQL and the API. On boot the API container runs
`alembic upgrade head` before starting uvicorn, so the schema is always
up to date. Then seed (optional) and use the API:

```bash
docker compose exec api python -m app.seed
curl http://localhost:8000/health
# {"status":"ok","database":"connected"}
```

Swagger UI: <http://localhost:8000/docs>

Stop everything: `docker compose down` (add `-v` to wipe the database volume).

## Testing instructions

```bash
# against the local database server (creates/migrates eve_healthcare_test itself)
pytest

# or with the venv from the repo
.venv/bin/pytest -v
```

75 tests cover authentication, diagnostics, booking authorization,
state transitions, payments, webhook idempotency (including duplicate and
concurrent webhook delivery), and error handling.

## Swagger documentation

Interactive docs at `/docs` (OpenAPI schema at `/openapi.json`). Every
endpoint documents its auth requirement, expected status codes, and schemas.
Use the **Authorize** button (HTTPBearer) to paste a login token and call
protected endpoints directly from the UI.

## Authentication flow

1. `POST /auth/signup` with `{full_name, email, password}` — passwords are
   hashed with bcrypt (8–64 chars, max 72 bytes).
2. `POST /auth/login` returns `{access_token, token_type: "bearer"}` — a JWT
   signed with `JWT_SECRET_KEY`, subject = user id.
3. Send `Authorization: Bearer <token>` on protected endpoints.
   `get_current_user` resolves and validates the token server-side.
4. Expired/invalid/missing tokens return `401`. The user id **always** comes
   from the token — never from the request body or query string.

## API endpoint documentation

| Method | Path                                  | Auth | Description                                          |
| ------ | ------------------------------------- | ---- | ---------------------------------------------------- |
| GET    | `/health`                             | no   | Liveness + DB connectivity                            |
| POST   | `/auth/signup`                        | –    | Register (201, 409 duplicate email)                   |
| POST   | `/auth/login`                         | –    | Obtain JWT (401 on bad credentials)                   |
| GET    | `/auth/me`                            | JWT  | Current user                                          |
| POST   | `/diagnostics/centres`                | JWT  | Create a centre (201)                                 |
| GET    | `/diagnostics/centres`                | JWT  | List centres                                          |
| GET    | `/diagnostics/centres/{id}`           | JWT  | Centre detail incl. tests + prices (404 if unknown)   |
| POST   | `/diagnostics/tests`                  | JWT  | Create a test (201, 409 duplicate code)               |
| GET    | `/diagnostics/tests`                  | JWT  | List tests                                            |
| POST   | `/diagnostics/centres/{id}/tests`     | JWT  | Offer a test at a centre with a price (201/404/409)   |
| GET    | `/diagnostics/centres/{id}/tests`     | JWT  | Tests offered at a centre with prices                 |
| POST   | `/bookings`                           | JWT  | Book a test (201; 404 unknown centre/test/not offered)|
| GET    | `/bookings`                           | JWT  | List **my** bookings                                  |
| GET    | `/bookings/{booking_id}`              | JWT  | Get my booking (404 if unknown **or not mine**)       |
| POST   | `/bookings/{booking_id}/cancel`       | JWT  | Cancel a PENDING booking (409 otherwise)              |
| POST   | `/payments`                           | JWT  | Initiate payment for my PENDING booking               |
| POST   | `/payments/webhook`                   | none | Gateway webhook; idempotent by `event_id`             |

There is **no** endpoint that lets a client set a booking status directly.

## Example requests

```bash
# 1. Sign up
curl -s -X POST http://localhost:8000/auth/signup \
  -H 'Content-Type: application/json' \
  -d '{"full_name": "Alice Example", "email": "alice@example.com", "password": "secret123"}'

# 2. Log in
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "secret123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. Create a centre, a test, and a price (any authenticated user may do this
#    in this simulation; see assumptions)
curl -X POST http://localhost:8000/diagnostics/centres \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "CityCare Diagnostics", "address": "12 MG Road", "city": "Bengaluru"}'

curl -X POST http://localhost:8000/diagnostics/tests \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code": "CBC", "name": "Complete Blood Count"}'

curl -X POST http://localhost:8000/diagnostics/centres/1/tests \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"test_id": 1, "price": "350.00"}'

# 4. Book (price is determined by the server)
curl -X POST http://localhost:8000/bookings \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"centre_id": 1, "test_id": 1, "appointment_time": "2027-01-15T10:00:00Z"}'

# 5. Pay
curl -X POST http://localhost:8000/payments \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"booking_id": "<booking id from step 4>"}'
```

## Example responses

`POST /bookings` → `201`:

```json
{
  "id": "b7597506-433e-41c5-859c-eb243ec2e072",
  "user_id": "67c07c98-cfe6-441c-9701-ef466d2efc93",
  "centre_id": 1,
  "test_id": 1,
  "appointment_time": "2027-01-15T10:00:00Z",
  "amount": "350.00",
  "status": "PENDING",
  "created_at": "2026-09-28T08:32:05Z",
  "updated_at": "2026-09-28T08:32:05Z"
}
```

`POST /payments` → `201`:

```json
{ "id": 1, "booking_id": "b7597506-…", "amount": "350.00", "status": "PENDING", "created_at": "…" }
```

`POST /payments/webhook` → `200` (first delivery):

```json
{
  "event_id": "evt-123",
  "payment_id": 1,
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED",
  "duplicate": false,
  "message": "Event processed; booking updated"
}
```

Same event delivered again → `200`, state untouched:

```json
{
  "event_id": "evt-123",
  "payment_id": 1,
  "payment_status": "SUCCESS",
  "booking_status": "CONFIRMED",
  "duplicate": true,
  "message": "Duplicate event ignored"
}
```

## Database / schema design

```
users                      users own bookings; identity comes from the JWT
├── id            UUID PK (default gen uuid)
├── email         UNIQUE, indexed        ← login identity
├── full_name
├── password_hash                        ← bcrypt, never returned by the API
└── created_at / updated_at

diagnostic_centres         id PK, name, address, city (indexed)
diagnostic_tests           id PK, code UNIQUE (e.g. "CBC"), name, description
centre_tests               association + centre-specific pricing
├── (centre_id, test_id) UNIQUE
├── price NUMERIC(10,2) CHECK via schema (client price is never trusted)
└── FKs to centre/test with ON DELETE CASCADE

bookings
├── id            UUID PK                ← non-enumerable public id
├── user_id       FK → users.id, indexed (+ composite index (user_id, status))
├── centre_id     FK → diagnostic_centres.id
├── test_id       FK → diagnostic_tests.id
├── appointment_time timestamptz (validated to be in the future)
├── amount        NUMERIC(10,2)          ← snapshot of centre_tests.price at creation
├── status        booking_status enum    ← PENDING | CONFIRMED | FAILED | CANCELLED
└── created_at / updated_at

payments
├── id            serial PK              ← basis of the deterministic simulation
├── booking_id    FK → bookings.id, UNIQUE  ← exactly one payment attempt per booking
├── amount        NUMERIC(10,2)          ← copied from booking.amount
├── status        payment_status enum    ← PENDING | SUCCESS | FAILED
└── created_at / updated_at

payment_webhook_events
├── event_id      UNIQUE, indexed        ← the idempotency key (DB-enforced)
├── payment_id    FK → payments.id, indexed
├── status        reported outcome ("SUCCESS"/"FAILED")
├── payload       JSONB (full original webhook body, for audit)
└── received_at
```

The prices a centre charges live in `centre_tests`, not on tests: the same
test can have different prices at different centres. Bookings snapshot the
price so later price changes never affect existing bookings.

## Booking state machine

```
            ┌──────────┐
 created →  │ PENDING  │
            └────┬─────┘
   payment SUCCESS │      payment FAILED    user cancels
        ┌──────────┴──────────┬───────────────┐
        ▼                     ▼               ▼
  ┌───────────┐         ┌──────────┐   ┌───────────┐
  │ CONFIRMED │         │  FAILED  │   │ CANCELLED │
  └───────────┘         └──────────┘   └───────────┘
     terminal              terminal        terminal
```

- Legal transitions are encoded in `BOOKING_TRANSITIONS` (app/models/enums.py).
- `CONFIRMED`, `FAILED`, `CANCELLED` are terminal; no transition leaves them.
- Cancellation is blocked while a payment for the booking is still PENDING.
- Clients cannot set booking status; only the payment lifecycle and the
  cancel endpoint can change it.

## Payment flow

1. `POST /payments` with the booking id. The server verifies the booking is
   owned by the JWT user, is PENDING, and has no payment yet
   (`payments.booking_id` UNIQUE enforces one attempt per booking at the DB
   level, including under concurrent requests). It creates a payment in
   PENDING and snapshots the booking amount.
2. The **simulated gateway** determines the outcome deterministically from
   the payment id: **odd id → SUCCESS, even id → FAILED** (documented, no
   randomness, easy to reproduce in tests/demos).
3. The gateway delivers the outcome to `POST /payments/webhook` with
   `{event_id, payment_id, status, amount}`. Processing:
   - payment PENDING + SUCCESS → payment SUCCESS, booking CONFIRMED
   - payment PENDING + FAILED  → payment FAILED, booking FAILED
   - same status again (new event id) → 200, no state change
   - conflicting outcome (e.g. FAILED for an already-SUCCESS payment) → 409,
     state preserved, event recorded for audit
   - amount mismatch with the stored payment → 409, state preserved
   - unknown payment → 404 (event not recorded)
   - malformed payload → 422 (event not recorded)
4. Payment/booking updates and the event insert happen in **one transaction**;
   the payment and booking rows are locked (`SELECT … FOR UPDATE`) so
   concurrent events are serialized.

## Webhook idempotency approach

The hard requirement: the same webhook delivered any number of times must
never be applied twice, and no in-memory state may be used.

- `payment_webhook_events.event_id` has a **database-level UNIQUE
  constraint**. The event row is inserted inside the same transaction that
  applies the state change — an "insert-to-claim" pattern.
- A duplicate delivery fails the insert with an integrity error → the
  transaction rolls back → the API responds 200 (`duplicate: true`) with the
  current state and changes nothing. A duplicate can never be applied twice
  because it can never even be recorded twice.
- Concurrent duplicate deliveries are safe: the payment row is locked with
  `FOR UPDATE`, so processors are serialized; the loser's insert hits the
  unique constraint and is treated as a duplicate. The response for a given
  `event_id` is deterministic (a redelivered conflicting event replays 409).
- No in-memory sets, dicts, or caches are involved; state lives only in
  PostgreSQL. This is verified by the concurrency tests, which deliver the
  same event from multiple threads simultaneously.

## Authorization model

- Identity comes exclusively from the JWT (`sub` claim → users.id).
- Booking/payment access requires ownership: a booking that doesn't exist and
  one owned by another user both return **404**, so IDs cannot be probed
  (no 403-vs-404 existence leak).
- Prices are resolved server-side from `centre_tests`; client-sent amounts
  are ignored. Webhook amounts must match the stored payment.
- Passwords are bcrypt-hashed; hashes and tokens are never logged or returned.

## Important assumptions

- **No roles system.** Any authenticated user may create centres/tests and
  set prices. Real systems would gate this behind an admin role; out of scope.
- **One payment attempt per booking.** If a payment fails, the booking is
  terminal (FAILED); the user creates a new booking to try again. This keeps
  the state machine strict and unambiguous.
- **Simulated gateway.** The outcome rule (odd id → SUCCESS, even id → FAILED)
  replaces a real gateway. A real integration would swap the parity rule for
  an HTTP call; the webhook contract stays the same.
- **Webhook authentication is not implemented.** A production webhook must
  verify a gateway signature (e.g. HMAC) and would sit behind network
  restrictions; out of scope here.
- Amounts are decimal strings (e.g. `"350.00"`) end-to-end to avoid float
  precision issues; the DB stores NUMERIC(10,2).

## Known limitations

- No pagination on list endpoints (fine for the assignment's data volumes).
- No admin role / audit UI; centre/test management is open to any user.
- No notification e-mails, no rescheduling, no refunds.
- The simulated gateway is synchronous-by-convention: its "async" outcome is
  delivered by calling the webhook endpoint yourself.
- Uvicorn runs single-process by default here; horizontal scaling would need
  a production server setup (workers behind a proxy).

## Potential future improvements

- HMAC signature verification on the webhook (+ timestamp replay window).
- Roles (admin/staff/user) with scoped permissions for catalogue management.
- Paginated, filterable listing endpoints; booking search by date range.
- Outbox pattern / background retries for webhook-driven side effects.
- Observability: request IDs, structured JSON logs, metrics.
- CI pipeline running Ruff + pytest on every push.
