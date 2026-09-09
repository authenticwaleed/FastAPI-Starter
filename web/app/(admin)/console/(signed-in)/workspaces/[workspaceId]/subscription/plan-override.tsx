"use client";

import { useActionState } from "react";

import { ConsoleLink } from "@/components/console/console-link";
import { Refused } from "@/components/console/refused";
import { FieldError, SubmitButton } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { day } from "@/lib/console-labels";
import type { FormState } from "@/lib/form-state";
import { grantPlanOverride, removePlanOverride } from "@/lib/platform-actions";
import type { PlanTier } from "@/lib/types";

const PLANS: PlanTier[] = ["starter", "growth", "business"];

/**
 * Granting a plan nobody is paying for, and taking it back.
 *
 * A pilot, a comp, an enterprise contract invoiced offline. It outranks
 * the subscription and survives every webhook, which is why it is a row
 * of its own at the API rather than a value written onto the subscription
 * -- that would revert on the next delivery, silently.
 *
 * **What this screen cannot show.** There is no route that reads the
 * current grant: the API returns one when it is made and at no other
 * time. So a grant made last month is not on this page, and this page
 * does not guess at one from the gap between the resolved plan and the
 * subscription's -- that gap is also what a cancelled subscription looks
 * like, and inventing an answer from it would be the client computing
 * something the API can answer (§7). The platform log has the rows; an
 * endpoint that answers "what is granted here" belongs in the API's plan.
 *
 * `forever` is rendered as a warning rather than a refusal, which is the
 * API's own intent: a comp somebody negotiated has no natural end, so
 * requiring a date would mean inventing one -- and a grant with no date
 * is a plan nothing ever takes away, which is worth being told about
 * rather than discovering two years later on a revenue report.
 */
export function PlanOverrideControls({ workspaceId }: { workspaceId: string }) {
  const [grantState, grant] = useActionState<FormState, FormData>(
    grantPlanOverride,
    null,
  );
  const [removeState, remove] = useActionState<FormState, FormData>(
    removePlanOverride,
    null,
  );

  const granted = grantState?.override;

  return (
    <div className="grid gap-4">
      <Refused state={grantState} />
      <Refused state={removeState} />

      {granted ? (
        <div
          className={`grid gap-1 rounded-md border px-3 py-2.5 text-sm ${
            granted.forever ? "border-amber-500/60 bg-amber-500/5" : ""
          }`}
          data-testid="granted-override"
          data-forever={granted.forever ? "" : undefined}
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">Granted {granted.plan}</span>
            {granted.forever ? (
              <Badge variant="outline" data-testid="forever-flag">
                no expiry
              </Badge>
            ) : (
              <span className="text-muted-foreground text-xs">
                until {day(granted.expires_at as string)}
              </span>
            )}
            {granted.applies ? null : <Badge variant="outline">not in force</Badge>}
          </div>

          <p className="text-muted-foreground text-xs">
            {granted.forever
              ? "Nothing will ever take this away. Somebody has to remember it exists."
              : "It lapses on its own, and the provider's word applies again."}
          </p>
        </div>
      ) : null}

      {removeState?.done ? (
        <p className="text-muted-foreground text-sm" data-testid="override-removed">
          Any granted plan is gone. The provider&rsquo;s word applies again — or
          the free plan, if there is no subscription.
        </p>
      ) : null}

      <form action={grant} className="grid max-w-xl gap-4">
        <input type="hidden" name="workspace_id" value={workspaceId} />

        <div className="grid gap-2">
          <Label htmlFor="plan">Plan to grant</Label>
          <select
            id="plan"
            name="plan"
            defaultValue="growth"
            className="border-input bg-background h-8 w-48 rounded-md border px-2 text-sm shadow-xs"
          >
            {PLANS.map((plan) => (
              <option key={plan} value={plan}>
                {plan}
              </option>
            ))}
          </select>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="reason">Why</Label>
          <Textarea
            id="reason"
            name="reason"
            required
            minLength={10}
            maxLength={500}
            rows={2}
            placeholder="Six-month pilot agreed with them on 3 March, invoiced offline"
          />
          <FieldError>{grantState?.fields?.reason}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="expires_at">Until (optional)</Label>
          <Input id="expires_at" name="expires_at" type="date" className="h-8 w-44" />
          <p className="text-muted-foreground text-xs">
            Leaving this empty is allowed and is flagged rather than refused. A
            grant with no date is a plan nothing will ever take away.
          </p>
          <FieldError>{grantState?.fields?.expires_at}</FieldError>
        </div>

        <SubmitButton className="w-fit">Grant this plan</SubmitButton>
      </form>

      <form action={remove} className="flex flex-wrap items-center gap-3">
        <input type="hidden" name="workspace_id" value={workspaceId} />
        <Button type="submit" variant="ghost" size="sm">
          Remove any granted plan
        </Button>
        <span className="text-muted-foreground text-xs">
          Harmless if there is none — the state somebody wanted already holds.
        </span>
      </form>

      <p className="text-muted-foreground text-xs">
        A grant made earlier is not shown here: the API returns one when it is
        made and at no other time.{" "}
        <ConsoleLink
          href={`/console/audit?workspace_id=${workspaceId}`}
          className="underline underline-offset-4"
        >
          The platform log
        </ConsoleLink>{" "}
        has the rows, with the plan and the reason.
      </p>
    </div>
  );
}
