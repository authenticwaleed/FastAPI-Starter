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
| Evaluate the assistant | `uv run python -m app.evaluation` |

The evaluation is not part of the test suite and not part of CI: it calls
the embedding provider and the model for real, which costs money and gives
a slightly different answer every time. What CI runs is the regression
test beside it, which puts the same dataset through the same runner with
fakes and proves the harness still works.

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
| GET | `/api/v1/account` | Read your own account |
| PATCH | `/api/v1/account` | Change your own name or email |
| POST | `/api/v1/account/change-password` | Replace your password |
| DELETE | `/api/v1/account` | Delete your own account |
| POST | `/api/v1/workspaces` | Create a workspace; you become its owner |
| GET | `/api/v1/workspaces` | List the workspaces you belong to |
| GET | `/api/v1/workspaces/{workspace_id}` | Read one workspace |
| PATCH | `/api/v1/workspaces/{workspace_id}` | Update it, if you administer it |
| DELETE | `/api/v1/workspaces/{workspace_id}` | Close it, if you own it |
| GET | `…/{workspace_id}/members` | List the team |
| PATCH | `…/{workspace_id}/members/{user_id}` | Change a member's role |
| DELETE | `…/{workspace_id}/members/{user_id}` | Remove a member, or leave |
| POST | `…/{workspace_id}/invitations` | Invite somebody by email |
| GET | `…/{workspace_id}/invitations` | List invitations sent |
| DELETE | `…/{workspace_id}/invitations/{invitation_id}` | Revoke one |
| GET | `/api/v1/invitations/{token}` | Preview a link, no account needed |
| POST | `/api/v1/invitations/{token}/accept` | Take the seat |
| POST | `…/{workspace_id}/contacts` | Add an end customer |
| GET | `…/{workspace_id}/contacts` | List them, filtered and paged |
| GET | `…/{workspace_id}/contacts/{contact_id}` | Read one |
| PATCH | `…/{workspace_id}/contacts/{contact_id}` | Update one |
| POST | `…/{workspace_id}/conversations` | Open a thread with a contact |
| GET | `…/{workspace_id}/conversations` | The inbox, filtered and paged |
| GET | `…/conversations/{conversation_id}` | Read one |
| PATCH | `…/conversations/{conversation_id}` | Change status or AI mode |
| POST | `…/conversations/{conversation_id}/assign` | Hand it over, or unassign |
| POST | `…/conversations/{conversation_id}/read` | Clear the unread count |
| POST | `…/conversations/{conversation_id}/takeover` | Take it from the assistant |
| POST | `…/conversations/{conversation_id}/release-to-ai` | Hand it back |
| GET | `…/conversations/{conversation_id}/events` | Who has had it, and why |
| POST | `…/conversations/{conversation_id}/close` | Close it |
| POST | `…/conversations/{conversation_id}/reopen` | Reopen it |
| GET | `…/conversations/{conversation_id}/messages` | Read the thread |
| POST | `…/conversations/{conversation_id}/messages` | Reply |
| POST | `…/conversations/{conversation_id}/ai-reply` | Have the assistant answer |
| GET | `…/conversations/{conversation_id}/ai-responses` | What it decided, and why |
| POST | `…/{workspace_id}/knowledge/sources` | Add a source of knowledge |
| GET | `…/{workspace_id}/knowledge/sources` | List them |
| GET | `…/knowledge/sources/{source_id}` | Read one |
| DELETE | `…/knowledge/sources/{source_id}` | Delete it and its documents |
| POST | `…/{workspace_id}/knowledge/documents` | Add knowledge as text |
| POST | `…/knowledge/documents/faq` | Add a question and its answer |
| POST | `…/knowledge/documents/upload` | Upload a PDF or text file |
| GET | `…/{workspace_id}/knowledge/documents` | List them, filtered and paged |
| GET | `…/knowledge/documents/{document_id}` | Read one |
| DELETE | `…/knowledge/documents/{document_id}` | Delete it and its chunks |
| POST | `…/{workspace_id}/knowledge/search` | Ask the knowledge base directly |
| GET | `…/{workspace_id}/analytics/overview` | The dashboard's headline row |
| GET | `…/{workspace_id}/analytics/conversations` | Volume and responsiveness |
| GET | `…/{workspace_id}/analytics/ai` | What the assistant did, and cost |
| POST | `…/{workspace_id}/integrations/whatsapp/connect` | Connect a number |
| GET | `…/{workspace_id}/integrations/whatsapp` | What is connected |
| DELETE | `…/{workspace_id}/integrations/whatsapp` | Disconnect it |
| GET | `/api/v1/webhooks/whatsapp` | Meta's subscription handshake |
| POST | `/api/v1/webhooks/whatsapp` | Meta's deliveries |

Protected endpoints take `Authorization: Bearer <token>`. The two webhook
routes are not: their caller is Meta, which has no account here.

Everything under `/account` acts on the account the token belongs to. None
of those paths takes a user id, which is deliberate: there is no id for a
caller to substitute, and so no ownership check for anyone to forget.

A **workspace** is the tenant boundary: one customer business, with the
users who work in it attached through memberships. Four roles exist,
ranked `owner` > `admin` > `agent` > `viewer`.

What a role admits is declared in the route's signature, through one of
`WorkspaceMemberDep`, `WorkspaceAdminDep` or `WorkspaceOwnerDep` — all
built by `require_workspace_role(...)` in
`app/api/dependencies/workspace.py`. No handler compares a role itself,
which is enforced by a test: a check written inside one handler is a rule
the next handler can silently fail to repeat.

Acting on a *person* needs rank rather than a fixed role. You may manage
somebody you outrank strictly, which is the plan's "owner manages admins,
admin manages agents" as one rule — so an admin cannot demote another
admin, and cannot promote anyone into the rank they hold themselves. An
owner may act on anyone, including another owner. Any member may leave a
workspace without needing rank at all.

A workspace must keep at least one owner: the last one cannot be demoted,
removed, or walk out, and cannot delete their account either. Every route
into a workspace's settings needs an owner, so a workspace without one is
a business its own members are locked out of. To leave, invite a
successor at `owner` first.

**Invitations** are how anyone else gets in. The link's token is 32 bytes
of CSPRNG output; what is stored is its SHA-256 digest, so the table is
not a set of working links. SHA-256 rather than Argon2 deliberately — the
value is high-entropy with no dictionary to attack, and an unsalted digest
is what lets acceptance be one indexed lookup instead of a slow
verification against every outstanding row.

The token is returned by the create call and by nothing else, because
nothing else can reproduce it. Once there is an email to put the link in,
that is where it should go and the field should stop being returned.

An invitation admits only the address it names, so forwarding the link
does not hand somebody else a seat. Accepting is single-use: `accepted_at`
is set in the same transaction that creates the membership. An expired
link answers `410`, not `404` — the holder had a real link, and "ask for
another" is different advice from "check the address".

**Contacts** are the first table holding somebody else's customers rather
than this product's users. A contact is identified within its workspace by
phone number, stored in E.164 — so a number typed with spaces in the
dashboard and the same number arriving from WhatsApp are one row, not two.
That uniqueness is **per workspace and deliberately not global**: one
person can be a customer of two businesses using this product, and those
are two contacts who must not see each other's history.

Reading contacts takes any membership; adding and editing takes `agent` or
above, because handling the people who message a business is an agent's
job rather than an administrative act.

**Conversations** are threads with a contact, and a contact has at most
one that is not closed — enforced by a partial unique index, so two agents
opening a thread with the same customer at the same moment cannot split
that customer's history in half. Closed conversations accumulate as
history without blocking the next one.

Two composite foreign keys make cross-tenant rows impossible rather than
merely refused: a conversation's `(workspace_id, contact_id)` points at
`contacts (workspace_id, id)`, and a message's
`(workspace_id, conversation_id)` at `conversations (workspace_id, id)`.
The database rejects a conversation naming another workspace's contact
even if every check in the application were skipped.

Messages carry a `sequence` — a database-assigned counter, never exposed —
because ordering by id would be random (UUIDs) and `created_at` alone is
not enough: Postgres fixes `now()` for a transaction, so a webhook writing
three messages from one payload gives all three the same timestamp.

A reply is written and committed *before* the provider is called. A crash
between the two loses a delivery, which retries and a human can recover
from; the other order loses the message, and nobody can tell it existed.
With no number connected it stays `queued` — nothing drains that queue
yet.

**The inbox** returns a row a dashboard can render without asking again:
the contact, the assignee and a preview of the last message are embedded
in each conversation, fetched by two joins and a lateral rather than by
three lookups per row. A test asserts the request costs the same number of
queries with six rows as with two.

That query is only fast because `ix_conversations_inbox_order` matches the
sort **exactly** — `DESC NULLS LAST` and both tie-breakers included. An
index that orders even slightly differently cannot be used to order by, so
Postgres would join the whole workspace, sort it, and return thirty rows:
measured at 499ms for twenty thousand conversations, against 1ms with the
index as written.

`status` may be repeated (`?status=open&status=pending` is the default
view), `assigned_to=me` needs no user id, and `search` matches the contact
rather than the message text.

**Unread** is a property of the conversation, not of each person reading
it. This is a shared inbox: a badge still lit on four screens after a
colleague has dealt with a customer is a queue that gets worked four
times. A customer's message raises the count — by a SQL expression, so two
arriving at once are two — and replying or `POST …/read` clears it. The
team's own messages never raise it.

**Knowledge** is what the assistant is allowed to know. Text, an FAQ pair,
or an uploaded PDF is normalised, hashed, chunked with overlap at sentence
and paragraph boundaries, embedded and stored — inside the request, so a
document that comes back `ready` is one the assistant can already answer
from. The hash makes re-uploading the same file a `409` rather than a
second copy of every answer's evidence.

Embeddings are stored as a plain `double precision[]`, normalised to unit
length, so similarity is a dot product over `unnest` and needs no
extension on any machine. The plan names pgvector and says the storage
choice can evolve: that swap is one method in
`KnowledgeRepository._score` plus a migration, and nothing above it
changes. A chunk whose vector is a different length is skipped rather than
scored on the overlap, so changing `EMBEDDING_DIMENSIONS` degrades to
"finds nothing" instead of to a plausible wrong number.

**Retrieval** is always scoped to one workspace, in the `WHERE` clause,
with no method that will answer without it — the plan calls a cross-tenant
knowledge leak a severe security failure, and the way to make one
impossible is for the scoping not to be a decision any caller gets to
make. Finding nothing is an empty list and not an error.

**The assistant** is a deterministic pipeline, not an agent: eligibility,
retrieval, prompt, model, validation, decision, in ordinary control flow
with every branch visible. It ends in one of `answered`, `suggested`,
`handoff`, `blocked` or `failed`, and every one of them writes a row to
`ai_response_logs` with the prompt version, the chunks it was given and
what it cost — the rows worth reading are the ones where it decided not to
answer.

With nothing retrieved it hands over rather than answering from the
model's general knowledge. Whether the reply is *fit to send* is settled
before the conversation's `ai_mode` is consulted, so switching a workspace
to `automatic` cannot send something `suggest_only` would have withheld. A
model that is down records `failed` and leaves the question untouched in
the thread.

An arriving message is what runs it. The webhook records the delivery,
answers 200, and schedules the assistant afterwards — drafting takes
seconds, and Meta reads a slow response as a failed delivery and sends the
whole envelope again. Only messages a delivery *actually wrote* are
followed up, so a repeat delivery produces no repeat answer.

The webhook and the button are treated differently on purpose. Arriving on
its own, the assistant answers a given message once and then replays that
decision for ever. Asked for by a person, it runs again — the reason to
press the button is that something has changed. The one decision never
repeated either way is a reply that was actually sent.

**Handoff** is the plan's mandatory half of that. `takeover` switches the
assistant off for a conversation, assigns it to the caller and records
why; nothing turns it back on but `release-to-ai`. The assistant hands
over on its own too, when it has no evidence or is not confident, and then
stays out until released — a thread waiting for a person is not one to
start answering into unannounced. That handoff leaves `ai_mode` alone: one
question the knowledge base could not cover is not grounds for rewriting a
setting the business chose.

`state` collapses the two fields a dashboard would otherwise have to
combine — `ai_active`, `suggest_only`, `human_active`, `ai_disabled`.
Every change of hands is a row in `conversation_events`, which is where
"how often does the assistant give up on this customer" is answerable.

**Evaluation** is `uv run python -m app.evaluation`: the dataset in
`app/evaluation/cases.json` run through the real pipeline against the real
providers, reporting grounded-answer rate, handoff precision, incorrect
and no-answer rates, retrieval success, latency and tokens — stamped with
the prompt version, so two versions of the instructions can be compared
rather than argued about. Hallucinations are printed as sentences rather
than counted, because what improves the next prompt is reading the one
that was wrong. It exits non-zero on any failure, and rolls back
everything it wrote. The suite runs the same dataset through the same
runner with fakes, which tests the harness without spending anything.

**Analytics** aggregates in SQL, never in Python — these are counts over
every conversation a business has ever had. Ranges are inclusive at both
ends and bucketed in the workspace's own timezone: nine in the evening in
Karachi belongs to that day, not to the next one because UTC has rolled
over. An unknown timezone is refused rather than quietly treated as UTC.
Average first response time excludes threads nobody has answered — folding
those in would make a busy morning look like an improvement — and reports
`null` rather than `0` when there is nothing to average.

**WhatsApp** is reached through `MessagingProvider`, a Protocol with three
methods. Everything Meta-shaped — the Graph URL, the webhook envelope, the
signature header — lives in `app/integrations/messaging/whatsapp.py` and
nothing above it knows any of that.

Access tokens are encrypted with Fernet before they are stored, decrypted
for the length of one call, and appear in no response and no log line.
`ENCRYPTION_KEY` is optional in development and refused-if-missing in
production.

Every delivery is verified by HMAC-SHA256 over the **raw request body** —
which is why that one route is `async` and reads `await request.body()`.
Re-serialising the parsed JSON would change the bytes and fail every
honest delivery.

Ingestion is idempotent per message, not per delivery: a provider retries
whenever it does not get a prompt 200, including when it did and the
response was lost. Anything that authenticates gets a 200, even payloads
that cannot be used — a webhook answering anything else is one the
provider sends again all day. Status notifications only move a message
forward, since `sent` can arrive after `read` when a delivery was
retried.

A workspace nobody has a membership of answers `404`, not `403`, whether or
not it exists. Telling those apart would turn the id in the URL into a way
of asking which businesses have accounts here. A member whose *role* is
insufficient does get a `403`: they have already proved they belong.

`DELETE /workspaces/{id}` closes a workspace rather than erasing it — the
status becomes `cancelled`, it leaves every listing, and every path to it
starts answering `404`. The rows survive, because a workspace is about to
own contacts, conversations and message history that one call should not
be able to destroy.

Every error, including validation failures and unknown paths, has the same
shape:

```json
{ "detail": "Email already registered", "code": "email_already_exists" }
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
| `ENCRYPTION_KEY` | unset | Encrypts provider tokens. Required in production |
| `WHATSAPP_VERIFY_TOKEN` | unset | Echoed back during Meta's webhook setup |
| `WHATSAPP_APP_SECRET` | unset | Signs every delivery. Without it, none authenticate |
| `VOYAGE_API_KEY` | unset | Embeddings. Without it, ingestion refuses clearly |
| `EMBEDDING_MODEL` | `voyage-3.5-lite` | Changing it invalidates stored vectors |
| `EMBEDDING_DIMENSIONS` | `1024` | Same — a changed length matches nothing |
| `ANTHROPIC_API_KEY` | unset | The assistant. Without it, AI replies answer `failed` |
| `ANTHROPIC_MODEL` | `claude-opus-5` | |
| `ANTHROPIC_MAX_TOKENS` | `1024` | A WhatsApp reply is a few sentences |

The last six are optional and checked where they are used: the inbox works
perfectly well with no knowledge base and no assistant. A blank value
counts as unset, from every source — a compose file writing
`KEY: ${KEY:-}` produces an empty string, and treating that as "set"
starts a deployment with a key that cannot do anything.

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
  logging out is the client discarding it, and changing a password does not
  sign anyone out.
- **No administration API.** A user can manage their own account and nothing
  else.
- **Nothing drains the queued messages.** A reply sent while no number is
  connected stays `queued` forever; a retry worker is a later phase.
- **Only text.** Images, audio, documents and interactive templates are
  parsed out of webhooks and skipped rather than stored empty.
- **`ai_mode`** is stored on every conversation and read by nothing.
- **No email is sent.** An invitation's link has to be handed over by
  whoever created it, because the API returns the token once for exactly
  that reason. Delivering it is a later phase.
- **Invitation tokens travel in the URL path**, which is what makes a link
  a link. This application redacts them from its own log lines, but an
  access log written by uvicorn, a proxy or a CDN sits outside that and
  will record the full path. Anywhere this is deployed for real needs an
  access-log policy that redacts `/invitations/*`.
- **Phone numbers must already be international.** `+92 300 1234567` and
  `0092 300 1234567` both work; a bare national number like `0300 1234567`
  is refused, because resolving it needs a country the product does not
  record yet. When that changes, the fix is a `country` on the workspace
  and a real libphonenumber parse — not a looser rule.
- **Email addresses are compared case-sensitively by the users table.**
  `Ada@example.com` and `ada@example.com` can both register. Invitation
  matching is case-insensitive and works either way, but the accounts
  themselves should probably not be two.
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
│                       plus text chunking and vector arithmetic
├── db/                 engine, session factory, declarative base
├── evaluation/         the AI's dataset, runner and metrics
├── integrations/       one package per outside service, each behind a
│                       Protocol with a fake in tests/support
├── models/             SQLAlchemy tables
├── repositories/       every query lives here
├── schemas/            request and response contracts
└── services/           business rules, and the transaction boundary

alembic/                migrations
tests/                  api, services, repositories, core, db
```
