/**
 * Reading the catalogue and the orders against it.
 *
 * The queries only. Formatting money is `lib/money.ts`, which is pure so a
 * client component can import it without dragging `next/headers` along.
 */

import { api } from "@/lib/api";
import type {
  Contact,
  Order,
  OrderStatus,
  Page,
  Product,
  ProductStatus,
} from "@/lib/types";

export const PAGE_SIZE = 20;

export function listProducts(
  workspaceId: string,
  {
    page = 1,
    search = null,
    status = null,
  }: { page?: number; search?: string | null; status?: ProductStatus | null } = {},
) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  });

  if (search) query.set("search", search);
  if (status) query.set("status", status);

  return api<Page<Product>>(`/workspaces/${workspaceId}/products?${query}`);
}

export function readProduct(workspaceId: string, productId: string) {
  return api<Product>(`/workspaces/${workspaceId}/products/${productId}`);
}

export function listOrders(
  workspaceId: string,
  {
    page = 1,
    search = null,
    status = null,
    contactId = null,
  }: {
    page?: number;
    search?: string | null;
    status?: OrderStatus | null;
    contactId?: string | null;
  } = {},
) {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  });

  if (search) query.set("search", search);
  if (status) query.set("status", status);
  if (contactId) query.set("contact_id", contactId);

  return api<Page<Order>>(`/workspaces/${workspaceId}/orders?${query}`);
}

export function readOrder(workspaceId: string, orderId: string) {
  return api<Order>(`/workspaces/${workspaceId}/orders/${orderId}`);
}

/**
 * The contacts an order can be placed for.
 *
 * An order names a contact rather than describing one, so the form picks
 * from people the workspace already knows. One page of a hundred: a
 * business with more than that wants a search box, which is a screen of
 * its own rather than a longer dropdown.
 */
export function listContactsForOrders(workspaceId: string) {
  return api<Page<Contact>>(
    `/workspaces/${workspaceId}/contacts?page=1&page_size=100`,
  );
}
