"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { deleteDocument } from "@/lib/knowledge-actions";
import type { FormState } from "@/lib/form-state";
import type { KnowledgeDocument } from "@/lib/types";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Delete this document
    </Button>
  );
}

/**
 * Remove one document.
 *
 * No typed confirmation, unlike deleting a source. One document is a small,
 * recoverable mistake -- paste it again -- where a source takes everything
 * in it, and a confirmation on both would train people to type past the one
 * that matters.
 */
export function DeleteDocument({
  workspaceId,
  document,
}: {
  workspaceId: string;
  document: KnowledgeDocument;
}) {
  const [state, action] = useActionState<FormState, FormData>(deleteDocument, null);

  return (
    <form action={action} className="grid gap-2 border-t pt-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="document_id" value={document.id} />

      <FormError>{state?.error}</FormError>

      <p className="text-muted-foreground text-sm">
        The assistant stops being able to retrieve anything from it.
      </p>

      <DeleteButton />
    </form>
  );
}
