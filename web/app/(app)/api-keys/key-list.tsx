"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";

import { EmptyState } from "@/components/empty-state";
import { SectionHeader } from "@/components/page-header";
import { Refusal } from "@/components/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { revokeApiKey } from "@/lib/api-key-actions";
import type { FormState } from "@/lib/form-state";
import type { ApiKey } from "@/lib/types";

function RevokeButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Revoke this key
    </Button>
  );
}

function when(value: string | null): string {
  return value
    ? new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" })
    : "—";
}

/**
 * The keys that exist, and a way to stop one.
 *
 * Revoking is not plan-gated and is not hidden when a plan lapses. A
 * workspace that drops off the plan which included API access must still
 * be able to turn off a live credential — otherwise a downgrade leaves
 * keys nobody can revoke, which is the opposite of what a downgrade should
 * cost.
 *
 * A revoked key stays on the list rather than vanishing. "Was there ever a
 * key on that server" is the question this list gets asked after an
 * incident, and one showing only live keys could not answer it.
 */
export function KeyList({
  workspaceId,
  keys,
  canManage,
}: {
  workspaceId: string;
  keys: ApiKey[];
  canManage: boolean;
}) {
  const [state, revoke] = useActionState<FormState, FormData>(revokeApiKey, null);
  const [confirming, setConfirming] = useState<string | null>(null);

  if (keys.length === 0) {
    return (
      <section className="grid gap-3">
        <SectionHeader title="Keys" />
        <EmptyState title="No keys yet">
          A key lets your own software reach this workspace. It is shown once,
          when you create it.
        </EmptyState>
      </section>
    );
  }

  return (
    <section className="grid gap-3">
      <SectionHeader title="Keys" />

      <Refusal state={state} />

      <ul className="grid gap-2" data-testid="key-list">
        {keys.map((key) => {
          const revoked = key.revoked_at !== null;
          const expired =
            key.expires_at !== null && new Date(key.expires_at) < new Date();

          return (
            <li
              key={key.id}
              data-revoked={revoked ? "" : undefined}
              className="grid gap-2 row"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className="text-sm font-medium">{key.name}</span>
                {/*
                  The prefix is what answers "which of these three is on
                  the staging server", which a name chosen in a hurry six
                  months ago does not.
                */}
                <code className="text-muted-foreground font-mono text-xs">
                  {key.key_prefix}…
                </code>

                {revoked ? (
                  <Badge variant="outline">Revoked</Badge>
                ) : expired ? (
                  <Badge variant="outline">Expired</Badge>
                ) : (
                  <Badge variant="default">Live</Badge>
                )}

                {canManage && !revoked ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() =>
                      setConfirming(confirming === key.id ? null : key.id)
                    }
                  >
                    {confirming === key.id ? "Cancel" : "Revoke"}
                  </Button>
                ) : null}
              </div>

              <p className="text-muted-foreground text-xs">
                Created {when(key.created_at)} · Last used{" "}
                {/*
                  Never used is a dash rather than the creation date. A key
                  nothing has ever presented is the interesting case when
                  an integration is not working.
                */}
                {when(key.last_used_at)} · Expires {when(key.expires_at)}
              </p>

              {confirming === key.id ? (
                <form action={revoke} className="grid gap-2 border-t pt-2">
                  <input type="hidden" name="workspace_id" value={workspaceId} />
                  <input type="hidden" name="key_id" value={key.id} />
                  <input type="hidden" name="key_prefix" value={key.key_prefix} />

                  <p className="text-muted-foreground text-xs">
                    Anything using this key stops working immediately. It
                    cannot be un-revoked; a replacement is a new key.
                  </p>

                  <Label htmlFor={`revoke-${key.id}`} className="text-xs">
                    Type <span className="font-mono">{key.key_prefix}</span> to
                    confirm
                  </Label>
                  <Input
                    id={`revoke-${key.id}`}
                    name="confirm"
                    autoComplete="off"
                    className="h-8 font-mono"
                    required
                  />
                  <RevokeButton />
                </form>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
