import type { Metadata } from "next";

import { Fact, Facts } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { Badge } from "@/components/ui/badge";
import { readWorkspaceIntegrations } from "@/lib/console";
import { when } from "@/lib/console-labels";
import type { AdminIntegrations } from "@/lib/types";

export const metadata: Metadata = { title: "Connections" };

/**
 * What a business has connected, and how healthily.
 *
 * No credential of any kind, and not because this screen leaves them out:
 * both rows carry a provider token encrypted at rest, and the API's
 * response models have nowhere to put one. The support question is
 * whether the number is connected and working, never what the token is.
 *
 * "Connected in March and last synced in April" is what a stale catalogue
 * looks like from here, which is why the dates are as prominent as the
 * status.
 */
export default async function ConsoleWorkspaceIntegrationsPage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let integrations: AdminIntegrations;

  try {
    integrations = await readWorkspaceIntegrations(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Connections",
      missing: "No workspace exists with that id.",
    });
  }

  const { whatsapp, storefront } = integrations;

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title="Connections"
        back={{ href: `/console/workspaces/${workspaceId}`, label: "Workspace" }}
        description="Whether the provider is reachable, and nothing that would let anybody act as this business."
      />

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">WhatsApp</h2>

        {whatsapp === null ? (
          <p
            className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm"
            data-testid="no-whatsapp"
          >
            No number is connected.
          </p>
        ) : (
          <Facts>
            <Fact label="Status">
              <Badge
                variant={whatsapp.status === "connected" ? "secondary" : "destructive"}
              >
                {whatsapp.status}
              </Badge>
            </Fact>
            <Fact label="Number">{whatsapp.phone_number}</Fact>
            <Fact label="Provider">{whatsapp.provider}</Fact>
            {/* The provider's public handle for the number, which is what a
                ticket to Meta is opened with. An identifier, not a secret. */}
            <Fact label="Number id" mono>
              {whatsapp.external_phone_number_id}
            </Fact>
            <Fact label="Connected">{when(whatsapp.connected_at)}</Fact>
          </Facts>
        )}
      </section>

      <section className="grid gap-3">
        <h2 className="text-sm font-medium">Storefront</h2>

        {storefront === null ? (
          <p
            className="text-muted-foreground rounded-md border border-dashed px-4 py-6 text-center text-sm"
            data-testid="no-storefront"
          >
            No shop is connected.
          </p>
        ) : (
          <Facts>
            <Fact label="Status">
              <Badge
                variant={storefront.status === "connected" ? "secondary" : "destructive"}
              >
                {storefront.status}
              </Badge>
            </Fact>
            <Fact label="Shop">{storefront.shop_domain}</Fact>
            <Fact label="Provider">{storefront.provider}</Fact>
            <Fact label="Last synced">
              {/* Null until the first full read finishes. "Not synced yet"
                  and "synced in April" are different tickets, so the dash
                  the Fact renders for null is doing real work here. */}
              {storefront.last_synced_at ? when(storefront.last_synced_at) : null}
            </Fact>
            <Fact label="Connected">{when(storefront.created_at)}</Fact>
          </Facts>
        )}
      </section>
    </div>
  );
}
