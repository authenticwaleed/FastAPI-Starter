import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { CreateKey } from "./create-key";
import { KeyList } from "./key-list";
import { api } from "@/lib/api";
import { ApiError } from "@/lib/errors";
import { listApiKeys } from "@/lib/analytics";
import { readSubscription } from "@/lib/billing";
import { admits } from "@/lib/plans";
import type { Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "API keys" };

const MAY_ADMINISTER = ["owner", "admin"];

/**
 * The credentials a customer's own software uses.
 *
 * Admin work, and only *creating* is plan-gated. Listing and revoking stay
 * available whatever the plan, because a workspace that loses API access
 * still has live keys and must be able to turn them off.
 */
export default async function ApiKeysPage() {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const [current, user, members] = await Promise.all([
    readSubscription(workspace.id),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  // The list itself is admin-only at the API. Read after the role is
  // known, so a member who may not see it gets a sentence rather than an
  // unhandled 403 -- which renders as "this page could not load", the
  // least useful thing a screen can say about a permission.
  let keys: Awaited<ReturnType<typeof listApiKeys>> = [];
  let mayList = true;

  try {
    keys = await listApiKeys(workspace.id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      mayList = false;
    } else {
      throw error;
    }
  }

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">API keys</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          For reaching {workspace.name} from your own software.
        </p>
      </div>

      {mayList ? (
        <KeyList workspaceId={workspace.id} keys={keys} canManage={administers} />
      ) : (
        <p className="text-muted-foreground text-sm" data-testid="not-permitted">
          Only an owner or an admin can see this workspace&rsquo;s keys.
        </p>
      )}

      {administers ? (
        <CreateKey
          workspaceId={workspace.id}
          included={admits(current, "api_access")}
        />
      ) : null}
    </div>
  );
}
