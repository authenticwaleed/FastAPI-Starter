# LeadPilot — AI WhatsApp Sales & Support SaaS
## Product Specification and Implementation Plan

> Working product name: **LeadPilot**  
> Backend: **FastAPI + PostgreSQL + SQLAlchemy 2.x**  
> Initial niche: **E-commerce businesses using WhatsApp for sales and customer support**  
> Recommended first sub-niche: **Fashion / apparel e-commerce stores**

---

# 1. Product Vision

LeadPilot is a multi-tenant SaaS platform that helps e-commerce businesses manage and automate customer conversations on WhatsApp.

The system should allow a business to:

- Connect its WhatsApp Business account
- Receive customer messages in a shared inbox
- Let an AI assistant answer repetitive questions
- Ground AI answers in the business's own knowledge base using RAG
- Hand conversations to human agents when the AI should not answer
- Track contacts, conversations, leads and outcomes
- Later connect Shopify / WooCommerce for products and orders
- Later automate follow-ups, abandoned cart recovery and order confirmation
- Measure response time, AI automation rate and sales/support outcomes
- Charge businesses through SaaS subscription plans

The product should not be positioned as:

> "Another AI chatbot."

The product should be positioned around business outcomes:

> "Automatically answer WhatsApp customers, recover leads, reduce repetitive support work and help convert conversations into orders."

---

# 2. Initial Target Customer

The first version should target a narrow customer profile.

## Recommended ICP

**Small and medium e-commerce businesses that:**

- Receive a meaningful number of customer messages on WhatsApp
- Sell products through Instagram, Facebook, Shopify, WooCommerce or their own website
- Repeatedly answer questions about:
  - price
  - size
  - color
  - availability
  - shipping
  - cash on delivery
  - returns
  - exchange policy
  - order status
- Have 1–10 people handling customer conversations
- Lose leads because responses are delayed
- Want automation but still need human control

## Recommended first niche

Fashion / apparel stores are a strong first niche because customer questions are repetitive and structured:

- Is size M available?
- Do you have black?
- What is the size chart?
- Can I exchange this?
- Is COD available?
- How long does delivery take?
- Where is my order?
- Can you recommend something similar?

This gives the product a clear problem to solve.

---

# 3. Product Principles

Throughout implementation, follow these rules:

1. **Do not build features before the underlying domain model is correct.**
2. **Every business-owned resource must belong to a workspace.**
3. **Authorization must be workspace-aware.**
4. **Routes handle HTTP concerns only.**
5. **Services contain business logic.**
6. **Repositories contain persistence logic.**
7. **Pydantic schemas define API contracts.**
8. **SQLAlchemy models define database persistence.**
9. **External integrations are isolated behind adapter/service layers.**
10. **AI output is never trusted blindly.**
11. **RAG must return evidence and confidence metadata internally.**
12. **Humans must be able to take over conversations.**
13. **Never log passwords, tokens, message secrets or customer-sensitive data unnecessarily.**
14. **Every important feature requires tests.**
15. **Do not add microservices until the monolith actually becomes a bottleneck.**
16. **Do not add Kafka, Redis, Celery, vector databases or other infrastructure just because they are popular. Add them when a real requirement appears.**
17. **Build the product in vertical slices that can be tested end to end.**

---

# 4. Existing Foundation

The current FastAPI starter already contains:

- FastAPI application structure
- `/api/v1` version prefix
- Central router
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- Repository layer
- Service layer
- User CRUD
- Argon2id password hashing
- JWT authentication
- Centralized exception handling
- Logging
- CORS
- Trusted hosts
- Liveness and readiness probes
- Docker
- Ruff
- mypy
- pre-commit
- pytest
- test database
- environment settings

This means the next work should focus on turning the starter into a SaaS product rather than rebuilding infrastructure.

---

# 5. Target High-Level Architecture

```text
Client / Dashboard
        |
        v
FastAPI HTTP API
        |
        +-------------------------------+
        |                               |
        v                               v
Authentication                    Webhook Endpoints
        |                               |
        v                               v
Workspace Authorization        WhatsApp Integration
        |                               |
        +---------------+---------------+
                        |
                        v
                 Service Layer
                        |
        +---------------+-------------------+
        |               |                   |
        v               v                   v
Conversation        Knowledge           Orders /
Services            / RAG               Products
        |               |                   |
        +---------------+-------------------+
                        |
                        v
                 Repository Layer
                        |
                        v
                   PostgreSQL
```

Later, asynchronous work can be introduced:

```text
Incoming WhatsApp message
        |
        v
Webhook
        |
        v
Persist message
        |
        v
Queue / Background Job
        |
        +--> RAG retrieval
        |
        +--> AI response generation
        |
        +--> Send WhatsApp response
        |
        +--> Analytics event
```

Do not introduce the queue until synchronous/background-task processing becomes insufficient.

---

# 6. Core Domain Model

The minimum SaaS domain should evolve toward:

```text
User
 |
 +--> WorkspaceMembership --> Workspace
                              |
                              +--> Contacts
                              |
                              +--> Conversations
                              |      |
                              |      +--> Messages
                              |
                              +--> Knowledge Sources
                              |      |
                              |      +--> Documents
                              |             |
                              |             +--> Chunks
                              |
                              +--> WhatsApp Integration
                              |
                              +--> Automations
                              |
                              +--> Usage Records
                              |
                              +--> Subscription
```

Later:

```text
Workspace
 |
 +--> Products
 |
 +--> Orders
 |
 +--> Integrations
 |      |
 |      +--> Shopify
 |      +--> WooCommerce
 |
 +--> Analytics Events
 |
 +--> API Keys
 |
 +--> Audit Logs
```

---

# 7. Core Database Entities

## 7.1 users

Existing user table.

Recommended fields:

```text
id
name
email
hashed_password
is_active
email_verified_at
created_at
updated_at
```

---

## 7.2 workspaces

Represents one customer business / tenant.

```text
id
name
slug
status
timezone
default_currency
created_by_user_id
created_at
updated_at
```

Recommended statuses:

```text
active
suspended
cancelled
```

---

## 7.3 workspace_memberships

Connects users to businesses.

```text
id
workspace_id
user_id
role
status
created_at
updated_at
```

Roles for MVP:

```text
owner
admin
agent
viewer
```

Do not build a fully dynamic permission engine initially.

---

## 7.4 workspace_invitations

```text
id
workspace_id
email
role
token_hash
expires_at
accepted_at
invited_by_user_id
created_at
```

Never store the raw invitation token.

---

## 7.5 contacts

Represents the end customer messaging the business.

```text
id
workspace_id
external_id
phone_number
name
email
status
source
metadata
created_at
updated_at
```

Possible statuses:

```text
lead
customer
blocked
```

---

## 7.6 conversations

```text
id
workspace_id
contact_id
channel
status
assigned_user_id
ai_mode
last_message_at
opened_at
closed_at
created_at
updated_at
```

Statuses:

```text
open
pending
closed
```

AI modes:

```text
automatic
suggest_only
disabled
```

---

## 7.7 messages

```text
id
workspace_id
conversation_id
sender_type
direction
channel
external_message_id
content_type
text
status
sent_at
received_at
created_at
```

Sender types:

```text
customer
agent
ai
system
```

Direction:

```text
inbound
outbound
```

Message status:

```text
queued
sent
delivered
read
failed
received
```

Later support:

```text
image
audio
video
document
interactive
location
```

Do not implement every WhatsApp message type in the MVP.

---

## 7.8 whatsapp_accounts

```text
id
workspace_id
provider
phone_number
external_phone_number_id
external_business_account_id
access_token_encrypted
status
connected_at
created_at
updated_at
```

Important:

- Encrypt provider tokens at rest
- Do not return access tokens from API responses
- Never write provider tokens to logs

---

## 7.9 knowledge_sources

Represents uploaded or synchronized information.

```text
id
workspace_id
name
source_type
status
created_at
updated_at
```

Source types:

```text
text
file
website
manual_faq
product_catalog
```

For MVP, start with:

```text
text
file
manual_faq
```

---

## 7.10 knowledge_documents

```text
id
workspace_id
knowledge_source_id
title
content_hash
status
metadata
created_at
updated_at
```

Statuses:

```text
pending
processing
ready
failed
```

---

## 7.11 knowledge_chunks

```text
id
workspace_id
document_id
chunk_index
content
embedding
token_count
metadata
created_at
```

The storage choice for embeddings can evolve later.

A reasonable MVP path is:

```text
PostgreSQL
    +
pgvector
```

This keeps infrastructure simple.

---

## 7.12 ai_response_logs

Useful for evaluation and debugging.

```text
id
workspace_id
conversation_id
message_id
model
prompt_version
retrieval_query
retrieved_chunk_ids
confidence
decision
latency_ms
input_tokens
output_tokens
created_at
```

Possible decision values:

```text
answered
suggested
handoff
blocked
failed
```

Do not store unnecessary sensitive prompt contents indefinitely.

---

## 7.13 subscriptions

Later phase.

```text
id
workspace_id
provider
provider_customer_id
provider_subscription_id
plan
status
current_period_start
current_period_end
cancel_at_period_end
created_at
updated_at
```

---

## 7.14 usage_records

```text
id
workspace_id
metric
quantity
period_start
period_end
created_at
```

Possible metrics:

```text
ai_responses
messages
conversations
knowledge_tokens
team_members
```

---

# 8. API Design

All tenant data should be scoped by workspace where ownership matters.

Recommended pattern:

```text
/api/v1/workspaces/{workspace_id}/...
```

Do not trust `workspace_id` simply because the client supplied it.

Every request must verify:

```text
authenticated user
        |
        v
workspace membership
        |
        v
required role / permission
        |
        v
resource belongs to workspace
```

---

# 9. Phase 0 — Market Validation Before Product Expansion

## Goal

Validate the problem before spending months implementing advanced features.

## Tasks

Interview at least:

```text
10 business owners
```

Try to recruit at least:

```text
3 pilot businesses
```

Ask:

- How many WhatsApp conversations do you receive daily?
- What questions repeat most often?
- Who answers them?
- How quickly do you normally respond?
- What happens outside business hours?
- How do you confirm orders?
- How do you track leads?
- How often do customers ask for order status?
- What causes conversations to be lost?
- What current tools do you use?
- What do you already pay for?
- Would you allow an AI assistant to answer automatically?
- Which questions must always go to a human?
- What would make this worth paying for?

## Deliverables

Create:

```text
docs/market-validation.md
```

Include:

```text
interview notes
top recurring problems
top requested features
existing alternatives
pricing feedback
pilot candidates
```

## Acceptance criteria

- [ ] 10 customer interviews completed
- [ ] Most common support/sales questions documented
- [ ] At least 3 businesses willing to test
- [ ] One primary niche selected
- [ ] MVP scope updated from real interviews

Do not skip this phase.

---

# 10. Phase 1 — Protect the Existing User System

## Goal

Remove the current authorization weakness before introducing tenant data.

## Changes

Existing generic user administration should no longer be publicly accessible to ordinary users.

Recommended public account endpoints:

```text
GET    /api/v1/account
PATCH  /api/v1/account
POST   /api/v1/account/change-password
DELETE /api/v1/account
```

Admin-level user management, if needed, should be separated later.

## New files

```text
app/api/routes/account.py
app/services/account_service.py
app/schemas/account.py
```

## Tests

- authenticated user can read own account
- authenticated user can update own account
- user cannot update another user's account
- passwords are never returned
- inactive account cannot access protected resources

## Acceptance criteria

- [x] Public `/users` operations are removed or restricted appropriately
- [x] Self-service account API exists
- [x] Authorization tests pass

---

# 11. Phase 2 — Workspaces / Multi-Tenancy

## Goal

Introduce the tenant boundary.

## Endpoints

```text
POST   /api/v1/workspaces
GET    /api/v1/workspaces
GET    /api/v1/workspaces/{workspace_id}
PATCH  /api/v1/workspaces/{workspace_id}
DELETE /api/v1/workspaces/{workspace_id}
```

## Example create request

```json
{
  "name": "Acme Fashion",
  "slug": "acme-fashion",
  "timezone": "Asia/Karachi",
  "default_currency": "PKR"
}
```

## Business rules

When a workspace is created:

```text
create workspace
        |
        v
create membership
        |
        v
creator role = owner
```

Slug must be unique.

A user may belong to multiple workspaces.

## New files

```text
app/models/workspace.py
app/models/workspace_membership.py

app/schemas/workspace.py
app/schemas/workspace_membership.py

app/repositories/workspace_repository.py
app/repositories/workspace_membership_repository.py

app/services/workspace_service.py

app/api/routes/workspaces.py
app/api/dependencies/workspace.py
```

## Tests

- user creates workspace
- creator becomes owner
- duplicate slug rejected
- unrelated user cannot read workspace
- member can read workspace
- unauthorized update rejected
- delete behavior tested

## Acceptance criteria

- [x] Workspace model exists
- [x] Membership model exists
- [x] Alembic migration exists
- [x] Workspace CRUD implemented
- [x] Every operation checks membership

---

# 12. Phase 3 — Roles and Workspace Authorization

## Goal

Create reusable authorization dependencies.

## MVP roles

```text
owner
admin
agent
viewer
```

## Recommended permissions

### owner

```text
all workspace actions
billing
delete workspace
manage admins
```

### admin

```text
manage agents
manage knowledge
manage conversations
manage integrations
view analytics
```

### agent

```text
view conversations
send messages
take over conversations
view contacts
```

### viewer

```text
read-only dashboard access
```

## Example dependencies

Conceptually:

```python
CurrentUserDep
WorkspaceMemberDep
WorkspaceAdminDep
WorkspaceOwnerDep
```

Or a permission helper:

```python
require_workspace_role("owner", "admin")
```

Avoid hard-coding role checks repeatedly inside routes.

## Tests

- viewer cannot modify workspace
- agent cannot manage billing
- admin cannot delete owner
- owner can manage roles
- cross-workspace access rejected

## Acceptance criteria

- [x] Reusable workspace authorization dependency exists
- [x] Role checks are centralized
- [x] Cross-tenant tests exist

---

# 13. Phase 4 — Workspace Invitations

## Goal

Allow business owners to invite team members.

## Endpoints

```text
POST   /api/v1/workspaces/{workspace_id}/invitations
GET    /api/v1/workspaces/{workspace_id}/invitations
DELETE /api/v1/workspaces/{workspace_id}/invitations/{invitation_id}

GET    /api/v1/invitations/{token}
POST   /api/v1/invitations/{token}/accept
```

## Flow

```text
Owner enters email + role
        |
        v
Generate secure random token
        |
        v
Store token hash
        |
        v
Send invitation email
        |
        v
User opens invitation
        |
        v
Validate token + expiry
        |
        v
Create membership
```

## Important rules

- invitation tokens expire
- store token hash, not raw token
- same user should not get duplicate active membership
- role must be allowed
- invitations should be revocable

## Acceptance criteria

- [x] Team member can be invited
- [x] Invitation expires
- [x] Invitation can be accepted once
- [x] Membership created correctly
- [x] Permission checks covered by tests

---

# 14. Phase 5 — Contacts

## Goal

Introduce end customers.

## Endpoints

```text
POST   /api/v1/workspaces/{workspace_id}/contacts
GET    /api/v1/workspaces/{workspace_id}/contacts
GET    /api/v1/workspaces/{workspace_id}/contacts/{contact_id}
PATCH  /api/v1/workspaces/{workspace_id}/contacts/{contact_id}
```

## Query parameters

Support eventually:

```text
search
status
source
page
page_size
```

## Important rules

Within one workspace, WhatsApp phone number should normally identify a contact.

Do not make phone number globally unique because the same customer can interact with multiple businesses.

## Acceptance criteria

- [x] Contacts belong to workspace
- [x] Phone number normalized
- [x] Duplicate handling defined
- [x] Pagination exists
- [x] Cross-tenant access rejected

---

# 15. Phase 6 — Conversations and Messages

## Goal

Build the core inbox data model before integrating WhatsApp.

## Conversation endpoints

```text
GET    /api/v1/workspaces/{workspace_id}/conversations
POST   /api/v1/workspaces/{workspace_id}/conversations

GET    /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}
PATCH  /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}

POST   /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/assign
POST   /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/close
POST   /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/reopen
```

## Message endpoints

```text
GET  /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages
POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages
```

## Message request

```json
{
  "text": "Hello, how can I help?"
}
```

## Business rules

- conversation belongs to one contact
- conversation belongs to one workspace
- messages cannot cross workspaces
- outbound human message requires agent permission
- closed conversation may reopen when new inbound message arrives

## Acceptance criteria

- [x] Conversation CRUD/domain operations exist
- [x] Messages persisted
- [x] Assignment works
- [x] Close/reopen works
- [x] Message ordering is deterministic
- [x] Pagination exists

---

# 16. Phase 7 — WhatsApp Integration

## Goal

Connect a real WhatsApp Business number.

Keep provider-specific code isolated.

Recommended abstraction:

```text
MessagingProvider
        |
        +--> WhatsAppProvider
```

## Files

```text
app/integrations/messaging/base.py
app/integrations/messaging/whatsapp.py

app/services/whatsapp_service.py
app/services/message_ingestion_service.py

app/api/routes/whatsapp.py
app/api/routes/webhooks.py
```

## Endpoints

```text
POST /api/v1/workspaces/{workspace_id}/integrations/whatsapp/connect
GET  /api/v1/workspaces/{workspace_id}/integrations/whatsapp
DELETE /api/v1/workspaces/{workspace_id}/integrations/whatsapp

GET  /api/v1/webhooks/whatsapp
POST /api/v1/webhooks/whatsapp
```

## Incoming message flow

```text
WhatsApp
    |
    v
Webhook
    |
    v
Verify webhook authenticity
    |
    v
Parse provider event
    |
    v
Find workspace by connected account
    |
    v
Find/create contact
    |
    v
Find/create open conversation
    |
    v
Persist inbound message
```

## Outbound flow

```text
Agent / AI
    |
    v
Message service
    |
    v
Persist pending outbound message
    |
    v
WhatsApp provider
    |
    v
Update message status
```

## Critical implementation details

- webhook processing must be idempotent
- external message IDs must be unique per integration
- provider retries must not create duplicate messages
- webhook verification must be tested
- invalid signatures/events must be rejected
- provider errors must be recorded safely
- tokens must not appear in logs

## MVP scope

Initially support:

```text
text inbound
text outbound
delivery status updates
```

Do not implement voice, video and every interactive template yet.

## Acceptance criteria

- [ ] WhatsApp account can be connected
- [ ] Incoming message creates/updates contact
- [ ] Incoming message creates conversation if needed
- [ ] Incoming message saved once
- [ ] Agent can reply from API
- [ ] Status webhooks update message state

---

# 17. Phase 8 — Shared Inbox API

## Goal

Make the backend usable by a frontend dashboard.

## Features

- list open conversations
- filter by assigned agent
- filter by unassigned
- filter by contact
- sort by last message
- unread count
- assign conversation
- send reply
- close/reopen
- view contact profile

## Example endpoint

```text
GET /api/v1/workspaces/{workspace_id}/conversations
```

Query:

```text
status=open
assigned_to=me
search=ali
page=1
page_size=30
```

## Conversation response should include

```text
conversation id
contact summary
status
assigned agent
AI mode
last message preview
last message timestamp
unread count
```

Avoid requiring the frontend to make five API calls just to render one inbox row.

## Acceptance criteria

- [ ] Inbox query is efficient
- [ ] Common filters implemented
- [ ] unread state defined
- [ ] no N+1 query problems in normal list response

---

# 18. Phase 9 — Knowledge Base

## Goal

Allow businesses to provide information the AI can use.

## MVP knowledge inputs

1. Manual FAQ
2. Plain text
3. PDF / text document upload

Website crawling can come later.

## Endpoints

```text
POST   /api/v1/workspaces/{workspace_id}/knowledge/sources
GET    /api/v1/workspaces/{workspace_id}/knowledge/sources
GET    /api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}
DELETE /api/v1/workspaces/{workspace_id}/knowledge/sources/{source_id}

POST   /api/v1/workspaces/{workspace_id}/knowledge/documents
GET    /api/v1/workspaces/{workspace_id}/knowledge/documents
GET    /api/v1/workspaces/{workspace_id}/knowledge/documents/{document_id}
DELETE /api/v1/workspaces/{workspace_id}/knowledge/documents/{document_id}

POST   /api/v1/workspaces/{workspace_id}/knowledge/search
```

## Ingestion flow

```text
Upload document
      |
      v
Validate file
      |
      v
Extract text
      |
      v
Normalize text
      |
      v
Chunk content
      |
      v
Generate embeddings
      |
      v
Store chunks + embeddings
```

## Important metadata

Each chunk should preserve:

```text
workspace_id
document_id
source_id
chunk_index
title
page if available
section if available
```

This allows answers to be traced to sources.

## Acceptance criteria

- [ ] Manual FAQ can be created
- [ ] Document can be ingested
- [ ] Chunks are workspace-isolated
- [ ] Similarity search works
- [ ] Source metadata returned
- [ ] Deleting document removes/invalidates chunks

---

# 19. Phase 10 — RAG Retrieval Service

## Goal

Create reliable retrieval before generating AI replies.

## Retrieval pipeline

```text
Customer question
      |
      v
Normalize query
      |
      v
Embedding
      |
      v
Vector search scoped to workspace
      |
      v
Top K chunks
      |
      v
Optional reranking / filtering
      |
      v
Context package
```

## Service interface

Conceptually:

```python
rag_service.retrieve(
    workspace_id=...,
    query=...,
    limit=...
)
```

Return structured results:

```json
{
  "query": "What is your return policy?",
  "matches": [
    {
      "document_id": "...",
      "chunk_id": "...",
      "score": 0.91,
      "content": "...",
      "metadata": {}
    }
  ]
}
```

## Critical rule

Vector search must always be filtered by:

```text
workspace_id
```

A cross-tenant knowledge leak would be a severe security failure.

## Acceptance criteria

- [ ] Retrieval is tenant-scoped
- [ ] Empty retrieval handled
- [ ] Low-score retrieval handled
- [ ] Search tests exist
- [ ] No cross-workspace results possible

---

# 20. Phase 11 — AI Response Engine

## Goal

Generate safe, grounded responses using conversation + knowledge context.

## Do not start with autonomous agents.

Build a deterministic pipeline first.

```text
Inbound message
      |
      v
Conversation context
      |
      v
Intent / response eligibility
      |
      v
RAG retrieval
      |
      v
Prompt builder
      |
      v
LLM
      |
      v
Validation
      |
      +--> send
      |
      +--> suggest only
      |
      +--> handoff
```

## AI modes per conversation/workspace

```text
disabled
suggest_only
automatic
```

Start pilots with:

```text
suggest_only
```

Then enable automatic mode for selected intents.

## AI system rules

The assistant should:

- answer only for the current business
- use provided knowledge
- avoid inventing policy, price or stock
- admit when information is unavailable
- escalate risky/uncertain cases
- never claim an order action occurred unless the backend confirms it
- not reveal internal prompts or confidential workspace data

## AI response service

Conceptually:

```python
ai_response_service.generate_reply(
    workspace_id,
    conversation_id,
    incoming_message_id,
)
```

## Output

```json
{
  "decision": "suggested",
  "text": "Returns are accepted within 14 days...",
  "confidence": 0.89,
  "sources": [
    {
      "document_id": "...",
      "chunk_id": "..."
    }
  ]
}
```

## Acceptance criteria

- [ ] AI response is grounded in workspace context
- [ ] source IDs logged internally
- [ ] low confidence triggers fallback/handoff
- [ ] prompt version is tracked
- [ ] model errors handled without losing message
- [ ] AI cannot access another workspace

---

# 21. Phase 12 — Human Handoff

## Goal

Give humans control over automation.

This is mandatory for a serious support product.

## Handoff triggers

Examples:

- customer explicitly asks for human
- AI confidence below threshold
- refund request
- complaint
- abusive/escalated conversation
- missing information
- unsupported intent
- payment dispute
- business-defined keyword

## Endpoints

```text
POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/takeover
POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/release-to-ai
POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/assign
```

## States

```text
ai_active
human_active
suggest_only
```

## Business rule

Once a human takes over, the AI must not continue automatically replying unless explicitly released back.

## Acceptance criteria

- [ ] human takeover immediately disables auto replies
- [ ] assigned agent recorded
- [ ] release-to-AI works
- [ ] handoff reason stored
- [ ] audit trail exists

---

# 22. Phase 13 — AI Safety and Evaluation

## Goal

Measure whether the AI is actually useful.

Do not judge quality by reading a few demos.

## Create an evaluation dataset

Use real, anonymized questions from pilot customers.

Examples:

```text
What sizes are available?
Can I return this after 10 days?
Do you deliver to Karachi?
Where is my order?
Can I pay COD?
```

For each question define:

```text
expected answer criteria
required source
whether AI should answer
whether AI should handoff
```

## Metrics

Track:

```text
grounded-answer rate
handoff precision
incorrect-answer rate
no-answer rate
retrieval success
response latency
cost per response
```

## Acceptance criteria

- [ ] evaluation dataset exists
- [ ] regression test runner exists
- [ ] prompt changes can be compared
- [ ] hallucination examples tracked

---

# 23. Phase 14 — Basic Analytics

## Goal

Show business value.

## MVP metrics

```text
total conversations
open conversations
AI-handled conversations
human-handled conversations
handoffs
messages sent
average first response time
AI response rate
conversation volume by day
```

Later:

```text
leads
orders
conversion rate
recovered carts
revenue attributed
```

## Endpoints

```text
GET /api/v1/workspaces/{workspace_id}/analytics/overview
GET /api/v1/workspaces/{workspace_id}/analytics/conversations
GET /api/v1/workspaces/{workspace_id}/analytics/ai
```

## Acceptance criteria

- [ ] dashboard metrics correct
- [ ] date range filtering works
- [ ] timezone respected
- [ ] analytics queries tested

---

# 24. Phase 15 — Refresh Tokens and Session Management

## Goal

Improve authentication for a real SaaS dashboard.

## Endpoints

```text
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
GET    /api/v1/account/sessions
DELETE /api/v1/account/sessions/{session_id}
DELETE /api/v1/account/sessions
```

## Recommended design

Use:

```text
short-lived access token
+
rotating refresh token
```

Store refresh token hashes, not raw tokens.

## Security requirements

- token rotation
- expiration
- revoke on logout
- revoke all sessions
- detect reused refresh token if implementing rotation families
- rate limit login/refresh

## Acceptance criteria

- [ ] refresh works
- [ ] logout invalidates session
- [ ] stolen old refresh token cannot be reused indefinitely
- [ ] session list exists

---

# 25. Phase 16 — Email Verification and Password Recovery

## Endpoints

```text
POST /api/v1/auth/resend-verification
POST /api/v1/auth/verify-email

POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
```

## Security rules

- generic response for unknown email
- token hashes stored
- tokens expire
- tokens are single-use
- reset invalidates relevant sessions where appropriate

## Acceptance criteria

- [ ] verification works
- [ ] reset works
- [ ] enumeration not exposed
- [ ] expiration tested

---

# 26. Phase 17 — Rate Limiting and Abuse Protection

## Goal

Protect expensive and sensitive endpoints.

Initial targets:

```text
login
forgot password
invitation creation
WhatsApp webhook abuse
AI generation
knowledge search
file upload
```

Possible later infrastructure:

```text
Redis
```

Do not introduce Redis until needed.

## Acceptance criteria

- [ ] login protected
- [ ] AI usage bounded
- [ ] rate-limit response documented
- [ ] tests cover limits

---

# 27. Phase 18 — Product Catalog

## Goal

Allow AI to answer product questions with structured data.

## products

```text
id
workspace_id
external_id
name
description
status
price
currency
metadata
created_at
updated_at
```

## variants

```text
id
workspace_id
product_id
external_id
sku
title
price
stock_quantity
attributes
created_at
updated_at
```

Attributes example:

```json
{
  "size": "M",
  "color": "Black"
}
```

## Endpoints

```text
POST   /api/v1/workspaces/{workspace_id}/products
GET    /api/v1/workspaces/{workspace_id}/products
GET    /api/v1/workspaces/{workspace_id}/products/{product_id}
PATCH  /api/v1/workspaces/{workspace_id}/products/{product_id}
DELETE /api/v1/workspaces/{workspace_id}/products/{product_id}
```

## Acceptance criteria

- [ ] products workspace-scoped
- [ ] variants supported
- [ ] structured product search works
- [ ] AI can use product lookup tool/service rather than hallucinating inventory

---

# 28. Phase 19 — Orders

## Goal

Support order status and confirmation workflows.

## orders

```text
id
workspace_id
contact_id
external_id
status
currency
subtotal
shipping_total
total
shipping_address
tracking_number
tracking_url
placed_at
created_at
updated_at
```

## Endpoints

```text
GET   /api/v1/workspaces/{workspace_id}/orders
GET   /api/v1/workspaces/{workspace_id}/orders/{order_id}
PATCH /api/v1/workspaces/{workspace_id}/orders/{order_id}
POST  /api/v1/workspaces/{workspace_id}/orders/{order_id}/confirm
```

## Important rule

AI must query structured order data for order status.

Do not put order status only into a vector knowledge base.

## Acceptance criteria

- [ ] order lookup by customer works
- [ ] AI can answer order-status questions
- [ ] incorrect customer cannot access another customer's order

---

# 29. Phase 20 — Shopify Integration

## Goal

Synchronize products, customers and orders.

Do this only after internal product/order models are stable.

## Integration responsibilities

```text
OAuth / installation
webhook handling
product synchronization
variant synchronization
order synchronization
customer mapping
uninstall cleanup
```

## Adapter structure

```text
app/integrations/ecommerce/base.py
app/integrations/ecommerce/shopify.py
```

Keep product services independent from Shopify-specific code.

## Acceptance criteria

- [ ] connection established
- [ ] initial sync
- [ ] webhook sync
- [ ] duplicate webhook handling
- [ ] disconnect handled

---

# 30. Phase 21 — WooCommerce Integration

Follow the same internal integration interface as Shopify.

Do not duplicate business logic.

```text
EcommerceProvider
        |
        +--> ShopifyProvider
        |
        +--> WooCommerceProvider
```

---

# 31. Phase 22 — Automation Engine

## Goal

Turn the platform from reactive chat into business workflow automation.

## Example automation

```text
WHEN
customer sends message

IF
intent == order_status

THEN
fetch order
generate answer
send reply
```

Another:

```text
WHEN
checkout abandoned

WAIT
2 hours

IF
order still not completed

THEN
send WhatsApp follow-up
```

## Core entities

### automations

```text
id
workspace_id
name
trigger_type
status
definition
created_at
updated_at
```

### automation_runs

```text
id
workspace_id
automation_id
status
started_at
completed_at
error
metadata
```

## Important

Do not build a visual workflow builder first.

Start with a small set of predefined automations.

Examples:

```text
FAQ auto-response
order status response
human handoff
follow-up after unanswered lead
abandoned cart follow-up
order confirmation
```

## Acceptance criteria

- [ ] predefined automation can run
- [ ] retry behavior defined
- [ ] run history available
- [ ] duplicate execution prevented where required

---

# 32. Phase 23 — Notifications

## Internal agent notifications

Examples:

```text
conversation assigned
AI requested handoff
customer waiting
integration failed
knowledge ingestion failed
```

## Endpoints

```text
GET   /api/v1/notifications
GET   /api/v1/notifications/unread-count
PATCH /api/v1/notifications/{notification_id}/read
POST  /api/v1/notifications/read-all
```

Later add email/push notification channels.

---

# 33. Phase 24 — Billing and Plans

Do not build billing before pilots prove value.

## Proposed plans

### Starter

Possible limits:

```text
1 WhatsApp number
2 team members
1,000 AI responses / month
basic knowledge base
basic analytics
```

### Growth

```text
more WhatsApp numbers
more users
higher AI usage
automations
e-commerce integration
advanced analytics
```

### Business

```text
high usage
multiple stores
API access
advanced roles
audit logs
priority support
```

Do not hard-code plan checks around the codebase.

Create centralized capability checks.

Example:

```python
subscription_service.require_feature(
    workspace_id,
    "automations",
)
```

## Endpoints

```text
GET  /api/v1/plans

GET  /api/v1/workspaces/{workspace_id}/subscription
POST /api/v1/workspaces/{workspace_id}/subscription/checkout
POST /api/v1/workspaces/{workspace_id}/subscription/cancel

POST /api/v1/webhooks/billing
```

## Acceptance criteria

- [ ] subscription state synced
- [ ] webhook idempotency implemented
- [ ] feature limits enforced centrally
- [ ] billing failure states handled

---

# 34. Phase 25 — Usage Metering

## Metrics

```text
AI responses
AI tokens
WhatsApp messages
active contacts
team members
knowledge storage
```

Create usage events at the service boundary.

Do not calculate billing-critical usage from unreliable logs.

## Acceptance criteria

- [ ] usage is workspace-scoped
- [ ] period totals accurate
- [ ] plan limits enforceable

---

# 35. Phase 26 — Audit Logs

Important for business accounts.

## Events

```text
workspace.created
workspace.updated

member.invited
member.joined
member.role_changed
member.removed

whatsapp.connected
whatsapp.disconnected

knowledge.document_uploaded
knowledge.document_deleted

conversation.assigned
conversation.closed
conversation.ai_disabled

subscription.changed

api_key.created
api_key.revoked
```

## Endpoint

```text
GET /api/v1/workspaces/{workspace_id}/audit-logs
```

Audit logs should be append-only from application perspective.

---

# 36. Phase 27 — API Keys

Later, allow customers to integrate with LeadPilot.

## Endpoints

```text
POST   /api/v1/workspaces/{workspace_id}/api-keys
GET    /api/v1/workspaces/{workspace_id}/api-keys
DELETE /api/v1/workspaces/{workspace_id}/api-keys/{key_id}
```

## Storage

```text
id
workspace_id
name
key_prefix
key_hash
last_used_at
expires_at
revoked_at
created_at
```

Return plaintext key only once.

---

# 37. Phase 28 — Background Jobs

Introduce a real job system only when needed.

Candidates:

```text
document ingestion
embedding generation
AI response generation
large e-commerce synchronization
analytics aggregation
scheduled automation
email sending
retrying failed external requests
```

Possible architecture later:

```text
FastAPI
  |
  +--> PostgreSQL
  |
  +--> Redis
         |
         +--> Worker
```

Choose the queue library when requirements are clear.

---

# 38. Phase 29 — Observability

## Logging

Use structured logging with identifiers:

```text
request_id
workspace_id
conversation_id
integration
operation
```

Avoid sensitive contents by default.

## Metrics

Track:

```text
HTTP latency
error rate
webhook failures
WhatsApp provider latency
LLM latency
LLM failures
embedding latency
queue depth
AI cost
AI responses
handoff rate
```

## Tracing

Add distributed tracing only if operational complexity requires it.

---

# 39. Phase 30 — Production Security

Before commercial launch:

- enforce HTTPS at deployment edge
- rotate secrets
- encrypt integration credentials
- configure backup policy
- test database restore
- configure rate limiting
- enforce strict CORS
- validate webhook signatures
- sanitize file uploads
- limit upload size
- validate MIME types
- scan risky file types where appropriate
- set token expiration policies
- secure billing webhooks
- ensure tenant isolation tests
- dependency vulnerability scanning
- production secret manager
- access logging policy
- privacy/data retention policy
- customer data deletion workflow

---

# 40. Suggested Project Structure

As the project grows:

```text
app/
├── main.py
│
├── api/
│   ├── router.py
│   ├── dependencies/
│   │   ├── auth.py
│   │   └── workspace.py
│   └── routes/
│       ├── health.py
│       ├── auth.py
│       ├── account.py
│       ├── workspaces.py
│       ├── memberships.py
│       ├── invitations.py
│       ├── contacts.py
│       ├── conversations.py
│       ├── knowledge.py
│       ├── analytics.py
│       ├── integrations.py
│       ├── webhooks.py
│       └── billing.py
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
│   ├── user.py
│   ├── workspace.py
│   ├── workspace_membership.py
│   ├── workspace_invitation.py
│   ├── contact.py
│   ├── conversation.py
│   ├── message.py
│   ├── whatsapp_account.py
│   ├── knowledge_source.py
│   ├── knowledge_document.py
│   ├── knowledge_chunk.py
│   ├── subscription.py
│   └── usage_record.py
│
├── schemas/
│   ├── auth.py
│   ├── account.py
│   ├── workspace.py
│   ├── membership.py
│   ├── invitation.py
│   ├── contact.py
│   ├── conversation.py
│   ├── message.py
│   ├── knowledge.py
│   ├── analytics.py
│   └── billing.py
│
├── repositories/
│   ├── user_repository.py
│   ├── workspace_repository.py
│   ├── membership_repository.py
│   ├── contact_repository.py
│   ├── conversation_repository.py
│   ├── message_repository.py
│   └── knowledge_repository.py
│
├── services/
│   ├── auth_service.py
│   ├── account_service.py
│   ├── workspace_service.py
│   ├── invitation_service.py
│   ├── contact_service.py
│   ├── conversation_service.py
│   ├── messaging_service.py
│   ├── knowledge_service.py
│   ├── rag_service.py
│   ├── ai_response_service.py
│   ├── analytics_service.py
│   └── subscription_service.py
│
├── integrations/
│   ├── messaging/
│   │   ├── base.py
│   │   └── whatsapp.py
│   ├── ai/
│   │   └── provider.py
│   └── ecommerce/
│       ├── base.py
│       ├── shopify.py
│       └── woocommerce.py
│
└── utils/

tests/
├── api/
├── services/
├── repositories/
├── integrations/
├── security/
└── conftest.py

alembic/
docs/
```

Do not create every file immediately.

Create each module only when its implementation phase starts.

---

# 41. API End State

A mature version may approximately expose:

```text
/api/v1

Health
├── GET /health
├── GET /health/live
└── GET /health/ready

Authentication
├── POST /auth/register
├── POST /auth/login
├── POST /auth/refresh
├── POST /auth/logout
├── POST /auth/forgot-password
├── POST /auth/reset-password
├── POST /auth/verify-email
└── POST /auth/resend-verification

Account
├── GET    /account
├── PATCH  /account
├── DELETE /account
├── POST   /account/change-password
├── GET    /account/sessions
└── DELETE /account/sessions/{session_id}

Workspaces
├── POST   /workspaces
├── GET    /workspaces
├── GET    /workspaces/{workspace_id}
├── PATCH  /workspaces/{workspace_id}
└── DELETE /workspaces/{workspace_id}

Members
├── GET    /workspaces/{workspace_id}/members
├── PATCH  /workspaces/{workspace_id}/members/{user_id}
└── DELETE /workspaces/{workspace_id}/members/{user_id}

Invitations
├── POST   /workspaces/{workspace_id}/invitations
├── GET    /workspaces/{workspace_id}/invitations
├── DELETE /workspaces/{workspace_id}/invitations/{invitation_id}
├── GET    /invitations/{token}
└── POST   /invitations/{token}/accept

Contacts
├── POST   /workspaces/{workspace_id}/contacts
├── GET    /workspaces/{workspace_id}/contacts
├── GET    /workspaces/{workspace_id}/contacts/{contact_id}
└── PATCH  /workspaces/{workspace_id}/contacts/{contact_id}

Conversations
├── GET  /workspaces/{workspace_id}/conversations
├── GET  /workspaces/{workspace_id}/conversations/{conversation_id}
├── POST /workspaces/{workspace_id}/conversations/{conversation_id}/assign
├── POST /workspaces/{workspace_id}/conversations/{conversation_id}/close
├── POST /workspaces/{workspace_id}/conversations/{conversation_id}/reopen
├── POST /workspaces/{workspace_id}/conversations/{conversation_id}/takeover
└── POST /workspaces/{workspace_id}/conversations/{conversation_id}/release-to-ai

Messages
├── GET  /workspaces/{workspace_id}/conversations/{conversation_id}/messages
└── POST /workspaces/{workspace_id}/conversations/{conversation_id}/messages

WhatsApp
├── POST   /workspaces/{workspace_id}/integrations/whatsapp/connect
├── GET    /workspaces/{workspace_id}/integrations/whatsapp
├── DELETE /workspaces/{workspace_id}/integrations/whatsapp
├── GET    /webhooks/whatsapp
└── POST   /webhooks/whatsapp

Knowledge
├── POST   /workspaces/{workspace_id}/knowledge/sources
├── GET    /workspaces/{workspace_id}/knowledge/sources
├── DELETE /workspaces/{workspace_id}/knowledge/sources/{source_id}
├── POST   /workspaces/{workspace_id}/knowledge/documents
├── GET    /workspaces/{workspace_id}/knowledge/documents
├── DELETE /workspaces/{workspace_id}/knowledge/documents/{document_id}
└── POST   /workspaces/{workspace_id}/knowledge/search

Analytics
├── GET /workspaces/{workspace_id}/analytics/overview
├── GET /workspaces/{workspace_id}/analytics/conversations
└── GET /workspaces/{workspace_id}/analytics/ai

Products
├── POST   /workspaces/{workspace_id}/products
├── GET    /workspaces/{workspace_id}/products
├── GET    /workspaces/{workspace_id}/products/{product_id}
├── PATCH  /workspaces/{workspace_id}/products/{product_id}
└── DELETE /workspaces/{workspace_id}/products/{product_id}

Orders
├── GET   /workspaces/{workspace_id}/orders
├── GET   /workspaces/{workspace_id}/orders/{order_id}
├── PATCH /workspaces/{workspace_id}/orders/{order_id}
└── POST  /workspaces/{workspace_id}/orders/{order_id}/confirm

Automations
├── POST   /workspaces/{workspace_id}/automations
├── GET    /workspaces/{workspace_id}/automations
├── PATCH  /workspaces/{workspace_id}/automations/{automation_id}
└── DELETE /workspaces/{workspace_id}/automations/{automation_id}

Notifications
├── GET   /notifications
├── GET   /notifications/unread-count
├── PATCH /notifications/{notification_id}/read
└── POST  /notifications/read-all

Billing
├── GET  /plans
├── GET  /workspaces/{workspace_id}/subscription
├── POST /workspaces/{workspace_id}/subscription/checkout
├── POST /workspaces/{workspace_id}/subscription/cancel
└── POST /webhooks/billing

Audit
└── GET /workspaces/{workspace_id}/audit-logs

API Keys
├── POST   /workspaces/{workspace_id}/api-keys
├── GET    /workspaces/{workspace_id}/api-keys
└── DELETE /workspaces/{workspace_id}/api-keys/{key_id}
```

---

# 42. Recommended Implementation Order

Follow this sequence.

```text
0.  Market validation
        |
1.  Fix existing user authorization
        |
2.  Workspaces
        |
3.  Memberships + RBAC
        |
4.  Invitations
        |
5.  Contacts
        |
6.  Conversations + messages
        |
7.  WhatsApp integration
        |
8.  Shared inbox backend
        |
9.  Knowledge base
        |
10. RAG retrieval
        |
11. AI response engine
        |
12. Human handoff
        |
13. AI evaluation
        |
14. Basic analytics
        |
15. Refresh tokens + sessions
        |
16. Email verification + password reset
        |
17. Rate limiting
        |
---------------- MVP / PILOT ----------------
        |
18. Product catalog
        |
19. Orders
        |
20. Shopify integration
        |
21. WooCommerce integration
        |
22. Automation engine
        |
23. Notifications
        |
24. Billing
        |
25. Usage metering
        |
26. Audit logs
        |
27. API keys
        |
28. Background job system
        |
29. Observability
        |
30. Production hardening
```

---

# 43. MVP Boundary

The first sellable pilot should contain only:

```text
Authentication
        +
Workspace
        +
Team roles
        +
Contacts
        +
WhatsApp connection
        +
Shared inbox
        +
Conversation history
        +
Knowledge base
        +
RAG retrieval
        +
AI suggested responses
        +
Optional automatic replies
        +
Human takeover
        +
Basic analytics
```

Do **not** block the MVP on:

```text
Shopify
WooCommerce
billing
visual automation builder
advanced reporting
API keys
mobile app
Instagram
Facebook Messenger
email
voice
advanced CRM
```

Those belong after pilot feedback.

---

# 44. Pilot Rollout Strategy

## Stage 1 — Internal testing

Use your own WhatsApp test business.

Validate:

- webhook reliability
- duplicate handling
- message persistence
- AI suggestions
- RAG quality
- handoff
- failure handling

## Stage 2 — One design partner

Connect one real business.

Initially configure:

```text
AI mode = suggest_only
```

Human reviews every suggestion.

Collect:

```text
customer question
AI suggestion
human final reply
retrieved sources
whether AI was correct
```

## Stage 3 — Three pilot customers

Enable automatic replies only for safe intents:

```text
shipping policy
return policy
COD availability
store timing
size guide
basic product FAQ
```

Keep human handoff for:

```text
refunds
complaints
payment problems
order changes
unknown questions
low confidence
```

## Stage 4 — Paid beta

Charge a small number of businesses.

Do not wait for the product to be perfect before testing willingness to pay.

---

# 45. Critical Product Metrics

Track these from the first pilot.

## Usage

```text
daily active businesses
conversations per workspace
messages per conversation
AI suggestions
AI auto replies
human replies
```

## Automation

```text
AI automation rate
handoff rate
AI acceptance rate
AI correction rate
```

## Quality

```text
incorrect AI answer rate
retrieval failure rate
low confidence rate
customer re-question rate
```

## Business value

```text
first response time
resolution time
leads handled
orders attributed
support hours saved
```

## Commercial

```text
trial -> paid conversion
monthly recurring revenue
customer acquisition cost
churn
expansion
gross margin
AI cost per workspace
```

---

# 46. AI Cost Control

AI features can destroy margins if left uncontrolled.

Implement:

- per-workspace usage counters
- maximum context size
- maximum retrieved chunks
- token budgets
- model selection by task
- caching where safe
- no AI call when deterministic rules can answer
- plan-based quotas
- logging of token usage and latency

Example:

```text
simple FAQ
    -> cheaper model

complex question
    -> stronger model

order status
    -> no reasoning required
    -> structured database lookup
```

Do not use the most expensive model for every message.

---

# 47. Data Isolation Checklist

Every tenant-owned table should contain:

```text
workspace_id
```

Every repository query for tenant data must either:

```text
filter by workspace_id
```

or receive a parent object that has already been verified.

Test:

- Workspace A cannot access Workspace B contact
- Workspace A cannot access Workspace B conversation
- Workspace A cannot retrieve Workspace B knowledge
- Workspace A cannot send through Workspace B WhatsApp account
- Workspace A cannot access Workspace B orders
- Workspace A cannot view Workspace B analytics

Tenant isolation tests are mandatory.

---

# 48. Error Handling

Continue using centralized application exceptions.

Potential new errors:

```text
WorkspaceNotFoundError
WorkspaceAccessDeniedError
InsufficientWorkspaceRoleError

InvitationNotFoundError
InvitationExpiredError

ContactNotFoundError
ConversationNotFoundError
ConversationClosedError

WhatsAppNotConnectedError
MessagingProviderError
InvalidWebhookError

KnowledgeDocumentNotFoundError
KnowledgeProcessingError

AIResponseUnavailableError
AIHandoffRequiredError

SubscriptionRequiredError
PlanLimitExceededError
```

Services should raise domain/application errors.

HTTP translation remains centralized.

---

# 49. Testing Strategy

Each feature should include:

## Unit tests

Business logic:

```text
workspace service
membership rules
invitation validation
conversation state transitions
handoff decisions
RAG filtering
AI eligibility
plan limit checks
```

## Repository tests

Database behavior:

```text
workspace isolation
unique constraints
pagination
message ordering
document chunk retrieval
```

## Integration tests

External adapters:

```text
WhatsApp payload parsing
webhook verification
LLM adapter
embedding adapter
Shopify adapter
```

Mock external HTTP calls.

## API tests

Full flow:

```text
register
login
create workspace
invite member
connect WhatsApp
receive webhook
create conversation
AI suggestion
agent reply
handoff
close conversation
```

## Security tests

```text
cross-tenant access
role escalation
forged webhook
expired token
revoked session
invalid invitation
```

---

# 50. CI Expectations

Every pull request should eventually run:

```text
dependency install
        |
        v
ruff check
        |
        v
ruff format --check
        |
        v
mypy
        |
        v
migration check / upgrade
        |
        v
pytest
```

Later:

```text
security scan
integration contract tests
AI evaluation suite
Docker build
```

---

# 51. Definition of Done for Each Phase

A phase is not complete because the endpoint returns 200.

Each phase should include:

- [ ] database model
- [ ] migration
- [ ] schemas
- [ ] repository
- [ ] service
- [ ] route
- [ ] dependency / authorization where required
- [ ] centralized errors
- [ ] unit tests
- [ ] repository tests
- [ ] API tests
- [ ] documentation
- [ ] lint passes
- [ ] type checking passes
- [ ] migrations apply on clean database
- [ ] Docker environment still starts

---

# 52. What Not to Build Yet

Avoid these early:

```text
microservices
Kubernetes
Kafka
event sourcing
CQRS
custom workflow language
custom vector database
custom authentication server
mobile apps
multiple messaging channels
advanced CRM
complex dynamic RBAC
full customer data platform
voice AI
autonomous multi-agent system
```

They create engineering work without proving customer value.

---

# 53. Immediate Next Development Task

The next implementation phase should be:

# **Workspaces + Memberships + Authorization**

Before WhatsApp.

Before RAG.

Before AI.

Why:

Every future resource must belong to a business.

If multi-tenancy is designed incorrectly now, every later feature becomes harder to fix.

Implement first:

```text
Workspace model
        |
        v
WorkspaceMembership model
        |
        v
Alembic migration
        |
        v
Workspace schemas
        |
        v
Workspace repository
        |
        v
Membership repository
        |
        v
Workspace service
        |
        v
Workspace authorization dependency
        |
        v
Workspace endpoints
        |
        v
Cross-tenant tests
```

First endpoints:

```text
POST   /api/v1/workspaces
GET    /api/v1/workspaces
GET    /api/v1/workspaces/{workspace_id}
PATCH  /api/v1/workspaces/{workspace_id}
DELETE /api/v1/workspaces/{workspace_id}
```

Then:

```text
GET    /api/v1/workspaces/{workspace_id}/members
PATCH  /api/v1/workspaces/{workspace_id}/members/{user_id}
DELETE /api/v1/workspaces/{workspace_id}/members/{user_id}
```

Only after this foundation is correct should the project move to:

```text
Contacts
    ->
Conversations
    ->
WhatsApp
    ->
Knowledge Base
    ->
RAG
    ->
AI
```

---

# 54. Final Product Roadmap

```text
FASTAPI STARTER
      ✅
       |
       v
SAAS FOUNDATION
Workspaces
Memberships
RBAC
Invitations
       |
       v
CUSTOMER COMMUNICATION CORE
Contacts
Conversations
Messages
WhatsApp
Shared Inbox
       |
       v
AI KNOWLEDGE LAYER
Knowledge Sources
Documents
Chunking
Embeddings
Vector Search
RAG
       |
       v
AI SUPPORT LAYER
Suggested Replies
Automatic Replies
Confidence
Human Handoff
Evaluation
       |
       v
SELLABLE MVP
Pilot Customers
Analytics
Security
Sessions
Rate Limits
       |
       v
COMMERCE LAYER
Products
Orders
Shopify
WooCommerce
       |
       v
AUTOMATION LAYER
Lead Follow-up
Order Confirmation
Abandoned Cart
Notifications
       |
       v
MONETIZATION
Plans
Subscriptions
Usage Metering
Billing
       |
       v
B2B MATURITY
Audit Logs
API Keys
Advanced Analytics
Observability
Production Hardening
```

---

# 55. Success Condition

The goal is not:

> "Finish every feature in this document."

The goal is:

> "Reach the smallest version that real businesses use and pay for, then let customer behavior determine what is built next."

A successful first version is one where a real business can:

1. create an account
2. create a workspace
3. invite a team member
4. connect WhatsApp
5. receive customer messages
6. see them in an inbox
7. upload its policies / FAQs
8. receive AI-generated suggested replies
9. allow safe questions to be answered automatically
10. take over difficult conversations manually
11. see how many conversations the AI handled
12. decide that the product saves enough time or captures enough sales to justify paying for it

That is the commercial milestone to optimize for.