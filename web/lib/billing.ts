/**
 * Reading what a workspace is on and what it has used.
 *
 * The queries only. The rule about which field to gate on is
 * `lib/plans.ts`, which is pure so a client component can import it.
 */

import { api } from "@/lib/api";
import type { Plan, UsageSummary, WorkspacePlan } from "@/lib/types";

/**
 * The price list.
 *
 * Unauthenticated, because a price list is a price list: whoever is
 * deciding whether to sign up has no account yet, and asking them to make
 * one to see what it costs is the wrong way round.
 */
export function listPlans() {
  return api<Plan[]>("/plans", { anonymous: true });
}

/**
 * What this workspace may do, and what it is paying for.
 *
 * Any member, not just an administrator: what the business is on governs
 * what everybody working in it can do, and being told "your plan does not
 * include this" by a screen that will not say what the plan is would be a
 * dead end.
 */
export function readSubscription(workspaceId: string) {
  return api<WorkspacePlan>(`/workspaces/${workspaceId}/subscription`);
}

export function readUsage(workspaceId: string) {
  return api<UsageSummary>(`/workspaces/${workspaceId}/usage`);
}
