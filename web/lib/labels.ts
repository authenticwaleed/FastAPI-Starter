/**
 * Wording, kept apart from the queries that fetch what it describes.
 *
 * Its own module because a client component needs these and must not pull
 * in `lib/inbox.ts` to get them: that file reaches `lib/api.ts`, which
 * reaches `next/headers`, and dragging server-only code into the browser
 * bundle is a build error rather than a runtime one. Splitting them is the
 * fix; a label is not a query and never was.
 */

import type { ConversationState } from "@/lib/types";

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
