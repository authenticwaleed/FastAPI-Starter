# The Baton design system

What the client is built from, and what to reach for instead of writing it
again. Established in phase 1 of `web_ui_improvement_plan.md`; every phase
after it builds on this rather than beside it.

The target: modern, professional, calm, operational, information-dense.
Software somebody has open for eight hours. Not a marketing site.

---

## What was wrong before

The audit that this phase came out of, kept because most of it explains why
the rules below are the shape they are.

| | |
|---|---|
| **Dark mode was unreachable** | A full `.dark` palette existed and nothing ever put the class on the page. No toggle, no cookie, no media query — the second half of every colour decision was dead code. |
| **Page titles were written 32 times** | `<h1 className="text-2xl font-semibold tracking-tight">`, by hand, in every screen. Some had a description, some had `mt-1` on it and some did not, and three had a back link glued on with `mt-2`. 24px is also a marketing heading. |
| **Section headings, 59 times** | `<h2 className="text-sm font-medium">`. Agreed on the size; disagreed on the gap under it, whether a description followed, and how a control got onto the right-hand side. |
| **Empty states, 37 times** | Some spelling of `rounded-md border border-dashed px-4 py-8 text-center text-sm`. Four different paddings. Several said only "None yet." |
| **Pagination, 9 times** | Eight by hand plus the console's own component. Two said "Previous/Next", two said "Newer/Older", one printed no total. |
| **`tab()`, 4 times** | A private helper in four files returning one of two class strings. The *only* signal for the active filter was an underline, on screens where every link is underlined. |
| **Badges chose their own colours** | 79 of them, most picking a variant in a ternary written on the spot. `past_due` — a bill to chase — came out in the same red as `suspended`, which is an account somebody switched off. |
| **No loading state anywhere** | No `loading.tsx`, no `Suspense`, no spinner. Every screen awaits the API server-side, so a click did nothing visible until the next page arrived. |
| **No surface hierarchy** | `--background` and `--card` were both `oklch(1 0 0)`. A card was visible only by its border, which is how a design system ends up drawing borders around everything. |
| **Radius was multiplied off one number** | `--radius: 0.625rem`, times 2.6, gave a 26px badge — the roundest object on an otherwise square screen. |
| **Focus was grey at 50%** | `--ring` was a mid grey. A grey ring on a grey border is a focus state you have to look for, which is the one state that must be findable without looking. 83 plain links had no focus style at all. |
| **Two arbitrary micro-sizes** | `text-[10px]` and `text-[11px]`, both meaning "denser than xs", in nine files. |
| **Twenty-two files styled `<select>` by hand** | Three heights (`h-7`, `h-8`, `h-9`), a stray `shadow-xs` on some, and `bg-background` on all — which, once the page stopped being pure white, made every one of them read as a hole rather than a control. |
| **Field borders at 1.35:1** | WCAG asks 3:1 of a control's boundary. `--input` was a line you could only see because you already knew a field was there. |
| **`<progress>` was unstyled** | Chrome renders a green fill on a dark grey track; Firefox and Safari each pick something else. It was the only green in the client and the only colour nothing had chosen. |

Two things the audit found and *kept*: the colour discipline (one raw
Tailwind palette colour in the entire client, since removed) and the
one-hue chart palette, which is deliberate and documented in
`app/globals.css`.

---

## Tokens

All in `app/globals.css`. Semantic names only — a screen naming
`bg-emerald-500` is a screen that will disagree with the next one and be
invisible in dark mode.

### Colour

| Token | For |
|---|---|
| `background` / `foreground` | The page and its ink. |
| `card` / `surface` | A panel on the page. Same paint, two names: `card` is what shadcn's components use, `surface` is what the rest of the client says. |
| `surface-muted` | A recessed strip: a table head, a footer, the quiet half of a split. |
| `popover` | Something in front of the page. |
| `primary` | The emphatic action. A near-black with a little blue in it, *not* a brand colour — the blue here belongs to data and to focus. |
| `secondary` / `accent` | A chip fill; a hover fill. |
| `muted` / `muted-foreground` | A quiet fill; secondary text. 5.2:1 on the page ground. |
| `destructive` `success` `warning` `info` | The four states. Each is an **ink** colour, tinted at the point of use — `bg-warning/10 text-warning` — so one token stays contrast-checked instead of three. |
| `border` / `border-subtle` | `border` separates things that are different; `border-subtle` divides things that are the same. |
| `input` | A shade stronger than `border`, so a field reads as somewhere to type. |
| `ring` | Focus, and nothing else in the client is this blue. |
| `sidebar*` | The rail: `sidebar`, `-foreground`, `-hover`, `-active`, `-active-foreground`, `-border`. Nothing renders one until phase 2. |
| `data` / `data-soft` / `grid` | Charts. One hue, because every series in this client is a single series. |

Both modes are picked against their own ground. A colour that passes on
white and is merely brightened does not pass on the dark surface.

### Scale

```
radius   sm 4px · md 6px · lg 8px · xl 12px · 2xl 16px
         inputs, buttons, rows and badges are md. panels lg. dialogs xl.

utility  .row     a record in a list   — border, surface, 12/10px padding
         .panel   a block of content   — border, surface, 16/12px padding
         .meter   a <progress> bar     — in --data, not the browser's green

text     2xs 11px · xs 12px · sm 14px · base 16px · lg 18px · xl 20px

shadow   raised   a panel sitting on the page
         overlay  something in front of it

motion   150ms, cubic-bezier(0.2, 0, 0, 1) — the default for bare
         `transition-*`. Nothing animates for longer.
```

Controls come in three heights and that is all: `h-6` (xs), `h-7` (sm),
`h-8` (default), `h-9` (lg). Inputs, selects and default buttons are all
`h-8`, so a filter bar lines up without anybody nudging it.

### Type

| Role | Class |
|---|---|
| Page title | `text-xl font-semibold tracking-tight` — via `PageHeader` |
| Page description | `text-sm text-muted-foreground` — via `PageHeader` |
| Section heading | `text-sm font-medium` — via `SectionHeader` |
| Micro label | `text-2xs font-medium uppercase tracking-wide` — via `FieldLabel` |
| Body / table text | `text-sm` |
| Label | `text-sm font-medium` — via `Label` |
| Metadata | `text-xs text-muted-foreground` |
| Caption, densest | `text-2xs` |

Money, counts, dates and anything read down a column get tabular
numerals. `th`, `td`, `time` and `[data-numeric]` get them from the base
layer; elsewhere use `tabular-nums`.

---

## Primitives

Reach for these. Do not write the markup again.

| Component | File |
|---|---|
| `PageHeader` `SectionHeader` `BackLink` `FieldLabel` | `components/page-header.tsx` |
| `EmptyState` | `components/empty-state.tsx` |
| `ErrorState` | `components/error-state.tsx` |
| `StatusBadge` | `components/status-badge.tsx` |
| `Pagination` | `components/pagination.tsx` |
| `FilterBar` `FilterGroup` `FilterTabs` | `components/filter-tabs.tsx` |
| `CopyButton` `CopyField` | `components/copy.tsx` |
| `DangerZone` `TypedConfirm` | `components/danger-zone.tsx` |
| `Skeleton` `SkeletonRow(s)` `PageSkeleton` | `components/skeleton.tsx` |
| `ThemeScript` `ThemeToggle` | `components/theme.tsx` |
| `SubmitButton` `FormError` `FieldError` | `components/form.tsx` |
| `NativeSelect` | `components/ui/native-select.tsx` |
| `Refusal` (402 vs 403) | `components/refusal.tsx` |
| `StatTile` `StatRow` | `components/charts/stat-tile.tsx` |

The console shares all of them and adds its own where the *wording* has to
differ: `ConsoleHeading`, `ConsolePages`, `ConsoleRefused`, `Facts`,
`WorkspaceStatusBadge`. Each is a thin wrapper — mostly to pass
`ConsoleLink`, which does not prefetch, because a prefetched console route
writes a row to the platform audit log for a page nobody opened.

### Status tones

A badge carries a *meaning*, not a colour somebody reached for. Six of
them, in `components/status-badge.tsx`; the domain maps from API status →
tone live in `lib/tones.ts`.

| Tone | Means | Examples |
|---|---|---|
| `neutral` | The ordinary state. Says nothing. | active, open, confirmed |
| `quiet` | Over, and uninteresting. | archived, cancelled, ended |
| `pending` | Not finished, nobody at fault. | queued, draft, invited |
| `positive` | Finished, and it worked. | delivered, ready, verified |
| `caution` | Needs somebody. | past due, expiring, near a limit |
| `critical` | Wrong. | failed, suspended, blocked, revoked |

Badges are for real states. Not for names, dates, IDs, prices or ordinary
values.

---

## Dark mode

`ThemeScript` — inlined, blocking, first in `<body>` — reads the
`baton_theme` cookie and puts `dark` on `<html>` before the first paint.
`ThemeToggle` writes that cookie and flips the same class. There is no
provider and no context: the class **is** the state, and CSS reads it.

The server never reads the cookie, deliberately. A root layout that called
`cookies()` to answer a question about colour would make every route in
the client dynamic to do it, and `/register`, `/pricing` and
`/forgot-password` are prerendered today.

Both modes are defined in full. Do not give a colour its only definition
in one of them.

---

## Rules

**Cards.** Not everything is a card. Use whitespace, typography, borders
and surfaces for hierarchy. A card exists because content needs
containment, not because shadcn ships one. Danger zones are deliberately
not cards — a card says *this belongs together*, and what is wanted there
is *this is not like the rest of the page*.

**Destructive actions.** Two weights. `variant="destructive"` is tinted,
for things whose worst outcome is doing them again the other way.
`variant="danger"` is filled, for what cannot be undone. A screen where
both look alike is a screen where the irreversible one is a mis-click.

**Refusals.** The API's distinctions are load-bearing and the UI keeps
them: 402 (the plan is in the way — blue, links to billing) is not 403
(you may not — red, links nowhere). Nor are `workspace_suspended`,
`admin_session_expired`, `support_access_required`, `approval_required`,
lifecycle conflicts and validation errors interchangeable. None of them is
a generic toast.

**Alerts.** `Alert` has five tones — default, `info`, `success`,
`warning`, `destructive` — and no role of its own. The caller says what it
is: `role="alert"` for something that has just gone wrong, `role="status"`
for something that has just changed, nothing at all for copy that was on
the page the whole time. A standing banner declaring itself a live region
is announced out of order on every load, and it outranks the real refusal
below it.

**Never colour alone.** Every badge carries its own word. Every filter
carries `aria-current`. Every state has a name in the DOM.

**Focus.** Every focusable thing gets a visible ring — the base layer
gives one to anything that did not ask.

**Motion.** 150ms, and the base layer honours `prefers-reduced-motion`.

**Measured, not asserted.** Every text pair in both themes is ≥4.5:1 and
the focus ring ≥3:1; field borders are 3.0:1 against both the page and
their own fill. Layout borders (`--border`) are deliberately below that —
they divide, they do not identify a control — which is a decision to
revisit in phase 10, not an oversight.

**Backend authority.** Nothing here changes API semantics, routes,
authorization, entitlement or lifecycle behaviour. Where backend behaviour
and visual convenience conflict, the backend wins.
