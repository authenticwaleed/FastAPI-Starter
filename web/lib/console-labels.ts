/**
 * The console's wording, apart from the reads it describes.
 *
 * Pure, like `lib/labels.ts`, so nothing here drags `lib/console.ts` --
 * and through it `next/headers` -- into a bundle that has no business
 * holding it.
 *
 * Timestamps are in here because a formatted date is wording too, and
 * because the console shows a great many of them: when a workspace was
 * closed, when its records go, when somebody last signed in. One
 * formatter means those never disagree from screen to screen.
 */

import type { StaffRole } from "@/lib/types";

/** A moment, to the minute. Local to whoever is reading, not to the business. */
export function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** A date, where the time of day is noise -- an erasure date, a period end. */
export function day(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export const STAFF_ROLE_LABEL: Record<StaffRole, string> = {
  support: "Support",
  admin: "Administrator",
  owner: "Owner",
};

/**
 * What each staff rank actually reaches, in one line.
 *
 * Shown on the console's front page rather than left implicit, because
 * "why can my colleague see the platform log and I cannot" is otherwise a
 * question that arrives as a bug report.
 */
export const STAFF_ROLE_REACH: Record<StaffRole, string> = {
  support: "Read a business's account and the people in it.",
  admin: "The same, and the platform's own log.",
  owner: "The same, and who else runs this platform.",
};

/**
 * The platform log's actions, as sentences.
 *
 * Only the ones this phase can produce, plus the handful a console session
 * will sit beside in the list. Unknown actions render as they arrived --
 * this log outlives the code that wrote to it, and a row from a version
 * that knew an action this one does not is a row worth showing anyway.
 */
const ACTIONS: Record<string, string> = {
  "console.opened": "Opened the console",
  "audit.read": "Read the platform log",
  "workspaces.searched": "Searched for a business",
  "workspace.read": "Opened a business",
  "workspace.members_read": "Read a team",
  "workspace.subscription_read": "Read a subscription",
  "workspace.usage_read": "Read usage",
  "workspace.integrations_read": "Read connections",
  "workspace.audit_read": "Read a business's own log",
  "users.searched": "Searched for an account",
  "user.read": "Opened an account",
  "staff.listed": "Listed platform staff",
  "staff.granted": "Gave somebody platform access",
  "staff.role_changed": "Changed a colleague's rank",
  "staff.revoked": "Took platform access away",
};

export function describeAction(action: string): string {
  return ACTIONS[action] ?? action;
}
