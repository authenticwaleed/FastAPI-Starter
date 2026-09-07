"use server";

/**
 * Filling and emptying the knowledge base.
 *
 * Everything here except searching is admin work at the API. Uploading is
 * not here at all: a file has to go straight from the browser to the relay
 * so its progress can be watched, and a server action can neither report
 * progress nor carry ten megabytes past Next's own body limit.
 */

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import type { FormState } from "@/lib/form-state";
import type { KnowledgeDocument, KnowledgeSource, SearchResult } from "@/lib/types";

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

export async function createSource(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  try {
    await api<KnowledgeSource>(`/workspaces/${workspaceId}/knowledge/sources`, {
      method: "POST",
      json: {
        name: form.get("name"),
        // Describes what will go in it and does not restrict what can. A
        // source named `file` holding typed text is a labelling mistake,
        // not a corrupt state, which is why the API does not enforce it
        // and this does not either.
        source_type: form.get("source_type") || "text",
      },
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/knowledge");

  return { done: true };
}

/**
 * Remove a source, and everything retrievable from it.
 *
 * Actually deleted, not marked. Knowledge a business has withdrawn has to
 * stop being able to appear in an answer to one of its customers, and the
 * screen says so before the button rather than after.
 */
export async function deleteSource(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const sourceId = String(form.get("source_id") ?? "");

  if (form.get("confirm") !== form.get("name")) {
    return { error: "Type the source's name to confirm." };
  }

  try {
    await api(`/workspaces/${workspaceId}/knowledge/sources/${sourceId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/knowledge");

  return { done: true };
}

export async function addText(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let document: KnowledgeDocument;

  try {
    document = await api<KnowledgeDocument>(
      `/workspaces/${workspaceId}/knowledge/documents`,
      {
        method: "POST",
        json: {
          knowledge_source_id: form.get("knowledge_source_id"),
          title: form.get("title"),
          content: form.get("content"),
        },
      },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/knowledge");
  redirect(`/knowledge/${document.id}`);
}

/**
 * A question and its answer, as a pair.
 *
 * Its own endpoint rather than text somebody formatted, because the
 * question is part of what gets embedded -- which is what makes a customer
 * asking it in their own words find the answer. Flattening it at the
 * client would leave every dashboard inventing its own formatting, and
 * that formatting would become what the assistant retrieves.
 */
export async function addFaq(_: FormState, form: FormData): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");

  let document: KnowledgeDocument;

  try {
    document = await api<KnowledgeDocument>(
      `/workspaces/${workspaceId}/knowledge/documents/faq`,
      {
        method: "POST",
        json: {
          knowledge_source_id: form.get("knowledge_source_id"),
          question: form.get("question"),
          answer: form.get("answer"),
        },
      },
    );
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/knowledge");
  redirect(`/knowledge/${document.id}`);
}

export async function deleteDocument(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const documentId = String(form.get("document_id") ?? "");

  try {
    await api(`/workspaces/${workspaceId}/knowledge/documents/${documentId}`, {
      method: "DELETE",
    });
  } catch (error) {
    return failure(error);
  }

  revalidatePath("/knowledge");
  redirect("/knowledge");
}

/**
 * Ask the knowledge base what the assistant would be given.
 *
 * The same retrieval the assistant runs, which is the point of exposing it
 * at all: a pilot can see what a question actually returns before trusting
 * it with a customer. Rate limited, so the screen submits rather than
 * searching per keystroke.
 */
export async function searchKnowledge(
  _: FormState,
  form: FormData,
): Promise<FormState> {
  const workspaceId = String(form.get("workspace_id") ?? "");
  const query = String(form.get("query") ?? "").trim();

  if (!query) return { fields: { query: "Ask something first." } };

  let result: SearchResult;

  try {
    result = await api<SearchResult>(
      `/workspaces/${workspaceId}/knowledge/search`,
      { method: "POST", json: { query, limit: 5 } },
    );
  } catch (error) {
    return failure(error);
  }

  return { done: true, search: result };
}
