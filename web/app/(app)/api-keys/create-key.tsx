"use client";

import { useActionState, useState } from "react";

import { CopyField } from "@/components/copy";
import { FieldError, SubmitButton } from "@/components/form";
import { Refusal } from "@/components/refusal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createApiKey } from "@/lib/api-key-actions";
import type { FormState } from "@/lib/form-state";
import type { ApiKeyCreated } from "@/lib/types";

/**
 * The key, shown once.
 *
 * Nothing stored can reproduce it, so this is the only moment it exists
 * anywhere a person can reach. That is why it cannot be dismissed by
 * accident: there is no close button in a corner, no click-outside, and no
 * escape key. The only way past it is a checkbox saying it has been saved
 * and then a button — two deliberate acts, because the cost of getting
 * this wrong is a key somebody has to make again and a deployment that
 * fails at three in the morning.
 */
function TheKey({ created, onDone }: { created: ApiKeyCreated; onDone: () => void }) {
  const [saved, setSaved] = useState(false);

  return (
    <div
      className="border-primary grid gap-3 rounded-md border-2 px-4 py-4"
      role="alertdialog"
      aria-label="Your new API key"
      data-testid="key-reveal"
    >
      <div className="grid gap-1">
        <h3 className="font-medium">Copy this key now</h3>
        <p className="text-muted-foreground text-sm">
          It is shown this once. We store only a fingerprint of it, so
          nobody — including us — can show it to you again. If it is lost,
          the way back is a new key.
        </p>
      </div>

      <CopyField value={created.key} mono data-testid="api-key-value" />

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={saved}
          onChange={(event) => setSaved(event.target.checked)}
          className="mt-0.5"
          data-testid="key-saved"
        />
        <span>I have saved this key somewhere safe.</span>
      </label>

      <Button
        type="button"
        size="sm"
        className="w-fit"
        disabled={!saved}
        onClick={onDone}
      >
        Done
      </Button>
    </div>
  );
}

/**
 * Make a key.
 *
 * Plan-gated at the API, so the refusal is the shared upgrade prompt.
 * Revoking is not gated and lives on the list below — a workspace that
 * loses API access must still be able to turn off the keys it has.
 */
export function CreateKey({
  workspaceId,
  included,
}: {
  workspaceId: string;
  included: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(createApiKey, null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  const created = state?.apiKey;
  const showing = created && created.id !== dismissed ? created : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Create a key</h2>
        </CardTitle>
        <CardDescription>
          For your own software to reach this workspace. A key addresses one
          workspace and carries no person&rsquo;s permissions.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        {showing ? (
          <TheKey created={showing} onDone={() => setDismissed(showing.id)} />
        ) : null}

        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <Refusal state={state} />

          {!included ? (
            <Alert variant="info" role="status" data-testid="not-in-plan">
              <AlertDescription>
                Your plan does not include API access. Keys you already have
                go on working until you revoke them.
              </AlertDescription>
            </Alert>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="key-name">What is it for</Label>
            <Input
              id="key-name"
              name="name"
              maxLength={100}
              placeholder="Staging server"
              required
            />
            <FieldError>{state?.fields?.name}</FieldError>
            <p className="text-muted-foreground text-xs">
              A name you will recognise in six months.
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="expires">Expires after (days)</Label>
            <Input
              id="expires"
              name="expires_in_days"
              inputMode="numeric"
              placeholder="Leave empty for no expiry"
              className="w-56 tabular-nums"
            />
            <FieldError>{state?.fields?.expires_in_days}</FieldError>
            <p className="text-muted-foreground text-xs">
              {/*
                Offered rather than imposed, matching the API: a key that
                stops working on a date nobody remembers choosing is an
                outage in somebody else's system.
              */}
              Up to 730. Empty means it never expires, which is a choice
              rather than an oversight.
            </p>
          </div>

          <SubmitButton className="w-fit">Create key</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
