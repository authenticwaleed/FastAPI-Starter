"use server";

/**
 * Adding and editing the people a business talks to.
 *
 * A contact is always created deliberately. Opening a conversation names
 * one rather than describing one, because creating a contact by side
 * effect would be a second, quieter path into the contacts table with
 * none of its rules.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { Contact } from "@/lib/types";

export type { FormState };

function failure(error: unknown): FormState {
  if (error instanceof ApiError) {
    return {
      error: error.sentence,
      fields: error.fields,
      retryAfter: error.retryAfter ?? undefined,
    };
  }

  throw error;
}

/**
 * The fields a contact form sends.
 *
 * An empty string means "not given" rather than "set this to empty": the
 * API takes null for absent, and sending "" would store a blank name where
 * the person meant to leave it alone.
 */
function optional(form: FormData, name: string): string | null {
  const value = String(form.get(name) ?? "").trim();

  return value === "" ? null : value;
}

export async function createContact(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let contact: Contact;

  try {
    contact = await api<Contact>(`/workspaces/${workspaceId}/contacts`, {
      method: "POST",
      json: {
        // Normalised by the API, so a number typed with spaces here and
        // the same number arriving from WhatsApp are one contact.
        phone_number: form.get("phone_number"),
        name: optional(form, "name"),
        email: optional(form, "email"),
        status: form.get("status") || "lead",
        source: optional(form, "source"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/contacts");
  redirect(`/contacts/${contact.id}`);
}

export async function updateContact(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const contactId = String(form.get("contact_id") ?? "");

  try {
    await api<Contact>(`/workspaces/${workspaceId}/contacts/${contactId}`, {
      method: "PATCH",
      json: {
        phone_number: form.get("phone_number"),
        name: optional(form, "name"),
        email: optional(form, "email"),
        status: form.get("status"),
        source: optional(form, "source"),
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath(`/contacts/${contactId}`);
  revalidatePath("/contacts");
  // The inbox shows the contact's name on every row of theirs.
  revalidatePath("/inbox");

  return { done: true };
}
