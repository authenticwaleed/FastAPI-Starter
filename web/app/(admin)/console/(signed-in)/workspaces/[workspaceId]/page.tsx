import type { Metadata } from "next";

import { WorkspaceStatusBadge } from "@/components/console/badges";
import { ConsoleLink } from "@/components/console/console-link";
import { Fact, Facts } from "@/components/console/facts";
import { ConsoleHeading } from "@/components/console/heading";
import { consoleRefusal } from "@/components/console/refusal";
import { StatRow, StatTile } from "@/components/charts/stat-tile";
import { SectionHeader } from "@/components/page-header";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { readWorkspace } from "@/lib/console";
import { day, when } from "@/lib/console-labels";
import type { AdminWorkspaceDetail } from "@/lib/types";

export const metadata: Metadata = { title: "Workspace" };

/** The five reads this screen deliberately does not make for you. */
const SECTIONS = [
  { slug: "members", title: "Members", body: "Who is on the team, and as what." },
  {
    slug: "subscription",
    title: "Subscription",
    body: "What the provider says, and what this workspace actually gets.",
  },
  { slug: "usage", title: "Usage", body: "Against the period it is billed for." },
  {
    slug: "integrations",
    title: "Connections",
    body: "WhatsApp and the storefront, without any credential.",
  },
  {
    slug: "audit",
    title: "Their own log",
    body: "What this business's people did to it.",
  },
  {
    slug: "support-access",
    title: "Support access",
    body: "Ask for a window on their actual data, and see who has had one.",
  },
  {
    slug: "conversations",
    title: "Their inbox",
    body: "Their customers' own messages. Only with a live window, and every thread opened is recorded.",
  },
  {
    slug: "lifecycle",
    title: "Lifecycle",
    body: "Suspend, close, restore, and the date their records go. Administrators and above.",
  },
];

/**
 * One business, in as much detail as metadata allows.
 *
 * One read, and this is the screen where that restraint is a design
 * decision rather than an omission. Members, subscription, usage,
 * connections and the business's own audit log are five further endpoints,
 * and each one writes its own row to the platform log naming this
 * workspace. A detail page that loaded all five to fill in some tabs would
 * record a support engineer as having read a customer's whole account when
 * all they did was check whether it was suspended.
 *
 * So they are five links, and each is paid for by somebody opening it.
 *
 * A 404 here means no such workspace and says exactly that -- the opposite
 * of the tenant surface, where the same code covers "you are not a member"
 * as well and must stay ambiguous (§3.2).
 */
export default async function ConsoleWorkspacePage({
  params,
}: {
  params: Promise<{ workspaceId: string }>;
}) {
  const { workspaceId } = await params;

  let workspace: AdminWorkspaceDetail;

  try {
    workspace = await readWorkspace(workspaceId);
  } catch (error) {
    return consoleRefusal(error, {
      title: "Workspace",
      missing: "No workspace exists with that id.",
    });
  }

  return (
    <div className="grid gap-8">
      <ConsoleHeading
        title={workspace.name}
        back={{ href: "/console/workspaces", label: "Workspaces" }}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{workspace.slug}</span>
            <WorkspaceStatusBadge status={workspace.status} />
            {/*
              The plan that applies right now, after overrides and status --
              never `subscription.plan`, which is what is being paid for and
              routinely disagrees (§3.4). The subscription screen shows the
              other one, beside this one, where the gap is the answer.
            */}
            <Badge variant="outline">{workspace.plan}</Badge>
          </span>
        }
      />

      {workspace.erase_after ? (
        // A warning rather than a refusal. Nothing has gone yet, and a
        // support engineer reading this needs the date, not an alarm.
        <Alert variant="warning" role="status" data-testid="erase-after">
          <AlertDescription>
            This workspace is closed. Its records are due to be destroyed on{" "}
            {day(workspace.erase_after)}, and after that there is nothing to
            restore.
          </AlertDescription>
        </Alert>
      ) : null}

      <section className="grid gap-3">
        <SectionHeader title="How much it holds" />
        <StatRow>
          <StatTile label="Members" value={workspace.counts.members} />
          <StatTile label="Contacts" value={workspace.counts.contacts} />
          <StatTile label="Conversations" value={workspace.counts.conversations} />
          <StatTile label="Messages" value={workspace.counts.messages} />
        </StatRow>
        <p className="text-muted-foreground text-xs">
          {workspace.counts.knowledge_documents.toLocaleString()} knowledge
          documents. Counts, unless somebody asks for a window on the
          messages behind them — which the business sees them ask for.
        </p>
      </section>

      <section className="grid gap-3">
        <SectionHeader title="The account" />
        <Facts>
          <Fact label="Owner">{workspace.owner_email}</Fact>
          <Fact label="Time zone">{workspace.timezone}</Fact>
          <Fact label="Currency">{workspace.default_currency}</Fact>
          <Fact label="Created">{when(workspace.created_at)}</Fact>
          <Fact label="Last changed">{when(workspace.updated_at)}</Fact>
          <Fact label="Id" mono>
            {workspace.id}
          </Fact>
        </Facts>
      </section>

      <section className="grid gap-3">
        <SectionHeader
          title="Look further"
          description="Each of these is a separate read, and each is recorded. Nothing below has been loaded."
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {SECTIONS.map((section) => (
            <ConsoleLink
              key={section.slug}
              href={`/console/workspaces/${workspace.id}/${section.slug}`}
              className="hover:bg-accent/50 grid content-start gap-1 panel"
            >
              <span className="text-sm font-medium">{section.title}</span>
              <span className="text-muted-foreground text-xs">{section.body}</span>
            </ConsoleLink>
          ))}

          {/*
            Admin rank at the API, and shown to everybody: knowing the
            rank would cost a call on every screen. Support meets a
            sentence there rather than a hidden door.
          */}
          <ConsoleLink
            href={`/console/audit?workspace_id=${workspace.id}`}
            className="hover:bg-accent/50 grid content-start gap-1 panel"
          >
            <span className="text-sm font-medium">What staff did here</span>
            <span className="text-muted-foreground text-xs">
              Our log rather than theirs. Administrators and above.
            </span>
          </ConsoleLink>
        </div>
      </section>
    </div>
  );
}
