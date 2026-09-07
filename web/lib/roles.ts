/**
 * What a role may do to another role.
 *
 * Pure, and in its own module for the reason `lib/labels.ts` is: a client
 * component needs these to decide which controls to render, and importing
 * them from a file that also fetches would drag `next/headers` into the
 * browser bundle and fail the build.
 *
 * The rule mirrors `may_manage` in the API's membership service, and
 * mirroring is all it does. The API decides every time; this only decides
 * what is worth putting on screen. Where the two disagree the API is right
 * and this file is the bug.
 */

import type { WorkspaceRole } from "@/lib/types";

/** Least authority first, so an index into it is a rank. */
export const PRECEDENCE: WorkspaceRole[] = ["viewer", "agent", "admin", "owner"];

function outranks(actor: WorkspaceRole, target: WorkspaceRole): boolean {
  // Strictly, so equal roles cannot manage each other: one admin demoting
  // another is how a disagreement between two people with the same
  // authority becomes whoever clicks first winning.
  return PRECEDENCE.indexOf(actor) > PRECEDENCE.indexOf(target);
}

/**
 * Whether somebody holding `actor` may act on somebody holding `target`.
 *
 * An owner may act on anyone, another owner included: somebody has to be
 * able to settle a dispute between two owners, and the last-owner rule
 * already stops that leaving a workspace unadministered.
 *
 * Everyone else has to outrank their target strictly. That is also what
 * stops an admin promoting anybody into the rank they hold themselves,
 * which would turn `admin` into `owner` in two moves.
 */
export function mayManage(actor: WorkspaceRole | null, target: WorkspaceRole): boolean {
  if (actor === null) return false;

  return actor === "owner" || outranks(actor, target);
}

/**
 * The roles `actor` may hand out.
 *
 * Checked against the role being granted, not only the one being taken
 * away -- the API checks both, because otherwise an admin could not demote
 * another admin but could still make an agent into one, which is the same
 * privilege through a different door.
 */
export function grantableBy(actor: WorkspaceRole | null): WorkspaceRole[] {
  return PRECEDENCE.filter((role) => mayManage(actor, role));
}

/**
 * What each role is for.
 *
 * Four fixed names rather than a permission engine, and they fan out
 * rather than nest: an admin manages people, an agent handles customers,
 * and neither contains the other. So the picker explains each one instead
 * of implying a slider from less to more.
 */
export const ROLE_DESCRIPTION: Record<WorkspaceRole, string> = {
  owner: "Everything an admin can do, plus closing the workspace.",
  admin: "Manages the team, the plan, the catalogue and the settings.",
  agent: "Answers customers: the inbox, contacts and orders.",
  viewer: "Reads everything and changes nothing.",
};
