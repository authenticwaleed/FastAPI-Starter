import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { DeleteProduct } from "./delete-product";
import { ProductForm } from "./product-form";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import { readProduct } from "@/lib/catalogue";
import { ApiError } from "@/lib/errors";
import { money } from "@/lib/money";
import type { Member, Product, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Product" };

const MAY_ADMINISTER = ["owner", "admin"];

export default async function ProductPage({
  params,
}: {
  params: Promise<{ productId: string }>;
}) {
  const { productId } = await params;
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let product: Product;

  try {
    product = await readProduct(workspace.id, productId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const [user, members] = await Promise.all([
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  return (
    <div className="grid gap-6">
      <div>
        <Link
          href="/products"
          className="text-muted-foreground text-sm underline-offset-4 hover:underline"
        >
          ← Products
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{product.name}</h1>
          <Badge variant={product.status === "active" ? "default" : "secondary"}>
            {product.status}
          </Badge>
          {product.external_id ? <Badge variant="outline">Synced</Badge> : null}
        </div>
        <p className="text-muted-foreground mt-1 text-sm tabular-nums">
          {/*
            A dash rather than a zero where there is no price. A product
            with none takes its variant's, and printing "0.00" here would
            quote a customer a free item.
          */}
          {money(product.price, product.currency)}
        </p>
      </div>

      {product.variants.length > 0 ? (
        <section className="grid gap-2">
          <h2 className="text-sm font-medium">Variants</h2>
          <ul className="grid gap-2" data-testid="variant-list">
            {product.variants.map((variant) => (
              <li
                key={variant.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2"
              >
                <span className="min-w-0 flex-1 truncate text-sm">
                  {variant.title ?? "Unnamed"}
                </span>
                {variant.sku ? (
                  <span className="text-muted-foreground font-mono text-xs">
                    {variant.sku}
                  </span>
                ) : null}
                <span className="text-sm tabular-nums">
                  {money(variant.price ?? product.price, product.currency)}
                </span>
                <span className="text-muted-foreground text-xs tabular-nums">
                  {variant.stock_quantity === null
                    ? // Not zero. Null means this business does not track
                      // stock, and "0 in stock" would be a different claim.
                      "Stock not tracked"
                    : `${variant.stock_quantity} in stock`}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <ProductForm
        workspaceId={workspace.id}
        product={product}
        canEdit={administers}
      />

      {administers ? (
        <DeleteProduct workspaceId={workspace.id} product={product} />
      ) : null}
    </div>
  );
}
