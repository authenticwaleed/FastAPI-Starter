import type { Metadata } from "next";
import Link from "next/link";

import { CreateWorkspace } from "./create-workspace";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { activeWorkspace, listWorkspaces } from "@/lib/workspace";

export const metadata: Metadata = { title: "Workspaces" };

/**
 * Every business this person works in, and a form to add another.
 *
 * Cancelled workspaces are not here, and that is the API's doing rather
 * than a filter: on the tenant surface a closed workspace answers 404
 * everywhere, so this list cannot show one. The platform console can, which
 * is where a business asking for one back is dealt with.
 */
export default async function WorkspacesPage() {
  const [workspaces, active] = await Promise.all([listWorkspaces(), activeWorkspace()]);

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Workspaces</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          A workspace is one business. Everything in Baton belongs to one.
        </p>
      </div>

      {workspaces.length > 0 ? (
        <ul className="grid gap-3">
          {workspaces.map((workspace) => (
            <li key={workspace.id}>
              <Card className="group">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <h2>{workspace.name}</h2>
                    {workspace.id === active?.id ? (
                      <Badge variant="secondary">Current</Badge>
                    ) : null}
                    {workspace.status !== "active" ? (
                      <Badge variant="outline" className="uppercase">
                        {workspace.status}
                      </Badge>
                    ) : null}
                  </CardTitle>
                  <CardDescription className="font-mono text-xs">
                    {workspace.slug} · {workspace.timezone} ·{" "}
                    {workspace.default_currency}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Link
                    href={`/workspaces/${workspace.id}/settings`}
                    className="text-sm underline underline-offset-4"
                  >
                    Settings
                  </Link>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-muted-foreground text-sm">
          You are not in any workspace yet.
        </p>
      )}

      <CreateWorkspace />
    </div>
  );
}
