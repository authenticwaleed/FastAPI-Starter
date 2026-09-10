import type { Metadata } from "next";

import { EndAccess } from "./end-access";
import { ConsoleLink } from "@/components/console/console-link";
import { ConsoleHeading } from "@/components/console/heading";
import { RequestAccess } from "@/components/console/request-access";
import { SupportWindow } from "@/components/console/support-window";
import { EmptyState } from "@/components/empty-state";
import { SectionHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { listSupportGrants } from "@/lib/console";
import { when } from "@/lib/console-labels";
import { ApiError } from "@/lib/errors";
import { supportWindowFor } from "@/lib/support-window";
import type { SupportGrant } from "@/lib/types";

export const metadata: Metadata = { title: "Support access" };

/**
 * Asking to read a customer's data, and the record of who has.
 *
 * Three things on one screen, and they are three ranks' worth of concern.
 * Anybody may ask, so the form is always here. Whoever holds a live window
 * sees what is left of it and can close it early. And administrators see
 * the history, which is the review surface for the power the other two
 * hand out -- support rank meets a sentence there instead, which is the
 * API's split rather than this screen's.
 *
 * The remaining time comes from what the API told this browser when the
 * grant was made, because listing grants is administrator rank and the
 * rank that reads customer data is not. See `lib/support-window.ts`.
 */
export default async function ConsoleSupportAccessPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  const supportWindow = await supportWindowFor(workspaceId);

  let grants: SupportGrant[] | null = null;
  let historyRefusal: string | null = null;

  try {
    grants = await listSupportGrants(workspaceId);
  } catch (error) {
    // Support rank cannot read this, and that is the point of the split
    // rather than a gap: the rank that answers tickets is the one that
    // needs access, and the rank that oversees them is the one that
    // reviews whether they should have had it.
    if (error instanceof ApiError && error.status === 403) {
      historyRefusal = error.sentence;
    } else if (error instanceof ApiError && error.status === 404) {
      historyRefusal = "No workspace exists with that id.";
    } else {
      throw error;
    }
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Support access"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="Nobody here has standing access to a customer's messages. A window is asked for, with a reason, and it closes on its own."
      />

      {supportWindow ? (
        <section className="grid gap-3">
          <SupportWindow
            workspaceId={workspaceId}
            expiresAt={supportWindow.expiresAt}
            now={supportWindow.now}
          />

          <div className="flex flex-wrap items-center gap-3">
            <ConsoleLink
              href={`/console/workspaces/${workspaceId}/conversations`}
              className="text-sm underline underline-offset-4"
            >
              Read their inbox
            </ConsoleLink>

            <EndAccess workspaceId={workspaceId} />
          </div>
        </section>
      ) : (
        <section className="grid gap-4">
          <SectionHeader title="Ask for a window" />
          <RequestAccess workspaceId={workspaceId} />
        </section>
      )}

      <section className="grid gap-3">
        <SectionHeader
          title="Who has been in this account"
          description="History as well as what is live. A list of only the live ones is almost always empty, and the question is about the past."
        />

        {historyRefusal !== null ? (
          <p className="text-muted-foreground text-sm" data-testid="history-refused">
            {historyRefusal}
          </p>
        ) : grants!.length === 0 ? (
          <EmptyState title="Nobody has ever asked to read this account" />
        ) : (
          <ul className="grid gap-2" data-testid="grant-list">
            {grants!.map((grant) => (
              <li
                key={grant.id}
                data-live={grant.live ? "" : undefined}
                className="grid gap-1 row"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-medium">{grant.staff_email}</span>

                  {/*
                    `live` comes from the API, worked out from both
                    timestamps and the clock. A grant that was revoked has
                    not expired, so a screen deciding this from
                    `expires_at` alone would show a closed window as open.
                  */}
                  {grant.live ? (
                    <Badge variant="default">live</Badge>
                  ) : grant.revoked_at ? (
                    <Badge variant="outline">ended early</Badge>
                  ) : (
                    <Badge variant="outline">expired</Badge>
                  )}

                  <span className="text-muted-foreground ml-auto text-xs">
                    {when(grant.created_at)} → {when(grant.expires_at)}
                  </span>
                </div>

                {/* The reason, which is also what the customer was told. */}
                <p className="text-muted-foreground text-sm">{grant.reason}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
