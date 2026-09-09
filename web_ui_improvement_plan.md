# Baton UI/UX Improvement Plan for Claude

You are a senior product designer and senior frontend engineer specializing in:

* Next.js
* TypeScript
* Tailwind CSS
* shadcn/ui
* Radix UI
* TanStack Query
* responsive B2B SaaS applications
* accessibility
* information-dense operational interfaces

You are improving the existing **Baton** frontend.

Baton has two separate surfaces:

1. Customer / tenant application
2. Internal staff / platform console

The backend API, authorization rules, entitlement rules, routes, and business behavior already exist.

Your responsibility is to improve the **visual design, UX, consistency, responsiveness, accessibility, and frontend presentation**.

Do not invent backend behavior.

Do not change API semantics.

Do not add fake features.

Do not rewrite working architecture unless necessary.

The target aesthetic is:

* modern
* professional
* calm
* premium
* operational
* information-dense
* trustworthy
* restrained
* polished

Avoid:

* excessive gradients
* glassmorphism
* giant cards
* excessive rounded corners
* oversized headings
* huge whitespace
* decorative dashboards
* rainbow status badges
* unnecessary animations
* generic shadcn-demo appearance

The interface should feel like software somebody can comfortably use for several hours every day.

---

# PHASE 1 — Audit the Existing UI and Establish the Design System

## Goal

Before touching individual product screens, inspect the existing frontend and establish a consistent visual foundation.

Do not begin randomly redesigning individual pages.

## First inspect

Review the current frontend structure and identify:

* existing Tailwind configuration
* global CSS
* CSS variables
* shadcn configuration
* typography
* layout components
* button variants
* inputs
* forms
* cards
* tables
* badges
* dialogs
* dropdowns
* navigation
* sidebar
* empty states
* loading states
* error states
* spacing inconsistencies
* radius inconsistencies
* duplicated UI patterns
* responsive issues
* dark mode problems
* accessibility problems

Document the main inconsistencies before changing them.

## Design tokens

Create or refine semantic tokens for:

* background
* foreground
* surface
* elevated surface
* muted background
* muted foreground
* border
* subtle border
* input
* primary
* primary foreground
* secondary
* accent
* destructive
* destructive foreground
* success
* warning
* informational
* sidebar
* sidebar foreground
* sidebar hover
* sidebar active
* focus ring

They must work correctly in both light and dark mode.

Do not scatter arbitrary Tailwind colors throughout the application.

Prefer semantic variables.

## Standardize

Establish consistent rules for:

* border radius
* shadows
* spacing
* section spacing
* page padding
* typography scale
* icon sizes
* button heights
* input heights
* table row heights
* sidebar widths
* page widths
* transition durations

## Typography

Create clear hierarchy for:

* page title
* page description
* section heading
* subsection heading
* body
* label
* metadata
* caption
* table text

Keep page titles compact.

This is an operational SaaS application, not a marketing website.

Use tabular numerals where appropriate for:

* money
* usage
* analytics
* counts
* numeric tables

## Shared primitives

Improve or create reusable primitives for:

* PageHeader
* SectionHeader
* EmptyState
* LoadingState
* StatusBadge
* InlineAlert
* ErrorState
* ConfirmDialog
* DestructiveConfirmDialog
* CopyButton
* DataTable shell
* pagination
* filters
* skeletons

Do not over-abstract.

Only extract patterns that genuinely repeat.

## Constraints

Do not:

* change API calls
* change routes
* change authentication
* change authorization
* change business logic
* introduce another component library
* add large unnecessary dependencies

## Completion criteria

Phase 1 is complete when:

* global design tokens are consistent
* typography has clear hierarchy
* dark mode works
* primitive components are coherent
* spacing/radii/buttons/forms feel related
* default shadcn styling no longer dominates the visual identity

After completing this phase, summarize:

1. design tokens changed
2. primitives changed
3. inconsistencies fixed
4. files changed
5. remaining problems for later phases

Do not proceed to Phase 2 automatically.

---

# PHASE 2 — Application Shell, Sidebar, Navigation and Page Structure

## Goal

Improve the overall shell of the customer-facing Baton application.

Do not redesign product-specific screens yet.

## Tenant application shell

Create a professional SaaS layout.

Desktop should generally provide:

* persistent sidebar
* workspace switcher
* grouped primary navigation
* utility navigation
* user/account control
* main content region
* optional page-specific top controls

Navigation should support the major tenant areas:

* Inbox
* Contacts
* Knowledge
* Products
* Orders
* Team
* Automations
* Integrations
* Analytics
* Audit Logs
* API Keys
* Billing
* Usage
* Workspace Settings

Do not invent routes that do not exist.

## Sidebar

Improve:

* active states
* hover states
* icon alignment
* section grouping
* spacing
* typography
* collapsed states if already supported
* tooltip behavior when collapsed
* user/account area
* workspace switcher hierarchy

Keep the sidebar visually restrained.

Avoid excessive borders and background blocks.

## Content layout

Do not force every page into the same max-width.

Create layout variants such as:

### Standard

Good for:

* settings
* billing
* team
* integrations

### Wide

Good for:

* tables
* products
* orders
* audit logs

### Full

Good for:

* Inbox
* analytics
* operational admin views

## Page header

Create/refine a reusable PageHeader supporting:

* title
* description
* breadcrumbs if appropriate
* status badge
* primary action
* secondary action
* tabs
* contextual actions

Avoid repeating custom header markup across pages.

## Responsive behavior

Desktop:

* persistent sidebar

Tablet:

* narrower sidebar or collapsible shell

Mobile:

* sheet/drawer navigation
* readable content padding
* no horizontally crushed navigation

## Important architecture constraint

The tenant application and staff console MUST NOT share navigation.

Do not introduce any link from the tenant application into the internal staff console.

## Completion criteria

Phase 2 is complete when:

* navigation feels deliberate
* workspace switching is visually clear
* current section is obvious
* page widths match content needs
* page headers are standardized
* mobile navigation is usable
* tenant/admin separation remains intact

Do not proceed automatically.

---

# PHASE 3 — Authentication, Account, Workspace Settings and Forms

## Goal

Polish all foundational account/auth/settings experiences.

Prioritize clarity and trust over decoration.

## Improve

Authentication screens:

* Sign in
* Register
* Verify email
* Resend verification
* Forgot password
* Reset password

Account screens:

* Profile
* Email
* Password
* Sessions
* Notifications

Workspace screens:

* Workspace list
* Workspace creation
* Workspace settings
* Close workspace

## Authentication layout

Create a polished authentication experience.

Avoid giant marketing panels unless one already meaningfully exists.

Focus on:

* strong form hierarchy
* compact composition
* readable errors
* accessible fields
* obvious submit action
* useful secondary links

## Forms

Standardize:

* labels
* help text
* placeholder treatment
* inline validation
* disabled state
* focus state
* required indicators
* field grouping
* section spacing
* form action areas

Do not wrap every field group in its own heavy card.

## Settings layouts

Prefer clear section structure such as:

Title
Description

Setting title        Control
Explanation

rather than dozens of unrelated cards.

Use dividers where appropriate.

## Sessions

Make device/session rows easy to scan.

Clearly identify:

* current session
* device/browser
* approximate activity
* revoke action

Revoking the current session should visually communicate sign-out.

## Destructive actions

Create consistent danger-zone patterns for:

* deleting account
* closing workspace
* revoking sessions
* password-related security actions

Do not make destructive buttons visually equivalent to ordinary actions.

Typed confirmation screens should clearly show:

* what will happen
* which subject is affected
* what must be typed
* destructive action

## Error handling

Preserve Baton API semantics.

Use inline errors for validation.

Do not expose raw JSON.

Do not branch UI copy from arbitrary backend prose where stable error codes already exist.

## Completion criteria

* auth feels production-ready
* settings pages have consistent form rhythm
* destructive actions are difficult to trigger accidentally
* session management is easy to understand
* validation errors appear in the correct fields
* mobile layouts remain usable

Do not proceed automatically.

---

# PHASE 4 — Inbox, Conversations and Contacts

## Goal

This is the most important visual phase.

The Inbox is Baton's core product.

Give this phase the highest UI quality bar.

## Overall layout

Create a professional support/inbox experience.

Where screen width permits, use three major regions:

1. conversation list
2. conversation thread
3. contact/customer context panel

Do not make it look like a consumer chat application.

It should feel like professional support software.

## Conversation list

Improve:

* selected state
* hover state
* unread state
* customer identity
* message preview
* timestamp
* assignment
* conversation status
* AI/manual status where appropriate

Rows should be compact but readable.

Do not use huge cards.

## Filters

Support existing filters such as:

* status
* assignee
* unread

Make them compact and easy to scan.

Avoid wasting half the screen with filter controls.

## Conversation thread

Differentiate clearly between:

* customer messages
* human agent messages
* assistant suggestions
* system events

AI suggestions MUST look like drafts/suggestions rather than sent messages.

System/event messages should not visually compete with actual conversation messages.

Use restrained message styling.

Avoid oversized colorful bubbles.

## Composer

Improve:

* focus
* send affordance
* disabled/read-only states
* loading/sending state
* keyboard usability
* action grouping

Sending is not optimistic.

Do not make it visually appear sent before the API confirms it.

## Read-only/viewer mode

When the user cannot write:

* do not leave a useless dead composer
* preserve a readable conversation experience

## Closed conversations

When closed:

* make closed state obvious
* provide reopen where permitted
* remove inappropriate actions

## Suspended workspace

When `workspace_suspended` occurs:

Treat it as an application mode.

Show a persistent banner.

Disable mutation controls.

Do not show a repeated error toast every time.

## Contact panel

Structure:

* identity
* contact information
* customer metadata
* useful history/context
* conversation relationships

Make it collapsible where useful.

## Contacts screens

Polish:

* contact list
* search
* contact detail
* empty states
* metadata
* related conversations

## Responsive behavior

Large:
conversation list + thread + context

Medium:
conversation list + thread, context collapsible

Small:
single-pane navigation between list/thread/details

Do not simply compress three columns into mobile width.

## Completion criteria

* Inbox feels like the flagship product
* unread/selected/status states are immediately understandable
* AI suggestions cannot be mistaken for sent replies
* closed/read-only/suspended states are clear
* mobile conversation navigation works
* contact information is easy to scan

Do not proceed automatically.

---

# PHASE 5 — Team, Knowledge, Products and Orders

## Goal

Polish Baton's major operational CRUD/data-management areas using a consistent data-heavy design language.

## Shared table system

Create/refine a reusable operational table experience.

Support:

* compact row density
* clear headers
* column alignment
* row hover
* contextual actions
* pagination
* filters
* search
* empty states
* loading skeletons
* responsive behavior

Do not make every row a card on desktop.

Do not turn every value into a badge.

Badges are for actual states.

---

## Team

Improve:

* member list
* role display
* invitation list
* invitation creation
* role changes
* remove member
* leave workspace

Role differences should be understandable.

Do not represent role hierarchy inaccurately.

Owner/admin/agent/viewer should remain faithful to actual semantics.

Invitation links returned once should receive a polished one-time-copy experience.

Expired invitations must be visually distinct from missing invitations.

---

## Knowledge

Improve:

* source list
* document list
* source filtering
* upload
* FAQ creation
* document detail
* search/retrieval results

Make source/document relationships obvious.

Display useful metadata such as:

* source
* type
* ingestion state
* timestamps
* document origin

Search results should make it clear which document each retrieved passage came from.

Upload experience should include:

* drag/drop where appropriate
* file information
* progress
* success/error state

Differentiate unsupported file type from unreadable file.

---

## Products

Design products as operational records, not storefront cards.

Emphasize:

* name
* SKU
* origin
* price
* external identifier
* editability/state

Products with missing:

* image
* SKU
* description

must still render cleanly.

External/storefront-synced products should have their origin clearly indicated.

---

## Orders

Prioritize:

* order ID
* customer
* status
* total
* date
* actionability

Order state should be extremely easy to scan.

Confirm actions should communicate state changes clearly.

If another user has already confirmed the order, update/refetch rather than showing a dramatic generic error.

## Completion criteria

* tables across these sections look related
* operational density is good
* empty states are purposeful
* role/document/product/order states are easy to understand
* mobile behavior is deliberate

Do not proceed automatically.

---

# PHASE 6 — Billing, Plans, Usage and Upgrade States

## Goal

Create a polished and trustworthy billing/entitlement experience.

This phase also establishes the shared 402 upgrade UI used elsewhere.

## Pricing

Improve the public pricing page.

Use:

* clean plan comparison
* strong current-plan state
* readable feature/limit comparisons
* restrained CTAs

Avoid aggressive marketing-page styling.

`null` limits must render as:

Unlimited

not blank.

## Current subscription

Clearly differentiate:

* current entitled plan
* paid subscription plan
* active
* past_due
* cancellation scheduled
* cancelled/stopped

Do not incorrectly disable features because a subscription is `past_due`.

A past-due subscription should appear as a warning.

Not a feature-loss state.

## Usage

Create readable usage components showing:

* resource
* current usage
* limit
* percentage where meaningful
* unlimited state
* approaching-limit state

Avoid excessive progress bars if a number communicates the value better.

## 402 plan limitations

Create a reusable UpgradePrompt.

It should communicate:

* what capability is unavailable
* why
* current plan/limit where available
* upgrade/billing action

A 402 is NOT a 403.

Never visually or verbally present plan limitations as role/permission failures.

## Checkout

Make checkout transition states clear.

Do not pretend checkout completion immediately changed the plan.

The frontend waits for actual subscription state.

## Cancellation

Clearly distinguish:

* cancellation scheduled
* subscription already ended

Explain period-end behavior.

## Billing provider errors

A provider error should communicate temporary billing-provider failure and allow retry where appropriate.

Do not blame the customer.

## Completion criteria

* pricing is clear
* current entitlement is obvious
* usage is easy to understand
* past_due is a warning without feature removal
* 402 states look consistent everywhere
* cancellation language is accurate

Do not proceed automatically.

---

# PHASE 7 — Automations, Integrations, Analytics, Audit Logs and API Keys

## Goal

Polish the final major tenant application areas.

---

## Automations

Improve:

* automation list
* create form
* settings
* enabled/disabled status
* run history
* empty run history
* validation errors

Automation status should be visible without using excessive colored badges.

Keep settings forms structured.

---

## Integrations

Improve integration cards for:

* WhatsApp
* storefront/ecommerce integrations

Cards should communicate:

* provider
* connected/disconnected
* relevant metadata
* sync state
* available actions

Do not use giant logos.

Connected state should be obvious.

Disconnect should communicate consequences.

A downgraded customer must still be able to:

* view
* disable
* disconnect

existing integrations where the backend permits it.

Do not hide controls just because creation is plan-gated.

---

## Analytics

Avoid generic dashboard-template design.

Use hierarchy.

For example:

Primary metrics

Secondary metrics

Charts

Supporting tables/details

Do not make every metric an identical oversized card.

Charts should have:

* subtle grid
* readable labels
* consistent tooltips
* dark mode support
* useful empty states

Do not recompute backend analytics client-side.

---

## Audit logs

Design for dense scanning.

Prioritize:

* timestamp
* actor
* action
* subject/resource
* context
* filters

Avoid unnecessarily tall rows.

Audit logs should feel like an operational tool.

---

## API keys

Improve:

* key list
* create action
* revoke action
* current key state
* one-time reveal

The one-time reveal deserves special attention.

The user must understand:

“This key cannot be shown again.”

Make copying easy.

Prevent accidental dismissal if existing behavior supports that requirement.

## Completion criteria

* integrations look cohesive
* automation configuration is understandable
* analytics has clear hierarchy
* audit logs are dense and usable
* API key reveal feels secure and intentional

Do not proceed automatically.

---

# PHASE 8 — Admin Console Foundation and Read-Only Operational Views

## Goal

Improve the internal platform console.

This is NOT simply the tenant UI with different navigation.

The console should feel more operational, dense, and serious.

## Architecture constraint

The admin console has:

* its own layout
* its own navigation
* its own authentication/session behavior

Do not share tenant navigation.

Primitive components may be shared.

## Console shell

Improve:

* admin sidebar
* top context
* search
* workspace navigation
* user navigation
* audit navigation
* operational density

Give the console a subtly different visual identity while remaining part of the Baton design system.

Possible differences:

* slightly denser layouts
* stronger metadata
* clearer operational statuses
* more restrained decorative spacing
* stronger warning treatments

Do not use an entirely different design language.

## Workspace search/detail

Optimize for investigation.

Workspace detail may show:

* status
* plan
* counts
* erasure date
* members
* subscription
* usage
* integrations
* audit history

Use hierarchy rather than placing everything in identical cards.

## User search/detail

Prioritize:

* identity
* account status
* workspace relationships
* relevant operational metadata

## Admin audit

Admin reads are operationally significant.

Do not introduce:

* automatic polling
* hover prefetching
* speculative loading

Do not issue requests the staff member did not intentionally trigger.

## Admin errors

Create dedicated UI for:

* admin_session_expired
* address_not_allowed
* missing row / 404

Do not reuse incorrect tenant wording.

## Completion criteria

* console clearly feels different from tenant workspace
* staff can scan workspace/user information rapidly
* no speculative reads were introduced
* operational errors have dedicated treatments

Do not proceed automatically.

---

# PHASE 9 — Support Access, Lifecycle Operations, Billing Operations and Approvals

## Goal

Polish the highest-risk internal operations.

UI hierarchy is especially important here.

---

## Support access

When support access is active, show persistent context.

The staff member should always see:

* workspace
* support-access state
* remaining duration

Make it impossible to casually forget that customer data is being viewed under temporary access.

`support_access_required` should guide staff toward the request flow rather than appearing as a generic failure.

---

## Lifecycle operations

Improve interfaces for:

* suspend
* unsuspend
* cancel
* restore
* erase
* reschedule erasure
* activate user
* deactivate user
* verify email
* revoke sessions
* staff access changes

Separate:

* normal
* sensitive
* destructive

actions.

Do not put every action in one row of equally prominent buttons.

Use secondary menus for lower-frequency operations where appropriate.

## Erasure

Erasure is one of the most dangerous actions.

Use typed confirmation.

Clearly show:

* affected workspace
* irreversible consequence
* required slug
* confirmation field
* destructive CTA

Do not weaken confirmation rules.

## Approval required

`approval_required` is not a generic error.

Render it as an operational state.

Show:

* what action is awaiting approval
* why
* request status
* appropriate next information

---

## Platform billing

Improve:

* subscription ledger
* past_due filter
* billing event list
* replay
* plan overrides

Make `past_due` a first-class operational state.

It should be easy to reach and highly scannable.

Plan overrides should show:

* active/expired
* expiry
* source
* whether it currently applies

A forever/no-expiry override should look like a warning requiring attention, not an error.

---

## Jobs and webhook failures

Improve:

* job list
* job detail
* failure reason
* retry
* cancellation
* webhook failure list

Failure reason should appear before retry controls.

Do not make retry the most prominent information.

---

## Approvals

Design approvals for fast but careful review.

Show:

* requested action
* requester
* subject
* timestamp
* justification/context
* current status
* approve action

High-risk approval actions must not feel casual.

## Completion criteria

* destructive operations have strong hierarchy
* support access is impossible to overlook
* approval states are understandable
* billing operations are scannable
* failures show context before actions

Do not proceed automatically.

---

# PHASE 10 — Responsive, Accessibility, Dark Mode and Final Polish

## Goal

Perform the final quality pass across the entire frontend.

Do not introduce major product redesigns during this phase.

This phase fixes inconsistencies.

## Responsive audit

Check approximately:

* 375px mobile
* 768px tablet
* 1024px laptop
* 1440px desktop
* wider desktop

Review every major layout.

### Inbox

3 columns
→ 2 columns
→ single-pane navigation

### Tables

Desktop:
full operational table

Tablet:
hide lower-priority columns

Mobile:
responsive row/card representation only where genuinely necessary

Do not blindly enable horizontal scrolling everywhere.

### Settings

Desktop:
structured multi-column where useful

Mobile:
single column

### Admin

Large:
summary + metadata + operational content

Small:
stack sections deliberately

---

## Dark mode

Audit:

* backgrounds
* elevated surfaces
* borders
* inputs
* selected rows
* hover states
* charts
* skeletons
* warnings
* errors
* success states
* dialogs
* dropdowns
* sidebar
* conversation messages

Dark mode must feel intentionally designed.

Do not merely invert colors.

---

## Accessibility

Audit:

* keyboard navigation
* focus order
* visible focus
* form labels
* icon button labels
* dialog focus trap
* headings
* semantic tables
* status communication
* color contrast
* touch targets
* screen-reader copy
* dropdown/menu keyboard support

Never communicate status using color alone.

---

## Loading states

Replace crude loading states with layout-appropriate skeletons.

Create skeletons for:

* conversation rows
* messages
* contact panel
* tables
* dashboard metrics
* settings
* admin details

Avoid unnecessary global spinners.

---

## Empty states

Review all major empty surfaces:

* conversations
* contacts
* team invitations
* knowledge documents
* products
* orders
* automations
* integrations
* analytics
* audit logs
* API keys
* jobs
* alerts

Each should answer:

1. What is this area?
2. Why is it empty?
3. What should I do next, if anything?

Do not use giant illustrations.

---

## Micro-interactions

Use restrained transitions.

Generally:

100–200ms

Improve:

* hover
* selected state
* button feedback
* menus
* copy-success
* disclosures
* dialog transitions

Avoid flashy page entrance animations.

---

## Final consistency audit

Inspect the entire application for:

* inconsistent spacing
* inconsistent border radius
* random colors
* arbitrary font sizes
* mismatched icons
* duplicated components
* heavy card overuse
* inconsistent empty states
* inconsistent error states
* inconsistent status badges
* inconsistent action placement
* responsive overflow
* poor dark mode
* accessibility regressions

Fix these before considering the redesign finished.

---

# FINAL RULES FOR EVERY PHASE

Throughout all phases:

## Preserve backend authority

Do not change:

* API behavior
* endpoint semantics
* authorization
* roles
* subscription behavior
* entitlement logic
* plan gating
* lifecycle behavior

When backend behavior and visual convenience conflict, backend behavior wins.

## Preserve architecture

Continue using:

* Next.js
* TypeScript
* Tailwind
* shadcn/ui
* Radix
* TanStack Query where appropriate
* Server Components by default

Do not convert the application into a client-heavy SPA.

## Authentication

Never expose access or refresh tokens to browser JavaScript.

Do not modify the existing httpOnly-cookie/proxy architecture merely for UI convenience.

## Error semantics

Preserve distinctions between:

* 402 plan limitation
* 403 permission failure
* workspace suspension
* admin session expiry
* support access requirement
* approval requirement
* lifecycle conflict
* validation errors

Do not replace all of these with generic toast notifications.

## Cards

Do not put everything inside cards.

Use:

* whitespace
* typography
* borders
* dividers
* surfaces

to create hierarchy.

Cards should exist because content needs containment, not because shadcn provides a Card component.

## Status badges

Use badges only for real states.

Do not turn:

* names
* ordinary values
* dates
* IDs
* prices

into pills.

## UI quality test

Before finishing any phase, ask:

* Can the user identify the primary task in two seconds?
* Can they scan the page quickly?
* Is the primary action obvious?
* Are dangerous actions separated?
* Is anything inside a card unnecessarily?
* Is spacing excessive?
* Is information density appropriate?
* Are states clear without relying only on color?
* Does dark mode look deliberate?
* Does mobile work?
* Does this look custom-designed rather than copied from default shadcn examples?

---

# REPORT FORMAT AFTER EACH PHASE

At the end of each phase, provide:

## Completed

Briefly explain what was improved.

## Components

List reusable components created or refactored.

## Files

List important files changed.

## UX improvements

Explain the meaningful user-facing improvements.

## Responsive/accessibility

Mention responsive or accessibility changes.

## Remaining issues

List anything intentionally left for a later phase.

## Backend limitations

If the backend prevents an ideal UX, state the limitation.

Do not invent a frontend workaround that changes backend semantics.

Most importantly:

**Implement the changes in the existing codebase. Do not merely describe what should be changed.**
