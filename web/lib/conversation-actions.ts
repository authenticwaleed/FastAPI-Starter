"use server";

/**
 * Everything a thread can be told to do.
 *
 * Agent or above at the API for every one of these. The screens hide what
 * a viewer cannot use, and each action still handles its own refusal --
 * a hidden control is a courtesy, never the enforcement.
 *
 * Two refusals here are not failures. `conversation_closed` and
 * `conversation_already_open` are what two people working one inbox do to
 * each other, and both mean "your view is stale" rather than "you did
 * something wrong". They revalidate and say so quietly.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { AiReply, Conversation, Message } from "@/lib/types";

export type { FormState };

/** The codes that mean somebody else moved first. */
const STALE = new Set(["conversation_closed", "conversation_already_open"]);

function failure(error: unknown, path: string): FormState {
  if (!(error instanceof ApiError)) throw error;

  if (STALE.has(error.code)) {
    // Refetch rather than argue. The thread on screen is out of date, and
    // showing the current one is more use than a red box about the one
    // that was there a moment ago.
    revalidatePath(path);

    return { error: error.sentence, stale: true };
  }

  return {
    error: error.sentence,
    fields: error.fields,
    retryAfter: error.retryAfter ?? undefined,
  };
}

function threadPath(conversationId: string): string {
  return `/inbox/${conversationId}`;
}

type Ids = { workspaceId: string; conversationId: string };

function ids(form: FormData): Ids {
  return {
    workspaceId: String(form.get("workspace_id") ?? ""),
    conversationId: String(form.get("conversation_id") ?? ""),
  };
}

/**
 * Send a reply.
 *
 * Never optimistic. A message that appeared in the thread and then turned
 * out not to have been accepted is the one failure an agent cannot recover
 * from -- they have already moved on believing the customer was answered.
 */
export async function sendMessage(_: FormState, form: FormData): Promise<FormState> {
  const { workspaceId, conversationId } = ids(form);
  const text = String(form.get("text") ?? "").trim();

  if (!text) return { fields: { text: "Write something first." } };

  try {
    await api<Message>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
      { method: "POST", json: { text } },
    );
  } catch (error) {
    const state = failure(error, threadPath(conversationId));

    // A send refused because somebody else closed the thread is the one
    // stale case the composer cannot report for itself: revalidating
    // re-renders the page without a composer at all, so the notice would
    // be unmounted before anybody read it. Carry it in the address
    // instead, where it survives the refresh.
    if (state?.stale) redirect(`${threadPath(conversationId)}?stale=1`);

    return state;
  }

  revalidatePath(threadPath(conversationId));
  revalidatePath("/inbox");

  return { done: true };
}

/**
 * Mark the thread read.
 *
 * Called from an effect after the thread has actually been looked at,
 * never during the render. Next prefetches links on hover, and a render
 * that marked read would clear the unread count on every row somebody's
 * cursor crossed on the way down the inbox.
 */
export async function markConversationRead(
  workspaceId: string,
  conversationId: string,
): Promise<void> {
  try {
    await api<Conversation>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/read`,
      { method: "POST" },
    );
  } catch (error) {
    // Nothing to tell anybody. This is housekeeping that happened to fail,
    // and a toast about it would interrupt somebody mid-conversation.
    if (!(error instanceof ApiError)) throw error;

    return;
  }

  revalidatePath("/inbox");
}

export async function setStatus(_: FormState, form: FormData): Promise<FormState> {
  const { workspaceId, conversationId } = ids(form);
  const action = String(form.get("action") ?? "");
  const endpoint = action === "reopen" ? "reopen" : "close";

  try {
    await api<Conversation>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/${endpoint}`,
      { method: "POST" },
    );
  } catch (error) {
    return failure(error, threadPath(conversationId));
  }

  revalidatePath(threadPath(conversationId));
  revalidatePath("/inbox");

  return { done: true };
}

export async function assignConversation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const { workspaceId, conversationId } = ids(form);
  const raw = String(form.get("user_id") ?? "");

  try {
    await api<Conversation>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/assign`,
      // An explicit null unassigns, which is why the API takes a body
      // here rather than offering a second endpoint to delete.
      { method: "POST", json: { user_id: raw === "" ? null : Number(raw) } },
    );
  } catch (error) {
    return failure(error, threadPath(conversationId));
  }

  revalidatePath(threadPath(conversationId));
  revalidatePath("/inbox");

  return { done: true };
}

/**
 * Take the thread from the assistant, or hand it back.
 *
 * One action for both, because it is one control in two states, and the
 * state is the conversation's -- never something the screen remembers.
 *
 * Handing back defaults to drafting rather than answering: a thread
 * somebody had to take over is not one to put back on full automation
 * without saying so. The API decides that default; this only carries it.
 */
export async function handoff(_: FormState, form: FormData): Promise<FormState> {
  const { workspaceId, conversationId } = ids(form);
  const take = form.get("action") === "takeover";
  const reason = String(form.get("reason") ?? "").trim();

  const path = take ? "takeover" : "release-to-ai";
  const body = take
    ? reason
      ? { reason }
      : {}
    : { ai_mode: String(form.get("ai_mode") ?? "suggest_only") };

  try {
    await api<Conversation>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/${path}`,
      { method: "POST", json: body },
    );
  } catch (error) {
    return failure(error, threadPath(conversationId));
  }

  revalidatePath(threadPath(conversationId));
  revalidatePath("/inbox");

  return { done: true };
}

/**
 * Ask the assistant to draft a reply.
 *
 * Answers 200 whatever it decides, so there is no error path for "it chose
 * not to answer" -- the decision comes back in the body and the screen
 * renders it. Rate limited and it costs money, so the form disables while
 * one is in flight and a 429 carries how long to wait.
 */
export async function requestAiReply(_: FormState, form: FormData): Promise<FormState> {
  const { workspaceId, conversationId } = ids(form);

  let reply: AiReply;

  try {
    reply = await api<AiReply>(
      `/workspaces/${workspaceId}/conversations/${conversationId}/ai-reply`,
      { method: "POST" },
    );
  } catch (error) {
    return failure(error, threadPath(conversationId));
  }

  revalidatePath(threadPath(conversationId));

  // `answered` means it was sent, which only happens in automatic mode.
  if (reply.decision === "answered") revalidatePath("/inbox");

  return { done: true, reply };
}

/** Open a thread with a contact, and go straight to it. */
export async function openConversation(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const contactId = String(form.get("contact_id") ?? "");

  let conversation: Conversation;

  try {
    conversation = await api<Conversation>(
      `/workspaces/${workspaceId}/conversations`,
      { method: "POST", json: { contact_id: contactId } },
    );
  } catch (error) {
    return failure(error, "/inbox");
  }

  revalidatePath("/inbox");
  redirect(`/inbox/${conversation.id}`);
}
