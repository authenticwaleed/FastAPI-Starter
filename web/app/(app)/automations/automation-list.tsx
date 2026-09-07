"use client";

import Link from "next/link";
import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { Refusal } from "@/components/refusal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { runDue, setAutomationStatus } from "@/lib/automation-actions";
import { STATUS_LABEL, TRIGGER_LABEL, specFor } from "@/lib/automations";
import type { FormState } from "@/lib/form-state";
import type { Automation } from "@/lib/types";

function Toggling({ children }: { children: string }) {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="outline" size="sm" disabled={pending}>
      {children}
    </Button>
  );
}

/**
 * What is switched on, and a way to switch it off.
 *
 * Turning one off is not plan-gated and must not be hidden when a plan
 * lapses. A business that downgrades and then cannot stop an automation
 * from messaging its customers has been locked in by its own
 * cancellation, which is the worst thing this screen could do.
 */
export function AutomationList({
  workspaceId,
  automations,
  canManage,
}: {
  workspaceId: string;
  automations: Automation[];
  canManage: boolean;
}) {
  const [toggleState, toggle] = useActionState<FormState, FormData>(
    setAutomationStatus,
    null,
  );
  const [sweepState, sweep] = useActionState<FormState, FormData>(runDue, null);

  const scheduled = automations.some(
    (automation) => automation.trigger_type === "schedule",
  );

  if (automations.length === 0) {
    return (
      <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
        None switched on yet.
      </p>
    );
  }

  return (
    <section className="grid gap-3">
      <Refusal state={toggleState ?? sweepState} />

      <ul className="grid gap-2" data-testid="automation-list">
        {automations.map((automation) => {
          const on = automation.status === "enabled";

          return (
            <li
              key={automation.id}
              data-kind={automation.kind}
              data-status={automation.status}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border px-3 py-2.5"
            >
              <div className="grid min-w-0 flex-1 gap-0.5">
                <Link
                  href={`/automations/${automation.id}`}
                  className="text-sm font-medium underline-offset-4 hover:underline"
                >
                  {automation.name}
                </Link>
                <span className="text-muted-foreground text-xs">
                  {TRIGGER_LABEL[automation.trigger_type]} ·{" "}
                  {specFor(automation.kind).summary}
                </span>
              </div>

              <Badge variant={on ? "default" : "outline"}>
                {STATUS_LABEL[automation.status]}
              </Badge>

              {canManage ? (
                <form action={toggle}>
                  <input type="hidden" name="workspace_id" value={workspaceId} />
                  <input type="hidden" name="automation_id" value={automation.id} />
                  <input
                    type="hidden"
                    name="status"
                    value={on ? "disabled" : "enabled"}
                  />
                  <Toggling>{on ? "Turn off" : "Turn on"}</Toggling>
                </form>
              ) : null}
            </li>
          );
        })}
      </ul>

      {canManage && scheduled ? (
        <div className="flex flex-wrap items-center gap-3">
          <form action={sweep}>
            <input type="hidden" name="workspace_id" value={workspaceId} />
            <Toggling>Run what is due now</Toggling>
          </form>

          {sweepState?.sweep ? (
            <span className="text-muted-foreground text-sm" role="status">
              {/*
                Both numbers, because the gap is the useful one: it is how
                much the sweep looked at and correctly left alone.
              */}
              Looked at {sweepState.sweep.considered}, acted on{" "}
              {sweepState.sweep.ran}.
            </span>
          ) : (
            <span className="text-muted-foreground text-xs">
              One of these runs on a schedule. Nothing schedules it yet, so
              this is the button that stands in for that.
            </span>
          )}
        </div>
      ) : null}
    </section>
  );
}
