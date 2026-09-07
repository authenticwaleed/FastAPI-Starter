import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ConfirmOrder } from "./confirm-order";
import { OrderForm } from "./order-form";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { readOrder } from "@/lib/catalogue";
import { ApiError } from "@/lib/errors";
import { readContact } from "@/lib/inbox";
import { money } from "@/lib/money";
import type { Contact, Member, Order, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Order" };

const MAY_HANDLE_CUSTOMERS = ["owner", "admin", "agent"];

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default async function OrderPage({
  params,
}: {
  params: Promise<{ orderId: string }>;
}) {
  const { orderId } = await params;
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let order: Order;

  try {
    order = await readOrder(workspace.id, orderId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const [user, members] = await Promise.all([
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  let contact: Contact | null = null;

  try {
    contact = await readContact(workspace.id, order.contact_id);
  } catch (error) {
    // A contact removed since the order was taken is a gap in the heading,
    // not a reason to fail the page.
    if (!(error instanceof ApiError)) throw error;
  }

  const mine = members.find((member) => member.user_id === user.id);
  const canWrite =
    mine !== undefined &&
    MAY_HANDLE_CUSTOMERS.includes(mine.role) &&
    workspace.status === "active";

  return (
    <div className="grid gap-6">
      <div>
        <Link
          href="/orders"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          ← Orders
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            {order.order_number ?? "Order"}
          </h1>
          <Badge
            variant={
              order.status === "cancelled" || order.status === "refunded"
                ? "outline"
                : order.status === "pending"
                  ? "secondary"
                  : "default"
            }
          >
            {order.status}
          </Badge>
        </div>
        <p className="text-muted-foreground mt-1 text-sm">
          {contact ? (
            <Link
              href={`/contacts/${contact.id}`}
              className="underline underline-offset-4"
            >
              {contact.name ?? contact.phone_number}
            </Link>
          ) : (
            "The contact has been removed"
          )}{" "}
          · {when(order.placed_at ?? order.created_at)}
        </p>
      </div>

      <dl className="grid gap-3 rounded-md border px-3 py-3 sm:grid-cols-3">
        {(
          [
            ["Subtotal", order.subtotal],
            ["Shipping", order.shipping_total],
            ["Total", order.total],
          ] as const
        ).map(([label, amount]) => (
          <div key={label} className="grid gap-0.5">
            <dt className="text-muted-foreground text-xs uppercase">{label}</dt>
            {/*
              A dash where the API sent nothing. An order recorded without a
              subtotal has none, and printing "0.00" would state a figure
              nobody entered.
            */}
            <dd className="text-sm tabular-nums">{money(amount, order.currency)}</dd>
          </div>
        ))}
      </dl>

      {canWrite ? (
        <ConfirmOrder workspaceId={workspace.id} order={order} />
      ) : null}

      {order.tracking_number || order.tracking_url ? (
        <p className="text-sm">
          Tracking:{" "}
          {order.tracking_url ? (
            <a
              href={order.tracking_url}
              className="underline underline-offset-4"
              rel="noreferrer noopener"
              target="_blank"
            >
              {order.tracking_number ?? order.tracking_url}
            </a>
          ) : (
            <span className="font-mono">{order.tracking_number}</span>
          )}
        </p>
      ) : null}

      <OrderForm workspaceId={workspace.id} order={order} canEdit={canWrite} />
    </div>
  );
}
