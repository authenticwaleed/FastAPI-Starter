import type { Metadata } from "next";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Baton" };

/**
 * Where a signed-in person lands.
 *
 * Two states and no dashboard: somebody with no workspace is asked to make
 * one, and somebody with one is told what is coming. A grid of placeholder
 * tiles would only have to be deleted when W3 brings the inbox that
 * belongs here.
 */
export default async function HomePage() {
  // Resolved again rather than passed down from the layout. Next dedupes a
  // fetch within one render pass, so this is the same request the layout
  // made, not a second one.
  const [user, workspace] = await Promise.all([
    api<User>("/auth/me"),
    activeWorkspace(),
  ]);

  const firstName = user.name.split(" ")[0];

  if (!workspace) {
    return (
      <div className="grid gap-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Welcome, {firstName}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">
            One thing to do before anything else works.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>
              <h2>Create a workspace</h2>
            </CardTitle>
            <CardDescription>
              A workspace is one business — its inbox, its team, its catalogue
              and its plan. Everything in Baton belongs to one, so this comes
              first.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button asChild>
              <Link href="/workspaces">Create a workspace</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome, {firstName}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          You are working in {workspace.name}.
        </p>
      </div>

      {workspace.status === "suspended" ? (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle>
              <h2>This workspace is suspended</h2>
            </CardTitle>
            <CardDescription>
              {/*
                An operational decision, not a billing one, and the copy must
                not imply otherwise. Reads keep working throughout, which is
                the whole shape of a suspension in this API.
              */}
              Everything here can still be read. Nothing can be changed until
              it is lifted. Your data has not gone anywhere.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Next: the inbox</h2>
          </CardTitle>
          <CardDescription>
            Conversations, contacts and the assistant arrive in the next
            phase. Until then, this workspace can be renamed, its team is
            managed from the API, and your account settings are below.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild variant="outline" size="sm">
            <Link href={`/workspaces/${workspace.id}/settings`}>
              Workspace settings
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href="/account">Your account</Link>
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
