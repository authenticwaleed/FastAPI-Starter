/**
 * The second person, for the two acts that need one.
 *
 * Its own module because two unrelated screens depend on it -- erasing a
 * workspace and promoting somebody to owner -- and because W13 builds the
 * other half on top: this phase opens the loop by raising a request, and
 * that one closes it by letting somebody else agree.
 *
 * The rule the whole thing exists for is that whoever agreed cannot be
 * whoever acts. Nothing here enforces that and nothing here should: the
 * API refuses at the moment the approval is spent, which is the only
 * moment both people are known.
 */

import { adminApi } from "@/lib/console-api";
import type { Approval, ApprovableAction, Page } from "@/lib/types";

/**
 * Every approval, spent and expired ones included.
 *
 * History is most of the value: a list of only what is pending is almost
 * always empty, and the question being asked is what has been agreed to.
 * Administrator rank at the API.
 */
export function listApprovals({ page = 1 }: { page?: number } = {}) {
  const parameters = new URLSearchParams({ page: String(page), page_size: "50" });

  return adminApi<Page<Approval>>(`/approvals?${parameters}`);
}

/**
 * What this act has waiting for it, most recent first.
 *
 * Read from the whole list rather than from a filter, because the API
 * offers none -- and a screen asking "is there an approval for erasing
 * *this* workspace" is asking about one row among a few dozen. If the
 * platform's approval history ever outgrows one page, the answer is a
 * filter on the endpoint rather than paging through it here.
 */
export async function approvalsFor(
  action: ApprovableAction,
  subject: string,
): Promise<Approval[]> {
  const page = await listApprovals();

  return page.items.filter(
    (approval) => approval.action === action && approval.subject === subject,
  );
}

/**
 * The one to spend, if there is one.
 *
 * `usable` is the API's own answer, from the three timestamps and the
 * clock. A client must not work it out for itself: an approval that was
 * agreed to and then spent has not expired, and one raised but not yet
 * agreed to looks identical from the outside.
 *
 * It says nothing about whether *you* may spend it. If you are the person
 * who approved it, the API refuses at the moment it is spent -- which is
 * the only moment it knows who is asking.
 */
export function usableApproval(approvals: Approval[]): Approval | null {
  return approvals.find((approval) => approval.usable) ?? null;
}

/** Waiting on a colleague: raised, not yet agreed to, not yet expired. */
export function pendingApproval(approvals: Approval[]): Approval | null {
  return (
    approvals.find(
      (approval) =>
        approval.approved_at === null &&
        approval.consumed_at === null &&
        Date.parse(approval.expires_at) > Date.now(),
    ) ?? null
  );
}

export function raiseApproval(request: {
  action: ApprovableAction;
  subject: string;
  reason: string;
  role?: string;
}) {
  return adminApi<Approval>("/approvals", { method: "POST", json: request });
}
