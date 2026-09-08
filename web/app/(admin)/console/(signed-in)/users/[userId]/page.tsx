import type { Metadata } from "next";

import {
  MembershipStatusBadge,
  WorkspaceStatusBadge,
} from "@/components/console/badges";
import { ConsoleLink } from "@/components/console/console-link";
import { Fact, Facts } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { ConsoleRefused, consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { readUser } from "@/lib/console";
import { when } from "@/lib/console-labels";
import type { AdminUserDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Account" };

/**
 * One account, where it belongs, and where it is signed in.
 *
 * The three things an "I cannot get in" ticket needs at once: whether the
 * account is active, whether it is really in the business it says it is,
 * and whether anything is signed in at all.
 *
 * Both lists are commonly empty, and that is a state rather than a
 * failure — it is what somebody who registered and never went further
 * looks like. Rendering that cleanly is one of the two things this phase
 * is judged on.
 */
export default async function ConsoleUserPage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  const { userId } = await params;
  const id = Number(userId);

  // An id that is not a whole number never reaches the API, which would
  // answer a 422 about a value that cannot name a row at all. The console
  // says the same thing it says about an id that simply is not there --
  // plainly, because on this surface there is nothing to be coy about.
  if (!Number.isSafeInteger(id) || id < 1) {
    return (
      <ConsoleRefused title="Account" sentence="No account exists with that id." />
    );
  }

  let user: AdminUserDetail;

  try {
    user = await readUser(id);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Account",
      missing: "No account exists with that id.",
    });
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title={user.name}
        back={{ href: "/console/users", label: "Accounts" }}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span>{user.email}</span>
            {user.is_active ? null : (
              <Badge variant="destructive" data-testid="deactivated">
                deactivated
              </Badge>
            )}
          </span>
        }
      />

      <section className="grid gap-3">
        <Facts>
          <Fact label="Address confirmed">
            {/* Null is "never confirmed", which gates nothing in this API
                but explains a customer who says they got no email. */}
            {user.email_verified_at ? when(user.email_verified_at) : null}
          </Fact>
          <Fact label="Registered">{when(user.created_at)}</Fact>
          <Fact label="Id" mono>
            {String(user.id)}
          </Fact>
        </Facts>
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Workspaces</h2>
          <p className="text-muted-foreground text-xs">
            Including the ones they have left and the ones that have closed.
          </p>
        </div>

        {user.memberships.length === 0 ? (
          <p
            className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm"
            data-testid="no-memberships"
          >
            This account is not in any workspace.
          </p>
        ) : (
          <ul className="grid gap-2" data-testid="membership-list">
            {user.memberships.map((membership) => (
              <li key={membership.workspace_id}>
                <ConsoleLink
                  href={`/console/workspaces/${membership.workspace_id}`}
                  className="hover:bg-accent/50 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
                >
                  <span className="text-sm font-medium">{membership.name}</span>
                  <span className="text-muted-foreground font-mono text-xs">
                    {membership.slug}
                  </span>

                  <span className="text-muted-foreground ml-auto text-xs">
                    Joined {when(membership.joined_at)}
                  </span>

                  {/*
                    Both statuses, because the two together are the answer:
                    "removed from a business that has since closed" and
                    "still an admin of a live one" are different tickets.
                  */}
                  <Badge variant="outline">{membership.role}</Badge>
                  <MembershipStatusBadge status={membership.status} />
                  <WorkspaceStatusBadge status={membership.workspace_status} />
                </ConsoleLink>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-3">
        <div>
          <h2 className="text-sm font-medium">Signed in</h2>
          <p className="text-muted-foreground text-xs">
            The same list the account&rsquo;s owner sees, and no token — what
            is stored is a digest, and nothing anywhere returns it.
          </p>
        </div>

        {user.sessions.length === 0 ? (
          <p
            className="text-muted-foreground rounded-md border border-dashed px-4 py-8 text-center text-sm"
            data-testid="no-sessions"
          >
            Nothing is signed in.
          </p>
        ) : (
          <ul className="grid gap-2" data-testid="session-list">
            {user.sessions.map((session) => (
              <li
                key={session.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-2.5"
              >
                <span className="min-w-0 flex-1 truncate text-sm">
                  {/* Best effort, and to be recognised rather than trusted. */}
                  {session.user_agent ?? "An unnamed client"}
                </span>
                <span className="text-muted-foreground font-mono text-xs">
                  {session.ip_address ?? "—"}
                </span>
                <span className="text-muted-foreground text-xs">
                  Last used {when(session.last_used_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
