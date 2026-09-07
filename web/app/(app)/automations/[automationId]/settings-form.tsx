"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FieldError, SubmitButton } from "@/components/form";
import { Refusal } from "@/components/refusal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  DEFAULTS,
  PLACEHOLDERS,
  settingList,
  settingNumber,
  settingString,
} from "@/lib/automations";
import { deleteAutomation, updateAutomation } from "@/lib/automation-actions";
import type { FormState } from "@/lib/form-state";
import type { Automation } from "@/lib/types";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Delete this automation
    </Button>
  );
}

function Placeholders({ items }: { items: string[] | undefined }) {
  if (!items || items.length === 0) return null;

  return (
    <p className="text-muted-foreground text-xs">
      {/*
        A fixed list rather than an expression language, which is the same
        decision the API makes about workflows: a business writes a
        sentence, not a program. Naming them saves everybody guessing.
      */}
      You can use {items.map((item) => <code key={item}>{item}</code>)} in the
      message.
    </p>
  );
}

/**
 * What one automation says and when.
 *
 * Editable on any plan. Only switching a *new* one on is gated, so a
 * business whose plan lapsed can still correct the wording of a message
 * its customers are receiving — which is not a feature so much as the
 * absence of a trap.
 */
export function SettingsForm({
  workspaceId,
  automation,
  canManage,
}: {
  workspaceId: string;
  automation: Automation;
  canManage: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(
    updateAutomation,
    null,
  );
  const [removeState, remove] = useActionState<FormState, FormData>(
    deleteAutomation,
    null,
  );

  const settings = automation.definition;

  return (
    <div className="grid gap-8">
      <form action={action} className="grid max-w-xl gap-4">
        <input type="hidden" name="workspace_id" value={workspaceId} />
        <input type="hidden" name="automation_id" value={automation.id} />
        <input type="hidden" name="kind" value={automation.kind} />

        <Refusal state={state} />

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
            defaultValue={automation.name}
            maxLength={120}
            disabled={!canManage}
          />
          <FieldError>{state?.fields?.name}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="status">Runs</Label>
          <select
            id="status"
            name="status"
            defaultValue={automation.status}
            className="border-input bg-background h-9 rounded-md border px-2 text-sm"
            disabled={!canManage}
          >
            <option value="enabled">Yes</option>
            <option value="disabled">No — switched off</option>
          </select>
        </div>

        {automation.kind === "order_confirmation" ? (
          <div className="grid gap-2">
            <Label htmlFor="template">What to send</Label>
            <Textarea
              id="template"
              name="template"
              rows={3}
              maxLength={1000}
              defaultValue={settingString(
                settings,
                "template",
                DEFAULTS.order_confirmation.template,
              )}
              disabled={!canManage}
            />
            <Placeholders items={PLACEHOLDERS.order_confirmation} />
            <FieldError>{state?.fields?.template}</FieldError>
          </div>
        ) : null}

        {automation.kind === "human_handoff" ? (
          <>
            <div className="grid gap-2">
              <Label htmlFor="keywords">Words that mean fetch a person</Label>
              <Textarea
                id="keywords"
                name="keywords"
                rows={6}
                defaultValue={settingList(
                  settings,
                  "keywords",
                  [...DEFAULTS.human_handoff.keywords],
                ).join("\n")}
                disabled={!canManage}
                className="font-mono text-sm"
              />
              <p className="text-muted-foreground text-xs">
                {/*
                  A list rather than a confidence score, and one per line.
                  The assistant already hands over when it cannot answer;
                  this is for the customer who is not asking a question at
                  all -- who is angry, or has said "refund".
                */}
                One per line. The assistant already hands over when it cannot
                answer — this is for somebody who is not asking a question.
              </p>
              <FieldError>{state?.fields?.keywords}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="acknowledgement">Say first (optional)</Label>
              <Textarea
                id="acknowledgement"
                name="acknowledgement"
                rows={2}
                maxLength={1000}
                defaultValue={settingString(
                  settings,
                  "acknowledgement",
                  DEFAULTS.human_handoff.acknowledgement,
                )}
                disabled={!canManage}
              />
              <p className="text-muted-foreground text-xs">
                Sent before the handoff so the customer is not left in
                silence. Leave it empty to say nothing.
              </p>
              <FieldError>{state?.fields?.acknowledgement}</FieldError>
            </div>
          </>
        ) : null}

        {automation.kind === "unanswered_lead_followup" ? (
          <>
            <div className="grid gap-2">
              <Label htmlFor="after_hours">Wait this many hours</Label>
              <Input
                id="after_hours"
                name="after_hours"
                inputMode="numeric"
                defaultValue={String(
                  settingNumber(
                    settings,
                    "after_hours",
                    DEFAULTS.unanswered_lead_followup.after_hours,
                  ),
                )}
                className="w-32 tabular-nums"
                disabled={!canManage}
              />
              <p className="text-muted-foreground text-xs">
                Between 1 and 168. Each conversation is nudged once ever, not
                once per sweep.
              </p>
              <FieldError>{state?.fields?.after_hours}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="template">What to send</Label>
              <Textarea
                id="template"
                name="template"
                rows={3}
                maxLength={1000}
                defaultValue={settingString(
                  settings,
                  "template",
                  DEFAULTS.unanswered_lead_followup.template,
                )}
                disabled={!canManage}
              />
              <Placeholders items={PLACEHOLDERS.unanswered_lead_followup} />
              <FieldError>{state?.fields?.template}</FieldError>
            </div>
          </>
        ) : null}

        {canManage ? <SubmitButton className="w-fit">Save</SubmitButton> : null}
      </form>

      {canManage ? (
        <form action={remove} className="grid gap-2 border-t pt-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />
          <input type="hidden" name="automation_id" value={automation.id} />

          <Refusal state={removeState} />

          <p className="text-muted-foreground text-sm">
            Switching it off stops it running and keeps the settings.
            Deleting does not keep them.
          </p>

          <DeleteButton />
        </form>
      ) : null}
    </div>
  );
}
