# Baton — Platform Administration

## Specification and Implementation Plan

> Surface: **`/api/v1/admin`**, for the people who operate Baton
> Audience: **staff of the business that runs Baton**, not customers of it
> Status: **nothing of this exists yet**; every phase below is new work

---

# 1. What this is, and what it is not

Baton already has administration. A workspace has an owner, admins and
agents, and `WorkspaceAdminDep` is the guard that separates them. That is
**tenant administration**: a customer running their own business inside
Baton.

This document is about the other kind — **platform administration**. The
people who run Baton itself, who need to answer a support email about a
workspace they are not a member of, suspend an account that is not
paying, find out why a message never went out, or comp a plan for a pilot
customer.

The distinction matters more than it sounds, because the two have
opposite defaults:

| | Tenant admin | Platform admin |
| --- | --- | --- |
| Scope | one workspace | every workspace |
| Granted by | the workspace owner | the business running Baton |
| Answer to "no such workspace" | deliberately ambiguous | must be exact |
| A read is | ordinary | worth recording |
| Blast radius of a bug | one customer | all of them |

Nothing in this plan changes what a tenant can do. It adds a second door,
with its own key, its own log, and its own rules.

**Out of scope.** Refunds and invoice edits stay in the payment
provider's dashboard: it is better at them and it is already the system
of record. This surface reads billing and grants entitlements; it does
not move money. Nor is this a frontend — it is the API a back-office
frontend would call.

---

# 2. What already exists

Worth stating precisely, because roughly half of this plan is *reaching*
things the codebase already models rather than building new ones.

- **109 API operations**, all tenant-facing, under `/api/v1`
- `WorkspaceService.access()` — the tenant boundary, one method, proven
- `AuditLog` with a strictly-ordered `sequence`, an actor, and JSON `meta`
- `Job` with `kind`, `status`, `attempts`, `run_at`, `last_error` — and a
  **nullable `workspace_id`**, so platform-level jobs already fit
- `Workspace.status` (`ACTIVE` / `SUSPENDED` / `CANCELLED`) and
  `erase_after`, with `SWEEP_ERASURES` and `ERASE_WORKSPACE` jobs behind
  them
- `Subscription`, `BillingEvent`, `PlanTier`, `Feature`, `PlanLimit`
- `UsageRecord`, per workspace, per metric, per period
- `UserSession` with revocation, and `ApiKey` per workspace

---

# 3. Four things the codebase makes true

These are not opinions. They are constraints the existing code imposes,
and each one decides part of the design. Read this section before
building anything.

## 3.1 There is no staff identity, at all

```
grep -rn "is_superuser|is_staff|is_admin|platform_admin" app/   ->  nothing
```

`User` has `id`, `name`, `email`, `hashed_password`, `is_active`,
`email_verified_at`. Every authorisation decision in the system runs
through a `WorkspaceMembership`. There is no concept of a person who is
privileged *outside* a workspace, which means Phase A1 is not optional
and nothing else can start before it.

## 3.2 The audit log cannot hold a platform action

```python
workspace_id: Mapped[uuid.UUID] = mapped_column(
    ForeignKey("workspaces.id", ondelete="CASCADE"),
)
```

Two problems, and the second is the serious one.

**It is NOT NULL.** "Granted staff access to a colleague" belongs to no
workspace. There is nowhere to put it.

**It is `ON DELETE CASCADE`.** When a workspace is finally erased, its
audit log is erased with it. That is right for a tenant's own history —
the customer asked to be forgotten. It is wrong for the record of what
*staff* did, because the most important entry that log will ever hold is
"a staff member read this workspace two days before it was erased", and
CASCADE destroys exactly that entry at exactly that moment.

**Decision: a separate `admin_audit_logs` table**, with a nullable,
non-cascading workspace reference. Not a second copy of the same idea for
tidiness — the two have different lifetimes and different owners, and one
must survive the other's deletion.

## 3.3 `WorkspaceAccess` assumes a membership

```python
@dataclass
class WorkspaceAccess:
    workspace: Workspace
    membership: WorkspaceMembership

    @property
    def role(self) -> WorkspaceRole:
        return self.membership.role
```

A staff member looking at a customer's workspace **has no membership**.
There are three ways out and only one is acceptable:

1. Insert a real membership when support access is granted. **No.** It
   would appear in the customer's member list, in their audit log as an
   ordinary join, and in any seat count they are billed on. It makes
   staff indistinguishable from customers, which is the one property this
   feature must never have.
2. Fabricate a detached `WorkspaceMembership` in memory. Tempting, and
   still wrong: `audit.did(..., actor_user_id=access.membership.user_id)`
   would then write a normal-looking entry for an abnormal act.
3. **Make the actor explicit.** `WorkspaceAccess` grows an optional
   `staff_actor`, and `membership` becomes optional alongside it. Every
   call site that reads `access.role` must then say what a staff actor's
   role is — which is the point, because it forces each one to be decided
   rather than inherited.

Option 3 is the plan. It is the largest single refactor in this document
and it is confined to Phase A3.

## 3.4 The tenant boundary lies on purpose, and admin must not

```python
if workspace is None or workspace.status == WorkspaceStatus.CANCELLED:
    raise WorkspaceNotFoundError(workspace_id)

membership = self._memberships.get_for_user(workspace_id, user.id)

if membership is None or membership.status != MembershipStatus.ACTIVE:
    raise WorkspaceNotFoundError(workspace_id)
```

Three different refusals, one answer. That is deliberate and correct: it
stops a stranger using workspace ids to discover which businesses have
accounts.

**Admin must not inherit this.** A support engineer who cannot tell "no
such workspace" from "it was cancelled last week" cannot answer the
ticket. Admin routes return `404` only when nothing exists, and `403`
when the staff member's role is insufficient — and the reason they can
afford to be honest is that everyone reaching them is already
authenticated as staff and already being recorded.

## 3.5 Bonus: `SUSPENDED` is a word, not a feature

`WorkspaceStatus.SUSPENDED` is declared and **nothing sets it and nothing
checks it**. `access()` rejects only `CANCELLED`, so a workspace marked
suspended today would keep working normally. Phase A4 has to build both
halves; do not assume the enum value means the behaviour exists.

---

# 4. Principles

1. **The tenant surface does not change.** No customer-facing behaviour
   moves because staff needed something.
2. **Reads are audited too.** On this surface, looking at a customer's
   data *is* the sensitive act. A log that records only writes answers
   the wrong question.
3. **Read before write.** Every phase ships its read endpoints before its
   mutations. A console that is useful and cannot break anything is worth
   more than a half-finished one that can.
4. **No silent power.** A tenant can always see, in their own audit log,
   that staff touched their workspace.
5. **Staff access is granted, time-boxed, and expires.** Standing access
   to every customer's data is not access control.
6. **Destructive operations name their subject.** Deleting takes the
   workspace's slug in the body, not just its id in the path.
7. **Services enforce; dependencies declare.** The same rule the tenant
   side already follows — a role check in a signature is documentation,
   the service is the enforcement.
8. **Admin never writes tenant data directly.** It calls the same
   services a customer's request would, so business rules cannot be
   bypassed by going through the back door.
9. **Every phase is shippable and tested.** Same bar as the rest of the
   project.

---

# 5. The phases

## Phase A1 — Staff identity, the door, and its own log

**Nothing else can start before this.** It builds the concept of a
privileged person and the record of what they do.

### Model

`staff_members` — a table, not a boolean on `users`:

| Column | Notes |
| --- | --- |
| `id` | uuid |
| `user_id` | FK users, unique — staff are ordinary accounts, promoted |
| `role` | `support` / `admin` / `owner` |
| `granted_by_user_id` | who promoted them |
| `granted_at`, `revoked_at` | nullable revoked_at; rows are kept |

A row rather than `users.is_staff` because a boolean cannot say who
granted it, when, or that it was taken away — and those are the three
questions asked after an incident.

`StaffRole`:

- **`support`** — read the console, request support access to a workspace
- **`admin`** — everything support can do, plus lifecycle and billing
- **`owner`** — everything, plus granting and revoking staff

`admin_audit_logs` — see §3.2:

| Column | Notes |
| --- | --- |
| `id`, `sequence` | same `Identity(always=True)` ordering as `AuditLog` |
| `actor_user_id`, `actor_email` | email kept, so the row survives the account |
| `action` | `AdminAction` StrEnum |
| `workspace_id` | **nullable, `ON DELETE SET NULL`** — never cascade |
| `workspace_slug` | denormalised, so the row still names its subject after erasure |
| `target_user_id` | nullable |
| `meta` | JSON |
| `ip_address`, `user_agent` | who and from where |
| `created_at` | |

### Routes

| Method | Path | Role |
| --- | --- | --- |
| GET | `/admin/me` | any staff |
| GET | `/admin/staff` | admin |
| POST | `/admin/staff` | owner |
| PATCH | `/admin/staff/{user_id}` | owner |
| DELETE | `/admin/staff/{user_id}` | owner |
| GET | `/admin/audit` | admin |

### Rules

- `StaffDep`, `StaffAdminDep`, `StaffOwnerDep`, mirroring the
  `WorkspaceMemberDep` / `WorkspaceAdminDep` shape already in use
- The router is mounted separately, so no admin path can ever be
  reachable through the tenant router by accident
- An owner cannot revoke their own last owner row — the same
  "refuse to strand" rule `MembershipService` already applies
- Staff auth reuses ordinary login. It does **not** reuse ordinary
  sessions: an admin session gets its own shorter idle timeout
- Admin rate limit scope: `RateLimited.ADMIN`
- `/admin/audit` is append-only and has no delete route, at any role

### Acceptance

- A non-staff user gets `403` from every `/admin` path
- A revoked staff member gets `403` on the next request
- Granting, changing and revoking staff each write an `admin_audit_logs`
  row naming both actor and subject
- Erasing a workspace leaves its `admin_audit_logs` rows intact, with
  `workspace_slug` still readable — one test, and it is the point of the
  phase

---

## Phase A2 — The console, read-only

The phase that makes support possible. No mutations anywhere.

### Routes

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/admin/workspaces` | Search by name, slug, status, plan; paged |
| GET | `/admin/workspaces/{id}` | One workspace: status, plan, counts, erase_after |
| GET | `/admin/workspaces/{id}/members` | Who is in it and with what role |
| GET | `/admin/workspaces/{id}/subscription` | Plan, status, period, provider ids |
| GET | `/admin/workspaces/{id}/usage` | Usage by metric and period |
| GET | `/admin/workspaces/{id}/integrations` | WhatsApp and storefront, connected or not |
| GET | `/admin/workspaces/{id}/audit` | The tenant's own audit log |
| GET | `/admin/users` | Search by email or name; paged |
| GET | `/admin/users/{id}` | One user, their memberships, their sessions |

### Rules

- **Aggregates and metadata only.** No route here returns a conversation,
  a message, a contact or a knowledge document. Reading a customer's
  actual customer data requires Phase A3, which is time-boxed and
  visible to the tenant. This phase deliberately stops at the line.
- Every one of these writes an `admin_audit_logs` row. Yes, on a GET. See
  principle 2.
- Never leak a secret: `provider_customer_id` is fine, an encrypted
  WhatsApp token is not decrypted here for any reason.
- All counting happens in repositories with explicit queries. A console
  that lazy-loads relationships across 500 workspaces will melt.

### Acceptance

- A workspace can be found by slug, by owner email, and by plan
- A cancelled workspace is visible with its `erase_after` date — unlike
  the tenant surface, which pretends it is gone
- Reading a workspace with no members, or a user with no workspaces,
  answers cleanly rather than erroring
- Every read appears in `/admin/audit`

---

## Phase A3 — Support access to a workspace

Where staff can read a customer's actual data. The most dangerous phase;
build it slowly.

### Model

`support_grants`:

| Column | Notes |
| --- | --- |
| `id`, `workspace_id`, `staff_user_id` | |
| `reason` | required, free text, minimum length enforced |
| `expires_at` | required; a grant with no end is not a grant |
| `revoked_at` | nullable |
| `created_at` | |

### The refactor

Per §3.3:

```python
@dataclass
class WorkspaceAccess:
    workspace: Workspace
    membership: WorkspaceMembership | None = None
    staff_actor: StaffMember | None = None

    @property
    def role(self) -> WorkspaceRole: ...
```

Every existing reader of `.role` and `.membership.user_id` must be
visited. `mypy` finds them all the moment `membership` becomes optional —
which is why this is safe to attempt at all, and why it should be one
commit that changes nothing else.

Rules that fall out of it:

- A staff actor's effective role is **read-only**, whatever their staff
  role. Support access reads; it does not act as the customer.
- `audit.did(...)` with a staff actor writes to *both* logs: the tenant's,
  so the customer can see it, and `admin_audit_logs`, so it outlives them.
- The tenant's entry says a staff member did it. It must never look like
  one of their own people.

### Routes

| Method | Path | Role |
| --- | --- | --- |
| POST | `/admin/workspaces/{id}/support-access` | support — reason and duration required |
| DELETE | `/admin/workspaces/{id}/support-access` | support — end it early |
| GET | `/admin/workspaces/{id}/support-access` | admin — active and historical grants |
| GET | `/admin/workspaces/{id}/conversations` | needs a live grant |
| GET | `/admin/workspaces/{id}/conversations/{cid}/messages` | needs a live grant |

### Acceptance

- Reading a conversation without a grant is `403`, with a live grant is
  `200`, and with an expired one is `403` again
- Maximum duration is capped in configuration; a request for longer is
  refused rather than clamped
- The tenant sees the access in their own `/api/v1/workspaces/{id}/audit`
- No staff route can write tenant data in this phase, proven by test
- A grant does not appear in the workspace's member list or seat count

---

## Phase A4 — Lifecycle

### Routes

| Method | Path | Role |
| --- | --- | --- |
| POST | `/admin/workspaces/{id}/suspend` | admin — reason required |
| POST | `/admin/workspaces/{id}/unsuspend` | admin |
| POST | `/admin/workspaces/{id}/cancel` | admin — body must echo the slug |
| POST | `/admin/workspaces/{id}/restore` | admin — before `erase_after` only |
| PATCH | `/admin/workspaces/{id}/erase-after` | admin — extend or bring forward |
| POST | `/admin/workspaces/{id}/erase-now` | owner — body must echo the slug |
| POST | `/admin/users/{id}/deactivate` | admin |
| POST | `/admin/users/{id}/activate` | admin |
| POST | `/admin/users/{id}/sessions/revoke` | admin — sign out everywhere |
| POST | `/admin/users/{id}/verify-email` | admin — when delivery failed |

### Rules

- **Suspension has to be built, not just set** (§3.5). `access()` grows a
  suspended branch: a suspended workspace is *reachable and frozen* —
  reads succeed, writes are refused with a distinct error naming the
  suspension. That is the behaviour the enum comment already promises,
  and it is the useful one: a customer who has not paid should be able to
  read their history and pay, not be locked out of their own data.
  Webhook ingestion for a suspended workspace must be decided explicitly:
  **accept and store, do not auto-reply**, so a suspension does not lose
  a customer's messages.
- Cancel routes through the existing `WorkspaceService` close path, so
  `erase_after` and the erasure jobs behave identically to a customer
  closing their own account.
- `erase-now` is the most destructive call in the product. Owner only,
  slug echoed in the body, and audited before it runs, not after.
- Deactivating a user revokes their sessions in the same transaction.
  A deactivated account that stays signed in is not deactivated.

### Acceptance

- Suspension actually blocks writes and permits reads, per route
- A suspended workspace still ingests inbound WhatsApp messages
- Restore before `erase_after` returns the workspace intact; after it,
  the route refuses rather than pretending
- `erase-now` with the wrong slug is refused and audited as an attempt

---

## Phase A5 — Billing and entitlements

### Model

The problem: `Subscription.plan` is what the payment provider says. Staff
need to grant a plan the provider knows nothing about — a pilot, a comp,
an enterprise contract invoiced offline. Overwriting `plan` directly
means the next provider webhook silently reverts it.

`plan_overrides`:

| Column | Notes |
| --- | --- |
| `workspace_id` | unique |
| `plan` | the tier granted |
| `reason`, `granted_by_user_id` | |
| `expires_at` | nullable — but a warning if unset |

Resolution order becomes **override, then subscription, then free**, in
one function that both the tenant surface and admin call. Nothing reads
`subscription.plan` directly any more.

### Routes

| Method | Path | Role |
| --- | --- | --- |
| GET | `/admin/billing/subscriptions` | admin — filter by status and plan |
| POST | `/admin/workspaces/{id}/plan-override` | admin |
| DELETE | `/admin/workspaces/{id}/plan-override` | admin |
| GET | `/admin/billing/events` | admin — provider deliveries, newest first |
| POST | `/admin/billing/events/{id}/replay` | admin — reprocess a stored delivery |

### Acceptance

- An override outranks the subscription, and a provider webhook arriving
  afterwards does not disturb it
- Removing an override falls back to whatever the provider last said
- An expired override stops applying without anything having to run
- Replaying an already-processed event is idempotent — `BillingEvent`
  already dedupes on the provider's event id; this must not defeat it

---

## Phase A6 — Operations

Where "why did this not work" gets answered without a database console.

### Routes

| Method | Path | Role |
| --- | --- | --- |
| GET | `/admin/jobs` | admin — filter by kind, status, workspace |
| GET | `/admin/jobs/{id}` | admin — payload, attempts, `last_error` |
| POST | `/admin/jobs/{id}/retry` | admin — reset attempts, run now |
| POST | `/admin/jobs/{id}/cancel` | admin |
| GET | `/admin/webhooks/failures` | admin — deliveries that did not verify |
| GET | `/admin/integrations/whatsapp` | admin — every connected number and its health |
| GET | `/admin/health` | admin — database, provider reachability, queue depth |

### Rules

- A job payload can contain customer message text. Redact by `JobKind`
  rather than dumping `payload` — an operations console is not a licence
  to read messages, and Phase A3 exists for when that is genuinely needed.
- Retry must respect `dedupe_key`, or a retried job races the original.

### Acceptance

- A failed `DELIVER_MESSAGE` job is findable by workspace and by error
- Retrying moves it back to pending and it is picked up
- Queue depth and oldest-pending-age are exposed — the two numbers that
  say the worker has stopped

---

## Phase A7 — Platform analytics

Deliberately last. It is the most fun to build and the least urgent, and
building it early produces a dashboard nobody can act on.

| Method | Path |
| --- | --- |
| GET | `/admin/analytics/overview` |
| GET | `/admin/analytics/growth` |
| GET | `/admin/analytics/revenue` |
| GET | `/admin/analytics/ai` |

Workspaces by status and plan; signups and closures over time; active
workspaces by real activity rather than by row count; AI spend across all
tenants, which is the number that decides whether the pricing works.

Every figure is an aggregate. No route here reveals one customer's data.

---

## Phase A8 — Hardening

Some of this belongs in A1; the rest is worth doing before the surface
carries real traffic.

- Two-person approval on `erase-now` and on granting `owner`
- Optional IP allowlist for `/admin`, off by default
- Admin session TTL shorter than a tenant's, enforced separately
- Alert on unusual patterns: support grants outside working hours, one
  staff member reading many workspaces in a short window
- A scheduled job expiring stale support grants, so expiry does not
  depend on someone reading a timestamp
- Load `/admin/audit` into whatever log store operations already uses

---

# 6. Route summary

| Phase | Routes | Theme |
| --- | --- | --- |
| A1 | 6 | Staff identity and the admin audit log |
| A2 | 9 | Read-only console |
| A3 | 5 | Time-boxed support access |
| A4 | 10 | Lifecycle |
| A5 | 5 | Billing and entitlements |
| A6 | 7 | Operations |
| A7 | 4 | Platform analytics |

Roughly **46 operations**, against the 109 that exist now.

---

# 7. Testing

Same bar as the rest of the project, plus three that are specific to this
surface and are the ones worth writing first:

1. **Every `/admin` route refuses a non-staff user.** Parametrised over
   the whole router by introspection, so a route added later is covered
   without anyone remembering to add it — the same trick that would have
   caught a missing tenant guard.
2. **Every `/admin` route writes an audit row**, reads included.
3. **The admin log survives its subject.** Erase a workspace; the rows
   naming it are still there and still name it.

---

# 8. Decisions to make before Phase A1

Each of these changes the shape of the work, and none has an obvious
default:

1. **Do staff sign in through `/api/v1/auth/login`, or a separate path?**
   Shared is simpler and means one account. Separate allows different
   password rules, mandatory MFA, and an IP allowlist without touching
   the tenant flow. *Recommendation: shared login now, separate session
   policy, and leave room for MFA.*
2. **Should the first staff row be seeded by migration, or by CLI?** A
   migration is reproducible and puts a privileged account in version
   control. *Recommendation: a CLI command, run once per deployment.*
3. **Does support access need the customer's consent?** Legally it may,
   depending on the market and what the terms say. Consent-on-request is
   a materially different feature from notify-after, and it is cheaper to
   decide now than to retrofit.
4. **How long can a support grant last?** *Recommendation: 4 hours,
   configurable, hard-capped at 24.*
5. **Is `/admin` on the same deployment?** Same process is simplest and
   what this plan assumes. A separate one lets the network keep it off
   the public internet entirely.

---

# 9. Suggested order

A1 → A2 gives a working, safe support console and is where most of the
value lands. A3 is the one to slow down for. A4 through A6 can be
reordered to follow whatever is actually hurting; A7 should stay last.
