# Baton

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
createdb baton
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
| Grant the first platform owner | `uv run python -m app.staff_cli grant you@example.com` |

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
| GET | `/api/v1/plans` | The price list. No account needed |
| GET | `/api/v1/health/live` | Liveness probe |
| GET | `/api/v1/health/ready` | Readiness probe, checks the database |
| POST | `/api/v1/auth/register` | Create an account |
| POST | `/api/v1/auth/login` | Exchange credentials for a token pair |
| POST | `/api/v1/auth/refresh` | Exchange the refresh token for a new pair |
| POST | `/api/v1/auth/logout` | End the session that token belongs to |
| POST | `/api/v1/auth/resend-verification` | Send another confirmation link |
| POST | `/api/v1/auth/verify-email` | Confirm an address |
| POST | `/api/v1/auth/forgot-password` | Send a password reset link |
| POST | `/api/v1/auth/reset-password` | Set a new password from that link |
| GET | `/api/v1/auth/me` | The current user, requires a token |
| GET | `/api/v1/account` | Read your own account |
| PATCH | `/api/v1/account` | Change your own name or email |
| POST | `/api/v1/account/change-password` | Replace your password |
| DELETE | `/api/v1/account` | Delete your own account |
| GET | `/api/v1/notifications` | Your feed, across every workspace |
| GET | `/api/v1/notifications/unread-count` | What the badge shows |
| PATCH | `/api/v1/notifications/{notification_id}/read` | Mark one read |
| POST | `/api/v1/notifications/read-all` | Clear the badge |
| GET | `/api/v1/account/sessions` | Where you are signed in |
| DELETE | `/api/v1/account/sessions/{session_id}` | Sign one device out |
| DELETE | `/api/v1/account/sessions` | Sign out everywhere |
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
| POST | `…/{workspace_id}/products` | Add a product and its variants |
| GET | `…/{workspace_id}/products` | The catalogue, searched and filtered |
| GET | `…/products/{product_id}` | Read one |
| PATCH | `…/products/{product_id}` | Update it, and optionally its variants |
| DELETE | `…/products/{product_id}` | Delete it and its variants |
| POST | `…/{workspace_id}/orders` | Record an order taken by hand |
| GET | `…/{workspace_id}/orders` | Orders, by customer, status or number |
| GET | `…/orders/{order_id}` | Read one |
| PATCH | `…/orders/{order_id}` | Record what has happened to it |
| POST | `…/orders/{order_id}/confirm` | Confirm a pending order |
| GET | `…/{workspace_id}/analytics/overview` | The dashboard's headline row |
| GET | `…/{workspace_id}/analytics/conversations` | Volume and responsiveness |
| GET | `…/{workspace_id}/analytics/ai` | What the assistant did, and cost |
| POST | `…/{workspace_id}/integrations/whatsapp/connect` | Connect a number |
| GET | `…/{workspace_id}/integrations/whatsapp` | What is connected |
| DELETE | `…/{workspace_id}/integrations/whatsapp` | Disconnect it |
| GET | `…/{workspace_id}/subscription` | What you may do, and what you pay |
| POST | `…/{workspace_id}/subscription/checkout` | Somewhere to pay |
| POST | `…/{workspace_id}/subscription/cancel` | Stop at the period's end |
| POST | `…/{workspace_id}/automations` | Switch a predefined automation on |
| GET | `…/{workspace_id}/automations` | What is switched on |
| GET | `…/automations/{automation_id}` | Read one |
| PATCH | `…/automations/{automation_id}` | Rename, reconfigure, or disable it |
| DELETE | `…/automations/{automation_id}` | Remove it and its history |
| GET | `…/automations/{automation_id}/runs` | What it has done, and skipped |
| POST | `…/{workspace_id}/automations/run-due` | Run the ones nothing fires |
| POST | `…/integrations/{provider}/install` | Start a storefront installation |
| GET | `…/integrations/{provider}` | What is connected |
| POST | `…/integrations/{provider}/sync` | Read the whole shop again |
| DELETE | `…/integrations/{provider}` | Disconnect it |
| GET | `/api/v1/integrations/{provider}/callback` | Shopify's OAuth redirect |
| POST | `/api/v1/integrations/{provider}/callback` | WooCommerce's key handover |
| GET | `/api/v1/webhooks/whatsapp` | Meta's subscription handshake |
| POST | `/api/v1/webhooks/whatsapp` | Meta's deliveries |
| POST | `/api/v1/webhooks/{provider}` | A storefront's deliveries |
| POST | `/api/v1/webhooks/billing` | The payment provider's deliveries |
| GET | `/api/v1/admin/me` | Who you are on the platform |
| GET | `/api/v1/admin/staff` | Everybody who runs it, revoked included |
| POST | `/api/v1/admin/staff` | Promote an existing account |
| PATCH | `/api/v1/admin/staff/{user_id}` | Move somebody up or down |
| DELETE | `/api/v1/admin/staff/{user_id}` | Take platform access away |
| GET | `/api/v1/admin/audit` | What staff have done |

Protected endpoints take `Authorization: Bearer <access_token>`. The two
webhook routes are not: their caller is Meta, which has no account here.
`/auth/refresh` and `/auth/logout` are not either — the refresh token in
the body is the credential, and requiring a live access token would make
both useless at the only moment they are needed.

Everything under `/account` acts on the account the token belongs to. None
of those paths takes a user id, which is deliberate: there is no id for a
caller to substitute, and so no ownership check for anyone to forget.

### Sessions

Logging in opens a **session** and returns two tokens. The access token is
short-lived and goes in the header of every request. The refresh token
buys the next access token, is good for exactly one use, and is what a
client should keep out of reach of a script.

```text
POST /auth/login    ->  access_token (15 min)  +  refresh_token
POST /auth/refresh  ->  a new one of each; the one you sent is now spent
```

Every refresh replaces both halves and pushes the session's deadline out
again, so `REFRESH_TOKEN_EXPIRE_DAYS` is an idle timeout: a session dies
when nobody has used it for that long, not on a fixed date.

A session is a **chain** of refresh tokens rather than one long-lived key,
and each spent link is kept while the session lives. That is what makes a
copied token detectable. If a spent token is presented again, the rightful
client has already moved on to the next link, so whoever sent this one
either copied it or is working from a copy that was taken — and the two
cannot be told apart. The whole session is revoked, both parties are
signed out, and the response is `401 refresh_token_reused`.

The access token names its session (`sid`), and that session is checked on
every request. Signing a device out therefore lands on its next call
rather than whenever its token happened to expire. That costs nothing
extra: authenticating already meant one query to load the user, and it is
now that same query with a join and two more conditions. Requests already
in flight are the only gap, which is what the short access-token lifetime
bounds.

`GET /account/sessions` lists the live ones, marking the one that asked;
`DELETE /account/sessions/{id}` ends one, and `DELETE /account/sessions`
ends all of them, this device included. Changing your password ends every
session **except** the one changing it — the point is to close the access
that knowing the old password gave, not to throw you out of the screen you
are standing in front of.

Refresh tokens are stored as SHA-256 digests, never as tokens, and a
session's chain is deleted the moment it is revoked. Rate limiting on
login and refresh is Phase 17 and is not here yet.

### Confirming an address, and forgetting a password

Registering emails a confirmation link. Following it stamps
`email_verified_at` on the account, which the API reports and **nothing is
gated on** — an unconfirmed account can do everything a confirmed one can.
Changing your address clears it, because what was confirmed was the old
one; `/auth/resend-verification` is how you confirm the new one.

`/auth/forgot-password` emails a reset link. Using it replaces the
password, signs out **every** session, and marks the address confirmed —
the person just read mail at it, which is the same thing a confirmation
link proves.

Both links are 32 bytes of CSPRNG output stored as a SHA-256 digest, good
for one use, and dead once used. Asking for another retires the previous
one, so a mailbox holds one working key rather than a drawerful. A link is
tied to the address it was sent to as well as to the account, so one
mailed to an old address stops working the moment the account moves. A
confirmation link cannot be spent as a password reset: it is the cheap one
that lives for days, and if it bought a password it would be worth what a
password is.

Neither `/auth/forgot-password` nor `/auth/resend-verification` will say
whether an address belongs to anybody. Both answer `202` with an empty
body for every address, and both do all their work — the lookup, the
token, the send — in a background task, so the response takes the same
time whether or not there was anything to send. Doing it inline could not:
the real case reaches a mail server and the unknown one returns after one
indexed `SELECT`.

The token travels in the request body, not the URL path — unlike an
invitation token, which has to be in a link. That is deliberate: a path is
what a proxy's access log records, and these do not need to be there.

Every failure of `/auth/verify-email` and `/auth/reset-password` is one
`400 invalid_verification_token`: unknown, used, expired, wrong kind, or
sent to an address the account no longer has. The holder has proved
nothing yet, and each distinction would be a fact about somebody's
account. `400` rather than `401` because nobody was authenticating — a
`401` would send a client holding a good session back to the login screen.

Mail goes out over SMTP, configured with `SMTP_HOST` and friends. With no
host set the sender writes the whole message to the log instead, link
included, which is what a laptop wants and exactly why production
**refuses to start** without `SMTP_HOST`, `EMAIL_FROM` and
`FRONTEND_BASE_URL`: a deployment that cannot send mail is one where
forgotten passwords silently go nowhere and reset links end up in a log
file. Rate limiting these — an unauthenticated endpoint that sends email
is worth limiting more than most — is Phase 17.

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

### Rate limits

Counted **per worker, in this process's memory** — there is no Redis, on
the plan's instruction not to introduce it before it is needed. What that
costs is stated rather than hidden: four workers allow four times each
limit. That is the right trade while these exist to stop abuse and runaway
loops, and the day they exist to sell quota is the day this grows a shared
store. Nothing above `app/core/rate_limit.py` would change.

Token buckets, not fixed windows. A fixed window lets twice the limit
through in the two seconds either side of a boundary and gives a client no
useful answer to "when may I try again?". A bucket refills continuously, so
the answer is exactly how long one token takes — which is what
`Retry-After` carries.

Every refusal is `429` with the same body shape as every other error
(`{"detail": ..., "code": "rate_limit_exceeded"}`) and a `Retry-After`
header in seconds.

| Scope | Keyed on | Endpoints |
| --- | --- | --- |
| `auth` | client address | `/auth/login`, `/auth/refresh` |
| `email` | client address | `/auth/register`, `/auth/forgot-password`, `/auth/resend-verification` |
| `invitations` | workspace | `POST …/invitations` |
| `ai` | workspace | `POST …/ai-reply`, and the assistant's own webhook runs |
| `search` | workspace | `POST …/knowledge/search` |
| `uploads` | workspace | `POST …/knowledge/documents/upload` |
| `webhook_rejections` | client address | the two webhooks — see below |

Unauthenticated endpoints are keyed on the caller's address, never on the
email they submitted: keying on somebody else's address is how a limiter
becomes a way to lock one person out of their own account. Authenticated
ones are keyed on the workspace, because what they cost is a tenant's money
rather than a stranger's patience — and membership is checked before
anything is counted, so a stranger cannot spend a business's allowance by
guessing its id.

The webhooks are limited on **deliveries that fail**, not on deliveries.
Meta and Shopify send real traffic in volume from a handful of addresses,
so counting every delivery would mean either a limit high enough to be no
limit or one that throttles the provider itself. An honest sender is never
charged for arriving; a sender of forgeries stops being answered.

The `ai` bucket is the only limit here that can stop a customer being
answered. It is set high enough that reaching it means something is wrong
rather than busy — two bots talking to each other is the case it exists for
— and when it trips the message is already stored and shows up unanswered
in the inbox, which is what a person is for.

Behind a proxy, run uvicorn with `--proxy-headers` or every caller shares
one bucket.

### Catalogue and orders

A **product** has variants; a variant has a SKU, a price and a stock level.
Money is `Numeric`, never a float, all the way through: a price stored as
`4499.999999999999` is a total that is wrong once it is multiplied by three.
Stock has **three** states, not two — `null` is "this business does not
count stock", `0` is "out of stock", and collapsing them would have the
assistant telling customers something is unavailable when the truth is that
nobody counted.

Variants are nested in the product's own request rather than given
endpoints of their own. Supplying `variants` on a `PATCH` replaces the set;
omitting it leaves them alone.

An **order** belongs to a contact, through a composite foreign key, so the
database itself refuses an order attached to another workspace's customer.
The contact cannot be changed through the API: moving an order to a
different customer is not an edit, it is a correction of who it was ever
for, and doing it through a `PATCH` nobody notices is how one person ends
up able to ask about another person's order.

Both tables exist for the assistant. Before it drafts a reply it runs a
**structured lookup** — the catalogue searched by keyword, this contact's
recent orders fetched by contact id — and those facts go into the prompt
alongside the knowledge base, tagged `product:` and `order:` so the model
knows which are exact. That is the plan's rule in both phases: a price, a
stock level or an order's status comes from a `WHERE` clause, never from
whichever passage read most like the question. Two customers with similar
orders would be a coin toss, and the wrong side of that coin is one
customer being told another's tracking number.

Editing the catalogue is an admin's; recording a shipment is an agent's. A
price list is what the business charges, and an agent answering messages
should not change it mid-conversation — but marking an order shipped is
the work they do all day.

### Plans and billing

Three plans, and **they are code**, in `app/services/plans.py`. That is the
plan's instruction for this phase read literally: do not hard-code plan
checks around the codebase, create centralised capability checks. So
`GET /plans` and every capability check answer from the same catalogue and
cannot drift, and a `subscriptions` row records only *which* plan a
workspace is on.

Two kinds of thing, enforced two ways. A **feature** is a yes or no,
declared in a route's decorator:

```python
dependencies=[REQUIRES_AUTOMATIONS]
```

A **limit** is a number, so it has to count something — team members,
knowledge documents, AI responses this period — and those live in
`SubscriptionService.require_within_limit`. Counted rather than remembered:
a stored count is a second thing that can disagree with the rows it counts.

| | Starter | Growth | Business |
| --- | --- | --- | --- |
| Team members | 2 | 10 | unlimited |
| AI responses / month | 1,000 | 10,000 | 100,000 |
| Knowledge documents | 50 | 500 | unlimited |
| Automations, storefronts | — | ✓ | ✓ |
| API access, audit logs | — | — | ✓ |

`402 Payment Required`, not `403`. A `403` says "you may not", which sends
somebody to an administrator who cannot help. A `402` says the *plan* is
what is in the way, and the plan is something they can change. Membership
is still checked first, so a stranger guessing at a workspace id is told it
does not exist rather than what it pays for.

**Only creating is gated.** A workspace whose plan lapses keeps being able
to read and switch off the automations it already has, and to see and
disconnect its storefront. That is the difference between losing a feature
and losing your data — or being locked in by one.

Nothing about a subscription is decided here. A checkout starts one at the
provider and a webhook brings the answer back; every field on the row is a
copy, because a row that disagreed with the provider would be a workspace
using a plan nobody is paying for. Cancelling sets it to end at the period
boundary rather than ending it: somebody who has paid for a month is
entitled to the month.

**Billing failures do not switch anything off.** `past_due` is a card that
did not go through and a provider that is still retrying, so the plan still
applies and the administrators get a notification. Only `canceled` and
`unpaid` fall back — and they fall back to **Starter**, not to nothing,
because a declined card must never lock a business out of its own inbox.

Billing webhooks are the one place in this application where handling a
delivery twice is not merely untidy: what gets got wrong is what somebody
is charged and what they are allowed to use. So the provider's event id is
claimed in `billing_events` *before* anything is applied, and a redelivery
loses at the claim — answering the same `200`, because the provider asked
whether we have it and we do. Stripe signs the timestamp along with the
body, so a delivery captured today cannot be replayed next week; that
window is checked, not just the digest.

The AI quota is the one limit that stops work rather than refusing to start
it. Running out records a `blocked` decision with reason `plan_limit`
rather than raising, because both callers need it that way — the endpoint
renders it, and the webhook has already answered `200` and has nobody left
to tell. The customer's message is stored either way and shows up
unanswered in the inbox.

Stripe is what the MVP charges through, over raw HTTP rather than the SDK,
for the reason the Shopify adapter is raw HTTP. With no `STRIPE_API_KEY`
configured nothing can be sold and every workspace is on Starter, which is
a perfectly working deployment — and the plan's own advice is not to build
billing before pilots prove value.

### Notifications

**No workspace in any of these paths**, which is the plan's endpoint list
read literally and also the right shape: a notification is addressed to a
*person*, and a person opening theirs wants everything meant for them —
from every business they work in, not one at a time. `workspace_id` is a
filter on all four endpoints, never a requirement, and every notification
says which workspace it came from.

What keeps the tenant boundary is the recipient *plus a membership check
on every read*. A notification outlives the membership that justified it,
so somebody removed from a business stops seeing its activity the moment
they are removed rather than keeping a feed of it.

| Told about | Who hears it |
| --- | --- |
| A conversation assigned to you | the assignee — never the person who assigned it |
| The assistant asking for a person | everyone who handles customers |
| A message that could not be delivered | administrators |
| A document that could not be ingested | administrators |

One row per recipient, because read state is per person and three of the
four endpoints are about read state. A shared row would need a second
table to hold who had read it, which is the same rows in a worse shape.

Notifications are written **in the same transaction as the thing they
describe**. One committed separately can exist for an assignment that was
rolled back, or be missing for one that was not.

The two failure kinds **do not repeat while they are still unread** — a
partial unique index on `(user_id, dedupe_key) WHERE read_at IS NULL`. A
provider outage produces one failure per message, and one notification per
failure would bury the problem under itself. An integration is not more
broken for having failed twice. The event kinds leave that key null and
never collide, so two assignments are two notifications.

`read_at` is a timestamp, not a flag, and is set once: marking something
read twice must not move it, or "when did they see this" stops being true
the moment somebody clicks twice.

**In-app only.** Email and push are named in the plan as later channels,
and the sender built in Phase 16 is there when they arrive. **"Customer
waiting"** is the one example from the plan not built: it is about time
passing rather than an event, so it needs the sweep the background-jobs
phase supplies.

### Automations

Three predefined automations, not a workflow builder — which is the plan's
instruction for this phase, and the reason an `automations` row holds
*settings* rather than a program. What each one does is code in
`app/services/automations.py`; what a business chooses is whether it runs,
when, and what it says. Settings are validated against the schema the
named automation declares before they are stored, so a row cannot exist
that the code reading it will not understand.

| Automation | Fires on | Deduplicated by |
| --- | --- | --- |
| Order confirmation | an order recorded | the order |
| Hand over to a person | a customer message matching a keyword | the message |
| Unanswered lead follow-up | a sweep, not an event | the conversation |

Three of the plan's six, and the other three are worth saying out loud.
**FAQ auto-response** and **order status response** are what the assistant
already does, driven by a conversation's `ai_mode` — retrieval, the
catalogue lookup and this customer's orders, all since Phase 11. Building
them again here would be a second path to the same reply with a second set
of bugs, which is the one thing this phase's plan says not to do.
**Abandoned cart follow-up** needs a cart, and nothing in this product has
one: that is a table and a webhook topic, not a setting.

**Duplicate execution** is a unique index on `(automation_id, dedupe_key)`,
and the run row is written *before* the work rather than after it. An index
only prevents anything if the claim exists before the second attempt looks,
so a redelivered webhook loses the race at the claim rather than halfway
through sending a message. An automation that returns no key is saying it
may run again, which is a decision each one makes for itself.

**Retries** are the automation's own policy — three attempts for a send,
two for a follow-up — and only `AppError` is retried, this application's
vocabulary for "something outside said no". Anything else is a bug, and
retrying a bug three times produces three of the same stack trace. Retries
are inline, which is honest rather than ideal: it runs after its response
so nobody is waiting, but a provider down for a minute produces a failed
run rather than one that resumes. The row it leaves is what a retry worker
would pick up.

**Run history** is `GET …/automations/{id}/runs`. Most rows are `skipped`,
and that is the point rather than noise: an automation is considered on
every matching event, so the history is also the record of everything it
correctly left alone. Filter by `status` for the ones that did something —
or the ones that failed, which is the question people usually arrive with.

Automations never run in a request. Messaging a customer means waiting on a
provider, and that must not be time a webhook spends before acknowledging
or an agent spends on a form. `POST …/automations/run-due` is the exception
by necessity: a follow-up is about something *failing* to happen, so it has
to be looked for, and there is no scheduler yet. That endpoint is what the
background-jobs phase will call on a timer, and nothing else changes when
it does. It is safe to call repeatedly — every run it records is
deduplicated on the thing it acted on.

One thing worth knowing before connecting a storefront: **an order
confirmation fires on a webhook and never on a sync.** A delivery is
something that has just happened; a sync is a shop's history, and
confirming all of it would message every customer the business has ever
had, about orders they placed months ago. That is enforced at the caller
rather than in the automation, because it is a property of how the order
arrived.

### Connecting a storefront

Two of them — **Shopify** and **WooCommerce** — behind one interface.
`{provider}` is a path parameter, so `…/integrations/shopify/install` and
`…/integrations/woocommerce/install` are the same four operations with a
different adapter behind them, and an unknown provider is a `422` before
any handler runs. One storefront per workspace, whichever it is.

The two installations genuinely differ, and that is why the seam is shaped
the way it is rather than being Shopify's flow with a second name on it:

| | Shopify | WooCommerce |
| --- | --- | --- |
| Flow | OAuth: redirect back with `?code=` | store POSTs the keys, then redirects |
| Callback proof | HMAC over the query string | **nothing** — the signed `state` is all of it |
| Credentials | one access token | a consumer key *and* secret |
| Webhook secret | the app secret you already hold | one the shop owner types in |
| Address | `something.myshopify.com` | wherever WordPress lives |

Which workspace an installation belongs to travels in a signed `state`,
because a storefront app is configured with a single callback URL. The shop
is signed into that state too and checked against whatever the provider
says: without that, somebody who could get one shop owner to approve an
installation could attach a different shop to their own workspace. For
WooCommerce the state is the *only* proof, since nothing about its POST is
signed — which is why it is checked once, in the service, rather than
twice in two adapters.

Credentials are encrypted at rest with the same key provider tokens
already use, and stored as one opaque string that only the adapter which
produced it takes apart. Either kind grants read access to a business's
whole catalogue and every order it has taken, which is one more reason
production refuses to start without `ENCRYPTION_KEY`.

A WooCommerce address is checked before it is ever dialled — https only, no
port, no path, and no loopback or private literal. This server makes
requests to whatever address a caller supplies, and on a cloud host
`169.254.169.254` is the machine's own credentials. What that check does
*not* do is resolve the name and see where it points, so a hostname that
resolves inward walks past it; `app/integrations/ecommerce/hosts.py` says
so, and says what closing it would take.

Everything the storefront sends is an **upsert keyed on the storefront's
own id**, which is what makes a repeated delivery harmless — a provider
retries anything it did not get a prompt 200 for, and Shopify sends
`orders/updated` for changes this application does not care about. A
payload carrying an `updated_at` older than what is already stored is
skipped rather than written backwards, so a retry that arrives after a
newer change cannot undo it. Topics nothing handles are acknowledged, not
refused: a subscription is easy to widen by accident, and a delivery that
can never be acted on would otherwise be retried for a day.

Disconnecting, and `app/uninstalled`, destroy the token and keep
everything already synced. A business that uninstalls has stopped granting
access; it has not asked to lose its own catalogue.

`app/integrations/ecommerce/base.py` is the wall the plan asks for. A
payload becomes `RemoteProduct` and `RemoteOrder` there, and nothing
downstream has heard of a `variants` array, an `inventory_management`
flag, or a `date_modified_gmt`. Adding WooCommerce added one adapter and
one migration widening a `CHECK` constraint; the sync, the catalogue, the
orders, the account table and the webhook handler are the ones Shopify
already used.

Both adapters carry the same distinction about stock, and both get it from
a different field: Shopify sends `inventory_quantity` as a present,
meaningless zero when tracking is off, and WooCommerce sends
`stock_quantity: null` with `manage_stock: false`. Either way a shop that
has never counted arrives as "not tracked" rather than as "out of stock".

### Platform administration

Everything above is **tenant** administration: a customer running their
own business here, where `WorkspaceAdminDep` separates an owner from an
agent. `/api/v1/admin` is the other kind — the people who operate Baton,
who have to answer a support email about a workspace they are not a
member of.

The two have opposite defaults, which is why they are two surfaces rather
than one with a wider role. A tenant sees one workspace; staff see every
one. The tenant boundary answers "no such workspace" to three different
refusals on purpose, so that an id cannot be used to discover which
businesses have accounts; `/admin` says what actually happened, because
everybody reaching it is already authenticated as staff and already being
recorded. And on the tenant surface a read is ordinary, while here it is
the sensitive act.

**Staff are ordinary accounts, promoted.** There is no separate login and
no endpoint here that creates a user: somebody joining the team registers
the way a customer does and is granted access afterwards, so they keep one
password, one session list and one way back in when they forget it. What
differs is the window — `ADMIN_SESSION_IDLE_MINUTES`, an hour against the
tenant side's thirty days. A session left sitting is refused by the
console and keeps working everywhere else.

Three ranks, cumulative: **support** reads the console, **admin** adds
lifecycle and billing, **owner** adds granting and revoking. Granting is
owner-only because it is the one act that creates more of this surface.
The last live owner cannot be demoted or revoked — only an owner may
grant, so a platform without one is a console nobody can be added to
again.

**Every route writes to `admin_audit_logs`, reads included.** That is the
point of the table rather than an excess of caution: what has to be
answerable afterwards is who looked at a customer's account, and a log of
only the writes answers a different question. Its rows are append-only —
there is no update or delete on the repository, and no route at any rank
— and they carry the actor's address copied at the time, so closing your
own account does not remove you from the record.

The workspace reference on that table is nullable and **does not
cascade**, which is the one schema decision worth reading the file for.
When a closed workspace is finally erased its own audit log goes with it,
correctly: the customer asked to be forgotten. What must not go with it is
the row saying a staff member read that workspace two days beforehand, so
the id is nulled and the slug — copied alongside — still names the
account.

The first owner comes from a terminal on the deployment:

```bash
uv run python -m app.staff_cli grant you@example.com
```

A command rather than a migration, deliberately: a migration would put a
privileged account in version control, identical everywhere, granted to
an address chosen by whoever wrote the file. And granting is the only
thing the command line can do — changing a rank or taking access away
goes through the console, where there is a named actor to record.

The router is mounted separately from the tenant one in `app/main.py`, so
that no `include_router` added to the wrong file can put an admin path
behind a tenant guard. Same process today; a separate deployment would
let the network keep this surface off the public internet entirely, and
nothing above the mount would change for it.

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
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Short: it is sent with every request |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `30` | Idle timeout. Every refresh pushes it out |
| `ADMIN_SESSION_IDLE_MINUTES` | `60` | The same session, refused by `/admin` alone |
| `CORS_ORIGINS` | empty | Comma separated. Empty means no cross-origin access |
| `CORS_ALLOW_CREDENTIALS` | `true` | Cannot be combined with `*` origins |
| `ALLOWED_HOSTS` | `*` | Host header allow-list. Must be explicit in production |
| `ENCRYPTION_KEY` | unset | Encrypts provider tokens. Required in production |
| `EMAIL_VERIFICATION_EXPIRE_HOURS` | `48` | How long a confirmation link lasts |
| `PASSWORD_RESET_EXPIRE_MINUTES` | `60` | Shorter: it is a key to the account |
| `FRONTEND_BASE_URL` | unset | Where the links point. Required in production |
| `SMTP_HOST` | unset | Unset logs the mail. Required in production |
| `SMTP_PORT` | `587` | |
| `SMTP_USERNAME` | unset | No login is attempted without one |
| `SMTP_PASSWORD` | unset | |
| `SMTP_USE_TLS` | `true` | STARTTLS. Off is for a local mail trap only |
| `EMAIL_FROM` | unset | The From address. Required in production |
| `RATE_LIMIT_ENABLED` | `true` | Off makes every limit below a no-op |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Per address. Login and refresh share it |
| `RATE_LIMIT_EMAIL_PER_HOUR` | `5` | Per address. The endpoints that send mail |
| `RATE_LIMIT_INVITATIONS_PER_HOUR` | `60` | Per workspace |
| `RATE_LIMIT_AI_PER_MINUTE` | `60` | Per workspace, webhook replies included |
| `RATE_LIMIT_SEARCH_PER_MINUTE` | `60` | Per workspace |
| `RATE_LIMIT_UPLOADS_PER_HOUR` | `120` | Per workspace |
| `RATE_LIMIT_WEBHOOK_REJECTIONS_PER_MINUTE` | `30` | Per address, failures only |
| `RATE_LIMIT_ADMIN_PER_MINUTE` | `120` | Per staff member. The platform console |
| `API_BASE_URL` | unset | Where this API answers. Needed for OAuth |
| `SHOPIFY_API_KEY` | unset | Without it, no storefront can be installed |
| `SHOPIFY_API_SECRET` | unset | Signs the OAuth callback and every webhook |
| `SHOPIFY_SCOPES` | read-only | Products, orders and customers |
| `WOOCOMMERCE_WEBHOOK_SECRET` | unset | Without it, no Woo delivery verifies |
| `STRIPE_API_KEY` | unset | Without it, nothing can be sold |
| `STRIPE_WEBHOOK_SECRET` | unset | Signs every billing delivery |
| `STRIPE_PRICE_GROWTH` | unset | Stripe's name for what Growth costs |
| `STRIPE_PRICE_BUSINESS` | unset | Same, for Business |
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
immediately instead of quietly widening the service's exposure. So are a
missing `ENCRYPTION_KEY`, and a missing `SMTP_HOST`, `EMAIL_FROM` or
`FRONTEND_BASE_URL` — those three because without them password reset does
not fail, it appears to work while the link goes to a log file.

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

- **Nothing prunes ended sessions.** A revoked session's refresh tokens are
  deleted with it, but the session row itself stays, and one that simply
  lapsed keeps its chain. Neither can authorise anything — every lookup is
  filtered on the clock — so this is table growth rather than exposure. A
  sweep belongs with the background jobs phase.
- **A session's device and address are labels, not evidence.** `User-Agent`
  is whatever the client sent, and the address is the peer's, which is the
  proxy's unless uvicorn runs with `--proxy-headers`. Nothing decides
  anything from either.
- **No administration API.** A user can manage their own account and nothing
  else.
- **Nothing drains the queued messages.** A reply sent while no number is
  connected stays `queued` forever; a retry worker is a later phase.
- **Only text.** Images, audio, documents and interactive templates are
  parsed out of webhooks and skipped rather than stored empty.
- **`ai_mode`** is stored on every conversation and read by nothing.
- **Confirming an address gates nothing.** `email_verified_at` is recorded
  and reported, and an unconfirmed account can still do everything. Making
  it a requirement is a product decision, not a missing implementation.
- **Workspace invitations are still not emailed.** The link has to be
  handed over by whoever created it, because the API returns the token
  once for exactly that reason. There is a sender to do it with now, so
  this is a wiring job rather than a phase.
- **Changing your address does not email the new one.** It clears the
  confirmation, and the client is expected to call
  `/auth/resend-verification` afterwards.
- **Nothing prunes spent or expired links.** `user_tokens` grows. None of
  those rows can do anything, so this is table growth rather than
  exposure, and it belongs with the same sweep the ended sessions need.
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
- **Rate limits are per worker.** Four workers allow four times each
  number. Documented above rather than hidden, and the fix is a shared
  store the day the limits are selling quota rather than stopping abuse.
- **Orders have no line items.** The plan's `orders` is totals, status and
  tracking — enough to answer "where is it", not "what did I order". Line
  items are a table, not a column, and adding them is a phase of its own.
- **Money is `Numeric(12, 2)`.** That covers PKR, AED, SAR, USD and EUR.
  The three-decimal currencies — KWD, BHD, OMR — need a migration.
- **A full storefront sync is synchronous.** Honest for a few hundred
  products and not for a few hundred thousand; moving it to a background
  job is the background-jobs phase, and nothing above it changes.
- **One storefront per workspace**, and one workspace per shop. More is a
  plan feature and a migration.
- **A WooCommerce address is checked by shape, not by where it resolves.**
  https only, no port, no path, no loopback or private literal — which
  catches the whole obvious class, and not a hostname that resolves inward.
  Closing that means resolving here and connecting to the resolved
  address, which is a custom transport rather than a regular expression.
- **WooCommerce keeps no tracking fields of its own.** They live in
  whichever shipping plugin the shop installed; the two `meta_data` keys
  the common ones use are read, and a shop using a third is not.
- **Automation retries are inline and bounded.** A provider down for a
  minute leaves a `failed` run rather than one that resumes. The row is
  what a retry worker would pick up; there is no worker yet.
- **Nothing runs `run-due` on a timer.** Until the background-jobs phase
  supplies a scheduler, a follow-up only happens when something calls that
  endpoint.
- **A follow-up goes out once per conversation, ever.** That is
  deliberate — the alternative is the same nudge every sweep, for as long
  as a lead stays dropped — but it also means a lead dropped twice is
  nudged once.
- **Notifications are in-app only.** Email and push are later channels;
  nothing is delivered outside the API.
- **Nothing tells anybody a customer has been waiting.** That one is about
  time passing rather than an event, so it needs the same scheduler the
  automation sweep does.
- **The WhatsApp number limit cannot bite.** One number per workspace is a
  unique constraint, so every plan is effectively capped at one until that
  changes. The limit is declared so the plan reads honestly and so the
  check is already in place.
- **Usage is counted at the moment of adding, never swept.** A workspace
  that drops to a smaller plan keeps whatever it already had — more
  members than the plan allows, say — and simply cannot add more.
- **Notifications are never pruned.** The table grows with activity. None
  of it is exposure — every read is scoped to the recipient and their
  current memberships — and it belongs with the same sweep the ended
  sessions and spent links need.

## Layout

```text
app/
├── main.py             application factory, lifespan, middleware
├── api/
│   ├── router.py       assembles the versioned router
│   ├── admin_router.py the platform surface, assembled apart from it
│   ├── errors.py       domain errors -> HTTP responses, in one place
│   ├── dependencies/   reusable request-scoped dependencies
│   └── routes/         HTTP concerns only
│       └── admin/      the routes scoped to no workspace at all
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
