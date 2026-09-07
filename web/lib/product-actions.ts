"use server";

/**
 * Changing the catalogue.
 *
 * Admin work at the API, all of it. An agent reads the catalogue -- they
 * need it to answer a customer -- and does not edit it.
 *
 * Money is sent as the string it was typed as. Nothing here parses an
 * amount: `"19.99"` through `Number` is 19.989999999999998, and a total
 * built from three of those is wrong in a way nobody finds afterwards.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Product } from "@/lib/types";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      code: error.code,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  throw error;
}

/** An empty field means "not given", which the API takes as null. */
function optional(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();

  return value === "" ? null : value;
}

/**
 * The variants submitted with a product.
 *
 * Supplying `variants` replaces the set entirely, which is the API's rule
 * and a deliberate one: merging would need a way to match an incoming
 * variant to an existing row, and no rule covers the hand-entered ones
 * that have neither an external id nor a SKU. The form says so.
 */
function variantsFrom(form: FormData) {
  const titles = form.getAll("variant_title");
  const skus = form.getAll("variant_sku");
  const prices = form.getAll("variant_price");
  const stock = form.getAll("variant_stock");

  return titles
    .map((title, index) => ({
      title: String(title).trim() || null,
      sku: String(skus[index] ?? "").trim() || null,
      // The string, untouched. The API takes a decimal and this is one.
      price: String(prices[index] ?? "").trim() || null,
      stock_quantity:
        String(stock[index] ?? "").trim() === ""
          ? // Null is "this business does not track stock", which is a
            // different answer from zero and has to stay one.
            null
          : Number(stock[index]),
    }))
    .filter(
      (variant) =>
        variant.title !== null || variant.sku !== null || variant.price !== null,
    );
}

export async function createProduct(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let product: Product;

  try {
    product = await api<Product>(`/workspaces/${workspaceId}/products`, {
      method: "POST",
      json: {
        name: form.get("name"),
        description: optional(form, "description"),
        status: form.get("status") || "active",
        price: optional(form, "price"),
        currency: optional(form, "currency"),
        variants: variantsFrom(form),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/products");
  redirect(`/products/${product.id}`);
}

export async function updateProduct(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const productId = String(form.get("product_id") ?? "");

  try {
    await api<Product>(`/workspaces/${workspaceId}/products/${productId}`, {
      method: "PATCH",
      json: {
        name: form.get("name"),
        description: optional(form, "description"),
        status: form.get("status"),
        price: optional(form, "price"),
        currency: optional(form, "currency"),
        variants: variantsFrom(form),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/products/${productId}`);
  revalidatePath("/products");

  return { done: true };
}

export async function deleteProduct(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const productId = String(form.get("product_id") ?? "");

  try {
    await api(`/workspaces/${workspaceId}/products/${productId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/products");
  redirect("/products");
}
