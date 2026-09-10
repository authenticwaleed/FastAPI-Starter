"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { NativeSelect } from "@/components/ui/native-select";
import { VariantFields } from "@/components/variant-fields";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { updateProduct } from "@/lib/product-actions";
import type { FormState } from "@/lib/form-state";
import type { Product } from "@/lib/types";

/**
 * Edit a product.
 *
 * A synced one is editable here and says where it came from, because the
 * shop is the system of record and the next sync will overwrite whatever
 * is typed. Disabling the form would be wrong -- a business may well want
 * to correct a description before the next sync -- but letting somebody
 * type into it with no warning would be worse.
 */
export function ProductForm({
  workspaceId,
  product,
  canEdit,
}: {
  workspaceId: string;
  product: Product;
  canEdit: boolean;
}) {
  const [state, action] = useActionState<FormState, FormData>(updateProduct, null);

  return (
    <form action={action} className="grid max-w-2xl gap-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="product_id" value={product.id} />

      <FormError>{state?.error}</FormError>

      {state?.done ? (
        <p className="text-muted-foreground text-sm" role="status">
          Saved.
        </p>
      ) : null}

      {product.external_id ? (
        <Alert role="status">
          <AlertDescription>
            This product came from a connected storefront. That shop is the
            system of record, so anything changed here is replaced the next
            time it syncs.
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          name="name"
          defaultValue={product.name}
          maxLength={255}
          disabled={!canEdit}
          required
        />
        <FieldError>{state?.fields?.name}</FieldError>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          name="description"
          defaultValue={product.description ?? ""}
          rows={4}
          disabled={!canEdit}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="grid gap-2">
          <Label htmlFor="price">Price</Label>
          {/*
            The decimal string exactly as the API sent it. Passing it
            through a number and back is how "19.99" becomes
            "19.989999999999998" in the box somebody is about to save.
          */}
          <Input
            id="price"
            name="price"
            defaultValue={product.price ?? ""}
            inputMode="decimal"
            pattern="[0-9]*\.?[0-9]*"
            className="tabular-nums"
            disabled={!canEdit}
          />
          <FieldError>{state?.fields?.price}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="currency">Currency</Label>
          <Input
            id="currency"
            name="currency"
            defaultValue={product.currency ?? ""}
            maxLength={3}
            className="uppercase"
            disabled={!canEdit}
          />
          <FieldError>{state?.fields?.currency}</FieldError>
        </div>

        <div className="grid gap-2">
          <Label htmlFor="status">Status</Label>
          <NativeSelect
            id="status"
            name="status"
            defaultValue={product.status}
            disabled={!canEdit}
          >
            <option value="active">Active</option>
            <option value="draft">Draft</option>
            <option value="archived">Archived</option>
          </NativeSelect>
        </div>
      </div>

      {canEdit ? (
        <>
          <VariantFields variants={product.variants} />
          <SubmitButton className="w-fit">Save</SubmitButton>
        </>
      ) : (
        <VariantsReadOnly product={product} />
      )}
    </form>
  );
}

function VariantsReadOnly({ product }: { product: Product }) {
  if (product.variants.length === 0) return null;

  return (
    <div className="grid gap-2">
      <h3 className="text-sm font-medium">Variants</h3>
      <ul className="grid gap-1">
        {product.variants.map((variant) => (
          <li key={variant.id} className="text-muted-foreground text-sm">
            {variant.title ?? variant.sku ?? "Unnamed"}
            {variant.stock_quantity === null
              ? ""
              : ` · ${variant.stock_quantity} in stock`}
          </li>
        ))}
      </ul>
    </div>
  );
}
