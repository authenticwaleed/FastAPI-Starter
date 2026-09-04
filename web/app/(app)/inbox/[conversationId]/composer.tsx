"use client";

import { useActionState, useEffect, useRef } from "react";
import { useFormStatus } from "react-dom";

import { FieldError, FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { sendMessage } from "@/lib/conversation-actions";
import type { FormState } from "@/lib/form-state";
import type { Conversation } from "@/lib/types";

function SendButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" size="sm" disabled={pending}>
      Send
    </Button>
  );
}

/**
 * The reply box.
 *
 * Never optimistic. A message that appeared in the thread and then turned
 * out not to have been accepted is the one failure an agent cannot recover
 * from: they have already moved on believing the customer was answered.
 *
 * 4096 characters because that is WhatsApp's own limit for a text body.
 * Enforcing it here means somebody finds out while they are still writing,
 * rather than after pressing send.
 */
export function Composer({
  workspaceId,
  conversation,
}: {
  workspaceId: string;
  conversation: Conversation;
}) {
  const [state, action] = useActionState<FormState, FormData>(sendMessage, null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    // Clear only on a send that worked. A failed one keeps what was typed,
    // because retyping a paragraph is the second thing that goes wrong
    // after the send that did not land.
    if (state?.done && box.current) box.current.value = "";
  }, [state]);

  return (
    <form action={action} className="grid gap-2">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="conversation_id" value={conversation.id} />

      <FormError>{state?.stale ? undefined : state?.error}</FormError>

      {state?.stale ? (
        <p className="text-muted-foreground text-sm" role="status">
          {state.error} The thread has been refreshed.
        </p>
      ) : null}

      <Textarea
        ref={box}
        name="text"
        rows={3}
        maxLength={4096}
        placeholder={`Reply to ${conversation.contact.name ?? conversation.contact.phone_number}`}
        aria-label="Your reply"
        required
      />
      <FieldError>{state?.fields?.text}</FieldError>

      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-xs">
          Sends on WhatsApp. Up to 4096 characters.
        </p>
        <SendButton />
      </div>
    </form>
  );
}
