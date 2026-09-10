"use client";

import { useActionState } from "react";

import { FieldError, FormError, SubmitButton } from "@/components/form";
import { NativeSelect } from "@/components/ui/native-select";
import { VariantFields } from "@/components/variant-fields";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { createProduct } from "@/lib/product-actions";
import type { FormState } from "@/lib/form-state";

/**
 * A new product.
 *
 * Only the name is required, which is the API's rule. Somebody sketching a
 * catalogue types six names and comes back for the prices, and a form
 * demanding a price and a SKU up front would stop them doing that.
 */
export function CreateProduct({ workspaceId }: { workspaceId: string }) {
  const [state, action] = useActionState<FormState, FormData>(createProduct, null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Add a product</h2>
        </CardTitle>
        <CardDescription>
          Only a name is needed. Everything else can wait.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <form action={action} className="grid max-w-2xl gap-4">
          <input type="hidden" name="workspace_id" value={workspaceId} />

          <FormError>{state?.error}</FormError>

          <div className="grid gap-2">
            <Label htmlFor="product-name">Name</Label>
            <Input id="product-name" name="name" maxLength={255} required />
            <FieldError>{state?.fields?.name}</FieldError>
          </div>

          <div className="grid gap-2">
            <Label htmlFor="product-description">Description</Label>
            <Textarea id="product-description" name="description" rows={3} />
            <FieldError>{state?.fields?.description}</FieldError>
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <div className="grid gap-2">
              <Label htmlFor="product-price">Price</Label>
              <Input
                id="product-price"
                name="price"
                inputMode="decimal"
                pattern="[0-9]*\.?[0-9]*"
                className="tabular-nums"
              />
              <FieldError>{state?.fields?.price}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="product-currency">Currency</Label>
              <Input
                id="product-currency"
                name="currency"
                maxLength={3}
                className="uppercase"
                placeholder="USD"
              />
              <FieldError>{state?.fields?.currency}</FieldError>
            </div>

            <div className="grid gap-2">
              <Label htmlFor="product-status">Status</Label>
              <NativeSelect
                id="product-status"
                name="status"
                defaultValue="active"
              >
                <option value="active">Active</option>
                <option value="draft">Draft</option>
                <option value="archived">Archived</option>
              </NativeSelect>
              <p className="text-muted-foreground text-xs">
                The assistant is told about active ones only.
              </p>
            </div>
          </div>

          <VariantFields />

          <SubmitButton className="w-fit">Add product</SubmitButton>
        </form>
      </CardContent>
    </Card>
  );
}
