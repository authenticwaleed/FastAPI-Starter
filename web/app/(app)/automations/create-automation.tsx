"use client";

import Link from "next/link";
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refusal } from "@/components/refusal";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { createAutomation } from "@/lib/automation-actions";
import { AUTOMATIONS } from "@/lib/automations";
import type { FormState } from "@/lib/form-state";
import type { AutomationKind } from "@/lib/types";

function AddButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      Switch it on
    </Button>
  );
}

/**
 * The ones not switched on yet.
 *
 * A fixed list rather than a builder, which is the API's shape: what a
 * business chooses is when an automation runs and what it says, not what
 * it does. Switching one on takes every default; the settings come after.
 *
 * On a plan that does not include automations this says so up front rather
 * than waiting for the 402. The refusal still renders if somebody presses
 * anyway -- the API decides, and a screen that only warned would be
 * guessing -- but nobody should have to press a button to find out.
 */
export function CreateAutomation({
  workspaceId,
  existing,
  included,
}: {
  workspaceId: string;
  existing: AutomationKind[];
  included: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    createAutomation,
    null,
  );

  const available = AUTOMATIONS.filter((spec) => !existing.includes(spec.kind));

  if (available.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        All three are set up. Turning one off is on the list above.
      </p>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Switch on an automation</h2>
        </CardTitle>
        <CardDescription>
          Each one starts with sensible wording you can change afterwards.
        </CardDescription>
      </CardHeader>

      <CardContent className="grid gap-4">
        <Refusal state={state} />

        {!included ? (
          <p
            className="text-muted-foreground rounded-md border px-3 py-2 text-sm"
            data-testid="not-in-plan"
          >
            Your plan does not include automations.{" "}
            <Link href="/billing" className="underline underline-offset-4">
              See what each plan includes
            </Link>
            .
          </p>
        ) : null}

        <ul className="grid gap-2">
          {available.map((spec) => (
            <li
              key={spec.kind}
              data-kind={spec.kind}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border px-3 py-2.5"
            >
              <div className="grid min-w-0 flex-1 gap-0.5">
                <span className="text-sm font-medium">{spec.name}</span>
                <span className="text-muted-foreground text-xs">
                  {spec.when} · {spec.summary}
                </span>
              </div>

              <form action={action}>
                <input type="hidden" name="workspace_id" value={workspaceId} />
                <input type="hidden" name="kind" value={spec.kind} />
                <AddButton />
              </form>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
