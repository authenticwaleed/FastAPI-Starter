import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateOrder } from "./create-order";
import { EmptyState } from "@/components/empty-state";
import { FilterTabs } from "@/components/filter-tabs";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { listContactsForOrders, listOrders } from "@/lib/catalogue";
import { money } from "@/lib/money";
import { ORDER_TONE } from "@/lib/tones";
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

  const keep = search ? `&search=${encodeURIComponent(search)}` : "";

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Orders"
        description={`What ${workspace.name}’s customers have bought.`}
        actions={
          <form action="/orders">
            <Input
              type="search"
              name="search"
              defaultValue={search ?? ""}
              placeholder="Order number"
              className="w-56"
              maxLength={128}
              aria-label="Search orders"
            />
          </form>
        }
      />

      <FilterTabs
        label="Status"
        options={[
          {
            value: "all",
            label: "All",
            href: `/orders?${keep.slice(1)}`,
            active: filter === null,
          },
          ...STATUSES.map((value) => ({
            value,
            label: value,
            href: `/orders?status=${value}${keep}`,
            active: filter === value,
          })),
        ]}
      />

      {orders.items.length === 0 ? (
        search || filter ? (
          <EmptyState title="Nothing matches that">
            Try a different order number, or clear the status filter.
          </EmptyState>
        ) : (
          <EmptyState title="No orders yet">
            An order is what a conversation turns into. Take one below, or let
            a connected storefront bring them across.
          </EmptyState>
        )
      ) : (
        <ul className="grid gap-2" data-testid="order-list">
          {orders.items.map((order) => (
            <li key={order.id} data-status={order.status}>
              <Link
                href={`/orders/${order.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 row"
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

                <StatusBadge tone={ORDER_TONE[order.status]} status={order.status}>
                  {order.status}
                </StatusBadge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Pagination
        page={page}
        total={orders.total}
        pageSize={orders.page_size}
        noun="orders"
        href={(to) => `/orders?page=${to}${keep}`}
      />

      {canWrite ? (
        <CreateOrder workspaceId={workspace.id} contacts={contacts.items} />
      ) : null}
    </div>
  );
}
