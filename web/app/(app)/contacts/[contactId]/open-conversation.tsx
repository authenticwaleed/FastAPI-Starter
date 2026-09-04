"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Button } from "@/components/ui/button";
import { openConversation } from "@/lib/conversation-actions";
import type { FormState } from "@/lib/form-state";
import type { Contact } from "@/lib/types";

function OpenButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" size="sm" variant="outline" disabled={pending}>
      Open a conversation
    </Button>
  );
}

/**
 * Start a thread with this person.
 *
 * `conversation_already_open` is the refusal to expect, and it is not a
 * fault: a contact may have one open thread at a time, so pressing this
 * when one exists means somebody else got there first. It says so quietly
 * and the list above it has already been refreshed.
 */
export function OpenConversation({
  workspaceId,
  contact,
}: {
  workspaceId: string;
  contact: Contact;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    openConversation,
    null,
  );

  return (
    <div className="flex items-center gap-3">
      {state?.error ? (
        <span
          className={state.stale ? "text-muted-foreground text-sm" : "text-destructive text-sm"}
          role={state.stale ? "status" : "alert"}
        >
          {state.error}
        </span>
      ) : null}

      <form action={action}>
        <input type="hidden" name="workspace_id" value={workspaceId} />
        <input type="hidden" name="contact_id" value={contact.id} />
        <OpenButton />
      </form>
    </div>
  );
}
