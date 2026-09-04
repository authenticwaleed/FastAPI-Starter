# Baton — The Web Client

## Specification and Implementation Plan

Next.js, TypeScript and Tailwind, against the API this repository already
serves. Thirteen phases, `W1`–`W13`, each shippable on its own.

---

# 1. What this is, and what it is not

Baton is an API with no face. Everything it does is reachable, and
nothing is usable: a business owner cannot answer a customer from curl,
and a support engineer cannot suspend a workspace from a JSON body they
have to hand-write. This document is the client that makes the existing
159 operations something a person can operate.

It is **not** a redesign, and it is not a place to add behaviour. Every
rule this client shows a person is a rule the API already enforces. Where
the two disagree the API is right and the screen is a bug — including
where the screen is friendlier.

**Out of scope.** No new endpoints. If a screen needs something the API
does not return, the answer is a phase in the API's own plan, not a
workaround in the client. Two places where that will be tempting are
named in §7.

---

# 2. What already exists

The whole surface, and it is worth reading §3 of this document before
assuming any of it behaves the way a typical CRUD API does.

| Surface | Operations | Reached through |
| --- | --- | --- |
| Tenant | 109 | a workspace membership |
| Platform | 50 | a staff row |

Both are mounted at `/api/v1`. `docs/api.html` in this repository is the
full reference, built by `./run.sh docs`; `/docs` and `/redoc` serve the
same schema from a running deployment.

Three things the client gets for free and should not rebuild: the error
envelope is uniform (§3.7), the schema is machine-readable and committed,
and roles are already fixed lists rather than a permission engine.

---

# 3. Seven things the API makes true

These are the places where a client written on habit will be wrong. Each
one has cost somebody an afternoon in an application built against an API
that behaved this way and was not read first.

## 3.1 A `402` is not a `403`

`403` means *you may not* — a role problem, and the person's
administrator can fix it. `402` (`feature_not_in_plan`,
`plan_limit_reached`) means *the plan is what is in the way*, and the
plan is something they can change themselves.

These must never render the same. A `403` shows "ask an owner"; a `402`
shows what the plan does not include and a link to billing. Rendering a
`402` as "permission denied" sends a paying customer to an administrator
who is powerless, which is the exact failure the API chose the status
code to avoid.

## 3.2 A `404` is deliberately ambiguous

On the tenant surface, a workspace that does not exist and a workspace
you are not a member of are the **same** answer. That is on purpose: an
id must not be usable to discover which businesses have accounts.

So the client never renders "you are not a member of this workspace". It
renders "no such workspace", every time, and does not try to be more
helpful. On the **platform** surface the opposite holds — a `404` there
means no such row, and the console should say so plainly.

## 3.3 A suspended workspace can be read and not written

Every non-`GET` under `/workspaces/{id}` is refused with `403
workspace_suspended` while a workspace is suspended. Reads keep working,
deliberately, so a business can still see its own inbox and audit log.

The client mirrors this as a **mode, not an error**: on
`workspace_suspended`, the workspace goes read-only — a banner, every
mutation control disabled — rather than showing a toast per click. Nothing
in the workspace payload announces suspension to a member, so the first
`403` is what puts the UI into that mode.

## 3.4 Entitlement is `plan`, never `subscription.plan`

`GET /workspaces/{id}/subscription` returns both. They answer different
questions and they routinely disagree:

- `plan` — what the workspace may actually do right now, after
  overrides and status. **Gate every screen on this.**
- `subscription.plan` — what is being paid for. Display only.

A `past_due` subscription still entitles the full plan while the provider
retries; a comped workspace is entitled to more than it pays for. A
client that gates on `subscription.plan` takes features away from a
customer whose card is merely being retried.

## 3.5 The console signs out on its own schedule

`/admin/*` refuses an idle session with `401 admin_session_expired` while
the *same session* keeps working on the tenant surface. The console
therefore needs its own re-authentication path, and a `401` there must
not clear the tenant session.

Two more console-only refusals with no tenant equivalent:
`403 address_not_allowed` (an IP allowlist) and `403 approval_required`
(a second staff member has to second the action). Both are terminal for
the request — no retry, no form change helps — and must read as such.

## 3.6 Money is a string, unlimited is `null`

`price` serialises as `"49"`, not `49`, so decimal precision survives the
wire. Inside `limits`, `null` means unlimited — present as a key, never
absent, so a comparison table always has a row.

## 3.7 Every failure has the same shape

```json
{ "detail": "Your plan does not include this", "code": "feature_not_in_plan" }
```

`code` is stable; `detail` is prose that may be reworded. **One module
maps codes to sentences**, and nothing anywhere branches on `detail`.
Validation failures add `errors[]` with per-field entries, which is what
drives inline form errors. A `429` carries `Retry-After`.

---

# 4. Principles

1. **The API is the authority.** The client hides controls a role cannot
   use, but a hidden control is never assumed to be an enforced one. Every
   mutation handles its own refusal.
2. **Read before write.** Each phase ships its screens read-only first.
   A console that is useful and cannot break anything beats a half-built
   one that can.
3. **No token in JavaScript.** The access and refresh tokens live in
   httpOnly cookies and are attached by the server. An XSS in this client
   must not be able to walk away with a session.
4. **One refusal renderer.** Every `code` in the API maps to a sentence in
   one file. A screen that invents its own wording for a `409` is a screen
   that will disagree with the next one.
5. **Server components by default.** Client components where there is
   genuine interaction state, and nowhere else.
6. **Optimistic where it is safe, never where it is not.** Marking a
   conversation read may be optimistic. Sending a message, cancelling a
   subscription, and anything on `/admin` may not.
7. **The two surfaces never share a layout or a nav.** No link from the
   customer app reaches the console. They share components and nothing
   else — the same separation the API keeps between its two routers.
8. **Every phase is shippable.** It ends with screens somebody can use,
   not scaffolding for the next phase.

---

# 5. Decisions taken

Settled before writing this, and recorded because each one closes off an
alternative somebody will otherwise reopen at phase six.

| | Decision | Instead of | Why |
| --- | --- | --- | --- |
| 5.1 | `web/` in this repository | a second repository | A change to an endpoint and its screen is one PR and one review. A breaking change across two repos is two PRs that have to land in order. |
| 5.2 | Session in httpOnly cookies, proxied by Next route handlers | tokens in `localStorage` | The refresh token is the durable credential; script-readable storage puts it one XSS away. The API's `/auth/refresh` and `/auth/logout` are unauthenticated and take the token in the body, which fits a server holding it. |
| 5.3 | shadcn/ui | a component library, or hand-rolling | Components are copied in and owned, so there is no upgrade treadmill and no fight with someone else's design. Accessibility comes from Radix rather than from good intentions. Matches this repository's habit of vendoring what it depends on. |
| 5.4 | One app, route groups `(app)` and `(admin)` | two applications | Mirrors the API's own shape — two routers, one mount. Separate layouts and separate guards; shared build, deploy and components. |
| 5.5 | Types generated from `docs/api.html`'s schema | hand-written types | `openapi-typescript` against the committed schema. The client's types and the reference come from the same place, so a drifting type is a build error rather than a runtime surprise. |
| 5.6 | TanStack Query for client state | Redux, Zustand, or none | Server state is the only state this client has much of. Caching, refetch and mutation lifecycles are what it needs, and none of that is global application state. |
| 5.7 | Playwright for phase acceptance | unit tests alone | Every acceptance criterion below is user-visible. Vitest covers the pure pieces — the code-to-sentence map, plan gating — and Playwright covers the rest. |

---

# 6. The phases

Each phase names its screens, the endpoints it consumes, the rules it
must get right, and what it is judged on. Endpoint counts are
cumulative against the 159 the API serves.

## Phase W1 — The shell, the session, and the door

The phase everything else assumes. No product screens.

### Screens

Sign in, register, verify email, resend verification, forgot password,
reset password. An authenticated shell with a workspace switcher stub and
a sign-out.

### Endpoints (9)

| Method | Path |
| --- | --- |
| POST | `/auth/register` |
| POST | `/auth/login` |
| POST | `/auth/refresh` |
| POST | `/auth/logout` |
| GET | `/auth/me` |
| POST | `/auth/verify-email` |
| POST | `/auth/resend-verification` |
| POST | `/auth/forgot-password` |
| POST | `/auth/reset-password` |

### Rules

- **The proxy is the only way out.** One route handler at
  `/api/[...path]` attaches `Authorization` from the cookie and forwards
  to FastAPI. No component ever holds a token or calls the API directly.
- **Refresh happens once per failure, on the server.** A `401` triggers
  one refresh and one retry. A second failure signs the person out. Two
  concurrent requests must not both refresh — single-flight it, or a
  rotated refresh token gets spent twice and the API answers
  `refresh_token_reused`, which is a hard sign-out by design.
- `refresh_token_reused` is not a retry. It means the token was replayed;
  clear the session and send the person to sign in.
- Cookies are `httpOnly`, `Secure` outside development, `SameSite=Lax`,
  plus an origin check on mutating route handlers.
- The code-to-sentence map (§3.7) is built here, covering every code the
  auth endpoints can return, and grows one entry per phase.

### Acceptance

- Signing in sets no value readable from `document.cookie`
- An expired access token refreshes without the person noticing
- A replayed refresh token signs out rather than looping
- A wrong password renders one sentence, not a raw JSON body
- Registering, then following the emailed link, confirms the address

---

## Phase W2 — The account, and the workspaces behind it

### Screens

Account settings (name, email), change password, active sessions with
per-device revoke and revoke-all, the notification feed with unread
badge, workspace list, create workspace, workspace settings, close
workspace.

### Endpoints (16)

`/account` (GET, PATCH, DELETE), `/account/change-password`,
`/account/sessions` (GET, DELETE), `/account/sessions/{id}` (DELETE),
`/notifications` (GET), `/notifications/unread-count`,
`/notifications/{id}/read`, `/notifications/read-all`,
`/workspaces` (POST, GET), `/workspaces/{id}` (GET, PATCH, DELETE).

### Rules

- The session list marks the current device. Revoking it is a sign-out,
  and the screen must treat it as one rather than showing an empty list.
- Changing a password ends every other session. Say so before, not after.
- Notifications are addressed to a **person**, not a workspace — the feed
  spans every workspace they are in, and it lives outside the workspace
  layout because of it.
- Closing a workspace is owner-only and reversible for a period by staff;
  the screen says what happens, and takes a typed confirmation.
- Workspace switching sets the active workspace in a cookie, not in
  client state, so a server component knows it on first render.

### Acceptance

- A viewer sees the workspace settings form disabled, not absent
- The unread badge clears without a full refetch of the feed
- Deleting the account requires the password and warns about owned
  workspaces (`409 workspace_ownership_required` renders as a list of
  what to hand over first)

---

## Phase W3 — The inbox

The product. Everything before this is scaffolding; everything after is
around the edges.

### Screens

Conversation list with filters (status, assignee, unread) and paging;
the thread view with message history; the composer; contact panel
alongside the thread; contact list and contact detail; the assistant's
suggested reply and its history.

### Endpoints (19)

`/conversations` (POST, GET), `/conversations/{id}` (GET, PATCH),
`/conversations/{id}/messages` (GET, POST), `…/assign`, `…/read`,
`…/takeover`, `…/release-to-ai`, `…/close`, `…/reopen`, `…/events`,
`…/ai-reply`, `…/ai-responses`, `/contacts` (POST, GET),
`/contacts/{id}` (GET, PATCH).

### Rules

- **Agent or above for every write here.** A viewer reads the inbox and
  sends nothing; the composer is absent for them, not disabled, because a
  permanently dead composer is worse than none.
- Takeover and release-to-ai are the same control in two states, and the
  state comes from `ai_mode` on the conversation. Never infer it.
- `POST …/ai-reply` is rate limited (`AI` scope) and costs money. One
  request in flight at a time, the button disabled while it runs, and
  `429` renders the wait from `Retry-After` rather than a generic error.
- Running out of the monthly AI allowance does **not** raise — the
  assistant records a blocked decision and the customer's message still
  arrives unanswered. The thread has to show that state, or a business
  will think the message was lost.
- `409 conversation_closed` and `409 conversation_already_open` are
  ordinary outcomes of two people working the same inbox, not errors.
  Refetch and re-render; do not show a red toast.
- Marking read may be optimistic. Sending may not.

### Acceptance

- Two agents with the same thread open do not overwrite each other's
  status changes
- A closed conversation offers reopen and nothing else
- The assistant's suggestion is clearly a draft until a person sends it
- A contact with no conversations renders as an empty state, not an error

---

## Phase W4 — The team

### Screens

Member list with roles, change role, remove member, leave workspace,
invite by email, pending invitations with revoke, and the public
invitation-acceptance page.

### Endpoints (8)

`/workspaces/{id}/members` (GET), `/members/{user_id}` (PATCH, DELETE),
`/workspaces/{id}/invitations` (POST, GET),
`/invitations/{invitation_id}` (DELETE), `/invitations/{token}` (GET),
`/invitations/{token}/accept` (POST).

### Rules

- **The invitation token is returned once and is not emailed by the API.**
  The screen that creates an invitation must show the link and make it
  copyable, because that is currently the only way it reaches anybody.
  See §7.
- `/invitations/{token}` is public — the preview page renders outside the
  authenticated shell, for somebody who may not have an account yet.
- An expired invitation answers `410`, not `404`, and the difference is
  the whole message: "ask for another", not "check the address".
- Roles fan out rather than nest: an admin manages people, an agent
  handles customers, and neither contains the other. The role picker
  explains what each one does; it is not a slider.
- A workspace must keep an owner. `409 last_owner` renders as an
  instruction, not a failure.

### Acceptance

- Inviting somebody already invited says so (`409`) without losing the form
- The acceptance page works signed out, then signs the person in
- An admin cannot change an owner's role, and the control says why

---

## Phase W5 — Knowledge

### Screens

Source list, add source, document list with per-source filter, upload a
document, add an FAQ pair, document detail, delete, and a search box that
shows what the assistant would retrieve.

### Endpoints (11)

`/knowledge/sources` (POST, GET), `/knowledge/sources/{id}` (GET,
DELETE), `/knowledge/documents` (POST, GET), `/knowledge/documents/faq`,
`/knowledge/documents/upload`, `/knowledge/documents/{id}` (GET, DELETE),
`/knowledge/search` (POST).

### Rules

- Upload is `multipart/form-data`, rate limited (`UPLOADS`), and only PDF
  and plain text are accepted. `415` names the types; `422
  unreadable_document` means the file was fine and the text was not — two
  different sentences.
- `409 document_already_ingested` is a duplicate, not a failure. Show the
  existing document rather than an error.
- The document count is a plan limit. At the ceiling the API answers
  `402 plan_limit_reached`; the screen shows the ceiling and a link to
  billing **before** the upload, from the usage figures in W7.
- Search is rate limited too, so debounce it and do not search per
  keystroke.

### Acceptance

- A 20 MB PDF reports progress and does not block the page
- Deleting a source explains what happens to its documents
- Search results show which document each passage came from

---

## Phase W6 — Catalogue and orders

### Screens

Product list with search, product detail and edit, create, delete; order
list with status filter, order detail, create order, edit, confirm.

### Endpoints (10)

`/products` (POST, GET), `/products/{id}` (GET, PATCH, DELETE),
`/orders` (POST, GET), `/orders/{id}` (GET, PATCH), `/orders/{id}/confirm`.

### Rules

- Products are admin-write, agent-read. Orders are agent-write, because
  taking an order is customer work.
- `409 product_conflict` is an SKU or external id already used in this
  workspace — an inline field error, not a page-level one.
- `409 order_not_confirmable` means the order is not pending any more.
  Refetch; somebody else confirmed it.
- Products synced from a storefront are not editable here in a meaningful
  sense — the shop is the system of record. Mark their origin.

### Acceptance

- A product with no image, no SKU and no description still renders
- Confirming an order twice is safe and says what happened
- Money renders from the string without a float ever appearing

---

## Phase W7 — Plans, billing and usage

The phase that makes every other phase's `402` meaningful.

### Screens

Public pricing page, current plan with subscription state, checkout
redirect, cancel with period-end explanation, usage meters against plan
limits, and the reusable **upgrade prompt** every other screen renders on
a `402`.

### Endpoints (5)

`/plans` (GET, public), `/workspaces/{id}/subscription` (GET),
`…/subscription/checkout` (POST), `…/subscription/cancel` (POST),
`/workspaces/{id}/usage` (GET).

### Rules

- Gate on `plan`, never `subscription.plan` (§3.4). This is the phase
  that builds the entitlement hook every other screen uses, and getting
  it wrong here is wrong everywhere.
- Checkout **changes nothing**. It returns a URL; redirect and wait. The
  subscription becomes real when the provider's webhook lands, so the
  return screen polls the subscription rather than assuming success.
- Cancelling sets `cancel_at_period_end` and leaves `status` as `active`.
  The screen must distinguish *stopping* from *stopped*, or it will say
  the wrong thing to both.
- `past_due` shows a warning and **keeps every feature enabled** (§3.4).
- `502 billing_provider_error` is the provider, not the customer. Say so,
  and offer a retry rather than a support link.
- `null` in `limits` renders as "Unlimited", never as a blank cell.

### Acceptance

- A `402` anywhere in the app renders the same upgrade prompt naming the
  missing feature
- A `past_due` workspace shows a warning with no feature disabled
- The pricing page renders signed out
- Usage meters and the limit that refuses an action agree

---

## Phase W8 — Automations and integrations

### Screens

Automation list, create, per-automation settings, run history, enable and
disable, run-due; WhatsApp connect, status and disconnect; storefront
connect, install callback landing, sync, status and disconnect.

### Endpoints (16)

`/automations` (POST, GET), `/automations/{id}` (GET, PATCH, DELETE),
`/automations/{id}/runs`, `/automations/run-due`,
`/integrations/whatsapp` (GET, DELETE), `…/whatsapp/connect`,
`/workspaces/{id}/integrations/{provider}` (GET, DELETE),
`…/{provider}/install`, `…/{provider}/sync`,
`/integrations/{provider}/callback` (GET, POST).

### Rules

- Both are plan-gated on **create only** — `REQUIRES_AUTOMATIONS`,
  `REQUIRES_ECOMMERCE`. A lapsed plan keeps reading, disabling and
  disconnecting what already exists. The screen must not hide those
  controls, or a customer is locked in by their own downgrade.
- `422 invalid_automation_settings` is per-automation and belongs on the
  field, not the page.
- The install callback is a **redirect target**, not an API call the
  client makes. It needs a landing route that renders success or failure
  and then sends the person to the integration screen.
- A WhatsApp access token is never returned by the API and must never
  appear in a form pre-filled. Connected or not is the whole state.
- Number and storefront counts are plan limits; show the ceiling.

### Acceptance

- Disconnecting explains what stops working
- A failed install callback lands somewhere that explains itself
- An automation's run history renders when there are no runs

---

## Phase W9 — Analytics, audit and API keys

The last tenant phase.

### Screens

Dashboard overview, conversation analytics, AI analytics, audit log with
filters, API key list, create key with one-time reveal, revoke.

### Endpoints (8)

`/analytics/overview`, `/analytics/conversations`, `/analytics/ai`,
`/audit-logs`, `/api-keys` (POST, GET), `/api-keys/{id}` (DELETE),
`/api-keys/current`.

### Rules

- Audit logs and API key **creation** are Business-plan features
  (`REQUIRES_AUDIT_LOGS`, `REQUIRES_API_ACCESS`). Listing and revoking
  keys are not gated — a downgraded workspace must still be able to
  revoke a key it can no longer create.
- **A key is returned once.** The reveal is modal, copyable, and warns
  before dismissal that it cannot be shown again.
- Date ranges: `422 invalid_date_range` and `422 unknown_timezone` are
  field errors on the range picker.
- Charts follow the project's own visualisation conventions; the numbers
  come from the API and are never recomputed client-side.

### Acceptance

- A workspace on Starter sees the audit screen with an upgrade prompt,
  not a 403 page
- The key reveal cannot be dismissed accidentally
- An empty analytics range renders zeroes, not an error

---

## Phase W10 — The console, read-only

The first platform phase. **No mutations anywhere.** Same principle the
API's own A2 followed, for the same reason.

### Screens

Console shell with its own layout and its own sign-in state, workspace
search, workspace detail (status, plan, counts, erasure date), members,
subscription, usage, integrations, the tenant's audit log, user search,
user detail, and the platform's own audit log.

### Endpoints (11)

`/admin/me`, `/admin/audit`, `/admin/workspaces` (GET),
`/admin/workspaces/{id}` and its `/members`, `/subscription`, `/usage`,
`/integrations`, `/audit`; `/admin/users` (GET), `/admin/users/{id}`.

### Rules

- **Every read here is audited by the API**, including the ones that look
  idle. The console must not poll, prefetch on hover, or speculatively
  load a workspace nobody opened — each of those writes rows to the
  platform log and makes it useless.
- `401 admin_session_expired` re-authenticates **into the console only**
  and leaves the tenant session alone (§3.5).
- `403 address_not_allowed` is terminal. Say the address is not permitted;
  offer nothing to click.
- A `404` here means no such row and says so — the opposite of §3.2.
- A cancelled workspace is visible with its erasure date, unlike on the
  tenant surface.
- This surface stops at aggregates. No conversation, message, contact or
  document is reachable until W11.

### Acceptance

- Nothing in the console issues a request the person did not ask for
- A workspace with no members and a user with no workspaces both render
- The console is unreachable from any customer-facing screen

---

## Phase W11 — Support access, and the door through it

Where staff can read a customer's actual data. The most dangerous phase;
build it slowly.

### Screens

Request support access with a reason and a duration, live grants with
time remaining, end access, and — only while a grant is live — the
workspace's conversation list and message threads.

### Endpoints (5)

`/admin/workspaces/{id}/support-access` (POST, GET, DELETE),
`/admin/workspaces/{id}/conversations`,
`/admin/workspaces/{id}/conversations/{id}/messages`.

### Rules

- `403 support_access_required` is the refusal this phase exists around,
  and it must read as **"ask for access"** rather than as a fault. It
  covers unknown, expired and revoked alike.
- The remaining time on a grant is always on screen while reading
  customer data. Access that expires silently mid-read is worse than
  access that is refused.
- `422 support_grant_too_long` names the configured maximum.
- The tenant can see in their own audit log that staff were here. The
  console says so plainly at the point of requesting — no silent power.
- Read-only. Nothing here writes into a customer's workspace.

### Acceptance

- Reading a conversation without a grant is refused and offers the
  request flow
- A grant that expires while a thread is open stops further reads
- Requesting access twice says a grant is already live (`409`)

---

## Phase W12 — Lifecycle, and the people who run it

The first console phase that changes anything.

### Screens

Suspend and unsuspend a workspace, cancel and restore, erase now,
reschedule erasure; activate and deactivate a user, verify an address,
revoke a user's sessions; staff list, grant access, change rank, revoke.

### Endpoints (14)

`/admin/workspaces/{id}/suspend`, `/unsuspend`, `/cancel`, `/restore`,
`/erase-now`, `/erase-after`; `/admin/users/{id}/activate`,
`/deactivate`, `/verify-email`, `/sessions/revoke`; `/admin/staff` (GET,
POST), `/admin/staff/{user_id}` (PATCH, DELETE).

### Rules

- **Destructive operations name their subject.** Erasure takes the
  workspace's slug typed in, not an "are you sure". `422
  confirmation_mismatch` renders on the field.
- `403 approval_required` means a second staff member must second the
  action. It is not an error and not a retry: the screen shows the
  request and who can approve it (approvals themselves are W13).
- Rank is a ladder, not a set: everything support can do, an admin can
  do. Granting and revoking staff is owner-only, and `409
  last_staff_owner` protects the last one.
- Suspension is an operational decision, not a billing one — the copy
  must not imply the customer failed to pay.
- `409 workspace_lifecycle` means the state does not permit it. Refetch
  and re-render the available actions.

### Acceptance

- Erasure cannot be triggered without typing the slug
- An action needing approval leaves a visible pending request
- Revoking your own staff access is refused with an explanation

---

## Phase W13 — Platform billing, operations, analytics and approvals

The last phase. Everything the console still cannot do.

### Screens

Subscription ledger with a `past_due` filter, billing event list with
replay, plan override grant and remove; job queue with retry and cancel,
refused webhook deliveries, platform health, connected WhatsApp numbers;
revenue, growth, AI spend and overview dashboards; approval requests,
approve, and the alert feed.

### Endpoints (20)

`/admin/billing/subscriptions`, `/admin/billing/events`,
`/admin/billing/events/{id}/replay`,
`/admin/workspaces/{id}/plan-override` (POST, DELETE), `/admin/jobs`
(GET), `/admin/jobs/{id}` (GET), `/admin/jobs/{id}/retry`, `/cancel`,
`/admin/health`, `/admin/webhooks/failures`,
`/admin/integrations/whatsapp`, `/admin/analytics/overview`, `/revenue`,
`/growth`, `/ai`, `/admin/approvals` (POST, GET),
`/admin/approvals/{id}/approve`, `/admin/alerts`.

### Rules

- `status=past_due` is the subscription screen's reason to exist. Make it
  a first-class filter, not a dropdown option — those are the customers
  somebody should be looking at before they become `unpaid`.
- A plan override outranks the provider and survives every webhook.
  `forever: true` (no expiry) renders in amber, per the API's own
  intent — a warning, not a refusal. `applies: false` shows an expired
  grant rather than hiding it.
- Replay is safe to press twice and `applied: false` is an ordinary
  answer meaning there was nothing to re-apply. Do not render it as
  failure. **Note:** an unknown event id currently answers `502
  billing_provider_error`, not the `404` the schema advertises — match on
  the code, and see §7.
- `/admin/health` is a page a person reads, not a probe an orchestrator
  polls. It may not be put on a refresh timer (see W10's rule on audited
  reads).
- Approvals close the loop opened in W12: a pending request from there
  is approved here, by somebody else.

### Acceptance

- The `past_due` list is reachable in one click from the console home
- A grant with no expiry is visibly flagged
- Replaying an already-applied event says so and changes nothing
- A failed job shows why it failed before offering a retry

---

# 7. What this plan refuses to do

Three things a screen will want and must not have.

- **It will not email invitations.** The API returns the token once and
  sends nothing; W4 shows a copyable link because that is the honest
  representation of what the API does. Wiring the existing sender is a
  change to the API, and it belongs in the API's plan.
- **It will not paper over the two schema mismatches.** `replay` answering
  `502` where it documents `404`, and `checkout`/`cancel` not declaring
  `403 workspace_suspended`, are API bugs. The client matches on `code`
  and works correctly today; it does not pretend the schema is right, and
  a fix upstream should delete the workaround.
- **It will not compute what the API can answer.** No client-side
  aggregation of analytics, no recomputed usage, no locally derived
  entitlement. Where a number is wanted that the API does not return, the
  answer is an endpoint.

---

# 8. Ordering, and why

`W1` blocks everything. `W2` blocks every workspace-scoped phase. `W7`
is deliberately later than the phases whose `402`s it explains — those
phases render a plain refusal until it lands, which is acceptable and
visibly incomplete, where building billing first would mean building it
against screens that did not exist yet.

`W3` is early because it is the product. A client that can run an inbox
and nothing else is worth shipping; one with settings, billing and
analytics but no inbox is not.

The four console phases come last as a block. They are the smallest
audience, they depend on nothing in the tenant app but its components,
and `W11` is the one to slow down for.
