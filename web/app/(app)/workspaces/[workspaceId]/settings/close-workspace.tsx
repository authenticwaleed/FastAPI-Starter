"use client";

import { useActionState } from "react";

import { DangerZone, TypedConfirm } from "@/components/danger-zone";
import { FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { useFormStatus } from "react-dom";
import { closeWorkspace } from "@/lib/workspace-actions";
import type { FormState } from "@/lib/form-state";
import type { Workspace } from "@/lib/types";

function CloseButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" className="w-fit" disabled={pending}>
      Close this workspace
    </Button>
  );
}

/**
 * Owner-only, and recoverable.
 *
 * The confirmation is the workspace's own slug rather than a fixed word,
 * because a phrase that is the same every time is one people learn to type
 * without reading. It is this client's caution and nothing more -- the API
 * asks for no confirmation at all, and the screen does not pretend the
 * typing is authentication.
 *
 * The copy says recoverable because it is: the rows survive and support can
 * restore it. Overstating this would frighten somebody out of an action
 * they can undo.
 */
export function CloseWorkspace({ workspace }: { workspace: Workspace }) {
  const [state, action] = useActionState<FormState, FormData>(closeWorkspace, null);

  return (
    <DangerZone
      title="Close this workspace"
      description="It stops appearing for everyone in it and every address answers as though it is gone. Nothing is deleted — support can restore it for a period afterwards."
    >
      <form action={action} className="grid gap-4">
        <input type="hidden" name="workspace_id" value={workspace.id} />
        <input type="hidden" name="slug" value={workspace.slug} />

        <FormError>{state?.error}</FormError>

        <TypedConfirm
          phrase={workspace.slug}
          error={state?.fields?.confirm}
        />

        <CloseButton />
      </form>
    </DangerZone>
  );
}
