"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { updateOrder } from "@/lib/order-actions";
import type { FormState } from "@/lib/form-state";
import type { Order, OrderStatus } from "@/lib/types";

const STATUSES: OrderStatus[] = [
  "pending",
  "confirmed",
  "shipped",
  "delivered",
  "cancelled",
  "refunded",
];

/**
 * Record what has changed about an order.
 *
 * No customer field, and that is the API's shape rather than an omission:
 * moving an order to a different person is not an edit, it is a correction
 * of who it was ever for, and doing that through a PATCH nobody notices is
 * how one customer ends up able to ask about another customer's order.
 */
export function OrderForm({
  workspaceId,
  order,
  canEdit,
}: {
  workspaceId: string;
  order: Order;
  canEdit: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(updateOrder, null);

  return (
    <form action={action} className="grid max-w-2xl gap-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="order_id" value={order.id} />

      <FormError>{state?.stale ? undefined : state?.error}</FormError>

      {state?.done ? (
        <p className="text-muted-foreground text-sm" role="status">
          Saved.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="status">Status</Label>
          <select
            id="status"
            name="status"
            defaultValue={order.status}
            className="border-input bg-background h-9 rounded-md border px-2 text-sm"
            disabled={!canEdit}
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <p className="text-muted-foreground text-xs">
            Confirming is its own button below — it records a decision rather
            than an observation.
          </p>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="order_number">Order number</Label>
          <Input
            id="order_number"
            name="order_number"
            defaultValue={order.order_number ?? ""}
            maxLength={64}
            className="font-mono"
            disabled={!canEdit}
          />
          <FieldError>{state?.fields?.order_number}</FieldError>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <div className="grid gap-2">
          <Label htmlFor="currency">Currency</Label>
          <Input
            id="currency"
            name="currency"
            defaultValue={order.currency ?? ""}
            maxLength={3}
            className="uppercase"
            disabled={!canEdit}
          />
        </div>

        {(
          [
            ["subtotal", "Subtotal"],
            ["shipping_total", "Shipping"],
            ["total", "Total"],
          ] as const
        ).map(([name, label]) => (
          <div key={name} className="grid gap-2">
            <Label htmlFor={name}>{label}</Label>
            {/*
              The decimal string exactly as it arrived. Through a number
              and back, "19.99" becomes "19.989999999999998" in the box
              somebody is about to save.
            */}
            <Input
              id={name}
              name={name}
              defaultValue={order[name] ?? ""}
              inputMode="decimal"
              pattern="[0-9]*\.?[0-9]*"
              className="tabular-nums"
              disabled={!canEdit}
            />
            <FieldError>{state?.fields?.[name]}</FieldError>
          </div>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="tracking_number">Tracking number</Label>
          <Input
            id="tracking_number"
            name="tracking_number"
            defaultValue={order.tracking_number ?? ""}
            maxLength={128}
            className="font-mono"
            disabled={!canEdit}
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="tracking_url">Tracking link</Label>
          <Input
            id="tracking_url"
            name="tracking_url"
            type="url"
            defaultValue={order.tracking_url ?? ""}
            maxLength={500}
            disabled={!canEdit}
          />
          <FieldError>{state?.fields?.tracking_url}</FieldError>
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="shipping_address">Shipping address</Label>
        <Textarea
          id="shipping_address"
          name="shipping_address"
          defaultValue={order.shipping_address ?? ""}
          rows={3}
          disabled={!canEdit}
        />
      </div>

      {canEdit ? <SubmitButton className="w-fit">Save</SubmitButton> : null}
    </form>
  );
}
