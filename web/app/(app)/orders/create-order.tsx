"use client";

import Link from "next/link";
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
import { Textarea } from "@/components/ui/textarea";
import { createOrder } from "@/lib/order-actions";
import type { FormState } from "@/lib/form-state";
import type { Contact } from "@/lib/types";

/**
 * Take an order.
 *
 * The contact is picked, never described. An order is always for somebody
 * the workspace already knows, and creating a contact by side effect here
 * would be a second, quieter path into the contacts table with none of its
 * rules -- which is the API's reasoning and a good one.
 */
export function CreateOrder({
  workspaceId,
  contacts,
}: {
  workspaceId: string;
  contacts: Contact[];
}) {
  const [state, action] = useActionState<FormState, FormData>(createOrder, null);

  if (contacts.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Take an order</h2>
          </CardTitle>
          <CardDescription>
            An order belongs to a contact, and there are none yet.{" "}
            <Link href="/contacts" className="underline underline-offset-4">
              Add one first
            </Link>
            .
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Take an order</h2>
        </CardTitle>
        <CardDescription>
          Recorded against a contact. Confirming it later is what tells them
          — if order confirmation is switched on for this workspace.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-2xl gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <FormError>{state?.error}</FormError>

          <div className="grid gap-2">
            <Label htmlFor="order-contact">Customer</Label>
            <select
              id="order-contact"
              name="contact_id"
              className="border-input bg-background h-9 rounded-md border px-2 text-sm"
              required
            >
              {contacts.map((contact) => (
                <option key={contact.id} value={contact.id}>
                  {contact.name ?? contact.phone_number}
                </option>
              ))}
            </select>
            <FieldError>{state?.fields?.contact_id}</FieldError>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="grid gap-2">
              <Label htmlFor="order-number">Order number</Label>
              <Input
                id="order-number"
                name="order_number"
                maxLength={64}
                className="font-mono"
              />
              <FieldError>{state?.fields?.order_number}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="order-currency">Currency</Label>
              <Input
                id="order-currency"
                name="currency"
                maxLength={3}
                className="uppercase"
                placeholder="USD"
              />
              <FieldError>{state?.fields?.currency}</FieldError>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            {(
              [
                ["subtotal", "Subtotal"],
                ["shipping_total", "Shipping"],
                ["total", "Total"],
              ] as const
            ).map(([name, label]) => (
              <div key={name} className="grid gap-2">
                <Label htmlFor={`order-${name}`}>{label}</Label>
                {/*
                  `inputMode` rather than `type="number"`: some browsers
                  hand back a value the platform has already rounded, and
                  the API takes a decimal string this must not disturb.
                */}
                <Input
                  id={`order-${name}`}
                  name={name}
                  inputMode="decimal"
                  pattern="[0-9]*\.?[0-9]*"
                  className="tabular-nums"
                />
                <FieldError>{state?.fields?.[name]}</FieldError>
              </div>
            ))}
          </div>

          <div className="grid gap-2">
            <Label htmlFor="order-address">Shipping address</Label>
            <Textarea id="order-address" name="shipping_address" rows={3} />
          </div>

          <SubmitButton className="w-fit">Record order</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
