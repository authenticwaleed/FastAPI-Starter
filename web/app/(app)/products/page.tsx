import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateProduct } from "./create-product";
import { EmptyState } from "@/components/empty-state";
import { FilterTabs } from "@/components/filter-tabs";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { listProducts } from "@/lib/catalogue";
import { money } from "@/lib/money";
import { PRODUCT_TONE } from "@/lib/tones";
import type { Member, ProductStatus, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Products" };

const MAY_ADMINISTER = ["owner", "admin"];
const STATUSES: ProductStatus[] = ["active", "draft", "archived"];

export default async function ProductsPage({
  searchParams,
}: {
  searchParams: Promise<{ search?: string; status?: string; page?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { search, status, page: rawPage } = await searchParams;

  const page = Math.max(1, Number(rawPage ?? 1) || 1);
  const filter = STATUSES.includes(status as ProductStatus)
    ? (status as ProductStatus)
    : null;

  const [products, user, members] = await Promise.all([
    listProducts(workspace.id, { page, search: search ?? null, status: filter }),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  const keep = search ? `&search=${encodeURIComponent(search)}` : "";

  return (
    <div className="grid gap-6">
      <PageHeader
        title="Products"
        description={`What ${workspace.name} sells. The assistant is told about active ones only.`}
        actions={
          <form action="/products">
            <Input
              type="search"
              name="search"
              defaultValue={search ?? ""}
              placeholder="Name or SKU"
              className="w-56"
              maxLength={255}
              aria-label="Search products"
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
            href: `/products?${keep.slice(1)}`,
            active: filter === null,
          },
          ...STATUSES.map((value) => ({
            value,
            label: value,
            href: `/products?status=${value}${keep}`,
            active: filter === value,
          })),
        ]}
      />

      {products.items.length === 0 ? (
        search || filter ? (
          <EmptyState title="Nothing matches that">
            Try a different name or SKU, or clear the status filter.
          </EmptyState>
        ) : (
          <EmptyState title="No products yet">
            The assistant answers questions about what you sell, so this is
            what it will be drawing on. Add one below, or connect a storefront.
          </EmptyState>
        )
      ) : (
        <ul className="grid gap-2" data-testid="product-list">
          {products.items.map((product) => (
            <li key={product.id} data-status={product.status}>
              <Link
                href={`/products/${product.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 row"
              >
                {/*
                  A product needs only a name. No SKU, no description and no
                  price is an ordinary row -- somebody sketching a catalogue
                  -- and every one of those has to render without a gap
                  where a value would be.
                */}
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {product.name}
                </span>

                {product.external_id ? (
                  <Badge variant="outline" title="Synced from a storefront">
                    Synced
                  </Badge>
                ) : null}

                <span className="text-muted-foreground text-xs tabular-nums">
                  {product.variants.length} variant
                  {product.variants.length === 1 ? "" : "s"}
                </span>

                <span className="text-sm tabular-nums">
                  {money(product.price, product.currency)}
                </span>

                <StatusBadge tone={PRODUCT_TONE[product.status]} status={product.status}>
                  {product.status}
                </StatusBadge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Pagination
        page={page}
        total={products.total}
        pageSize={products.page_size}
        noun="products"
        href={(to) => `/products?page=${to}${keep}`}
      />

      {administers ? <CreateProduct workspaceId={workspace.id} /> : null}
    </div>
  );
}
