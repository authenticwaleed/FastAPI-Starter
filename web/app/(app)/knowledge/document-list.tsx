import Link from "next/link";

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
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const scope = sourceId ? `&source=${sourceId}` : "";

  return (
    <section className="grid gap-3">
      <h2 className="text-sm font-medium">
        Documents{sourceId ? " in this source" : ""}
      </h2>

      {documents.length === 0 ? (
        <p className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm">
          Nothing here yet.
        </p>
      ) : (
        <ul className="grid gap-2" data-testid="document-list">
          {documents.map((document) => (
            <li key={document.id} data-status={document.status}>
              <Link
                href={`/knowledge/${document.id}`}
                className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
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

      {lastPage > 1 ? (
        <nav className="flex items-center justify-between text-sm" aria-label="Pages">
          <span className="text-muted-foreground tabular-nums">
            Page {page} of {lastPage} · {total} in total
          </span>
          <span className="flex gap-3">
            {page > 1 ? (
              <Link
                href={`/knowledge?page=${page - 1}${scope}`}
                className="underline underline-offset-4"
              >
                Previous
              </Link>
            ) : null}
            {page < lastPage ? (
              <Link
                href={`/knowledge?page=${page + 1}${scope}`}
                className="underline underline-offset-4"
              >
                Next
              </Link>
            ) : null}
          </span>
        </nav>
      ) : null}
    </section>
  );
}
