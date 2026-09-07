import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateOrder } from "./create-order";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { listContactsForOrders, listOrders } from "@/lib/catalogue";
import { money } from "@/lib/money";
import type { Member, OrderStatus, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Orders" };

const MAY_HANDLE_CUSTOMERS = ["owner", "admin", "agent"];

const STATUSES: OrderStatus[] = [
  "pending",
  "confirmed",
  "shipped",
  "delivered",
  "cancelled",
  "refunded",
];

function tab(active: boolean) {
  return active
    ? "font-medium underline underline-offset-4"
    : "text-muted-foreground underline-offset-4 hover:underline";
}

function when(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export default async function OrdersPage({
  searchParams,
}: {
  searchParams: Promise<{ search?: string; status?: string; page?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { search, status, page: rawPage } = await searchParams;

  const page = Math.max(1, Number(rawPage ?? 1) || 1);
  const filter = STATUSES.includes(status as OrderStatus)
    ? (status as OrderStatus)
    : null;

  const [orders, contacts, user, members] = await Promise.all([
    listOrders(workspace.id, { page, search: search ?? null, status: filter }),
    listContactsForOrders(workspace.id),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const canWrite =
    mine !== undefined &&
    MAY_HANDLE_CUSTOMERS.includes(mine.role) &&
    workspace.status === "active";

  const names = new Map(
    contacts.items.map((contact) => [
      contact.id,
      contact.name ?? contact.phone_number,
    ]),
  );

  const lastPage = Math.max(1, Math.ceil(orders.total / orders.page_size));
  const keep = search ? `&search=${encodeURIComponent(search)}` : "";

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Orders</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            What {workspace.name}&rsquo;s customers have bought.
          </p>
        </div>

        <form action="/orders">
          <Input
            type="search"
            name="search"
            defaultValue={search ?? ""}
            placeholder="Order number"
            className="h-8 w-56"
            maxLength={128}
            aria-label="Search orders"
          />
        </form>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-y py-3 text-sm">
        <span className="text-muted-foreground text-xs uppercase">Status</span>
        <Link href={`/orders?${keep.slice(1)}`} className={tab(filter === null)}>
          All
        </Link>
        {STATUSES.map((value) => (
          <Link
            key={value}
            href={`/orders?status=${value}${keep}`}
            className={tab(filter === value)}
          >
            {value}
          </Link>
        ))}
      </div>

      {orders.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          {search || filter ? "Nothing matches that." : "No orders yet."}
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="order-list">
          {orders.items.map((order) => (
            <li key={order.id} data-status={order.status}>
              <Link
                href={`/orders/${order.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {order.order_number ?? "No order number"}
                </span>

                <span className="text-muted-foreground truncate text-sm">
                  {names.get(order.contact_id) ?? "A contact"}
                </span>

                <span className="text-muted-foreground text-xs">
                  {when(order.placed_at ?? order.created_at)}
                </span>

                <span className="text-sm tabular-nums">
                  {money(order.total, order.currency)}
                </span>

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
              </Link>
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage} · {orders.total} in total
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/orders?page=${page - 1}${keep}`}
                className="underline underline-offset-4"
              >
                Previous
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/orders?page=${page + 1}${keep}`}
                className="underline underline-offset-4"
              >
                Next
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}

      {canWrite ? (
        <CreateOrder workspaceId={workspace.id} contacts={contacts.items} />
      ) : null}
    </div>
  );
}
