/**
 * Wording, kept apart from the queries that fetch what it describes.
 *
 * Its own module because a client component needs these and must not pull
 * in `lib/inbox.ts` to get them: that file reaches `lib/api.ts`, which
 * reaches `next/headers`, and dragging server-only code into the browser
 * bundle is a build error rather than a runtime one. Splitting them is the
 * fix; a label is not a query and never was.
 */

import type {
  AuditEntry,
  ConversationState,
  SenderType,
  StorefrontProvider,
} from "@/lib/types";

/**
 * Who is answering, in words a person would use.
 *
 * The API derives `state` from `ai_mode` and the handoff together so a
 * client has one field to render rather than a rule to reimplement. This
 * is only the wording for it.
 */
export const STATE_LABEL: Record<ConversationState, string> = {
  ai_active: "Assistant is answering",
  suggest_only: "Assistant drafts, you send",
  human_active: "You have this",
  ai_disabled: "Assistant is off",
};

/**
 * Everything an inbox screen says in the second person.
 *
 * Gathered into one object because it all changes together and for one
 * reason: the console reads these same threads and is not the business
 * whose threads they are. "You have this" and "You: " are true on a
 * customer's own screen and false on the platform's, and a staff member
 * being addressed as the team is where a support console starts to look
 * like a colleague -- the thing the API declines to allow at its end by
 * refusing support an "assigned to me" filter.
 */
export type InboxWording = {
  voice: Record<SenderType, string>;
  state: Record<ConversationState, string>;
};

/** The wording for somebody reading their own inbox. */
export const TENANT_WORDING: InboxWording = {
  voice: {
    customer: "Them",
    agent: "You",
    ai: "Assistant",
    system: "Baton",
  },
  state: STATE_LABEL,
};

/**
 * A workspace's own audit events, as sentences.
 *
 * Here rather than beside the screen that first needed them, because two
 * screens now render this log: the business's own audit page and the
 * console's copy of it. Support quoting an entry back to a customer has to
 * be quoting the words that customer can read for themselves, and two maps
 * would eventually be two vocabularies.
 *
 * An unknown event shows as it arrived. This log outlives the code that
 * writes to it, and a row from a version that knew an event this one does
 * not is still worth showing.
 */
const EVENTS: Record<string, string> = {
  "workspace.created": "Workspace created",
  "workspace.updated": "Workspace settings changed",
  "workspace.closed": "Workspace closed",
  "member.invited": "Somebody was invited",
  "member.joined": "Somebody joined",
  "member.role_changed": "A role was changed",
  "member.removed": "Somebody left or was removed",
  "whatsapp.connected": "WhatsApp connected",
  "whatsapp.disconnected": "WhatsApp disconnected",
  "knowledge.document_uploaded": "A document was added",
  "knowledge.document_deleted": "A document was deleted",
  "conversation.assigned": "A conversation was assigned",
  "conversation.closed": "A conversation was closed",
  "conversation.ai_disabled": "The assistant was switched off for a thread",
  "subscription.changed": "The subscription changed",
  "api_key.created": "An API key was created",
  "api_key.revoked": "An API key was revoked",
  "support.access_granted": "Support was given access",
  "support.access_ended": "Support access ended",
  "workspace.suspended": "The workspace was suspended",
  "workspace.unsuspended": "The suspension was lifted",
  "workspace.restored": "The workspace was restored",
};

export function describeEvent(event: string): string {
  return EVENTS[event] ?? event;
}

/**
 * Who an audit entry names, as much as is still known.
 *
 * A null actor is a real entry rather than missing data -- a payment
 * provider changed a subscription, and naming somebody would put an
 * accusation in the record. An actor with an address and no id is a
 * deleted account, which is the case this table exists to outlive.
 */
export function describeActor(
  actor: { name: string | null; email: string | null } | null,
): string {
  if (actor === null) return "Not a person";

  return actor.name ?? actor.email ?? "A deleted account";
}

/**
 * The same, for an entry in a *workspace's* own log.
 *
 * A support engineer never appears among a customer's colleagues: the API
 * leaves the actor empty and writes their address into `by_staff`
 * instead, precisely so that an entry cannot read as one of the
 * customer's own people having done it.
 *
 * Which leaves a screen a choice about how to render the empty actor, and
 * only one of the answers is honest. "Not a person" is right for a
 * payment provider changing a subscription; on a support entry it would
 * tell a business that nobody was in their account when somebody named
 * was -- and being able to see that is half of what the support-access
 * design is for.
 */
export function describeTenantActor(entry: AuditEntry): string {
  const staff = entry.metadata?.by_staff;

  if (typeof staff === "string") return `Baton support · ${staff}`;

  return describeActor(entry.actor);
}

/** The storefronts this product can connect to. */
export const STOREFRONTS: StorefrontProvider[] = ["shopify", "woocommerce"];

export const STOREFRONT_LABEL: Record<StorefrontProvider, string> = {
  shopify: "Shopify",
  woocommerce: "WooCommerce",
};
