/**
 * Reading the knowledge base.
 *
 * The queries only. What the limits are and how a file is described is
 * `lib/knowledge-limits.ts`, which is pure so the upload component -- which
 * has to run in the browser to report progress -- can import it.
 */

import { api } from "@/lib/api";
import type {
  DocumentStatus,
  KnowledgeDocument,
  KnowledgeSource,
  Page,
} from "@/lib/types";

export function listSources(workspaceId: string, page = 1) {
  return api<Page<KnowledgeSource>>(
    `/workspaces/${workspaceId}/knowledge/sources?page=${page}&page_size=100`,
  );
}

export function readSource(workspaceId: string, sourceId: string) {
  return api<KnowledgeSource>(
    `/workspaces/${workspaceId}/knowledge/sources/${sourceId}`,
  );
}

export function listDocuments(
  workspaceId: string,
  {
    page = 1,
    sourceId = null,
    status = null,
  }: { page?: number; sourceId?: string | null; status?: DocumentStatus | null } = {},
) {
  const query = new URLSearchParams({ page: String(page), page_size: "20" });

  if (sourceId) query.set("source_id", sourceId);
  if (status) query.set("status", status);

  return api<Page<KnowledgeDocument>>(
    `/workspaces/${workspaceId}/knowledge/documents?${query}`,
  );
}

export function readDocument(workspaceId: string, documentId: string) {
  return api<KnowledgeDocument>(
    `/workspaces/${workspaceId}/knowledge/documents/${documentId}`,
  );
}
