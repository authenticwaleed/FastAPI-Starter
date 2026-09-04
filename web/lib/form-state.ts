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

import type { AiReply } from "@/lib/types";

export type FormState = {
  /** One sentence, already chosen for the code the API returned. */
  error?: string;
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
} | null;

/** The shape every action's catch produces. Re-thrown if it is not a refusal. */
export type Refusal = { error: string; fields: Record<string, string> };
