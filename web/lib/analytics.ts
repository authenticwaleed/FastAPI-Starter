/**
 * Reading the numbers, the log, and the keys.
 *
 * Every figure comes from the API and none is recomputed here. Two totals
 * derived on a client from the same rows the API already counted is two
 * answers to one question, and the one on screen is the one somebody acts
 * on.
 */

import { api } from "@/lib/api";
import type {
  AiAnalytics,
  ApiKey,
  AuditEntry,
  ConversationAnalytics,
  Overview,
  Page,
} from "@/lib/types";

export type Window = { start: string | null; end: string | null; timezone: string };

function query(window: Window): string {
  const parameters = new URLSearchParams();

  if (window.start) parameters.set("start", window.start);
  if (window.end) parameters.set("end", window.end);
  // The API defaults to UTC. Sending the workspace's own zone is what
  // makes "Tuesday" mean the same thing on this page as it does to the
  // business, since every bucket is cut on that zone's midnight.
  parameters.set("timezone", window.timezone);

  return parameters.toString();
}

export function readOverview(workspaceId: string, window: Window) {
  return api<Overview>(
    `/workspaces/${workspaceId}/analytics/overview?${query(window)}`,
  );
}

export function readConversationAnalytics(workspaceId: string, window: Window) {
  return api<ConversationAnalytics>(
    `/workspaces/${workspaceId}/analytics/conversations?${query(window)}`,
  );
}

export function readAiAnalytics(workspaceId: string, window: Window) {
  return api<AiAnalytics>(
    `/workspaces/${workspaceId}/analytics/ai?${query(window)}`,
  );
}

export function listAuditLogs(
  workspaceId: string,
  { page = 1, event = null }: { page?: number; event?: string | null } = {},
) {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: "50",
  });

  if (event) parameters.set("event", event);

  return api<Page<AuditEntry>>(
    `/workspaces/${workspaceId}/audit-logs?${parameters}`,
  );
}

/** Unpaginated at the API: a workspace has a handful of keys, not a page. */
export function listApiKeys(workspaceId: string) {
  return api<ApiKey[]>(`/workspaces/${workspaceId}/api-keys`);
}

/**
 * How long somebody waited, in words.
 *
 * `null` stays null all the way to the screen. "Nothing has been answered
 * yet" and "answered instantly" are different facts, and rendering the
 * first as `0s` would report a response time no business achieved.
 */
export function duration(seconds: number | null): string | null {
  if (seconds === null) return null;

  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86_400) return `${(seconds / 3600).toFixed(1)}h`;

  return `${(seconds / 86_400).toFixed(1)}d`;
}

/** A rate the API sends as a fraction, as a percentage somebody reads. */
export function percentage(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}
