# FastAPI Starter — Implementation Plan

This document is the roadmap for evolving this project from a small FastAPI starter into a clean, production-ready backend while learning each concept step by step.

The goal is **not** to add every abstraction at once. We will introduce a new layer only when the project actually needs it.

---

## 1. Current Project State

The project already contains the basic FastAPI structure:

```text
app/
├── main.py
├── api/
│   ├── router.py
│   └── routes/
│       ├── health.py
│       └── users.py
├── core/
│   ├── config.py
│   └── security.py
├── db/
│   ├── base.py
│   └── session.py
├── models/
│   └── user.py
├── repositories/
│   └── user_repository.py
├── schemas/
│   └── user.py
└── services/
    └── user_service.py

alembic/
├── env.py
└── versions/

tests/
├── conftest.py
├── test_database_connection.py
├── test_db_session.py
├── test_health.py
├── test_migrations.py
├── test_security.py
├── test_user_model.py
├── test_user_repository.py
├── test_user_service.py
└── test_users.py
```

### Implemented

- [x] `uv` based Python project
- [x] FastAPI application factory
- [x] API version prefix: `/api/v1`
- [x] Central API router
- [x] Health endpoint
- [x] Pydantic request/response schemas
- [x] User service layer
- [x] FastAPI dependency injection
- [x] Basic `404` handling
- [x] Request validation
- [x] PostgreSQL persistence via SQLAlchemy 2.x
- [x] Alembic migrations
- [x] Repository layer
- [x] Full user CRUD with pagination
- [x] Duplicate-email handling (`409`)
- [x] Argon2id password hashing
- [x] Pytest tests
- [x] Environment-based settings
- [x] `.env.example`

### Current storage

Users are persisted in PostgreSQL through a repository layer.

```text
FastAPI process
    ↓
UserService
    ↓
UserRepository
    ↓
SQLAlchemy
    ↓
PostgreSQL
```

Users now survive a restart and are shared across workers. Passwords are stored only as Argon2id hashes.

---

# 2. Target Architecture

As the application grows, we will move toward this request flow:

```text
HTTP Request
     ↓
Router
     ↓
Pydantic Schema
     ↓
Dependency Injection
     ↓
Service Layer
     ↓
Repository Layer
     ↓
SQLAlchemy
     ↓
PostgreSQL
```

For authenticated endpoints:

```text
HTTP Request
     ↓
JWT / Authentication Dependency
     ↓
Router
     ↓
Service
     ↓
Repository
     ↓
Database
```

The final project will approximately look like:

```text
app/
├── main.py
│
├── api/
│   ├── router.py
│   ├── dependencies/
│   │   └── auth.py
│   └── routes/
│       ├── health.py
│       ├── auth.py
│       └── users.py
│
├── core/
│   ├── config.py
│   ├── security.py
│   ├── exceptions.py
│   └── logging.py
│
├── db/
│   ├── base.py
│   └── session.py
│
├── models/
│   └── user.py
│
├── schemas/
│   ├── auth.py
│   └── user.py
│
├── repositories/
│   └── user_repository.py
│
├── services/
│   ├── auth_service.py
│   └── user_service.py
│
└── utils/

tests/
├── conftest.py
├── api/
├── services/
└── repositories/

alembic/
Dockerfile
docker-compose.yml
.env.example
pyproject.toml
```

We will **not** create all of these files immediately. Each phase below introduces only what is required.

---

# 3. Phase 1 — PostgreSQL Database

## Goal

Replace temporary in-memory storage with PostgreSQL.

### We will learn

- What PostgreSQL is responsible for
- Application vs database responsibilities
- Database connection URLs
- Environment variables for database configuration
- Local database setup

### Planned configuration

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/fastapi_starter
```

### New dependencies

Expected packages:

```bash
uv add sqlalchemy psycopg[binary]
```

### Acceptance criteria

- [x] PostgreSQL runs locally
- [x] Application can connect to PostgreSQL
- [x] Database URL comes from settings
- [x] No credentials are hard-coded in Python

---

# 4. Phase 2 — SQLAlchemy 2.x

## Goal

Introduce SQLAlchemy as the database ORM/toolkit.

### New files

```text
app/db/
├── __init__.py
├── base.py
└── session.py
```

### Responsibilities

`session.py`

```text
engine creation
session factory
database session dependency
```

`base.py`

```text
SQLAlchemy declarative base
shared model metadata
```

### Important concepts

We will learn the difference between:

```text
Pydantic schema       SQLAlchemy model
---------------       ----------------
API data contract     Database table mapping
```

They are related, but they are **not the same thing**.

### Acceptance criteria

- [x] SQLAlchemy engine is configured
- [x] Database session can be injected into FastAPI endpoints/services
- [x] Session lifecycle is handled correctly
- [x] Database configuration stays outside route files

---

# 5. Phase 3 — User Database Model

## Goal

Persist users in a real database table.

### New file

```text
app/models/user.py
```

The model will eventually contain fields similar to:

```text
id
name
email
hashed_password
is_active
created_at
updated_at
```

### Important rule

We will never store plain-text passwords.

Bad:

```text
password = "secret123"
```

Database should contain something like:

```text
hashed_password = "...password hash..."
```

### Acceptance criteria

- [x] User table model exists
- [x] Email is unique
- [x] Primary key is configured
- [x] Timestamps are handled consistently
- [x] Password field stores only a hash

---

# 6. Phase 4 — Alembic Database Migrations

## Goal

Manage database schema changes safely.

### Dependency

```bash
uv add alembic
```

### Why migrations matter

We should not manually edit production databases whenever a model changes.

Instead:

```text
Change SQLAlchemy model
        ↓
Create Alembic migration
        ↓
Review migration
        ↓
Apply migration
        ↓
Database schema updated
```

### Commands we will learn

```bash
alembic revision --autogenerate -m "create users table"
alembic upgrade head
alembic downgrade -1
```

### Acceptance criteria

- [x] Alembic initialized
- [x] User table migration generated
- [x] Migration can upgrade a clean database
- [x] Migration can be rolled back

---

# 7. Phase 5 — Repository Layer

## Goal

Separate database queries from business logic.

### New file

```text
app/repositories/user_repository.py
```

### Responsibility split

```text
Router
HTTP concerns

Service
Business rules

Repository
Database queries

SQLAlchemy Model
Database mapping
```

For example:

```text
UserService.create_user()
        ↓
checks whether email is allowed/available
        ↓
UserRepository.create()
        ↓
SQLAlchemy
        ↓
PostgreSQL
```

### Why we are adding it now

A repository layer before a database would have been unnecessary abstraction. Once several database queries exist, it starts earning its place.

### Acceptance criteria

- [x] Routes contain no raw SQLAlchemy queries
- [x] User service contains business logic
- [x] User repository owns persistence operations
- [x] Repository methods are independently testable

---

# 8. Phase 6 — Complete User CRUD

## Goal

Implement proper user resource operations.

### Planned endpoints

```text
POST   /api/v1/users
GET    /api/v1/users/{user_id}
GET    /api/v1/users
PATCH  /api/v1/users/{user_id}
DELETE /api/v1/users/{user_id}
```

### We will add

- User creation
- Fetch one user
- Fetch many users
- Update user
- Delete user
- Duplicate-email handling
- Pagination

### Possible query example

```text
GET /api/v1/users?page=1&page_size=20
```

`page` starts at 1 and `page_size` is capped at 100, so a client cannot ask
for the whole table in one request.

### Response shape

The list endpoint returns an envelope rather than a bare array, so a client
can work out how many pages exist without a second request:

```text
{
  "items": [ ...users... ],
  "total": 137,
  "page": 1,
  "page_size": 20
}
```

### Acceptance criteria

- [x] CRUD endpoints work against PostgreSQL
- [x] Duplicate emails return a useful error
- [x] Missing users return `404`
- [x] List endpoint supports pagination
- [x] Response schemas do not expose sensitive fields

---

# 9. Phase 7 — Password Hashing

## Goal

Store passwords safely before implementing login.

### We will learn

- Password hashing vs encryption
- Password verification
- Why plain-text passwords must never be stored

### Planned flow

```text
Registration password
       ↓
Password hashing function
       ↓
Hashed password
       ↓
Database
```

Login:

```text
Submitted password
       ↓
Verify against stored hash
       ↓
Valid / Invalid
```

### Acceptance criteria

- [x] Plain password is accepted only as request input
- [x] Plain password is never persisted
- [x] Password hash is never returned through API responses
- [x] Password verification is covered by tests

---

# 10. Phase 8 — JWT Authentication

## Goal

Add registration/login and protected endpoints.

### Planned endpoints

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

### Login flow

```text
email + password
      ↓
validate credentials
      ↓
create access token
      ↓
return JWT
```

Protected request:

```text
Authorization: Bearer <token>
      ↓
auth dependency
      ↓
verify JWT
      ↓
load current user
      ↓
endpoint executes
```

### New files

```text
app/core/security.py
app/api/dependencies/auth.py
app/api/routes/auth.py
app/schemas/auth.py
app/services/auth_service.py
```

### Acceptance criteria

- [ ] User can register
- [ ] User can log in
- [ ] Valid token grants access
- [ ] Invalid/expired token is rejected
- [ ] Protected endpoint receives current user through dependency injection

---

# 11. Phase 9 — Centralized Exceptions

## Goal

Stop scattering application errors across every route.

### Example domain/application errors

```text
UserNotFoundError
EmailAlreadyExistsError
InvalidCredentialsError
InactiveUserError
```

These can then be translated into HTTP responses centrally.

### Desired separation

Instead of service code knowing HTTP status codes:

```text
Service
    ↓
raises EmailAlreadyExistsError
    ↓
FastAPI exception handler
    ↓
409 Conflict
```

### Acceptance criteria

- [ ] Business logic is not tightly coupled to `HTTPException`
- [ ] Error responses have a consistent shape
- [ ] Common errors are handled centrally

---

# 12. Phase 10 — Logging

## Goal

Add useful application logs without dumping random `print()` statements everywhere.

### We will log

- Application startup/shutdown
- Important request failures
- Database failures
- Authentication failures where appropriate
- Unexpected exceptions

### We will avoid logging

- Passwords
- JWT secrets
- Database passwords
- Sensitive personal data unless explicitly required and handled safely

### Acceptance criteria

- [ ] Application uses Python logging rather than debugging `print()` calls
- [ ] Log level can be controlled by environment
- [ ] Secrets are not written to logs

---

# 13. Phase 11 — Better Testing

## Goal

Move from basic endpoint tests to a reliable test suite.

### Test categories

```text
Unit tests
    ↓
service/business logic

Repository tests
    ↓
database behavior

API/integration tests
    ↓
HTTP request → full application flow
```

### Planned structure

```text
tests/
├── conftest.py
├── api/
│   ├── test_auth.py
│   └── test_users.py
├── services/
│   └── test_user_service.py
└── repositories/
    └── test_user_repository.py
```

### We will learn

- Pytest fixtures
- Dependency overrides
- Test database isolation
- Testing authenticated endpoints
- Testing failures, not only happy paths

### Acceptance criteria

- [ ] Tests do not depend on production database data
- [ ] Each test can run independently
- [ ] Authentication behavior is tested
- [ ] CRUD success and error paths are tested

---

# 14. Phase 12 — CORS and API Security Basics

## Goal

Prepare the API to work safely with a frontend/client application.

### Topics

- CORS configuration
- Allowed origins
- Trusted hosts
- Environment-specific settings
- Secure secrets
- Input validation
- Authentication boundaries

### Important rule

Do not blindly use permissive production settings such as unrestricted origins unless that behavior is intentionally required.

### Acceptance criteria

- [ ] Development and production settings can differ
- [ ] Allowed origins come from configuration
- [ ] Secrets are supplied through environment variables

---

# 15. Phase 13 — Docker

## Goal

Make local development and deployment reproducible.

### Files

```text
Dockerfile
docker-compose.yml
.dockerignore
```

### Planned services

```text
Docker Compose
├── api
└── postgres
```

### Development flow

```text
docker compose up
       ↓
FastAPI + PostgreSQL
```

### Acceptance criteria

- [ ] API runs inside a container
- [ ] PostgreSQL runs as a separate service
- [ ] Application can connect using container networking
- [ ] Database data uses persistent volume storage
- [ ] Secrets/config are not baked into the image

---

# 16. Phase 14 — Code Quality Tooling

## Goal

Automatically catch formatting, linting, and type issues.

### Tools we may add

```text
Ruff
Pyright or mypy
pre-commit
```

### Checks

```text
formatting
linting
imports
type checking
tests
```

### Acceptance criteria

- [ ] Formatting is automated
- [ ] Lint checks pass
- [ ] Important modules are type checked
- [ ] Tests are runnable through one documented command

---

# 17. Phase 15 — CI Pipeline

## Goal

Automatically verify every code change.

A basic CI pipeline should run:

```text
Install dependencies
        ↓
Lint
        ↓
Type check
        ↓
Run tests
        ↓
Pass / Fail
```

Possible platform:

```text
GitHub Actions
```

### Acceptance criteria

- [ ] CI runs for pull requests/pushes
- [ ] Broken tests fail the pipeline
- [ ] Lint/type failures fail the pipeline

---

# 18. Phase 16 — Production Readiness

## Goal

Prepare the service for a real deployment environment.

### Topics

- Production configuration
- Application startup behavior
- Database migration strategy
- Health/readiness endpoints
- Reverse proxy/load balancer considerations
- HTTPS termination
- Structured logging
- Worker/process strategy
- Graceful shutdown
- Environment secrets

### Health endpoints may evolve into

```text
/health/live
/health/ready
```

Where:

```text
liveness  → process is alive
readiness → service dependencies are usable
```

### Acceptance criteria

- [ ] Production startup procedure is documented
- [ ] Database migrations are applied safely
- [ ] Health checks are deployment-friendly
- [ ] Secrets are not committed to Git

---

# 19. Planned API End State

An early complete API may contain:

```text
Health
------
GET    /api/v1/health

Authentication
--------------
POST   /api/v1/auth/register
POST   /api/v1/auth/login
GET    /api/v1/auth/me

Users
-----
POST   /api/v1/users
GET    /api/v1/users
GET    /api/v1/users/{user_id}
PATCH  /api/v1/users/{user_id}
DELETE /api/v1/users/{user_id}
```

Later features should be added only after the foundation above is stable.

---

# 20. Implementation Order

We will follow this order:

```text
1.  Current FastAPI foundation             ✅
2.  PostgreSQL                             ✅
3.  SQLAlchemy 2.x                         ✅
4.  User database model                    ✅
5.  Alembic migrations                     ✅
6.  Repository layer                       ✅
7.  Full user CRUD                         ✅
8.  Password hashing                       ✅
9.  JWT authentication
10. Centralized error handling
11. Logging
12. Stronger tests / test database
13. CORS + security configuration
14. Docker
15. Ruff + type checking + pre-commit
16. CI pipeline
17. Production readiness
```

We should resist jumping directly to JWT, Docker, or deployment before understanding persistence and database sessions. Each phase depends on concepts from the previous one.

---

# 21. Rules We Will Follow

Throughout the project:

1. **Routes handle HTTP concerns.**
2. **Schemas define request/response contracts.**
3. **Services contain business logic.**
4. **Repositories contain persistence logic once a database exists.**
5. **SQLAlchemy models represent database tables.**
6. **Dependencies provide reusable request-scoped resources.**
7. **Secrets never belong in source code.**
8. **Passwords are never stored in plain text.**
9. **Every important feature gets tests.**
10. **We add abstractions only when they solve a real problem.**

---

# 22. Next Step

The next implementation task is:

> **Phase 8 — JWT authentication: add `/auth/register`, `/auth/login` and a protected `/auth/me`, with an auth dependency that resolves the current user from a bearer token.**

Groundwork that already exists: `verify_password()` in `app/core/security.py` is
implemented and tested, and simply has no caller until login uses it.

Still to add: token creation/decoding, JWT settings (secret, algorithm, expiry)
in `Settings`, `app/schemas/auth.py`, `app/services/auth_service.py`,
`app/api/dependencies/auth.py` and `app/api/routes/auth.py`.

We will implement it incrementally so every new file and abstraction has a clear purpose.