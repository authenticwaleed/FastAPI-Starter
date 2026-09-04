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
import { createContact } from "@/lib/contact-actions";
import type { FormState } from "@/lib/form-state";

/**
 * Add somebody by hand.
 *
 * Only the number is required, which is the API's rule and the right one:
 * this is a product that reaches people on WhatsApp, so a contact without
 * a number is a row nothing can act on. Everything else is what the
 * business happens to know so far.
 */
export function CreateContact({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(createContact, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Add a contact</h2>
        </CardTitle>
        <CardDescription>
          The number is normalised, so one typed with spaces here and the same
          one arriving from WhatsApp are one person.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-md gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <FormError>{state?.error}</FormError>

          <div className="grid gap-2">
            <Label htmlFor="phone_number">Phone number</Label>
            <Input
              id="phone_number"
              name="phone_number"
              type="tel"
              placeholder="+92 300 1234567"
              required
            />
            <FieldError>{state?.fields?.phone_number}</FieldError>
            <p className="text-muted-foreground text-xs">
              International format, including the country code.
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="contact-name">Name</Label>
            <Input id="contact-name" name="name" maxLength={150} />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="contact-email">Email</Label>
              <Input id="contact-email" name="email" type="email" />
              <FieldError>{state?.fields?.email}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="contact-status">Status</Label>
              <select
                id="contact-status"
                name="status"
                defaultValue="lead"
                className="border-input bg-background h-9 rounded-md border px-2 text-sm"
              >
                <option value="lead">Lead</option>
                <option value="customer">Customer</option>
                <option value="blocked">Blocked</option>
              </select>
            </div>
          </div>

          <SubmitButton className="w-fit">Add contact</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
