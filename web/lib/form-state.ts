/**
 * What a server action hands back to the form that called it.
 *
 * Its own module rather than living beside the first actions that needed
 * it, now that several of them share it: a file marked `"use server"` may
 * only export functions, so a type kept in one would have every other
 * action module importing from a sibling it has nothing else to do with.
 *
 * Nothing here composes a sentence. `ApiError.sentence` does that, from the
 * one map in `lib/errors.ts`, and an action's job is only to carry it.
 */

import type {
  AiReply,
  ApiKeyCreated,
  InvitationCreated,
  PlanOverride,
  SearchResult,
  SweepReport,
  SyncReport,
} from "@/lib/types";

export type FormState = {
  /** One sentence, already chosen for the code the API returned. */
  error?: string;
  /**
   * The code behind that sentence.
   *
   * Carried so a screen can tell a plan refusal from every other kind
   * without matching on prose. A 402 wants the upgrade prompt and a link
   * to billing; a 403 wants "ask an owner", which is a different screen
   * and a different next step.
   */
  code?: string;
  /**
   * The API's own prose, where it says something the code cannot.
   *
   * Two refusals on the platform surface carry their particulars here --
   * which state refused a lifecycle move, which colleague already
   * approved this -- and a screen shows that line beneath the sentence.
   * Displaying it is not branching on it: nothing anywhere decides
   * anything from these words, and `code` is still what a screen reads.
   */
  detail?: string;
  /** Per-field messages from a 422, keyed by the input's name. */
  fields?: Record<string, string>;
  /** For the flows that finish without navigating anywhere. */
  done?: boolean;
  /** How long to wait, when a 429 says so. */
  retryAfter?: number;
  /** How many notifications the last call cleared. */
  marked?: number;
  /**
   * The refusal was somebody else moving first, not a fault. The view has
   * been refetched; say so quietly rather than colouring it red.
   */
  stale?: boolean;
  /** What the assistant decided, when one was asked for. */
  reply?: AiReply;
  /**
   * The invitation just created, token included.
   *
   * Carried back because the API returns the token exactly once and the
   * screen has to show the link -- nothing emails it yet.
   */
  invitation?: InvitationCreated;
  /** What the knowledge base returned for a question. */
  search?: SearchResult;
  /**
   * Where a provider wants the person sent next.
   *
   * Shared by the payment checkout and a storefront install, because
   * they are the same shape: the API answers with a URL somewhere else,
   * nothing has changed yet, and the screen navigates away.
   */
  checkoutUrl?: string;
  /** What one due-run sweep did. */
  sweep?: SweepReport;
  /** What one storefront sync did. */
  sync?: SyncReport;
  /**
   * What a replay did.
   *
   * `false` is an ordinary answer meaning there was nothing to re-apply,
   * and the screen says so rather than colouring it as a failure. Carried
   * separately from `done` because the request succeeded either way.
   */
  applied?: boolean;
  /**
   * The plan just granted.
   *
   * Carried back because the API returns a grant when one is made and at
   * no other time -- there is no route that reads the current one -- so
   * this response is the only chance to show its expiry, or that it has
   * none.
   */
  override?: PlanOverride;
  /**
   * The key just made, with the secret in it.
   *
   * Carried because the API returns it exactly once and nothing stored
   * can reproduce it. If the action does not hand it to the screen, the
   * key is lost the moment it is created.
   */
  apiKey?: ApiKeyCreated;
} | null;

/** The shape every action's catch produces. Re-thrown if it is not a refusal. */
export type Refusal = { error: string; fields: Record<string, string> };
