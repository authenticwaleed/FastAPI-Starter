/**
 * The platform's own books, machinery and numbers.
 *
 * W13's reads, in one module because they are one subject seen from four
 * sides: what is being paid for, what the queue is doing, what the whole
 * thing adds up to, and who has been looking at customers. None of them
 * takes a workspace id except the job filter, and none returns anything
 * about one business that its own screens do not already show.
 *
 * The same discipline as the rest of the console: every function here
 * writes a row to the platform's audit log, so each screen calls exactly
 * what it shows and nothing fetches ahead. `/admin/health` in particular
 * is a page a person reads and not a probe an orchestrator polls — there
 * is no refresh timer on it and there must not be one.
 */

import { adminApi as read } from "@/lib/console-api";
import type {
  AdminAiSpend,
  AdminAlerts,
  AdminBillingEvent,
  AdminGrowth,
  AdminHealth,
  AdminJobDetail,
  AdminJobSummary,
  AdminOverview,
  AdminRevenue,
  AdminSubscriptionRow,
  AdminWebhookFailure,
  AdminWhatsAppNumber,
  Page,
} from "@/lib/types";

export const PLATFORM_PAGE_SIZE = 50;

function paged(page: number, extra: Record<string, string | null | undefined> = {}) {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(PLATFORM_PAGE_SIZE),
  });

  for (const [key, value] of Object.entries(extra)) {
    if (value) parameters.set(key, value);
  }

  return parameters;
}

// --- the books ---------------------------------------------------------

/**
 * Every subscription, as the payment provider describes it.
 *
 * Filtered on what the provider says rather than on what a workspace is
 * entitled to, deliberately: this is the provider's side of the ledger,
 * so a business comped onto Business appears here on whatever it is
 * actually paying for. The other question is asked on the console's
 * workspace search.
 */
export function listSubscriptions({
  status = null,
  plan = null,
  page = 1,
}: { status?: string | null; plan?: string | null; page?: number } = {}) {
  return read<Page<AdminSubscriptionRow>>(
    `/billing/subscriptions?${paged(page, { status, plan })}`,
  );
}

export function listBillingEvents({
  eventType = null,
  page = 1,
}: { eventType?: string | null; page?: number } = {}) {
  return read<Page<AdminBillingEvent>>(
    `/billing/events?${paged(page, { event_type: eventType })}`,
  );
}

// --- the machinery -----------------------------------------------------

/**
 * The queue, across every workspace.
 *
 * `kind=deliver_message&status=failed` is the query this exists for: it
 * turns "their message never arrived" into a row with an error on it,
 * without anybody opening a database console.
 */
export function searchJobs({
  kind = null,
  status = null,
  workspaceId = null,
  page = 1,
}: {
  kind?: string | null;
  status?: string | null;
  workspaceId?: string | null;
  page?: number;
} = {}) {
  return read<Page<AdminJobSummary>>(
    `/jobs?${paged(page, { kind, status, workspace_id: workspaceId })}`,
  );
}

/** One job, with its attempts, its error, and a payload redacted by kind. */
export function readJob(jobId: string) {
  return read<AdminJobDetail>(`/jobs/${jobId}`);
}

/**
 * Deliveries this application turned away.
 *
 * The one failure in the system that otherwise reaches nobody: the
 * provider is told with a status code, the sender is a machine, and the
 * customer whose storefront secret was mistyped notices days later that
 * their orders stopped arriving.
 */
export function listWebhookFailures({
  provider = null,
  reason = null,
  page = 1,
}: { provider?: string | null; reason?: string | null; page?: number } = {}) {
  return read<Page<AdminWebhookFailure>>(
    `/webhooks/failures?${paged(page, { provider, reason })}`,
  );
}

/** Every connected number, and whose it is. Unpaginated at the API. */
export function listWhatsAppNumbers() {
  return read<AdminWhatsAppNumber[]>("/integrations/whatsapp");
}

/**
 * Whether anything is wrong right now.
 *
 * Distinct from the public `/health`, which answers an orchestrator. This
 * one is for a person, and the phase's rule is that it may not be put on
 * a timer: every read of it is a row in the platform log, and a page that
 * refreshed itself would fill that log with nobody's decisions.
 */
export function readHealth() {
  return read<AdminHealth>("/health");
}

/** Who has been reading a lot of customers' accounts lately. */
export function readAlerts({ hours = 1 }: { hours?: number } = {}) {
  return read<AdminAlerts>(`/alerts?hours=${hours}`);
}

// --- the numbers -------------------------------------------------------
//
// Four dashboards rather than one, and four reads. A single page calling
// all of them would spend four rows on somebody who wanted the headline,
// which is the same argument the workspace detail screen makes about not
// loading its five sub-screens.

export function readPlatformOverview() {
  return read<AdminOverview>("/analytics/overview");
}

export function readGrowth({ days = 30 }: { days?: number } = {}) {
  return read<AdminGrowth>(`/analytics/growth?days=${days}`);
}

export function readRevenue() {
  return read<AdminRevenue>("/analytics/revenue");
}

export function readAiSpend({ days = 30 }: { days?: number } = {}) {
  return read<AdminAiSpend>(`/analytics/ai?days=${days}`);
}
