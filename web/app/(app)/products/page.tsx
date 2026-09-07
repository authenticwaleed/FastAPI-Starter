import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { CreateProduct } from "./create-product";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { listProducts } from "@/lib/catalogue";
import { money } from "@/lib/money";
import type { Member, ProductStatus, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Products" };

const MAY_ADMINISTER = ["owner", "admin"];
const STATUSES: ProductStatus[] = ["active", "draft", "archived"];

function tab(active: boolean) {
  return active
    ? "font-medium underline underline-offset-4"
    : "text-muted-foreground underline-offset-4 hover:underline";
}

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

  const lastPage = Math.max(1, Math.ceil(products.total / products.page_size));
  const keep = search ? `&search=${encodeURIComponent(search)}` : "";

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Products</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            What {workspace.name} sells. The assistant is told about active
            ones only.
          </p>
        </div>

        <form action="/products">
          <Input
            type="search"
            name="search"
            defaultValue={search ?? ""}
            placeholder="Name or SKU"
            className="h-8 w-56"
            maxLength={255}
            aria-label="Search products"
          />
        </form>
      </div>

      <div className="flex flex-wrap items-center gap-3 border-y py-3 text-sm">
        <span className="text-muted-foreground text-xs uppercase">Status</span>
        <Link href={`/products?${keep.slice(1)}`} className={tab(filter === null)}>
          All
        </Link>
        {STATUSES.map((value) => (
          <Link
            key={value}
            href={`/products?status=${value}${keep}`}
            className={tab(filter === value)}
          >
            {value}
          </Link>
        ))}
      </div>

      {products.items.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm">
          {search ? "Nothing matches that." : "No products yet."}
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="product-list">
          {products.items.map((product) => (
            <li key={product.id} data-status={product.status}>
              <Link
                href={`/products/${product.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
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

                <Badge
                  variant={product.status === "active" ? "default" : "secondary"}
                >
                  {product.status}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage} · {products.total} in total
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/products?page=${page - 1}${keep}`}
                className="underline underline-offset-4"
              >
                Previous
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/products?page=${page + 1}${keep}`}
                className="underline underline-offset-4"
              >
                Next
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}

      {administers ? <CreateProduct workspaceId={workspace.id} /> : null}
    </div>
  );
}
