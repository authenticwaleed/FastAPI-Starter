import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
        <PageHeader
          title={`Welcome, ${firstName}`}
          description="One thing to do before anything else works."
        />

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
      <PageHeader
        title={`Welcome, ${firstName}`}
        description={`You are working in ${workspace.name}.`}
      />

      {workspace.status === "suspended" ? (
        // A warning rather than a refusal, and not a card. Suspension is
        // an operational decision, not a billing one, and reads keep
        // working throughout -- which is the whole shape of it in this API.
        // Red would tell a business its account had failed.
        <Alert variant="warning" role="status">
          <AlertTitle>This workspace is suspended</AlertTitle>
          <AlertDescription>
            Everything here can still be read. Nothing can be changed until
            it is lifted. Your data has not gone anywhere.
          </AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>
            <h2>Your inbox</h2>
          </CardTitle>
          <CardDescription>
            Customer conversations arrive here when somebody messages the
            connected number. You can also open one yourself from a contact.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button asChild size="sm">
            <Link href="/inbox">Open the inbox</Link>
          </Button>
          <Button asChild variant="outline" size="sm">
            <Link href="/contacts">Contacts</Link>
          </Button>
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
