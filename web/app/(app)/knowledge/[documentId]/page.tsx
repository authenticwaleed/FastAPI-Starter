import type { Metadata } from "next";
import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { DeleteDocument } from "./delete-document";
import { BackLink, PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { readDocument, readSource } from "@/lib/knowledge";
import { DOCUMENT_TONE } from "@/lib/tones";
import type { KnowledgeDocument, KnowledgeSource, Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Document" };

const MAY_ADMINISTER = ["owner", "admin"];

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default async function DocumentPage({
  params,
}: {
  params: Promise<{ documentId: string }>;
}) {
  const { documentId } = await params;
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  let document: KnowledgeDocument;

  try {
    document = await readDocument(workspace.id, documentId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();

    throw error;
  }

  const [user, members] = await Promise.all([
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  let source: KnowledgeSource | null = null;

  try {
    source = await readSource(workspace.id, document.knowledge_source_id);
  } catch (error) {
    // A document whose source has just been deleted is a race, not a
    // reason to fail the page. Its name is a nicety; the document is not.
    if (!(error instanceof ApiError)) throw error;
  }

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  return (
    <div className="grid gap-6">
      <PageHeader
        back={<BackLink href="/knowledge" label="Knowledge" />}
        title={document.title}
        description={
          <>
            {source ? (
              <Link
                href={`/knowledge?source=${source.id}`}
                className="hover:text-foreground underline underline-offset-4"
              >
                {source.name}
              </Link>
            ) : (
              "Its source has been removed"
            )}{" "}
            · added {when(document.created_at)}
          </>
        }
      />

      <dl className="grid gap-3 panel sm:grid-cols-3">
        <div className="grid gap-0.5">
          <dt className="text-muted-foreground text-xs uppercase">Status</dt>
          <dd>
            <StatusBadge
              tone={DOCUMENT_TONE[document.status]}
              status={document.status}
            >
              {document.status}
            </StatusBadge>
          </dd>
        </div>

        <div className="grid gap-0.5">
          <dt className="text-muted-foreground text-xs uppercase">Passages</dt>
          <dd className="text-sm tabular-nums">{document.chunk_count}</dd>
        </div>

        <div className="grid gap-0.5">
          <dt className="text-muted-foreground text-xs uppercase">Updated</dt>
          <dd className="text-sm">{when(document.updated_at)}</dd>
        </div>
      </dl>

      {document.status === "failed" && document.error ? (
        // The API puts plain words here rather than a trace, because a scan
        // with no text in it is the ordinary case and "it failed" would
        // send somebody looking for a bug rather than a different file.
        <Alert variant="destructive" role="status">
          <AlertDescription>{document.error}</AlertDescription>
        </Alert>
      ) : null}

      {document.status === "ready" && document.chunk_count === 0 ? (
        // Ready and empty is the quiet failure: nothing is wrong, and the
        // document answers nothing. A warning rather than an empty state --
        // there is something here, and it is not doing what was expected.
        <Alert variant="warning" role="status">
          <AlertDescription>
            This document produced no passages, so the assistant cannot
            retrieve anything from it. It may have been empty.
          </AlertDescription>
        </Alert>
      ) : null}

      {administers ? (
        <DeleteDocument workspaceId={workspace.id} document={document} />
      ) : null}
    </div>
  );
}
