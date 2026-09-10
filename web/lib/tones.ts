/**
 * What each of the API's states *means*, once, for every screen that shows
 * one.
 *
 * The client was deciding this in ternaries written where the badge was
 * rendered, which is why `cancelled` came out outlined on the orders list
 * and grey on the order itself, and why a product's `draft` -- somebody
 * still writing it -- looked exactly like a `pending` order, which is
 * somebody waiting.
 *
 * Kept beside `labels.ts` and for the same reason: it is pure, so a client
 * component can import it without dragging a module that reaches
 * `next/headers` into the browser bundle. And kept *apart* from it because
 * a tone is not a word -- one says what a state is called, the other says
 * how much it should worry you.
 */

import type { Tone } from "@/components/status-badge";
import type {
  ContactStatus,
  DocumentStatus,
  OrderStatus,
  ProductStatus,
} from "@/lib/types";

/**
 * `pending` is the only order state with anything to do about it, so it is
 * the only one that is not grey. Six differently coloured badges down a
 * list would make the one row that needs somebody the hardest to find.
 */
export const ORDER_TONE: Record<OrderStatus, Tone> = {
  pending: "caution",
  confirmed: "neutral",
  shipped: "neutral",
  delivered: "positive",
  cancelled: "quiet",
  refunded: "quiet",
};

/**
 * `active` is what the assistant is told about. `draft` is unfinished and
 * `archived` is finished with; neither is a problem, so neither is
 * coloured as one.
 */
export const PRODUCT_TONE: Record<ProductStatus, Tone> = {
  active: "neutral",
  draft: "pending",
  archived: "quiet",
};

/**
 * `lead` and `customer` are both ordinary -- one has bought and one has
 * not, which is a fact about the business rather than a state to act on.
 * `blocked` is the only one somebody decided.
 */
export const CONTACT_TONE: Record<ContactStatus, Tone> = {
  lead: "pending",
  customer: "neutral",
  blocked: "critical",
};

/**
 * Ingestion, which is the one place a `failed` is worth red: a document
 * that did not process is a gap in what the assistant knows, and nothing
 * else on the screen says so.
 */
export const DOCUMENT_TONE: Record<DocumentStatus, Tone> = {
  pending: "pending",
  processing: "pending",
  ready: "positive",
  failed: "critical",
};
