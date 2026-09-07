"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Variant } from "@/lib/types";

type Row = { key: string; title: string; sku: string; price: string; stock: string };

function rowsFrom(variants: Variant[]): Row[] {
  return variants.map((variant, index) => ({
    key: `${variant.id}-${index}`,
    title: variant.title ?? "",
    sku: variant.sku ?? "",
    // The string as it arrived. Rendering a price through a number and
    // back is how "19.99" becomes "19.989999999999998" in an input.
    price: variant.price ?? "",
    stock: variant.stock_quantity === null ? "" : String(variant.stock_quantity),
  }));
}

/**
 * The buyable versions of a product.
 *
 * Shared by the create and edit forms because the API takes them the same
 * way in both: nested in the product's own request rather than through
 * endpoints of their own. A product arrives with its sizes, and two round
 * trips to store it would be two chances to store half of it.
 *
 * Submitting replaces the whole set, which is the API's rule, and the form
 * says so out loud. Merging would need a way to match an incoming variant
 * to an existing row, and no rule covers the hand-entered ones that have
 * neither an external id nor a SKU.
 */
export function VariantFields({ variants = [] }: { variants?: Variant[] }) {
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(variants));

  return (
    <fieldset className="grid gap-3">
      <legend className="text-sm font-medium">Variants</legend>

      <p className="text-muted-foreground text-xs">
        Sizes, colours, packs. Saving replaces the whole list with what is
        here — a row removed below is removed from the product.
      </p>

      {rows.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          None. The product is sold as one thing.
        </p>
      ) : null}

      {rows.map((row, index) => (
        <div
          key={row.key}
          data-variant-row=""
          className="grid gap-2 rounded-md border px-3 py-2.5"
        >
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`variant-title-${index}`} className="text-xs">
                Name
              </Label>
              <Input
                id={`variant-title-${index}`}
                name="variant_title"
                defaultValue={row.title}
                maxLength={255}
                className="h-8"
                placeholder="Large"
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor={`variant-sku-${index}`} className="text-xs">
                SKU
              </Label>
              <Input
                id={`variant-sku-${index}`}
                name="variant_sku"
                defaultValue={row.sku}
                maxLength={100}
                className="h-8 font-mono"
              />
            </div>
          </div>

          <div className="grid gap-2 sm:grid-cols-2">
            <div className="grid gap-1.5">
              <Label htmlFor={`variant-price-${index}`} className="text-xs">
                Price
              </Label>
              <Input
                id={`variant-price-${index}`}
                name="variant_price"
                defaultValue={row.price}
                // `inputMode` rather than `type="number"`, which in some
                // browsers hands back a value the platform has already
                // rounded. The API takes a decimal string and this keeps
                // one.
                inputMode="decimal"
                pattern="[0-9]*\.?[0-9]*"
                className="h-8 tabular-nums"
                placeholder="Leave empty to use the product's"
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor={`variant-stock-${index}`} className="text-xs">
                Stock
              </Label>
              <Input
                id={`variant-stock-${index}`}
                name="variant_stock"
                defaultValue={row.stock}
                inputMode="numeric"
                className="h-8 tabular-nums"
                placeholder="Empty if you do not track it"
              />
              {/*
                Empty is not zero. Null means this business does not track
                stock at all, and a form that sent 0 for a blank field
                would tell every customer the item is out of stock.
              */}
            </div>
          </div>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="w-fit"
            onClick={() => setRows(rows.filter((_, at) => at !== index))}
          >
            Remove this variant
          </Button>
        </div>
      ))}

      <Button
        type="button"
        variant="outline"
        size="sm"
        className="w-fit"
        onClick={() =>
          setRows([
            ...rows,
            {
              key: `new-${Date.now()}-${rows.length}`,
              title: "",
              sku: "",
              price: "",
              stock: "",
            },
          ])
        }
      >
        Add a variant
      </Button>
    </fieldset>
  );
}
