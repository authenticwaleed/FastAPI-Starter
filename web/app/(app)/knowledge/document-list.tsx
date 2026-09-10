import Link from "next/link";

import { EmptyState } from "@/components/empty-state";
import { SectionHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Badge } from "@/components/ui/badge";
import type { DocumentStatus, KnowledgeDocument } from "@/lib/types";

const STATUS: Record<DocumentStatus, { label: string; variant: "secondary" | "outline" | "destructive" | "default" }> = {
  pending: { label: "Queued", variant: "outline" },
  processing: { label: "Processing", variant: "secondary" },
  ready: { label: "Ready", variant: "default" },
  failed: { label: "Failed", variant: "destructive" },
};

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium" });
}

/**
 * What is in the knowledge base.
 *
 * `chunk_count` is shown beside the status because it is the honest
 * measure: a document that is `ready` with no passages answers nothing,
 * and a screen showing only "ready" would say that was fine.
 */
export function DocumentList({
  documents,
  total,
  page,
  pageSize,
  sourceId,
}: {
  documents: KnowledgeDocument[];
  total: number;
  page: number;
  pageSize: number;
  sourceId: string | null;
}) {
  const scope = sourceId ? `&source=${sourceId}` : "";

  return (
    <section className="grid gap-3">
      <SectionHeader title={`Documents${sourceId ? " in this source" : ""}`} />

      {documents.length === 0 ? (
        <EmptyState title="Nothing here yet">
          Upload a file or write something, and the assistant will be able to
          answer from it.
        </EmptyState>
      ) : (
        <ul className="grid gap-2" data-testid="document-list">
          {documents.map((document) => (
            <li key={document.id} data-status={document.status}>
              <Link
                href={`/knowledge/${document.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 row"
              >
                <span className="min-w-0 flex-1 truncate text-sm">
                  {document.title}
                </span>

                <span className="text-muted-foreground text-xs tabular-nums">
                  {document.chunk_count} passage
                  {document.chunk_count === 1 ? "" : "s"}
                </span>

                <span className="text-muted-foreground text-xs">
                  {when(document.created_at)}
                </span>

                <Badge variant={STATUS[document.status].variant}>
                  {STATUS[document.status].label}
                </Badge>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <Pagination
        page={page}
        total={total}
        pageSize={pageSize}
        noun="documents"
        href={(to) => `/knowledge?page=${to}${scope}`}
      />
    </section>
  );
}
