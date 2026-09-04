import type { Metadata } from "next";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";

export const metadata: Metadata = { title: "Baton" };

/**
 * Where a signed-in person lands.
 *
 * There is nothing here yet, and saying so plainly beats an empty dashboard
 * with placeholder tiles: W2 brings workspaces and W3 brings the inbox, and
 * a chart of nothing would only have to be deleted.
 */
export default async function HomePage() {
  // Resolved again rather than passed down from the layout. Next dedupes a
  // fetch within one render pass, so this is the same request the layout
  // made, not a second one.
  const user = await api<User>("/auth/me");

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">
          Welcome, {user.name.split(" ")[0]}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          You are signed in. There is not much to do here yet.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Next: a workspace</CardTitle>
          <CardDescription>
            A workspace is one business — its inbox, its team, its catalogue and
            its plan. Creating and switching between them arrives with the next
            phase, and the inbox with the one after.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-muted-foreground text-sm">
          Signed in as {user.email}.
        </CardContent>
      </Card>
    </div>
  );
}
