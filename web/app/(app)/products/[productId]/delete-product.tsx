"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";

import { FormError } from "@/components/form";
import { Button } from "@/components/ui/button";
import { deleteProduct } from "@/lib/product-actions";
import type { FormState } from "@/lib/form-state";
import type { Product } from "@/lib/types";

function DeleteButton() {
  const { pending } = useFormStatus();

  return (
    <Button type="submit" variant="destructive" size="sm" disabled={pending}>
      Delete this product
    </Button>
  );
}

/**
 * Remove a product.
 *
 * No typed confirmation. Archiving is right there in the form above and is
 * what most people actually want -- it takes the product out of what the
 * assistant is told about while keeping it -- so this is the deliberate,
 * rarer choice rather than the one somebody reaches by accident.
 */
export function DeleteProduct({
  workspaceId,
  product,
}: {
  workspaceId: string;
  product: Product;
}) {
  const [state, action] = useActionState<FormState, FormData>(deleteProduct, null);

  return (
    <form action={action} className="grid gap-2 border-t pt-4">
      <input type="hidden" name="workspace_id" value={workspaceId} />
      <input type="hidden" name="product_id" value={product.id} />

      <FormError>{state?.error}</FormError>

      <p className="text-muted-foreground text-sm">
        Setting the status to archived hides it from the assistant and keeps
        it. Deleting does not keep it.
      </p>

      <DeleteButton />
    </form>
  );
}
