import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { AddText } from "./add-text";
import { CreateSource } from "./create-source";
import { DocumentList } from "./document-list";
import { SearchPanel } from "./search-panel";
import { SourceList } from "./source-list";
import { UploadDocument } from "./upload-document";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import { listDocuments, listSources } from "@/lib/knowledge";
import type { Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Knowledge" };

const MAY_ADMINISTER = ["owner", "admin"];

/**
 * What the assistant knows.
 *
 * Reading is any member's; everything that changes the knowledge base is
 * admin work at the API, and searching sits between them -- an agent may
 * search, because checking what the assistant would be given is part of
 * answering a customer well.
 */
export default async function KnowledgePage({
  searchParams,
}: {
  searchParams: Promise<{ source?: string; page?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { source, page: rawPage } = await searchParams;
  const page = Math.max(1, Number(rawPage ?? 1) || 1);

  const [sources, documents, user, members] = await Promise.all([
    listSources(workspace.id),
    listDocuments(workspace.id, { page, sourceId: source ?? null }),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";
  const maySearch =
    mine !== undefined && ["owner", "admin", "agent"].includes(mine.role);

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Knowledge</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          What the assistant can draw on when it answers a customer.
        </p>
      </div>

      {maySearch ? <SearchPanel workspaceId={workspace.id} /> : null}

      <SourceList
        workspaceId={workspace.id}
        sources={sources.items}
        activeSourceId={source ?? null}
        canManage={administers}
      />

      <DocumentList
        documents={documents.items}
        total={documents.total}
        page={page}
        pageSize={documents.page_size}
        sourceId={source ?? null}
      />

      {administers ? (
        <div className="grid gap-6 lg:grid-cols-2 lg:items-start">
          <Card>
            <CardHeader>
              <CardTitle>
                <h2>Upload a file</h2>
              </CardTitle>
              <CardDescription>
                A PDF or plain text. The text is extracted and broken into
                passages the assistant can retrieve.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <UploadDocument workspaceId={workspace.id} sources={sources.items} />
            </CardContent>
          </Card>

          <AddText workspaceId={workspace.id} sources={sources.items} />
        </div>
      ) : null}

      {administers ? <CreateSource workspaceId={workspace.id} /> : null}
    </div>
  );
}
