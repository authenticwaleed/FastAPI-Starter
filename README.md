# FastAPI Starter

A small FastAPI service built the way a production one is: PostgreSQL behind
SQLAlchemy 2, Alembic migrations, JWT authentication, and a layered
architecture where routes handle HTTP, services hold business rules and
repositories own the queries.

[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) records how it was built,
phase by phase, and why each decision went the way it did.

## Requirements

- Python 3.11+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/)

## Getting started

```bash
cp .env.example .env

# Generate a signing key and put it in .env as JWT_SECRET_KEY.
python -c "import secrets; print(secrets.token_urlsafe(32))"

uv sync
createdb fastapi_starter
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Interactive documentation is then at http://localhost:8000/docs.

## Commands

| Task | Command |
| --- | --- |
| Run the tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type check | `uv run mypy` |
| Lint, format and types together | `uv run pre-commit run --all-files` |

Install the git hook once with `uv run pre-commit install`, and the lint,
format and type checks run on every commit. The tests are deliberately not
among them: they need a database, and a commit hook is the wrong place to
discover that. CI runs both halves — the hooks' checks, then
`alembic upgrade head` and `pytest`.

The suite uses its own database, named after the configured one with `_test`
appended. It is created and migrated automatically on the first run, and each
test is rolled back afterwards, so it never touches application data. Set
`TEST_DATABASE_URL` to point it somewhere else.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Simple health check |
| GET | `/api/v1/health/live` | Liveness probe |
| GET | `/api/v1/health/ready` | Readiness probe, checks the database |
| POST | `/api/v1/auth/register` | Create an account |
| POST | `/api/v1/auth/login` | Exchange credentials for a token |
| GET | `/api/v1/auth/me` | The current user, requires a token |
| POST | `/api/v1/users` | Create a user |
| GET | `/api/v1/users` | List users, paginated |
| GET | `/api/v1/users/{id}` | Fetch one user |
| PATCH | `/api/v1/users/{id}` | Update name, email or password |
| DELETE | `/api/v1/users/{id}` | Delete a user |

Protected endpoints take `Authorization: Bearer <token>`.

Every error, including validation failures and unknown paths, has the same
shape:

```json
{ "detail": "User not found", "code": "user_not_found" }
```

Branch on `code`, which is stable; `detail` is prose and may be reworded.

## Configuration

All configuration is read from the environment, with `.env` as a convenience
for local development. Nothing has a default that would be unsafe in
production.

| Variable | Default | Notes |
| --- | --- | --- |
| `DATABASE_URL` | **required** | Must use the `postgresql+psycopg://` form |
| `JWT_SECRET_KEY` | **required** | Changing it invalidates every issued token |
| `ENVIRONMENT` | `development` | `development`, `staging` or `production` |
| `DEBUG` | `false` | SQL echo. Refused in production |
| `LOG_LEVEL` | `INFO` | Standard Python level names |
| `LOG_FORMAT` | per environment | `text` in development, `json` elsewhere |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | |
| `CORS_ORIGINS` | empty | Comma separated. Empty means no cross-origin access |
| `CORS_ALLOW_CREDENTIALS` | `true` | Cannot be combined with `*` origins |
| `ALLOWED_HOSTS` | `*` | Host header allow-list. Must be explicit in production |

Settings are validated at startup, and production is held to a stricter
standard than a laptop: `DEBUG`, a wildcard origin and a wildcard host are
all refused when `ENVIRONMENT=production`, so a misconfiguration fails
immediately instead of quietly widening the service's exposure.

## Docker

```bash
export JWT_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose up --build
```

> **Verified.** The stack has been built and run: PostgreSQL comes up healthy,
> `migrate` applies the migrations and exits, the API answers
> `/health/ready` over the compose network, and data survives
> `docker compose down` followed by `up`.
>
> `.github/workflows/ci.yml` is the one thing still unproven: every command
> in it passes locally, but a workflow only executes on a push.

- The API is on port 8000; PostgreSQL is published on **5433**, so it does
  not collide with an instance already running on the host.
- A one-off `migrate` service applies migrations, and the API waits for it to
  finish before starting.
- Data lives in the `postgres-data` volume and survives `docker compose down`.
  `docker compose down -v` deletes it.
- No configuration is baked into the image: `.dockerignore` excludes `.env`,
  and compose refuses to start without `JWT_SECRET_KEY` in the environment.
  On older Docker Compose versions a missing value is reported as
  "invalid interpolation format" rather than by name.

## Running in production

### Startup procedure

1. Supply configuration as environment variables from your platform's secret
   store. Do not ship a `.env` file.
2. Apply migrations as a **separate step**, before the new version starts:

   ```bash
   alembic upgrade head
   ```

3. Start the server:

   ```bash
   uvicorn app.main:app \
     --host 0.0.0.0 --port 8000 \
     --workers 4 \
     --proxy-headers --forwarded-allow-ips='*'
   ```

### Migrations

Run them as their own job, never from the application's entrypoint. With more
than one replica, an entrypoint has every instance racing to migrate the same
database. Review what `alembic revision --autogenerate` produces before
applying it — it detects table and column changes, not intent, and a rename
looks exactly like a drop plus an add.

For a change that removes something, expand and contract across two releases:
add the new column and start writing to it, deploy, backfill, then drop the
old one in a later release. That keeps the old and new code able to run
against the same schema while a rollout is in progress.

### Health checks

Point the liveness probe at `/api/v1/health/live` and the readiness probe at
`/api/v1/health/ready`. Only readiness touches the database: if liveness did,
a database outage would make the orchestrator restart every healthy process
it has, which cannot possibly help.

### Behind a proxy or load balancer

TLS terminates at the proxy. Run uvicorn with `--proxy-headers` so the
application sees the original scheme and client address rather than the
proxy's, and restrict `--forwarded-allow-ips` to the proxy where you can. Set
`ALLOWED_HOSTS` to the hostnames the service answers to, and `CORS_ORIGINS`
to the origins your frontend is served from.

### Workers and connections

Each worker is a separate process with its own connection pool, so the
database sees `workers × (pool_size + max_overflow)` connections at peak —
with SQLAlchemy's defaults that is 15 per worker. Keep the total below
PostgreSQL's `max_connections`, or put PgBouncer in front.

### Secrets

`.env` is gitignored and excluded from the image. `JWT_SECRET_KEY` is a
`SecretStr`, so it is masked in reprs and is never written to a log. Rotating
it invalidates every token that is currently valid, which logs everyone out.

## Troubleshooting

**`alembic upgrade head` fails with "Can't locate revision identified by ..."**

The database is stamped with a revision that is no longer in
`alembic/versions/` — usually a migration that was applied locally and then
deleted before it was ever committed. Confirm the schema already matches the
models:

```bash
uv run alembic check
```

If it reports no new operations, record the current revision without running
any DDL:

```bash
uv run alembic stamp head
```

If it does report drift, drop the database and migrate it from scratch.

**The tests fail to connect, or want to create a database**

The suite creates its own `<name>_test` database on first run, which needs a
PostgreSQL role allowed to `CREATE DATABASE`. Point `TEST_DATABASE_URL` at a
database you have already created if that is not available.

## Deliberately not included

Worth knowing before this is used for something real:

- **No refresh tokens or revocation.** A token is valid until it expires;
  logging out is the client discarding it.
- **The `/users` endpoints are unauthenticated.** Who may list, edit or
  delete users is an authorisation question this starter does not answer.
- **No rate limiting**, on login or anywhere else.

## Layout

```text
app/
├── main.py             application factory, lifespan, middleware
├── api/
│   ├── router.py       assembles the versioned router
│   ├── errors.py       domain errors -> HTTP responses, in one place
│   ├── dependencies/   reusable request-scoped dependencies
│   └── routes/         HTTP concerns only
├── core/               settings, security, logging, domain exceptions
├── db/                 engine, session factory, declarative base
├── models/             SQLAlchemy tables
├── repositories/       every query lives here
├── schemas/            request and response contracts
└── services/           business rules, and the transaction boundary

alembic/                migrations
tests/                  api, services, repositories, core, db
```
