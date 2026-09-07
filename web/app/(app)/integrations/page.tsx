import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { StorefrontPanel } from "./storefront-panel";
import { WhatsAppPanel } from "./whatsapp-panel";
import { api } from "@/lib/api";
import { readSubscription } from "@/lib/billing";
import { readStorefronts, readWhatsApp } from "@/lib/integrations";
import { admits, ceiling } from "@/lib/plans";
import type { Member, User } from "@/lib/types";
import { activeWorkspace } from "@/lib/workspace";

export const metadata: Metadata = { title: "Integrations" };

const MAY_ADMINISTER = ["owner", "admin"];

/**
 * The two things this product talks through.
 *
 * Both panels read their state and are shown to any member; only an owner
 * or an admin gets the controls. Only *connecting a storefront* is
 * plan-gated at the API — reading, syncing and disconnecting are not, and
 * neither are they here.
 */
export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: Promise<{ connected?: string; failed?: string }>;
}) {
  const workspace = await activeWorkspace();

  if (!workspace) redirect("/workspaces");

  const { connected, failed } = await searchParams;

  const [whatsapp, storefronts, current, user, members] = await Promise.all([
    readWhatsApp(workspace.id),
    readStorefronts(workspace.id),
    readSubscription(workspace.id),
    api<User>("/auth/me"),
    api<Member[]>(`/workspaces/${workspace.id}/members`),
  ]);

  const mine = members.find((member) => member.user_id === user.id);
  const administers =
    mine !== undefined &&
    MAY_ADMINISTER.includes(mine.role) &&
    workspace.status === "active";

  const numbers = ceiling(current, "whatsapp_numbers");

  return (
    <div className="grid gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Where your customers reach you, and where your catalogue comes from.
        </p>
      </div>

      {connected ? (
        <p
          className="rounded-md border px-3 py-2 text-sm"
          role="status"
          data-testid="install-outcome"
        >
          {connected} is connected. Its catalogue and orders will come across
          on the first sync.
        </p>
      ) : null}

      {failed ? (
        // A failed install has to land somewhere that explains itself. The
        // provider sends the browser back whatever happened, and a page
        // that only handled success would leave somebody staring at a
        // screen that had not changed.
        <p
          className="border-destructive/40 rounded-md border px-3 py-2 text-sm"
          role="alert"
          data-testid="install-outcome"
        >
          That shop was not connected. The approval may have been declined, or
          the link may have expired — starting again is safe.
        </p>
      ) : null}

      <WhatsAppPanel
        workspaceId={workspace.id}
        account={whatsapp}
        canManage={administers}
      />

      {whatsapp === null && numbers !== null ? (
        <p className="text-muted-foreground -mt-6 text-xs">
          Your plan allows {numbers} number{numbers === 1 ? "" : "s"}.
        </p>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        {storefronts.map(({ provider, account }) => (
          <StorefrontPanel
            key={provider}
            workspaceId={workspace.id}
            provider={provider}
            account={account}
            canManage={administers}
            included={admits(current, "ecommerce")}
          />
        ))}
      </div>
    </div>
  );
}
