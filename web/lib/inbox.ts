/**
 * Reading the inbox.
 *
 * The queries a screen makes, in one place, so that a page component is
 * about layout and a filter is not spelled out three different ways in
 * three different files.
 */

import { api } from "@/lib/api";
import type {
  AiResponseLog,
  Contact,
  Conversation,
  ConversationEvent,
  ConversationStatus,
  Message,
  Page,
} from "@/lib/types";

export const INBOX_PAGE_SIZE = 30;
export const THREAD_PAGE_SIZE = 50;

export type InboxFilters = {
  page: number;
  /** Repeated in the query string. The inbox opens on open *and* pending. */
  statuses: ConversationStatus[];
  /** `me`, a colleague's numeric id, or nothing. */
  assignedTo: string | null;
  unassigned: boolean;
  search: string | null;
  contactId?: string;
};

/**
 * The inbox opens on what is still somebody's problem.
 *
 * Open and pending both, because a thread waiting on a delivery has not
 * been dealt with -- it is only waiting. Closed is a filter somebody asks
 * for, never a default.
 */
export const DEFAULT_STATUSES: ConversationStatus[] = ["open", "pending"];

export function inboxQuery(filters: InboxFilters): string {
  const query = new URLSearchParams();

  query.set("page", String(filters.page));
  query.set("page_size", String(INBOX_PAGE_SIZE));

  for (const status of filters.statuses) query.append("status", status);

  // `unassigned` wins over `assigned_to` at the API, because asking for
  // both is a contradiction. The screens never send both; this mirrors the
  // precedence rather than relying on it.
  if (filters.unassigned) {
    query.set("unassigned", "true");
  } else if (filters.assignedTo) {
    query.set("assigned_to", filters.assignedTo);
  }

  if (filters.search) query.set("search", filters.search);
  if (filters.contactId) query.set("contact_id", filters.contactId);

  return query.toString();
}

export function listConversations(workspaceId: string, filters: InboxFilters) {
  return api<Page<Conversation>>(
    `/workspaces/${workspaceId}/conversations?${inboxQuery(filters)}`,
  );
}

export function readConversation(workspaceId: string, conversationId: string) {
  return api<Conversation>(
    `/workspaces/${workspaceId}/conversations/${conversationId}`,
  );
}

/**
 * One page of a thread, newest first.
 *
 * That is the API's order and it is the right one: page one is what you
 * see when a chat opens, and paging back is scrolling up. A screen
 * rendering oldest-at-the-top reverses each page, which is what
 * `messagesOldestFirst` below is for.
 */
export function listMessages(
  workspaceId: string,
  conversationId: string,
  page = 1,
) {
  return api<Page<Message>>(
    `/workspaces/${workspaceId}/conversations/${conversationId}/messages` +
      `?page=${page}&page_size=${THREAD_PAGE_SIZE}`,
  );
}

export function messagesOldestFirst(messages: Message[]): Message[] {
  return [...messages].reverse();
}

export function listEvents(workspaceId: string, conversationId: string) {
  return api<Page<ConversationEvent>>(
    `/workspaces/${workspaceId}/conversations/${conversationId}/events` +
      `?page=1&page_size=50`,
  );
}

export function listAiResponses(workspaceId: string, conversationId: string) {
  return api<Page<AiResponseLog>>(
    `/workspaces/${workspaceId}/conversations/${conversationId}/ai-responses` +
      `?page=1&page_size=20`,
  );
}

export function listContacts(
  workspaceId: string,
  { page = 1, search = null }: { page?: number; search?: string | null } = {},
) {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });

  if (search) query.set("search", search);

  return api<Page<Contact>>(`/workspaces/${workspaceId}/contacts?${query}`);
}

export function readContact(workspaceId: string, contactId: string) {
  return api<Contact>(`/workspaces/${workspaceId}/contacts/${contactId}`);
}
