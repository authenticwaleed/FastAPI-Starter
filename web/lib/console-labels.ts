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

import type { InboxWording } from "@/lib/labels";
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

/**
 * How long is left, in words, or null once there is nothing left.
 *
 * Null rather than "0m", because the two are different facts and the
 * screen does different things with them: a window with a minute in it is
 * a nudge, and a window that has closed is a banner saying so and a
 * request form. Rounding is downwards for the same reason -- somebody
 * with 59 seconds should read "less than a minute", never "1m".
 *
 * Pure and taking `now`, so the countdown that ticks in the browser and
 * the sentence rendered on the server come out of the same function.
 */
export function timeLeft(expiresAt: string, now: number): string | null {
  const seconds = Math.floor((Date.parse(expiresAt) - now) / 1000);

  if (!Number.isFinite(seconds) || seconds <= 0) return null;
  if (seconds < 60) return "less than a minute";

  const minutes = Math.floor(seconds / 60);

  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;

  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

/**
 * The same inbox, worded for somebody it does not belong to.
 *
 * Every "you" on a customer's own screen becomes the team here. A thread
 * telling a staff member they had sent the reply, or that they have this
 * conversation, would be the first place the console started to look like
 * a colleague -- and a support engineer who reads it that way is one step
 * from answering as the business.
 */
export const CONSOLE_WORDING: InboxWording = {
  voice: {
    customer: "Their customer",
    agent: "The team",
    ai: "Assistant",
    system: "Baton",
  },
  state: {
    ai_active: "Assistant is answering",
    suggest_only: "Assistant drafts, the team sends",
    human_active: "The team has this",
    ai_disabled: "Assistant is off",
  },
};

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
  "support_access.granted": "Asked for access to a customer's data",
  "support_access.revoked": "Ended their own access",
  "support_access.listed": "Reviewed who has had access",
  "workspace.conversations_read": "Read a customer's inbox",
  "workspace.messages_read": "Read one of a customer's threads",
  "staff.listed": "Listed platform staff",
  "staff.granted": "Gave somebody platform access",
  "staff.role_changed": "Changed a colleague's rank",
  "staff.revoked": "Took platform access away",
  "workspace.suspended": "Suspended a business",
  "workspace.unsuspended": "Lifted a suspension",
  "workspace.cancelled": "Closed a business's account",
  "workspace.restored": "Restored a closed account",
  "workspace.erase_after_changed": "Moved an erasure date",
  "workspace.erased": "Erased a business, and everything in it",
  // The one entry written for something that did not happen. Somebody
  // typing the wrong name into an erasure is either tired or in the
  // wrong window, and both are worth reading about afterwards.
  "workspace.erase_refused": "Mistyped the name of a business being erased",
  "user.deactivated": "Turned an account off",
  "user.activated": "Turned an account back on",
  "user.sessions_revoked": "Signed an account out everywhere",
  "user.email_verified": "Marked an address confirmed",
  "approval.requested": "Asked a colleague to agree to something",
  "approval.granted": "Agreed to a colleague's request",
  "approval.spent": "Spent a colleague's agreement",
  "approval.listed": "Read what has been agreed to",
};

export function describeAction(action: string): string {
  return ACTIONS[action] ?? action;
}
