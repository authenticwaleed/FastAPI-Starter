"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { FormState } from "@/lib/form-state";
import type { Workspace } from "@/lib/types";
import { updateWorkspace } from "@/lib/workspace-actions";

/**
 * What an administrator may change.
 *
 * `slug` is shown and not editable, which mirrors the API: it is absent
 * from the update schema because it ends up in links and in customers'
 * bookmarks, and moving it would break the ones that already exist.
 *
 * `canEdit` disables rather than hides. Somebody who cannot change these
 * still needs to see what they are, and an absent form is a screen that
 * looks broken to the person who has to go and ask an owner about it.
 */
export function SettingsForm({
  workspace,
  canEdit,
}: {
  workspace: Workspace;
  canEdit: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(updateWorkspace, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Settings</h2>
        </CardTitle>
        <CardDescription>
          {canEdit
            ? "The timezone here is the one every report is bucketed in."
            : "Only an owner or an admin can change these."}
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspace.id} />

          <FormError>{state?.error}</FormError>

          {state?.done ? (
            <p className="text-muted-foreground text-sm" role="status">
              Saved.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              name="name"
              defaultValue={workspace.name}
              maxLength={100}
              disabled={!canEdit}
              required
            />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="slug">Address</Label>
            <Input
              id="slug"
              defaultValue={workspace.slug}
              readOnly
              disabled
              className="font-mono"
            />
            <p className="text-muted-foreground text-xs">
              Fixed once created. It is in links that already exist.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="timezone">Timezone</Label>
              <Input
                id="timezone"
                name="timezone"
                defaultValue={workspace.timezone}
                maxLength={64}
                disabled={!canEdit}
              />
              <FieldError>{state?.fields?.timezone}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="default_currency">Currency</Label>
              <Input
                id="default_currency"
                name="default_currency"
                defaultValue={workspace.default_currency}
                maxLength={3}
                className="uppercase"
                disabled={!canEdit}
              />
              <FieldError>{state?.fields?.default_currency}</FieldError>
            </div>
          </div>

          {canEdit ? <SubmitButton className="w-fit">Save</SubmitButton> : null}
        </form>
      </CardContent>
    </Card>
  );
}
