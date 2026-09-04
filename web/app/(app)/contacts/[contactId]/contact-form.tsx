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
import { updateContact } from "@/lib/contact-actions";
import type { FormState } from "@/lib/form-state";
import type { Contact } from "@/lib/types";

/**
 * The profile.
 *
 * The number can be changed, because people change numbers, and it stays
 * unique within the workspace -- so moving a contact onto one another
 * contact already holds is refused. That is a merge, which is a different
 * operation than an edit, and the API is right not to do it by accident.
 */
export function ContactForm({
  workspaceId,
  contact,
}: {
  workspaceId: string;
  contact: Contact;
}) {
  const [state, action] = useActionState<FormState, FormData>(updateContact, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Details</h2>
        </CardTitle>
        <CardDescription>
          What the business knows about this person.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />
          <input type="hidden" name="contact_id" value={contact.id} />

          <FormError>{state?.error}</FormError>

          {state?.done ? (
            <p className="text-muted-foreground text-sm" role="status">
              Saved.
            </p>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="phone_number">Phone number</Label>
            <Input
              id="phone_number"
              name="phone_number"
              type="tel"
              defaultValue={contact.phone_number}
              className="font-mono"
              required
            />
            <FieldError>{state?.fields?.phone_number}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              name="name"
              defaultValue={contact.name ?? ""}
              maxLength={150}
            />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                name="email"
                type="email"
                defaultValue={contact.email ?? ""}
              />
              <FieldError>{state?.fields?.email}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="status">Status</Label>
              <select
                id="status"
                name="status"
                defaultValue={contact.status}
                className="border-input bg-background h-9 rounded-md border px-2 text-sm"
              >
                <option value="lead">Lead</option>
                <option value="customer">Customer</option>
                <option value="blocked">Blocked</option>
              </select>
            </div>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="source">Source</Label>
            <Input
              id="source"
              name="source"
              defaultValue={contact.source ?? ""}
              maxLength={50}
              placeholder="whatsapp, shopify, walk-in"
            />
            <FieldError>{state?.fields?.source}</FieldError>
          </div>

          <SubmitButton className="w-fit">Save</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
